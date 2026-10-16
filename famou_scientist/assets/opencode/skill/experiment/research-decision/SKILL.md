---
name: research-decision
description: After analyzing trustworthy experiment results, decide PROCEED / REFINE / PIVOT. Use at the analysis→decision juncture to judge whether results support the hypothesis, need more evidence, or disprove the hypothesis.
metadata:
  category: experiment
  trigger-keywords: "decision,proceed,pivot,refine,go/no-go,results support,hypothesis confirmed,next step,analysis done"
  applicable-stages: "14,15"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

实验跑完、**数据已经可信**（不是崩了、不是 NaN、不是准确率近随机——那些先走
`experiment-repair`），分析也做完了。现在站在岔路口：这些结果，接下来怎么走？
load 这个 skill 拿 ARC 的 go/no-go 决策框架，做出**明确的三选一判定**，别含糊收尾。

> 前提：这一步只在**数据可信**时做。数据本身有技术缺陷 → 那是 `experiment-repair`，
> 不是这里。先确认"实验对不对"，再问"结论说明什么"。

> **搭配 `research-reflection`**：本 skill 出**判定**（PROCEED/REFINE/PIVOT 三选一）；
> 判定前先 load `research-reflection` 做**结论⇄最初假设的对照 + 归因反思**，并把过程落盘到
> `experiment/reflection.md`。reflection 想清楚"支不支持、为什么、下一步"，本 skill 落成正式判定。

## 三个决策

| 决策 | 含义 | 下一步 |
|------|------|--------|
| **PROCEED** | 结果充分且支持假设 | → 写论文（AGENTS.md 第 8 步）|
| **REFINE** | 假设**没死**，但证据不够硬（方差大/条件少/不达标）| → 回去**改实验设计**重跑（同一假设，第 4-5 步）|
| **PIVOT** | 假设被数据**推翻/矛盾** | → 回去**换假设**（放弃当前方向，第 3 步）|

## PROCEED 的硬门槛（5 条，全部满足才能 PROCEED）

这是 ARC 的关键判据——**任何一条不满足，就必须 REFINE，不准 PROCEED**：

1. **至少 2 个 baseline + proposed 方法都有结果**（不能只跑了自己的方法）
2. **主指标定义明确**（方向、单位都清楚）
3. **每个条件 ≥ 3 个随机种子**（少于 3 个没法估方差，不可信）
4. **不同条件的逐种子数值不雷同**（ablation 完整性——雷同说明区分参数没接进代码）
5. **分析质量自评 ≥ 4/10**

> 这 5 条防的是"拿半成品实验写论文"。宁可 REFINE 多跑一轮，不要 PROCEED 一个站不住的结论。

## REFINE vs PIVOT 怎么分（关键）

分界线是**"假设还活着吗"**：

- **REFINE** = 假设没死，只是证据不足 → 加种子/加条件/加 baseline 再来一轮，**同一假设**
- **PIVOT** = 数据明确**反对**假设 → 这个方向错了，**换假设**重来

混淆代价很大：该 PIVOT 时 REFINE = 反复给错假设补实验，永远收敛不了；
该 REFINE 时 PIVOT = 轻易丢掉一个其实对的方向。

> **REFINE/PIVOT 要提的新方向，先过 `novelty-gate`**：别反射式抛一个"换超参/换数据集"的
> 增量当后续。没真新意的方向要么深挖、要么如实告诉用户这条路创新见底了——别用小修小补消耗用户耐心。

## 退化循环规则（别无限 REFINE）

ARC 踩坑沉淀的硬规则——**REFINE 不是无限的**：

- 若多轮 REFINE 后指标**饱和**（全 ≈0 或 ≈1）或**完全不变** → 再 REFINE 也救不了
  （往往是基准设计本身太易/太难），**应改判 PROCEED + 注明质量局限**，别再 REFINE
- 同类实验缺陷连续 2 轮 REFINE 仍在 → 同样 PROCEED + caveat，别死循环

## 输出格式（明确、可追溯）

给用户展示时，按这个结构输出：

```markdown
## Decision
PROCEED / REFINE / PIVOT  （三选一，明确）

## Justification
为什么这个决策——基于证据说理

## Evidence
支撑决策的关键数据点（指标值、种子数、条件对比）

## Next Actions
选定路径的具体下一步
```

## 配合 AGENTS.md 的节奏

- 这一步是 AGENTS.md 第 7 步的"研究决策"，**关键停顿点**
- **C 逐步** / **PIVOT 或 REFINE 这种推倒重来**：必须停下、展示判定+依据、等用户确认
  （重大方向变更属硬问题，A/B 全自动节奏也不能跳过）
- **PROCEED**：A/B 节奏下可直接进入写论文

> 这复刻了 ARC `_execute_research_decision` 的决策逻辑，但判定由你（OpenCode）在对话里
> 做出并对用户负责——ARC 的价值是上面那套门槛和 REFINE/PIVOT 判据。
