---
name: peer-review
description: Simulate rigorous conference peer review on a paper draft to find problems before revision. Use after a draft is written, ideally via an independent reviewer subagent (fresh context) to avoid self-confirmation bias.
metadata:
  category: experiment
  trigger-keywords: "peer review,reviewer,审稿,review draft,critique,weaknesses,rebuttal,会议评审"
  applicable-stages: "18"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

论文草稿写完后（Stage 18）、修订（Stage 19）之前。目的：**像顶会审稿人一样狠挑毛病**，
产出可执行的修改意见，驱动修订——不是夸，是找弱点。

> 区别于 `quality-gate`：peer-review 是「找问题、改进质量」（软，驱动修订）；
> quality-gate 是「最终 go/no-go 放行」（定稿前把关）。先 review→修订，再 quality-gate。

## 🔑 执行方式：用独立 reviewer，别自己审自己

**首选：起一个独立 reviewer subagent**（用 `task` 工具，`subagent_type` 选可用的通用类型）：
- 只把**论文文本** + 下面的审稿清单作为 prompt 传给它
- **不要带写作过程的上下文** —— subagent 是 fresh context，没有"这是我刚写的、我知道每个数字怎么来"的包袱
- 这样才有真正"换个人审"的效果，避开**确认偏误**（自己写的自己难挑刺）

若不便起 subagent → 降级：显式**切换到审稿人视角**，刻意带敌意找茬（"我要拒掉这篇，理由是什么"），别用作者视角自我辩护。

## 审稿方法：3 个审稿人视角

模拟至少 3 个不同专长的审稿人，各自给 strengths / weaknesses / **actionable revisions**：
- **Reviewer A（方法专家）**：方法是否新颖、技术是否扎实、有无明显缺陷
- **Reviewer B（领域专家）**：是否扣题、与领域 SOTA 比如何、贡献是否实质
- **Reviewer C（统计/严谨性专家）**：实验是否充分、统计是否有效、结论是否被数据支撑

> ⚠️ **判 benchmark 覆盖要对齐 baseline 惯例，别空泛地嫌"benchmark 太少"**：评判标准是
> **「和它对比的 baseline 普遍在哪些 benchmark 上评测」**——若论文覆盖了 baseline 们共用的那些 benchmark，
> 数量就是合理的（哪怕只有 1 个领域标准 benchmark）；只有当它**比 baseline 惯例还少**（baseline 普遍跑 3 个、
> 它只挑 1 个交差，导致和大半 baseline 没法比 / 结论可能依赖单一数据集）才算缺陷。不要为了"更全面"而要求超出领域惯例的数量。

## 8 点强制检查清单

每个审稿人都过一遍这 8 点（ARC 沉淀的顶会评审要点）：

1. **主题对齐**：全篇是否扣题？有没有把环境/工程问题当成贡献来写？
2. **声称-证据对齐**：标题/摘要/结论里**每个声称**，Results 里都有对应指标/表/图支撑？无支撑的声称 = 严重问题
3. **统计有效性**：有置信区间/误差棒？n>1（多种子）？显著性检验合适？
4. **完整性**：各 section 齐全且有深度？（NeurIPS 正文约 5000-6500 词量级）
5. **可复现性**：超参/随机种子/算力/数据集细节是否写全？（回扣 `baseline-profiling` 那套）
6. **写作质量**：流畅散文而非 bullet 堆砌？方法/结果/讨论别用列表；别过度对冲（"we do not claim..."）；标题 ≤14 词
7. **图表**：至少 2 张图？**零图 = desk reject**。**有没有一张方法/架构概览图让读者 30 秒看懂你怎么做的？** 只有数据对比图、没有方法示意图是常见缺陷——缺则提示补（走 `arc_generate_schematic`）
8. **引用分布**：引用不能只在 Intro/Related Work，方法/实验/讨论也要引相关工作

## 输出 + 配合

- 产出结构化评审意见（按 reviewer 分组 + 总体 verdict：accept / weak accept / borderline / reject），存入 `deliverables/reviews.md`
- **同时 load `failure-mode-audit`**：审稿视角最适合盯 **Mode 4（捷径依赖：消融是否真排除了捷径）/
  Mode 7（frame-lock：这篇是不是答错了题）**——把这两项并入审稿意见。
- **承重引用过 `citation-faithfulness`**：对支撑核心论点/带数字的引用，用 `arc_fetch_source` 抓摘要核对
  "这条引用真支撑这句话吗"（Reviewer 最爱挑的误引），UNSUPPORTED 的写进 required revisions。
- **Stage 19 修订**：据评审意见逐条改论文，改完可再过一轮（直到无重大 weakness）
- 修订后再走 `quality-gate`（反造假 + 阈值放行）

> 一句话：写完别急着收，先请「另一个你」以审稿人身份狠审一遍——独立视角才挑得出真问题。
