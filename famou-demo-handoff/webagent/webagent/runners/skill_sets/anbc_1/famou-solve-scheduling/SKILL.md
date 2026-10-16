---
name: famou-solve-scheduling
description: >
  排程 / 排班 / 调度类问题的专项求解参考。当 famou-build 判断当前问题属于
  生产排程、机组/人员排班、手术/资源调度、项目工期压缩、作业车间 (job shop) /
  流水车间 (flow shop)、单跑道/单机排序、岸桥分配、机组闭合路径等场景时调用，
  获取该类问题的算法选型、约束建模、验证要点等专项指导。
  遇到关键词（排程、排班、调度、makespan、换产、提前期、工期、班次、任务序列、
  Gantt、手术、岸桥、跑道、订单/工单、模具、换色、夜班、外包、precedence、
  作业车间、流水车间、闭合路径、机组、司机、护士、医生、着陆时间窗、操作时间范围）时优先调用。
---

# 排程求解

排程问题的评分通常看四个维度,任何一项失分整套交付都报废:

1. **硬约束逐条满足**——漏读一条边界条件(冷却期跨自然天、感控"当天该手术室最后一台"、闭合路径首=末、保质期 +1 偏移)= 整套报废
2. **目标函数口径正确**——makespan / 加权完成时间 / 总成本的计算方式与题目措辞逐一对齐
3. **输出字段完整合规**——字段名、行数、数值精度与 spec 完全一致
4. **独立验证通过**——用与建模代码独立的逻辑从输出反查每条硬约束,`Optimal` 不等于建模正确

写代码前的第一件事:**把所有硬约束和交付字段逐条抄到脚本顶部注释里**,包括边界条件和精度要求。这条比算法选择更优先。

## 执行流程

1. **理解问题**:从用户提供的任务描述中,逐条抽取业务清单——目标函数(makespan / 加权完成时间 / 总成本 / 资源数最小化)、硬约束(逐条,**含边界条件**:首日无前一天、感控隔离、冷却期、保质期、闭合路径、强制休息)、交付字段、特殊数据加载需求(如 pickle + 自定义模块,见 pitfalls.md)。检查项见 `references/coding_standards.md`。
2. **识别子族**:按上面信号定位问题分类。详见 `references/subtypes.md`。
3. **选算法骨架**:从 `references/algorithm_playbook.md` 拷贝对应子族的决策变量、约束族、目标函数模板。
4. **复制起手代码**:从 `references/code_templates/` 选最贴近的模板。
5. **编码与求解**:规范见 `references/coding_standards.md`。
6. **独立验证**:**用与求解代码完全独立的方式**(另写一段函数 / 另一脚本 / 不同实现思路),从输出反向逐条检查每个硬约束。`Optimal` 不是建模正确——验证脚本是抓 bug 的最后一道防线。检查清单见 `references/pitfalls.md` 末尾。

## 验证方法

**用与求解代码独立的逻辑**从输出反推每条硬约束,常见类目:

1. **资源容量**:每类受限资源在每个时间桶(日 / 班次 / 时段)内的占用 ≤ 容量上限
2. **顺序 / 优先级**:对所有 (i, j) ∈ precedence,有 start[j] ≥ end[i]
3. **结构 / 路径**:节点间流转的实体满足结构约束(闭合回路首 = 末、连通性、入度 = 出度、唯一入口出口等)
4. **时间分离 / 切换时间**:相邻任务 i → j 满足 `time[j] - time[i] >= sep[i][j]`(双向矩阵均需校验)
5. **业务专属规则**:逐条对照问题描述(隔离、冷却、时效、强制休息、资格匹配 …),按原措辞校验,不做翻译
6. **目标值复算**:用输出结果计算目标函数与各惩罚项,与求解器自报值差距 < 1e-4

终结回复需明示:目标值(含各分项)、关键事件计数(状态切换、加班、例外处理等)、硬约束 0 违反。

## 参考文件索引

| 文件 | 何时读 |
|------|-------|
| `references/subtypes.md` | Step 2(子族识别 + 决策树 + 典型样貌) |
| `references/algorithm_playbook.md` | Step 3(每子族的决策变量/约束/目标骨架) |
| `references/code_templates/subtype_a_sequence_ils.py` | Step 4(A 单机/序列 ILS) |
| `references/code_templates/subtype_b_multiline_milp.py` | Step 4(B 多产线 MILP) |
| `references/code_templates/subtype_c_resource_cpsat.py` | Step 4(C 资源约束 CP-SAT) |
| `references/coding_standards.md` | Step 1 / 5(业务清单 + 编码规范) |
| `references/pitfalls.md` | Step 6(易踩坑 + 退出自检 + pickle/database mock) |
