# Replenishment Subtypes

This document maps replenishment-skill cases to a small set of primary algorithmic templates, lists the reusable extension recipes that decorate them, and specifies graceful-degradation rules for unrecognized cases.

---

## 决策树 (Decision Tree)

Use this tree to route a new case to a primary subtype:

```
新 case 进入
│
├─ 涉及多周期库存推进 (inv[t] = inv[t-1] + arrivals - sales - spoilage)?
│   │
│   ├─ 是 ──► 是否有冷库 / 加权容量约束 (cold_usage 按 SKU 加权)?
│   │           │
│   │           ├─ 是 ──► **multi_period_replenishment_milp**
│   │           │         (含 hub-spoke、lead-time、cold storage 等变体)
│   │           │
│   │           └─ 否 ──► 仍归 **multi_period_replenishment_milp**
│   │                     (cold capacity 退化为通用容量约束)
│   │
│   └─ 否 ──► 是否在多个供应商之间做选择, 含折扣/风险/MOQ/汇率等修饰?
│               │
│               ├─ 是 ──► **multi_supplier_procurement_milp**
│               │
│               └─ 否 ──► 见 `## 兜底: other`
│
└─ 既非多周期推进, 也非多供应商选择 ──► 见 `## 兜底: other`
```

Quick keywords:
- "cold storage", "cold_usage", "spoilage", "horizon T weeks", "DC/warehouse", "hub/spoke", "lead time" → `multi_period_replenishment_milp`
- "supplier selection", "early-payment discount", "lead-time surcharge", "risk premium", "FX", "MOQ" → `multi_supplier_procurement_milp`

---

## primary: multi_period_replenishment_milp

**Discriminator.** Instruction describes multi-period inventory replenishment with cold storage capacity, per-SKU `cold_usage`, and ordering decisions over a horizon at one or more DCs/warehouses.

**Algorithm skeleton.**
Build a MILP / CP-SAT model over `(period, SKU, location)` with **integer** order variables. Precompute effective unit costs (purchase + holding + shortage + surcharges). Simulate inventory state period-by-period:

```
inv[t] = inv[t-1] + arrivals[t] - sales[t] - spoilage[t]
```

Enforce cold capacity, weighted by per-SKU `cold_usage`, at **both** peak (post-arrival) and end-of-period. Minimize total cost (purchase + holding + shortage + spoilage). Emit a **dense** output grid over all `(period × SKU × location)`.

**Core constraints.**
1. Order quantity variables must be declared as **Integer** (not Continuous).
2. Cold capacity constraint must be weighted by per-SKU `cold_usage` at every storage location.
3. Cold capacity must be enforced at **peak** occupancy (`prev_inv + arrivals`) **and** end-of-period — not only end-of-period.
4. Inventory non-negativity enforced at every period (no netting across periods).
5. Output CSV must contain a **complete dense grid** over all `(period × SKU × location)`, including zero-order rows.
6. Output column names must exactly match spec (e.g., `order_units`, not `order_qty`); integer cast before write.

---

## primary: multi_supplier_procurement_milp

**Discriminator.** Instruction describes selecting among multiple suppliers with conditional cost modifiers (discounts, surcharges, risk premiums, MOQs) over a planning horizon, without cold storage as a primary bottleneck.

**Algorithm skeleton.**
Precompute fully-loaded effective unit cost `cost[supplier, product, month]` folding in price, lead-time surcharge, risk premium, and FX. Build a MILP with:

- integer purchase quantities `x[s,p,m]`
- binary supplier-used `y[s]`
- binary month-active `b[s,m]`
- binary discount-taken `ep[s,m]`

Linearize binary × continuous terms (e.g., `discount × qty`) via auxiliary variables with big-M. Minimize `Σ effective_cost · x − discount_savings`, subject to demand satisfaction, supplier capacity, and portfolio rules.

**Core constraints.**
1. Purchase quantities declared as **Integer** variables.
2. All discrete decisions (supplier-used, discount-taken) modeled as explicit **binaries**.
3. Bilinear terms (binary × continuous) **linearized** via auxiliary variables with big-M tied to capacity.
4. Effective unit cost precomputed **outside** the solver, including lead-time surcharge and risk premium.
5. Output CSV uses exact required column names with **complete row coverage**.

---

## Extensions

Reusable recipes layered on top of a primary:

### `supplier_weekly_capacity`
Add per-week supplier capacity constraint: `Σ_p order[p,t] ≤ supplier_capacity[t]`. Allow pre-ordering by enabling orders in earlier weeks, but constrain cold capacity to absorb the pre-built inventory **at peak occupancy**.

### `pre_build_lookahead`
When capacity is tight near peak demand weeks, augment the model to look ahead: include forward demand in the planning horizon so the solver can pre-build. If using a greedy fallback, add `buffer = min(future_demand * 0.2, cap_slack)`.

### `early_payment_discount`
Add binary `ep[s,m]` indicating early-payment for supplier `s` in month `m`. Introduce auxiliary `z[s,m] = ep[s,m] · qty[s,m]` with big-M linearization:
```
z ≤ M · ep
z ≤ qty
z ≥ qty − M · (1 − ep)
z ≥ 0
```
Subtract `0.01 · price · z` from the objective.

### `lead_time_surcharge`
During effective-cost precomputation, add **$5/unit** to suppliers with `lead_time > 7` days:
`eff_cost[s,p,m] += 5  if lead_time[s] > 7`.

### `reliability_risk_premium`
During effective-cost precomputation:
`eff_cost[s,p,m] += 0.10 * (100 - reliability_score[s])`.

### `hub_spoke_transshipment`
Add a hub location with its own inventory state. Decision variables: `order[hub, t]` from supplier, `transfer[hub→spoke, p, t]` with per-transfer cost. Spoke inventory only flows from hub transfers. Apply weighted cold capacity **at hub AND each spoke** independently.

### `quality_substitution`
Allow premium SKU to satisfy standard SKU demand when standard is short. Add variable `sub[premium→standard, t, loc]` in the demand-fulfillment equation:
`sales_std + sub ≥ demand_std` (capped by available premium inventory). Decrement premium inventory by `sub`.

### `weighted_cold_capacity_at_all_nodes`
Apply `Σ_p inv[p,t,loc] · cold_usage[p] ≤ cold_capacity[loc]` at **every** location (hub and all spokes), not only the hub. Enforce both at peak (post-arrival / post-transfer-in) and end-of-period.

### `lead_time_arrivals`
Define `arrivals[p,t,loc] = order[p, t − lead_time[loc], loc]` (zero if `t < lead_time`). Inventory update uses **arrivals**, not orders. Emit order rows for **all** periods `1..T` even when `t + lead_time > T` (zero is acceptable but the row must exist).

---

## case → subtype 映射

| case | primary | extensions | notes |
|---|---|---|---|
| `wb_cold_storage_replenishment` | `multi_period_replenishment_milp` | `supplier_weekly_capacity`, `pre_build_lookahead` | 单 DC 冷库; 注意 supplier 周容量 + peak occupancy 联合约束 |
| `wb_multi_supplier_procurement` | `multi_supplier_procurement_milp` | `early_payment_discount`, `lead_time_surcharge`, `reliability_risk_premium` | 全部 cost modifier 应在 solver 外预计算; 折扣需 big-M 线性化 |
| `wb_replenishment_hub_spoke` | `multi_period_replenishment_milp` | `hub_spoke_transshipment`, `quality_substitution`, `weighted_cold_capacity_at_all_nodes` | 每个 spoke 独立冷库容量; premium→standard 替代受 premium 库存上限约束 |
| `wb_replenishment_with_lead_time` | `multi_period_replenish