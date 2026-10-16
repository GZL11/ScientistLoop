---
name: code-plan-review
description: Before running an experiment, use an INDEPENDENT reviewer subagent to audit—item by item against the design.md Implementation Contract—whether the experiment code faithfully implements the plan (dataset/splits, every condition & baseline, hyperparams, seeds, eval protocol, observability). Then a mandatory SMOKE TEST (tiny sync run) confirms it actually executes (no shape/NaN errors, asserts fire, config echo matches, first metric parses) BEFORE the expensive async run. Catches silent deviations and runtime bugs — not after a multi-hour run. Fail-closed: fix gaps, then run.
metadata:
  category: experiment
  trigger-keywords: "code review,代码审查,保真,fidelity,plan-code gap,implementation faithfulness,静默偏离,dataset subsample,子采样,baseline 对齐,eval protocol,跑前审查,before running,完整数据集"
  applicable-stages: "11,12"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

实验代码 `experiment/experiment.py` 写完了，**但还没跑**（Stage 11→12 之间）。load 这个 skill，
在**真正 `arc_run_experiment` 之前**做一道"代码 ⇄ 规划保真度审查"。

> 为什么必须跑前做：已有论文（*Hidden Pitfalls of AI Scientist Systems*）记录到，
> Agent Laboratory / AI Scientist v2 会**静默偏离规划**——规划要求加载完整数据集，代码却
> 偷偷子采样/合成数据集，且不声明，导致虚高的"超过 SOTA"结果。**代码和规划的 gap 往往
> 跑完才被发现**。现在实验改异步长跑，跑完几小时才发现 gap 代价巨大——必须跑前拦住。

## 🔑 执行方式：起一个独立 reviewer subagent，别自己审自己

**首选：用 `task` 工具起一个独立 reviewer subagent**（fresh context）：
- 只喂它这些材料：**`experiment/experiment.py`（及多文件项目的全部代码）** +
  **`planning/design.md`（含「实现契约」小节 —— 这是核对的硬基准）** + **`planning/hypotheses.md`** +
  **baseline-profiling 配置表** + 下面的保真清单。
- **核对方式 = 拿实现契约当 checklist 逐条打勾**：契约里**每一条**都要在代码里找到对应实现并判定，
  没找到的**显式列为"缺失"**——而不是泛泛"读一遍觉得对"。
- **不要带写代码时的上下文**——它不知道"这是我刚写的、我以为我实现对了"，才挑得出真 gap，
  避开确认偏误（同 `peer-review` 审论文的逻辑，这里是审代码）。
- 不便起 subagent → 降级：显式切到"挑剔的复现审稿人"视角，逐项对照，刻意找偏离。

## 保真清单（逐项核对，对着已知的坑设计）

**基准 = `design.md` 的「实现契约」**：reviewer **先对契约逐条核对**（每条 → 代码哪几行实现了 → 判定），
再确保下面这些**高危维度一条都不漏**。
> **契约缺失兜底**：若 `design.md` 没有实现契约小节、或太薄不足以逐条核 → reviewer **先据 design.md /
> hypotheses / baseline 配置表反推、重建一份逐条清单**，再据此比对（fail-safe，**绝不因为没契约就跳过审查**）。

reviewer 对每一项给"✅一致 / ⚠️存疑 / ❌偏离 / ⬜缺失"，并指到具体代码行：

1. **数据真实性（最高危）**：代码是否**真加载了规划要求的完整数据集**？
   有没有**子采样 / 合成 / 换成更小更易的数据集**？数据划分（train/val/test）和规划一致吗？
   —— 这是论文点名的头号静默偏离，重点查。
2. **条件 / baseline 完整性**：`design.md` 里每个 condition、每个 baseline，代码里
   **都真实现并会真跑**吗？有没有"声明了却没接进代码"、或参数没真正生效（不同条件跑出雷同结果）？
3. **指标 & 评估协议**：主指标的定义/方向/单位，评估协议（如何切分、如何聚合、用什么测），
   和 `baseline-profiling` 配置表对齐吗？有没有偷偷换了更宽松的评估？
4. **超参 & 种子**：超参和规划一致？**每条件的随机种子数够吗**（≥3 才能估方差）？种子真随机化了吗？
5. **指标输出格式**：结果是否按 sandbox 能解析的格式打印（如 `condition=X metric: value`），
   否则跑完拿不到 metrics。
6. **作弊/泄漏排查**：有没有测试集泄漏、用标签作弊、把答案写死等导致虚高的写法？
7. **可观测性 & 早暴露**（防"跑完才发现"）：代码是否有
   **① 进度条/周期进度行**（`[epoch 3/50][batch 120/938] 12%` + 已耗时/ETA）、
   **② 每 epoch·N step 打印 `train_loss` + val 主指标**（边跑边打，**不是只在结尾打一次**）、
   **③ 开跑回显真正生效的关键超参**（防"我以为设了其实没生效"）、
   **④ 首 batch sanity**（`shape/dtype`、标签分布、几个样本值，看数据真没读错）？
   判据：跑歪时心跳第一次 tail（~15min 内）就该看出"epoch 几、loss 多少"。规范见 `async-experiment-execution`
   §"定期打印进度+核心指标"——本项只负责**核验它真被实现**。

## 🔴 执行级证据 > LLM 眼看（关键）

光"读代码觉得对"不够——静默子采样这种坑，代码乍看是对的。要求**让代码自证**：

- 实验开跑时**打印关键事实**：实际数据集大小 `len(dataset)`、各 split 样本数、condition 列表、
  关键超参、种子 —— 进 `runner.log`。
- 加几条 **assertion** 把规划写死：`assert len(train_set) == <规划值>`、`assert num_conditions == N`。
  这样"实际只用了 1000 条 / 规划是 50000 条"会**在日志或报错里立刻现形**，而不是藏到结果里。
- 这条同时呼应 `async-experiment-execution` 的"多打日志"——既防冷启动，也让保真度可核验。
- 这些打印 + assertion **不是摆设**：下一节的**冒烟测试**会真跑一遍让它们当场触发（assert 炸 / 数据量回显不符立刻现形），而不是等全量跑完。

## 🔥 冒烟测试（静态审查通过后、launch 全量异步之前，必做）

静态审查能抓"代码⇄规划"的偏离，但 **shape 不匹配 / NaN / 某参数没生效 / 数据真读错 / API 用错** 这类
**静态读不出，必须真跑一次才暴露**。所以审查 ✅ 之后、起全量异步之前，**必做一次冒烟**：

`arc_run_experiment(code, is_async=false)` 跑一个**几秒~1 分钟的迷你版**——缩到 **1 epoch / 1~2 batch /
数据子集 / 必要时缩小模型**，但**走完整代码路径**（数据加载 → 前向 → 反向 → 指标打印）。冒烟必须确认四件事：

1. **真跑通**：无报错、无 shape 不匹配、无 NaN。
2. **assert 没炸**：契约里写死的断言（数据量、condition 数等）全过。
3. **配置/数据量符合契约**：开跑回显的**实际**数据集大小、各 split、生效超参、首 batch sanity，与实现契约一致
   （不是"我以为设了"）。
4. **指标可解析**：按约定格式（`metric: value`）真打印出了至少一个指标——否则全量跑完也拿不到 metrics。

**四项全过才允许 `is_async=true` 起全量**；任一不过 → 走 `experiment-repair` 改 → 重审/重冒烟（fail-closed）。
> 冒烟用同步小跑，正是 `async-experiment-execution` 同步/异步表里"秒级 smoke test 用同步"那一档——
> 这里把它从"可选用法"提成**全量前的必经关卡**。把"跑完才发现"压到"冒烟秒级现形"。

## Fail-closed：审不过不许跑

- 发现 ❌偏离 / ⚠️存疑 → **先改代码对齐规划，再审一遍**，走 `experiment-repair` 的修复节奏；
  对齐了才允许 `arc_run_experiment`。
- 若发现的是**规划本身的问题**（如规划的数据集其实拿不到）→ 回 Stage 4 调 `design.md`，
  别让代码偷偷"将就"一个没声明的替代方案。
- **绝不**为了往下走而放过 gap——这正是真实性优先在代码层的体现。

## 产出

结构化审查报告写入 `experiment/code-review.md`：
- **契约逐条核对表**：实现契约每一条 → ✅/⚠️/❌/⬜缺失 + 指到代码行 + 说明；
- **整改项**：每个 ❌/⚠️/⬜ 对应的修法；
- **冒烟结果**：四项确认（跑通 / assert / 配置·数据量符合契约 / 首指标可解析）+ 关键回显摘要 + 通过与否；
- **最终放行判定**：`aligned + smoked`（可起全量）/ `blocked`（列明卡在哪）。

对话里只给摘要 + 关键 gap + 文件路径。

## 配合其它 skill / 流程

- **接在写代码之后、跑实验之前**（AGENTS.md 第 5 步末 → 第 6 步前）。
- **同时 load `failure-mode-audit`**：本 skill 是它**跑前关卡**的驱动——保真清单逐项过完后，
  再按 failure-mode-audit 显式核对 **Mode 1（实现 bug）/ Mode 4（捷径依赖，标记需补反捷径消融）/
  Mode 6（方法学造假：Methods 叙述与代码脱节）**，三态判定写进 `code-review.md`。
- **对称于 `peer-review`**：peer-review 写后审**论文**，本 skill 跑前审**代码**——两道独立 reviewer。
- **配 `baseline-profiling` / `experimental-design`**：保真清单的"基准/数据/协议"以它们的产物为准绳。
- **配 `experiment-repair`**：发现 gap 的修复走它的诊断→改→重审循环。
- **跑后还有 `research-reflection`**：本 skill 是**跑前**保真，reflection 是**跑后**对照假设复盘，前后呼应。

> 一句话：长实验跑下去之前，先请"另一个你"对着规划逐行验代码、并让代码打印真实配置自证——
> 把"代码和计划对不上"挡在烧算力之前，而不是几小时后才发现。
