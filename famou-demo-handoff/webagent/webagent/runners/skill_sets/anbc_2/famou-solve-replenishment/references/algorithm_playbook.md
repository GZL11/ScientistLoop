# 补货 / 采购算法手册

> **变量与字段命名约定**:本文件中 `capacity[dc]`、`usage_per_unit[sku]`、`shelf_life`、`lead_time`、
> `demand[dc, sku, t]` 等都是**算法记号**,不是数据文件中的固定列名。
> 实际写脚本时需按用户提供的数据中的字段名读入并赋给这些算法变量。
> 凡是带 `[dc]` / `[sku]` / `[t]` / `[dc, sku, t]` 下标的,对应数据中的某些列或参数表。

## 子类型 A：多 DC 独立多周期补货（MILP）

### 决策变量
```
order[dc, sku, t]   ≥ 0   # 第 t 期下单量（提前期=0 时即到货量）
inv[dc, sku, t]     ≥ 0   # 期末库存
short[dc, sku, t]   ≥ 0   # 缺货量
waste[dc, sku, t]   ≥ 0   # 损耗量
sub_in[dc, low, t]  ≥ 0   # 低等级 SKU 接受替代的量
sub_out[dc, high, t] ≥ 0  # 高等级 SKU 出库被替代的量
```

### 库存守恒（最关键约束）
```python
# 普通 SKU
inv[dc, sku, t] = inv[dc, sku, t-1] + order[dc, sku, t] - demand[dc, sku, t]
                  + short[dc, sku, t] - waste[dc, sku, t]
# 注意 short 是把"未满足的需求"变成"占位"——加在右边等于"少消耗了 short 这么多"

# 替代品（高等级 high → 低等级 low）：
# low 守恒：+ sub_in[dc, low, t]（被高等级补入的量）
# high 守恒：- sub_out[dc, high, t]（被替代出去的量）
# 等量配对：sub_in[dc, low, t] == sub_out[dc, high, t]   for each (low, high) 配对
```

### 容量约束
```python
sum_sku inv[dc, sku, t] * usage_per_unit[sku] <= capacity[dc]   # 加权占用风格(冷藏体积)
sum_sku inv[dc, sku, t] <= capacity[dc]                         # 件数风格
```

### 产能约束（全网）
```python
sum_dc order[dc, sku, t] <= supplier_cap[sku, t]
```

### 保质期建模
**精确（批次追踪 FIFO）：**
```python
batch[dc, sku, t_arrival, t]  # t_arrival 期到货的批次，到 t 期还剩多少
# 守恒：batch[..., t] = batch[..., t-1] - 该批次出库 - 过期报废
# t - t_arrival >= shelf_life → 强制全部报废
```

**近似（避免囤超过保质期能消耗的量）：**
```python
inv[dc, sku, t] <= sum(demand[dc, sku, t..t+shelf_life-1])
```

### 目标函数
```python
minimize:
    sum(purchase_cost[sku] * order[dc, sku, t])
  + sum(holding_cost[sku] * inv[dc, sku, t])
  + sum(shortage_penalty[sku] * short[dc, sku, t])
  + sum(waste_cost[sku] * waste[dc, sku, t])
```

### 求解
```python
solver = pulp.PULP_CBC_CMD(timeLimit=240, gapRel=0.001, msg=1)
prob.solve(solver)
```

---

## 子类型 B：Hub-Spoke MILP

### 决策变量
```
purchase[sku, t]          ≥ 0    # 中央仓采购
allocate[dc, sku, t]      ≥ 0    # 中央 → 地区 dc 调拨
inv_central[sku, t]       ≥ 0    # 中央仓库存
inv_regional[dc, sku, t]  ≥ 0    # 地区仓库存
short[dc, sku, t]         ≥ 0    # 地区仓缺货
```

### 两层库存守恒
```python
# 中央仓
inv_central[sku, t] = inv_central[sku, t-1] + purchase[sku, t]
                    - sum_dc allocate[dc, sku, t]

# 地区仓（同期完成调拨：DC1 期初采购 → 期内调出 → 地区仓期末库存）
inv_regional[dc, sku, t] = inv_regional[dc, sku, t-1]
                         + allocate[dc, sku, t]
                         - demand[dc, sku, t]
                         + short[dc, sku, t]
                         - waste[dc, sku, t]
```

### 容量
```python
# 中央
sum_sku inv_central[sku, t] * usage_per_unit[sku] <= central_capacity
# 地区
sum_sku inv_regional[dc, sku, t] * usage_per_unit[sku] <= regional_capacity[dc]
```

### 调拨费
```python
transport_cost = sum(0.5 * allocate[dc, sku, t]
                     for dc in regional for sku for t)
```

### 目标函数
```python
minimize:
    sum(purchase_cost[sku] * purchase[sku, t])           # 中央仓采购成本
  + sum(holding_central[sku] * inv_central[sku, t])      # 中央仓持仓
  + sum(holding_regional[sku] * inv_regional[dc, sku, t])# 地区仓持仓
  + sum(shortage_penalty[sku] * short[dc, sku, t])       # 地区仓缺货
  + transport_cost                                        # 调拨运费
  # 若有损耗：+ sum(waste_cost[sku] * waste[dc, sku, t])
```

---

## 子类型 C：多供应商采购 MILP

### 决策变量
```
buy[s, p, m]      ≥ 0          # 供应商 s 第 m 月对产品 p 采购量
use[s]            ∈ {0, 1}     # 是否启用 s（决定是否触发框架合同最低）
early_pay[s, m]   ∈ {0, 1}     # 是否选择提前付款（仅 s ∈ early_pay 候选）
```

### 关键约束
```python
# 需求满足
sum_s buy[s, p, m] >= demand[p, m]

# 月产能上限
sum_p buy[s, p, m] <= monthly_capacity[s]

# 起订量（开关式）：sum_p buy[s,p,m] 要么为 0 要么 ≥ min_order_qty[s]
# 用辅助二元 active[s, m] ∈ {0,1}：
sum_p buy[s, p, m] <= big_M * active[s, m]
sum_p buy[s, p, m] >= min_order_qty[s] * active[s, m]

# 框架合同：use[s]=1 → sum buy[s] >= contract_min[s]
sum_{p,m} buy[s, p, m] >= contract_min[s] * use[s]
sum_{p,m} buy[s, p, m] <= big_M * use[s]

# 至少 3 家
sum_s use[s] >= 3

# 单一占比 ≤ 40%
sum_{p,m} buy[s, p, m] <= 0.4 * total_demand

# 加权次品率 ≤ 2%（线性化：分母不变就是常数）
sum_{s,p,m} (defect_rate[s] * buy[s, p, m]) <= 2.0 * total_demand

# 提前付款：仅支持 s 才允许 early_pay
early_pay[s, m] == 0  for s ∉ early_pay_eligible
```

### 综合单位成本（带早付折扣的线性化）
```python
# unit_cost(s, p, m) 含汇率/进口税/长周期/风险/质检的常数
# 早付折扣 1% 是变量乘变量（buy × early_pay），需线性化：
#   引入 buy_early[s, p, m] = buy[s, p, m] 当 early_pay=1 否则 0
#   buy_early[s, p, m] <= big_M * early_pay[s, m]
#   buy_early[s, p, m] <= buy[s, p, m]
#   buy_early[s, p, m] >= buy[s, p, m] - big_M * (1 - early_pay[s, m])

# 总成本：
total_cost = sum(unit_cost[s,p] * buy[s,p,m]) - sum(0.01 * unit_cost[s,p] * buy_early[s,p,m])
```

### big_M 取值
`big_M = total_demand * 1.5`，避免 1e9 导致数值不稳定。

---

## 子类型 D：带提前期 MILP

### 提前期处理（最易出错）
```python
# 第 t 期下的单 在第 t + lead_time[sku] 期到货
inv[dc, sku, t] = inv[dc, sku, t-1]
                + (order[dc, sku, t - lead_time[sku]] if t > lead_time[sku] else 0)
                - demand[dc, sku, t]
                + short[dc, sku, t]
                - waste[dc, sku, t]
                + sub_in - sub_out
```

**前 lead_time 期不可避免缺货**——这是物理特性，不是 bug。
PLAN 通常会接受这部分缺货（在报告里说明即可）。

### Rolling Horizon 贪心（精确 MILP 太慢时备选）
```
for t in range(1, T+1):
    1. 应用本期到货：inv += order_placed[t - L]
    2. 消耗需求：sales = min(inv, demand[t])；short = demand[t] - sales
    3. 触发替代：若有 high 等级库存且 low 缺货，等量替代
    4. 检查保质期：超期批次报废
    5. 决策本期下单 order[t]：覆盖未来 (L + safety_buffer) 周需求
       受产能上限和容量上限约束
```

---

## 子类型 E：CFLP MILP

### 决策变量
```
open[f]    ∈ {0, 1}    # 设施 f 是否开
assign[c, f] ∈ {0, 1}  # 客户 c 分配给设施 f
```

### 约束
```python
sum_f assign[c, f] == 1                              # 每客户唯一分配
sum_c demand[c] * assign[c, f] <= capacity[f] * open[f]
assign[c, f] <= open[f]                              # 必须开了才能分
```

### 目标
```python
minimize sum(fixed_cost[f] * open[f])
       + sum(transport_cost[c, f] * assign[c, f] * demand[c])
```

---

## 子类型 F：微电网能源调度 MILP

### 决策变量
```
charge[t]   ≥ 0    # 充电功率（kW）
discharge[t] ≥ 0   # 放电功率（kW）
buy[t]      ≥ 0    # 电网购电功率（kW）
soc[t]      ∈ [SOC_min, SOC_max]   # SOC 对应电量（kWh）
mode_charge[t]   ∈ {0, 1}    # 是否充电
mode_discharge[t] ∈ {0, 1}   # 是否放电
switch[t]   ∈ {0, 1}    # 状态切换发生（用于罚款）
```

### 约束
```python
# 功率平衡（每时段）
pv[t] + buy[t] + discharge[t] == load[t] + charge[t]
buy[t] >= 0   # 不能向电网售电

# 充放电互斥
mode_charge[t] + mode_discharge[t] <= 1
charge[t] <= max_power * mode_charge[t]
discharge[t] <= max_power * mode_discharge[t]

# SOC 动态（5 分钟粒度，单位换算到 kWh）
dt = 5 / 60   # 小时
soc[t] == soc[t-1] + eff_charge * charge[t] * dt - (1 / eff_discharge) * discharge[t] * dt

# 切换计数
switch[t] >= mode_charge[t] - mode_charge[t-1]
switch[t] >= mode_charge[t-1] - mode_charge[t]
# discharge 同理
```

### 目标
```python
minimize sum(price[t] * buy[t] * dt)              # ToU 购电
       + sum(0.2 * pv[t] * dt)                     # 光伏成本
       + 1.0 * sum(switch[t])                      # 切换罚款
```

ToU 价格按时段查表(具体时段划分以问题描述为准,常见三档:谷/平/峰)。

---

## 求解时间预算

| 子类型 | 变量量级 | 推荐 timeLimit | gapRel |
|--------|---------|---------------|--------|
| A | 300 | 60s | 0.001 |
| B | 600 | 120s | 0.001 |
| C | 200 + 二元 | 120s | 0.005 |
| D | 300 | 120s | 0.001 |
| E | n_facilities × n_customers | 240s | 0.005 |
| F | 288 × 多变量 ≈ 2000 | 120s | 0.001 |

CBC 在数值病态时不收敛——切到 OR-Tools CP-SAT（整数为主时更稳）或 HiGHS。
