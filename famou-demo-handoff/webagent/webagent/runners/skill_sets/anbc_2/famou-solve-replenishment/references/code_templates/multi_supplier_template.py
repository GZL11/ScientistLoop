"""
多供应商采购 MILP 起手模板（子类型 C）
适用:多供应商采购(复杂定价 + 框架合同 + 占比/次品率)风格
  - 8 供应商 × 6 产品 × 4 月
  - 复杂单位成本（汇率 + 进口税 + 长周期 + 风险 + 质检 + 早付折扣）
  - 框架合同 / 起订量 / 占比 / 次品率 / 最少供应商数
"""
import pulp
import pandas as pd


def compute_unit_cost(price_per_unit, fx, duty_rate, lead_time_days,
                      reliability_score, surcharge_long=5.0):
    """不含早付折扣的基础综合单位成本（元）"""
    base = price_per_unit * fx * (1 + duty_rate)
    long_lead = surcharge_long if lead_time_days > 7 else 0
    risk = 0.10 * (100 - reliability_score)
    quality = 0.50 * (1 + (100 - reliability_score) / 100.0)
    return base + long_lead + risk + quality


def solve_procurement(suppliers, pricing, demand_pm, contracts,
                       capacity, min_order, defect_rates, fx, duty,
                       lead_time, reliability, early_pay_eligible,
                       max_share=0.4, max_defect=2.0, min_suppliers=3,
                       time_limit=180, gap=0.005):
    """
    求解多供应商采购 MILP 模型。

    Args:
        suppliers: 供应商列表
        pricing: 价格字典 {(s, p): price}
        demand_pm: 需求字典 {(p, m): demand}
        contracts: 合同字典
        capacity/min_order/defect_rates: 供应商参数
        fx/duty/lead_time/reliability: 成本参数
        early_pay_eligible: 支持早付的供应商集合
        max_share/max_defect/min_suppliers: 约束参数
        time_limit/gap: 求解参数

    Returns:
        MILP 求解结果
    """
    products = sorted({p for p, _ in demand_pm})
    months   = sorted({m for _, m in demand_pm})
    total_demand = sum(demand_pm.values())
    big_M = total_demand * 1.5

    prob = pulp.LpProblem("MultiSupplier", pulp.LpMinimize)

    # ── 变量 ──────────────────────────────────────────────────────────
    buy = {(s, p, m): pulp.LpVariable(f"buy_{s}_{p}_{m}", lowBound=0)
           for s in suppliers for p in products for m in months}
    use = {s: pulp.LpVariable(f"use_{s}", cat='Binary') for s in suppliers}
    active = {(s, m): pulp.LpVariable(f"act_{s}_{m}", cat='Binary')
              for s in suppliers for m in months}
    early = {(s, m): pulp.LpVariable(f"early_{s}_{m}", cat='Binary')
             for s in suppliers for m in months}
    # 早付折扣的双线性线性化：buy_early = buy * early
    buy_early = {(s, p, m): pulp.LpVariable(f"bye_{s}_{p}_{m}", lowBound=0)
                 for s in suppliers for p in products for m in months}

    # ── 需求满足 ─────────────────────────────────────────────────────
    for p in products:
        for m in months:
            prob += pulp.lpSum(buy[(s, p, m)] for s in suppliers) >= demand_pm[(p, m)]

    # ── 月产能上限 ───────────────────────────────────────────────────
    for s in suppliers:
        for m in months:
            prob += pulp.lpSum(buy[(s, p, m)] for p in products) <= capacity[s]

    # ── 起订量（开关） ──────────────────────────────────────────────
    for s in suppliers:
        for m in months:
            prob += pulp.lpSum(buy[(s, p, m)] for p in products) <= big_M * active[s, m]
            prob += pulp.lpSum(buy[(s, p, m)] for p in products) >= min_order[s] * active[s, m]
            # active=1 → use=1
            prob += active[s, m] <= use[s]

    # ── 框架合同（启用 → 满足最低）─────────────────────────────────
    for s, c_min in contracts.items():
        prob += pulp.lpSum(buy[(s, p, m)] for p in products for m in months) \
                >= c_min * use[s]

    # use=0 → 完全不采购
    for s in suppliers:
        prob += pulp.lpSum(buy[(s, p, m)] for p in products for m in months) \
                <= big_M * use[s]

    # ── 至少 min_suppliers 家 ───────────────────────────────────────
    prob += pulp.lpSum(use[s] for s in suppliers) >= min_suppliers

    # ── 单一占比 ≤ max_share ────────────────────────────────────────
    for s in suppliers:
        prob += pulp.lpSum(buy[(s, p, m)] for p in products for m in months) \
                <= max_share * total_demand * 1.0  # 假设需求精确满足

    # ── 加权次品率 ≤ max_defect % ──────────────────────────────────
    prob += pulp.lpSum(defect_rates[s] * buy[(s, p, m)]
                       for s in suppliers for p in products for m in months) \
            <= max_defect * total_demand

    # ── 早付资格限制 ─────────────────────────────────────────────────
    for s in suppliers:
        if s not in early_pay_eligible:
            for m in months:
                prob += early[s, m] == 0

    # ── 早付折扣线性化：buy_early = buy × early ────────────────────
    for s in suppliers:
        for p in products:
            for m in months:
                prob += buy_early[s, p, m] <= big_M * early[s, m]
                prob += buy_early[s, p, m] <= buy[s, p, m]
                prob += buy_early[s, p, m] >= buy[s, p, m] - big_M * (1 - early[s, m])

    # ── 目标函数 ─────────────────────────────────────────────────────
    obj_terms = []
    for s in suppliers:
        for p in products:
            unit = compute_unit_cost(
                pricing[(s, p)], fx[s], duty[s], lead_time[s], reliability[s])
            for m in months:
                obj_terms.append(unit * buy[s, p, m])
                obj_terms.append(-0.01 * unit * buy_early[s, p, m])  # 1% 早付折扣
    prob += pulp.lpSum(obj_terms)

    # ── 求解 ──────────────────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, gapRel=gap, msg=1)
    status = prob.solve(solver)
    print(f"Status: {pulp.LpStatus[status]}, Obj: {pulp.value(prob.objective):.2f}")

    return prob, dict(buy=buy, use=use, active=active, early=early)


def extract_results(vars_, suppliers, products, months,
                     pricing, fx, duty, lead_time, reliability):
    """从求解变量中提取并整理采购结果。"""
    rows = []
    for s in suppliers:
        for p in products:
            for m in months:
                q = pulp.value(vars_['buy'][s, p, m]) or 0
                if q < 1e-6:
                    continue
                unit = compute_unit_cost(
                    pricing[(s, p)], fx[s], duty[s], lead_time[s], reliability[s])
                ep = pulp.value(vars_['early'][s, m]) or 0
                if ep > 0.5:
                    unit *= 0.99
                rows.append({
                    'supplier': s, 'product': p, 'month': m,
                    'quantity': round(q, 2),
                    'unit_cost': round(unit, 4),
                    'total_cost': round(q * unit, 2),
                    'early_payment': bool(ep > 0.5),
                })
    return pd.DataFrame(rows)


if __name__ == '__main__':
    # 用法：
    #   1. 从 supplier_info.csv / supplier_pricing.csv / monthly_demand.csv /
    #      contract_minimums.csv 读取数据，构建上面所有 dict
    #   2. solve_procurement(...)
    #   3. extract_results(...) → procurement_plan.csv
    #   4. 计算 supplier_summary、optimization_result.json
    pass
