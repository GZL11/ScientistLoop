# Merged Success Patterns

All 3 runs converged on essentially the same approach. Below are the consensus strategies ranked by prevalence.

---

## 1. Precompute Effective Unit Costs to Keep Objective Linear
**Prevalence: [3/3 runs]**

### Why It Works
Every per-unit cost modifier in the problem (early-payment discount, lead-time surcharge, reliability/risk premium, quality/inspection fee, exchange rate, import duty) is **data-dependent, not decision-dependent**. Folding them all into a single scalar `eff_cost[(s,p,m)] = (price·ep_factor + lt_surcharge + risk_premium + inspection_fee) · fx · (1+duty)` *before* model construction collapses an apparently nonlinear cost structure into a clean `Σ eff_cost · x` objective. The MILP stays small, linear, and fast.

### Generalizable Instruction
Before building any optimization model, **separate parametric constants from decision variables**. Any cost/coefficient that can be computed purely from input data — even if it looks complex (FX chains, tiered discounts, surcharges) — should be precomputed into a single per-variable coefficient. Never let the solver see the decomposition; it only needs the final linear coefficient.

---

## 2. Big-M Pair for Semi-Continuous (MOQ / "zero-or-at-least-K") Quantities
**Prevalence: [3/3 runs]**

### Why It Works
Order quantities that must be either 0 or ≥ MOQ are semi-continuous and cannot be expressed with bounds alone. The canonical encoding uses a binary activation indicator `b[s,m]` with the paired constraints:
- `qty ≤ cap · b`  (forces qty=0 when inactive)
- `qty ≥ moq · b`  (forces qty≥MOQ when active)

This is tight, standard, and well-handled by every MILP solver.

### Generalizable Instruction
For any "buy zero or at least K" / semi-continuous decision, use the **big-M pair** `moq·b ≤ qty ≤ cap·b` with a binary `b`. Choose `cap` as the tightest valid upper bound (not an arbitrary large M) to keep the LP relaxation strong.

---

## 3. Hierarchical Binaries: Period-Level → Horizon-Level Activation
**Prevalence: [3/3 runs]**

### Why It Works
Procurement constraints often live at *different time scales*: MOQs are monthly, but contract minimums, supplier diversity counts, and fixed-supplier-fees are horizon-level. Linking a monthly binary `b[s,m]` to a horizon binary `z[s]` (via `b[s,m] ≤ z[s]`) cleanly composes the two layers — `z[s]` then gates aggregate constraints like `Σ_m qty[s,m] ≥ min_total · z[s]` or diversity `Σ_s z[s] ≥ 3`.

### Generalizable Instruction
When a problem has constraints at multiple aggregation levels, use **chained binaries**: a fine-grained indicator per period/unit, linked by `b_fine ≤ b_coarse` to a coarse-grained indicator. The coarse binary becomes the natural hook for fixed costs, minimum totals, and counting/diversity constraints.

---

## 4. Linearize Weighted-Average / Ratio Constraints by Clearing the Denominator
**Prevalence: [3/3 runs]**

### Why It Works
Constraints like "weighted defect rate ≤ 2%" naively look like `Σ rate_s · x_s / Σ x_s ≤ 0.02` — a nonlinear ratio. Multiplying through and rearranging yields the pure linear form `Σ (rate_s − 0.02) · x_s ≤ 0`. Same trick applies to share/concentration caps: `share_s ≤ 0.4` becomes `5·total_s ≤ 2·total_all`.

### Generalizable Instruction
**Never introduce fractional/ratio constraints into a MILP.** Always cross-multiply and move the threshold inside the sum: `Σ (a_i − threshold) · x_i  ≤ 0` for weighted averages, and integer cross-multiplication for share caps. This keeps the model linear with no auxiliary variables.

---

## 5. MILP via PuLP as the Solver Choice
**Prevalence: [3/3 runs]**

### Why It Works
PuLP gives a clean, declarative interface to CBC (and other backends), making the above patterns (precomputed coefficients, paired big-M, chained binaries, linearized ratios) directly expressible. The combinatorial structure — integer quantities, MOQs, diversity counts — is exactly what branch-and-bound handles well.

### Generalizable Instruction
For procurement / sourcing / assignment problems with integer quantities and logical constraints (MOQ, diversity, fixed costs), **default to MILP** with a high-level modeling layer (PuLP, Pyomo, OR-Tools). Don't reach for metaheuristics until you've confirmed the problem doesn't fit cleanly into linear form after the four tricks above.

---

## Cross-Cutting Meta-Principle
All three runs share one underlying philosophy: **do as much arithmetic as possible in Python before the solver sees the model.** Constants stay in NumPy/dicts; only genuine decisions become variables; every constraint is rewritten until it's linear. The solver's job is search, not algebra.