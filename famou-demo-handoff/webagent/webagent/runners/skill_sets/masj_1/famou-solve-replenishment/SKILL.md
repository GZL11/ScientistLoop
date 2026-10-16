```markdown
---
name: famou-solve-replenishment
description: >
  补货 / 采购 / 库存优化类问题的专项求解参考。当 famou-build 判断当前问题属于
  多周期库存补货、Hub-Spoke 网络调拨、多供应商采购、带提前期 (lead time) 补货、
  容量选址 (CFLP)、库存替代品、保质期/损耗、安全库存、
  微电网/储能能源调度、网络流功率平衡等场景时调用，
  获取该类问题的算法选型、约束建模、验证要点等专项指导。
  遇到关键词（补货、采购、库存、提前期、lead time、DC、仓库、缺货、调拨、转运、
  供应商、安全库存、保质期、损耗、过期、SKU、shelf life、选址、设施开设、
  微电网、储能、SOC、电价、ToU、光伏、充电、放电、功率平衡）时优先调用。
---

# Replenishment Build Skill

This skill helps you write `solver.py` for replenishment / procurement optimization problems. It covers two primaries:

- **multi_period_replenishment_milp** — period × SKU × location with cold capacity, holding/shortage/spoilage costs.
- **multi_supplier_procurement_milp** — supplier selection with discounts, surcharges, risk premium, MOQ.

## When to mount (keywords in instruction.md)

- "replenishment", "reorder", "order quantity", "order_units"
- "cold capacity", "cold_usage", "cold storage", "perishable", "spoilage"
- "DC", "warehouse", "hub", "spoke", "transshipment"
- "supplier", "MOQ", "lead time surcharge", "early payment discount", "reliability"
- "multi-period", "weekly demand", "planning horizon"

## References

- `references/subtypes.md` — full subtype discriminators, algorithm skeletons, core invariants, and case→primary mapping.
- `references/algorithm_playbook.md` — step-by-step modeling recipes, big-M linearization, peak vs. end-of-period capacity, lead-time arrivals, hub-spoke transfers, quality substitution.
- `references/code_templates/replenishment_milp.py` — starter template for `multi_period_replenishment_milp`.
- `references/code_templates/procurement_milp.py` — starter template for `multi_supplier_procurement_milp`.
- `references/pitfalls.md` — concrete failure patterns from prior runs with diffs.

## Solve flow

1. **Read `instruction.md` carefully.** Note the case name if present, the cost components (purchase, holding, shortage, spoilage, surcharges, discounts), the horizon T, the SKU/supplier/location sets, and the **exact** required output column names and CSV path.
2. **Identify subtype** using `references/subtypes.md`:
   - Cold storage + per-SKU cold_usage + multi-period inventory → `multi_period_replenishment_milp`.
   - Multiple suppliers + conditional cost modifiers (discounts/surcharges/risk) → `multi_supplier_procurement_milp`.
3. **List active extensions** from the case→extensions map (e.g. `lead_time_arrivals`, `hub_spoke_transshipment`, `early_payment_discount`, `weighted_cold_capacity_at_all_nodes`, `quality_substitution`, `pre_build_lookahead`, `supplier_weekly_capacity`).
4. **Copy the matching template** from `references/code_templates/` to `solver.py`. Do not start from scratch.
5. **Adapt the template**:
   - Wire input parsing to whatever files PLAN.md / instruction reference (CSV, JSON, YAML).
   - Precompute effective unit costs **outside** the solver (lead-time surcharge, risk premium, FX, holding).
   - Declare order/purchase quantity variables as **Integer** (not Continuous).
   - Add each active extension by following its recipe in `references/algorithm_playbook.md`.
   - For cold capacity, add **both** peak-occupancy (post-arrival) and end-of-period constraints, weighted by `cold_usage[p]`, at **every** storage node.
   - For lead times, define `arrivals[p,t,loc] = order[p, t-L, loc]` (zero if `t<L`); inventory update uses arrivals, not orders.
   - For binary × continuous (e.g. discount × qty), introduce auxiliary `z` with big-M tied to capacity, not an arbitrary large number.
6. **Build the dense output grid** before writing CSV: iterate over the full Cartesian product (period × SKU × location, or supplier × product × month) and emit zero rows where no decision was made. Cast integer-typed columns to `int`.
7. **Run** `python solver.py` from the working directory. Confirm it produces the expected output file at the path the evaluator checks.
8. **Self-check** against the list below before finishing.

## Pre-exit self-check (must pass all)

1. **Integer order/purchase variables.** `cat solver.py | grep -n "Integer\|cat=.*Integer\|NewIntVar"` — quantity decisions are integer, not continuous.
2. **Cold capacity is weighted by `cold_usage[p]` at every storage location** (hub AND every spoke/DC), not just the hub and not unweighted unit counts.
3. **Cold capacity enforced at peak occupancy** `Σ_p cold_usage[p] · (inv[p,t-1,loc] + arrivals[p,t,loc]) ≤ cap[loc]`, AND at end-of-period. Both, because evaluators take the stricter.
4. **Inventory non-negativity at every period** for every (SKU, location); no netting across periods, no negative residuals masked by positives.
5. **Lead-time arrivals correctly indexed.** `arrivals[p,t,loc] = order[p, t-L, loc]`, zero for `t < L`. Order rows for periods where `t+L > T` still appear in output (with qty 0 if needed).
6. **Effective unit cost precomputed** including: lead-time surcharge ($5/unit if lead_time>7), reliability premium (`0.10 · (100 - reliability)`), FX, and holding cost where applicable. No mid-solve recomputation that drops a term.
7. **Bilinear terms linearized**: for any `binary × continuous`, the auxiliary `z` has all four big-M constraints (`z ≤ M·b`, `z ≤ x`, `z ≥ x − M·(1−b)`, `z ≥ 0`) and `M` is set to the capacity upper bound, not infinity.
8. **Output CSV column names match the spec exactly** (e.g. `order_units` not `order_qty`, `period` not `week` unless instruction says otherwise). Cast quantity columns to `int` before `to_csv`.
9. **Dense output grid.** Row count equals `|periods| × |SKUs| × |locations|` (or `|suppliers| × |products| × |months|`). Zero-decision rows are present.
10. **Replay the evaluator's capacity / cost formula on your own solution** in a final sanity print; if it differs from the solver's objective or violates a capacity bound, the model is under-constrained — fix before exiting.

If solver returns infeasible: first relax shortage to a penalized soft variable (large per-unit cost) rather than hard demand satisfaction, then inspect which period/location is binding. Do NOT silently drop constraints.
```