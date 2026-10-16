# 排程常见坑 + 退出自检清单

> 本文件中的具体数字(任务数、产线数、产能值...)都是**典型样貌**——
> 用于说明踩坑形态。**真正的约束以用户提供的问题描述为准**。

---

## 通用坑

### 坑 0:没读完任务描述就动手

任务描述中常常有"次要目标""所用默认值""可视化样式规范"这些容易跳过的小节,但里面会藏着评分用得上的信息(如 Gold 客户罚款 ×3、感控排当日最后、冷却期跨自然天而非工作日)。**读两遍**,把硬约束抄到脚本注释顶部。

**领域特有约束清单化**（对应模式 4）：读题时同步列出一张"领域特有约束清单"，包括：
- 跨资源的全局限额（如"全系统每日某类操作上限"而非单资源限额）
- 任务连续性要求（如首尾同节点、同产线不中断等）
- 跨期累积约束（如资源占用持续多个时间单位，需在滚动窗口内累加统计）
- 任务间强制间隔（如跨资源的休息间隔、冷却期按自然天而非工作日）
- 软约束与硬约束的明确区分（软约束引入松弛变量进目标函数，**不建成硬性边界**）

每条约束在建模前写独立验证函数，**不等到提交前才验证**。

---

### 坑 1:交付字段名/文件名不匹配

`landing_time` 写成 `landing` ——评分脚本/验证读不到,全盘归零。
中文字段名(`车辆编号`/`网点编码`/`工单编号`)也必须**逐字保留**。

**防御流程**（对应模式 5）：
1. 在编写任何求解代码前，从题目中逐字提取所有要求的输出字段名，固定为脚本顶部注释
2. 生成输出后立即 `pd.read_csv` 重读，断言每个必要字段存在且拼写一致
3. 从输出文件**独立重建目标函数值**，与求解器报告值比对
4. 检查是否存在全零、全空或无意义分配的退化情况（全零输出能通过格式检查但评分为 0）

```python
# 提交前格式自检模板
df = pd.read_csv('output.csv')
required_cols = [...]  # 从题目逐字复制
for col in required_cols:
    assert col in df.columns, f"缺失字段: {col}"
assert df[score_col].sum() > 0, "输出退化为全零，禁止提交"
```

---

### 坑 2:求解器 Optimal 不等于建模正确

CBC/CP-SAT 报 Optimal 只代表"在你写下的约束里最优"。
约束写错(变量方向反、索引转置)时它仍可能给"最优"解。

**独立验证是强制要求**（对应模式 1）：用与建模代码**完全独立**的验证函数从输出反向逐条检查：

```python
def verify_all_constraints(solution_df):
    violations = []
    # 逐条重算每个硬约束的满足情况
    for constraint_name, check_fn in hard_constraints.items():
        n_viol = check_fn(solution_df)
        if n_viol > 0:
            violations.append(f"{constraint_name}: {n_viol} 处违规")
    # 重建目标函数值
    recomputed_obj = compute_objective(solution_df)
    assert abs(recomputed_obj - reported_obj) < tolerance, \
        f"目标值不一致: 重建={recomputed_obj}, 报告={reported_obj}"
    return violations
# 零违规方可提交
assert len(verify_all_constraints(df)) == 0
```

重点验证以下高频方向性错误：
- 非对称矩阵行列含义是否与题意一致（先做行 or 先做列？）
- 多重系数是否为乘法叠加而非加法（如容量 = base × ramp × ns）
- 资源约束的统计范围是单资源还是全局、单期还是滚动窗口
- 软约束松弛变量是否进入目标函数而非建成硬性边界

---

### ⚠️ 坑 3:参数方向性/作用域理解错误（通用模式）

**触发场景**：约束矩阵、惩罚系数、资源限额等参数的方向性、乘法叠加关系或作用范围存在歧义时。

**常见表现**：
- 非对称矩阵行列含义搞反（先做为行还是先做为列）
- 多重系数误作加法而非乘法（如有效产能 = base + ramp + ns，而非 base × ramp × ns）
- 资源约束统计范围错误（单机 vs 全局、单日 vs 滚动窗口）
- 固定成本与变动成本混淆：固定成本不随产量变化，应与决策变量数量而非产出挂钩
- 软约束建成硬约束，导致模型 infeasible

**正确做法**：
1. 建模前用已知样例数据逐一打印关键参数的实际取值，验证方向性与非对称性
2. 对每个约束明确是硬性可行性约束还是软性惩罚约束，分别用不同机制实现
3. 对滚动窗口类资源约束，显式枚举每个时间点的累积占用量而非仅检查瞬时值
4. 对跨期状态传递（库存、人员数等），逐字确认状态变量的更新公式及生效时机

```python
# 参数方向验证示例
# 选几个已知的 (a, b) 对，验证 param[a][b] 与 param[b][a] 的非对称性是否符合题意
for a, b in known_sample_pairs:
    print(f"param[{a}][{b}]={param[a][b]}, param[{b}][{a}]={param[b][a]}")
    # 预期：某方向 > 0 或 != 对方向，否则方向可能搞反
```

**验证门槛**：提交前独立重建约束验证函数，打印违规数量；对软约束重建目标函数值并与求解器报告值比对，差异超过容忍阈值则禁止提交。

---

### ⚠️ 坑 4:多期状态传递与成本结构建模错误

**触发场景**：问题包含跨期状态传递（库存水位、人员数量、设备状态等）以及同时含有固定支出与变动支出的成本结构时。

**常见错误**：
- 将固定成本（不随产量变化）错误建模为按产量比例分配的变动成本
- 忽视状态变量的生效时机（当期生效 vs 下期生效，期初值 vs 期末值）
- 将软性惩罚约束建成硬性可行性约束，导致模型无解
- 跨期累积约束（如连续多期的资源占用）仅检查单期值而非窗口内累计

**正确做法**：
```python
# 跨期状态验证模板（从输出方案逐期重算）
state = initial_state
for t in time_periods:
    # 严格按题意的状态转移方程更新
    state = transition(state, decisions[t])
    # 验证当期约束
    assert state['inventory'] >= 0, f"第 {t} 期库存为负"
    assert state['headcount'] >= min_headcount[t], f"第 {t} 期人员不足"

# 分别重算固定成本与变动成本
fixed_cost = sum(fixed_rate[r] * (1 if used[r] else 0) for r in resources)
variable_cost = sum(var_rate[r] * usage[r] for r in resources)
total_cost = fixed_cost + variable_cost
assert abs(total_cost - reported_cost) < tolerance
```

---

## 子族 A 专属坑(单机序列 / 流水车间 / Job Shop)

### 坑 A1:分离矩阵索引方向搞反

`separation_matrix[i][j]` 的方向通常是:**先做的为行索引,后做的为列索引**,
约束写 `time[j] - time[i] >= sep[i][j]`(i 先于 j)。
具体方向以问题描述/数据结构为准——**拿不准时打印几个样本验证一下**：

```python
# 验证分离矩阵方向：选几对(i,j)，打印 sep[i][j] vs sep[j][i]，确认非对称性与描述一致
for i, j in sample_pairs:
    print(f"sep[{i}][{j}]={sep[i][j]}, sep[{j}][{i}]={sep[j][i]}")
```

在任何优化运行之前先做此验证，避免大规模跑完才发现方向反了。

---

### 坑 A2:流水车间 makespan 计算错误

NEH 评估时必须追踪**所有机器**的最晚完成时间,不是只看末机:
```
start[i, m] = max(complete[i, m-1], complete[i-1, m])
```
忘记 `complete[i-1, m]`(同机器前一工件)会算出过低 makespan 并验证失败。

**makespan 独立验证**（提交前必做）：从输出 CSV 重新模拟：
```python
# 按机器分组检查无重叠；按作业分组检查工序顺序
# 取所有工序 end_time 最大值与求解器报告值比对，差值必须 < 1e-4
recomputed_makespan = max(row['end_time'] for row in schedule_rows)
assert abs(recomputed_makespan - reported_makespan) < 1e-4
```

---

### 坑 A3:ILS 扰动力度不变 / 过早收敛

连续 5 次无改进还在做 3 段翻转 = 局部最优陷阱。
**自适应**:`k = 3 + min(no_improve // 5, 9)`。

强化要点：
- **不要用固定迭代次数终止**，应跑满时间预算（`while time.time() - t0 < budget`）
- 连续 20 轮无改进时，重置温度至初始值的 50%（若用模拟退火），防止过早凝固
- 当时间预算剩余 < 30% 且 gap > 5% 时，升级为 **double-bridge（4 段翻转）** 扰动而非 3 段
- 对于 500 作业规模，建议时间分配：贪心初始化 20%、主搜索 60%、定向优化 pass 20%

---

### ⚠️ 坑 A3b:模拟退火温度/接受策略缺失

当 ILS/or-opt 陷入局部最优后，应切换至模拟退火：
```
T0 = initial_cost * 0.02
cooling_rate = 0.995
accept_prob = exp(-delta_cost / T)
```
每 50+ 轮无改进后重启温度（重置至当前 T × 2，不超过 T0）。

---

### ⚠️ 坑 A3c:单一初始解策略导致搜索局限（对应模式 2）

**现象**：元启发式搜索长时间运行后仍有较大改善空间，但搜索已无进展。

**根本原因**：仅依赖单一初始排序策略（如固定用最短处理时间优先），初始解的局部邻域覆盖受限，整个搜索被困在同一盆地内。

**正确做法**：
1. **至少构造 3 种差异化初始解**，例如：
   - 最早截止时间优先（EDF）
   - 惩罚加权优先（高惩罚任务靠近目标时间）
   - 随机打乱后贪心构造
2. 对每种初始解执行完整的独立搜索后取全局最优
3. 搜索过程中持续追踪改善幅度，当连续若干轮无显著改善时自动升级扰动强度
4. 始终记录并输出当前最优值与下界估计及其差距百分比

```python
best_cost = float('inf')
best_solution = None
for strategy in [edd_init, penalty_weighted_init, random_init]:
    sol = strategy()
    sol, cost = local_search(sol, time_budget / 3)
    if cost < best_cost:
        best_cost, best_solution = cost, sol
print(f"best={best_cost}, lower_bound={lb}, gap={100*(best_cost-lb)/lb:.1f}%")
```

**验证门槛**：确认至少尝试了多种初始构造策略；时间预算被充分利用而非找到第一个可行解后提前终止；gap 超过质量门槛且时间尚余则继续搜索。

---

### 坑 A4:大规模 or-opt 完整 O(n²) 超时

500 节点 × 500 插入位置 = 25 万次评估每轮,30s 时间就用完了。
**先 swap 收敛**(限邻域 30),再做 or-opt 且每次内层加时间检查。

补充：or-opt 可