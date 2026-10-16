---
name: benchmark-selection
description: Choose which benchmarks/datasets to evaluate on after profiling baselines. Build a baseline×benchmark coverage matrix, match benchmark coverage to field practice, and decide which reported numbers can be reused. Hand the selected datasets to dataset-acquisition for path confirmation, download, authentication, and validation before experiments.
metadata:
  category: experiment
  trigger-keywords: "benchmark,dataset,数据集,evaluation,download,reuse baseline,reported results,选数据,benchmark选择"
  applicable-stages: "9,11"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

profile 完候选 baseline（`baseline-profiling`）之后、设计/跑实验之前。这一步决定：
**用哪几个 benchmark 评测、能否复用 baseline 已报告的结果、数据从哪来**。

## 第 0 步（必做）：列出 baseline × benchmark 覆盖矩阵

选之前**先把候选 baseline 各自用过哪些 benchmark 显式列成一张表**——不要跳过这步直接拍脑袋选一个。
从 `baseline-profiling` 的结果里，每个 baseline 一行，列出它**评测用的 benchmark + 在每个 benchmark 上报告的关键数字**：

```
benchmark →      | ImageNet | CIFAR-100 | iNat-2018 | Places365 | 报告来源
baseline ↓
ResNet-50        |  76.1    |   —       |   —       |  54.7     | [He'16]
ViT-B/16         |  77.9    |  87.1     |   —       |   —       | [Dosov'21]
ConvNeXt-T       |  82.1    |   —       |  —        |  55.0     | [Liu'22]
你的方法          |   ?      |   ?       |   ?       |   ?       | 待跑
─────────────────┼──────────┼───────────┼───────────┼───────────┤
覆盖该 bench 的 N |   3      |   1       |   0       |   2       |
```

这张表一次解决三件事：① 哪些 benchmark 是领域共用的（列里 N 大）；② 你的方法**必须在哪些 benchmark 上有数**才能和 baseline 同台对比；③ 哪些格子已有现成数字可直接复用（见下文省力点）。**把这张表写进 `planning/design.md`。**

## 选 benchmark：数量跟随 baseline 的普遍做法 + 两个标准

### 数量：看你要对比的 baseline 普遍用几个，就用几个

> ⚠️ **不要凭空决定数量，也不要硬凑**。正确的数量由矩阵直接读出来：**看你要对比的那些 baseline 普遍在几个
> benchmark 上评测**——它们普遍用 2~3 个，你就用 2~3 个；它们普遍只用 1 个标准 benchmark，你用 1 个也完全没问题。
> 目标是和 baseline **同台可比、对齐领域惯例**，不是追求 benchmark 数量。

- **读矩阵的"每行用了几个"**：多数 baseline 各自评测用了几个 benchmark？这就是你的目标数量。
  - 普遍多个 → 你也覆盖那几个**共用**的（落在矩阵里 N 大的列），别只挑一个交差——那样会和大半 baseline 没法对比。
  - 普遍单个标准 benchmark → 用那一个就够，这是领域事实标准，不必为凑数硬加冷门数据集。
- **常见错误是少选**（agent 容易只挑一个就跑）：如果 baseline 们普遍在 3 个 benchmark 上报数，你只跑 1 个，
  就只能和一部分 baseline 比、且结论可能依赖单一数据集特性——**这种"比 baseline 惯例还少"才是要避免的**。
- 也别走反向极端硬凑数量：benchmark 跟着 baseline 惯例走即可，覆盖**它们共用的那些**比堆数量重要。

### 在数量对齐 baseline 惯例的前提下，每个 benchmark 按两点取舍

从候选 baseline **用过的 benchmark** 里选（不要凭空选冷门数据集），按两点排序：

1. **覆盖度**：被**多少个候选 baseline 使用**（即矩阵里那一列的 N）。用得越多 → 对比基础越广，且越可能有现成结果可复用。
2. **任务贴近度**：benchmark 的任务设定 / 数据分布 / 评测目标，与你的研究问题有多匹配。

**优先选「多个 baseline 共用 + 与任务贴近」的那些**。多数情况，领域里就那两三个 baseline 扎堆用的
benchmark——这不是巧合，是事实标准；选它们既保证可比性，又能最大化复用现成数字。

## 🟢 省力关键点：复用 baseline 已报告的结果

如果你选的 benchmark 上，**baseline 已经有公开报告的结果**（就是上面矩阵里非空的格子，来自
`baseline-profiling` 抽到的「报告的关键数字」），且**评估协议一致**（同数据划分 / 同指标定义 / 同评测方式）：

- **直接引用那个数字做对比，不必自己复现 baseline** —— 只跑你自己的方法即可，省下大量算力
- 在论文/结果里注明数字来源（"as reported in [cite]"）
- **前提是协议必须一致**（回到 `baseline-profiling` 的对齐检查）；协议不一致就不能直接借数字，
  要么对齐重跑 baseline，要么明确声明差异
- 若 baseline 没报告该 benchmark 上的结果、或协议对不齐 → 才需要自己复现 baseline

> 这条能把"必须复现所有 baseline"降级为"大多数借数字、个别才重跑"，是实验阶段最大的省力点。

## 数据集获取交接

确定 benchmark 后，load `dataset-acquisition`。由它统一处理：

- 先检查用户是否已有可用数据路径；
- 向用户确认默认 `research-runs/<active-run>/experiment/data/` 或自定义下载位置；
- 核对数据大小、许可、认证、代理、磁盘空间和官方获取方式；
- 下载、恢复、解压并验证真实数据；
- 无法自主恢复时用结构化问题停下来让用户选择，不能只发普通消息后继续实验或论文。

本 skill 不直接下载数据，也不重复维护下载失败策略。

## 配合流程

- 上游 `baseline-profiling`：提供候选 baseline 用的 benchmark 清单 + 它们报告的数字
- 本步：建覆盖矩阵 → 看 baseline 普遍用几个、定出对齐惯例的 benchmark 组（共用那几个）+ 决定哪些 baseline 数字可复用
- 下游 `dataset-acquisition`：确认本地路径或下载位置，获取并验证数据
- 下游 `experimental-design`：在选定的**每个** benchmark 上设计实验，只跑「自己的方法 + 不可复用的 baseline」
- 把覆盖矩阵、选择理由（为什么这几个 benchmark、数量为何对齐 baseline 惯例）、数据路径、可复用的 baseline 数字，记入 `planning/design.md`
