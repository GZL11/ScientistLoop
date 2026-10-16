# Cross-Task Success Patterns: Meta-Analysis

## 1. Permutation/Sequence Encoding with Deterministic Time Derivation
**Prevalence: [5/6 runs]** (Patches #1, #2, #3, #4, #5)

### Why It Works
For single-machine, flow-shop, and job-shop scheduling, encoding the solution as a permutation (or per-resource sequence) makes hard constraints — uniqueness, precedence, capacity — *structurally tautological*. Once the order is fixed, optimal start times follow from a closed-form forward pass: a left-shift recurrence (flow shop), greedy earliest-feasible packing (single-machine ALP), or topological/longest-path evaluation (job shop disjunctive graph). This collapses a 2D (order × time) optimization into a 1D combinatorial search over permutations, eliminating entire constraint classes from the search.

### Generalizable Instruction
For sequencing/scheduling problems on shared resources, **separate the combinatorial decision (order) from the continuous decision (timing)**. Represent solutions as permutations or resource sequences so feasibility is automatic, then derive times via a deterministic forward pass (DP recurrence, greedy packing, or topological sort). Spend the entire compute budget on permutation search rather than on enforcing constraints that the encoding already guarantees.

---

## 2. Strong Constructive Seed + Iterated Local Search
**Prevalence: [5/6 runs]** (Patches #1, #2, #3, #4, #5)

### Why It Works
Every successful sequencing solver paired a problem-aware constructive heuristic (NEH for flow shop, Giffler-Thompson for job shop, target-time/EDD sort for ALP) with iterated local search using swap and or-opt/insertion neighborhoods. The constructive seed lands in a good basin immediately, so local search polishes rather than explores from scratch. Multiple seed orderings (target time, deadline, penalty ratio, total processing time) hedge against any single heuristic's blind spots.

### Generalizable Instruction
Never start local search from a random or trivial solution when a domain-appropriate constructive heuristic exists. Use NEH for flow shop, Giffler-Thompson for job shop, and due-date/target sorting for E/T objectives. Then apply swap + or-opt + insertion neighborhoods with perturbation restarts (ILS). Seed-quality matters more than metaheuristic sophistication.

---

## 3. Locality-Restricted Neighborhoods
**Prevalence: [2/6 runs]** (Patches #1, #2)

### Why It Works
Separation matrices and precedence chains induce spatial locality: distant reorderings are usually dominated by nearby ones or outright infeasible. Restricting swap windows (e.g. ±30) and or-opt moves (±50) shrinks the neighborhood by orders of magnitude without sacrificing solution quality, enabling far more iterations within a fixed time budget.

### Generalizable Instruction
When sequencing problems have separation, setup, or precedence costs that grow with positional distance, restrict local-search neighborhoods to a sliding window. The effective neighborhood is local; don't waste evaluations on swaps that are structurally guaranteed to be worse or infeasible.

---

## 4. JIT Compilation of Inner Evaluation Loop
**Prevalence: [2/6 runs]** (Patches #3, #4)

### Why It Works
Local search performance is dominated by millions of objective re-evaluations (makespan, completion-time DP). Numba `@njit` on the evaluation function (the 2D completion-time recurrence) turns naive O(n·m) per call into something fast enough to support millions of neighbor evaluations within minutes — making ILS competitive with bespoke incremental update schemes.

### Generalizable Instruction
Identify the innermost evaluation function called by local search and JIT-compile it (Numba, Cython, or hand-rolled C). For DP-style recurrences over arrays, this is typically a 10–100× speedup with minimal code change, and it usually beats trying to write incremental delta-evaluation logic.

---

## 5. Cheap Feasibility Short-Circuiting
**Prevalence: [2/6 runs]** (Patches #2, #5)

### Why It Works
Detect infeasibility (time-window violation, cycle in disjunctive graph) inline during evaluation and return immediately with `inf`/discard. This keeps the search in feasible territory without explicit repair logic and costs almost nothing per call.

### Generalizable Instruction
Bake feasibility checks into the evaluation function with early-exit on first violation. Don't run a separate "is-feasible" pass; fail fast inside the same forward sweep that computes the objective.

---

## 6. (Task-Specific, Not Generalized) MILP with Tightly-Bound Binaries
**Prevalence: [1/6 runs]** (Patch #6 only)

Single appearance — battery dispatch with mode binaries. Likely task-specific to small-horizon discrete-mode dispatch problems where MILP is tractable. The principles (binding binaries to physical variables with both upper *and* lower bounds; calibrating soft-penalty coefficients against marginal economic value) are sound but not corroborated by other runs.

---

## Summary Priority for Future Runs
1. **First**: Check if the problem is sequencing on shared resources → use permutation encoding + deterministic time derivation.
2. **Second**: Pair a problem-aware constructive seed with ILS (swap + or-opt).
3. **Third**: JIT-compile the evaluation loop and use windowed neighborhoods.
4. **Fourth**: Bake feasibility into evaluation with early-exit.
5. **Last resort** (small/discrete-mode problems only): MILP with carefully-bound binaries.