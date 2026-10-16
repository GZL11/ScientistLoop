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

## 子族 A 专属坑(单机序列)

### 坑 A1:分离矩阵索引方向搞反

`separation_matrix[i][j]` 的方向通常是:**先做的为行索引,后做的为列索引**,
约束写 `time[j] - time[i] >= sep[i][j]`(i 先于 j)。
具体方向以问题描述/数据结构为准——拿不准时打印几个样本验证一下。

### 坑 A2:流水车间 makespan 计算错误

NEH 评估时必须追踪**所有机器**的最晚完成时间,不是只看末机:
```
start[i, m] = max(complete[i, m-1], complete[i-1, m])
```
忘记 `complete[i-1, m]`(同机器前一工件)会算出过低 makespan 并验证失败。

### 坑 A3:ILS 扰动力度不变

连续 5 次无改进还在做 3 段翻转 = 局部最优陷阱。
**自适应**:`k = 3 + min(no_improve // 5, 9)`。

### 坑 A4:大规模 or-opt 完整 O(n²) 超时

500 节点 × 500 插入位置 = 25 万次评估每轮,30s 时间就用完了。
**先 swap 收敛**(限邻域 30),再做 or-opt 且每次内层加时间检查。

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

### 坑 B5:特殊数据加载(pickle + 自定义模块)

某些数据用 `pickle` 序列化但依赖自定义 `database` 模块(等)。
**用以下 mock 在脚本头部注入:**

```python
import pickle, sys, types, importlib.util

class FlexClass:
    def __init__(self, *a, **k): pass
    def __setstate__(self, s): self.__dict__.update(s)

class AutoAttrModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (FlexClass,), {})
        setattr(self, name, cls)
        return cls

class MockLoader:
    def __init__(self, modname): self.modname = modname
    def create_module(self, spec): return AutoAttrModule(self.modname)
    def exec_module(self, module): pass

class MockFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith('database'):  # 改为实际依赖的模块名
            spec = importlib.util.spec_from_loader(fullname, MockLoader(fullname))
            return spec
        return None

sys.meta_path.insert(0, MockFinder())
data = pickle.load(open('data/data.pkl', 'rb'))
```

---

## 子族 C 专属坑(资源约束)

### 坑 C1:CP-SAT 时间被 NoOverlap 吃光

20+ 个 NoOverlap 约束 + 几百个 IntervalVar 时,求解器搜索很慢。
**对策:**
- `solver.parameters.num_search_workers = 4`(多线程)
- 加冗余但易求解的约束(例如先按 deadline 把任务硬定到具体某天)
- 用 redundant constraints:把"医生不重叠"展成显式两两 disjunction(CP-SAT 喜欢这种)

### 坑 C2:跨日资源占用未正确建模

例如 ICU 床位"跨 2 天":占床日 = {完成日, 完成日+1}。
错误:仅扣完成日。
正确:CP-SAT 用 IntervalVar 长度 = 2 天的虚拟资源占用,`AddCumulative(capacity=N)`。

### 坑 C3:"当天最后"硬约束

例如感控病例排"该手术室、当天的最后一台"——指**该手术室、当天**的最后一台,不是全院或全周最后。
正确建模:`start[i] >= max(end[j])  for j ∈ same_room_same_day, j != i`
错误建模:把感控排成一周最后或全院最后。

### 坑 C4:闭合约束被绕过

"首站 = 末站"是硬约束,不是软约束。
**必须在每一步链扩展时检查仍可闭合**,而不是末步再修。
末班无法接续时只能作为独立 2 任务链(保证首=末)。
若站点之间存在不可直达关系(如 A↔Z 之间无直接,必须走 M 中转),换乘要计入工时与衔接时间。

### 坑 C5:里程/工时口径混淆

任务描述常说"里程只算执行任务里程,不计司机步行/换乘空走"。
工时则是"首任务接班 → 末任务交班",**包含空闲等待时段**。
两个口径一定要分清,否则验证 100% 不过。

---

## 历史踩坑

> 来自评测运行的失败模式聚合。下方为新增聚合条目(21 patches)。

### sched-001:硬编码绝对路径导致 extractor 找不到产物 [7/21 runs]

**观察自:** patches #3, #4, #7, #9, #10, #20, #21

求解器把开发机绝对路径(`/path/to/workspace/.../run_0X`)写死,既用作输入读取也用作输出落盘。评估器在另一个工作目录执行,看不到任何产物 → exit code 1,得 0 分。

**避坑:**
- **永远不要硬编码绝对路径**。
- 读输入:`./data/` 优先,带 fallback 搜索;或读 `os.environ.get("RUN_DIR", ".")` / CLI 参数。
- 写输出:统一写到当前工作目录(`os.getcwd()`)或脚本所在目录(`os.path.dirname(os.path.abspath(__file__))`)下的相对路径。
- 写完后 `assert os.path.exists(out_path)`,并 `print(os.path.abspath(out_path))` 让日志可见。

```python
import os
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
OUT = os.path.join(os.getcwd(), "schedule_result.csv")  # 评估器在 CWD 找
df.to_csv(OUT, index=False, encoding="utf-8-sig")
assert os.path.exists(OUT), OUT
print("WROTE:", os.path.abspath(OUT))
```

### sched-002:产物文件名/schema/编码不匹配 [11/21 runs]

**观察自:** patches #1, #2, #5, #6, #7, #8, #14, #15, #16, #17, #18

失败形态包括:(a) 算出解但从没写出指定文件名;(b) 列名/dtype/索引基(0 vs 1)错;(c) 只写了 Gantt HTML / summary JSON 之类的辅助产物,主 CSV/JSON 缺失。

**避坑——把 schema 当硬约束建模:**
- 编码 solver 之前,先从任务描述/extractor 脚本里抄出 **精确文件名、路径、列、dtype、编码**。
- 在脚本里把期望 schema 设为常量,`to_csv` 之前 assert:

```python
EXPECTED_COLS = ["task_id", "machine_id", "mold_id", "start_time", "end_time", "planned_qty", "is_parallel"]
assert list(df.columns) == EXPECTED_COLS, f"schema mismatch: {df.columns.tolist()}"
df.to_csv("schedule_result.csv", index=False, encoding="utf-8-sig")  # 中文表头必须带 -sig
```

- 各领域常见 schema(以问题为准):
  - 流水车间:`result.csv` 列 `position,job_id` + `makespan.txt`(纯整数)
  - Job-shop:`schedule_result.csv` 列 `job_id, step, machine, start_time, end_time` + `result.json` 含 `makespan`
  - 手术室排程:`schedule_result.csv` 手术字段 + `summary.json` 含 KPI
  - 生产排程:`schedule_result.csv` 列如上述
  - 微网调度:`dispatch.csv` 全时步轨迹 + `summary.json`
- **可视化与解的写出解耦**:先在 `try/except` 中把主产物落盘,再去渲染 Gantt(渲染崩了不影响得分)。

### sched-003:优化前未先落盘 baseline,异常/超时 = 0 分 [8/21 runs]

**观察自:** patches #1, #6, #8, #12, #14, #17, #19, #20

solver 上来就跑 ILS / tabu / MILP / JIT 编译,中途 OOM/超时/异常 → 磁盘上零产物,即便内部已有可行解。

**避坑——先写 baseline,再迭代覆盖:**
1. **构造可行初解后立刻落盘**(贪心 / EDD / NEH / 全网格基线 / 顺序 JSS),用 `os.replace` 原子替换。
2. 优化主循环包 `try/finally`,任何退出路径都把当前 best 刷盘。
3. 给最终 write+flush+verify **预留 ≥10s 尾部预算**。
4. solver 状态为 INFEASIBLE/UNKNOWN 时,降级到启发式

### sched-004:产物列名/粒度与 extractor 期望不一致(深化版)[8/11 recent runs]

**观察自:** patches #1, #2, #3, #4, #7, #8, #10, #11(近期 11 run 聚合)

不仅是文件名错,更细的失败:
- 写了 `schedule_result.csv` 但任务要的是 `surgery_schedule.csv` / `crew_schedule.csv` / `solution.csv`
- 列名大小写/单复数错位:`room_id` vs `room`、`Start_time` vs `start_time`
- **行粒度错误**:写了 per-driver 汇总(`driver_summary.csv`),evaluator 要 per-task 长表;每个任务一行
- **必填列遗漏**:生产排程必须**同时**输出 `End` 和 `quantity`,只写其一也 0 分
- evaluator 的 column-normalizer 在列名不匹配时会 fallback 到错误文件,看着没报错但分数为 0

**避坑——交付契约硬编码 + 自我回读校验:**

```python
# 1) 在 solver 之前,从任务描述/EXTRACTOR_SPEC 抄死契约
DELIVERABLE = {
    "filename": "surgery_schedule.csv",   # 大小写、扩展名都必须一致
    "required_cols": ["surgery_id", "day", "room", "surgeon", "start_time", "end_time"],
    "row_granularity": "one row per surgery",   # 不是 per-room、不是 per-day 汇总
    "value_formats": {"day": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM"},
    "enums": {"room": ["OR1","OR2","OR3","OR4","OR5","OR6"]},
}

# 2) 写出后立即回读 + assert
import pandas as pd, os, re
out = DELIVERABLE["filename"]
assert os.path.exists(out), f"missing {out}"
chk = pd.read_csv(out)
assert list(chk.columns) == DELIVERABLE["required_cols"], chk.columns.tolist()
assert len(chk) == len(tasks), f"granularity wrong: {len(chk)} vs {len(tasks)} tasks"
for c, fmt in DELIVERABLE["value_formats"].items():
    pat = {"YYYY-MM-DD": r"^\d{4}-\d{2}-\d{2}$", "HH:MM": r"^\d{2}:\d{2}$"}[fmt]
    assert chk[c].astype(str).str.match(pat).all(), f"{c} format violated"
for c, allowed in DELIVERABLE["enums"].items():
    bad = set(chk[c]) - set(allowed)
    assert not bad, f"{c} has illegal values: {bad}"
print("DELIVERABLE OK:", out, len(chk), "rows")
```

**启发式:** "脚本无报错 + 得分 0" 几乎一定是产物名/列名/粒度错,而**不是**模型 bug。两次重写 solver 还出不了产物时,直接降级写 trivial baseline(全外包 / 全顺序 / 全单点),先拿到非零 validity。

### sched-005:决策变量被硬编码为"全用满",导致功率/资源平衡破坏 [2/11 runs]

**观察自:** patches #5, #6(微网调度类任务)

`P_pv_used = pv_available` 这种"可再生能源全用满"的硬编码,在 PV > load + 充电容量时会迫使 `P_grid` 取负,或 evaluator 反推出 `P_pv_used` 为负值(`P_pv_used min = -0.8`),硬约束直接判 fail。本质是缺少**弃光/弃风/溢出**这类松弛变量。

**避坑——对所有"可能需要松弛"的量都声明为带界决策变量:**

```python
# 错:把可用量当成已使用量
# P_balance: pv_available[t] + grid[t] + discharge[t] == load[t] + charge[t]   # 会逼出负 grid

# 对:弃光作为决策变量
P_pv_used = [model.NewIntVar(0, pv_available[t], f"pv_used_{t}") for t in T]
# 平衡式用决策变量:
for t in T:
    model.Add(P_pv_used[t] + P_grid[t] + P_discharge[t] == load[t] + P_charge[t])
# 若任务描述不鼓励弃光,改为软惩罚,而非删变量:
model.Minimize(sum(cost) + PENALTY * sum(pv_available[t] - P_pv_used[t] for t in T))
```

通用原则:**功率/物料/库存/产能平衡式两侧的每一项,如果实际可能"用不完"或"少供给",都要建成 `[0, upper]` 决策变量,绝不直接代入原始可用量。**

---

## 退出前自检

写出主产物后、脚本结束前,逐条勾选:

- [ ] 文件名与 EXTRACTOR_SPEC/任务描述**逐字一致**(大小写、扩展名、是否带 `_result`)
- [ ] 路径用相对路径(`