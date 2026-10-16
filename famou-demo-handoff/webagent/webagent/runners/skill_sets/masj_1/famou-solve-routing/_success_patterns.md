# Merged Success Patterns Across 7 Optimization Runs

## 1. Constructive Greedy Seed + Local Search Refinement
**Prevalence: [7/7 runs]**

Every run — TSP and CVRP alike — followed the same two-phase template: build a feasible solution cheaply with a greedy heuristic (nearest-neighbor for tours, K-means + per-cluster NN for VRP), then iteratively improve it with a local-search neighborhood (2-opt, 3-opt, Or-opt, or capacity rebalancing).

**Why it works:** A greedy constructor produces a feasible warm start in O(n²), giving local search a good basin to refine. Local search then spends compute on quality improvements rather than feasibility recovery. The two phases have complementary strengths: greedy is fast but myopic; local search is slow but corrects myopia.

**Generalizable instruction:** Default pipeline for any combinatorial optimization = cheap greedy constructor → iterative local search. Never start local search from random; never stop at the greedy solution.

---

## 2. Feasibility-Preserving Move Operators
**Prevalence: [6/7 runs]**

2-opt segment reversal, Or-opt relocation, and 3-opt moves all preserve the Hamiltonian-cycle / permutation property by construction. Multiple runs explicitly noted that "no constraint repair is needed."

**Why it works:** When the move operator structurally preserves feasibility, the search can focus entirely on objective improvement. Constraint-repair logic is a major source of bugs and wasted compute.

**Generalizable instruction:** Choose neighborhood operators that preserve feasibility automatically (reversal, swap, relocation on permutations). Avoid moves that require post-hoc repair unless the constraint is the primary objective.

---

## 3. O(1) Delta-Cost Move Evaluation
**Prevalence: [5/7 runs]**

Every TSP run computed swap deltas locally — comparing only the 4 affected edges (`d(i-1,i) + d(j,j+1)` vs `d(i-1,j) + d(i,j+1)`) — rather than recomputing the full tour cost.

**Why it works:** This turns each candidate move from O(n) to O(1), making O(n²) neighborhoods tractable. For n=1000 this is the difference between 1 sweep/sec and 1000 sweeps/sec.

**Generalizable instruction:** Always express move evaluation as a delta over the modified edges/elements, not a full objective recomputation. This is non-negotiable for n ≥ a few hundred.

---

## 4. Precomputed/Cached Distance Matrix
**Prevalence: [4/7 runs]**

Runs explicitly precomputed the full pairwise distance matrix or memoized distances on first access, so every move evaluation became a lookup.

**Why it works:** Local search is dominated by distance queries. Caching converts repeated trigonometric/sqrt computation into O(1) array indexing — typically 10-100× speedup.

**Generalizable instruction:** Whenever n ≤ a few thousand and memory permits, precompute the full pairwise cost matrix once. For larger n, use memoization with an LRU cache.

---

## 5. Cluster-First, Route-Second Decomposition (for VRP)
**Prevalence: [3/7 runs — all CVRP runs]**

K-means on (lon, lat) → per-cluster TSP. Capacity feasibility enforced by transferring boundary customers to the *geographically nearest* cluster with headroom.

**Why it works:** Spatial locality dominates routing cost in geographic VRPs. Decomposition reduces a hard joint problem to one easy clustering + many independent tractable TSPs.

**Generalizable instruction:** For large geographic VRPs, decompose by spatial clustering before routing. Critical detail: rebalancing must move points to the *nearest feasible* cluster, not just any feasible one, or you'll create tangled routes.

---

## 6. Multi-Start / Randomized Diversification
**Prevalence: [3/7 runs]**

Multi-start NN with different seed cities, or randomized 2-opt sampling instead of exhaustive enumeration when the full neighborhood is too large.

**Why it works:** Single-start greedy + deterministic local search converges to one local optimum. Random restarts and randomized neighborhood sampling escape this trap with low overhead.

**Generalizable instruction:** Add cheap diversification (random restarts, random neighborhood sampling) when local search plateaus or the neighborhood is too large to enumerate.

---

## 7. Progressive Neighborhood Strengthening
**Prevalence: [2/7 runs]**

Chain neighborhoods from cheapest to richest: NN → 2-opt (until convergence) → 3-opt / Or-opt for diminishing returns.

**Why it works:** Most improvement comes from the cheapest moves. Spending early compute on 3-opt is wasteful; saving it for after 2-opt converges captures the marginal gains.

**Generalizable instruction:** Order local-search neighborhoods by cost-per-move ascending. Only escalate to richer neighborhoods after cheaper ones converge.

---

## Discarded (Task-Specific, Single-Run)

- **Hazmat-class vehicle partitioning** (Patch #3): specific to multi-commodity hazmat VRP.
- **Risk-weighted segment cost (50× multiplier)**: domain-specific cost structure.
- **Speed differentiation trunk vs. delivery (70 vs 35 km/h)**: instance-specific.

These reflect specific problem variants, not transferable principles.