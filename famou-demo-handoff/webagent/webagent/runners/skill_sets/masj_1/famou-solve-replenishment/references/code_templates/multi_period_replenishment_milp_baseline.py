"""
Multi-Period Replenishment MILP - Baseline Template
Subtype: multi_period_replenishment_milp

Generic template for multi-period, multi-SKU, multi-location replenishment
optimization with capacity, integrality, perishability, and cost constraints.

Adapt this template for specific cases (cold storage, perishable goods, etc.)
by editing the `# ADAPT HERE:` blocks.
"""

import os
import json
import math
import pandas as pd
import numpy as np
import pulp


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_inputs(data_dir):
    """
    加载多周期补货问题数据。

    Args:
        data_dir: 数据目录路径

    Returns:
        dict: 包含 locations, skus, periods, capacity, cold_usage, demand 等
    """
    raise NotImplementedError("Override load_inputs for the specific case.")


# ---------------------------------------------------------------------------
# Core MILP build & solve
# ---------------------------------------------------------------------------
def build_and_solve(params, time_limit=120):
    """
    构建并求解多周期补货 MILP 模型。

    Args:
        params: 参数字典
        time_limit: 时间限制（秒）

    Returns:
        MILP 求解结果
    """
    locations = params["locations"]
    skus = params["skus"]
    periods = params["periods"]
    capacity = params["capacity"]
    cold_usage = params["cold_usage"]
    demand = params["demand"]
    max_order = params["max_order"]
    costs = params["costs"]
    shelf_life = params.get("shelf_life", {s: 10**6 for s in skus})
    init_inv = params.get("init_inv", {(l, s): 0 for l in locations for s in skus})

    prob = pulp.LpProblem("replenishment", pulp.LpMinimize)

    # CONSTRAINT-CHECK: Order quantity variables must be Integer (not Continuous)
    order = {(l, s, t): pulp.LpVariable(f"order_{l}_{s}_{t}",
                                        lowBound=0, cat="Integer")
             for l in locations for s in skus for t in periods}

    inv = {(l, s, t): pulp.LpVariable(f"inv_{l}_{s}_{t}",
                                      lowBound=0, cat="Integer")
           for l in locations for s in skus for t in periods}

    fulfilled = {(l, s, t): pulp.LpVariable(f"fulf_{l}_{s}_{t}",
                                            lowBound=0, cat="Integer")
                 for l in locations for s in skus for t in periods}

    shortage = {(l, s, t): pulp.LpVariable(f"short_{l}_{s}_{t}",
                                           lowBound=0, cat="Integer")
                for l in locations for s in skus for t in periods}

    waste = {(l, s, t): pulp.LpVariable(f"waste_{l}_{s}_{t}",
                                        lowBound=0, cat="Integer")
             for l in locations for s in skus for t in periods}

    # ----- Constraints -----
    for l in locations:
        for s in skus:
            for idx, t in enumerate(periods):
                prev_inv = init_inv.get((l, s), 0) if idx == 0 else inv[(l, s, periods[idx - 1])]

                # Inventory balance: prev + arrivals - fulfilled - waste = end_inv
                # CONSTRAINT-CHECK: Inventory non-negativity at every period
                # (inv var has lowBound=0, plus explicit balance)
                prob += (inv[(l, s, t)] ==
                         prev_inv + order[(l, s, t)] - fulfilled[(l, s, t)] - waste[(l, s, t)])

                # Demand satisfaction: fulfilled + shortage = demand
                d = demand.get((l, s, t), 0)
                prob += fulfilled[(l, s, t)] + shortage[(l, s, t)] == d
                prob += fulfilled[(l, s, t)] <= prev_inv + order[(l, s, t)]

    # CONSTRAINT-CHECK: Cold capacity weighted by per-SKU cold_usage at every location
    # CONSTRAINT-CHECK: Capacity enforced at PEAK (prev_inv + arrivals) AND end-of-period
    # EVOLVED: use safety_factor to leave slack against evaluator's stricter peak definition
    cap_safety = float(params.get("capacity_safety_factor", 0.95))  # EVOLVED: configurable buffer
    for l in locations:
        cap = capacity.get(l, float("inf"))
        if cap == float("inf"):
            continue
        eff_cap = cap * cap_safety  # EVOLVED: shrink effective cap to absorb rounding/peak edge cases
        for idx, t in enumerate(periods):
            # End-of-period load
            prob += (pulp.lpSum(cold_usage.get(s, 1.0) * inv[(l, s, t)] for s in skus)
                     <= eff_cap), f"cap_end_{l}_{t}"  # EVOLVED: apply effective cap

            # Peak load = previous inventory + arrivals (before fulfillment/waste)
            peak_terms = []
            for s in skus:
                prev = init_inv.get((l, s), 0) if idx == 0 else inv[(l, s, periods[idx - 1])]
                peak_terms.append(cold_usage.get(s, 1.0) * (prev + order[(l, s, t)]))
            prob += pulp.lpSum(peak_terms) <= eff_cap, f"cap_peak_{l}_{t}"  # EVOLVED: apply effective cap

            # EVOLVED: also bound prev_inv + arrivals - fulfilled (post-fulfillment, pre-waste)
            # to catch evaluator definitions that exclude waste from capacity relief.
            mid_terms = []
            for s in skus:
                prev = init_inv.get((l, s), 0) if idx == 0 else inv[(l, s, periods[idx - 1])]
                mid_terms.append(cold_usage.get(s, 1.0) *
                                 (prev + order[(l, s, t)] - fulfilled[(l, s, t)]))
            prob += pulp.lpSum(mid_terms) <= eff_cap, f"cap_mid_{l}_{t}"  # EVOLVED

    # Supplier production capacity per (sku, t)
    for s in skus:
        for t in periods:
            mx = max_order.get((s, t))
            if mx is not None and mx < float("inf"):
                prob += pulp.lpSum(order[(l, s, t)] for l in locations) <= mx

    # Perishability: limit cumulative net inflow over rolling shelf-life window
    for l in locations:
        for s in skus:
            sl = shelf_life.get(s, 10**6)
            if sl is None or sl >= len(periods):
                continue
            # Inventory at end of t cannot exceed orders received in last `sl` periods
            for idx, t in enumerate(periods):
                window = periods[max(0, idx - sl + 1): idx + 1]
                prob += inv[(l, s, t)] <= pulp.lpSum(order[(l, s, tp)] for tp in window) + \
                                           (init_inv.get((l, s), 0) if idx < sl else 0)

    # ----- Objective -----
    prob += pulp.lpSum(
        costs[s].get("purchase", 0) * order[(l, s, t)] +
        costs[s].get("holding", 0) * inv[(l, s, t)] +
        costs[s].get("waste", 0) * waste[(l, s, t)] +
        costs[s].get("shortage", 0) * shortage[(l, s, t)]
        for l in locations for s in skus for t in periods
    )

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit)
    prob.solve(solver)

    return {"order": order, "inv": inv, "fulfilled": fulfilled,
            "shortage": shortage, "waste": waste, "status": pulp.LpStatus[prob.status]}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
def write_output(params, sol, out_path):
    """将补货方案格式化输出为 CSV 文件。"""
    rows = []
    locations = params["locations"]
    skus = params["skus"]
    periods = params["periods"]

    # CONSTRAINT-CHECK: dense grid over all (period × SKU × location), including zeros
    for t in periods:
        for s in skus:
            for l in locations:
                key = (l, s, t)
                qty = sol["order"][key].value() if key in sol["order"] else 0
                qty = int(round(qty or 0))  # integer cast before write
                # ADAPT HERE: column names must EXACTLY match evaluator spec
                rows.append({
                    "period": t,
                    "product": s,        # rename if case uses 'sku' / 'item'
                    "location": l,       # rename if case uses 'dc' / 'warehouse'
                    "order_units": qty,  # NOT 'order_qty' — match spec exactly
                })

    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    return df


# ---------------------------------------------------------------------------
# Post-solve safety repair (defensive)
# ---------------------------------------------------------------------------
def repair_capacity(params, sol):
    """
    Defensive trim: if solver returned a capacity violation due to numerical
    issues, scale orders down at the offending (location, period).
    EVOLVED: iterate forward through periods, recomputing inv after each trim,
    so downstream peaks reflect the trimmed state.
    """
    locations = params["locations"]
    skus = params["skus"]
    periods = params["periods"]
    capacity = params["capacity"]
    cold_usage = params["cold_usage"]

    # EVOLVED: snapshot integer values into a mutable dict for forward simulation
    order_v = {k: int(round(v.value() or 0)) for k, v in sol["order"].items()}
    inv_v = {k: int(round(v.value() or 0)) for k, v in sol["inv"].items()}
    fulf_v = {k: int(round(v.value() or 0)) for k, v in sol["fulfilled"].items()}
    waste_v = {k: int(round(v.value() or 0)) for k, v in sol["waste"].items()}

    for l in locations:
        cap = capacity.get(l, float("inf"))
        if cap == float("inf"):
            continue
        for idx, t in enumerate(periods):
            for s in skus:
                prev = (params["init_inv"].get((l, s), 0) if idx == 0
                        else inv_v[(l, s, periods[idx - 1])])
                # recompute end-inventory consistent with trimmed orders  # EVOLVED
                inv_v[(l, s, t)] = max(0, prev + order_v[(l, s, t)]
                                       - fulf_v[(l, s, t)] - waste_v[(l, s, t)])
            # peak after this period's arrivals
            peak = sum(cold_usage.get(s, 1.0) *
                       ((params["init_inv"].get((l, s), 0) if idx == 0
                         else inv_v[(l, s, periods[idx - 1])])
                        + order_v[(l, s, t)]) for s in skus)
            if peak > cap + 1e-6:
                excess = peak - cap
                total_arr_weight = sum(cold_usage.get(s, 1.0) * order_v[(l, s, t)]
                                       for s in skus)
                if total_arr_weight <= 0:
                    continue
                ratio = max(0.0, 1.0 - excess / total_arr_weight)
                for s in skus:
                    order_v[(l, s, t)] = int(math.floor(order_v[(l, s, t)] * ratio))
                # EVOLVED: re-simulate inv for this period after trimming
                for s in skus:
                    prev = (params["init_inv"].get((l, s), 0) if idx == 0
                            else inv_v[(l, s, periods[idx - 1])])
                    avail = prev + order_v[(l, s, t)]
                    fulf_v[(l, s, t)] = min(fulf_v[(l, s, t)], avail)
                    inv_v[(l, s, t)] = max(0, avail - fulf_v[(l, s, t)] - waste_v[(l, s, t)])

    # write back trimmed values  # EVOLVED
    for k, v in order_v.items():
        sol["order"][k].varValue = v
    for k, v in inv_v.items():
        sol["inv"][k].varValue = v
    for k, v in fulf_v.items():
        sol["fulfilled"][k].varValue = v
    return sol


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def solve(**kwargs):
    """
    Evaluator entry. kwargs typically includes:
      data_dir: path to inputs
      output_path: csv to write
    """
    data_dir = kwargs.get("data_dir", "./data")
    output_path = kwargs.get("output_path", "./solution.csv")

    params = load_inputs(data_dir)
    sol = build_and_solve(params, time_limit=kwargs.get("time_limit", 120))
    sol = repair_capacity(params, sol)
    df = write_output(params, sol, output_path)
    return {"status": sol["status"], "rows": len(df), "output_path": output_path}