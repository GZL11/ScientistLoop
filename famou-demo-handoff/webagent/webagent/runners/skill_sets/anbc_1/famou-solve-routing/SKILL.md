---
name: famou-solve-routing
description: >
  路径规划类问题的专项求解参考。当 famou-build 判断当前问题属于
  TSP / 多车 TSP (mTSP) / CVRP / VRPTW、配送路线、危险品运输、城市配送、
  应急站覆盖、多约束 VRP、多实例旅行商、车辆路网调度等场景时调用，
  获取该类问题的算法选型、约束建模、验证要点等专项指导。
  遇到关键词（配送、路线、巡回、TSP、VRP、运输、车辆、网点、载重、容量、
  时间窗、time window、Dijkstra、危化品、hazmat、应急站、路网、segment、
  工作量均衡、最短路、cluster、聚类配送）时优先调用。
---

# 路径规划求解

路径规划问题的评分通常看四个维度,任何一项失分整套交付都报废:

1. **节点全覆盖、无重复**——漏一个或重复访问一个 = 整套报废
2. **硬约束 0 违反**——容量、时间窗及问题描述里其他一切硬约束(逐条见下方验证清单)
3. **目标函数有可比性**——总距离 / 总时长 / 总成本计算口径要正确(行驶速度、服务时间是否计入、距离度量统一)

写代码前的第一件事:**把"必访节点集合"抄到独立验证脚本里**,最后用 `set(visited) == set(must_visit)` 抠死。这条比任何算法优化都更优先。

## 执行流程

1. **理解问题**:从用户提供的任务描述中,逐条抽取业务清单——目标函数(总距离/时长/成本/工作量均衡度)、硬约束(容量、时间窗、车辆类别、路网禁令、应急站)、距离口径(欧式/Haversine/路网最短路)、必访节点集合、交付要求。检查项见 `references/coding_standards.md`。
2. **识别子族**:详见 `references/subtypes.md`。
3. **选算法骨架**:从 `references/algorithm_playbook.md` 拷贝对应子族的构造启发式 + 改进算法 + 距离矩阵预计算代码。
4. **复制起手代码**:从 `references/code_templates/` 选最贴近的模板。先实现数据加载适配实际字段名,再实例化求解。
5. **编码与求解**:规范见 `references/coding_standards.md`。
6. **独立验证**:**用与求解代码完全独立的方式**逐条验证全节点覆盖、容量、时间窗、车辆类别、路网禁令、应急站覆盖。检查清单见 `references/pitfalls.md` 末尾。

## 验证方法

验证比求解优化更重要。三类典型错配:

- **节点漏访问 / 多访**:仓库或哑节点是否纳入必访集?编号空间或坐标系不同的子实例不能合并到同一矩阵。
- **距离口径不一致**:目标值与硬约束所用的距离/时间计算方式必须统一。
- **遗漏服务时间**:`total = travel + n_stops * service`——只算行驶时间会系统性低估累计耗时。

**用与求解代码独立的逻辑**从输出反查每条硬约束:

1. **节点覆盖**:`set(all_visited) == set(must_visit)` 且 `len(visited) == len(set(visited))`(每点恰好一次)
2. **资源容量**:每条路线/车辆累计资源占用 ≤ 上限(载重、件数、工时 等)
3. **时间窗**:每节点 `earliest <= arrival <= latest`,服务时间纳入累计
4. **业务专属约束**:资格匹配、路网/区域禁令、覆盖半径、护送/同行规则 等,按问题描述原措辞逐条
5. **目标值复算**:用输出重新累加总距离/时长/成本及各惩罚项,与脚本报告值完全一致。

终结回复需明示:覆盖节点数 / 总数、各路线关键资源占用上下限、目标值(含各分项)、硬约束 0 违反。

## 参考文件索引

| 文件 | 何时读 |
|------|-------|
| `references/subtypes.md` | Step 2(子族识别 + 决策树 + 典型样貌) |
| `references/algorithm_playbook.md` | Step 3(每子族的构造 + 改进 + 距离/路网代码) |
| `references/code_templates/tsp_template.py` | Step 4(A 纯 TSP / 多实例 TSP) |
| `references/code_templates/cvrp_template.py` | Step 4(C CVRP) |
| `references/code_templates/hazmat_vrp_template.py` | Step 4(E 危化品多约束 VRP) |
| `references/coding_standards.md` | Step 1 / 5(业务清单 + 编码规范) |
| `references/pitfalls.md` | Step 6(易踩坑 + 退出自检清单) |
