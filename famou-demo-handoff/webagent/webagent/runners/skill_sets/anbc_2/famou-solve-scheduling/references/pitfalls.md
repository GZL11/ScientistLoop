# 排程常见坑 + 退出自检清单

> 本文件中的具体数字(任务数、产线数、产能值...)都是**典型样貌**——
> 用于说明踩坑形态。**真正的约束以用户提供的问题描述为准**。

## 通用坑

### 坑 0:没读完任务描述就动手

任务描述中常常有"次要目标""所用默认值""可视化样式规范"这些容易跳过的小节,但里面会藏着评分用得上的信息(如 Gold 客户罚款 ×3、感控排当日最后、冷却期跨自然天而非工作日)。**读两遍**,把硬约束抄到脚本注释顶部。

### 坑 1:交付字段名/文件名不匹配

`landing_time` 写成 `landing` ——评分脚本/验证读不到,全盘归零。
中文字段名(`车辆编号`/`网点编码`/`工单编号`)也必须**逐字保留**。
最后一步前用 `pd.read_csv` 重读自己的输出,对照需求清单字段表打勾。

### 坑 2:求解器 Optimal 不等于建模正确

CBC/CP-SAT 报 Optimal 只代表"在你写下的约束里最优"。
约束写错(变量方向反、索引转置)时它仍可能给"最优"解。
**必须独立验证**:用与建模代码独立的方式从输出反向逐条检查硬约束。

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

### 坑 A3:ILS 扰动力度不变 / 过早收敛

连续 5 次无改进还在做 3 段翻转 = 局部最优陷阱。
**自适应**:`k = 3 + min(no_improve // 5, 9)`。

强化要点：
- **不要用固定迭代次数终止**，应跑满时间预算（`while time.time() - t0 < budget`）
- 连续 20 轮无改进时，重置温度至初始值的 50%（若用模拟退火），防止过早凝固
- 当时间预算剩余 < 30% 且 gap > 5% 时，升级为 **double-bridge（4 段翻转）** 扰动而非 3 段
- 对于 500 作业规模，建议时间分配：贪心初始化 20%、主搜索 60%、定向优化 pass 20%

### ⚠️ 坑 A3b:模拟退火温度/接受策略缺失

当 ILS/or-opt 陷入局部最优后，应切换至模拟退火：
```
T0 = initial_cost * 0.02
cooling_rate = 0.995
accept_prob = exp(-delta_cost / T)
```
每 50+ 轮无改进后重启温度（重置至当前 T × 2，不超过 T0）。

### 坑 A4:大规模 or-opt 完整 O(n²) 超时

500 节点 × 500 插入位置 = 25 万次评估每轮,30s 时间就用完了。
**先 swap 收敛**(限邻域 30),再做 or-opt 且每次内层加时间检查。

补充：or-opt 可尝试迁移 2~3 个作业的段（segment），比单作业迁移效果更好；
在瓶颈机器（负荷最高的机器）的子序列上优先做 swap/insert，往往能快速降低 makespan。

### ⚠️ 坑 A5:大规模排程高惩罚任务未定向优化

**现象**：全局随机扰动已收敛，但仍有大量高惩罚任务（如延迟率 > 50%）。

**根本原因**：随机扰动对高惩罚任务改善概率低，应专项处理。

**正确做法**：
1. **高惩罚定向优化 pass**：识别惩罚最高的前 10% 任务，在其时间窗内枚举所有可行插入位置进行局部重排（O(n) per task）。
2. **延迟率诊断**：若超过 50% 任务延迟，说明初始排序策略不佳，应尝试多种初始排序：
   - 最早截止时间优先（EDF）
   - 惩罚系数加权优先（penalty_late/penalty_early 比值大的优先靠近目标时间）
   - 随机打乱后重新构造
   **至少运行 3 种初始排序，取最优结果**，不能仅接受当前局部搜索结果。
3. **针对延迟任务的快速互换**：对每个当前延迟的任务，检查是否存在可与之互换位置的有余量任务，实现 O(n) 改善。

### ⚠️ 坑 A6:Job Shop 建模退化为贪心调度

**现象**：直接用贪心（最短处理时间、最早完工等）提交，未使用改进搜索。

**正确做法**（按规模选择）：

| 规模 | 推荐方法 |
|------|----------|
| ≤ 200 作业 × 20 机器 | OR-Tools CP-SAT（精确建模） |
| 200~500 作业 | CP-SAT warm-start + ILS 后处理 |
| > 500 作业 | NEH 初始解 + 自适应 ILS + SA |

**CP-SAT JSP 建模模板**：
```python
from ortools.sat.python import cp_model
model = cp_model.CpModel()
# 为每道工序创建 IntervalVar
intervals_per_machine = defaultdict(list)
for job in jobs:
    prev_end = 0
    for op_idx, (machine, duration) in enumerate(job.operations):
        start = model.NewIntVar(0, horizon, f'start_{job.id}_{op_idx}')
        end = model.NewIntVar(0, horizon, f'end_{job.id}_{op_idx}')
        interval = model.NewIntervalVar(start, duration, end, f'interval_{job.id}_{op_idx}')
        # 工序顺序约束
        if op_idx > 0:
            model.Add(start >= prev_end)
        intervals_per_machine[machine].append(interval)
        prev_end = end
# 同机器无重叠
for machine, ivars in intervals_per_machine.items():
    model.AddNoOverlap(ivars)
# 目标
makespan = model.NewIntVar(0, horizon, 'makespan')
model.AddMaxEquality(makespan, all_last_ends)
model.Minimize(makespan)
# 多线程 + warm-start
solver = cp_model.CpSolver()
solver.parameters.num_search_workers = 8
solver.parameters.max_time_in_seconds = 300  # 至少 5 分钟
```

**多重启策略**：至少 3 个不同随机种子独立运行，取最优解；同时输出 lower bound 和 gap。

**提交前必须报告**：`best_makespan = X, lower_bound = Y, gap = Z%`。

---

## 子族 B 专属坑(多产线生产)

### 坑 B1:MILP 报 infeasible 但实际有解

通常是约束建模 bug:
- `still_short` / `late` 方向:必须用 `>=`,不要写成 `<=`(实际项目中真实事故)
- `Series.prod()` 把 pandas Series 当成乘积函数用(应该用 `row['product']`)
- 换产首日没赋值:`co[l, 1]` 应固定为 0
- 冷却期用了"工作日"距离而非"自然天"

**先去掉夜班/外包/冷却期等复杂约束,看能否可行?再逐步加约束定位 bug。**

### 坑 B2:换产建模仅按"天"判定

错误:`co[l,d] = (d 在生产)`——这把所有生产天都算成换产。
正确:`co[l,d] = (今天生产 ≠ 昨天生产)`,等价为对所有 `p1 ≠ p2`:
`co[l,d] >= x[l,p1,d-1] + x[l,p2,d] - 1`,再 `co[l,1] = 0`。

### 坑 B3:保质期建模忘记 +1

"生产当天计第 1 天"意味着:
`生产日期 ≥ deadline 日期 - shelf_life_days + 1`,**不是** `- shelf_life_days`。
shelf=4 表示"生产当天到 deadline 当天总共 4 天"。

### 坑 B4:CBC 不收敛(gap 卡 20%+)

- 加**手工初始解(warm-start)**:先用贪心构造可行方案塞进去
- 加成本上界 cuts:`prob += total_cost <= 估计上界 * 1.2`
- 切到 OR-Tools CP-SAT,整数变量为主时通常更快
- 若仍超时:超时后**接受当前可行解 + 输出 gap**,不要硬等

### ⚠️ 坑 B6：有效产能系数（ramp / ns）MIP 内部 vs 外部不一致（高频、全零）

**现象**：run_01 得分正常，run_02 / run_03 得分 0.0，评估器报
`Capacity exceeded at date line=L-X: YY.00 > ZZ.ZZ (base=45.0, ramp=0.7, ns=1.0)`。

**根本原因**：

产线有效产能 = `base_cap × ramp_factor × ns_factor`，其中：
- `ramp_factor`：换产当天的产能折扣（通常 < 1，如 0.7）
- `ns_factor`：夜班扩产系数（通常 ≥ 1，如 1.5）

MIP 建模时通常引入二元变量 `is_change[l,d]`，用复杂线性化约束定义它，
再在容量约束里乘上系数。

**陷阱**：MIP 的 `is_change` 定义约束有时**不能捕捉所有真实换产情形**：
- 若产线在某天停产后重启，评估器视重启日为"换产"（新产品 ≠ 上一次生产的产品），
  但 MIP 里可能因 `active_day[l,d_prev]=0` 导致 `active_both=0` → `is_change=0`，
  约束失效，评估器发现违反。
- MIP 解本身数值精度问题（CBC gapRel=2%）也可能在边界情形产生 is_change=0 但实际=1。
- **同类别内不同产品（如 A1→A3→A1）同样触发 ramp 容量折扣**，"三条产线各守一类"只规避了类别间换产费用，不规避容量折扣，必须在约束中体现。

**停产后重启判定优先级**：
> 当用户口头澄清"空闲后重启不触发降效"时，**不能直接相信**，必须：
> 1. 用独立验证脚本同时按两种口径（`last_prod=None → is_change=True` 和 `False`）各算一遍；
> 2. 对比哪种与评估器实际结果一致，再确定建模方式。

**正确做法**：

1. **从已提交方案倒推换产序列**，独立计算每个 (产线, 日期) 的有效产能：
```python
for l in lines:
    last_prod = None
    for d in sorted_days:
        if line_produces_on(l, d):
            cur_prod = get_product(l, d)