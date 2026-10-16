# Consolidated Success Patterns Across 9 Optimization Runs

## 1. Construction + Local Search Pipeline (Greedy/NN seed → 2-opt refinement)
**Prevalence: [9/9 runs]** — universal across all patterns

### Why It Works
Every successful run paired a fast constructive heuristic (nearest-neighbor, greedy insertion) with an iterative improvement step (2-opt or single-node moves). The constructive seed places the search in a good basin of attraction; the local search polishes within that basin. Precomputed distance matrices and O(1) delta-evaluation of swaps (`d(a,c)+d(b,d)−d(a,b)−d(c,d)`) make 2-opt cheap enough to run to convergence within per-instance time budgets.

### Generalizable Instruction
For any routing/TSP/VRP problem, default to **constructive heuristic + 2-opt with delta-evaluated swaps on a precomputed distance matrix**. Seed quality matters more than local-search sophistication at moderate scale. Use first-improvement with restart-on-swap; allocate explicit per-instance time budgets when batching.

---

## 2. Decompose by Category/Constraint Before Optimizing
**Prevalence: [7/9 runs]** (Patches 1, 2, 3, 4, 5, 6 + implicit in 9)

### Why It Works
When problems have natural partitions — geographic clusters (K-Means on coords), categorical incompatibility (hazmat class, vehicle certification), or capacity groups — solving each partition independently shrinks each subproblem to a size where strong methods (exhaustive enumeration for n≤8, 2-opt for n≤500) become tractable and near-optimal. Decomposition is lossless when partitions cannot share resources.

### Generalizable Instruction
**Identify the decomposition structure first.** If the problem has hard categorical constraints (compatibility, zoning) or natural spatial groupings, partition before optimizing. Use K-Means with multiple seeds (selected on the *evaluation metric*, not inertia) for spatial decomposition; use exact category matching for compatibility constraints. Then solve each subproblem with the strongest tractable method.

---

## 3. Mirror the Evaluator's Exact Cost Function in the Inner Loop
**Prevalence: [6/9 runs]** (Patches 1, 2, 3, 5, 6, plus 7-9 implicitly use exact Euclidean)

### Why It Works
Solvers that baked the *true* scoring function into local search — including piecewise speeds (70 km/h depot vs 35 km/h inter-stop), service times, exact penalty coefficients (`COST_PER_RISK = 50 + 0.5 = 50.5` for risk + 1% insurance), and lexicographic priorities — optimized the right quantity. Solvers using proxy distances optimized the wrong objective and underperformed.

### Generalizable Instruction
**Read the evaluator carefully and replicate its cost decomposition exactly inside your inner loop.** Include all penalty coefficients, asymmetric edge costs, service times, and constraint-derived effective weights. A simpler heuristic with the right objective beats a sophisticated one optimizing a proxy.

---

## 4. Priority-Aligned Sequential Pipeline for Lexicographic Objectives
**Prevalence: [3/9 runs]** (Patches 1, 2, 3)

### Why It Works
For multi-objective VRPs ordered as `balance ≫ compactness ≫ duration`, building the solution stage-by-stage in priority order — (1) cluster spatially, (2) repair capacity with minimum spatial disruption via nearest-cluster migration, (3) intra-route 2-opt, (4) rebalance via boundary-node moves gated by improvement check on the dominant metric — preserves invariants from earlier stages.

### Generalizable Instruction
For lexicographic multi-objective problems, **structure the pipeline to match the priority order**, and at each later stage use moves that minimally perturb the higher-priority quantities already optimized (e.g., single-node transfers barely change spatial compactness but heavily affect balance).

---

## 5. Hard Constraints as Feasibility Filters, Not Soft Penalties
**Prevalence: [3/9 runs]** (Patches 4, 5, 6)

### Why It Works
For VRPs with edge bans (school zones, explosive blacklists), capacity caps, time windows, and risk caps, encoding constraints as hard filters that prune infeasible permutations/insertions during enumeration is cleaner and faster than penalty-method tuning. Patch 5 evaluates `route_time_min` (with mandatory rests) inside the permutation loop; Patch 6 checks full tentative routes at each greedy insertion.

### Generalizable Instruction
**Encode hard constraints as predicates that prune the search**, not as penalty terms. Validate the *full tentative route* on each insertion/swap rather than tracking deltas, since constraint coupling (load × time × risk) often defeats incremental tracking.

---

## 6. Exhaustive Enumeration When Subproblem Is Small (n ≤ 8)
**Prevalence: [2/9 runs]** (Patches 4, 5)

### Why It Works
After category-based decomposition, each subproblem often has ≤5–8 nodes. `itertools.permutations` over 5 nodes is 120 routes — cheaper to enumerate than to run any metaheuristic, and provably optimal.

### Generalizable Instruction
**After decomposition, check subproblem size**. If n ≤ 8, brute-force permutation enumeration with feasibility filters dominates metaheuristics in both quality and code simplicity.

---

## 7. Vectorized Numpy for Distance Matrices and Inner Loops
**Prevalence: [3/9 runs]** (Patches 7, 8, 9)

### Why It Works
At n=500, pure-Python 2-opt is too slow. Vectorized distance computation (`coords[:, None, :] - coords[None, :, :]`) and numpy-sliced swap evaluation reduce inner loops to C-speed, fitting tight time budgets across many instances.

### Generalizable Instruction
**Precompute distance matrices once with vectorized numpy**, and where possible, vectorize the inner swap-scan. This is mandatory at n ≥ 200 with batch time budgets.

---

## 8. Handle Format/Rotation Constraints as Post-Processing
**Prevalence: [3/9 runs]** (Patches 7, 8, 9)

### Why It Works
Symmetric TSP tours are rotation-invariant in cost, so a "must-start-at-city-1" constraint should not be embedded in the search. Optimize freely, then rotate via `np.roll` after convergence.

### Generalizable Instruction
**Decouple cost-invariant output-format constraints (start city, direction) from the optimizer.** Apply them as post-hoc transformations to avoid artificially restricting the search space.

---

## Discarded (One-off / task-specific)
- Patch 4's specific hazmat-class-to-vehicle mapping (V1→flammable, etc.) — task-specific
- Patch 9's specific 28-second time budget — instance-tuning detail