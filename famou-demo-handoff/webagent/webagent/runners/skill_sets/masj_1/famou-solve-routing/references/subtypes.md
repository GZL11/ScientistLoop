# Routing Subtypes

## 决策树

Use this quick decision tree to map a new routing case to a primary subtype:

```
Does the instruction specify a depot + a fleet of K vehicles + per-vehicle capacity
and/or per-customer demands, and ask for per-vehicle routes?
├── YES → primary: cvrp_cluster_then_route
│         (Then layer on extensions for any side constraints:
│          dual-speed travel, workload balance, spatial compactness,
│          hazmat segregation, edge restrictions, max duration, driver rest, …)
│
└── NO  → Is the instruction a single Hamiltonian cycle over all given coordinates,
         starting and ending at the same point, with no capacity/vehicle concept?
         ├── YES → primary: tsp_local_search
         │         (Add large_n_scaling if n is large; multi_instance_io if dataset
         │          contains multiple instances to be solved independently.)
         │
         └── NO  → fallback: see "兜底: other" below.
```

Heuristics:
- Mention of "vehicle", "capacity", "demand", "depot", "fleet" → CVRP family.
- Mention of "tour", "visit each city once", "return to start", only `(x, y)` coords → TSP family.
- Mention of "hazmat / class / forbidden roads / driver rest / max hours" → CVRP + hazmat extensions.

---

## primary: tsp_local_search

**Discriminator**
Instruction asks for a single Hamiltonian cycle visiting all cities exactly once and returning to start, with only coordinates given (no capacity/vehicles).

**Algorithm skeleton**
Precompute pairwise distance matrix → nearest-neighbor (multi-start) constructive seed → 2-opt / Or-opt local search using O(1) delta evaluation → optionally randomized restarts; output permutation tour.

**Core constraints**
- Tour visits every city exactly once and returns to the start (Hamiltonian cycle).
- Output schema must match evaluator: if benchmark is multi-instance, enumerate every instance and emit one tour per instance.
- Distance computation must be consistent between solver and evaluator (same metric, same rounding).

---

## primary: cvrp_cluster_then_route

**Discriminator**
Instruction specifies a depot, a fleet of K vehicles with capacity, customer demands/locations, and asks for per-vehicle routes (possibly with workload balance / spatial compactness / extra side constraints).

**Algorithm skeleton**
Partition customers (K-means on coordinates, optionally weighted by demand and constrained by per-cluster capacity) → assign each cluster to a vehicle → solve per-cluster TSP via NN + 2-opt/Or-opt with delta evaluation → rebalance boundary customers to the nearest feasible cluster when capacity/side-constraints are violated → compute travel time using the specified speed model and service times.

**Core constraints**
- Per-vehicle load must not exceed capacity.
- Each customer is served exactly once by exactly one vehicle; route starts and ends at the depot.
- Number of routes must not exceed available vehicles.
- All edges/moves must be checked against any case-specific feasibility rules (segregation, restrictions) before being accepted, not only at final validation.
- Travel time/cost must be computed with the speed/service-time model the instruction specifies, consistently across construction and local search.

---

## Extensions

Each extension is a self-contained recipe that can be composed on top of a primary skeleton.

### `large_n_scaling`
Precompute full O(n²) distance matrix as a numpy array of float32; use multi-start nearest-neighbor (e.g., 10–20 different seed cities); run 2-opt with O(1) delta cost (compare `d[i-1,i]+d[j,j+1]` vs `d[i-1,j]+d[i,j+1]`); for n≈1000 use neighbor-list pruning (only consider j among k-nearest of i, k≈20) to keep sweeps fast; finish with an Or-opt pass.

### `multi_instance_io`
At entry, enumerate the dataset directory or group input rows by `instance_id`; assert count equals the spec (e.g., 128); loop over each instance with a fixed per-instance time budget; collect tours into a single `solution.json` keyed by `instance_id` matching the evaluator schema; never hardcode a single input file.

### `dual_speed_travel_time`
Implement `travel_time(u, v)` that uses 70 km/h when exactly one endpoint is the depot (depot↔node trunk legs) and 35 km/h otherwise (inter-node), plus add 120 s service time at every customer visit when computing route duration; use this function uniformly in construction, delta evaluation, and final cost.

### `workload_balance`
Add a balance penalty to the objective: `total_time + λ * (max_route_duration - min_route_duration)`, or constrain each route's duration within `[mean*(1-α), mean*(1+α)]`; during K-means, weight points by demand and target equal cluster sums; include a cross-route relocate/swap operator that only accepts moves which reduce the max route duration.

### `spatial_compactness`
Use K-means (or capacitated K-means) on `(lon, lat)` so clusters are convex; when rebalancing for capacity, always move a boundary customer to its geographically nearest feasible cluster; after routing, run a cross-route 2-opt* only between geographically adjacent clusters to avoid creating crossings.

### `single_class_per_vehicle_segregation`
Before any routing: partition customers by `hazmat_class` into disjoint pools and route each pool independently with its own subset of vehicles. In the feasibility check enforce two separate predicates: (1) `len({p.hazmat_class for p in route}) == 1`, (2) that class ∈ `vehicle.allowed_classes`. Never merge classes even if a vehicle is certified for several.

### `edge_level_road_restrictions`
Load ALL restriction types from the data (do not hardcode keywords); build `FORBIDDEN[hazmat_class]` as a set of `frozenset({u, v})` (undirected); apply INF masking uniformly to every cost/risk/time matrix used by any Dijkstra or local-search call, per class; check forbidden edges inside every move operator (greedy insert, 2-opt, Or-opt, relocate, swap) before accepting; expand Dijkstra hop-by-hop and re-validate the full expanded path; never emit "flag as violation" fallbacks — if no feasible path, split the route or take a longer detour.

### `max_route_duration`
Track cumulative route duration (drive time + service time + rest time) and reject any insertion/move whose new duration exceeds 10 h; during construction, close the route and start a new one (or reject the customer for this vehicle) when the next insertion would breach the limit.

### `mandatory_driver_rest`
Maintain a running odometer per route; whenever cumulative driven distance since the last rest crosses a 160 km boundary, add 30 min rest to the route duration before the next leg; include this rest cost in delta evaluation so local-search moves see the true post-rest duration, and re-check the 10 h cap after every move.

---

## case → subtype 映射

| case | primary | extensions | notes |
|---|---|---|---|
| `wb_tsp_1000` | `tsp_local_search` | `large_n_scaling` | Single large TSP (~1000 cities); neighbor-list pruning + Or-opt are essential to fit time budget. |
| `wb_tsp_multi` | `tsp_local_search` | `multi_instance_io` | Many independent TSP instances; key the output by `instance_id` and use a per-instance time budget. |
| `wb_city_delivery_routing` | `cvrp_cluster_then_route` | `dual_speed_travel_time`, `workload_balance`, `spatial_compactness` | Urban CVRP variant: depot↔node = 70 km/h, inter-node = 35 km/h, 120 s service; balance route durations and keep clusters geographically convex. |
| `wb_hazmat_transport` | `cvrp_cluster_then_route` | `single_class_per_vehicle_segregation`, `edge_level_road_restrictions`, `max_route_duration`, `mandatory_driver_rest` | Hazmat CVRP: one class per vehicle, class-specific forbidden edges enforced inside every move, ≤10 h shifts, +30 min rest every 160 km. |

---

## 兜底: other

When a new case does not cleanly match either primary, degrade gracefully rather than silently misclassifying:

1. **Re-check the discriminators in order.**
   - If a depot + vehicles + capacity/demand exist → force `cvrp_cluster_then_route`, even if other features look unfamiliar.
   - Else if the task is a single closed tour over coordinates → force `tsp_local_search`.

2. **Unknown side constraints → additive, conservative extensions.**
   - Treat any unrecognized constraint (