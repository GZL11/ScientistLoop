# 排程算法手册

## 子类型 A：单机序列优化（ILS）

### 适用场景
单跑道降落、单机加工序列、流水/作业车间 makespan、切排件序列。

### 算法骨架（ILS）
```
1. 构建初始解：按目标时间贪心 / NEH / 加权处理时间降序
2. 阶段1 swap（相邻交换）—— ~ 总预算 20%
3. 阶段2 or-opt（单任务重定位）—— ~ 总预算 35%
4. 阶段3 ILS 扰动重启 —— 剩余预算
   - 扰动：随机翻转 3–12 段（无改进 ≥5 次后加大力度）
   - 局部搜索：swap + or-opt
   - 接受准则：greedy（仅接受改进）
5. 时间到期前 3s 优雅停止，写最终解
```

### 评估函数（务必向量化）
```python
times, feasible = compute_times(order)            # 顺序填时刻，违反窗口直接 inf
cost = np.dot(pe[order], early) + np.dot(pl[order], late)
```
**infeasible 序列返回 `math.inf`，不被接受**。

### 流水车间(Flow shop)
- 初始解用 **NEH**:按加权处理时间降序,逐步插入到使 makespan 最小的位置
- 评估改为 makespan = 末机最晚完成时刻
- 邻域改为 swap / insertion 工件级

### 作业车间(Job shop)
- 编码:**每机器一个工序排列**(permutation per machine)
- **Tabu Search**:邻域 = 同机器上相邻两工序交换
- 列表长度 20–30,每轮邻域 ~80

### 切排(钢卷/板材)
- 序列层用 ILS(决定切排顺序),几何层用 `rectpack`(MaxRects、Skyline)
- 评估函数 = 用过的钢卷/板材数 + 余料惩罚

---

## 子类型 B：多产线生产排程（MILP）

### 决策变量
```
x[l,p,d]      ∈ {0,1}    # 产线 l 在 d 天生产产品 p
qty[l,p,d]    ≥ 0         # 当天产量（吨）
night[l,d]    ∈ {0,1}     # 是否夜班（产能 ×1.5，加 $80/吨）
co[l,d]       ∈ {0,1}     # 是否换产（产能 ×0.7）
out[p,d]      ≥ 0         # 当天外包量
late[p]       ≥ 0         # 逾期天数
```

### 关键约束
```python
# 每产线每天最多一种产品
sum_p x[l,p,d] <= 1

# 产量上限(含换产、夜班复合系数)
qty[l,p,d] <= cap[l,cat(p)] * (1 + α*night[l,d]) * (1 - β*co[l,d]) * x[l,p,d]
# 例:cap × 1.5 × 0.7 = ×1.05(换产+夜班同时)
# α (夜班产能加成) 与 β (换产产能损失) 以问题描述为准

# 换产触发:当天与前一天产品不同则 co=1
# 辅助变量 product-day-pair:co[l,d] >= x[l,p1,d-1] + x[l,p2,d] - 1, ∀ p1≠p2
# 首日(d=1)默认无前一天 → co[l,1] = 0

# 冷却期(若有):类型 X 后第 d+1, d+2 天禁类型 Y
sum_{p∈Y} x[l,p,d'] <= M*(1 - x[l,p∈X,d])  for d' ∈ {d+1, d+2}

# 保质期:生产日 d ≥ deadline - shelf_life + 1(注意 +1)
x[l,p,d] = 0  for d < deadline[p] - shelf_life[p] + 1

# 需求精确满足(自产 + 外包)
sum_{l,d} qty[l,p,d] + sum_d out[p,d] == demand[p]

# 全厂当天自产/外包总量上限(以问题描述为准)
sum_{l,p} qty[l,p,d] <= TOTAL_CAP_PER_DAY
sum_{p} out[p,d] <= OUTSOURCE_CAP_PER_DAY

# 逾期:完工日 = 最后自产日 + lateness(外包默认 deadline 当天到,不逾期)
late[p] >= last_prod_day[p] - deadline[p]
```

### 目标函数(典型加权)
```python
total = changeover_cost + outsource_cost + lateness_cost + night_cost + storage_cost
# 重要客户(如 Gold 等级) lateness 单价可能加权(常见 ×2 或 ×3)
```

### 求解策略
1. 先建最简模型(无夜班、无外包)确认 feasible
2. 加复杂约束,注意**一次只加一类**,方便定位 infeasible
3. **手工 warm-start**:先用启发式构造一个可行解作为 CBC 初始值(`prob.solver.set_initial_solution`),
   能把 gap 从 20%+ 压到 1% 的时间从 20 分钟压到 5 分钟(实际项目实测)
4. `PULP_CBC_CMD(timeLimit=240, gapRel=0.005, msg=1)`

### 大规模工单 + 模具特殊处理
- 模具变量 `m[j,k] ∈ {0,1}`(工单 j 用模具 k)
- 规模大(数百工单 × 数十机台 × 数百模具)时切贪心 EDD(Earliest Due Date) + 反向排程:
  ```
  1. 按 due_date 升序排工单
  2. 从 due_date 反推最晚开始时间(latest_start_time)
  3. 按优先级分配到 mold_machine_priority 中的首个空闲机台
  4. 冲突时延后或换次优机台
  ```

---

## 子类型 C：资源约束项目 / 人员排班

### C1 — CP-SAT(手术室、建设项目,30–200 任务)

OR-Tools 的 `NoOverlap2D` + `AddCumulative` 比 PuLP 更适合这类约束密集场景:

```python
from ortools.sat.python import cp_model
model = cp_model.CpModel()

# 每任务 = (start, end, room) interval 变量
intervals = {i: model.NewIntervalVar(start[i], dur[i], end[i], f'op{i}') for i in S}

# 同一资源(房间/机台)不重叠
for r in rooms:
    model.AddNoOverlap([intervals[i] for i in S if room[i] == r])

# 同医生/工人不重叠(同人任意两台间隔 >= 最小间隔)
# Cumulative:特殊设备每天上限 K 台
model.AddCumulative([intervals[i] for i in special_ops],
                    demands=[1]*len(special_ops), capacity=K)

# Cumulative:ICU 占床(每手术 demand=1,duration=2 天)
# 当日最后:用大M约束 start[i] >= start[j] + dur[j] for j ∈ same_room_same_day
# 工时上限:sum(dur[i] * worker_count[i]) per day ≤ 上限

# 求解
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 240
solver.parameters.num_search_workers = 4
```

### C2 — 贪心+图匹配(岸桥/机组,>100 任务)

**港口岸桥(最小化岸桥数):**
```
1. 按泊位区域划分岸桥自然分组
2. 按开港时间对船舶排序
3. 为每艘船选择"距泊位最近的可用连续岸桥块"
4. 冲突时后移船舶开始时间(取最小可行延后量)
5. 验证无时间冲突 + 无位置冲突
```

**机组司机(最小化司机数,带闭合路径):**
```
1. 按时间排序所有任务
2. 链式构造:维护已开 N 名司机,每个任务尝试接到最近的、能合规接续的司机末尾
   - 衔接:t_pickup[next] - t_dropoff[prev] >= 最小衔接 + transfer_min(prev_drop → next_pickup)
   - 司机累计工时 ≤ 上限、累计里程 ≤ 上限
   - **每步都要保证"还能闭合到首站"**(关键!末班无法闭合时必须开新司机)
3. 优化:枚举闭合模板(单返、多跳返、换乘返),优先用长模板替换短链
4. 末班任务无法接续时,作为独立 2 任务链(首站=末站本身保证)
```

### 时间 vs 算法决策

| 任务数 | 资源类型 | 推荐 | 时间预算 |
|--------|---------|------|---------|
| < 30 | 简单 | MILP / CP-SAT | < 30s |
| 30–100 | 多硬资源 | **CP-SAT** | 120–180s |
| 100–200 | 多硬资源 + 复杂约束 | CP-SAT + workers=4 | 240s |
| > 200 | 物理位置 / 闭合路径 | 贪心+图算法+模板枚举 | 60–120s |

## 共用：MILP / CP-SAT vs 元启发式选择

```
有"加权总成本最小"目标？
  → 倾向 MILP / CP-SAT（能给出 gap 保证）
有"makespan / 序列质量"目标 + 大规模？
  → 倾向 ILS / Tabu（评估函数能向量化才划算）
```
