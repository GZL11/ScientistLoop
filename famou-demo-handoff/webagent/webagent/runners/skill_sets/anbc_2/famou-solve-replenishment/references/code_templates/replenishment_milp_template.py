"""
多 DC 多周期补货 MILP 起手模板（子类型 A / B / D 共用）
适用：cold_storage、hub_spoke、lead_time 风格补货问题

核心思路：
- 决策变量按 (dc, sku, t) 索引，便于结果提取
- 提前期：第 t 期下单在 t + lead_time[sku] 期到货（>0 时）
- 替代：sub_in（被补入低等级 SKU）== sub_out（出库的高等级 SKU），等量配对
- Hub-Spoke：开关 hub_spoke=True 切换两层网络

替换 load_data() 实现以适配你的数据规格。
"""
import pulp
import pandas as pd


# ── 1. 加载数据（按实际 CSV 字段调整）─────────────────────────────────

def load_data(work_dir):
    """
    加载补货问题数据。

    Args:
        work_dir: 数据目录路径

    Returns:
        包含 DCs, SKUs, T, capacity 等的元组（详见 docstring）
    """
    raise NotImplementedError("根据用户提供的数据字段名实现")


# ── 2. 构建模型 ────────────────────────────────────────────────────────

def build_model(DCs, SKUs, T, capacity, cold_usage, purchase_cost, holding_cost,
                waste_cost, shortage_penalty, shelf_life, lead_time, supplier_cap,
                demand, substitute_pairs,
                hub_spoke=False, central_dc=None, transshipment_cost_per_unit=0.5,
                time_limit=240, gap=0.001):
    """
    构建补货 MILP 模型。

    Args:
        DCs/SKUs/T: 配送中心/产品/规划期数
        capacity/cold_usage: 容量和冷链使用量
        purchase_cost/holding_cost/waste_cost/shortage_penalty: 成本参数
        shelf_life/lead_time: 保质期和提前期
        supplier_cap: 供应商产能
        demand: 需求
        substitute_pairs: 替代产品对
        hub_spoke: 是否使用 Hub-Spoke 网络
        central_dc: 中央 DC
        transshipment_cost_per_unit: 中转成本
        time_limit/gap: 求解参数

    Returns:
        (prob, order, inv, short, waste, sub_in, sub_out) 元组
    """
    PERIODS = list(range(1, T + 1))
    prob = pulp.LpProblem("Replenishment", pulp.LpMinimize)

    if hub_spoke:
        regional = [d for d in DCs if d != central_dc]
    else:
        regional = []

    # ── 决策变量 ──────────────────────────────────────────────────────
    if hub_spoke:
        order = {(sku, t): pulp.LpVariable(f"order_{sku}_{t}", lowBound=0)
                 for sku in SKUs for t in PERIODS}
        allocate = {(dc, sku, t): pulp.LpVariable(f"alloc_{dc}_{sku}_{t}", lowBound=0)
                    for dc in regional for sku in SKUs for t in PERIODS}
    else:
        order = {(dc, sku, t): pulp.LpVariable(f"order_{dc}_{sku}_{t}", lowBound=0)
                 for dc in DCs for sku in SKUs for t in PERIODS}

    inv = {(dc, sku, t): pulp.LpVariable(f"inv_{dc}_{sku}_{t}", lowBound=0)
           for dc in DCs for sku in SKUs for t in PERIODS}
    short = {(dc, sku, t): pulp.LpVariable(f"short_{dc}_{sku}_{t}", lowBound=0)
             for dc in DCs for sku in SKUs for t in PERIODS}
    waste = {(dc, sku, t): pulp.LpVariable(f"waste_{dc}_{sku}_{t}", lowBound=0)
             for dc in DCs for sku in SKUs for t in PERIODS}

    # 替代变量（per dc, per (high, low) 对, per period）
    sub_in  = {}
    sub_out = {}
    for dc in DCs:
        for hi, lo in substitute_pairs:
            for t in PERIODS:
                sub_in[(dc, lo, hi, t)] = pulp.LpVariable(
                    f"subin_{dc}_{lo}_{hi}_{t}", lowBound=0)
                sub_out[(dc, hi, lo, t)] = sub_in[(dc, lo, hi, t)]   # 1:1 等量配对

    # ── 库存守恒 ──────────────────────────────────────────────────────
    for dc in DCs:
        for sku in SKUs:
            for t in PERIODS:
                # 到货量
                if hub_spoke and dc != central_dc:
                    arrival = allocate.get((dc, sku, t), 0)
                elif hub_spoke and dc == central_dc:
                    arrival = order[(sku, t - lead_time[sku])] \
                              if t > lead_time[sku] else 0
                else:
                    arrival = order[(dc, sku, t - lead_time[sku])] \
                              if t > lead_time[sku] else 0

                # 替代项：低等级 sku 接受替代 → +sub_in；高等级 sku 出库被替代 → -sub_out
                sub_in_total  = pulp.lpSum(sub_in[(dc, sku, hi, t)]
                                            for hi, lo in substitute_pairs if lo == sku)
                sub_out_total = pulp.lpSum(sub_out[(dc, sku, lo, t)]
                                            for hi, lo in substitute_pairs if hi == sku)

                inv_prev = inv[(dc, sku, t - 1)] if t > 1 else 0

                prob += (
                    inv[(dc, sku, t)] == inv_prev + arrival
                    - demand.get((dc, sku, t), 0)
                    + short[(dc, sku, t)]
                    - waste[(dc, sku, t)]
                    + sub_in_total - sub_out_total
                )

                # 保质期近似（避免囤超过保质期能消耗的量）
                if shelf_life[sku] < 999:
                    horizon = range(t, min(T, t + shelf_life[sku]) + 1)
                    future = sum(demand.get((dc, sku, t2), 0) for t2 in horizon)
                    prob += inv[(dc, sku, t)] <= future

    # ── 容量约束（按 cold_usage 加权）─────────────────────────────────
    for dc in DCs:
        for t in PERIODS:
            prob += pulp.lpSum(inv[(dc, sku, t)] * cold_usage[sku] for sku in SKUs) \
                    <= capacity[dc]

    # ── 产能约束（全网合计）──────────────────────────────────────────
    for sku in SKUs:
        for t in PERIODS:
            cap = supplier_cap.get((sku, t), supplier_cap.get(sku, float('inf')))
            if hub_spoke:
                prob += order[(sku, t)] <= cap
            else:
                prob += pulp.lpSum(order[(dc, sku, t)] for dc in DCs) <= cap

    # ── Hub-Spoke：中央仓库存守恒 ───────────────────────────────────
    if hub_spoke:
        for sku in SKUs:
            for t in PERIODS:
                arrival = order[(sku, t - lead_time[sku])] \
                          if t > lead_time[sku] else 0
                inv_prev = inv[(central_dc, sku, t - 1)] if t > 1 else 0
                prob += (
                    inv[(central_dc, sku, t)] == inv_prev + arrival
                    - pulp.lpSum(allocate[(dc, sku, t)] for dc in regional)
                )

    # ── 目标函数 ──────────────────────────────────────────────────────
    if hub_spoke:
        purchase = pulp.lpSum(purchase_cost[sku] * order[(sku, t)]
                              for sku in SKUs for t in PERIODS)
        transport = pulp.lpSum(transshipment_cost_per_unit * allocate[(dc, sku, t)]
                                for dc in regional for sku in SKUs for t in PERIODS)
    else:
        purchase = pulp.lpSum(purchase_cost[sku] * order[(dc, sku, t)]
                              for dc in DCs for sku in SKUs for t in PERIODS)
        transport = 0

    holding = pulp.lpSum(holding_cost[sku] * inv[(dc, sku, t)]
                         for dc in DCs for sku in SKUs for t in PERIODS)
    shortage_cost = pulp.lpSum(shortage_penalty[sku] * short[(dc, sku, t)]
                                for dc in DCs for sku in SKUs for t in PERIODS)
    waste_total = pulp.lpSum(waste_cost[sku] * waste[(dc, sku, t)]
                              for dc in DCs for sku in SKUs for t in PERIODS)
    prob += purchase + transport + holding + shortage_cost + waste_total

    # ── 求解 ──────────────────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, gapRel=gap, msg=1)
    status = prob.solve(solver)
    print(f"Status: {pulp.LpStatus[status]}, Obj: {pulp.value(prob.objective):.2f}")

    return prob, dict(order=order, inv=inv, short=short, waste=waste,
                      sub_in=sub_in, allocate=(allocate if hub_spoke else None))


# ── 3. 验证（独立反向）──────────────────────────────────────────────

def validate(vars_, DCs, SKUs, T, capacity, cold_usage, demand, shelf_life,
             substitute_pairs, hub_spoke=False, central_dc=None):
    """校验补货方案的可行性，返回问题列表。"""
    issues = []
    inv = vars_['inv']; short = vars_['short']; waste = vars_['waste']
    for dc in DCs:
        for t in range(1, T + 1):
            cap_used = sum((pulp.value(inv[(dc, sku, t)]) or 0) * cold_usage[sku]
                            for sku in SKUs)
            if cap_used > capacity[dc] + 1e-3:
                issues.append(f"{dc} t={t} 容量超出 {cap_used:.2f} > {capacity[dc]}")
    for dc in DCs:
        for sku in SKUs:
            for t in range(1, T + 1):
                if (pulp.value(inv[(dc, sku, t)]) or 0) < -1e-6:
                    issues.append(f"{dc} {sku} t={t} 库存为负")
                if (pulp.value(short[(dc, sku, t)]) or 0) < -1e-6:
                    issues.append(f"{dc} {sku} t={t} 缺货为负")
    return issues


# ── 4. 提取结果 ──────────────────────────────────────────────────────

def extract_to_df(vars_, DCs, SKUs, T, demand, hub_spoke=False, central_dc=None):
    """将 MILP 求解结果提取为 DataFrame。"""
    rows = []
    for dc in DCs:
        for sku in SKUs:
            for t in range(1, T + 1):
                if hub_spoke and dc == central_dc:
                    od = pulp.value(vars_['order'][(sku, t)]) or 0
                elif hub_spoke:
                    od = pulp.value(vars_['allocate'][(dc, sku, t)]) or 0
                else:
                    od = pulp.value(vars_['order'][(dc, sku, t)]) or 0
                rows.append({
                    'dc': dc, 'product': sku, 'period': t,
                    'order_qty':     round(od, 2),
                    'end_inventory': round(pulp.value(vars_['inv'][(dc, sku, t)]) or 0, 2),
                    'demand':        demand.get((dc, sku, t), 0),
                    'shortage':      round(pulp.value(vars_['short'][(dc, sku, t)]) or 0, 2),
                    'waste':         round(pulp.value(vars_['waste'][(dc, sku, t)]) or 0, 2),
                })
    return pd.DataFrame(rows)


if __name__ == '__main__':
    # 1. 用 load_data() 填入实参
    # 2. 调用 build_model(...)
    # 3. validate()，issues 为空再交付
    # 4. extract_to_df() 写 CSV
    # 5. 生成 HTML 可视化
    pass
