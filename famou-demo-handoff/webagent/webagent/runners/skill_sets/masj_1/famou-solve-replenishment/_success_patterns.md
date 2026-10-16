# Consolidated Success Patterns

## 1. MILP/CP-SAT with Full Cost Linearization [4/7 runs]
**Sources:** Patches #3, #4, #5, #6

**Why it works:** When business rules involve conditional thresholds (MOQs, contract minimums, supplier activation, early-payment discounts), formulating them as a single MILP/CP-SAT model lets a general-purpose branch-and-cut solver explore tradeoffs globally. The key engineering moves are:
- Introduce **one binary per discrete decision dimension** (`y[s]` supplier-used, `b[s,m]` month-active, `ep[s,m]` discount-taken) rather than overloading variables.
- **Linearize bilinear terms** (binary × continuous, e.g. discount × quantity) via auxiliary variables `z = x·b` bounded by big-M tied to physical capacity.
- Express "if-used-then-≥-threshold" rules as **paired big-M inequalities** (`z ≥ min·b`, `z ≤ M·b`).

**Generalizable instruction:** For problems with disjunctive/conditional business rules, default to MILP with explicit binary indicators at every aggregation level (per-period, per-horizon) and linearize all bilinear interactions with auxiliary variables. Don't fall back to greedy until the MILP is proven intractable.

---

## 2. Precompute Effective Unit Costs Outside the Solver [5/7 runs]
**Sources:** Patches #3, #4, #5, #6, #7

**Why it works:** Procurement/assignment problems layer multiplicative and additive cost modifiers (FX rate, duties, lead-time surcharge, risk premium, inspection fee, quality penalty). Folding all of these into a single scalar `cost[s,p,m]` *before* model construction keeps the optimization objective linear (`Σ qty · unit_cost`), makes it interpretable for downstream reporting, and works equally well in MILP, CP-SAT, or greedy approaches.

**Generalizable instruction:** Separate **per-unit fixed coefficients** (computable from inputs alone) from **decision-dependent costs** (MOQ activation, discount eligibility). Compute a fully-loaded cost matrix in a preparation step; let the solver only handle the truly decision-dependent terms.

---

## 3. Procedural Constraint Enforcement via Simulation/State Updates [3/7 runs]
**Sources:** Patches #1, #2, #7

**Why it works:** When constraints involve physical flow (inventory aging, capacity sharing, FIFO), simulating the system period-by-period with explicit state updates (`end_inv = current_inv + order - satisfied`) guarantees feasibility by construction rather than relying on algebraic encoding. Shared resources are handled via **proportional rationing** (`scale = capacity / total_demand`).

**Generalizable instruction:** For multi-period flow problems where feasibility is fragile, build an explicit state-update simulator with age/FIFO buckets and proportional rationing of shared resources. This trades some optimality for guaranteed validity—use as a fallback or as a feasibility-repair pass after optimization.

---

## 4. Look-Ahead / Pre-Build Beats Pure Myopia [2/7 runs]
**Sources:** Patches #1 (with shelf-life buffer), #2 (lesson learned negatively)

**Why it works:** When production capacity is binding and lost-sales penalties dominate, a myopic policy that only orders the current shortfall cannot exploit slack periods to pre-build inventory. Patch #1 added a forward-looking buffer (`min(future_demand * 0.2, 50)`); Patch #2's failure was explicitly attributed to lacking this.

**Generalizable instruction:** In any multi-period problem with tight shared capacity and asymmetric stockout/holding costs, the policy must look ahead at least one peak. Either solve as a multi-period LP/MIP, or augment greedy with a domain-tuned forward buffer keyed to the binding constraint.

---

## 5. Express Portfolio/Regulatory Rules as Linear Aggregates [3/7 runs]
**Sources:** Patches #3, #6, #7

**Why it works:** Diversity (`Σ used ≥ k`), concentration caps (`total_s ≤ α · total_demand`), and weighted-quality limits (`Σ defect·x ≤ θ · total`) all become **clean linear inequalities** when expressed against a precomputed total-demand constant rather than as ratios. Contract minimums must be gated on the `used[s]` binary so the model can skip a supplier entirely.

**Generalizable instruction:** Rewrite ratio/percentage constraints as linear aggregates against precomputed totals. Always make minimum-volume contracts conditional on a supplier-active binary so opting out is feasible.

---

## Discarded as Task-Specific (1 run only)
- **Patch #7's hard-coded allocation mix (30/30/25/15):** Clever for this exact instance but not generalizable—it's tuned to specific supplier IDs and constraint values.
- **Patch #1's shelf-life-specific buffer of 0.2×future_demand capped at 50:** Magic numbers tied to this dataset.