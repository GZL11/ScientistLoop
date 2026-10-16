---
name: quality-gate
description: Final go/no-go quality check on a paper before export. Use after revision, to score the paper against a threshold and cross-check every reported number against real experiment data (anti-fabrication) before finalizing.
metadata:
  category: experiment
  trigger-keywords: "quality gate,go/no-go,final check,before export,paper quality,fabrication,publishable,quality threshold"
  applicable-stages: "20"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

论文起草 + 自评 + 修订都做完了，**导出成品前的最后一道关**。load 这个 skill 拿
下面的质量门方法论：给论文打分、卡阈值、**逐条核对报告数字的真实性**，决定能不能
导出，还是打回再改。

> 区别于 `scientific-writing` 的"同行评审自评"（那是找问题驱动修订）——质量门是
> **最终 go/no-go**：这篇论文够不够格发出去？不够就打回 required_actions，不准导出。

## 质量门怎么判

对修订后的论文，产出一个评估 JSON：

```json
{
  "score_1_to_10": <数字>,
  "verdict": "<pass / revise>",
  "strengths": [...],
  "weaknesses": [...],
  "required_actions": [...]   // 不达标时必须做的整改
}
```

- **score ≥ 阈值（默认看 config 的 quality_threshold）→ PASS**，可进入导出
- **score < 阈值 → 打回**，按 required_actions 改完再过一遍质量门
- LLM 评估失败/拿不到分 → **按"未达标"处理**（强制走修订，不准放行）

## 评分维度（综合同行评审的 8 个检查点）

打分时按这些维度审，每条都影响分数：

1. **主题对齐** —— 全篇是否扣题？有没有把环境问题/无关内容当贡献？
2. **声称-证据对齐** —— 标题/摘要/结论里**每个声称**，Results 里都有对应的指标/表/图支撑？无支撑的声称要扣分
3. **统计有效性** —— 有置信区间/误差棒？n>1（多种子）？显著性检验合适？
4. **完整性** —— 各 section 齐全且有深度？（NeurIPS 正文 5000-6500 词量级）
5. **可复现性** —— 超参/随机种子/算力/数据集是否写全？
6. **写作质量** —— 流畅散文而非 bullet 堆砌？方法/结果/讨论里别用列表；别过度对冲（"we do not claim..."）；标题 ≤14 词
7. **图表** —— 至少 2 张图？**零图 = desk reject**。**有没有一张方法/架构概览图（不只是数据对比图）让读者 30 秒看懂方法？** 缺则提示补（`arc_generate_schematic`）
8. **引用分布** —— 引用不能只在 Intro/Related Work，方法/实验/讨论也要引相关工作

> ⚠️ **不要因 benchmark"数量少"就扣分**：benchmark 覆盖是否够，以**「对比的 baseline 普遍用哪些 benchmark」**为准——
> 覆盖了 baseline 共用的那些就算达标（哪怕只有 1 个领域标准 benchmark）。只有**比 baseline 惯例还少**
> （和大半 baseline 没法对比 / 结论依赖单一数据集）才扣分；别要求超出领域惯例的 benchmark 数量。

## 🔴 反造假交叉核对（ARC 最硬的纪律，务必做）

这是质量门最关键、最不能省的一步——**论文里报告的每个数字，必须能追溯到真实实验数据**：

- 把论文里的指标值，与 `experiment/results.md` / `experiment/results.json` **逐一交叉核对**
- **若实验状态是 failed / 无有效 metrics，但论文却报告了结果数字 → 判定造假，严厉扣分**
- 数字对不上、查无实据的结果 → 当作未支持/编造，要求删除或改写
- 实验没做的部分，论文应明说"未开展该分析"，而不是编一个数字填上

> 这条对应 ARC 质量门里的 anti-fabrication cross-check。它和 guardrails hook 是**两道防线**：
> hook 做确定性强制拦截（metric 全 0、引用核验），这个 skill 让你**主动逐条核对数字真实性**。

## 配合 AGENTS.md 与 hook

- 这是 AGENTS.md 第 8 步的"质量自检（Stage 20）"，**关键停顿点**：展示评分 + verdict + required_actions，等用户确认
- **同时 load `failure-mode-audit`** 做**定稿前关卡**：复查全部 7 模式，重点 **Mode 2（幻觉引用，借
  `citation-faithfulness` 查支撑性）/ Mode 4（捷径依赖）/ Mode 7（frame-lock：是否答错了题）**；
  在跑后关卡曾 SUSPECTED 的模式必须在此 CLEAR 或已 override，否则**拒绝导出**。
- **不达标先改，别急着导出**（呼应"真实性优先"）
- guardrails hook 是硬底线（metric 全 0、引用核验门强制触发，跳不过）；本 skill 是
  **主动的全面自检**——两者叠加才完整。别因为"hook 会拦"就省了主动核对

> 这复刻了 ARC `_execute_quality_gate` 的逻辑（LLM 打分 + 反造假交叉核对 + 阈值放行），
> 但由你（OpenCode）在对话里执行并对用户负责。
