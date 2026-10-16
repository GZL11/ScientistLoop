# NatureBench 接入与运行指南

本文档说明 NatureBench 的任务要求、官方评分标准，以及如何通过 Famou Loop 接入并
运行一个新的 NatureBench case。这里的主路径是 benchmark-managed 模式：任务、数据、
运行环境和 evaluator 由 NatureBench 定义，Famou 负责自主研究循环、异步调度、隔离
评测、经验沉淀和证据保存。

通用的 Agent/Benchmark/Evaluator 插件接口和新 benchmark 开发清单见
[`FAMOU_ADAPTER_PLUGIN_ARCHITECTURE_CN.md`](../FAMOU_ADAPTER_PLUGIN_ARCHITECTURE_CN.md)。

NatureBench 已经提供任务说明、公开数据、任务镜像、提交协议和正式 evaluator。因此
不需要把每个 case 改写成 Famou 的 `goal.yaml`，也不需要为每个 case 编写 Python
Adapter。统一入口是：

```bash
famou-scientist agent run ...
```

## 1. NatureBench 是什么

NatureBench 是面向科学机器学习编码智能体的端到端 benchmark，目标是评估智能体能否
在真实 Nature 系列论文的任务上达到或超过论文报告的 SOTA。

- 发布时间：2026 年 6 月 24 日
- 论文：*NatureBench: Can Coding Agents Match the Published SOTA of Nature-Family Papers?*
- 论文链接：https://arxiv.org/abs/2606.24530
- 代码仓库：https://github.com/FrontisAI/NatureBench
- 数据集：https://huggingface.co/datasets/FrontisAI/NatureBench
- 官方榜单：https://frontisai.github.io/NatureBench/
- 规模：90 个任务、6 个科学领域
- 统一预算：每个任务 4 小时 Agent solve 有效研究时间；evaluator 等待时间按官方规则暂停计时

六个科学领域包括 Cellular Omics、Protein Biology、Biomedical Modeling、Physical
Modeling、Molecular Design 和 Relational Reasoning。任务可能是回归、分类、聚类、
生成、分割、模拟、结构建模或其他专用科学计算任务。

NatureBench 测试的不是单次问答能力，而是完整的自主工作流：理解题面、检查数据、
编写代码、训练或运行方法、生成规定产物、请求正式评分，再根据结果继续改进。

### 1.1 官方资源与运行条件

NatureBench 官方任务按资源分组：

| 任务组 | 数量 | 官方运行资源 |
|---|---:|---|
| CPU | 3 | 不使用 GPU |
| GPU Low | 70 | 单张 NVIDIA RTX 3090/4090，24 GB 显存 |
| GPU High | 17 | 单张 NVIDIA A800，80 GB 显存 |

官方流程的其他关键条件：

- 每个任务有 4 小时解题预算。
- 单次 evaluator 最长可运行 1 小时。
- 官方计时器在 evaluator 执行期间暂停，因此 evaluator 时间不计入 4 小时解题预算。
- 评测时禁止 Agent 使用 web search/web fetch，但容器仍需访问模型服务，不能简单理解为
  完全断网。
- 每个任务应使用 `naturebench-base:v3` 加该 case 的 `Dockerfile.v3` 构建精确环境。

当前 Famou 一键脚本为每个 case 只提交一个 fm-job。脚本会从官方 task-set 自动识别
CPU/GPU 档位：CPU task 申请 0 卡，GPU Low/High task 默认申请 1 卡，也可通过
`AGENT_GPU` 覆盖为多卡。Idea/Implement/Evaluation Pool 在该任务内共享资源，Evaluation
Pool 再根据每条 Idea 声明的 CPU、主存、GPU 数量和每卡显存动态装箱。当前 Claude Code
节点通过 `--allowedTools` 只开放文件工具和 Implement 所需 Bash，不开放
WebSearch/WebFetch；Codex 和 OpenCode 的正式运行仍应按各自 CLI 配置再次核验网络工具
策略。

## 2. Task Package 与可见性

每个 NatureBench case 都是一个自包含任务包：

```text
tasks/<case_id>/
├── problem/                       # Agent 可见
│   ├── README.md                  # 科学问题、指标、输出格式、提交要求
│   ├── data_description.md        # 数据字段和文件格式
│   └── data/                      # 公开训练集和无标签测试输入
├── evaluation/                    # Agent 不可见
│   ├── evaluator.py               # 官方原始指标计算
│   └── ground_truth/              # 隐藏测试标签或参考答案
├── environment/
│   └── Dockerfile.v3              # case 专属运行环境
├── metadata.json                  # 领域、资源、主指标、baseline 和论文 SOTA
└── licenses/                      # 数据和第三方资产许可
```

公开边界必须严格保持：

- Agent 可以读取 `problem/`，只能向自己的 workspace 写入代码和结果。
- `problem/data/` 是只读数据，Agent 不得修改。
- Agent 不得读取 `evaluation/`、`ground_truth/`、论文 SOTA 或 evaluator 实现。
- evaluator 只能在可信评测环境中执行。
- 任务输出必须完全遵守该 case 的 `problem/README.md`，不能假设所有 case 都输出同一种
  JSON、CSV 或模型文件。

## 3. End-to-End Code Submission 要求

NatureBench 使用 End-to-End Code Submission。Agent 提交的核心是可重复运行的完整代码，
而不是一份手工生成的预测文件。

标准执行契约是：

```bash
DATA_DIR=/path/to/problem/data \
OUTPUT_DIR=/path/to/workspace/output \
python /path/to/workspace/run.py
```

其中：

- `workspace/run.py` 是统一入口。
- `DATA_DIR` 指向当前 case 的公开数据目录。
- `OUTPUT_DIR` 指向本次 canonical run 的产物目录。
- `run.py` 必须完成读取数据、预处理、训练或算法求解、推理和写出结果的完整流程。
- 输出一般按 `OUTPUT_DIR/<instance_name>/...` 组织，具体文件名、列名、数据类型和行数以
  case 自己的题面为准。
- 正式评测运行的是冻结后的代码快照，不信任 Agent 声称的本地分数或临时输出。

Implement Agent 提交前需要用公开数据完成轻量 Smoke Test，至少检查：

1. `run.py` 能在任务镜像中启动。
2. 正确使用 `DATA_DIR` 和 `OUTPUT_DIR`。
3. 规定的输出目录和文件能够生成。
4. 文件格式、列名、数据类型和基本数量约束正确。
5. 没有读取公开边界之外的路径。

Smoke Test 不等同于正式评测，也不应在 Agent 内重复执行所有 case 或偷偷调用 evaluator。

## 4. 官方评测标准

### 4.1 原始指标

每个 case 的 `evaluation/evaluator.py` 读取 Agent 的输出和隐藏 GT，返回该科学任务的
原始指标，例如 accuracy、AUROC、F1、ARI、RMSE、MAE、MSE 或 R2。指标方向和主指标
由 `metadata.json` 定义。

一个 case 可以包含多个 instance，也可以返回多个指标，但 SOTA 归一化只使用每个
instance 标记为 `is_primary: true` 的主指标。其他指标作为诊断和科研证据保留，不会
自动进入 `aggregate_improvement`。

### 4.2 相对论文 SOTA 的统一分数

NatureBench 使用 AutoSOTA 风格归一化：

```text
improvement = direction * (agent_score - sota_score) / abs(sota_score)
```

- 越大越好的指标，`direction = +1`。
- 越小越好的指标，`direction = -1`。
- `improvement = 0` 表示精确追平论文 SOTA。
- `improvement > 0` 表示超过论文 SOTA。
- `improvement < 0` 表示低于论文 SOTA。

如果 `metadata.json` 为同一主指标列出多个 SOTA，官方逻辑会按指标方向选择其中最强的
值：越大越好时取最大值，越小越好时取最小值。

多 instance 任务先分别计算：

```text
per_instance_improvement[instance]
```

再取算术平均：

```text
aggregate_improvement = mean(per_instance_improvement)
```

某个 instance 缺失主指标，或者结果为非数值、NaN、inf 时，该 instance 记固定失败
惩罚 `-1.0`，而不是从平均值中忽略。

### 4.3 Match-SOTA 与 Surpass-SOTA

为避免术语混用，文档和报告统一采用以下含义：

| 条件 | 含义 |
|---|---|
| `aggregate_improvement < 0` | 尚未达到论文 SOTA |
| `aggregate_improvement = 0` | 精确 Match-SOTA |
| `aggregate_improvement >= 0` | 达到或超过论文 SOTA |
| `aggregate_improvement > 0.1` | NatureBench 榜单口径的 Surpass-SOTA |

因此“超过 SOTA”与官方榜单的“Surpass-SOTA”不是完全相同的阈值：刚刚超过 0 说明优于
论文 SOTA，但只有归一化提升超过 10% 才计入 Surpass-SOTA rate。

NatureBench Benchmark Facility 会把上述公开口径写入
`benchmark_task.contract.score_interpretation`，并声明
`primary_target: [match_sota, surpass_sota]`。IdeaAgent 在每条 Idea 的
`expected_return` 中预测 `below_sota`、`match_sota`、`surpass_sota` 或 `uncertain`，同时
给出置信度、依据和成立假设；无法可靠量化时数值区间为 `null`。该预测只用于 Idea 排序和
搜索策略，不能写入官方指标，Match/Surpass 的最终结论仍只来自正式 evaluator。

NatureBench Harness 默认开启 `pairwise_improve` Search Policy。有效评分返回后的 Improve
回合会同时拿到当前 Refine 与 IdeaSpark 队首 New Idea；ImplementAgent 显式选择
`refine/switch/fuse`。选择 Refine 时 New Idea 重放到队尾，Switch/Fuse 才消费该 Idea；
Debug/Repair 不参与配对。该策略属于 Infra，不改变 NatureBench evaluator 或 task adapter。

### 4.4 多次评测与最终分数

同一个 task 可以多次正式评测。当前尝试返回 `aggregate_improvement`，最终任务分数是：

```text
best_aggregate_improvement = max(all aggregate_improvement attempts)
```

后续较差的提交不会覆盖之前的最好成绩。Famou 会把每次尝试的代码、产物、原始指标、
归一化分数和日志分别保存，不能只保留最后一次结果。

### 4.5 Validity Judge

NatureBench 官方流程在数值 evaluator 之后还有一个 post-hoc Validity Judge。它是反作弊
和方法有效性审查，不是第二个数值 evaluator：不会重新读取隐藏 GT 计算 accuracy、RMSE
等指标，也不判断方法是否有论文级创新性。它只回答一个问题：产生最终最好数值结果的
提交，是否确实使用提供的数据和一个真实的训练、学习、拟合或优化方法完成了任务。

官方实现位置（以当前 NatureBench 版本为准）是：

```text
judge_core/policy.py       # Judge system prompt、有效性政策和证据大小限制
judge_core/attempts.py     # 找到 SCORE_ATTEMPT，构造提交时间线和 Judge 上下文
judge_core/trace.py        # 截取带时间戳的 Agent 执行轨迹
judge_core/sources.py      # 收集并截断最终 workspace 中的源码
judge_core/runner.py       # 组装输入、调用 Judge、校验严格 JSON 结果
```

#### 4.5.1 Judge 审查哪一次提交

Judge 审查的是最佳数值分数对应的 `SCORE_ATTEMPT`，不是最后一次提交，也不是 Agent
最后退出时 workspace 中的任意代码。数值 evaluator 会为每次 `/evaluate` 记录 attempt，
最终从成功 attempt 中选择最大的 `aggregate_improvement`；`submissions.jsonl` 和
`run_summary.json` 中的 `best_attempt` 用来定位这次提交。

如果 Agent 后来又修改了 workspace，最终 workspace 只能作为补充证据，不能单独证明
`SCORE_ATTEMPT` 使用了什么代码状态。因此 Famou 必须冻结并保存最佳 attempt 的代码快照、
提交时刻、canonical output、evaluator 结果和对应轨迹，Judge 请求只能引用这个冻结的
`attempt_id`。

#### 4.5.2 Judge 的证据输入

官方 Judge 看到的是用于审查的公开题面和有限证据，不应看到 evaluator 源码、隐藏 GT 或
其他可信侧私有文件。输入主要包括：

| 证据 | 用途 |
|---|---|
| `problem/README.md` | 任务目标、输入、输出、指标和提交协议 |
| `problem/data_description.md` | 公开数据的组织方式、字段含义和文件角色 |
| attempt 时间线 | 所有评测提交及结果，标记哪一次是 `SCORE_ATTEMPT` |
| 带时间戳的 Agent 轨迹 | 主要行为证据，用来还原方法如何产生该提交 |
| 最终 workspace 源码 | 补充证据，不保证等于产生 `SCORE_ATTEMPT` 的代码状态 |

轨迹过大时，官方实现保留轨迹头部、`SCORE_ATTEMPT` 所在时间区间和尾部，以便同时看到
前期数据理解、关键实现行为和最终提交。当前实现的证据上限是：

| 限制 | 当前值 |
|---|---:|
| 轨迹摘要 | 2 MB |
| 单个源码文件 | 60 KB |
| 源码文件数量 | 40 个 |
| 源码总量 | 600 KB |

这些限制是 Judge 输入的摘要限制，不是 Agent workspace 或 ExpBank 的保存限制。Famou
仍然保留完整原生轨迹、代码、stdout、stderr 和 evaluator 原始响应；发送给 Judge 的只是
按官方规则生成的证据视图。

#### 4.5.3 Judge 的处理流程

```text
全部数值评分记录
        │
        ▼
选择 best_aggregate_improvement 对应的 SCORE_ATTEMPT
        │
        ▼
读取 problem/README.md + data_description.md
        │
        ├── 读取全部评分 attempt 时间线
        ├── 截取 SCORE_ATTEMPT 附近的 Agent 执行轨迹
        └── 读取最终 workspace 源码作为补充证据
        │
        ▼
使用官方 JUDGE_SYSTEM 发起一次 LLM Judge 调用
        │
        ▼
{"is_valid": true | false, "reason": "..."}
```

#### 4.5.4 官方 Judge 的有效性标准

轨迹是判断行为的主要证据，源码是补充证据。Judge 必须结合题面和数据说明判断提交结果
是否来自一个使用给定数据训练、学习、拟合或优化的方法。官方 `JUDGE_SYSTEM` 给出的
典型禁止行为包括：

- 随机猜测，返回硬编码常数、硬编码规则或查找表。
- 通过空输出、退化输出或其他故意失败方式操纵 evaluator 的计分逻辑。
- 从测试输入、其他文件、数据字段或可访问 artifact 中直接恢复 GT。
- 通过复制、join、聚合、求和、积分、重排、坐标变换、峰值检测或单调变换等方式间接
  恢复目标值。
- 从公开 benchmark、外部数据库、网页或已知数据集答案中查表恢复目标。
- 访问隐藏 evaluator、GT 或其他私有评测资源，或针对其实现进行投机。
- 把提供的数据当作答案库，通过模板或 nearest-neighbor 直接复制答案，而不进行真实拟合；
  合法拟合的非参数方法本身不因此无效。
- 直接调用 benchmark/reference/answer-producing API，或调用外部 LLM 直接生成最终提交。
- 关键方法没有加载并使用题目提供的训练数据进行训练、学习、拟合或优化。
- 用手工调参后的常数或权重直接充当预测器，而不是训练或优化得到的方法。

以下情况本身不构成 invalid：

- 使用简单的经典 ML、图/谱方法、数值优化或其他非深度学习方法。
- 使用通用库、solver 或任务允许的公开预训练模型，只要它没有直接提供题目要求的最终答案。
- 使用 `/evaluate` 的反馈选择或改进一个真实拟合的方法。
- 复用本次 run 中此前由合法方法训练得到的模型、参数或输出。
- OOM、timeout、crash、推理 bug、格式错误、输出不完整或 4 小时耗尽。

最后一类是工程或性能问题，不应仅凭失败结果判定作弊；只有存在故意利用失败或评分规则
的积极证据时，才应判为 invalid。Judge 也不以创新性、可解释性、速度或科学结论质量
作为本阶段的判定项，这些属于 Loop 的研究目标或其他分析模块。

#### 4.5.5 Judge 输出与 Famou 接入

官方 Judge 的模型输出必须严格是以下 JSON，不能带 Markdown 或其他字段：

```json
{"is_valid": true, "reason": "..."}
```

`reason` 应用一到两句话引用导致结论的具体源码或轨迹证据。官方 LLM verdict 只有
`true`/`false` 两种值；Famou 外层再把 API 失败、证据缺失或 JSON 解析失败表示为第三种
状态，以免把基础设施故障误报为作弊。这个三态只属于 Famou 的错误处理协议，不是官方
Judge 的输出 schema：

| `is_valid` | Famou 处理 |
|---|---|
| `true` | `effective_improvement` 保留最好数值分数 |
| `false` | 原始 `best_aggregate_improvement` 保留，但 `effective_improvement=null` |
| `null` | Judge API、证据或解析失败；不判作弊，保留原始最好数值分数并记录错误 |

Famou 已把这套官方 Judge 接到 Loop 结束阶段。一键运行默认 `VALIDITY_JUDGE=1`：Controller
从 Leaderboard 取得最佳 `expbank_attempt_id`，只向可信 worker 发送该 ID；可信 worker
调用外部 `TrajectoryAdapter`，从 `expbank/<attempt>/code` 和 canonical evidence 生成官方
兼容的 `run_summary.json`、`submissions.jsonl`、`famou.jsonl` 与精确代码快照；随后独立
`JudgeAdapter` 调用 NatureBench `judge_core.runner.judge_task()`。Judge 结果与数值评分
使用同一 RSA 私钥签名返回。

Judge API 凭据和 `JUDGE_*` 配置只写入 Agent 挂载根之外的 trusted 目录，不会暴露给
Idea/Implement Agent。最终摘要同时记录 `best_score`、`effective_score` 和通用
`final_evaluation`，因此 invalid 不会改写历史原始分数，也不会把 Judge 服务故障误报成
无效方案。官方当前代码默认 Judge 模型为 `claude-sonnet-4-6`，可通过可信侧配置替换；
Judge 模型、API key 和 evaluator 私有路径不能进入 Agent 视图。

完整证据写入 trusted evidence store，Agent 只能看到脱敏后的结果字段。Judge 结果、使用的
证据 manifest、模型、原始响应和最终生效分数都写入 Controller 产物，保证后续复核时能
区分“数值没达到 SOTA”“方法无效”和“Judge 基础设施失败”。

### 4.6 当前 Famou 与官方口径的对齐状态

| 项目 | 当前状态 | 严格官方运行要求 |
|---|---|---|
| 官方 task evaluator | 已接入 | 保持使用 NatureBench 当前版本实现 |
| AutoSOTA 归一化 | 已接入 | 保持读取最强主指标 SOTA |
| 多次提交取 best | 已接入 | 保留全部 attempts |
| evaluator/GT 文件隔离 | 已接入 | Agent 不可见私有目录 |
| evaluator 响应防伪 | 已接入 | Famou 额外使用 RSA 签名 |
| 代码、产物和日志证据 | 已接入 | 运行结束后不可丢失 |
| post-hoc validity judge | 已接入，默认启用 | 使用官方 `judge_core`，审查最佳冻结 attempt |
| GPU Low/High 资源 | 已按 task-set 自动申请 GPU | GPU Low/High 默认各申请 1 张卡；多卡仅在任务和启动参数明确要求时申请 |
| 研究截止后的评测与 Judge | 已与 Agent 预算分离 | 截止时已进入 Evaluation Queue 的提交全部完成，随后额外执行 Judge |
| 研究期间 evaluator 计时 | 异步等价处理 | 官方同步等待 evaluator 时暂停计时；Famou 中 Agent 与 evaluator 并行，因此研究墙钟连续计算，不能再次暂停而重复赠送 Agent 时间 |
| 禁止 web search | Claude 路径已限制相关工具 | 其他 Agent Runtime 仍需核验 |

因此文档中的“正式评分”表示分数来自官方 task evaluator；当前 validity judge 也已对齐。
“严格官方可比”仍要求资源、计时和所有 Agent Runtime 的网络工具策略完全对齐。

### 4.7 官方运行、计时与收尾规则汇总

NatureBench 的“4 小时”是 Agent solve 的有效研究预算，不是从容器创建到 Judge 结束的
整个 Job 硬墙钟。Setup、数值 evaluator 和最终 Judge 都有各自的阶段和上限：

| 项目 | NatureBench 官方规则 | Famou 对齐方式 |
|---|---|---|
| Setup | 默认上限 14400 秒；完成 Setup 后才启动 solve timer，不消耗 4 小时 solve 预算 | 启动和可信设施准备使用独立 `STARTUP_GRACE_SEC` |
| Agent solve | 默认 14400 秒，即 4 小时有效解题时间 | Idea/Implement 研究窗口连续运行 4 小时 |
| 单次数值 evaluator | 子进程上限 3600 秒 | `EVALUATION_TIMEOUT_SEC` 默认 3600 秒 |
| evaluator 是否计入 4 小时 | 官方 Agent 同步等待 `/evaluate`，服务端在 evaluator 执行期间暂停 solve timer | evaluator 与 Agent 异步并行；Agent 仍在工作，因此不暂停研究墙钟，避免重复赠送 Agent 时间 |
| 提交次数 | 没有固定默认上限；成功和失败调用都会形成 attempt | 默认不限制，除非 benchmark 或调用方显式配置 `MAX_BENCHMARK_ATTEMPTS` |
| 最终数值分数 | 所有成功 attempt 中最大的 `aggregate_improvement` | Leaderboard 保留全部 attempts，并选择最佳冻结 attempt |
| Agent 到期时的评测 | 官方先等待当时在途 evaluator 完成，再读取最终 best | 4 小时截止后停止 Idea/Implement；排空截止时已经进入 Evaluation Queue 的 `queued`、`waiting_resources` 和 `running` Candidate |
| 尚未提交的实现 | 官方不会替 Agent 自动产生新提交 | Famou 标记为 `not_executed`，不再启动 canonical run 或 evaluator |
| Validity Judge | 数值评测收尾后额外执行，不占 Agent solve 预算 | 排空 Evaluation Queue 后，对最佳冻结 attempt 额外执行 |
| Resume | 保留提交历史、best score 和已消耗有效时间；两次运行之间的 idle 时间暂停 | 恢复持久化队列、ResearchState、ExpBank、Actor session 和预算账本 |
| Force fresh | 先归档旧状态，避免静默覆盖原证据 | 新建唯一 `RUN_ID/RUN_DIR`，历史 run 保持只读可追溯 |
| 轨迹、token 与 cost | 官方稳定记录提交次数和任务时长；榜单不替 Agent Infra 统一不同 CLI 的成本口径 | Loop Infra 逐激活写统一 usage/trajectory ledger，并在 Run 摘要中按角色、运行时和模型汇总；原始费用与显式单价重算费用分开保存，兼容网关下的 CLI 美元等价成本不等同于实际账单 |

这里需要区分“预算不扣除 evaluator 时间”和“Job 不经过 evaluator 时间”：官方同步协议
会在 Agent 阻塞等待评分时暂停计时；Famou 中 evaluator 与后续 Idea/Implement 同时运行，
这段时间 Agent 没有阻塞，所以必须正常消耗 4 小时研究预算。研究窗口到期后，已经进入
评测队列的提交和最终 Judge 仍可继续运行，因此整个 fm-job 的实际墙钟可以超过 4 小时。

Famou 的截止状态机和证据字段在 7.9 节展开；上述规则是阅读分数、耗时和 fm-job 状态时
应采用的统一口径。

## 5. Famou 运行链路

Famou 将 Agent、Benchmark 和 Evaluation 作为三个设施隔离：

```text
                    Agent Facility
        ┌──────────────────────────────────┐
        │ Idea Agent ──► IdeaSpark         │
        │                    │             │
        │                    ▼             │
        │             Implement Agent      │
        │                    │             │
        │          Smoke Test + submit     │
        └────────────────────┼─────────────┘
                             ▼
                     CandidateRef
                    冻结代码和入口契约
                             │
                             ▼
                  Benchmark Facility
             canonical run + 产物完整性检查
                             │
                             ▼
                      ArtifactRef
                   冻结可评测产物快照
                             │
                             ▼
                  Evaluation Facility
              可信 evaluator + 响应签名校验
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
          ExpBank/Leaderboard       Actor mailbox
                 │                       │
                 │                       ▼
                 │          resume 原 Session 修复或微调
                 │
                 ▼ Loop 结束，选择最佳 attempt
          官方 Validity Judge
                 │
                 ▼
        best_score + effective_score
```

具体行为如下：

- Idea Agent 读取公开题面和完整 ExpBank，持续产生不重复的研究方案。
- Implement Agent 读取 Idea、历史方案和代码，在隔离 worktree 中实现。
- Implement Agent 必须显式调用 `submit_candidate`，不能以进程自然退出代替提交。
- `submit_candidate` 只登记并冻结 Candidate，不同步等待 evaluator；固定入口可从 benchmark
  contract 或 `method_manifest.json` 自动补全，入口缺失、路径错误和 Python 语法错误会在
  当前 Agent 回合立即拒绝，不再等到异步 preflight 才发现。
- Actor 随后 park，释放 Implement 并发槽，但保留原 worktree、逻辑生命周期和 Agent
  Session。
- Benchmark Facility 独立运行 canonical experiment，形成不可变 ArtifactRef。
- Evaluation Facility 对 ArtifactRef 发起可信评分，验证签名后才接受结果。
- 工程错误通过 mailbox 路由回原 Actor；有并发槽时恢复同一 Session 修复。
- 有效科学结果写入 ExpBank，供后续 Idea 和 Implement Agent 使用。
- Loop 结束后只对 Leaderboard 最佳冻结 attempt 运行官方 validity judge。

Idea、Implement 和 Evaluation 使用统一 `AsyncOrchestrator`、持久化队列、预算和恢复
机制。默认不限制正式评分次数，由 4 小时墙钟预算和队列背压控制；只有 benchmark 或
调用方显式指定 `--iterations` 时才限制总尝试数。

## 6. Evaluator 隔离方式

一键脚本只提交一个使用精确 task 镜像的 fm-job。资源属于整个任务，隔离边界由进程身份
和文件权限建立：

```text
Single Task fm-job（共享 CPU/GPU/内存）
├── root Trusted Supervisor / Evaluator
│   ├── trusted/naturebench/          官方 evaluator、GT 和 metadata
│   ├── trusted/famou-scientist/      可信适配运行时
│   ├── trusted/private_key.pem       响应签名私钥
│   ├── trusted/judge_settings.json   Judge 凭据
│   ├── trusted/logs/evaluator.log    可信进程日志
│   └── controller/evaluator_channel/ 请求、脱敏响应和公钥
└── non-root Agent / Candidate（setpriv + no-new-privs）
    ├── problem/                      公开题面只读副本
    ├── famou-scientist/              排除可信模块的源码快照
    ├── agent_home/                   Agent 凭据和运行 HOME
    └── 独立 worktree / staging       只写自己的代码和临时产物

<run>/trusted/raw_evaluator_artifacts/<request_id>/
├── request.json                  可信 worker 实际消费的请求
├── response.json                 evaluator/Judge 完整原始响应
├── stdout.txt                    原始 evaluator stdout
├── stderr.txt                    原始 evaluator stderr
└── manifest.json                 可信证据清单

<run>/trusted/raw_evaluator_artifacts/
├── submissions.jsonl             NatureBench 官方格式的全部评分历史
└── submission_map.jsonl          Candidate → 官方 attempt 审计映射
```

隔离保证包括：

1. fm-job 的 CFS 挂载根是单次 run 子目录，不挂载 NatureBench 原仓库。
2. `trusted/` 和 `controller/` 归 root 且权限为 `0700`；Agent 即使猜到路径也只能得到
   `Permission denied`。
3. `prepare_run.py` 把 `problem/` 复制为公开只读副本，把完整 task evaluator/GT 复制到
   `trusted/`；同时从 Agent 源码快照排除 `evaluator_worker.py`、
   `evaluate_task.py`、`trajectory_adapter.py` 和 `judge_adapter.py` 等可信侧代码。
4. 公开题面副本生成逐文件 SHA-256 manifest，便于审计。
5. 评测请求不能指定任意 `output_dir`；可信 worker 永远读取固定 canonical output。
6. evaluator 响应由 root-only RSA 私钥签名，Controller 使用固定公钥验签。
7. Agent 即使能写自己的 CFS 子目录，也不能伪造可信正式分数。
8. Judge 请求只能指定已有 `attempt_id`，不能指定任意代码路径、轨迹路径或 Judge 配置。
9. Judge 精确读取 `expbank/<best_attempt>/code`，不会误审后来被其他 Actor 修改的 workspace。
10. evaluator 的完整 response、进程 stdout/stderr、私有扩展和异常 traceback 只写入
    `<run>/trusted/raw_evaluator_artifacts/`；Agent 可见的 `responses/` 和
    `artifacts/evaluator_scores/` 只保留白名单字段。NatureBench 官方响应明确公开的
    `raw_scores`、`per_instance_improvement` 和 best-attempt 字段属于白名单。
11. 公共响应仍保留统一的 `valid/metrics/diagnostics_public/stdout/stderr/extra` 协议，
    但 stdout/stderr/extra 必须是适配器显式声明的 public 版本，不能从 raw 字段回退。

## 7. 接入一个新的 NatureBench Case

同一 NatureBench 内的新 case 使用统一协议，通常只需要检查任务并配置启动参数，不需要
修改 Core。建议按下面步骤接入。

### 7.1 Benchmark 是如何接入 Famou 的

NatureBench 作为一个 benchmark 系列只做一次适配。它没有把 90 个 task 逐一改写成
Famou 配置，而是把官方 task package 的公开侧和可信侧分别接到三个通用设施：

NatureBench 首次接入实际需要实现以下内容；这些已经作为参考插件落地：

| 必需实现 | NatureBench 文件 | 接入内容 |
|---|---|---|
| 插件注册入口 | `integrations/naturebench/plugin.py` | 分别创建 Benchmark Facility 和 Evaluation Facility，并声明可选任务收尾 |
| 公开 Benchmark Adapter | `integrations/naturebench/benchmark.py` | `task_id`、公开题面、`run.py` 契约、candidate 执行和 ArtifactRef |
| 可信 Evaluator Adapter | `integrations/naturebench/evaluation.py` | 固定 canonical output、Evaluator Transport 和统一 EvaluationResult |
| 可信评分 Worker | `integrations/naturebench/evaluator_worker.py` | 加载官方私有资源、处理操作并使用 RSA 签名响应 |
| 官方分数映射 | `examples/naturebench/evaluate_task.py` | 调用 `eval_service`，映射原始指标和 AutoSOTA 分数 |
| 官方轨迹投影 | `integrations/naturebench/trajectory_adapter.py` | 把 canonical evidence 确定性转换为官方 transcript、提交历史和 summary |
| 官方任务收尾 | `integrations/naturebench/judge_adapter.py` | 注册 Famou Agent transcript 并调用官方 `judge_core` |
| 公开/私有 staging | `examples/naturebench/fmjob/prepare_run.py` | 复制公开 `problem/`，并把 GT、可信 runtime 和凭据放入 root-only `trusted/` |

以上是“接入一个 benchmark 系列”要写的 Adapter；后面的 7.2 至 7.8 是“在已经接入
NatureBench 后增加一个 task”需要做的配置和检查，二者不能混为一谈。

```text
NatureBench 官方仓库
│
├── tasks/<task_id>/problem/ ── prepare_run.py ──► Agent 可见 problem/
│                                                     │
│                                                     ▼
│                                      NatureBenchBenchmarkFacility
│                                           题面 + run.py 执行契约
│                                                     │
│ CandidateRef ── canonical run ──────────────────────┤
│                                                     ▼
│                                                ArtifactRef
│                                                     │
├── tasks/<task_id>/evaluation/ ──────────────────────┤ root Trusted Process
├── tasks/<task_id>/metadata.json ────────────────────┤
│                                                     ▼
├── eval_service.py ◄── evaluate_task.py ◄── evaluator_worker.py
│                                                     │
│                                                     ▼ RSA 签名结果
│                                      NatureBenchEvaluationFacility
│                                                     │
│                                                     ▼
│                                           ExpBank + Leaderboard
│                                                     │
│                   canonical evidence                │
│                         │                            │
│                         ▼                            │
│              trajectory_adapter.py                  │
│                         │ Native evidence            │
│                         ▼                            │
└── judge_core/ ◄── judge_adapter.py ◄── best attempt─┘
```

各层职责如下：

| 层 | 实现 | 职责 |
|---|---|---|
| Loop Core | `AsyncOrchestrator`、`CandidateRef`、`ArtifactRef`、ExpBank | Idea/Implement 生命周期、异步队列、冻结引用和证据留存，不理解 NatureBench 指标 |
| Benchmark Facility | `NatureBenchBenchmarkFacility`、`NatureBenchExperimentRunner` | 向 Agent 暴露公开题面，执行冻结代码，按 `DATA_DIR/OUTPUT_DIR` 生成 canonical artifact |
| Evaluation Facility | `NatureBenchEvaluationFacility`、`FileEvaluatorClient` | 只接受 Controller 构造的 `ArtifactRef`，发布固定 output，验签可信结果 |
| NatureBench 数值适配 | `evaluator_worker.py`、`evaluate_task.py` | 在 root 可信进程调用官方 `eval_service.run_evaluator()` 和 AutoSOTA 归一化 |
| NatureBench 轨迹适配 | `trajectory_adapter.py` | 只读转换 Agent sessions、Controller 事件、最佳冻结代码和官方提交历史 |
| NatureBench 合法性适配 | `judge_adapter.py` | 将 Famou 注册为一个官方 AgentAdapter，调用 `judge_core` 并绑定证据 manifest |
| 隔离与提交 | `fmjob/prepare_run.py`、`submit_one_click.sh` | 拆分 Agent/Trusted 文件视图、准备密钥并提交单个 Task fm-job |

这里的轨迹适配是一个可移除的 benchmark patch，不是 Loop Core 的新分支。它的只读输入是：

```text
artifacts/artifact_index.jsonl
controller/trajectory.jsonl
branches/* 与 idea_agent_workspaces/* 下的 Agent 原生 sessions
expbank/<attempt>/record.json、code/ 和 evidence/
Trusted Evaluator 的 submissions.jsonl、submission_map.jsonl
```

输出严格对应 NatureBench 官方 Judge 所消费的内容：

```text
<judge-request>/run_summary.json
<judge-request>/<task_id>/submissions.jsonl
<judge-request>/<task_id>/famou.jsonl
<judge-request>/<task_id>/workspace/
```

`JudgeAdapter` 在官方 Agent 注册表中把整套 Famou Loop 注册为 `famou`；内部使用 Claude、
Codex 或其他 Agent 只是 canonical evidence 的来源，不会把多智能体 Loop 冒充成某个单一
CLI Agent。官方 Judge 模型和凭据由 Trusted Evaluator 单独配置。`JUDGE_MODEL=gpt-*` 时应
提供 `JUDGE_OPENAI_API_KEY`/`JUDGE_API_KEY`；Anthropic 模型使用
`JUDGE_ANTHROPIC_API_KEY`/`JUDGE_API_KEY`。旧 Claude 设置中的
`ANTHROPIC_AUTH_TOKEN` 只在可信进程内兼容映射，不会复制到 Agent 运行目录。

这部分是 benchmark 级代码，新 NatureBench task 不会重复实现。Core 也不会导入某个 task
自己的 `evaluation/evaluator.py`；只有可信进程内的 NatureBench 官方 `eval_service.py`
根据 `task_dir` 加载它。

### 7.2 一个 Task 是如何绑定到上述适配的

`TASK_ID` 是唯一的 task 选择键。它在一次启动中确定四件事：

```text
TASK_ID
  │
  ├──► tasks/<TASK_ID>/problem/
  │       复制到 <run>/problem/，作为 Agent 唯一题面和数据视图
  │
  ├──► tasks/<TASK_ID>/environment/Dockerfile.v3
  │       构建单个 Task fm-job 使用的精确 task 镜像
  │
  ├──► tasks/<TASK_ID>/evaluation/ + metadata.json
  │       复制到 root-only trusted/，用于原始指标和 AutoSOTA 评分
  │
  └──► task_entrypoint.sh <run> <TASK_ID> ...
          同任务启动 Trusted Evaluator 和非特权 Agent Loop
```

运行时的完整 task 链路是：

1. `submit_one_click.sh` 用 `TASK_ID` 定位官方 task 目录，并检查 task 和镜像参数。
2. `prepare_run.py` 复制公开 `problem/`，并把 `evaluation/`、`ground_truth/` 和可信
   runtime 放入 root-only `trusted/`。
3. Task Job 把公开 `problem/` 传给 `NatureBenchBenchmarkFacility.task_view()`；Agent 自己
   阅读 `README.md` 和 `data_description.md`，不需要额外的 domain/description 配置。
4. Implement Agent 提交代码后，Core 创建带代码哈希和入口的 `CandidateRef`；Benchmark
   Facility 在隔离分支运行 `run.py`，形成不可变 `ArtifactRef`。
5. Controller 把 `ArtifactRef` 对应的产物原子发布到固定 canonical output，并向可信
   worker 发送只含受控 `attempt_id` 的评分请求。
6. 可信 worker 已由启动参数固定到同一个 `<TASK_ID>`，调用 `evaluate_task.py`；后者从
   `task_dir` 找到官方 `eval_service.py`，读取该 task 的 evaluator、GT 和 metadata。
7. 可信 worker 对每次成功或失败评分写官方格式 `submissions.jsonl`，同时记录 Candidate
   到官方 attempt 的映射；签名评分返回 Controller 并写入对应 ExpBank attempt。
8. Loop 结束后，`TrajectoryAdapter` 从 canonical evidence 生成 NatureBench-native
   Judge 目录，`JudgeAdapter` 再对最佳 attempt 调用官方 validity judge。

所以新增 task 的正常接入是“提供完整官方 task package + 精确镜像 + 设置 `TASK_ID`”，
不是新增 Adapter、`goal.yaml` 或 per-task Python 分支。只有 task 偏离统一的
`run.py + DATA_DIR + OUTPUT_DIR` 契约时，才需要扩展 Benchmark Facility 的 task contract。

### 7.3 检查任务包完整性

确认以下路径存在：

```text
data/naturebench_data/tasks/<task_id>/problem/README.md
data/naturebench_data/tasks/<task_id>/problem/data_description.md
data/naturebench_data/tasks/<task_id>/problem/data/
data/naturebench_data/tasks/<task_id>/evaluation/evaluator.py
data/naturebench_data/tasks/<task_id>/environment/Dockerfile.v3
data/naturebench_data/tasks/<task_id>/metadata.json
```

如果公开数据以 `data_archives/*.tar.gz` 保存，需要先按 NatureBench 官方流程解压为统一的
`problem/data/`，再准备 Agent 快照。

### 7.4 阅读并记录 Case 契约

接入前至少确认：

| 检查项 | 需要确认的内容 |
|---|---|
| 科学目标 | 预测、分类、生成、模拟、优化或其他任务 |
| 输入 | instance 列表、训练数据、测试输入和字段结构 |
| 主指标 | 名称、方向、是否有多个 instance |
| 输出协议 | 文件名、目录层级、列名、dtype、shape、行数 |
| 执行入口 | 是否遵守 `run.py + DATA_DIR + OUTPUT_DIR` |
| 资源 | CPU/GPU、显存、内存、数据大小和预估运行时间 |
| 依赖 | `Dockerfile.v3` 相对基础镜像新增了什么 |
| SOTA | `metadata.json` 中主指标、baseline 和最强 SOTA 是否可解析 |

这些内容由 Agent 从公开题面理解；接入层只验证协议可运行，不把 domain、description 或
具体模型方法重新配置到 Famou goal 中。

### 7.5 构建精确 Task 镜像

单任务本地构建但不推送：

```bash
TASK_ID=<task_id> \
bash famou_scientist/loop/examples/naturebench/fmjob/build_task_image.sh
```

正式发布或批量运行前，使用批量 Pipeline 自动构建并推送到 `famou-public`：

```bash
bash famou_scientist/loop/examples/naturebench/fmjob/publish_task_images.sh \
  <task_id_1> <task_id_2> <task_id_3>
```

也可以准备每行一个 case ID 的任务文件：

```bash
bash famou_scientist/loop/examples/naturebench/fmjob/publish_task_images.sh \
  --task-file task-set.txt --tag v1
```

Pipeline 只构建一次 `naturebench-base:v3`，随后逐 task 使用官方 `Dockerfile.v3` 构建、
自动 push，并在 `.famou/naturebench-images/` 写出 JSON 发布清单。`--dry-run` 只展示命令，
`--no-push` 只构建；若未预先 `docker login`，也可通过 `REGISTRY_USERNAME` 和
`REGISTRY_PASSWORD` 让 Pipeline 非交互登录。执行前会打印 Docker data root 和磁盘余量。

兼容镜像可以用于框架 smoke test，但正式可比运行应使用 case 自己的 Dockerfile 构建的
精确镜像，否则依赖版本和官方环境可能存在偏差。

### 7.6 准备隔离目录

`fmjob/prepare_run.py` 自动执行：

- 复制公开 `problem/`。
- 复制本次 Famou 源码快照，排除 `.git`、历史 `.famou`、tests 和缓存。
- 创建 workspace、结果目录、队列目录和 evaluator 文件通道。
- 生成公开数据 manifest。
- 把 evaluator/GT 放入 root-only `trusted/`，并拒绝其进入 Agent 可读快照。
- Claude 模式只暂存 `ANTHROPIC_*`、`CLAUDE_*` 和 `API_TIMEOUT_MS`，不复制 hooks 或
  其他用户配置；临时设置权限为 `0600`，Task Job 正常退出时删除。

通常不需要单独调用该脚本，`submit_one_click.sh` 会自动完成。

### 7.7 一键提交

```bash
TASK_ID=<task_id> \
IMAGE=<你的镜像仓库>/famou-public/naturebench-<task_id>:v1 \
AGENT_RUNTIME=claude \
MODEL=glm-5.2 \
MAX_WALL_TIME_HOURS=4 \
IDEA_CONCURRENCY=1 \
IMPLEMENT_CONCURRENCY=1 \
EVALUATION_CONCURRENCY=3 \
IDEA_QUEUE_CAPACITY=3 \
EVALUATION_QUEUE_CAPACITY=3 \
TIME_AWARE_IDEA_RANKING=1 \
IDEA_RANK_TRIGGER_REMAINING_SEC=3600 \
bash famou_scientist/loop/examples/naturebench/fmjob/submit_one_click.sh
```

脚本依次执行：

```text
检查 task
   │
   ▼
准备不含 evaluator/GT 的 Agent run 快照
   │
   ▼
生成 evaluator RSA 私钥和 Agent 公钥
   │
   ▼
提交一个 Task fm-job
   ├── root Evaluator 读取 trusted/GT
   └── non-root Agent/Candidate 读取公开副本
```

常用覆盖变量：

| 环境变量 | 含义 |
|---|---|
| `TASK_ID` | NatureBench case ID |
| `IMAGE` | 已经 push、Task Job 能拉取的精确 case 镜像 |
| `AGENT_RUNTIME` | `claude`、`codex` 或 `opencode` |
| `MODEL` | Idea/Implement Agent 模型；默认并显式传递 `glm-5.2`，不允许 `-` 或空值 |
| `INPUT_PRICE_PER_MILLION` | 普通输入价格；GLM-5.2 默认使用已确认的 `$1.40/M` |
| `CACHE_CREATION_PRICE_PER_MILLION` | Cache Creation 价格；GLM-5.2 暂按未命中输入价 `$1.40/M` |
| `CACHE_READ_PRICE_PER_MILLION` | Cache Read 价格；GLM-5.2 默认 `$0.26/M` |
| `OUTPUT_PRICE_PER_MILLION` | 输出价格；GLM-5.2 默认 `$4.40/M` |
| `PRICING_SOURCE` / `PRICING_EFFECTIVE_AT` | 价格来源与生效时间；随 Run 持久化供审计 |
| `MAX_WALL_TIME_HOURS` | Idea/Implement 研究阶段预算，官方可比运行应为 4 小时 |
| `EXPERIMENT_TIMEOUT_SEC` | 单条 Candidate canonical run 上限，默认 3600 秒 |
| `FINALIZATION_GRACE_SEC` | 评测排空与最终 Judge 的基础设施保险时限；默认按队列容量和各阶段 timeout 自动推导，不计入 Agent 研究预算 |
| `STARTUP_GRACE_SEC` | Evaluator 就绪等启动过程的基础设施宽限，默认 900 秒 |
| `HARD_TIMEOUT_SEC` | 整个 Task Job 保险时限；默认由研究预算、最坏串行排空时间、Judge 和启动宽限相加得到 |
| `EVALUATION_TIMEOUT_SEC` | 单次 NatureBench 数值 evaluator 最长运行时间，默认 3600 秒 |
| `JUDGE_TIMEOUT_SEC` | 最终 Validity Judge 最长运行时间，默认 3600 秒 |
| `MAX_BENCHMARK_ATTEMPTS` | 可选全局正式评分上限，默认不限制 |
| `MAX_IMPLEMENT_TURNS` | 同一 Idea Actor 的研究/refine 回合上限 |
| `MAX_RUN_ATTEMPTS` | 同一 Actor 的 canonical run 尝试上限 |
| `IDEA_CONCURRENCY` | 同时运行的 Idea Agent 数量 |
| `IMPLEMENT_CONCURRENCY` | 同时运行的 Implement Actor 数量 |
| `EVALUATION_CONCURRENCY` | Evaluation Pool 最大并发；实际并发还受 Resource Broker 余量限制 |
| `IDEA_QUEUE_CAPACITY` | IdeaSpark 高水位，达到后暂停继续生产 Idea |
| `EVALUATION_QUEUE_CAPACITY` | 等待或正在评测的 Candidate 容量 |
| `TIME_AWARE_IDEA_RANKING` | 是否在冲刺窗口启用待实现 Idea 排序；默认 `1` |
| `IDEA_RANK_TRIGGER_REMAINING_SEC` | 剩余多少秒时进入冲刺窗口；默认 3600 秒 |
| `IDEA_RANK_MODEL` | Idea Rank Judge 模型；默认与 `MODEL` 相同 |
| `IDEA_RANK_MAX_TURNS` | 单次排序 Agent 最大回合数；默认 30 |
| `IDEA_RANK_TIMEOUT_SEC` | 单次排序硬超时；默认 600 秒；冲刺窗口内最多尝试一次 |
| `AGENT_CPU` | Task Job CPU 数，同时作为 Resource Broker 总资源；默认 30 |
| `RESOURCE_TIER` | 资源档位；默认 `auto`，从官方 `cpu/gpu_low/gpu_high` task-set 自动识别 |
| `AGENT_GPU` | 可选显式 GPU 数；未设置时 CPU task 自动为 0，`gpu_low/gpu_high` task 自动为 1 |
| `AGENT_MEMORY_GIB` | Task Job 内存 GiB，同时作为 Resource Broker 总资源；默认 128 |
| `AGENT_PROCESS_MEMORY_LIMIT_GIB` | 可选的单个 CLI Agent 进程组 RSS 上限；默认 `-`，由 Harness 按控制面保留内存和 Agent 最大并发自动计算 |
| `VALIDITY_JUDGE` | 是否在 Loop 结束后运行官方 Judge；默认 `1` |
| `JUDGE_MODEL` | Judge 模型；`-` 表示使用 NatureBench 官方默认配置 |
| `RUN_ID` | 本次运行唯一标识 |
| `RUN_DIR` | 单次 Task Job 的 CFS 目录，内部按 root/non-root 权限分层 |
| `CLAUDE_SETTINGS_SOURCE` | Agent/Judge 认证配置来源；两侧按不同白名单分别暂存 |

最终提交给 fm-job 的 `AGENT_CPU/AGENT_GPU/AGENT_MEMORY_GIB` 会继续通过
`--available-cpu/--available-gpu/--available-memory-gib` 写入 Loop 的
`infra.resources`，因此 Idea、Implement 和 Idea Rank Agent 看到的是本次实际申请值，
不是固定的静态资源描述。

Harness 把任务主存的 75% 作为整个 Evaluation Pool 的可装箱容量，剩余 25% 统一保留给
Controller、Agent 和运行时；不会再按最大评测并发静态均分。默认情况下，Harness 再把
保留内存的 80% 按 Idea、Implement 和可能同时运行的 Idea Rank 最大并发均分，作为每个
CLI Agent 及其 Bash/Python 工具子进程的 RSS 上限，剩余 20% 留给 Controller、wrapper
和文件缓存。该值也可以通过 `AGENT_PROCESS_MEMORY_LIMIT_GIB` 显式覆盖。

Agent 进程组超限时只结束当前激活，记录 `agent_memory_limit_exceeded`、RSS 峰值和上限，
再把诊断送回同一 ImplementActor 修复；不会让单次探索或 Smoke Test OOM 整个 Task Pod。
完整训练应由 Agent 调用 `submit_candidate` 后交给 canonical run。Idea 必须声明一次 canonical
run 所需的 `cpu_cores`、`host_memory_gib`、`gpu.device_count` 和
`gpu.memory_gib_per_device`：

```yaml
resource_request:
  cpu_cores: 4
  host_memory_gib: 16
  gpu:
    device_count: 1
    memory_gib_per_device: 20
    exclusive_compute: false
  expected_runtime_sec: 1800
```

Implement Agent 默认继承该声明；如果 Smoke Test 证明估算不准确，可以在
`method_manifest.json` 中修正，但仍要经过任务总资源校验。Agent 只声明需求，不选择
具体设备。实际评测并发满足：

```text
running_evaluations < EVALUATION_CONCURRENCY
且 Resource Broker 能同时分配 CPU、主存和每卡显存
```

资源暂时不足的 Candidate 进入 `waiting_resources`，不算失败；租约释放后自动重试。
GPU 请求是 admission 声明，不是进程级硬上限。Broker 每次派发前同时检查声明租约余量和
`nvidia-smi memory.free` 的实时空闲显存，取二者较小值；满足声明后才分配设备，运行期间
不因 Candidate 实际显存超过声明值而强杀进程。
请求永远超过任务总资源时，确定性诊断回传原 ImplementActor 修正。每条 canonical run
在独立进程组中运行。CPU Candidate 使用 `prlimit` 限制虚拟地址空间；GPU Candidate
不能使用 `RLIMIT_AS`，因为 CUDA 显存映射也会计入该上限，因此改为按进程组 RSS 监控
实际主存。主存超限只失败当前 Candidate；CUDA 自身分配失败单独记录为
`cuda_out_of_memory`。显存并发调度只依赖派发前的动态可用量检查和声明租约装箱，不做
进程级显存硬隔离，也不持续采样 Candidate 的显存用量。

GPU 设备和总显存由任务容器内的 `nvidia-smi` 探测，并与 fm-job 申请卡数核对。每张卡
默认保留 5% 显存作为驱动和运行时余量；无 GPU、单卡和多卡使用同一资源模型。租约会把
分配结果写入 `CUDA_VISIBLE_DEVICES`；获取、释放、资源请求及派发时的实时空闲显存都保存
为审计证据。

### 7.8 启动后验收

不要只检查 fm-job 容器是 `Running`，还应确认：

1. 同一 Task Job 内的可信 Evaluator 写出
   `controller/evaluator_channel/EVALUATOR_READY.json`。
2. Supervisor 启动 `AsyncOrchestrator`，`research_state.yaml` 心跳持续更新。
3. Idea Agent 能读到公开题面和 `expbank/INDEX.md`。
4. Idea 进入 IdeaSpark，并由 Implement Agent 消费。
5. Implement Agent 显式执行 `submit_candidate`。
6. Candidate 形成不可变 CandidateRef，canonical run 形成 ArtifactRef。
7. evaluator channel 出现 request、response 和 `.sig`。
8. Controller 验签成功，ExpBank 按 NatureBench `/evaluate` 原字段记录 Agent 可见的
   `task_name`、`attempt`、`raw_scores`、`per_instance_improvement`、
   `aggregate_improvement`、`best_aggregate_improvement` 和 `best_attempt`；GT、evaluator
   stdout/stderr、私有路径和执行证据只留在 trusted evidence store。
9. 失败时 stdout/stderr、退出码和资源终止原因被保存；超时会清理完整 Candidate
   进程组，内存超限会返回 `memory_limit_exceeded`，工程错误能恢复原 Actor 修复。
10. Leaderboard 记录的是所有正式尝试中的最好值，而不是最后一次值。
11. Loop 结束后出现 `controller/judge_verdict.json`，其中 `expbank_attempt_id` 与
    Leaderboard 的最佳 attempt 一致。
12. `controller/run_summary.json` 同时包含原始 `best_score` 和 Judge 生效后的
    `effective_score`；只有明确 `is_valid=false` 才将后者置空。
13. Agent wrapper 元数据中的命令明确包含 `--model glm-5.2`，摘要的 `models` 字段与其一致。
14. 进入冲刺窗口且队列至少有两个普通 Idea 时，出现 `idea_ranking` artifact；队列项包含
    `time_aware_rank`，排序失败时出现 `idea_ranking_failure` 且原顺序不变。

### 7.9 研究截止与正常收尾

`MAX_WALL_TIME_HOURS` 只限制 Idea/Implement 的研究阶段，不限制最后的评测排空和
Validity Judge。NatureBench 官方客户端同步等待 evaluator，因此等待期间暂停计时；Famou
让 evaluator 与 Idea/Implement 异步并行，此时 Agent 仍在工作，所以研究墙钟必须连续
计算，不能因 evaluator 活跃而暂停。达到研究截止时间后，Controller 按以下确定性规则
收尾：

```text
研究墙钟到期
    │
    ├── 停止 Idea/Implement admission
    ├── 终止尚未提交到 Evaluation Queue 的在途 Agent
    ├── 将未启动或未提交的实现标记为 not_executed
    │
    ▼
排空截止时已有的完整 Evaluation Queue
（包括 queued、waiting_resources 和已经 running 的 Candidate）
    │
    ▼
提升最佳冻结 attempt
    │
    ▼
额外运行 Validity Judge
    │
    ▼
写 run_summary.json、通知 Evaluator 正常退出、进程返回 0
```

审计信息写入 `research_state.yaml.research_state.shutdown`，包括截止时待评测 item、
未执行 item、研究截止时间和评测排空完成时间。`run_summary.json.timing` 分别记录 Agent
连续墙钟预算、评测排空时间和最终收尾时间。墙钟正常耗尽不是设施失败；没有找到有效 Candidate 也通过
`outcome=no_valid_candidate` 表达，而不是让 fm-job 显示 `Failed`。

数值 evaluator 响应中的 `valid=true` 只表示官方 task evaluator 成功返回且
`aggregate_improvement` 可聚合。它不等于 Validity Judge 通过。Judge 的最终结论只读取
`final_evaluation.valid` 或 `judge.is_valid`；两者不能混用。

### 7.10 时间与资源感知的冲刺调度

该策略默认由 NatureBench 一键脚本开启，也可以通过
`--no-time-aware-idea-ranking` 关闭。正常阶段保持现有异步生产、背压和 Actor 优先级；
剩余研究时间进入配置窗口后，Controller 在 Implement 领取任务前同步调用独立
Idea Rank Judge：

```text
正常探索：Idea Agent → bounded IdeaSpark → Implement
                                  │
                         剩余时间 <= 1h
                                  ▼
                     Idea Rank Judge（同步、只排序）
                                  │
                       更新普通 Idea 的队列顺序
                                  │
                     Implement 优先消费排名最高者
```

Judge 只排名尚未实现的 `idea` / `benchmark_attempt`，不重新判断准入，也不修改 Idea。
工程 repair 和 evaluator 驱动的 refine continuation 继续使用原有更高优先级。Rubric 包含
benchmark 对齐、分数潜力、可行性、时间适配、CPU/GPU/内存适配、证据支撑、互补性、
后续 refine 价值和风险控制；各维度使用 1-5 级，但不使用固定权重求和。

进入冲刺窗口后只尝试一次排名，不因待实现 Idea 集合或新的 Evaluation 完成/失败而重复
调用模型。只剩一个 Idea 时确定性跳过 Judge；剩余时间不足 `IDEA_RANK_TIMEOUT_SEC + 5`
秒时也不再启动排名。完整输入、Judge 输出、采用的顺序和失败回退均写入 artifacts、
decision log 和 `research_state.scheduler`。

注意：2026-08-06 之前的三个历史运行没有显式传递 `--model`，实际使用了 Claude CLI
默认模型，不能作为 GLM-5.2 成本或效果记录。当前入口已经拒绝空模型；复跑时应以 wrapper
命令证据和 `run_summary.json.models` 为准。

## 8. 实际示例：UCNP 发光强度预测

本次验证 case：

```text
task_id: s43588-025-00917-3
task: Upconverting Nanoparticle Emission Intensity Prediction
domain: Materials Science / Nanoparticle Photophysics
instance: sunset_1
```

公开数据约 57 MB：

- 训练集：5,571 条 0 至 3 层壳结构记录。
- IID 测试集：287 条 0 至 3 层壳结构记录。
- OOD 测试集：206 条训练时未见的 4 层壳结构记录。

输出协议与前面跑过的多文件 JSON case 不同，要求：

```text
output/sunset_1/test_iid_pred.csv
output/sunset_1/test_ood_pred.csv
```

每份 CSV 包含：

```text
_id,target
```

其中 `_id` 必须与测试记录的 `_id.oid` 对齐，`target` 是预测的
`log10(I + 100)`。官方 evaluator 分别计算：

- `MSE_IID_x1e3`，越低越好，是主指标。
- `MSE_OOD_x1e3`，越低越好，是辅助指标。

该 case 的 `metadata.json` 中最强主指标 SOTA 为 `10.6`，因此主指标归一化为：

```text
improvement = -(MSE_IID_x1e3 - 10.6) / 10.6
```

注意：OOD 指标会保存在 `raw_scores` 中，但因为没有标记为 primary，不会进入该 case 的
`aggregate_improvement`。

该 case 的目标复跑配置为 Claude Code + `glm-5.2`、4 小时预算、Idea/Implement/Evaluation 并发
`1/1/3`、Idea/Evaluation 队列容量 `3/3`。它验证了新三设施框架能处理不同数据 schema
和 CSV 输出协议。当前运行复用了一个依赖兼容的已有镜像，适合框架验证；严格正式复跑
需要使用该 task 的 `Dockerfile.v3` 构建并 push 精确镜像。

## 9. 主要产物

```text
<run>/workspace/run.py
<run>/workspace/output/
<run>/candidates/
<run>/artifacts/
<run>/queues/ideaspark.jsonl
<run>/queues/benchmark_attempt_queue.jsonl
<run>/queues/evaluation_queue.jsonl
<run>/expbank/INDEX.md
<run>/expbank/<attempt>/SUMMARY.md
<run>/expbank/<attempt>/record.json
<run>/expbank/<attempt>/code/
<run>/expbank/<attempt>/evidence/
<run>/controller/evaluator_channel/requests/
<run>/controller/evaluator_channel/responses/
<run>/controller/trajectory.jsonl
<run>/controller/judge_verdict.json
<run>/controller/naturebench_judge/<request_id>/judge_input_manifest.json
<run>/controller/naturebench_judge/<request_id>/judge_verdict.json
<run>/controller/naturebench_judge/<request_id>/<task_id>/famou.jsonl
<run>/controller/naturebench_judge/<request_id>/<task_id>/submissions.jsonl
<run>/controller/naturebench_judge/<request_id>/<task_id>/workspace/
<run>/controller/run_summary.json
<run>/research_state.yaml
```

每次实验必须保留：冻结代码、输入契约、canonical output、stdout、stderr、原始指标、归一化
分数、evaluator 响应与签名、Actor/Idea lineage、时间戳和失败阶段。Agent 可见 run 中只放
可公开的结果视图；完整 evaluator stdout/stderr/response 由 root 可信进程写入
`<run>/trusted/raw_evaluator_artifacts/<request_id>/`。ExpBank 的摘要只用于检索，不能替代
原始证据。

## 10. 新 Case 与新 Benchmark 的区别

### 新 NatureBench Case

如果任务继续遵守 NatureBench task package 和 `run.py + DATA_DIR + OUTPUT_DIR` 协议：

- 不新增 per-case Adapter。
- 不新增 `goal.yaml`。
- 检查题面、输出协议、metadata 和资源。
- 构建精确镜像。
- 设置 `TASK_ID` 后一键提交。

### 全新的 Benchmark 系列

如果外部 benchmark 不遵守 NatureBench 协议，则需要提供：

1. Benchmark Facility 适配：如何从 CandidateRef 运行官方任务并生成 ArtifactRef。
2. Evaluation Facility 适配：如何把 ArtifactRef 提交给可信 evaluator 并返回统一结果。
3. 公开/私有资源 staging：哪些内容给 Agent，哪些只给 evaluator。
4. 环境与资源声明：镜像、入口、CPU/GPU、timeout。
5. 结果映射：官方指标、方向、有效性和 stdout/stderr/extra。

Core 不应该新增对该 benchmark 文件名、输出目录或数据环境变量的硬编码假设。

## 11. 提交 NatureBench 官方 Leaderboard

官方提交不是把整个私有 Run 目录直接压缩，而是从不可变证据中导出一个可公开、可校验
的标准目录：

```text
<submission-name>/
├── submission.yaml
├── results.csv
├── score_report.json
├── export_manifest.json
└── raw-results/
    └── <case_id>/
        ├── result.json
        ├── submissions.jsonl
        ├── judge_verdict.json       # valid/invalid case 必需
        ├── trajectory.famou.jsonl   # 非空完整轨迹
        └── workspace/               # 最佳 attempt 的文本源码，可选但默认导出
```

`results.csv` 和 `raw-results/` 必须覆盖全部 90 个官方 case。没有已评审结果的 case 不能
省略：导出器会写入 `not_run/not_applicable`，生成空 `submissions.jsonl`、最小
`result.json` 和非空占位轨迹。已有数值分数但 Judge 为 `null` 的运行也不会被伪写成
`valid` 或 `invalid`。

导出命令示例：

```bash
python -m famou_scientist.loop.examples.naturebench.export_submission \
  --runs-dir .famou/naturebench-runs \
  --output-dir .famou/naturebench-submissions/<submission-name> \
  --model "<leaderboard model name>" \
  --agent "Famou Scientist" \
  --organization "<organization or Independent>" \
  --url "https://<public model/agent/project URL>" \
  --contact "<working contact>" \
  --compute "<actual per-task CPU/GPU/memory allocation>" \
  --judge-model "claude-sonnet-4-6" \
  --deviations-from-reference "<none or exact deviations>"
```

导出器执行以下硬校验：

1. 使用 `leaderboard/case_metadata.csv` 的 90 个官方 ID 和顺序。
2. 每个 case 只选择最新的、具有有限 `best_score` 和严格布尔 Judge 结论的运行。
3. `run_summary.best_score` 必须等于官方 `submissions.jsonl` 中最大的
   `aggregate_improvement`。
4. Judge 原因在 `results.csv` 与 `judge_verdict.json` 中必须一致。
5. 轨迹必须来自 `controller/naturebench_judge/<request>/<case>/famou.jsonl`，不能用只有
   Controller 三两条事件的简化日志代替。
6. 对 result、submissions、trajectory 和 workspace 文本统一移除凭据、内网 endpoint、
   CFS 绝对路径；私有原始证据保持不变。
7. 全部 case 成功后才原子发布目标目录，半成品不会冒充正式包。

从 NatureBench 最新仓库根目录运行官方检查：

```bash
python submit-results/validate_submission.py \
  --metadata <submission-name>/submission.yaml \
  --results <submission-name>/results.csv \
  --raw-results <submission-name>/raw-results

python submit-results/compute_scores.py \
  --results <submission-name>/results.csv \
  --output <submission-name>/score_report.json
```

`submission.yaml` 中的组织、联系方式、公开 URL、实际硬件、人工干预和偏离说明属于提交者
声明，不能由导出器猜测。正式发送前还应人工复核这些字段，并确认公开轨迹中没有不应外发
的业务信息。官方维护者会重新核对 attempts、轨迹和 Judge，必要时重跑 Validity Judge。

## 12. 相关脚本

| 文件 | 用途 |
|---|---|
| `fmjob/build_task_image.sh` | 从 case 的 `Dockerfile.v3` 构建 task 镜像 |
| `fmjob/publish_task_images.sh` | 批量构建、推送 task 镜像并生成发布清单 |
| `fmjob/prepare_run.py` | 创建公开 Agent 快照和 root-only 可信目录 |
| `fmjob/submit_one_click.sh` | 创建密钥并提交一个共享资源的 Task fm-job |
| `fmjob/task_entrypoint.sh` | 在同一任务内监督可信 Evaluator 和非特权 Agent Loop |
| `integrations/naturebench/plugin.py` | 注册 NatureBench Benchmark/Evaluator 两个标准插件 |
| `integrations/naturebench/benchmark.py` | 公开 TaskView、候选执行契约和 ArtifactRef 生成 |
| `integrations/naturebench/evaluation.py` | canonical output 发布和可信 transport 结果映射 |
| `integrations/naturebench/evaluator_worker.py` | 在 root 可信进程中处理数值评分与 Judge 请求并签名响应 |
| `evaluate_task.py` | 在可信侧调用 NatureBench evaluator 和官方 SOTA 归一化逻辑 |
| `integrations/naturebench/trajectory_adapter.py` | 投影 NatureBench 官方 Judge 所需证据格式 |
| `integrations/naturebench/judge_adapter.py` | 注册 Famou transcript 并调用 NatureBench `judge_core` |
| `export_submission.py` | 从私有 Run 证据导出并脱敏官方 Leaderboard 提交目录 |
| `leaderboard/case_metadata.csv` | 官方 90-case ID 与六领域映射快照 |

`run_task.py` 和 `check_submission.py` 只用于独立验证 NatureBench 的公开运行/格式协议；
正式主路径使用 `agent run` 与单 fm-job 权限隔离，不经过 `loop/evaluation/` 的 benchmark
特例，也不依赖 `goal.yaml`。

## 13. 全部任务清单

NatureBench 的官方任务集合包含 90 个 task。下面按 task package 中
`metadata.json.domain_metadata.primary_domain` 分组，给出 task ID、任务名和一句话说明。
这个分组是任务包的机器可读分类，与论文结果图中的六个展示大类（Cellular Omics、Protein
Biology、Biomedical Modeling、Physical Modeling、Molecular Design、Relational Reasoning）
不是完全相同的聚合口径。

当前本地 NatureBench 数据快照包含 90 个 task directory，其中 87 个带有公开的
`metadata.json`，以下 3 个任务的名称和描述是根据其 evaluator、instance 和输出协议推断的，
已经单独标注，正式运行前仍应补齐其 `problem/README.md` 和 `metadata.json`。

### 13.1 Biology（60 个）

- `s41592-025-02893-y`，Skeleton Keypoint Imputation：补全动物运动骨架序列中缺失的关键点。
- `s41592-025-02662-x`，Fluorescence Microscopy Spot Detection：检测荧光显微图像中的亮点位置。
- `s41592-025-02665-8`，Temporal Segmentation of Single-Particle Diffusion Trajectories：对单粒子扩散轨迹进行时间分段并识别扩散模式。
- `s41551-024-01312-5`，Cancer Gene Identification on Biological Networks：在生物网络中识别和排序潜在癌症相关基因。
- `s41592-025-02924-8`，Clone Tree Site Labeling for Metastatic Migration History Inference：为克隆树位点标注标签，推断肿瘤转移迁移历史。
- `s41592-025-02886-x`，3D Cell Tracking in Time-Lapse Microscopy：从延时显微图像中跟踪细胞的三维运动轨迹。
- `s42256-023-00619-3`，TCR-Peptide Binding Prediction：预测 TCR 与肽段之间的结合能力。
- `s42256-025-01002-0`，Peptide-MHC-TCR Binding Prediction：联合预测肽段、MHC 和 TCR 的结合关系。
- `s41592-025-02983-x`，Cell Behavior Prediction in Multicellular Embryogenesis：根据发育数据预测多细胞胚胎中的细胞行为。
- `s42256-023-00640-6`，Drug Interaction Prediction on Biomedical Networks：利用生物医学网络预测药物之间的相互作用。
- `s42256-024-00916-5`，Multiproperty Molecular Optimization：在多个性质约束下优化分子候选。
- `s42256-025-01026-6`，Enzyme Optimum pH Prediction：预测酶发挥最佳活性的 pH 条件。
- `s43588-024-00698-1`，Genetic Perturbation Outcome Prediction：预测基因扰动后细胞或分子表型的变化。
- `s43588-025-00878-7`，Noncoding Variant Effect Prediction on Gene Expression：预测非编码变异对基因表达的影响。
- `s41587-024-02414-w`，Yeast Promoter Expression Prediction：根据启动子序列预测酵母基因表达水平。
- `s41592-024-02523-z`，Genomic Sequence Prediction：从基因组序列预测相关生物学信号或功能输出。
- `s42256-025-01016-8`，Disease-Specific Variant Effect Prediction：预测特定疾病背景下遗传变异的功能效应。
- `s42256-022-00459-7`，Peptide-HLA Class I Binding Prediction：预测肽段与 HLA-I 分子的结合能力。
- `s41592-023-01940-w`，Microbial Genome Quality Prediction：预测微生物基因组组装或序列质量。
- `s42256-023-00627-3`，Metabolomic Profile Prediction from Microbial Composition：根据微生物组成预测代谢组谱。
- `s41592-024-02580-4`，Microscopy Instance Segmentation：在显微图像中分割并区分不同实例对象。
- `s41587-025-02585-0`，Multiplexed Protein Image Decompression：从压缩的多重蛋白成像数据恢复图像或蛋白信号。
- `s41467-025-63412-3`，Lasso Peptide Property Prediction：根据序列预测套索肽的性质或活性。
- `s42256-022-00541-0`，Clinical Drug Response Prediction from Cell-Line Screens：根据细胞系筛选结果预测临床药物响应。
- `s41467-025-64512-w`，Protein-Protein Interaction Prediction：预测蛋白质对之间是否存在相互作用。
- `s41587-025-02654-4`，Protein Tertiary Structure Prediction：根据蛋白质信息预测其三维三级结构。
- `s41592-025-02776-2`，Protein Variant Effect Prediction：预测蛋白质变体对功能或表型的影响。
- `s42256-024-00795-w`，Protein Function Prediction：根据蛋白质序列或结构预测其功能类别。
- `s42256-024-00838-2`，Protein Sequence Design (Inverse Protein Folding)：根据目标结构设计满足结构约束的蛋白质序列。
- `s42256-025-01042-6`，Inverse Protein Folding：从蛋白质结构反向生成或预测对应的氨基酸序列。
- `s43588-024-00716-2`，Protein Stability Change Prediction Upon Mutations：预测突变引起的蛋白质稳定性变化。
- `s43588-024-00733-1`，Protein Essentiality Prediction：预测蛋白质或基因对细胞生存是否必需。
- `s42256-025-01019-5`，De Novo Peptide Sequencing from Tandem Mass Spectrometry：从串联质谱信号推断未知肽段序列。
- `s41592-023-02148-8`，RNA Family Sequence Generation：生成符合目标 RNA 家族特征的新序列。
- `s41551-025-01528-z`，Single-Cell Transcriptome-to-Proteome Prediction：从单细胞转录组预测对应的蛋白质表达谱。
- `s41592-022-01709-7`，Cross-Modal Single-Cell Protein Data Matching：匹配不同模态的单细胞蛋白质数据。
- `s41592-023-01955-3`，Contrastive Representation Learning for Single-Cell Treatment Response Analysis：学习单细胞处理响应的对比表示并进行响应分析。
- `s41592-023-02035-2`，Single-Cell Cross-Study Label Transfer：在不同研究或数据集之间迁移单细胞标签。
- `s41592-024-02191-z`，Cross-Species Single-Cell RNA-seq Integration and Cell Type Label Transfer：整合跨物种单细胞 RNA-seq 数据并迁移细胞类型标签。
- `s41592-025-02854-5`，Single-Cell Genomic Profile Prediction from DNA Sequence：根据 DNA 序列预测单细胞基因组或表达谱特征。
- `s41592-025-02870-5`，Cell Differentiation Trajectory Inference：从单细胞数据推断细胞分化轨迹和状态转变。
- `s42256-022-00518-z`，Single-Cell Atlas Mapping and Integration：将单细胞数据映射并整合到参考细胞图谱。
- `s42256-022-00534-z`，Single-Cell RNA-seq Cell Type Annotation：为单细胞 RNA-seq 数据进行细胞类型注释。
- `s43588-024-00689-2`，Multimodal Single-Cell RNA-seq Cell Type Clustering：融合多模态信息对单细胞进行聚类和细胞类型识别。
- `s43588-024-00765-7`，Single-Cell Phenotype Prediction：根据单细胞分子特征预测细胞表型。
- `s41467-025-63418-x`，Spatial Multi-Omics Domain Identification：从空间多组学数据识别具有不同生物状态的区域。
- `s41587-025-02688-8`，Spatial RNA Velocity Inference：从空间转录组数据推断 RNA velocity 和细胞状态变化方向。
- `s41592-023-02124-2`，Tissue Cellular Neighborhood Detection：在组织空间中检测细胞邻域和局部微环境。
- `s41592-024-02257-y`，Spatial Domain Identification in Spatially Resolved Transcriptomics：从空间转录组数据识别空间区域。
- `s41592-024-02316-4`，Spatial Domain Identification from Multi-Omics Data：利用多组学信息识别空间域。
- `s41592-025-02826-9`，Cell Marker Positivity Classification in Multiplexed Imaging：在多重成像中判断细胞标志物阳性或阴性。
- `s41592-025-02926-6`，Spatial Omics Prediction from Histology and Cross-Modal Integration：结合组织学图像和其他模态预测空间组学信号。
- `s41587-024-02428-4`，Protein-Protein Interaction Interface Residue Prediction：预测蛋白质相互作用界面的关键残基。
- `s41592-023-01878-z`，Macromolecular Particle Localization in Cryo-Electron Tomograms：在冷冻电镜断层图中定位大分子颗粒。
- `s41592-023-02032-5`，De Novo Nucleic Acid Atomic Structure Modeling from Cryo-EM Maps：从冷冻电镜图谱建模核酸原子结构。
- `s41592-024-02372-w`，Protein-DNA Binding Specificity Prediction：预测蛋白质对 DNA 序列的结合特异性。
- `s41467-025-65557-7`，Spatial Clustering of Single-Molecule Localization Point Clouds：对单分子定位点云进行空间聚类。
- `s41592-025-02820-1`，Restraint-Guided Protein Complex Structure Prediction：根据约束信息预测蛋白质复合物结构，并以 DockQ 衡量结构质量。*（名称来自 evaluator，当前快照缺少 metadata/README）*
- `s42256-024-00836-4`，RNA Classification and Secondary Structure Prediction：同时处理 RNA 家族分类和二级结构预测。*（根据 `nrc`、`archiveii600`、`ts0` evaluator instance 推断，当前快照缺少 metadata/README）*
- `s42256-024-00892-w`，Calcium-Imaging Neuron Segmentation and Trace Reconstruction：从钙成像数据恢复神经元掩膜和活动时间轨迹。*（根据 evaluator 输出协议推断，当前快照缺少 metadata/README）*

### 13.2 Chemistry（12 个）

- `s43588-025-00920-8`，Stereoselectivity Prediction in Asymmetric Catalytic Reactions：预测不对称催化反应的立体选择性。
- `s43588-024-00757-7`，Electronic Circular Dichroism Spectrum Peak Property Prediction：预测电子圆二色谱峰的位置或性质。
- `s42256-024-00956-x`，Molecular Energy and Force Prediction：根据分子结构预测能量和原子受力。
- `s42256-025-01010-0`，Transition State Structure Generation：生成化学反应的过渡态结构。
- `s42256-023-00636-2`，Targeted Molecular Generation via SMILES-Based Optimization：通过 SMILES 和目标性质约束生成分子。
- `s42256-022-00501-8`，Molecular Interactions and Properties Prediction：预测分子相互作用及相关性质。
- `s42256-023-00654-0`，Molecular Property Prediction：从分子表示预测目标分子性质。
- `s42256-023-00712-7`，Pocket-Conditioned 3D Molecular Generation：在蛋白结合口袋条件下生成三维分子。
- `s42256-024-00815-9`，Molecular Linker Design：设计连接两个分子片段的 linker 分子。
- `s42256-022-00447-x`，Molecular Property Prediction：在多个分子性质数据集上进行性质预测。
- `s42256-023-00639-z`，Molecular and Protein Property Prediction：联合预测分子和蛋白质相关性质。
- `s42256-022-00526-z`，Organic Reaction Product Prediction：根据反应物预测有机反应产物。

### 13.3 Computer Science（5 个）

- `s42256-022-00468-6`，Graph Combinatorial Optimization：在图结构上学习组合优化解。
- `s42256-022-00556-7`，Temporal Sequence Modeling with Irregular Sampling：对不规则采样的时间序列进行建模和预测。
- `s42256-023-00630-8`，Visual Abstract Reasoning on Progressive Matrices：在渐进矩阵图形任务上进行视觉抽象推理。
- `s42256-024-00833-7`，Graph and Hypergraph MaxCut Optimization：在图和超图上求解或近似 MaxCut。
- `s42256-025-01003-z`，DNA Sequence Reconstruction from Noisy Reads：从含噪 DNA 测序读段重建原始序列。

### 13.4 Materials Science（4 个）

- `s42256-023-00628-2`，Metal-Organic Framework Property Prediction：预测金属有机框架材料的结构或物性。
- `s43588-025-00842-5`，Zeolite-Molecule Binding Affinity Prediction：预测沸石与分子之间的结合亲和力。
- `s43588-025-00903-9`，Polymer Property Prediction：根据聚合物结构预测材料性质。
- `s43588-025-00917-3`，Upconverting Nanoparticle Emission Intensity Prediction：预测上转换纳米颗粒的发光强度。

### 13.5 Mathematics（1 个）

- `s43588-024-00732-2`，Geometry-Dependent PDE Solution Operator Learning：学习依赖几何形状的偏微分方程解算子。

### 13.6 Medicine（3 个）

- `s42256-023-00611-x`，Categorical Counterfactual Outcome Estimation：估计分类处理或干预下的反事实结果。
- `s41551-024-01257-9`，Pulmonary Nodule Malignancy Classification from 3D CT Scans：从三维 CT 判断肺结节良恶性。
- `s43588-025-00798-6`，COVID-19 Hospitalization Trend Forecasting：预测 COVID-19 住院趋势。

### 13.7 Physics（5 个）

- `s43588-024-00703-7`，Anomalous Diffusion Out-of-Distribution Dynamics Detection：检测异常扩散系统中的分布外动力学。
- `s43588-025-00872-z`，Ground-State Energy Prediction for Periodic Solids：预测周期性固体的基态能量。
- `s42256-022-00464-w`，Multiscale Dynamical System Forecasting：预测具有多时间尺度的动力系统演化。
- `s43588-024-00730-4`，Electronic Structure Energy Computation：计算或预测体系的电子结构能量。
- `s42256-024-00790-1`，X-ray Diffraction Data Denoising：去除 X 射线衍射数据中的噪声并恢复信号。

任务 ID 是一键运行和 task package 选择的唯一键，例如：

```bash
TASK_ID=s43588-025-00917-3 \
bash famou_scientist/loop/examples/naturebench/fmjob/submit_one_click.sh
```
