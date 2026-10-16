# Routing Build-Phase Algorithm Playbook

## Primary 1: `tsp_local_search`

**Applicable cases:** `wb_tsp_1000`, `wb_tsp_multi`

### Baseline

- **Starter algorithm:** Precompute full pairwise distance matrix (float32, O(n²) memory) → single-start nearest-neighbor (NN) constructive seed → 2-opt local search with O(1) delta evaluation (`d[i-1,i]+d[j,j+1]` vs `d[i-1,j]+d[i,j+1]`) → output permutation tour returning to start.
- **Scale:** n≈1000 for `wb_tsp_1000`; ~128 instances for `wb_tsp_multi` (loop with per-instance budget).
- **Observed score range:** A single-start NN + plain 2-opt typically lands ~5–10% above optimal; this is the safe feasibility-first baseline.
- **Reference code template:** see `tsp_local_search` skeleton — distance matrix → NN seed → 2-opt sweep with delta cost → tour output. Match evaluator's distance metric and rounding exactly.

**Core constraints to honor in baseline:**
- Hamiltonian cycle (every city once, returns to start). 2-opt segment reversal preserves this by construction — no repair needed.
- Multi-instance cases must enumerate every `instance_id` and emit one tour per instance keyed to evaluator schema. Never hardcode a single input file.
- Use the same distance formula and rounding as the evaluator.

### Improvement 1: Multi-start NN + Or-opt finishing pass

- **When to switch:** Baseline plateaus and there's headroom before the time budget; applies to both `wb_tsp_1000` and each instance of `wb_tsp_multi`.
- **Core idea:** Run NN from 10–20 different seed cities, keep the best seed, then alternate 2-opt sweeps with Or-opt (relocate chains of length 1, 2, 3) until no improving move is found.
- **Expected gain:** Typically closes 30–60% of the gap to optimal vs single-start 2-opt.
- **Cost:** Linear in number of starts; Or-opt is O(n²) per sweep but converges quickly after 2-opt.

### Improvement 2: Neighbor-list pruning for n≈1000

- **When to switch:** When 2-opt sweeps become the time bottleneck (n ≥ ~500). Essential for `wb_tsp_1000`.
- **Core idea:** Precompute k-nearest neighbors (k≈20) per city. In 2-opt and Or-opt, only consider partner indices `j` among the k-nearest of `i`. Combined with O(1) delta evaluation, this turns each sweep from O(n²) to O(n·k).
- **Expected gain:** 20–50× speedup per sweep, enabling many more restart × refinement cycles within the budget; usually translates to a further 1–3% tour-length reduction.
- **Cost:** O(n²) one-time precomputation of neighbor lists; modest memory.

---

## Primary 2: `cvrp_cluster_then_route`

**Applicable cases:** `wb_city_delivery_routing`, `wb_hazmat_transport`

### Baseline

- **Starter algorithm:** Demand-weighted, capacity-constrained K-means on (lon,lat) with K = number of vehicles → assign each cluster to a vehicle (respecting eligibility) → per-cluster TSP via NN + 2-opt with O(1) delta → boundary-customer rebalancing to nearest feasible cluster when capacity violated → travel time computed with the case's prescribed speed/service-time model used uniformly in construction, delta evaluation, and final cost.
- **Scale:** Tens to a few hundred customers; K small (single-digit to low double-digit vehicles).
- **Observed score range:** Cluster-first/route-second produces feasible solutions but is highly sensitive to side-constraint enforcement. On `wb_hazmat_transport`, traces show that mishandling hazmat segregation or road restrictions drops the score to 0 (infeasible).
- **Reference code template:** see `cvrp_cluster_then_route` skeleton — capacitated K-means → per-cluster NN + 2-opt/Or-opt → rebalance → cost with the instruction's speed model.

**Core constraints to honor in baseline:**
- Per-vehicle load ≤ capacity; each customer served exactly once; route starts and ends at depot; route count ≤ available vehicles.
- All side constraints (segregation, edge bans, max duration, rest) enforced **inside every move operator**, not only at final validation.
- Travel time uses the speed model and service times the instruction specifies, applied uniformly across construction, local search, and reporting.

### Case-specific extension wiring

**`wb_city_delivery_routing`:**
- `dual_speed_travel_time`: 70 km/h on depot↔customer trunk legs, 35 km/h customer↔customer, +120 s service time per visit. Use this `travel_time(u,v)` everywhere — construction, 2-opt delta, final cost.
- `workload_balance`: add λ·(max_route_duration − min_route_duration) to objective; weight K-means points by demand; cross-route relocate/swap accepted only if it reduces max route duration.
- `spatial_compactness`: K-means on coordinates for convex clusters; rebalance always to geographically nearest feasible cluster; cross-route 2-opt* between geographically adjacent clusters only.

**`wb_hazmat_transport`:** This case has the highest failure rate in traces. All four extensions are mandatory:
- `single_class_per_vehicle_segregation`: partition customers by `hazmat_class` into disjoint pools BEFORE routing; route each pool independently. Enforce two separate predicates: `len({p.hazmat_class for p in route}) == 1` AND `that_class ∈ vehicle.allowed_classes`. Never co-load classes even if the vehicle is certified for several.
- `edge_level_road_restrictions`: load ALL restriction types from data (no hardcoding `blacklist_explosive` or any single keyword); store as undirected `frozenset({u,v})`; build per-class `FORBIDDEN[hazmat_class]`; mask every cost/risk/time matrix with INF uniformly; check forbidden edges inside every move operator (greedy insert, 2-opt, Or-opt, relocate, swap); expand Dijkstra hop-by-hop and re-validate the full path; never emit "flag as violation" fallbacks — split the route or detour.
- `max_route_duration`: track cumulative drive + service + rest time; reject any insertion/move whose new duration exceeds 10 h; close routes at the limit during construction.
- `mandatory_driver_rest`: per-route odometer; whenever cumulative driven distance crosses a 160 km boundary, add 30 min rest before the next leg; include rest cost in delta evaluation; re-check 10 h cap after every move.

### Improvement 1: Cross-route relocate/swap with constraint-aware delta

- **When to switch:** After per-cluster 2-opt converges and routes are individually locally optimal but globally unbalanced or have boundary inefficiencies.
- **Core idea:** Add cross-route operators (relocate one customer, swap two customers, 2-opt*) that evaluate the move's full delta — including capacity, segregation, forbidden edges, max duration, and rest cost — before accepting. For `wb_city_delivery_routing` the acceptance rule includes the workload-balance penalty; for `wb_hazmat_transport` the acceptance rule rejects any move that introduces a forbidden edge or co-loads classes.
- **Expected gain:** Significant on `wb_city_delivery_routing` (better balance + shorter total time); on `wb_hazmat_transport` mostly recovers feasibility-aware optimality after segregation forces narrow per-class pools.
- **Cost:** Each move now requires checking side constraints — keep checks O(1) by precomputing per-route load, duration, and a frozenset of forbidden edges to test against.

### Improvement 2: Iterated local search with capacitated K-means restarts

- **When to switch:** Baseline + cross-route operators converge but the score is still gated by an unlucky initial clustering (common when demand is skewed or hazmat pools are imbalanced).
- **Core idea:** Run multiple K-means restarts with different seeds (and demand-weighting strengths); for each, run the full route-then-improve pipeline; keep the best. For hazmat, restart per class pool independently.
- **Expected gain:** Robustness against bad initial partitions; typically a few percent improvement and sharply lower variance run-to-run.
- **Cost:** Linear in number of restarts; each restart is independent so easy to budget.

---

## 跨 subtype 通用经验

1. **Greedy seed → local search is the universal template.** Never start local search from random; never stop at the greedy solution. NN (TSP) or K-means + per-cluster NN (CVRP) gives a feasible warm start; 2-opt / Or-opt / cross-route moves provide refinement. Both phases are non-negotiable.

2. **O(1) delta evaluation is mandatory for n ≥ a few hundred.** Express every move's cost as the change over the affected edges, not a full recomputation. For TSP at n=1000 this is ~1000× speedup; for CVRP it makes cross-route operators tractable.

3. **Precompute the full pairwise distance/time matrix.** When n ≤ a few thousand and memory permits, store as float32 numpy. All move evaluations become array lookups. For travel-time models with side rules (dual speed, hazmat masking), precompute the *post-rule* matrix once per class.

4. **Choose feasibility-preserving operators.** 2-opt reversal, Or-opt relocation, and swap on permutations preserve the Hamiltonian/permutation structure for free. For CVRP side constraints (capacity, segregation, forbidden edges, duration, rest), check feasibility *inside the move's delta* — not as a post-hoc repair, and never as a "flag as violation" fallback. Infeasible output scores 0.

5. **Apply side constraints uniformly across construction, every local-search operator, and final validation.** The dominant failure mode in routing traces is "checked at validation but not inside 2-opt / Or-opt / relocate." If the constraint is real, every move operator must see it.

6. **Never hardcode constraint keywords or restriction types.** Enumerate from the data. Treat edge restrictions as undirected (`frozenset({u,v})`). Mask all cost matrices (distance, risk, time, combined) consistently — Dijkstra over an unmasked matrix will silently re-introduce banned edges via intermediate hops.

7. **Distinguish eligibility from simultaneous compatibility.** A vehicle certified for multiple hazmat classes is NOT licensed to co-load them on one trip. Enforce segregation as a separate predicate before the eligibility check.

8. **Match evaluator I/O exactly.** Same distance metric, same rounding, same schema, same instance enumeration. For multi-instance benchmarks, assert the instance count up front and loop with a fixed per-instance budget; never hardcode a single input file.