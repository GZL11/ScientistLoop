# Consolidated Failure Analysis: 12 Optimization Patches

## 1. Hazmat Road Restrictions Incompletely Enforced [7/12 runs]

**Patches:** #2, #6, #7, #8, #9, #10 (and partially #4)

### Root Cause
Solvers consistently under-enforced edge-level road restrictions in hazmat VRP:
- **Hardcoded single restriction type**: only `blacklist_explosive` was filtered; `school_zone`, `tunnel_ban`, `residential_restricted`, `weight_limit`, etc. were ignored or treated as soft cost multipliers (#2, #8, #9).
- **Directional lookup**: restrictions stored as `(from, to)` only, allowing reverse traversal `(to, from)` to bypass the ban (#6, #10).
- **Inconsistent matrix masking**: `INF` applied to one cost matrix but not all (distance vs. risk vs. combined), so Dijkstra over the unmasked matrix re-introduced banned edges via intermediate hops (#10).
- **Wrong scope assumption**: bans tied to vehicle ID whitelists rather than cargo class, or assumed class-specific when actually applies to all hazmat (#7, #9).
- **Soft fallback emitted infeasible edges**: "pick closest anyway, flag as violation" output banned edges (#7).

### Consolidated Fix
1. **Enumerate all restriction types from the CSV**; never hardcode a single keyword. Build a mapping `FORBIDDEN_BY_TYPE[restriction_type] → set(hazmat_classes)`. Default unknown types to "ban for all hazmat classes."
2. **Treat restrictions as undirected**: store as `frozenset({u,v})` and check both directions.
3. **Mask ALL cost matrices uniformly**: distance, risk, and any combined matrix used by any Dijkstra/TSP call must set forbidden arcs to `INF` per hazmat class.
4. **Filter at every stage**: greedy insertion, 2-opt, or-opt, relocate, swap — not just final validation. Reject any move introducing a forbidden edge before computing cost.
5. **Validate the full hop-by-hop expanded path** (including intermediate Dijkstra hops) against the raw restriction set; emit the full expanded sequence so optimizer and evaluator see identical edges.
6. **Never emit "flag as violation" fallbacks** — infeasible output scores 0. If no path exists, reroute via Dijkstra on the class-restricted subgraph or split the route.

---

## 2. Single-Hazmat-Class-per-Vehicle Constraint Violated [4/12 runs]

**Patches:** #2, #3, #5 (and partially #4)

### Root Cause
Solvers conflated **eligibility** (`vehicle.allowed_classes` certification) with **simultaneous compatibility** (what may be co-loaded on one trip). The validator checked `classes_needed.issubset(vehicle.allowed_classes)` and permitted vehicles certified for multiple classes to carry a mix, but ADR/DOT-style segregation requires only ONE hazmat class per vehicle per trip regardless of certification breadth.

### Consolidated Fix
Distinguish two separate checks; enforce segregation **before** the eligibility check:
```python
classes_in_route = {points[k].hazmat_class for k in route[1:-1]}
if len(classes_in_route) > 1:
    return False, "Multiple hazmat classes co-loaded"
if not classes_in_route.issubset(vehicle.allowed_classes):
    return False, "Vehicle not certified for class"
```
Architecturally: **partition customers by `hazmat_class` into disjoint pools first**, then run VRP routing within each pool independently. Never merge routes across classes (unless the problem explicitly defines a multi-class certification level).

---

## 3. Multi-Instance Output Schema Not Honored [2/12 runs]

**Patches:** #11, #12

### Root Cause
For benchmarks named `*_multi` (e.g., `wb_tsp_multi`), the evaluator expects 128 tours in a single `solution.json`, but the solver hardcoded a single input file path and emitted one tour. The multi-instance structure (rows grouped by `instance_id`, or multiple instance files in a directory) was never enumerated.

### Consolidated Fix
1. **Enumerate the dataset first**: list all instance files or group by `instance_id`; assert the count matches the spec before solving.
2. **Loop over every instance**, allocating a fixed per-instance time budget (e.g., 10–30s each for 128×500 TSP). Use vectorized NumPy distance matrices.
3. **Emit the exact expected schema**: `{"tours": [...]}` or `{instance_id: tour}` per the evaluator. Tours are 0-indexed permutations of length N with **no repeated start city**.
4. **Validate before submit**: `len(solution) == num_instances` and each tour `set(tour) == set(range(N))`.
5. Ignore per-instance diagnostic side files — only `solution.json` is read.

---

## 4. Hard Constraints Missing from Route Builder [2/12 runs]

**Patches:** #4 (and overlaps with #1 on local search)

### Root Cause
Route construction consisted of `[depot] + customers + [depot]` with no edge feasibility check, no risk-cap accumulation, and no distance ordering. Helpers like `can_use_edge` existed but were never called during construction; constraints were checked only post-hoc, by which point the greedy ordering had already locked in violations.

### Consolidated Fix
Encode **all** constraints inside the route builder, not at validation:
1. Per-step edge feasibility check against the class-filtered graph.
2. Maintain `cum_risk` while inserting; reject insertions exceeding the cap (e.g., 1500). Split across vehicles if needed.
3. Use Dijkstra on the **restricted subgraph** for inter-customer distances — direct lookups returning a `9999` default inflate cost and miss legal multi-hop routes.
4. Order customers via nearest-neighbor + 2-opt on the restricted graph, not CSV order.

---

## 5. Wrong Optimization Objective / Weak Local Search [1/12 runs]

**Patch:** #1

### Root Cause (brief)
K-means clustering on raw coordinates plus a 10-neighbor 2-opt window produced tangled tours with hull intrusions and segment crossings. Local search optimized time variance (load balance) instead of distance, and inter-route moves used `append` instead of cheapest insertion.

### Fix Summary
- Use sweep/angular clustering, not K-means, for spatial cohesion.
- Optimize total travel distance; balance is secondary.
- Run full 2-opt/Or-opt to convergence, restricted to k=20 nearest neighbors.
- Use cheapest-insertion (never `append`) for inter-route moves.
- Reject moves that cross another route's convex hull.

*(Task-specific to spatial-penalty CVRP evaluators; flagged for awareness.)*

---

## Cross-Cutting Meta-Lessons

These patterns recur across multiple groups and warrant general policy:

1. **Validator parity**: the solver's internal validator must replicate the evaluator's checks **exactly** — iterate every constraint type from the data file, not just a hardcoded subset. A constraint not enumerated in code is a constraint silently violated. (Patches #2, #4, #7, #8, #9)

2. **Hard constraints in construction, not just validation**: filter forbidden moves *during* greedy/local search rather than post-hoc rejecting whole routes. Mask cost matrices with `INF` so the optimizer never proposes infeasible moves. (Patches #4, #6, #8, #9, #10)

3. **Read schema/scope from data, not assumptions**: don't hardcode which IDs/classes a restriction applies to; parse the `restriction_type` and scope columns directly. (Patches #7, #8, #9)

4. **Match the evaluator's output schema before optimizing for cost**: a near-optimal solution with wrong format scores 0. Confirm instance count, file name, key structure, and indexing convention up front. (Patches #9, #11, #12)