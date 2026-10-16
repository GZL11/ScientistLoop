"""
子类型 B — 多产线生产排程（MILP）起手模板
适用：chemical plant scheduling, multi-line production, 换产+外包+逾期惩罚
"""
import pulp
import csv
import pandas as pd

# ── 1. 读取数据（按实际字段名修改）──────────────────────────────────────────

def load_data(data_dir):
    """
    返回示例结构：
    products: [{id, category, demand, deadline, priority}]
    lines:    [{id, categories, daily_capacity}]  # categories: 该产线可生产的产品类型
    params: {changeover_same, changeover_cross, outsource_unit_cost, outsource_max,
             storage_cost_per_ton_day, late_penalty_per_day, night_shift_extra_cap,
             night_shift_cost_per_ton, days}
    """
    raise NotImplementedError("根据实际数据文件实现加载逻辑")

# ── 2. 建模────────────────────────────────────────────────────────────────

def build_and_solve(products, lines, params, time_limit=600):
    """
    构建并求解多产线生产排程 MILP 模型。

    Args:
        products: 产品列表 [{id, category, demand, deadline, priority}]
        lines: 产线列表 [{id, categories, daily_capacity}]
        params: 参数字典
        time_limit: 时间限制（秒）

    Returns:
        (prob, x, qty, outsource, lateness) 元组
    """
    P = [p['id'] for p in products]
    L = [l['id'] for l in lines]
    D = list(range(1, params['days'] + 1))

    prob = pulp.LpProblem("MultiLineScheduling", pulp.LpMinimize)

    # 决策变量
    x = {(l, p, d): pulp.LpVariable(f"x_{l}_{p}_{d}", cat='Binary')
         for l in L for p in P for d in D}
    qty = {(l, p, d): pulp.LpVariable(f"qty_{l}_{p}_{d}", lowBound=0)
           for l in L for p in P for d in D}
    changeover = {(l, d): pulp.LpVariable(f"co_{l}_{d}", cat='Binary')
                  for l in L for d in D}
    outsource = {(p, d): pulp.LpVariable(f"out_{p}_{d}", lowBound=0)
                 for p in P for d in D}
    lateness = {p: pulp.LpVariable(f"late_{p}", lowBound=0) for p in P}

    # 约束：每产线每天最多一种产品
    for l in L:
        for d in D:
            prob += pulp.lpSum(x[l, p, d] for p in P) <= 1

    # 约束：产量 ≤ 容量（考虑换产减产）
    for l in L:
        cap = [li for li in lines if li['id'] == l][0]['daily_capacity']
        for d in D:
            for p in P:
                # 换产时产能 × 0.7
                prob += qty[l, p, d] <= cap * (x[l, p, d] - 0.3 * changeover[l, d])

    # 约束：换产逻辑（前后天产品不同则换产=1）
    # 简化：changeover[l,d] >= x[l,p,d] + x[l,p,d-1] - 1 对每个 p ... 或用辅助变量
    # 此处用大 M 近似：若 d>1，且前一天产品 p1，今天产品 p2≠p1，则换产
    # （精确建模需引入产品-天二元变量的乘积展开，或用额外约束）

    # 约束：需求满足（含逾期）
    for p_data in products:
        p = p_data['id']
        deadline = p_data['deadline']
        demand = p_data['demand']
        prob += (
            pulp.lpSum(qty[l, p, d] for l in L for d in D if d <= deadline + lateness[p]) +
            pulp.lpSum(outsource[p, d] for d in D)
            >= demand
        )

    # 外包总量上限
    prob += pulp.lpSum(outsource[p, d] for p in P for d in D) <= params['outsource_max']

    # 目标函数（示意，按实际成本结构修改）
    changeover_cost = pulp.lpSum(
        params['changeover_same'] * changeover[l, d]
        for l in L for d in D
    )
    outsource_cost = pulp.lpSum(
        params['outsource_unit_cost'] * outsource[p, d]
        for p in P for d in D
    )
    lateness_cost = pulp.lpSum(
        p_data['late_penalty'] * lateness[p_data['id']]
        for p_data in products
    )
    # 库存持有成本（按产量 × 完成到截止日期的提前天数估算）
    # 此处简化，实际需引入库存变量

    prob += changeover_cost + outsource_cost + lateness_cost

    # 求解
    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, gapRel=0.005, msg=1)
    status = prob.solve(solver)

    print(f"Status: {pulp.LpStatus[status]}")
    print(f"Objective: {pulp.value(prob.objective):.2f}")
    return prob, x, qty, outsource, lateness

# ── 3. 结果提取────────────────────────────────────────────────────────────

def extract_results(prob, x, qty, outsource, lateness, products, lines, params):
    """
    提取 MILP 求解结果为 DataFrame。

    Args:
        prob: MILP 问题对象
        x: 决策变量（产品-产线-天）
        qty: 产量变量
        outsource: 外包变量
        lateness: 逾期变量
        products: 产品列表
        lines: 产线列表
        params: 参数字典

    Returns:
        pd.DataFrame: 包含 line, day, product, qty, outsource, lateness_days 列
    """
    results = []
    for l in [li['id'] for li in lines]:
        for d in range(1, params['days'] + 1):
            for p_data in products:
                p = p_data['id']
                if pulp.value(x[l, p, d]) is not None and pulp.value(x[l, p, d]) > 0.5:
                    results.append({
                        'line': l, 'day': d, 'product': p,
                        'qty': round(pulp.value(qty[l, p, d]) or 0, 2),
                        'outsource': round(pulp.value(outsource[p, d]) or 0, 2),
                        'lateness_days': round(pulp.value(lateness[p]) or 0, 1),
                    })
    return pd.DataFrame(results)

if __name__ == '__main__':
    # 示例用法：替换为实际数据加载
    # products, lines, params = load_data('./data')
    # prob, x, qty, outsource, lateness = build_and_solve(products, lines, params)
    # df = extract_results(prob, x, qty, outsource, lateness, products, lines, params)
    # df.to_csv('schedule.csv', index=False)
    print("修改 load_data 后运行")
