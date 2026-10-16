---
name: famou-solve-replenishment
description: >
  补货 / 采购 / 库存优化类问题的专项求解参考。当 famou-build 判断当前问题属于
  多周期库存补货、Hub-Spoke 网络调拨、多供应商采购、带提前期 (lead time) 补货、
  容量选址 (CFLP)、库存替代品、保质期/损耗、安全库存等场景时调用，
  获取该类问题的算法选型、约束建模、验证要点等专项指导。
  遇到关键词（补货、采购、库存、提前期、lead time、DC、仓库、缺货、调拨、转运、
  供应商、安全库存、保质期、损耗、过期、SKU、shelf life、选址、设施开设）时优先调用。
---

# 补货 / 采购 / 调拨求解

补货问题的评分通常看四个维度,任何一项失分整套交付都报废:

1. **库存守恒正确**——任意一项 +/- 写反、漏一项、索引转置,求解器仍报 "Optimal" 但模型从头就错
2. **硬约束 0 违反**——容量、提前期、MOQ、保质期及问题描述里其他一切硬约束(逐条见下方验证清单)
3. **目标函数口径正确**——成本各分项(采购/持有/缺货/损耗/折扣/附加费)计算是否完整,与题目措辞逐一对齐
4. **输出格式合规**——列名与 spec 完全一致、数量列为整数、dense grid(含零行)

写代码前的第一件事:**在脚本顶端用注释把库存平衡方程逐项画出来**,每个 +/- 的物理含义注明(`short` 是加号——代表少消耗了这么多;替代方向是高等级替代低等级),再开始写约束。这条比算法选择更优先。

## 执行流程

1. **理解问题**:从用户提供的任务描述(spec / brief / problem statement / 业务文档)中,逐条抽取业务清单——目标函数构成、硬约束、替代规则、初始条件、数据文件清单、交付要求。检查项见 `references/coding_standards.md`。
2. **识别子族**:详见 `references/subtypes.md`。
3. **选算法骨架**:从 `references/algorithm_playbook.md` 拷贝对应子族的决策变量、约束族、目标函数模板。
4. **复制起手代码**:从 `references/code_templates/` 选最贴近的模板。先实现 `load_data()` 适配实际字段名,再实例化模型。
5. **编码与求解**:规范见 `references/coding_standards.md`。
6. **独立验证**:**用与建模代码完全独立的方式**。检查清单见 `references/pitfalls.md` 末尾。

## 验证思路

`Optimal` 是"在你写下的约束里最优",不是"建模正确"。三类典型错配:
- **守恒方程错符号**:增项写成减项 / 漏一项 / 索引转置
- **方向反**:替代、调拨、上下游等有方向的关系建反,仍能解出"最优"
- **比例 / 聚合分母用错**:占比、达成率、平均值的分母对象错位

**用与建模代码独立的逻辑**从输出反查每条硬约束,退出前必做:

1. **守恒 / 平衡方程逐项重算**(每周期、每节点)
2. **目标值 = 各分项之和**,用输出重新累加,与求解器自报值差距 < 1e-4
3. **硬约束 0 违反**:容量、时间窗、特殊业务规则按问题描述原措辞逐条

终结回复需明示:目标值(含各分项)、关键事件计数(短缺、损耗、切换 等)、硬约束 0 违反。

## 参考文件索引

| 文件 | 何时读 |
|------|-------|
| `references/subtypes.md` | Step 2(子族识别 + 决策树 + 子族典型样貌) |
| `references/algorithm_playbook.md` | Step 3(每子族的决策变量/约束/目标骨架) |
| `references/code_templates/replenishment_milp_template.py` | Step 4(A/B/D 通用 MILP 起手) |
| `references/code_templates/multi_supplier_template.py` | Step 4(C 多供应商) |
| `references/code_templates/cflp_template.py` | Step 4(E 选址) |
| `references/code_templates/microgrid_dispatch_template.py` | Step 4(F 储能调度) |
| `references/coding_standards.md` | Step 1 / 5(业务清单 + 编码规范) |
| `references/pitfalls.md` | Step 6(易踩坑 + 退出自检清单) |
