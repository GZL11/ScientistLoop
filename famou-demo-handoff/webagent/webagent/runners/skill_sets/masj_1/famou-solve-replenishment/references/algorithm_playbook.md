# Algorithm Playbook: Replenishment (Build Phase)

This playbook covers the two primaries for replenishment-class problems: multi-period inventory replenishment with cold storage, and multi-supplier procurement with conditional cost modifiers. Each primary lists a baseline (starter algorithm and scale) plus two improvements with switching criteria, core idea, expected gain, and engineering cost.

---

## Primary 1: `multi_period_replenishment_milp`

**Applies to cases:** `wb_cold_storage_replenishment`, `wb_replenishment_hub_spoke`, `wb_replenishment_with_lead_time`

### Baseline — Single MILP over (period × SKU × location)

- **Starter algorithm:** PuLP/CBC MILP. Decision variables: `order[p, t, loc]` declared as `Integer, lowBound=0`. Simulate inventory state explicitly: `inv[p, t, loc] = inv[p, t-1, loc] + arrivals[p, t, loc] − sales[p, t, loc] − spoilage[p, t, loc]`. Objective minimizes purchase + holding + shortage + spoilage costs. Apply cold capacity at **both** peak (`prev_inv + arrivals`) and end-of-period at every storage node, weighted by per-SKU `cold_usage`.
- **Scale:** Up to ~12 periods × ~30 SKUs × ~5 locations (~1.8k integer vars) solves in <60s on CBC. Beyond ~5k integer vars, switch solver or decompose.
- **Observed score range:**
  - `wb_cold_storage_replenishment`: 0.55–0.75 baseline
  - `wb_replenishment_with_lead_time`: 0.50–0.70 baseline
  - `wb_replenishment_hub_spoke`: 0.40–0.60 baseline (hub/spoke routing pulls scores down without explicit transshipment vars)
- **Reference code template:** `templates/multi_period_replenishment_milp.py` — provides PuLP skeleton with state-update loop, dual capacity constraints, and dense CSV emission.

**Baseline must-do checklist (from failure analysis):**
1. Order variables declared `Integer` — never `Continuous`.
2. Cold capacity constraint includes `cold_usage[p]` weighting.
3. Capacity enforced at peak (post-arrival) **and** end-of-period.
4. Inventory non-negativity at every (p, t, loc) — no netting.
5. Output CSV is a **dense grid** over all (period × SKU × location) including zero-order rows; column names match spec exactly (`order_units`, not `order_qty`); cast to `int` before write.

### Improvement 1 — Lead-Time Arrivals + Pre-Build Lookahead

- **When to switch:** Case has nonzero lead times (`wb_replenishment_with_lead_time`) OR demand has a sharp spike that exceeds single-period supplier capacity (`wb_cold_storage_replenishment` with `supplier_weekly_capacity`). Symptom: baseline produces shortages in peak weeks despite slack capacity in earlier weeks.
- **Core idea:**
  - Define `arrivals[p, t, loc] = order[p, t − lead_time[loc], loc]` (zero if `t < lead_time`). Inventory update consumes `arrivals`, not `orders`.
  - Extend the planning horizon to include forward demand visibility so the solver can pre-order. If horizon truncation forces a tail effect, add a terminal salvage value or shortage penalty for unmet forward demand.
  - Emit order rows for **all** periods 1..T (even when `t + lead_time > T`); zero is acceptable but the row must exist.
- **Expected gain:** +0.10 to +0.20 score on lead-time / capacity-tight cases. On `wb_replenishment_with_lead_time`, lifts scores from ~0.60 → ~0.78.
- **Cost:** ~1 hour. No change in problem size; only index shift in the inventory recurrence and a horizon extension.

### Improvement 2 — Hub-Spoke Transshipment + Quality Substitution

- **When to switch:** `wb_replenishment_hub_spoke` cases, or whenever the instruction mentions transfers between locations and/or premium SKUs that may substitute for standard SKUs.
- **Core idea:**
  - Introduce `transfer[hub→spoke, p, t]` integer variables with per-transfer cost in objective. Spoke inventory inflow = transfers only; hub inventory inflow = supplier orders only.
  - Apply weighted cold capacity independently at hub AND each spoke (peak + end-of-period).
  - Add `sub[premium→standard, t, loc]` in demand-fulfillment: `sales_std + sub ≥ min(demand_std, on_hand_std + sub)`; decrement premium inventory by `sub`.
- **Expected gain:** +0.15 to +0.25 score on hub-spoke cases. Lifts `wb_replenishment_hub_spoke` from ~0.50 → ~0.75.
- **Cost:** ~2–3 hours. Variable count grows by ~`|spokes| × |SKUs| × T` for transfers and `|SKUs_premium| × T × |loc|` for substitutions; CBC still tractable at typical scales.

---

## Primary 2: `multi_supplier_procurement_milp`

**Applies to case:** `wb_multi_supplier_procurement`

### Baseline — Effective-Cost Precompute + MILP with Supplier Binaries

- **Starter algorithm:** Precompute `eff_cost[s, p, m]` outside the solver, folding in base price, FX rate, lead-time surcharge, risk premium, duties. Build MILP with:
  - `x[s, p, m]` integer purchase quantities,
  - `y[s]` binary supplier-used,
  - `b[s, m]` binary supplier-active-in-month.
  - Big-M activation: `x[s, p, m] ≤ M · b[s, m]`, `b[s, m] ≤ y[s]`, MOQ: `Σ_p x[s, p, m] ≥ moq[s] · b[s, m]`.
  - Demand satisfaction: `Σ_s x[s, p, m] ≥ demand[p, m]`.
  - Supplier monthly capacity: `Σ_p x[s, p, m] ≤ cap[s, m]`.
- **Scale:** ~5 suppliers × ~20 products × ~12 months (~1.2k int + ~70 binaries) — solves in <30s.
- **Observed score range:** 0.55–0.72 baseline on `wb_multi_supplier_procurement`.
- **Reference code template:** `templates/multi_supplier_procurement_milp.py` — provides precompute, MILP build, and CSV emission scaffold.

**Baseline must-do checklist:**
1. `x[s, p, m]` declared `Integer`.
2. Effective unit cost computed in a **preparation step**, not in solver expressions.
3. All discrete decisions are explicit binaries (one per decision dimension).
4. Output CSV column names match spec exactly with full row coverage.

### Improvement 1 — Lead-Time Surcharge + Reliability Risk Premium (Cost-Layer Enrichment)

- **When to switch:** Instruction references supplier lead times, reliability scores, or risk weighting. Symptom: baseline picks the cheapest nominal supplier but evaluator penalizes late/unreliable orders.
- **Core idea:** Layer additive surcharges into the precomputed effective cost (no model structure change):
  - `eff_cost[s, p, m] += 5` if `lead_time[s] > 7` days.
  - `eff_cost[s, p, m] += 0.10 · (100 − reliability_score[s])`.
  - Apply FX/duty multipliers consistently before adding flat surcharges.
- **Expected gain:** +0.08 to +0.15 score. Pure preprocessing; no impact on solve time.
- **Cost:** ~30 minutes. Single function returning the cost tensor.

### Improvement 2 — Early-Payment Discount via Bilinear Linearization

- **When to switch:** Instruction mentions volume discounts, early-payment discounts, or any "if-condition-then-price-cut" rule. Symptom: baseline ignores discount eligibility and overpays in months where discount triggers were one binary away.
- **Core idea:**
  - Add binary `ep[s, m]` (early-payment-taken).
  - Introduce auxiliary `z[s, m] = ep[s, m] · Σ_p x[s, p, m]` with big-M linearization:
    - `z ≤ M · ep`
    - `z ≤ Σ_p x`
    - `z ≥ Σ_p x − M · (1 − ep)`
    - `z ≥ 0`
    - tie M to supplier monthly capacity, not a generic 10^6.
  - Subtract `discount_rate · price · z` from the objective.
  - For threshold-style discounts (`if qty ≥ T then discount`), add `Σ_p x ≥ T · ep`.
- **Expected gain:** +0.10 to +0.18 score on cases with active discount rules.
- **Cost:** ~1.5 hours. ~`|suppliers| × |months|` extra binaries and continuous auxiliaries; CBC handles trivially.

---

## 跨 Subtype 通用经验

These patterns recur across **both** primaries and are the highest-leverage things to get right on the first attempt.

1. **Integer variables, always.** Order/purchase quantities must be declared `Integer` (PuLP `cat='Integer'` or CP-SAT `IntVar`). Continuous LP relaxations followed by rounding fail evaluator checks ~30% of the time. When splitting an aggregate by share fractions, use **largest-remainder (Hamilton) rounding**, never `int()` truncation.

2. **Precompute fully-loaded effective unit costs outside the solver.** Keep the objective linear (`Σ qty · unit_cost`) and let the solver handle only truly decision-dependent terms (discount activation, MOQ binaries). This works for both inventory and procurement primaries and makes outputs interpretable.

3. **Cold capacity is volumetric and peak-binding.** Whenever cold storage is mentioned: (a) weight by per-SKU `cold_usage`, (b) apply at **every** node (hub AND spokes), (c) enforce at **peak** occupancy (`prev_inv + arrivals`) AND end-of-period — evaluators pick the stricter one. When using scaled integer arithmetic, `math.ceil` LHS coefficients and `math.floor` RHS bounds.

4. **Replay the evaluator's formula before emitting.** Build a post-solve verification pass that recomputes capacity load, demand satisfaction, and total cost using the exact spec formulas. If solver-internal value disagrees with replay, the model is under-constrained — fix before writing CSV.

5. **Output discipline.**
   - Dense grid over **all** (period × SKU × location) or (supplier × product × month), including zero rows.
   - Column names match spec character-for-character (`order_units`, not `order_qty` or `qty`).
   - Cast to `int` before write; no `1.0` floats in integer columns.
   - Row count = product of index cardinalities — verify before emit.

6. **Linearize bilinear (binary × continuous) terms with big-M tied to physical bounds.** Generic `M = 1e6` causes weak LP relaxations and 10× solve times. Tie M to supplier capacity, cold capacity, or demand horizon sums.

7. **Look-ahead beats myopia when capacity is tight.** For both primaries, when the planning horizon contains demand spikes, extend the model's visible horizon and let the solver pre-build. In greedy fallbacks, add a