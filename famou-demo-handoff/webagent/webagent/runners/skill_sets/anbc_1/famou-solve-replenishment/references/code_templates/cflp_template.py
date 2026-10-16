"""
容量选址 (CFLP) MILP 起手模板（子类型 E）
适用:容量选址(选哪些设施开 + 客户分配)风格
"""
import pulp
import pandas as pd


def solve_cflp(facilities, customers, fixed_cost, capacity, demand,
               transport_cost, time_limit=240, gap=0.005):
    """
    求解 CFLP 容量选址问题。

    Args:
        facilities: 设施 ID 列表
        customers: 客户 ID 列表
        fixed_cost: 固定成本字典 {facility: cost}
        capacity: 容量字典 {facility: capacity}
        demand: 需求字典 {customer: demand}
        transport_cost: 运输成本字典 {(customer, facility): cost}
        time_limit: 时间限制（秒）
        gap: 相对 gap 容差

    Returns:
        (prob, open_f, assign) 元组
    """
    prob = pulp.LpProblem("CFLP", pulp.LpMinimize)

    open_f = {f: pulp.LpVariable(f"open_{f}", cat='Binary') for f in facilities}
    assign = {(c, f): pulp.LpVariable(f"asg_{c}_{f}", cat='Binary')
              for c in customers for f in facilities}

    # 每客户唯一分配
    for c in customers:
        prob += pulp.lpSum(assign[c, f] for f in facilities) == 1

    # 容量
    for f in facilities:
        prob += pulp.lpSum(demand[c] * assign[c, f] for c in customers) \
                <= capacity[f] * open_f[f]

    # 必须开了才能分
    for c in customers:
        for f in facilities:
            prob += assign[c, f] <= open_f[f]

    # 目标
    prob += (pulp.lpSum(fixed_cost[f] * open_f[f] for f in facilities)
             + pulp.lpSum(transport_cost[c, f] * demand[c] * assign[c, f]
                          for c in customers for f in facilities))

    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, gapRel=gap, msg=1)
    status = prob.solve(solver)
    print(f"Status: {pulp.LpStatus[status]}, Obj: {pulp.value(prob.objective):.2f}")

    return prob, open_f, assign


def extract_results(open_f, assign, facilities, customers, demand):
    """
    提取 CFLP 求解结果。

    Args:
        open_f: 设施开启变量字典
        assign: 分配变量字典
        facilities: 设施列表
        customers: 客户列表
        demand: 需求量字典

    Returns:
        (opened, pd.DataFrame): 开启的设施列表和分配结果表
    """
    opened = [f for f in facilities if (pulp.value(open_f[f]) or 0) > 0.5]
    rows = []
    for c in customers:
        for f in facilities:
            if (pulp.value(assign[c, f]) or 0) > 0.5:
                rows.append({'customer': c, 'facility': f, 'demand': demand[c]})
                break
    return opened, pd.DataFrame(rows)


if __name__ == '__main__':
    # 1. load 数据：fixed_cost, capacity, demand, transport_cost
    # 2. solve_cflp(...)
    # 3. extract_results(...) → result.json + assignments.csv
    pass
