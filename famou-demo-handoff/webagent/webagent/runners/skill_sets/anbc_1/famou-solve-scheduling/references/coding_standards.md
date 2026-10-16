# 排程编码与规范

汇总 SKILL.md Step 1(业务清单提取)/ Step 5(编码运行) 的细节。本文件可独立修改而不动 SKILL.md。

> **关键原则**:所有文件名、字段名、产物形态都以**用户提供的任务描述为准**。
> 本文件给出的是**数据形态分类 / 编码思路 / 常见组合**,不是固定命名约定。

## 1. 业务清单提取(Step 1)

无论用户以什么形式提供问题(单个文档 / 对话描述 / 多个 spec),开始建模前必须把以下条目逐项抄到脚本顶部注释中。**抄两遍**——遗漏一条硬约束的代价远高于建模过度。

### 1.1 业务清单

- **目标函数**:makespan / 加权完成时间 / 总成本(多项加权:换产费 + 逾期罚款 + 外包费 + 库存持有 + 夜班费 + 切换罚款 ...)/ 资源数最小化(岸桥/司机/护士)?多目标时各项权重必须明确。
- **硬约束清单**:逐条列出,**包括边界条件**——首日无前一天、感控隔离、冷却期、保质期、闭合路径、强制休息、precedence 链、护士工时、不同班次产能倍率、外包上限。
- **资源池**:每池容量 / 上限 / 时段(手术室、ICU 床、医生、护士、岸桥、机台、模具)。是否跨日?(如 ICU 占床日 = {完成日, 完成日+1})
- **目标函数权重**:Gold 客户罚款 ×3、加班费 1.5×、夜班 +X 元/吨——评分对权重敏感。

### 1.2 数据清单

按用途分类:

| 数据类型 | 用途 | 典型字段方向 |
|---------|------|------------|
| 任务主数据 | 任务 id、所需时长、deadline、类型 | task_id / dur / due_date / type |
| 资源主数据 | 资源容量、班次、可用时段 | resource_id / capacity / shift |
| precedence 表 | 任务间先后关系 | predecessor / successor |
| 兼容矩阵 | 任务-资源、任务-工人 是否兼容 | task / resource / 0-1 |
| 分离矩阵(若 A 子族)| 任意两任务间最小间隔 | from / to / sep_time |
| 换产成本表(若 B 子族)| 同类/跨类换产费 | from_type / to_type / cost / time |
| 班次/产能表(若 B 子族)| 不同班次的产能倍率 | shift / mult |
| ToU / 时段表 | 哪段时间用何价或何资源限 | period / value |

**特殊数据加载**:若数据是 `pickle + 自定义模块`(如某些工单/模具数据用了 `database` 模块),需在脚本头部 mock 注入 (见 pitfalls.md 中的 `MockFinder` 片段)。

### 1.3 交付清单

- 每个产物文件的**确切文件名**与**字段名**(中英文逐字保留:`landing_time` ≠ `landing`,`车辆编号` ≠ `vehicle_id`)。
- 行数与数值精度(小数位通常 2 位,整数则保整数;以问题描述为准)。
- 可视化要求:**按用户指定走**——若用户要求 Gantt / 资源占用热图 / 产线日历,按要求选;若没指定,Gantt 是最自然呈现。

## 2. 编码规范(Step 5)

### MILP 求解器

- **PuLP + CBC**:`PULP_CBC_CMD(timeLimit=240, gapRel=0.005, msg=1)`,`msg=1` 留 log 便于诊断。
- **OR-Tools CP-SAT**:约束逻辑复杂(如手术室、感控、岸桥、闭合路径)时比 MILP 更易写、更快收敛。`solver.parameters.num_search_workers = 4`。
- **时间预算**:总预算约 5 分钟,CBC 留 240–280s,ILS 留 ~270s。
- 子族 B/C 先建**最简模型确认可行**,再逐步加复杂约束(每加一类就跑一次,方便定位 infeasible 来源)。
- **手工 warm-start**(MILP):用启发式构造可行解作为初始值,gap 收敛快得多。
- **回退方案**:MILP 超时 / infeasible 时切到启发式(脚本里写好 fallback 分支)。

### ILS / 元启发式

- 评估函数务必 **numpy 向量化**(子族 A 必备)。infeasible 序列返回 `math.inf` 不被接受。
- 扰动力度自适应(无改进 5 次后加大):`k = 3 + min(no_improve // 5, 9)`。
- 保存历史最优;时间到点前 3s **优雅停止**。

### 编码常见错位

- **首日边界**:`changeover[l, day=1] = 0` 必须显式;否则求解器把首日也算成换产。
- **保质期 +1**:"生产当天计第 1 天" → 生产日 ≥ deadline - shelf_life **+ 1**(不是 `- shelf_life`)。
- **冷却期口径**:跨自然天还是工作日?A 类后第 d+1, d+2 天禁 C 类——具体天数与方向以问题描述为准。
- **复合产能系数**:`base × night_mul × changeover_mul`——例如 `1.5 × 0.7 = 1.05`(夜班 + 换产同时)。
- **ICU 占床跨 2 天**:不是仅扣完成日,而是 {完成日, 完成日+1}。CP-SAT 用 IntervalVar 长度=2 + AddCumulative。
- **跨日换产建模**:用 `co[l,d] >= x[l,p1,d-1] + x[l,p2,d] - 1, ∀ p1≠p2`,首日 `co[l,1] = 0`。

### CP-SAT 常用模式

```python
from ortools.sat.python import cp_model
model = cp_model.CpModel()

# 任务 i = (start, end, dur) interval
intervals = {i: model.NewIntervalVar(start[i], dur[i], end[i], f't{i}') for i in T}

# 同资源不重叠
for r in resources:
    model.AddNoOverlap([intervals[i] for i in T if assigned[i] == r])

# 容量类(如腹腔镜每天 ≤ 2):AddCumulative
model.AddCumulative([intervals[i] for i in laparo_ops],
                    demands=[1]*len(laparo_ops), capacity=2)

# 感控/最后一台:start[i] >= end[j] for j ∈ same_room_same_day, j != i

# 求解
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 240
solver.parameters.num_search_workers = 4
```

### 进度打印

关键节点都 print:初始解成本 → 每阶段改进 → 最终成本 → 各项分项 → infeasible 报告。
运行后查输出文件是否存在、行数是否符合要求。
