# 第三方 Agent 评审机制

> 汇总 famou-scientist 里**所有"起一个独立的第三方 agent 来评审"**的环节：分别在**哪个阶段**触发、
> 评审**什么**、**为什么必须换一个 agent 来审**（而不是自己审自己）、**怎么用 `task` 工具把它起起来**、
> 喂它什么 / 不喂它什么、产出落到哪、以及怎么在轨迹里复盘这次评审。
>
> 配套阅读：`code-plan-review` / `peer-review` skill（给 agent 看的纪律本体）、
> `failure-mode-audit` / `citation-faithfulness`（评审时挂载的清单）、
> `docs/overview/ARCHITECTURE.md`（整体架构与三道 hook 门）、`docs/operations/TRAJECTORY_OBSERVABILITY.md`（子会话怎么看）。

---

## 0. 为什么要"第三方 agent"——核心是规避确认偏误

一句话动机：**写代码 / 写论文的那个 agent，挑不出自己的毛病。**

它带着"这是我刚写的、我以为我实现对了、我知道每个数字怎么来"的上下文包袱，天然会**自我辩护**而非找茬。
这不是态度问题，是**确认偏误（confirmation bias）** 的结构性后果。已有论文（*Hidden Pitfalls of AI
Scientist Systems*）记录到，Agent Laboratory / AI Scientist v2 会**静默偏离规划**——规划要求加载完整
数据集，代码却偷偷子采样 / 合成、且不声明，跑出虚高的"超过 SOTA"。**这种 gap 自己审往往审不出来。**

解法：在两个最关键的关口，**用 `task` 工具起一个 fresh-context 的独立子 agent**，只喂它待审材料 +
审查清单，**不带任何写作过程的上下文**——这样它才是真正"换一个人来审"，挑得出真问题。

> 更深一层的理由：famou-scientist 的定位是**"你提课题 → agent 自主科研 → 成稿"的"完全自主"档**。
> 而这一档**没有带客观金标的标准 benchmark 可刷**——一旦研究方向 / idea 由 agent 自己提，就没有"标准答案"
> 可对齐，业界只能退守"LLM 模拟审稿"或"真投会议"（详见 `docs/benchmarks/BENCHMARKS_AI4S.md` §0 坐标三）。
> 既然外部没有客观分数兜底，**质量保证只能内建**：本文这两道"第三方 agent 评审"正是我们**替代不存在的客观
> 评分、自己把住科研质量**的核心手段。

> 注意边界：这里说的"第三方 agent 评审"特指**起独立子 agent**的两个软关卡。它和另外两类把关机制不同：
> - **hook 硬门**（确定性、跳不过，无 LLM）：实验质量门、数字核验门、引用核验门、图版核验门、skill 加载门——
>   见 `docs/overview/ARCHITECTURE.md`。它们不是"agent 评审"，是代码级强制护栏。
> - **自评 skill**（同一个 agent 切视角自检，不另起子 agent）：`quality-gate`（定稿 go/no-go 打分卡）、
>   `research-reflection`（跑后对照假设复盘）、`novelty-gate`（新方向创新自检）。
>   它们可以、但**不强制**起子 agent。
>
> 本文聚焦**强烈建议起独立子 agent**的那两处。

---

## 1. 全景图：两个第三方评审关口

```
研究流水线（Stage 编号见 AGENTS.md）

  …写实验代码                          …写论文草稿
  (Stage 11)                          (Stage 17)
      │                                    │
      ▼  ┌─────────────────────┐           ▼  ┌─────────────────────┐
 ★关口一 │  code-plan-review   │      ★关口二 │    peer-review      │
 跑实验前 │  跑前·代码保真审查   │      修订前   │  成稿后·模拟顶会评审 │
      │  └─────────────────────┘           │  └─────────────────────┘
      │   起独立 reviewer 子 agent          │   起独立 reviewer 子 agent
      │   (task 工具, fresh context)        │   (task 工具, fresh context)
      │   只喂：代码+design+hypotheses       │   只喂：论文全文+审稿清单
      │        +baseline 配置表+保真清单      │   挂载：failure-mode-audit(Mode4/7)
      │   挂载：failure-mode-audit(Mode1/4/6) │        +citation-faithfulness
      │   产出：experiment/code-review.md     │   产出：deliverables/reviews.md
      │   判定：aligned / blocked            │   判定：accept/weak/borderline/reject
      ▼  ❌ blocked → 改对齐再审(fail-closed)  ▼  → 据意见修订(Stage 19)
   过了才允许 arc_run_experiment          再走 quality-gate 定稿
  (Stage 12，烧算力)
```

| | **关口一：code-plan-review** | **关口二：peer-review** |
|---|---|---|
| 阶段 | Stage 11→12 之间（**写完代码、还没跑**） | Stage 18（**草稿写完、还没修订**） |
| 审对象 | 实验代码 ⇄ 规划的**保真度** | 论文草稿的**科学严谨性** |
| 防什么 | 静默偏离：子采样 / 缺 baseline / 协议漂移 / 泄漏 | 确认偏误下的弱点：声称无证据、统计不足、frame-lock |
| 为何必须在此 | 实验改异步长跑，**跑完几小时才发现 gap 代价巨大** | 自己写的论文自己难挑刺，要"换个审稿人" |
| 失败处理 | **fail-closed**：blocked 就改对齐再审，绝不带 gap 烧算力 | 软驱动：据意见修订，可多轮，再交 quality-gate |
| 对称关系 | 跑**前**审**代码** | 写**后**审**论文** |

---

## 2. 关口一：`code-plan-review`（跑前·代码保真审查）

### 2.1 什么时候、审什么
实验代码 `experiment/experiment.py` 写完了**但还没跑**（Stage 11→12 之间）。skill 加载门会做兜底：
写 `experiment.py` / 调 `arc_run_experiment` 前没 load 这个 skill 会被警告。

审查清单（reviewer 对每项给 **✅一致 / ⚠️存疑 / ❌偏离** 并指到具体代码行）：

1. **数据真实性（最高危）**：代码是否真加载了规划要求的**完整数据集**？有没有偷偷子采样 / 合成 /
   换成更小更易的数据集？train/val/test 划分和规划一致吗？——论文点名的头号静默偏离。
2. **条件 / baseline 完整性**：`design.md` 里每个 condition、每个 baseline，代码都真实现并会真跑吗？
   有没有"声明了却没接进代码"、参数没真生效（不同条件跑出雷同结果）？
3. **指标 & 评估协议**：主指标定义/方向/单位、评估协议，和 `baseline-profiling` 配置表对齐吗？
   有没有偷偷换成更宽松的评估？
4. **超参 & 种子**：和规划一致？**每条件随机种子数够吗（≥3 才能估方差）**？种子真随机化了？
5. **指标输出格式**：结果是否按 sandbox 能解析的格式打印（如 `condition=X metric: value`），
   否则跑完拿不到 metrics。
6. **作弊 / 泄漏排查**：测试集泄漏、用标签作弊、答案写死等导致虚高的写法。

### 2.2 执行级证据 > LLM 眼看（关键）
光"读代码觉得对"不够——静默子采样这种坑，代码乍看是对的。要求**让代码自证**：

- 开跑时**打印关键事实**进 `runner.log`：`len(dataset)`、各 split 样本数、condition 列表、关键超参、种子。
- 加 **assertion** 把规划写死：`assert len(train_set) == <规划值>`、`assert num_conditions == N`——
  "实际只用 1000 条 / 规划是 50000 条"会**在日志或报错里立刻现形**，而不是藏进结果。
- 这条也呼应 `async-experiment-execution` 的"多打日志"：既防冷启动，也让保真度可核验。

### 2.3 挂载 failure-mode-audit
保真清单过完后，再按 `failure-mode-audit` 显式核对 **Mode 1（实现 bug）/ Mode 4（捷径依赖，标记需补
反捷径消融）/ Mode 6（方法学造假：Methods 叙述与代码脱节）**，三态判定一并写进报告。

### 2.4 产出与放行
结构化报告写 `experiment/code-review.md`：逐项 ✅/⚠️/❌ + 代码行 + 整改项 + **最终放行判定（aligned / blocked）**。

- 发现 ❌偏离 / ⚠️存疑 → **先改对齐规划，再审一遍**（走 `experiment-repair` 的修复节奏），对齐了才允许 `arc_run_experiment`。
- 若是**规划本身的问题**（如数据集其实拿不到）→ 回 Stage 4 改 `design.md`，别让代码偷偷"将就"未声明的替代方案。
- **绝不**为了往下走而放过 gap——这是真实性优先在代码层的体现。

---

## 3. 关口二：`peer-review`（成稿后·模拟顶会评审）

### 3.1 什么时候、审什么
论文草稿写完（Stage 18）、修订（Stage 19）之前。目的是**像顶会审稿人一样狠挑毛病**，产出可执行修改意见
驱动修订——不是夸，是找弱点。

> 区别于 `quality-gate`：peer-review 是「找问题、改进质量」（软，驱动修订）；quality-gate 是「最终
> go/no-go 放行」（定稿前把关）。**先 review→修订，再 quality-gate。**

### 3.2 三个审稿人视角
模拟至少 3 个不同专长的审稿人，各自给 strengths / weaknesses / **actionable revisions**：

- **Reviewer A（方法专家）**：方法是否新颖、技术是否扎实、有无明显缺陷。
- **Reviewer B（领域专家）**：是否扣题、与领域 SOTA 比如何、贡献是否实质。
- **Reviewer C（统计/严谨性专家）**：实验是否充分、统计是否有效、结论是否被数据支撑。

> ⚠️ 判 benchmark 覆盖要对齐 baseline 惯例，别空泛地嫌"benchmark 太少"：标准是**「和它对比的 baseline
> 普遍在哪些 benchmark 上评测」**——覆盖了 baseline 共用的那些就合理（哪怕只 1 个领域标准 benchmark）；
> 只有当它**比 baseline 惯例还少**才算缺陷。

### 3.3 8 点强制检查清单（每个审稿人都过一遍）
1. **主题对齐**：全篇扣题？有没有把环境/工程问题当贡献写？
2. **声称-证据对齐**：标题/摘要/结论里**每个声称**，Results 都有指标/表/图支撑？无支撑 = 严重问题。
3. **统计有效性**：置信区间/误差棒？n>1（多种子）？显著性检验合适？
4. **完整性**：各 section 齐全有深度？（NeurIPS 正文约 5000–6500 词量级）
5. **可复现性**：超参/种子/算力/数据集细节写全？（回扣 `baseline-profiling`）
6. **写作质量**：流畅散文而非 bullet 堆砌；别过度对冲；标题 ≤14 词。
7. **图表**：至少 2 张图？**零图 = desk reject**。
8. **引用分布**：不能只在 Intro/Related Work，方法/实验/讨论也要引。

### 3.4 挂载 failure-mode-audit + citation-faithfulness
- **failure-mode-audit**：审稿视角最适合盯 **Mode 4（捷径依赖：消融是否真排除捷径）/ Mode 7（frame-lock：
  这篇是不是答错了题）**——并入审稿意见。
- **citation-faithfulness**：对支撑核心论点 / 带数字的**承重引用**，用 `arc_fetch_source` 抓摘要核对
  "这条引用真支撑这句话吗"，UNSUPPORTED 的写进 required revisions（Reviewer 最爱挑的误引）。

### 3.5 产出与后续
- 结构化评审意见（按 reviewer 分组 + 总体 verdict：accept / weak accept / borderline / reject）→ `deliverables/reviews.md`。
- **Stage 19 修订**：逐条改论文，改完可再过一轮（直到无重大 weakness）。
- 修订后再走 `quality-gate`（反造假 + 阈值放行）。

---

## 4. 怎么用 `task` 工具起第三方 agent（两处通用）

两个关口的调用范式完全一致，只是喂的材料不同：

1. **首选：用 `task` 工具起一个独立 reviewer 子 agent**，`subagent_type` 选可用的通用类型（如 `general`）。
2. **只喂"待审材料 + 审查清单"作为 prompt**：
   - code-plan-review → `experiment.py`（多文件项目给全部代码）+ `design.md` + `hypotheses.md` +
     baseline-profiling 配置表 + §2.1 保真清单。
   - peer-review → 论文全文 + §3.2/§3.3 审稿清单。
3. **绝不带写作/写代码过程的上下文**——子 agent 是 fresh context，没有"这是我刚写的"的包袱，这才是
   "换个人审"的全部价值所在。
4. **降级路径**：不便起 subagent（环境不支持 / 成本顾虑）→ 显式**切换到敌意审稿人视角**刻意找茬
   （code-plan-review：当"挑剔的复现审稿人"逐行验代码；peer-review：当"我要拒掉这篇，理由是什么"），
   **绝不**用作者视角自我辩护。降级是次选，效果弱于真起子 agent。

> 一句话纪律：**把待审物 + 清单丢给"另一个你"，自己别旁观提示**——上下文越干净，挑出的 gap 越真。

---

## 5. 在轨迹里复盘这次评审（observability）

`task` 工具起的子 agent **会另开一个子 `session`**，其 `parent_id` 指向发起它的主会话。所以这次第三方
评审在轨迹里是可追溯的：

```bash
# 列会话时，reviewer 子会话会标 ↳子，agent 字段常为 general
famou-scientist trace

# 复盘主会话时连同 subagent 子会话一起拉（看完整评审过程）
famou-scientist trace <session_id> --include-children

# 网页可视化里勾「含子会话」即把 reviewer 子会话并入、各自成块
famou-scientist trace --web
```

配合落盘产物一起看：`experiment/code-review.md`（关口一）、`deliverables/reviews.md`（关口二）是评审
结论的权威记录；子会话轨迹是评审**过程**（reviewer 看了什么、怎么判的）。详见 `docs/operations/TRAJECTORY_OBSERVABILITY.md`。

---

## 6. 速查表

| 维度 | code-plan-review | peer-review |
|---|---|---|
| 触发阶段 | Stage 11→12（跑前） | Stage 18（成稿后、修订前） |
| skill | `code-plan-review` | `peer-review` |
| 起子 agent | `task` 工具，fresh context | `task` 工具，fresh context |
| 喂什么 | 代码 + design.md + hypotheses.md + baseline 配置 + 保真清单 | 论文全文 + 审稿清单 |
| 不喂什么 | 写代码的上下文 | 写作过程的上下文 |
| 挂载清单 | failure-mode-audit（Mode 1/4/6） | failure-mode-audit（Mode 4/7）+ citation-faithfulness |
| 产出 | `experiment/code-review.md`（aligned/blocked） | `deliverables/reviews.md`（accept…reject） |
| 失败语义 | **fail-closed**：改对齐再审才放行跑实验 | 软驱动：据意见修订 → quality-gate |
| 降级 | 切"挑剔复现审稿人"视角逐行验 | 切"我要拒这篇"敌意审稿人视角 |
| 子会话可见 | `trace --include-children` / 网页勾「含子会话」 | 同左 |

> 总结：famou-scientist 在**烧算力之前**和**论文定稿之前**这两个最贵的关口，各设一道"第三方 agent
> 评审"——用 `task` 起 fresh-context 子 agent、只喂材料+清单、不带原作上下文，靠**独立视角**挡住
> 自己审不出的静默偏离与论文弱点。其余把关由 hook 硬门（确定性）和自评 skill（同 agent 切视角）承担。
