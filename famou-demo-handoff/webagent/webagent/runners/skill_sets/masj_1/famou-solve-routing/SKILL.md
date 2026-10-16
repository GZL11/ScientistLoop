```markdown
---
name: famou-solve-routing
description: >
  路径规划类问题的专项求解参考。当 famou-build 判断当前问题属于
  TSP / 多车 TSP (mTSP) / CVRP / VRPTW、配送路线、危险品运输、城市配送、
  应急站覆盖、多约束 VRP、多实例旅行商、车辆路网调度等场景时调用，
  获取该类问题的算法选型、约束建模、验证要点等专项指导。
  遇到关键词（配送、路线、巡回、TSP、VRP、运输、车辆、网点、载重、容量、
  时间窗、time window、Dijkstra、危化品、hazmat、应急站、路网、segment、
  工作量均衡、最短路、cluster、聚类配送）时优先调用。
---

# Routing Build Skill

Helps Build phase author `solver.py` for the two routing primaries:
- **tsp_local_search** — single Hamiltonian cycle (TSP).
- **cvrp_cluster_then_route** — fleet of capacitated vehicles from a depot (CVRP family, incl. hazmat).

## When to mount

Mount this skill if `instruction.md` contains any of:
- "TSP", "Hamiltonian", "tour", "visit every city", "shortest cycle"
- "vehicle", "fleet", "depot", "capacity", "demand", "route per vehicle"
- "delivery", "dispatch", "CVRP", "VRP"
- "hazmat", "hazardous", "restricted road", "segregation"
- coordinate lists + "minimize total distance / time"

If the instruction is purely matching/scheduling/assignment with no spatial routes, do **not** mount.

## References (read in this order)

1. `references/subtypes.md` — discriminator rules and which primary applies to which case ID.
2. `references/algorithm_playbook.md` — algorithm skeletons + extension recipes (large_n_scaling, multi_instance_io, dual_speed_travel_time, workload_balance, spatial_compactness, single_class_per_vehicle_segregation, edge_level_road_restrictions, max_route_duration, mandatory_driver_rest).
3. `references/code_templates/` — runnable starting points:
   - `tsp_2opt.py` (NN + 2-opt + Or-opt, neighbor-list pruning)
   - `cvrp_cluster_route.py` (capacitated K-means → per-cluster TSP → cross-route relocate/swap)
   - `hazmat_helpers.py` (forbidden-edge masking, hop-by-hop Dijkstra validation, rest-stop accounting)
4. `references/pitfalls.md` — concrete failure cases, especially the hazmat restriction enforcement checklist.

## Build flow

1. **Read `instruction.md` end-to-end.** Note: case ID, output schema, distance metric, rounding, speed model, service time, capacity, vehicle count, hazmat classes, restriction CSV columns, route duration cap, rest rules, multi-instance vs single.
2. **Identify the primary** using `references/subtypes.md` discriminators. If a case ID is listed in `case_to_primary`, use that mapping directly.
3. **List the extensions** that apply to this case (from `case_extensions`). Every extension recipe in `algorithm_playbook.md` you select must be implemented end-to-end (construction + delta eval + final cost), not bolted on at validation.
4. **Copy the matching template** from `references/code_templates/` into `solver.py` as a starting skeleton.
5. **Adapt the template**:
   - Wire the I/O exactly to the evaluator schema (instance keys, route field names, depot index convention, 0/1-based indexing).
   - Replace the distance function with the one the instruction specifies (Euclidean / Haversine / matrix lookup, with the correct rounding).
   - Plug in each selected extension (see recipes). For hazmat, build the forbidden-edge set **before** any routing call and pass the masked matrix everywhere.
   - Set a per-instance time budget; for multi-instance benchmarks, divide the global budget by instance count with a safety margin.
6. **Run on a tiny synthetic case first** (n=10, 1 vehicle) to confirm the I/O round-trips through the evaluator schema. Then scale up.
7. **Self-check** against the list below before declaring done.

## Pre-exit self-check (critical)

Run through every item; each maps to a recurring failure mode.

1. **Schema match.** Does `solution.json` use the exact keys the evaluator expects, for every instance? For multi-instance benchmarks, did you enumerate ALL instances (don't hardcode one file)?
2. **Tour validity.** TSP: every city appears exactly once and the tour returns to the start. CVRP: every customer served exactly once, each route starts and ends at the depot, route count ≤ available vehicles.
3. **Capacity.** For every route, sum of demands ≤ vehicle capacity. Check after every local-search move, not just at the end.
4. **Distance/time consistency.** The travel-time function used in construction, in 2-opt/Or-opt delta evaluation, and in the final emitted cost is the **same** function, with the same speed model and service time. For dual-speed cases, depot-leg vs inter-node distinction is applied uniformly.
5. **Hazmat — restriction enforcement** (if applicable):
   - All restriction types loaded from the data (no hardcoded keyword like `blacklist_explosive`).
   - Forbidden edges stored undirected (`frozenset({u,v})`) and checked both ways.
   - INF mask applied to **every** cost/risk/time matrix used by any Dijkstra or move operator, per hazmat class.
   - Every move operator (greedy insert, 2-opt, Or-opt, relocate, swap) rejects forbidden edges **before** scoring.
   - Hop-by-hop expanded path is re-validated against the raw restriction set; the emitted route is the fully expanded sequence.
   - No "flag as violation" soft fallback that emits a banned edge.
6. **Hazmat — segregation** (if applicable): each route contains exactly one hazmat class, AND that class is in the assigned vehicle's allowed set. Two separate predicates, both enforced.
7. **Route duration cap** (if applicable): cumulative drive + service + rest time ≤ the stated limit (e.g., 10 h) for every route, re-checked after every accepted move.
8. **Mandatory rest** (if applicable): rest time added whenever cumulative driven distance since last rest crosses the boundary (e.g., 160 km → +30 min); included in delta evaluation so local search sees post-rest duration.
9. **Scaling.** For n ≈ 1000, distance matrix is float32 numpy, 2-opt uses O(1) delta and a k-nearest neighbor list; sweeps complete within budget.
10. **Determinism & budget.** Solver finishes within the time limit on the largest instance, with a deterministic seed for reproducibility.

If any item fails, fix the algorithm — do not paper over with post-hoc filtering or violation flags.
```