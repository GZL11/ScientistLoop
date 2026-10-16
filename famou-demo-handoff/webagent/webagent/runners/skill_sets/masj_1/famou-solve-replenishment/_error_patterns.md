# Consolidated Failure Analysis: 18 Optimization Run Patches

## 1. Cold Storage Capacity: Wrong Scope (End-of-Period vs. Peak Occupancy)
**Prevalence: [7/18 runs]** — Patches #1, #3, #4, #5, #10, #11, #12

### Root Cause
The capacity constraint was applied to **end-of-period inventory** only, but evaluators measure cold load at **peak occupancy** — typically right after receipt/arrival, before demand is fulfilled. Several variants:
- LP allowed batches to "net out" negative residuals against positive ones, masking true storage (#1)
- Peak in-period stock = `prev_inv + arrivals` is strictly ≥ end-of-period inventory (#3, #4, #5, #12)
- Some evaluators include in-transit/throughput cold usage, not just stored inventory (#10)
- Pipeline inventory ignored in forward projections (#12)

### Consolidated Fix
For every (DC, period), add **peak-occupancy** capacity constraints alongside (or replacing) end-of-period bounds:
```
∑_p cold_usage[p] · (inventory[p, t-1, dc] + arrivals[p, t, dc]) ≤ cold_capacity[dc]
```
Additionally:
- For multi-batch perishable models, enforce **per-batch cumulative non-negativity** at every period: `Σ_{t'≤t} consumed[batch, t'] ≤ purchase[batch]` for every prefix, not just the lifetime aggregate.
- Apply the constraint to **both** receiving load and end-of-period load; evaluators typically pick the stricter one.
- Replay the evaluator's exact capacity formula on your solution before emitting outputs; if the model and evaluator disagree, the model is under-constrained.

---

## 2. Cold Storage Capacity: Missing Per-SKU `cold_usage` Weighting
**Prevalence: [5/18 runs]** — Patches #8, #9, #10, #11, #17

### Root Cause
The capacity constraint either omitted the per-SKU `cold_usage` coefficient entirely (treating each unit as 1 cube) or applied it only at the hub but not at regional DCs. Evaluator computes `Σ inventory_units · sku.cold_usage`, often producing >2× the unit count for SKUs with cold_usage > 1.

### Consolidated Fix
Cold capacity is **volumetric**, not unit-count. Apply weighted constraints uniformly at **every** location (hub AND spokes):
```
∑_p inventory[p, t, loc] · cold_usage[p] ≤ cold_capacity[loc]   ∀ (t, loc)
```
When using CP-SAT/integer arithmetic, scale both sides consistently (e.g., × 1000) and use `math.ceil` on LHS coefficients, `math.floor` on RHS bounds — never raw `int()` truncation.

---

## 3. Integer / Integrality Violations on Order Quantities
**Prevalence: [4/18 runs]** — Patches #13, #14, #15, #16

### Root Cause
Order variables declared as continuous (`cat='Continuous'`, `LpVariable` without integer flag), or fractional allocations from `total_demand × demand_share` written directly to CSV. Evaluator requires integer `order_units`.

### Consolidated Fix
1. Declare order variables as integer from the start: `LpVariable(..., lowBound=0, cat='Integer')` or CP-SAT `IntVar`.
2. When splitting an aggregate quantity by share fractions, use **largest-remainder (Hamilton) rounding** to preserve the integer global total:
   ```python
   floors = {dc: int(raw[dc]) for dc in dcs}
   remainder = total - sum(floors.values())
   for dc in sorted(dcs, key=lambda d: raw[d]-floors[d], reverse=True)[:remainder]:
       floors[dc] += 1
   ```
3. Defensive cast: `int(round(value))` before CSV write.
4. Pre-write assert: `all(float(v).is_integer() for v in order_units_column)`.

---

## 4. Output Schema / Missing Rows
**Prevalence: [4/18 runs]** — Patches #13, #14, #15, #16

### Root Cause
Solvers wrote only non-zero orders or skipped infeasible periods (e.g., `t + lead_time > T`), and used wrong column names (`order_qty` instead of `order_units`).

### Consolidated Fix
- Always emit a **complete dense grid** over all `(period × SKU × DC)` combinations, including zero-order rows and periods past lead-time horizon.
- Read the task's required column names from the spec before writing; assert header equality.
- Pre-write assert: `len(rows) == N_periods × len(SKUs) × len(DCs)`.

---

## 5. Aggregate / Network-Wide Constraints Applied Locally
**Prevalence: [2/18 runs]** — Patches #17, #18

### Root Cause
Constraints keyed only by `(period, SKU)` (not by DC) are **global pooled limits** but were applied as per-DC variable upper bounds, allowing each of N DCs to independently order up to the cap (Nx overshoot).

### Consolidated Fix
Always inspect the **index keys** of each input table. If a capacity column is not indexed by location, it is aggregate — add a summation constraint:
```python
for t in periods:
    for sku in SKUs:
        model.Add(sum(order[t][dc][sku] for dc in DCs) <= order_cap[t][sku])
```
Per-DC variable bounds are loose; the binding constraint is the sum. General rule: **table indexing reveals constraint scope.**

---

## 6. Hub-Spoke Timing: Same-Period Transshipment Beyond On-Hand
**Prevalence: [2/18 runs]** — Patches #8, #9

### Root Cause
Hub balance equations allowed shipments out in period `t` to draw from period-`t` purchases (cross-docking), but evaluators require shipments to come from **prior-period** ending inventory.

### Consolidated Fix
```
∑_dc replenish[p, t, dc] ≤ hub_inv[p, t-1]    # use previous period
```
Separate "arrivals" from "available for shipment"; only allow same-period flow if the spec explicitly permits cross-docking.

---

## 7. Missing Shelf-Life / FIFO Cohort Modeling
**Prevalence: [2/18 runs]** — Patches #2, #4

### Root Cause
Solvers omitted explicit shelf-life enforcement, relying on waste-cost penalties to implicitly bound inventory. Optimizer hoards stock indefinitely when holding cost < waste cost savings, inflating storage and breaching capacity.

### Consolidated Fix
Model shelf life with **age-indexed cohorts**: `inv[dc, sku, t, age]` for `age = 0..shelf_life-1`. Force `age = shelf_life → waste`. Use FIFO via separate `consume[dc, sku, t, age]` variables. Never rely on waste-cost penalties alone.

---

## 8. Knife-Edge Constraints Without Tolerance Buffer
**Prevalence: [1/18 runs]** — Patch #7

### Root Cause (briefly noted as one-off)
LP solver tolerance + post-rounding produced 2.0001% defect rate vs. 2.0% cap. Mitigation: tighten RHS by ε (e.g., use 1.99% in solver), solve in integers from start, re-validate rounded solution.

---

## 9. Missing Constraint Families (MOQ, Contract Min, Late Penalties)
**Prevalence: [1/18 runs]** — Patch #6

### Root Cause (briefly noted as one-off)
Semi-continuous MOQ constraints (`qty == 0 OR qty ≥ MOQ`) and contract minimums never encoded. Mitigation: introduce binary "active" indicators `z[s,m]` with `MOQ·z ≤ qty ≤ cap·z`. General rule: **build a checklist mapping each input CSV column to a model constraint** before coding.

---

## 10. Substitution Modeled as Phantom Supply
**Prevalence: [1/18 runs]** — Patch #5

### Root Cause (briefly noted as one-off)
Premium-for-standard substitution added as free additive term in balance equation rather than as a transfer that decrements premium inventory. Mitigation: model substitution as a flow that **simultaneously decrements donor stock and satisfies recipient demand**.

---

# Top-Priority Skills to Encode

1. **Capacity scope check** [7/18]: peak-occupancy vs. end-of-period — always constrain the receiving moment, and replay evaluator logic before emitting.
2. **Per-SKU coefficient weighting** [5/18]: capacity is volumetric, not unit-count; apply uniformly at all locations.
3. **Integrality + dense output grid** [4/18 each]: declare integer vars, use largest-remainder rounding for share splits, emit complete `(period × SKU × DC)` tuples with correct column names.
4. **Index-key audit for constraint scope** [2/18]: tables not indexed by location ⇒ aggregate ⇒ require `sum()` constraints.
5. **Pre-emit validation gate** (mentioned in 8+ patches as supporting fix): always replay the evaluator's exact formulas on the solution and assert feasibility before writing CSVs.