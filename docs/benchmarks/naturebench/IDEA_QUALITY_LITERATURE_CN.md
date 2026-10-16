# 2026 科研智能体论文调研 → Idea 质量的架构级改进

> 更新时间：2026-08-31 CST
> 目的：用今年的论文找 loop 架构 / memory 层的改进点，**先在我们自己的全量数据上验证前提成立**，再决定是否引入。
> 配套：[`LOOP_DESIGN_INVENTORY_CN.md`](LOOP_DESIGN_INVENTORY_CN.md)（现有设计，避免重复提出）

---

## 零、调研范围

两轮 arXiv 检索，共读 **66 篇 2026 年摘要**，其中 4 篇读全文。

- **第一轮（40 篇）**：`scientific idea generation` / `research ideation` / `hypothesis generation` 等关键词。
  结论：**这一支几乎不适用于我们**。它们的评价对象是"人类评审觉得新颖吗"，
  优化目标是 Novelty/Diversity；我们有 evaluator 返回的真分数，不需要代理指标。
  只有 3 篇的结论对我们有用（见 §1.4）。
- **第二轮（26 篇）**：`MLE-bench` / `data science agent` / `AI scientist + memory` /
  `closed-loop hypothesis` 等，即**执行落地、有真实分数**的一支。
  这一支和我们同构，是本文主要来源。

顺带：MARS 与 Iris 都把 **Famou-Agent** 列为 MLE-Bench 对照系统
（MARS 附录记为 `Gemini-2.5-Pro / 64 vCPU / 500GB / 1×A800 / 24h / 有专家知识库`）。

---

## 一、和我们同构的 8 篇（执行落地一支）

| 论文 | 核心机制 | 报告效果 |
|---|---|---|
| **Iris** (2608.02143) | 「信息范式」：把演进状态从*候选解*改成*信息状态*；**epistemic action**（只诊断不改解）；task knowledge = 可改写 claim（scope/status/provenance）；**多粒度上下文** | MLE-Bench 12h any-medal 64.9%、gold 39.1%，均为第一 |
| **Praxist** (2608.25955) | lineage 为中心的**分型证据图**（finding / lane frontier / agenda）；把"哪个设计元素带来提升、证据是否通过验证、能否重组"显式记录 | MLE-Bench 75 任务 60 枚奖牌(80.0%)、49 金，对照 Claude Code 55 枚(73.3%)/34 金；花费 \$3,054 vs \$38,370 |
| **AiScientist** (2604.13018) | thin control over thick state：File-as-Bus 工作区把跨角色、跨调用的决策相关产物持久化 | MLE-Bench Lite 81.82%；**移除 File-as-Bus 后 Any-Medal 掉 31.82pp** |
| **HASTE** (2606.30911) | 跨任务技能分 **global / domain / competition 三层**，按层加载；层间由 LLM 抽象向上提升 | 固定 159 条技能：分层加载 100% 夺牌，**平铺加载 62.5% = 完全不加载 62.5%**，且多花 2× 输出 token。冷启 40.9% → 热启 77.3% |
| **MARS** (2602.02660) | **Comparative Reflective Memory**：对比当前解与已知最优解的*差异*来定位因果；预算感知 MCTS | 开源框架 SOTA；**63% 被采用的 lesson 来自跨分支迁移** |
| **Arbor / HTR** (2606.11926) | 长生命周期 coordinator + 短生命周期 executor + 持久假设树（假设/产物/证据/提炼洞见） | 6 个真实任务全部取得最佳 held-out 结果 |
| **SAGE / MHFA** (2606.31478) | 失败恢复不用单条自由反思，而是**生成多个有证据的失败解释、独立评严重性、确定性路由到 hypothesis / design / implementation 三个干预层级** | — |
| **AIRA₂** (2603.26499) | 异步多 GPU worker 池；Hidden Consistent Evaluation | 结论值得注意：**前人报告的"长搜索过拟合"其实是评测噪声，不是记忆化** |

### 1.4 Idea 一支里唯一有用的 3 篇

- **HindSight** (2603.15164)：用 30 个月后的真实论文与引用做时间切分评价。
  LLM-as-Judge 认为 RAG 与 vanilla 无差别（p=0.584），HindSight 显示 2.5× 差距（p<0.001）；
  **HindSight 分与 LLM 判的 novelty 负相关（ρ=−0.29）**。
  → 对我们的意义：**别拿 LLM judge 当 idea 质量代理**。我们的冲刺期 idea 排序判官要谨慎。
- **SoundnessBench** (2605.30329)：12 个前沿模型对 idea 可行性判断存在**普遍乐观偏置**；
  加重提示只是把假阳换成假阴。
- **Budgeted Subset Refinement** (2607.14118)：固定预算下，**只精修选出的子集**优于均匀精修；
  单纯 rerank 不产出强 idea，必须有 refinement。

---

## 二、这些机制在我们系统上是否成立——全量实测

> 全部基于 **79 个 opus-5 run / 1109 条 ExpBank attempt / 993 次 Idea Agent 调用**，非抽样。

### 2.1 Idea Agent 拿到的注入上下文接近空

| 项 | 实测 |
|---|---|
| Idea 调用总数 | 993 |
| 注入 `experience` 中**含本 Run 已评测 attempt** 的调用 | **297（29.9%）**，中位数 **0 条** |
| 这些条目中含 idea/method 正文的 | **0 / 1268** |
| 这些条目中含逐实例结果的 | **0 / 1268** |
| 5 个 slot 里出现重复 branch 的调用 | 157 / 297（52.9%） |
| 跨任务条目 | 中位 2 条、最多 20 条（只有目录元数据，无正文） |

条目形状固定为 `{artifact_refs, benchmark, created_at, id, outcome, summary, type}`，
`outcome` 只有一个 `aggregate_improvement` 标量 + branch_id + 产物路径。
**"branch X 得 −0.58、branch Y 得 −0.44"，但没有说 X 和 Y 各自做了什么。**

### 2.2 Agent 自己去读 ExpBank，但读的正好是丢掉信息的那一层

| Idea Agent 实际打开的文件 | 占 975 次可解析调用 |
|---|---|
| 跨任务 `INDEX.md` | 100.0% |
| attempt 的 `SUMMARY.md` | **83.4%** |
| `evidence/evaluation.json`（**含逐实例**） | **16.8%** |
| `record.json`（**含逐实例**） | **2.1%** |
| 冻结的 `code/` | **4.3%** |

而 `SUMMARY.md` 的内容实测：

| 项 | 实测 |
|---|---|
| SUMMARY.md 文件数 | 1109 |
| `## 结果` 段含逐实例 / raw_scores 的 | **0 / 1109** |
| `record.json` 含 `per_instance_improvement` 的 | 855 / 1109 |
| `evidence/evaluation.json` 含逐实例的 | 830 / 835 |
| `record.conclusion` 为 6 句模板之一的 | **1109 / 1109** |
| `record.next_step` 为空的 | **768 / 1109（69.2%）** |

`conclusion` 的全部取值：
`评测有效，但未超过当前最佳方法。`(499) /
`正式评测有效，当前候选成为新的最佳方法。`(267) /
`当前候选存在工程问题，尚不能形成方法有效性结论。`(139) /
`当前版本存在工程问题…`(111) / `研究时间截止前未进入评测池…`(91) / `尚未形成结论。`(2)

**结论：数据在盘上（record.json / evidence 里有 830~855 份逐实例结果），
但 Agent 在 83% 的情况下只读到把它丢掉的那一层摘要。**
Praxist 说的"记录了发生了什么，但没有确立哪个设计元素带来了提升"，在我们这里是可复现的事实。

> 需要说明：`SUMMARY.md` 的 `## 方法` 段质量其实很高——抽查的 0004 里写了
> "Moran's I 0.136→0.223（最差子指标提升 50×）""注意力头 0.62–0.67 权重压在最不具空间结构的视图上"
> 这类可核查因果。所以缺的不是叙述能力，是**结构化字段**：结果只留了一个聚合标量，
> 结论被模板占位，next_step 七成为空。

### 2.3 聚合分掩盖了巨大的实例间异质性

| 项 | 实测 |
|---|---|
| 有 ≥2 个实例分数的 attempt | 548 |
| 逐实例 improvement 极差（max−min） | 中位 **0.248**，p90 **1.556** |
| aggregate<0 但**剔除最差单实例后 ≥0** 的 attempt | **70（占多实例 attempt 的 12.8%）** |
| 涉及的 run | 24 / 79 |
| 其中**最终仍未 Match** 的 run | **7** |

这 7 个里包含全表最接近的一个：`s42256-024-00795-w`（最终 −0.0038）。

不是说"去掉那个实例就能过"——实例不能去掉。而是说：
**决定成败的往往是某一个实例，而 Idea Agent 在 83% 的情况下只看到被平均掉之后的那个数。**

需要精确说明（订正一版早先偏强的表述）：逐实例数据**不是 Idea Agent 看不到**，
`expbank/00NN/record.json` 与 `evidence/evaluation.json` 里都有，它有 Read 权限。
真正的差别有三层：

1. orchestrator 的 `_worst_submetric`（`orchestrator.py:957`）已经把
   "最差实例是谁 / 它的值 / 其余实例均值 / 有几个实例已达标"**算好了**，
   但只写进 `refine_diagnostics`，**只随 Implement Agent 的续跑下发**；
2. 它只对 **actor 当前的 parent attempt** 计算，不是全 run 视角；
3. Idea Agent 想要同样的东西，得自己逐个 attempt 打开 `evaluation.json` 再算——
   而它实测只在 **16.8%** 的调用里打开过这个文件。

### 2.4 Idea 的自估收益系统性偏高，且在 run 内几乎不能排序

`expected_return.expected_metric.range` vs 实际分数，n=467（其余 430 条 range 为 null）：

| 项 | 实测 |
|---|---|
| 实际落在预测区间内 | 51.2% |
| 实际**低于**区间下界 | **41.8%** |
| 实际**高于**区间上界 | 7.1% |
| **高估比例（实际 < 预测中点）** | **72.2%** |
| 高估幅度 p50 / p75 / p90 | **+0.037 / +0.229 / +0.522** |
| 高估超过 0.3 的 | 95 / 467（20.3%） |
| confidence=low 的区间命中率 | 49.2%（n=325） |
| confidence=medium 的区间命中率 | 55.6%（n=142） |
| `range` 直接留空 | 430 / 1109（38.8%） |

**相关性（此处更正一版早先的错误结论）**：全量 Pearson `−0.002` 是被少数无界指标的极端值
（如 `s41592-025-02893-y` 实际 −306）拉平的**假象**，不能据此说"毫无信息量"。稳健口径：

| 口径 | n | Pearson | Spearman |
|---|---:|---:|---:|
| 全量 | 467 | −0.002 | **0.322** |
| 裁掉 \|实际\|>1.0 | 440 | **0.445** | 0.412 |
| 裁掉 \|实际\|>0.5 | 394 | 0.380 | 0.363 |
| 裁掉 \|实际\|>0.2 | 308 | 0.427 | 0.440 |

跨任务是有相关的（ρ≈0.32~0.44），但这多半来自"它跟着任务难度走"。
**在唯一有调度价值的地方——同一个 run 内部给若干 attempt 排序——它很弱**：
55 个（≥4 条且预测非常数的）run 里，run 内 Spearman 中位 0.255、均值 0.098，
**23/55 个 run 为负**。

原因也很直接：**预测区间本身几乎是常数**。467 条预测中点的 10%~90% 分位只有 `[−0.060, +0.060]`，
出现最多的区间是 `[−0.05,+0.10]` `[−0.05,+0.08]` `[−0.05,+0.15]` `[−0.05,+0.12]`——
这是在复述 Match 的判定阈值，不是在做预测。

系统性乐观与 SoundnessBench 的"普遍乐观偏置"一致。

**但粗粒度的 `target_level` 有信号**（单调）：

| target_level | n | 实际分中位 | %≥0 |
|---|---:|---:|---:|
| `surpass_sota` | 16 | **+0.1110** | 81.2% |
| `match_sota` | 396 | −0.0283 | 39.6% |
| `uncertain` | 43 | −0.1726 | 18.6% |
| `below_sota` | 12 | −0.3509 | 0.0% |

→ 排序可以用 `target_level`；**数值区间和 confidence 不应当用于任何调度决策**
（目前也确实没有用于调度）：run 内排序 ρ 中位仅 0.255 且 23/55 个 run 为负，
达不到 Budgeted Subset Refinement 那类"选子集精修"所需的打分精度。
另外 `range` 的写法本身要改——现在是复述 Match 阈值，应当要求写**相对当前 run best 的增量**。

### 2.5 领先线路上的搜索是空转，而指引里没有这一格

沿用 §2 的全量口径（79 个 opus run）。ExpBank 里共 **361** 条 `search_decision`，
其中 **306 条是 Agent 亲自做的**，**55 条是 `controller_fallback`**
（Adapter 没返回合法 `--search-action`，控制器安全回退为 refine）——
即 **15.2% 的续跑"决策"根本不是决策**。下表已剔除兜底，只看 Agent 的选择，
按**父是否为当时的 run best** 分层（这是 `current_is_run_best` 的口径）：

| 分层 | 决策 | n | 相对父的 delta 中位 | 改善率 |
|---|---|---:|---:|---:|
| **父 = 当时最佳**（41 次） | fuse | 24 | **+0.00072** | **54.2%** |
| | refine | 17 | **+0.00002** | **52.9%** |
| | **switch** | **0** | — | — |
| 父 ≠ 当时最佳（258 次） | fuse | 139 | +0.01083 | 76.3% |
| | refine | 94 | +0.01000 | 71.3% |
| | switch | 25 | +0.04145 | 84.0% |

（兜底的 55 次分布：父≠最佳 42、父=最佳 13。）

**领先线路上的改善率是 52.9%/54.2%——和抛硬币没有区别，delta 中位是 +0.00002/+0.00072。**

> 混淆声明：父=最佳是"对含噪抽样取 max"，下一次抽样天然向下回归；父≠最佳则向上回归。
> 所以这两层的 delta 差异**不能**单独证明"refine 无效"。但改善率恰好落在 50% 附近，
> 正是纯回归所预测的形态——即我们**无法把它与"完全无效"区分开**。
> 下面两组是直接的结果计数，不受回归影响。

**直接计数 1——达标之后基本爬不动**：42 个 run 达到过 Match（≥0），
首次达标后一共又做了 **342 次评测，只有 67 次（19.6%）刷新了 best**，
首次达标后的额外提升中位 **+0.00304**（p90 +0.104）。

**直接计数 2——Match→Surpass 几乎不发生**：13 个 run 最终 Surpass，
但其中 **8 个在首次越过 0 的那一次就已经 >0.1**。
**真正靠后续搜索从 Match 爬到 Surpass 的只有 5 个 run。**
Surpass 要 >0.1，而这个区间里每次评测买到的中位增量是 +0.003。

**为什么会这样——注意不是代码禁止的**：

1. `PairwiseImproveSearchPolicy.prepare_dispatch`（`search/policy.py:180`）下发的
   `allowed_actions` 恒为 `["refine","switch","fuse"]`，**无条件**，
   与 `current_is_run_best` 无关。**代码层面没有任何限制。**
   0/41 完全是 Agent 自己的选择。
2. `cli_agent_wrapper.py:589` 的决策指引只覆盖两种处境：
   `current_is_run_best` 为 **false** 时"可考虑 switch/fuse"；
   `current_score` 接近 `target_score` 时"优先受控 refine"。
   **没有任何一条覆盖"我是最佳、但已经卡住了"**。
3. 更关键的是——**指引里从未告诉 Agent："Run 的最终成绩取全部 attempt 的最大值，
   而当前最佳已经入账"**。实测 74/74 个 run 的 `effective_score` 恰等于
   全部 attempt 分数的最大值，0 例外。

所以从 Agent 的视角，放弃领先线路看起来像是在拿整个 Run 冒险；
而事实上**在平台期 switch 的下行风险是 0**（best 已锁定），上行是打破平台。
Agent 把 switch 概率压到 0 的那个区间，恰好是 switch 唯一免费的区间。

### 2.6 工程失败的救回率不到一半

父 attempt 无分数（工程失败）的父子对 **94** 组，子 attempt 拿到分数的 **40 组（42.6%）**。
`max_repairs_per_revision=1`。配合 inventory §九 已记的
"31 次超时全部跑满 59.5 分钟上限且心跳已触发"，说明修复分支既不换策略也不换层级。
对应 SAGE 的 MHFA（把根因确定性路由到 hypothesis / design / implementation 三个层级）。

### 2.7 跨任务经验层是平铺的

`.famou/cross_task_expbank`：131 条记录 / 132 个 md / 810 KB，中位 5 KB/条，
按 6 个 domain 分目录（cellular_omics 46、protein_biology 25、biomedical_modeling 19、
physical_modeling 18、molecular_design 15、relational_reasoning 8）。

注入时按 domain 过滤 + 排除本任务，最多 20 条**目录条目**（只有 domain/result/best_score/summary_path）。
**没有抽象层**：每条都是一次 run 的原始复盘叙述，没有向上提炼成
"这个 domain 通用的做法"或"跨 domain 通用的做法"。

对照 HASTE：他们的 domain 层≈我们的 domain 目录，但他们多了
**global 层 + LLM 驱动的层间提升**，而且实测*平铺加载 = 完全不加载*。
我们目前的形态更接近他们的"平铺"而不是"分层"。

> 诚实声明：我们**没有做过**开/关跨任务经验的对照实验，
> 所以不能说我们这层"无效"。只能说结构上缺抽象层，且 HASTE 的对照实验说明这个差别会致命。

---

## 三、由此得到的改进项（按证据强度排序）

### P0. 摘要层补齐结构化结果与因果字段（改的是 memory，不是吞吐）

对应：Praxist 的 finding、Iris 的 revisable claim、MARS 的 comparative reflection。
证据：§2.2 + §2.3。

1. ~~`SUMMARY.md` 的 `## 结果` 段写入逐实例 improvement 表~~ —— **已实现**
   （`storage/expbank.py` 的 `_result_lines`，22 个测试，全套 407 passed）。
   现在该段给出：聚合指标及其口径、**已达标实例数 / 总数**、
   **最差实例是谁 / 值多少 / 其余实例均值**、以及按 improvement 升序、
   最差实例加粗置顶的逐实例表（含原始子指标与达标标记）。
   提取与归纳逻辑与 orchestrator 的 `_worst_submetric` 共用同一实现，
   在 1916 条历史记录上验证重构前后逐条一致（0 处差异）。
   只影响新写入的摘要，历史 run 属不可变证据，不回填。
2. **待做**：`conclusion` 从 6 句模板改为**必须回答"相对父 attempt，
   哪个设计元素造成了哪个实例的哪个方向变化"**；没有父 attempt 时相对本 Run 最优。
   这正是 MARS 的 comparative reflection，而我们的 `## 方法` 段已经证明模型写得出
   这种内容——只是没有要求它写进 `conclusion`。
3. **待做**：`next_step` 从 69% 为空改为必填，且必须绑定到具体实例/子指标。

### P1. Idea 侧下发 `worst_instance` 诊断（对齐已有的 `refine_diagnostics`）

证据：§2.1（0/1268 条目含逐实例）+ §2.3（12.8% 的 attempt 由单实例决定成败，7 个 run 因此未 Match）。

`_prepare_benchmark_idea_request` 目前只给 `previous_best`（一个标量）。
补上与 Implement 侧 `refine_diagnostics.worst_submetric` **同构**的字段，
外加"本 Run 各 attempt 在该实例上的历史值"，让 Idea Agent 能提"专门救这个实例"的方案。
同时修掉 §2.1 里 5 个 slot 重复 branch 的问题（52.9%），改为按 attempt 去重 + 覆盖分数分位。

> 注意：inventory §2.2 已写明 prompt 里要求关注 worst_submetric。
> 这里补的不是"再说一遍要关注"，而是**给它可以据以行动的数据**。

### P1b. 平台期逃逸：告诉 Agent「best 已入账，切换不丢分」，并给出停滞信号

证据：§2.5。这是目前**证据最直接、改动最小**的一项。

三个事实叠在一起：

- Run 成绩 = 全部 attempt 的最大值（**74/74 个 run 逐一核对，0 例外**），
  所以领先线路的分数**已经锁定**，从它切走的下行风险是 **0**；
- 但父=当时最佳时 **switch 实际发生 0/54 次**，refine/fuse 的改善率是 52.9%/54.2%（≈抛硬币）；
- 首次达标后的 **342 次评测只有 19.6% 刷新 best**，靠后续搜索从 Match 爬到 Surpass 的
  **只有 5 / 42 个 run**。

改法两条，都不新增任何 LLM 调用：

1. **`refine_diagnostics` 加停滞信号**：`lineage_non_improving_streak`（本 lineage 连续几次没刷新 run best）
   与 `evaluations_since_run_best`（全 run 距上次刷新 best 过了几次评测）。
   注意这**不是**当初被判为过度设计的 `gap_to_target`——那是"离目标多远"，
   这是"这条线还在不在爬"，是两个不同的量。
2. **决策指引补第三种处境**。`cli_agent_wrapper.py:589` 现在只覆盖
   `current_is_run_best=false`（可 switch/fuse）与"接近 target_score"（受控 refine），
   **完全没有"我是最佳但已经卡住"这一格**；而且全文从未告诉 Agent
   "Run 最终成绩取 max、当前 best 已入账"。补上这句 + 停滞时明确允许 switch。

> 前置校验（必须先做，否则不要改）：`current_is_run_best=true` 且停滞时 switch
> 在我们系统上**从未发生过**，所以没有任何直接效果数据。
> §2.5 里 switch 的 +0.041/84% 全部来自"父≠最佳"层，**不能外推到领先线路**。
> 这一项要按 A/B 跑对照批次验证，不能当成已知有效。

### P2. epistemic action：允许一次"只诊断不提交"的实验

对应：Iris（消融：去掉 epistemic action，any-medal 66.7%→60.0%）
+ SAGE 的 MHFA + Iris 的 kuzushiji 案例
（表面像建模瓶颈，实为推理端默认"每图最多 100 个检测框"的截断；解除后 0.661→0.817）。

现状：`require_submit_candidate: true`，每个 implement 回合都必须产出可评测候选，
系统里**没有**"花 20 分钟只做一次数据/失败诊断、不产出候选"的动作类型。
我们的等价症状是 §2.3：pipeline 干净跑完、rc=0，但某个实例分数崩掉，
没人去查是尺度、缺失值还是输出协议。

这是三项里改动最大的一项（要新增动作类型 + 预算分配），建议**先做 P0/P1 再评估**。

### P3. 跨任务经验加 global 抽象层

对应：HASTE（固定 159 条技能：分层 100% vs 平铺 62.5% = 不加载 62.5%）。
证据：§2.7。

在现有 6 个 domain 目录之上加一层 `GLOBAL.md`（由 experience_summary agent 跨 domain 提炼），
注入时给 global + 本 domain 两层，而不是把 domain 内 46 条平铺给它挑。

---

## 四、明确**不做**的

| 提议 | 不做的原因 |
|---|---|
| 多 agent 辩论选 idea | HindSight：LLM judge 与真实价值负相关（ρ=−0.29）。我们有真分数，不需要代理判官 |
| 用自估收益给 idea 排序/分配精修预算 | §2.4：run 内排序 ρ 中位 0.255、23/55 个 run 为负；且 72.2% 高估、p90 高估 +0.52 |
| 本地 CV / 验证集 fitness | 用户已否；且 evaluator 池只用了 15.8%，打分不是瓶颈 |
| 进化/种群式 idea 搜索（EvoGens/FlowPIE 等） | 它们提升的是 Novelty/Diversity，不是落地分数；我们已实测 attempt 数 r=0.055、lineage 数 r=−0.035 与成绩无关 |
| 联网检索增强 ideation（Graph2Idea/FlowPIE） | NatureBench 禁止联网 |
| 更长时限 / 更高并发 | 属于工程吞吐，用户已明确排除 |

---

## 五、证据可复现路径

本文所有数字由以下口径产生，可重跑：

- 全体：`.famou/naturebench-runs/{opus5-v[1-5]-*, opus5-m2s-*, rerun-v3-claude-opus-*}`，79 个 run
- Idea 上下文：`artifacts/worker_calls/idea_agent_*.json` →
  `result.output.__agent_call__.request_path` → `metadata.experience`
- Idea 实际读文件：`result.telemetry.trajectory.normalized_path` 里的
  `file_path` / `path` 参数
- ExpBank：`expbank/0*/{record.json, SUMMARY.md, evidence/evaluation.json}`
- 逐实例：`record.json` 内任意层级的 `per_instance_improvement`
