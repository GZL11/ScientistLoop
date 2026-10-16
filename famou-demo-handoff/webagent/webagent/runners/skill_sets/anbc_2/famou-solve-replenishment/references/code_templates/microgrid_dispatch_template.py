"""
微电网能源调度 MILP 起手模板（子类型 F）
适用:储能 + 光伏 + 电网 ToU 调度风格
  - 5 分钟粒度，288 时段
  - 储能 SOC 范围 + 充放电效率
  - 分时电价 ToU
  - 充放电状态切换计数（最小化）
"""
import pulp
import pandas as pd
import numpy as np


def tou_price(hour_minute_str):
    """根据 'HH:MM:SS' 返回该时段对应的电价（元/kWh）"""
    h = int(hour_minute_str[:2])
    if 0 <= h < 6:    return 0.345995    # 谷
    if 6 <= h < 11:   return 0.650425    # 平
    if 11 <= h < 14:  return 0.345995    # 谷
    if 14 <= h < 16:  return 0.650425    # 平
    if 16 <= h < 23:  return 0.954855    # 峰
    return 0.650425                       # 23-24 平


def solve_dispatch(times, pv_kw, load_kw, prices,
                    capacity_kwh=3393, max_power_kw=1625,
                    soc_min_kwh=169.65, soc_max_kwh=3223.35, soc_init_kwh=169.65,
                    eff_ch=0.95, eff_dis=0.95, dt_h=5 / 60,
                    pv_cost=0.2, switch_penalty=1.0,
                    time_limit=120, gap=0.001):
    """
    求解微电网能源调度 MILP 模型。

    Args:
        times: 时间序列
        pv_kw: 光伏装机 (kW)
        load_kw: 负荷序列 (kW)
        prices: 分时电价序列
        capacity_kwh: 储能容量 (kWh)
        max_power_kw: 最大充放电功率
        soc_min_kwh/soc_max_kwh: SOC 上下限
        eff_ch/eff_dis: 充放电效率
        pv_cost: 光伏成本
        switch_penalty: 切换惩罚
        time_limit/gap: 求解参数

    Returns:
        MILP 求解结果
    """
    T = len(times)
    PERIODS = list(range(T))

    prob = pulp.LpProblem("Dispatch", pulp.LpMinimize)

    # 决策变量
    charge   = {t: pulp.LpVariable(f"ch_{t}",  lowBound=0, upBound=max_power_kw)
                for t in PERIODS}
    discharge = {t: pulp.LpVariable(f"dis_{t}", lowBound=0, upBound=max_power_kw)
                  for t in PERIODS}
    buy      = {t: pulp.LpVariable(f"buy_{t}", lowBound=0) for t in PERIODS}
    soc      = {t: pulp.LpVariable(f"soc_{t}", lowBound=soc_min_kwh,
                                    upBound=soc_max_kwh) for t in PERIODS}
    mode_ch  = {t: pulp.LpVariable(f"mc_{t}", cat='Binary') for t in PERIODS}
    mode_dis = {t: pulp.LpVariable(f"md_{t}", cat='Binary') for t in PERIODS}
    switch   = {t: pulp.LpVariable(f"sw_{t}", lowBound=0, upBound=1) for t in PERIODS}

    # 约束
    for t in PERIODS:
        # 功率平衡
        prob += pv_kw[t] + buy[t] + discharge[t] == load_kw[t] + charge[t]

        # 充放电互斥
        prob += mode_ch[t] + mode_dis[t] <= 1
        prob += charge[t] <= max_power_kw * mode_ch[t]
        prob += discharge[t] <= max_power_kw * mode_dis[t]

        # SOC 动态
        prev_soc = soc[t - 1] if t > 0 else soc_init_kwh
        prob += soc[t] == prev_soc + eff_ch * charge[t] * dt_h \
                - (1 / eff_dis) * discharge[t] * dt_h

        # 切换计数（mode_ch[t] vs mode_ch[t-1]，绝对值线性化）
        if t > 0:
            prob += switch[t] >= mode_ch[t] - mode_ch[t - 1]
            prob += switch[t] >= mode_ch[t - 1] - mode_ch[t]
            prob += switch[t] >= mode_dis[t] - mode_dis[t - 1]
            prob += switch[t] >= mode_dis[t - 1] - mode_dis[t]

    # 目标
    purchase_cost = pulp.lpSum(prices[t] * buy[t] * dt_h for t in PERIODS)
    pv_total_cost = pulp.lpSum(pv_cost * pv_kw[t] * dt_h for t in PERIODS)
    switch_cost   = pulp.lpSum(switch_penalty * switch[t] for t in PERIODS)
    prob += purchase_cost + pv_total_cost + switch_cost

    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, gapRel=gap, msg=1)
    status = prob.solve(solver)
    print(f"Status: {pulp.LpStatus[status]}, Obj: {pulp.value(prob.objective):.2f}")

    return prob, dict(charge=charge, discharge=discharge, buy=buy, soc=soc,
                      mode_ch=mode_ch, mode_dis=mode_dis, switch=switch)


def extract_results(vars_, times, pv_kw, load_kw, prices, dt_h=5 / 60):
    """从求解变量中提取微电网调度结果并整理为 DataFrame。"""
    rows = []
    for t, ts in enumerate(times):
        rows.append({
            '时间': ts,
            '光伏出力_kW': pv_kw[t],
            '园区负荷_kW': load_kw[t],
            '电网购电_kW': round(pulp.value(vars_['buy'][t]) or 0, 2),
            '充电_kW':    round(pulp.value(vars_['charge'][t]) or 0, 2),
            '放电_kW':    round(pulp.value(vars_['discharge'][t]) or 0, 2),
            'SOC_kWh':    round(pulp.value(vars_['soc'][t]) or 0, 2),
            '电价':       prices[t],
            '购电费':     round((pulp.value(vars_['buy'][t]) or 0) * prices[t] * dt_h, 4),
        })
    return pd.DataFrame(rows)


if __name__ == '__main__':
    df = pd.read_csv('data/day_profile.csv')
    times = df['时间'].tolist()
    pv_kw = df['光伏出力_kW'].values
    load_kw = df['园区负荷_kW'].values
    prices = np.array([tou_price(t.split()[1]) for t in times])

    prob, vars_ = solve_dispatch(times, pv_kw, load_kw, prices)
    result = extract_results(vars_, times, pv_kw, load_kw, prices)
    result.to_csv('dispatch_result.csv', index=False)
