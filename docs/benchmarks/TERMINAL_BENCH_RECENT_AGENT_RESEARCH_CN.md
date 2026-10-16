# Terminal-Bench 长程 Agent 研究调研

> 调研日期：2026-08-14  
> 范围：Terminal-Bench 2.0/2.1 及其相邻的 terminal-agent、harness evolution、long-horizon execution 工作。  
> 说明：论文中的分数是作者自报结果，可能使用不同模型、Harness、任务划分、重试预算和版本；除非特别注明，不应直接与官方 leaderboard 数字比较。

## 1. 核心结论

Terminal-Bench 领域最近的高分工作已经从“更换基础模型”转向四个系统问题：

1. **Harness 是性能的一等变量。** Prompt、工具、middleware、memory、状态管理和控制流会显著改变同一个模型的结果。
2. **长程任务的关键是外部状态，而不是无限扩大上下文。** 任务状态、已验证事实、失败诊断和未完成子目标需要从原始 transcript 中抽取出来，独立于 Agent 上下文维护。
3. **Verifier 结果可以驱动跨任务优化，但不能在单个任务内伪造官方反馈。** 单任务仍应是 `instructions -> one run -> final workspace -> official verifier`；harness 演化是跨任务、跨 episode 的外层过程。
4. **真正可迁移的提升需要 regression control 和 cross-benchmark evaluation。** 只在同一批任务上迭代，很容易学到 grader、task template 或工具 schema 的捷径。

对 Famou 的直接启示不是再新增一套单任务 Runner，而是把现有 Loop 明确拆成三层：

```text
统一 Infra
    workspace、sandbox、进程、资源、队列、预算、控制、checkpoint、轨迹和 artifact

Evaluator Layer
    benchmark task adapter、公开检查、正式 verifier、安全结果归一化

Agent DAG Layer
    SotaSearchGraph：Idea -> Implement -> Evaluate -> Refine
    TerminalTaskGraph：Solve <-> SurrogateVerify <-> Repair
                      -> Agent exit -> FinalAudit（GT）
    HarnessEvolutionGraph：跨任务归因、修改 harness、回归验证、接受或回滚
```

三者通过稳定 contract 组合。Terminal-Bench 需要新增的是 Evaluator Adapter 和 Agent DAG，
不是第二套 Infra。`terminal_task` 可以作为 DAG/profile 名称存在，但不应对应独立的 workspace、
进程、资源、控制或可观测性实现。TerminalTaskGraph 也不能套用 SOTA loop 的
`Idea -> Implement -> submit_candidate -> evaluator feedback` 语义。

## 2. Benchmark 与榜单口径

### 2.1 Terminal-Bench 2.0

Terminal-Bench 原论文将 2.0 描述为 89 个困难的终端任务。每个 task 包含：

- 自然语言 instructions；
- 独立任务环境；
- 人工编写的 reference solution；
- 可执行 verifier/tests；
- Agent 运行期间可观察的终端交互和最终 workspace。

官方 2.0 榜单现在要求通过 Harbor 运行 `terminal-bench/terminal-bench-2`。论文和榜单中常见的指标是 pass@1 或任务通过率，但不同论文可能使用不同的抽样和重试设置。

### 2.2 Terminal-Bench 2.1

官方当前同时维护 2.1 榜单，提交要求通过 Harbor 使用 `terminal-bench/terminal-bench-2-1`。截至本调研日，官方页面显示的高分组合包括：

| 排名 | Agent | Model | 推理设置 | 通过率 |
|---:|---|---|---|---:|
| 1 | Claude Code | Fable 5 | xhigh | 83.8% |
| 2 | Codex | GPT-5.5 | xhigh | 83.1% |
| 3 | Terminus 2 | Fable 5 | high | 80.4% |
| 4 | Cursor CLI | Grok 4.5 | high | 79.3% |
| 5 | Claude Code | Opus 4.8 | high | 78.9% |
| 6 | Codex | GPT-5.6 Terra | max | 78.4% |
| 7 | Terminus 2 | GPT-5.5 | xhigh | 78.0% |
| 8 | mini-SWE-agent | Muse Spark 1.1 | xhigh | 76.2% |

这里排名的是 **Agent + Model + Harness 配置 + 推理预算** 的组合，而不是单独的模型。比如同一个模型由 Claude Code、Codex、Terminus 2 运行时可能产生明显不同的结果。

官方页面：<https://www.tbench.ai/leaderboard/terminal-bench/2.1>

### 2.3 比较结果时必须保留的字段

任何 Famou 实验记录至少需要同时保存：

```json
{
  "benchmark": "terminal-bench",
  "version": "2.1",
  "agent_harness": "...",
  "model": "...",
  "reasoning_effort": "...",
  "attempt_protocol": "pass@1",
  "task_split": "...",
  "verifier_source": "official",
  "score": 0.0,
  "cost": 0.0
}
```

否则，“论文达到 80%”和“榜单达到 80%”很可能不是同一个实验。

## 3. 近期高分与高价值工作

### 3.1 Harness 自动演化

#### Agentic Harness Engineering

论文：[Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses](https://arxiv.org/abs/2604.25850)

作者报告在 Terminal-Bench 2 上将 pass@1 从 69.7% 提升到 77.0%，超过其人类设计的 Codex-CLI harness 基线 71.9%。方法有三个 observability 层：

- **Component observability**：把 prompt、tool、middleware、memory 等可修改组件文件化、可版本化、可回滚；
- **Experience observability**：把大量原始 trajectory 转成分层、可检索的经验证据；
- **Decision observability**：每次 harness 修改先写出预期影响，下一轮结果再验证预测是否成立。

论文的消融结论很重要：增益主要来自工具、middleware 和长期 memory，而不是单纯改 system prompt。

**对 Famou 的启示**：harness 变更应是结构化 patch，必须绑定修改假设、证据、验证集结果和回滚信息，不能只把每次 Agent 输出存成一段总结。

#### Self-Harness

论文：[Self-Harness: Harnesses That Improve Themselves](https://arxiv.org/abs/2606.09498)

Self-Harness 将外层优化拆成：

```text
Weakness Mining -> Harness Proposal -> Proposal Validation
```

它从执行轨迹中识别模型特定的失败模式，生成尽量小的 harness 修改，再通过回归测试决定是否保留。作者在 Terminal-Bench 2.0、SWE-bench Verified 和 AppWorld 上报告九个 model-benchmark 组合均有 held-in 和 held-out 改善，最高相对提升达到 132%。

**价值**：这是最接近“让 loop 自己改进 loop”的基线，但其关键不是自由反思，而是“失败模式驱动的小修改 + regression validation”。

#### DarwinX

论文：[DarwinX: Evolving Agent Harnesses Through Natural Selection](https://arxiv.org/abs/2608.07545)

DarwinX 认为单条 harness 演化链容易路径依赖，因此维护多个 harness 个体和不同 lineage：

- 只有不破坏已有能力的变体才能进入 archive；
- 新变体必须满足 preserve-and-extend contract；
- 失败经验、教师轨迹和 Agent 自身经验使用统一的 edit interface；
- 允许不同 lineage 之间重组。

作者报告 Terminal-Bench 2.1 在匹配基础模型上提升到 83.2%，在更强模型上达到 84.7%，并报告未修改的 evolved harness 可迁移到 TerminalWorld 和 SWE-bench Verified。

**价值**：它把 SOTA loop 中的“候选搜索”迁移到了正确的对象：搜索 harness 版本，而不是在单个 terminal task 内搜索 candidate。

#### Do Agent Optimizers Compound?

论文：[Do Agent Optimizers Compound?](https://arxiv.org/abs/2607.14004)

这篇工作专门检查优化是否可以持续累积，而不是只在固定 benchmark 上优化一次。比较 GEPA、Meta Harness 和 RELAI-VCL 后，作者报告 lifelong average：

| 方法 | lifelong average |
|---|---:|
| Baseline | 58.7% |
| Meta Harness | 64.6% |
| GEPA | 66.0% |
| RELAI-VCL | 76.4% |

关键机制是 regression control：新任务上的改进不能以旧任务退化为代价。

**价值**：对于 Famou 的 outer harness loop，固定的 replay/regression set 不是可选项。

#### SEAGym

论文：[SEAGym: An Evaluation Environment for Self-Evolving LLM Agents](https://arxiv.org/abs/2606.17546)

SEAGym 将 Harbor-compatible benchmark 转成自演化评测环境，显式区分：

- train batches；
- frozen update-validation；
- held-out in-distribution test；
- out-of-distribution transfer；
- replay diagnostics；
- cost 和 snapshot records。

**价值**：它提供了评估“harness 是否真的变强”的实验协议，避免只看一条逐轮上升曲线。

#### APEX 与 AdaMAST

论文：[APEX](https://arxiv.org/abs/2606.15363)、[Fantastic Adaptive Taxonomies and How to Use Them](https://arxiv.org/abs/2607.16387)

APEX 同时演化 harness、行为原则和 workflow topology；其报告的 APEX Health Score 从 0.300 提升到 0.570。AdaMAST 则把原始失败轨迹归纳为证据支持的失败 taxonomy，按 system、role、domain 三个轴组织失败码。

**价值**：ExpBank 不应只保存“某个 idea 得分多少”，还需要保存稳定的失败类别和证据片段。

### 3.2 长程执行、状态与轨迹

#### LongHorizon-Harness

论文：[LongHorizon-Harness](https://arxiv.org/abs/2608.01964)

它提出 Manage-Execute-Audit（MEA）：

```text
Manager：维护外部 task state，选择下一个 subtask
Executor：用新 context 执行当前 subtask
Auditor：只读检查环境状态是否真的发生预期变化
```

作者报告 Qwen 3.7 Plus 在 Terminal-Bench 2.1 从 69.7% 提升到 77.2%。重点不是增加更多 prose prompt，而是让“任务状态”和“已验证事实”脱离滚动上下文。

**对 Famou 的启示**：TerminalTaskGraph 需要通过统一 Infra 持久化外部
`task_state.json`、已验证事实列表、未完成子目标和 checkpoint，而不是只依赖 Agent
自己记住进度。

#### Remember When It Matters

论文：[Remember When It Matters](https://arxiv.org/abs/2607.08716)

该方法使用独立 memory agent，持续从最近 trajectory 更新结构化 memory，并决定是否向 action agent 注入提醒。作者在 Terminal-Bench 上报告 +8.3 个百分点，在 tau2-bench 上报告 +6.8 个百分点。选择性注入优于：

- 被动暴露完整 memory bank；
- 每轮强制注入；
- 只有 advisor 没有 memory state；
- 普通 semantic retrieval。

**启示**：memory 不是“把历史全塞回 prompt”，而是一个有写入、压缩、相关性判断和注入门控的运行时组件。

#### CompactionRL

论文：[CompactionRL](https://arxiv.org/abs/2607.05378)

它将 context compaction 纳入 RL 训练，同时训练任务执行和摘要生成。作者报告：

- GLM-4.5-Air：Terminal-Bench 2.0 为 24.5%，比基线高 3.1 个百分点；
- GLM-4.7-Flash：Terminal-Bench 2.0 为 20.2%，比基线高 6.8 个百分点。

**启示**：长任务的 resume 不能只恢复 native session id，还需要恢复经过验证的 compact state。

#### Scaling Test-Time Compute for Agentic Coding

论文：[Scaling Test-Time Compute for Agentic Coding](https://arxiv.org/abs/2604.16529)

该工作把完整 rollout 压缩成包含 hypothesis、progress、failure mode 的结构化摘要，然后用于两种 test-time scaling：

- Recursive Tournament Voting：并行生成多个 rollout，再逐级比较摘要；
- Parallel-Distill-Refine：用之前 rollout 的摘要指导后续 rollout。

作者报告 Terminus 1 + Claude 4.5 Opus 在 Terminal-Bench 2.0 从 46.9% 提升到 59.1%。

**协议注意**：这类方法不是单次 `pass@1`，需要明确记录它是否使用多次独立尝试，以及最终如何从多个 workspace 选择结果。

#### Shepherd

论文：[Shepherd](https://arxiv.org/abs/2605.10913)

Shepherd 把每次模型动作、tool call 和 environment change 建模为可逆事件，支持：

- 从历史点 fork；
- 修改某个决策后重放后续执行；
- 在不重新运行完整 Docker commit 的情况下回滚；
- 让 meta-agent 直接操作执行轨迹。

作者报告 counterfactual workflow optimization 在 Terminal-Bench 2.0 上比 MetaHarness 高 12.8%，墙钟时间降低 58%。

**启示**：Famou 的 trajectory store 应从“日志文件”逐步升级成可定位的事件流和 workspace checkpoint。

### 3.3 模型训练与任务/轨迹合成

#### NexForge

论文：[NexForge](https://arxiv.org/abs/2607.14186)

NexForge 先从能力需求生成 task profile，再自动构造文件、依赖、运行配置和专家轨迹。作者报告：

- 3.6K terminal tasks 使 Qwen3.5-35B-A3B 从 22.5% 提升到 52.0%；
- 扩展到 43.2K tasks 后达到 58.4%；
- Nex-N2 系列模型在 Terminal-Bench 2.1 报告 75.3%。

这是模型训练路线，不是 runtime loop，但说明“可执行、可验证、覆盖能力缺口的 task/trajectory 数据”比单纯扩充 prompt 更重要。

#### Meta-Task

论文：[Meta-Task](https://arxiv.org/abs/2607.27929)

Meta-Task 将“生成 terminal task”本身做成 Terminal-Bench 格式任务：Agent 在真实容器中生成 task、执行 reference solution、运行 verifier，并在生成过程中修复 instruction、environment 和 verifier 的不一致。作者报告只用 3,221 条合成 trajectory，Qwen3-14B 达到 22.5%，Qwen3-32B 达到 31.8%。

**启示**：未来的 Terminal-Bench Science 适配器也应把 task package 的 instruction、环境和 verifier 作为一个可联合核验的 contract。

#### Recursive Synthesis for Long-Horizon Terminal Tasks

论文：[RST](https://arxiv.org/abs/2608.05466)

RST 从已验证 seed task 出发，扩展 reference solution，再同步改写 instruction 和 verifier，放入新 sandbox 验证，通过的 task 继续作为下一轮 seed。作者报告 15 轮生成 37,484 个 task，平均成本约 0.05 美元/task。

**启示**：如果我们以后生成科学终端任务，必须保留 seed、变更、fresh-sandbox validation 和 verifier 版本链。

#### SETA 与 CalibForge

论文：[SETA](https://arxiv.org/abs/2607.10891)、[CalibForge](https://arxiv.org/abs/2608.06352)

SETA-Synth/SETA-Evol 构造超过 4,500 个可验证 terminal environments，Qwen3-8B 通过 GRPO 在 Terminal-Bench 2.0 达到 12%，并使 DeepSeek-V4-Flash 在同一 harness 下从 40% 提升到 43%。

CalibForge 则使用多个 solver 的通过/失败差异对 task 难度做 adversarial calibration，构造 5,431 个 calibrated tasks；作者报告训练模型在 Terminal-Bench 2.0 达到 32.58% 和 47.57%，相对基础模型最高提升 24.71 个百分点。

**启示**：任务难度应该相对某个 solver pool 校准，而不是只检查“reference solution 能不能跑通”。

#### Tmax、Terminal-Lego 与 Interaction Trajectories

论文：[Tmax](https://arxiv.org/abs/2606.23321)、[Terminal-Lego](https://arxiv.org/abs/2606.03461)

Tmax 报告仅用 9B 参数模型达到 Terminal-Bench 2.0 的 27%，其数据生成结合 difficulty control、personas 和 verifier diversification，并使用 outcome-only RL。

Terminal-Lego 的结果指出：最高分 Agent 不一定是最好的 teacher。作者发现 DeepSeek-V3.2 产生的 trajectory 训练后泛化能力强于分数更高的 Claude Opus 4.6，原因是轨迹中显式展示了 inspect-act-verify 行为，而不是只展示一条顺利完成的路径。

**启示**：训练/经验库应优先保存“可迁移的检查和恢复过程”，不能只保存成功答案。

### 3.4 评测、Verifier 与泛化

#### Terminal-Bench 原论文

论文：[Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces](https://arxiv.org/abs/2601.11868)

原论文正式介绍 Terminal-Bench 2.0：89 个真实工作流风格任务，每个任务具有独立环境、人工 reference solution 和 comprehensive tests。论文早期实验显示 frontier Agent 在该 benchmark 上整体低于 65%，说明它的目标不是测试短代码生成，而是测试环境交互、依赖处理、调试和最终 artifact 完成。

#### TerminalWorld

论文：[TerminalWorld](https://arxiv.org/abs/2605.22535)

TerminalWorld 从 80,870 条真实 terminal recording 反向构造 1,530 个 task，整理出 200 个人工复核的 Verified task。八个 frontier model、六个 Agent 的最高通过率只有 62.5%，与 Terminal-Bench 分数的 Pearson correlation 只有 0.20。

**启示**：Terminal-Bench 高分不等于真实终端能力已解决，必须有跨 benchmark held-out 测试。

#### Cross-Benchmark Generalization

论文：[Cross-Benchmark Generalization in Long-Horizon Agents](https://arxiv.org/abs/2608.00181)

该工作强调：在同一 benchmark 的 holdout 上取得高分，可能只是学到了工具 schema、grader parsing 或 task template。更可信的验证方式是训练和测试 benchmark 完全分离，再观察 Terminal-Bench、TerminalWorld、SWE-bench 等之间的转移。

**启示**：Famou 的 harness evolution 需要固定 regression set、held-out set、OOD set 和 replay set，不能只看当前任务集合的平均分。

#### Permission Denied

论文：[Permission Denied](https://arxiv.org/abs/2608.02670)

该工作在 Terminal-Bench 2.1 上测试不同安全策略，包括 scoped credentials、restricted egress、read-only filesystem 和 non-root execution。作者报告最严格策略下成功率最高下降 18.3 个百分点，成本最高增加 167.3%。

**启示**：Agent 运行时的权限、网络、文件系统和 root/non-root 身份必须成为实验配置的一部分，否则分数不可复现。

#### Hardening Agent Benchmarks with Adversarial Hacker-Fixer Loops

论文：[Hardening Agent Benchmarks with Adversarial Hacker-Fixer Loops](https://arxiv.org/abs/2606.08960)

作者审计五个 terminal-agent benchmark 的 1,968 个 task，发现 323 个 task 存在 frontier model 可利用的 verifier 漏洞。其 hacker-fixer loop 让 Agent 尝试绕过 verifier，再由 fixer 修复 grader。

**启示**：官方 verifier 不是天然可信；Famou 应保存 verifier 版本、结果证据和 workspace hash，并尽量使用官方 Harness 的 verifier，而不是复制一份本地实现。

#### LLM-as-a-Verifier

论文：[LLM-as-a-Verifier](https://arxiv.org/abs/2607.05391)

这项工作把 verification 作为新的 scaling axis，通过 scoring-token logits 产生连续分数，并沿着分数粒度、重复评估和 criteria decomposition 扩展验证能力。

**启示**：LLM judge 可以作为诊断和训练信号，但在 Terminal-Bench 这类任务中不应替代官方最终 verifier。它更适合放在官方分数之后，生成非正式 failure diagnosis。

## 4. 这些工作共同说明了什么

### 4.1 高分来自组合，而不是单个 prompt

当前最有效的系统通常同时具备：

- 强基础模型；
- 经过任务适配的 CLI harness；
- 稳定的 shell/file/process 工具；
- 长程状态或 memory；
- 轨迹压缩；
- 本地可执行检查；
- 严格的 workspace 和 verifier 约束；
- 足够的 inference budget。

因此，榜单上的“Agent”比“Model”更接近真正的比较单位。

### 4.2 单任务内部与外部优化必须分离

单任务内部：

```text
INSTRUCTIONS.md
    -> Agent 观察环境
    -> 执行命令和修改 workspace
    -> 本地检查/自我恢复
    -> 退出
    -> 官方 verifier
```

外部优化：

```text
多个独立 task run
    -> 官方 verifier 结果
    -> trajectory/failure analysis
    -> 修改 harness
    -> train/validation/replay/OOD 回归
    -> 接受、回滚或保留多个 lineage
```

这里不能把一次 task run 中的本地检查误认为官方 evaluator feedback，也不能要求 Agent 调用 `submit_candidate`。

### 4.3 “经验”应当是可验证结构，而非自然语言总结

近期工作反复出现以下结构：

```json
{
  "failure_code": "dependency_state_not_verified",
  "evidence": ["...trajectory event ids..."],
  "affected_stage": "environment_setup",
  "proposed_change": "...",
  "prediction": "...",
  "validation_tasks": ["..."],
  "regression_result": "...",
  "accepted": true
}
```

这比当前 SOTA loop 中单独保存一个 best score 或 idea summary 更适合长程 terminal agent。

### 4.4 主要失败模式

从这些论文可以归纳出几类反复出现的问题：

1. **环境状态漂移**：Agent 以为依赖、服务或文件已就绪，实际没有。
2. **行为状态衰减**：关键 instructions、失败原因和未完成目标被长 transcript 淹没。
3. **验证不足**：Agent 只执行了修改，没有验证修改是否真的影响最终产物。
4. **工具误用**：工具过多、权限不匹配、命令输出不可控或 middleware 改变了模型意图。
5. **harness 过拟合**：在 benchmark 内提升，但换任务、换模型或换 verifier 后退化。
6. **技能污染**：错误经验进入 skill/memory bank 后，被后续经验继续引用和放大。
7. **Verifier hacking**：Agent 优化 grader 可见的表面行为，而不是完成真实任务。
8. **权限与成本失真**：宽松 root 权限、无限网络或重复重试导致分数不能代表真实部署能力。

## 5. 不训练时如何借鉴训练方法

我们不需要训练模型参数，但训练论文中的许多机制可以转换成跨任务的
harness/memory/skill 更新。关键是：这些更新发生在独立 task run 之间，而不是在
单个 Terminal-Bench task 内把官方 verifier 变成在线 reward。

### 5.1 训练机制到系统机制的映射

| 训练中的机制 | 不训练时的等价设计 | Famou 中的对象 |
|---|---|---|
| On-policy data | 优先分析当前 Agent+harness 真实产生的失败轨迹 | trajectory、failure store |
| SFT trajectory | 从成功/失败轨迹提炼可复用操作流程 | skill、runbook、checklist |
| RL reward | 用官方 verifier 和本地证据判断 harness patch 是否保留 | harness version |
| Curriculum learning | 先运行处于当前能力边界的任务 | task scheduler |
| Hard-negative mining | 优先保留模型或 harness 之间结果分歧的任务 | validation/replay set |
| Continual learning | 新版本必须通过旧任务 regression | regression gate |
| Context-compaction training | 维护经过验证的外部 task state | state manager、memory |
| Teacher distillation | 提炼 inspect-act-verify 过程，而不是复制最终答案 | procedural skill |
| Verifier diversification | 使用不同类型的本地检查和 OOD task | verifier/test suite |
| Multi-solver calibration | 用 Claude/Codex/Kimi/Z-Code 的分歧定位能力缺口 | task selection |

因此，最接近“参数更新”的实际操作不是改模型，而是发布一个新的
`harness_version`：它包含 prompt、tool schema、middleware、memory policy、状态管理
和恢复策略的版本化变更。

### 5.2 Post-episode On-policy Failure Mining（外层）

Self-Harness、DarwinX 和 RELAI-VCL 都支持一个共同判断：最有价值的开发反馈通常来自
当前 `model + harness_version + runtime_profile` 在**已经结束的 development episode**
中的失败，而不是泛泛地阅读其他 Agent 的成功案例。这里不是指 Agent 在同一个 task
运行中收到官方 evaluator feedback。正确的时间顺序是：

```text
development task 独立运行
    -> Agent 退出
    -> 第三方/官方兼容 verifier 最终校验
    -> Controller 归档 pass/fail、workspace 和 trajectory
    -> 外层分析失败并提出下一版 harness patch
    -> 新 harness 在新的 isolated episode 中验证
```

原 Agent session 不会因为 verifier 失败而恢复，也不会在原 workspace 上继续修改。每个
失败 episode 应尽量转成结构化记录：

```json
{
  "failure_code": "service_started_but_not_verified",
  "stage": "execution",
  "evidence": ["trajectory:event-104", "trajectory:event-117"],
  "root_cause": "trusted premature success signal",
  "recommended_check": "probe process and endpoint before proceeding",
  "affected_runtimes": ["codex", "kimi-code"],
  "validated_on": []
}
```

这里可用的失败证据按可信度包括：

- verifier 的最终 pass/fail、rubric 或公开诊断（如果 Harness 提供）；
- Agent 的 exit code、timeout 和资源终止原因；
- 最终 workspace、artifact manifest 和文件 hash；
- trajectory 中的命令错误、重复尝试、未验证假设和提前结束；
- Agent 运行期间自行执行的公开测试或环境检查。

如果第三方 verifier 只返回一个最终布尔值而不提供诊断，外层只能把 trajectory 中的
可疑模式标记为待验证假设，不能直接声称找到了根因。是否真的改进，需要在另一批
development/replay task 上通过对照实验确认。

因此，这一节描述的是**任务结束后的外层优化**，不是 TerminalTaskGraph 的运行期反馈。
当前 task 能否继续执行，必须由公开终端输出、代理 verifier 和本地检查决定；官方 verifier
结果只能影响未来的 checker、harness 或 skill 版本。

正式 held-out/leaderboard task 不应用于这种 failure mining。正式评测前必须冻结 harness；
官方 test 的结果只进入最终报告，不能反馈回来生成下一版 harness。若 benchmark 没有合法
的 development split 或可运行 verifier，则只能在其他公开任务上开发通用 harness，再对
该 benchmark 做一次冻结后的迁移评测。

不同 runtime 的失败分布不一定相同，因此可以共享 failure taxonomy，但保留
runtime-specific profile。例如 Claude Code、Codex、Kimi-Code、Z-Code 可以使用同一
状态机，却分别配置 compaction 阈值、命令重试策略、tool 输出截断方式和 memory 注入
频率。

### 5.3 提炼 Inspect-Act-Verify 过程

Terminal-Lego 的结果说明，最高分 Agent 不一定产生最好的 teacher trajectory。对后续
任务最有迁移价值的不是“最后写出了什么”，而是是否展示了：

```text
Inspect environment
    -> form hypothesis
    -> make smallest change
    -> verify actual state
    -> recover or continue
```

因此 SkillBank 不应主要保存某个 task 的答案，而应保存以下可迁移程序：

- 修改配置后如何确认实际生效；
- 启动服务后如何检查进程、端口和日志；
- 安装依赖后如何确认使用的是正确解释器和环境；
- 大规模修改前如何建立最小复现；
- 失败后如何区分代码错误、环境错误和资源错误。

每条 skill 必须带来源 trajectory、适用范围、证据、成功/失败验证记录和冲突信息。

### 5.4 Verified Task State 与 selective memory

LongHorizon-Harness、Remember When It Matters 和 CompactionRL 的共同启示是：不能把
完整历史 transcript 无限注入下一轮上下文。Controller 应维护一个外部、可持久化的
任务状态：

```json
{
  "requirements": [],
  "open_subtasks": [],
  "verified_facts": [],
  "failed_hypotheses": [],
  "changed_files": [],
  "active_processes": [],
  "next_action": null
}
```

只有通过命令输出、文件 hash、本地 test、进程状态等环境证据确认的事实，才能进入
`verified_facts`。Agent 自己说“已经完成”不能直接更新正式状态。

Memory 也不应是完整历史的被动检索，而应经过：

```text
trajectory
    -> candidate memory
    -> evidence validation
    -> deduplicate/conflict check
    -> scoped storage
    -> relevance gate
    -> selective injection
```

这可以避免错误经验进入 skill/memory bank 后，被后续运行不断引用和放大。

### 5.5 把 RL 的 reward 变成 harness regression gate

外层 harness 演化可以采用如下流程：

```text
收集失败 cluster
    -> 提出最小 harness patch
    -> development tasks 验证
    -> replay 旧任务
    -> held-out tasks 验证
    -> 检查成本、超时和 token 回归
    -> promote / reject / keep as alternate lineage
```

一个 patch 是否接受，不能只看平均通过率。至少应满足：

```text
new_pass_rate >= old_pass_rate + threshold
critical_regressions == 0
timeout_rate 不增加
median_cost 不超过预算
held_out 不发生显著退化
```

这对应 DarwinX 的 preserve-and-extend 和 RELAI-VCL 的 regression control。相比直接
修改模型权重，harness patch 更容易解释、回滚和针对不同 runtime 保留多个版本。

### 5.6 Curriculum 与 hard-negative task selection

没有训练时，curriculum 不再是训练 batch 顺序，而是决定下一批要运行和诊断的任务。
优先级最高的 task 通常是：

- 当前 Agent 反复失败但接近成功的任务；
- Claude/Codex/Kimi/Z-Code 结果不一致的任务；
- 同一模型在不同 harness 上结果不一致的任务；
- 得到部分 artifact 但最终 verifier 失败的任务；
- 新 patch 成功但旧版本成功的任务发生退化的任务。

这类任务比随机重复简单任务提供更多 harness 诊断信息，也更适合作为 regression set。

### 5.7 Counterfactual replay 与隔离尝试

Shepherd 的可逆执行思路可以先以较轻量的方式实现：

- 保存关键阶段的 workspace snapshot；
- 保存 task-state checkpoint 和 trajectory offset；
- 从失败前 checkpoint 创建 isolated fork；
- 只改变一项 harness 决策后重放；
- 比较 verifier、成本、超时和轨迹变化。

这类 replay 属于新的 isolated attempt，不能偷偷修改已经被官方 verifier 评分的 workspace。
如果最终指标是 pass@1，不能把多个 replay 中最好的结果标成 pass@1；多次尝试必须单独标记
为 pass@k 或 harness development evaluation。

### 5.8 测试集污染边界

训练论文里的 benchmark feedback 可以用于模型优化，但我们的 harness evolution 也会造成
同样的测试集过拟合。因此应在正式 leaderboard 运行前冻结：

```text
development tasks  -> 允许发现失败和修改 harness
validation tasks   -> 允许决定是否接受 patch
held-out tasks     -> 只用于最终选择
official test      -> 冻结 harness 后单次评测
```

官方 test task 的 hidden verifier 结果不能反馈给同一个 harness 版本再继续演化。否则即使
没有训练模型，也已经在做 benchmark-level test optimization。

### 5.9 运行期 Surrogate Verifier 与 RSI

最终 verifier 在 Agent 退出后才运行，因此无法帮助当前 episode 修复。要在单次长程执行
中形成有效闭环，关键不是提前调用官方 verifier，而是从公开 instructions、环境状态和
可执行接口构造一个 **Surrogate Verifier**（代理 verifier）。它不声称给出官方分数，
而是在 Agent 退出前尽量发现当前 workspace 为什么可能无法通过最终校验。

如果把 RSI 定义为 run-time recursive self-improvement，那么代理 verifier 使当前 episode
中同时存在两个递归改进对象：

```text
Solution improvement:
    实现 -> 检查失败 -> 诊断 -> 修复实现

Verifier improvement:
    检查覆盖不足 -> 生成更强检查 -> 寻找新反例
```

完整运行期闭环应是：

```text
INSTRUCTIONS.md
    -> 编译 requirements 和 acceptance criteria
    -> 生成本地验证计划
    -> Agent 执行
    -> Surrogate Verifier 只读检查
    -> 发现反例、缺失项和未经验证的假设
    -> Agent 修复
    -> 强化验证方法
    -> Final Audit
    -> Agent 退出
    -> Official Verifier
```

这不是普通的自然语言 reflection，而是一个以环境证据为中心的 falsification loop：

```text
Solve -> Falsify -> Diagnose -> Repair -> Strengthen Verifier -> Falsify Again
```

#### 5.9.1 代理 verifier 的四个层次

**第一层：确定性规格检查。**

从 instructions 中提取可追踪的 requirement，并为每项 requirement 绑定 checker 和证据：

```json
{
  "id": "req-03",
  "source_span": "The service must listen on port 8080",
  "criticality": "critical",
  "status": "verified",
  "checker": "socket_probe",
  "evidence": ["checks/socket_probe-03.json"]
}
```

确定性检查适合覆盖：

- 文件存在性、输出格式和 schema；
- CLI 参数、stdout/stderr 和退出码；
- build、lint 和公开测试；
- 服务进程、端口、endpoint 和重启行为；
- artifact 是否非空、可解析和位于正确路径；
- 权限、依赖、解释器和环境变量；
- instructions 明确规定的数量、名称和接口。

**第二层：生成式测试。**

根据公开 specification 生成 boundary case、property-based test、metamorphic test、异常
输入、restart/idempotency test、differential test 和 performance smoke test。生成的测试
必须保存来源 requirement，不能把 Agent 自己新增的假设冒充题面要求。

**第三层：只读 Auditor。**

Auditor 使用独立 context，只读取原始 instructions、requirements graph、workspace、运行
状态和 check evidence。它不能修改 workspace，目标也不是确认“看起来完成”，而是主动寻找：

- requirement 没有对应证据；
- evidence 与 requirement 不匹配；
- Agent 只验证了 happy path；
- 临时文件或错误环境造成假通过；
- 运行时状态和最终 artifact 不一致；
- Agent 提前停止或把 `unknown` 当成 `passed`。

**第四层：领域不变量。**

科学和工程任务可以增加独立于具体答案的不变量检查，例如：

- 量纲和单位一致性；
- 守恒关系；
- 数值范围、有限性和单调性；
- seed 和 reproducibility；
- baseline 对照和独立重算；
- 输出数量、shape、schema 和统计特征；
- 极限条件、对称性和已知特殊情形。

这些检查不能替代官方 metric，但可以在没有 hidden labels 的情况下提前发现大量实现错误。

#### 5.9.2 RSI 可修改和不可修改的对象

当前 episode 中允许递归更新：

- 当前计划和 subtask decomposition；
- requirements 的状态和证据；
- task-local memory；
- failed hypotheses 和 counterexamples；
- 本地测试与验证覆盖；
- 修复策略和剩余预算分配。

当前正式 task 中禁止修改：

- 官方 verifier 和 hidden tests；
- trusted control plane；
- 全局 persistent harness；
- benchmark task definition；
- 已经由 verifier 评分的 workspace。

永久的 harness、skill 和 memory 更新仍然属于 episode 结束后的 development workflow。

#### 5.9.3 防止自我确认和代理指标投机

同一个 Agent 同时写实现、写测试并判断测试充分，很容易形成自洽但错误的闭环。主要风险是：

```text
实现包含错误
    -> Agent 写出具有同一错误假设的测试
    -> 测试通过
    -> Agent 错误宣布完成
```

因此代理 verifier 至少需要以下约束：

- Executor 和 Auditor 使用独立 context；
- Auditor 默认只读，不能替 Executor 修复结果；
- checker 必须绑定 instruction 原文或明确的环境不变量；
- requirement 状态至少区分 `verified`、`failed`、`unknown`；
- `unknown` 不能计入通过率；
- check 必须保存可重放命令、输入、输出、退出码和证据 hash；
- final audit 使用与执行阶段不同的检查组合；
- 优先降低 false-pass，而不是追求代理分数看起来更高。

代理 verifier 最好输出 coverage 和 unresolved risk，而不是伪造一个官方 score：

```json
{
  "critical_verified": 7,
  "critical_failed": 0,
  "critical_unknown": 1,
  "noncritical_verified": 12,
  "verification_coverage": 0.86,
  "counterexamples": [],
  "unresolved_risks": ["req-08 has no independent evidence"],
  "official_score": null
}
```

#### 5.9.4 RSI 状态与停止条件

建议为运行期 RSI 单独保存：

```json
{
  "requirements": [],
  "checks": [],
  "verified_facts": [],
  "failed_checks": [],
  "unknown_requirements": [],
  "counterexamples": [],
  "repairs": [],
  "verification_coverage": 0.0,
  "refine_round": 0,
  "last_surrogate_report": null
}
```

Agent 可以自主结束当前 turn，但不能仅凭自然语言声明整个 Agent loop 已完成。满足以下条件时，
Controller 可以提前结束 loop：

```text
所有 critical requirement 都有独立证据
没有 high-severity failed check
没有未解释的 build/process/runtime error
代理 verifier 连续两轮没有发现新的 critical issue
剩余时间足以清理临时状态、退出 Agent、冻结 workspace 并运行 FinalAudit（GT）
```

无论代理检查是否通过，达到 `max_agent_wall_time` 后都必须结束 Agent
loop、冻结当前 workspace 并进入 FinalAudit。Refine 不设置固定轮数上限；只要仍有 Solver
时间预算且检查返回 repair_required，就继续恢复同一 session。还应为 FinalAudit 设置独立的 evaluator deadline，
不允许 Agent 占用这部分预算。

#### 5.9.5 用最终 verifier 校准未来的代理 verifier

在 development task 上，episode 结束后的最终 verifier 结果可以用于校准未来版本，但仍然
不能修复刚刚结束的 task：

```text
Proxy predicts pass + Official fails  -> false pass，最高优先级缺口
Proxy predicts fail + Official passes -> false reject，检查可能过严
Proxy and Official agree              -> 可保留的证据模式
```

校准记录需要绑定 benchmark version、task split、harness version 和 checker version。
正式 held-out/leaderboard 的结果不能用于继续校准当前参赛 harness。

#### 5.9.6 在架构中的位置

最终边界应明确为：

```text
统一 Infra / Graph Executor
    -> TerminalTaskGraph
        -> Runtime RSI / Surrogate Verifier
        -> Agent 退出并冻结 Workspace
    -> Terminal-Bench Evaluator Adapter
        -> Deferred Official Verifier

    -> HarnessEvolutionGraph（可选、仅开发阶段）
        -> 聚合多个已结束 episode
        -> 更新下一版全局 harness/skill/memory
```

因此，Terminal-Bench 内部 loop 的核心不是多次正式评分，而是运行期的
`specification -> evidence -> falsification -> repair`。Agent 退出并冻结 workspace 后，
才进入一次性的 `FinalAudit（GT/official verifier）`；它不能再回到 `Repair` 修改当前 run，
也不作为 Agent 可直接调用的节点。

#### 5.9.7 研究重点：Verifier Engineering

对 Famou 而言，最值得投入的不是仿造一个官方 score，而是构造可信的、可解释的、可重放的
代理 verifier。它应当把公开 instructions 编译成 Requirement IR，再为每项 requirement
选择检查策略：

```text
INSTRUCTIONS.md
    -> Requirement IR
    -> Checker Plan
    -> Agent 执行
    -> Evidence-backed diagnosis
    -> Repair / strengthen checker
```

Requirement IR 至少包含：

```json
{
  "id": "req-07",
  "source_span": "...",
  "criticality": "critical",
  "check_strategy": ["file_schema", "runtime_probe"],
  "status": "unknown",
  "evidence": []
}
```

Checker 的可信度优先级应为：

```text
确定性环境检查
    > property/metamorphic test
    > differential test
    > 独立 LLM Auditor
    > Agent 自我判断
```

运行期诊断不能只返回“未通过”或一个代理 score，而应携带可重放证据：

```json
{
  "requirement_id": "req-07",
  "status": "failed",
  "checker": "runtime_probe",
  "evidence": {
    "command": "curl --fail http://127.0.0.1:8080/health",
    "exit_code": 7,
    "stdout": "",
    "stderr": "connection refused"
  },
  "diagnosis": "service process is not accepting connections",
  "next_probe": "inspect process and startup logs"
}
```

代理 verifier 还应能识别检查覆盖不足，并递归增加：

- boundary inputs；
- restart/idempotency checks；
- independent recomputation；
- differential implementations；
- requirement 未覆盖部分的生成式测试；
- Auditor 主动寻找的 counterexample。

核心指标应优先关注 false-pass，而不是代理 score：

- critical requirement coverage；
- proxy false-pass rate；
- evidence reproducibility；
- diagnosis 后的 repair uplift；
- verifier 时间和 token 成本；
- Proxy/Official 一致率。

其中最危险的情况是：

```text
Proxy 认为完成 -> Official 判定失败
```

这类 false-pass 应成为下一轮 checker engineering 的最高优先级。最终系统应被理解为
**verifier-centric long-horizon agent runtime**，而不是依赖最终评分反馈的 candidate loop。

## 6. 对 Famou Loop 的具体设计建议

### 6.1 新增 TerminalTask Agent DAG，复用统一 Infra

不新增第二套单任务 Runner。应先从当前固定承载 SOTA DAG 的 `AsyncOrchestrator` 中抽取
通用 `GraphExecutor`/`AgentGraph` 扩展点，然后把现有 SOTA 流程和 Terminal-Bench 流程
注册成不同 DAG：

```text
GraphExecutor（统一 Infra）
    ├── SotaSearchGraph
    │     Idea -> Implement -> Evaluate -> Refine
    │
    └── TerminalTaskGraph
          Solve <-> SurrogateVerify <-> Repair
                    -> Agent exit -> FreezeWorkspace -> FinalAudit（GT）
```

`terminal_task` 或 `harness_task` 只作为 DAG/profile 的配置名。两种 DAG 共同复用：

- workspace、sandbox 和 Agent CLI runtime；
- ResourceBroker、并发、墙钟预算和进程组清理；
- pause/resume/stop、checkpoint 和 control bus；
- trajectory、observability、artifact store 和内容哈希；
- evaluator 的可信文件/HTTP 通道；
- run summary、证据导出和状态收口。

对应到当前代码，改造范围应控制为：

| 逻辑层 | 直接复用 | Terminal-Bench 新增/调整 |
|---|---|---|
| Infra | workspace、sandbox、Agent runtime、ResourceBroker、队列、预算、控制总线、trajectory、artifact contract、evaluator channel | 从固定 `AsyncOrchestrator` 流程抽取通用 Graph Executor 扩展点 |
| Evaluator | `BenchmarkFacility`/`EvaluationFacility` 的公开面与可信面、ArtifactRef 哈希交接、Harbor trial bridge | 具体 Harbor 0.14 backend：task container 生命周期、FMJob artifact copy-out/copy-in、官方 verifier 结果归一化 |
| Agent DAG | CLI Agent adapter、session、prompt/skill 注入、checkpoint | `TerminalTaskGraph` 及其 Solve/SurrogateVerify/Repair 节点 |

其中 Infra 的 Graph Executor 抽取是一次公共解耦，不是 Terminal-Bench 专属运行模式；完成后接入
新的 benchmark 应主要落在 Evaluator Adapter 和 Agent DAG 两层。

每一轮 Agent 执行都是一个完整 turn，而不是由 Infra 在任意时刻强制暂停：

```text
round 0:
    resume ImplementAgent(session=solver, prompt=solve)
    -> Agent 自己结束当前 turn
    -> SurrogateVerify

round 1..N:
    如果需要修正且仍有预算：
        resume ImplementAgent(session=solver, prompt=refine_report)
        -> Agent 自己结束当前 turn
        -> SurrogateVerify
```

Solve 和后续 Repair/Refine 使用同一个 native Agent session 与同一个 workspace。
循环在代理检查通过或达到 `max_agent_wall_time` 时结束；Refine 轮数不作为终止条件。
Infra 的硬 timeout/stop 只处理 Agent 不退出或外部控制等异常情况，不是正常的轮次切换机制。

TerminalTaskGraph 自己只定义以下领域状态迁移：

```text
created
  -> staged
  -> agent_turn_running (solve/refine, same session)
  -> agent_turn_exited
  -> surrogate_verifying
  -> agent_turn_running (refine, when needed and within N/time budget)
  -> agent_loop_completed
  -> workspace_frozen
  -> verifier_deferred
  -> final_audit (GT)
  -> artifact_collected
  -> completed / failed / timed_out
```

Evaluator Layer 对 Terminal-Bench 提供一个 Adapter，内部继续保持公开面和可信面分离：

```text
Public Task/Evaluator Side
    instructions、task environment、surrogate checks、公开 diagnostics

Trusted Official Evaluator Side
    只接收冻结的 workspace/artifact reference
    -> Harbor/official verifier（FinalAudit/GT）
    -> redacted normalized result
```

这种内部拆分是安全边界，不是第四套运行基础设施。FinalAudit/official verifier 节点由可信
Controller 在 Agent 退出并冻结 workspace 后触发，不能暴露给 Agent 反复调用，也不能回写当前
workspace。

最小结果结构：

```json
{
  "task_id": "...",
  "benchmark": "terminal-bench",
  "benchmark_version": "2.1",
  "agent_runtime": "claude|codex|kimi-code|z-code",
  "model": "...",
  "exit_code": 0,
  "timed_out": false,
  "workspace_manifest": "...",
  "trajectory": "...",
  "requirements": "controller/runtime_rsi/requirements.json",
  "runtime_verification": {
    "critical_failed": 0,
    "critical_unknown": 0,
    "verification_coverage": 1.0,
    "last_surrogate_report": "controller/runtime_rsi/surrogate_round_2.json"
  },
  "verifier_result": null
}
```

`runtime_verification` 只记录 specification-derived checks 和环境证据，不是官方分数。
`verifier_result` 在 Agent 运行期间应保持为空；官方 Harness 结束 verifier 后再写入正式结果。

### 6.2 外层再实现 Harness Evolution

外层 loop 可以复用现有 SOTA loop 的搜索思想，但搜索对象改为：

- system prompt；
- tool set 和 tool schema；
- middleware；
- memory policy；
- task-state manager；
- checkpoint/compaction policy；
- failure taxonomy；
- 是否启用 manager/auditor/fresh-context executor。

每次修改都需要绑定：修改假设、影响任务、官方 verifier 结果、成本变化、回归结果和 rollback reference。

### 6.3 推荐的评测分层

```text
train tasks       用于发现和修复失败
validation tasks  决定是否接受 harness patch
replay tasks      检查旧能力是否退化
held-out tasks    检查同分布泛化
OOD benchmark     检查跨 benchmark 迁移
```

只有 validation、replay、held-out 和 OOD 的结果同时满足要求，才应把 harness 版本标记为可发布。

### 6.4 Resume 语义

Terminal task 的 resume 不是新 candidate，也不是新的 official submission。它应恢复：

- 同一个 workspace；
- task state；
- checkpoint；
- native session（如果 runtime 支持）；
- 压缩后的历史上下文；
- trajectory offset；
- deadline 和剩余预算。

如果 Agent DAG 已经完成且 workspace 已冻结，后续修复应当创建新的 isolated attempt，不能偷偷修改
已经被 verifier 评分的 workspace。单个 turn 的正常退出不属于这里；只要尚未达到 N/时间限制且
workspace 未冻结，Controller 就可以 resume 同一个 ImplementAgent session 继续 refine。

## 7. 实施优先级

### 7.1 当前实施状态（2026-08-18）

第一阶段核心闭环已经落地：

- 通用领域 contract：`famou_scientist/loop/domain/graph.py`；
- 通用持久化执行器与状态：`runtime/graph_executor.py`、`storage/graph_state.py`；
- 独立 Terminal DAG：`graphs/terminal_task/`；
- 双 Agent 组合根：`harness/terminal_task.py`；
- 通用可恢复 Agent turn：`execution/agent_turn.py`；
- Harbor trial bridge：`integrations/terminal_bench_science/harbor.py`，以 Harbor canonical
  trial/artifact 路径为输入，FMJob 可通过 `execution/sandbox.py` 的 `FmJobSandbox`
  运行 Solver/VerifierAgent；
- 四份版本化 v1 prompt：`prompts/cli_agents/terminal_task/`；
- CLI 通过 `--agent-graph terminal_task` 选择该 DAG，并可分别指定 Solver/Verifier
  runtime、model、Verifier planning timeout 和最大 refine 次数。

当前执行语义已经通过自动测试固定：Solve 与 VerifierPlan 真正并发；VerifierPlan 在首轮前冻结；
solve/refine 恢复同一个 Solver native session；每轮只把脱敏后的 SurrogateReport 交给 Solver；
该报告同步到 Solver 可访问的 `.famou/surrogate/round_N.json`，Agent-facing evidence 不引用
Controller 或 Verifier 私有路径；
Agent 时间耗尽后仍冻结 workspace 并执行一次 FinalAudit；FinalAudit 结果不回流当前 run；恢复已完成
run 不会重复节点。Terminal 路径不会创建 SOTA `ResearchState` 或 ExpBank，也不会进入
`AsyncOrchestrator`。模块边界测试同时禁止通用 GraphExecutor 引用具体 DAG、TerminalGraph 引用
SOTA 领域对象、SOTA Orchestrator 反向引用 TerminalTask。

需要准确区分已完成和未完成部分：当前已用 fake Benchmark/Evaluator 跑通端到端闭环，并已实现
Harbor trial facility、不可变 artifact manifest、哈希交接、FMJob Agent sandbox 和 FinalAudit
contract。通过 `--benchmark-adapter terminal_bench_science --evaluator-adapter terminal_bench_science`
并传入 `--harbor-backend module:Class` 可以接入具体 Harbor 0.14 launcher；该 launcher 必须实现
`HarborTaskBackend`，负责 Harbor container 的 artifact copy-out/copy-in、公开检查和官方 verifier。
当前仓库还没有把 Harbor 0.14 的私有 runtime API 硬编码进 core，也尚未完成真实 Harbor task
container、官方 verifier 和 trajectory 的最小端到端 smoke。现有 SOTA 流程继续使用 `AsyncOrchestrator`，尚未机械改写成
`SotaSearchGraph`；它只在 Harness 组合根与 Terminal DAG 分流，领域状态和控制流保持独立。

### P0：抽取 DAG 扩展点并保持现有流程兼容

- 从 `AsyncOrchestrator` 抽取通用 `GraphExecutor`/`AgentGraph` contract；
- 将现有 Idea/Implement/Evaluate 流程注册为 `SotaSearchGraph`，行为保持不变；
- 让 DAG 节点复用现有 workspace、资源、控制、预算、轨迹和 artifact 能力；
- 定义 `TerminalTaskGraph` 的输入、节点输出、状态迁移和最终 `FrozenWorkspaceRef`；
- 用 contract test 证明两个 DAG 不需要各自复制 Infra。

### P1：TerminalTask Agent DAG 与长程状态管理

- `INSTRUCTIONS.md` 原样传入；
- 一个长程 native Agent session，包含 solve 和按剩余时间执行的 refine turn；
- timeout、exit code 和进程组清理复用统一 Infra；
- 外部 `task_state.json`；
- instructions-derived requirements graph；
- verified facts、open subtasks、failed hypotheses 和 counterexamples；
- 确定性 checker registry 和可重放 evidence；
- solve/surrogate-verify/repair 运行期 RSI；
- `max_agent_wall_time` 和 Agent turn 自主退出语义（旧 `max_refine_rounds` 参数仅为兼容保留，不参与终止）；
- context compaction；
- checkpoint 和 resume；
- runtime verification 与 official score 的明确隔离。

### P2：Terminal-Bench Evaluator Adapter

- task container 和 workspace 映射；
- model/runtime/deadline 映射；
- workspace/artifact 冻结、hash 和只读交接；
- 独立 FinalAudit/official verifier deadline；
- 官方 verifier 结果收集；
- 公开诊断与隐藏结果的脱敏边界；
- benchmark-native trajectory 转换；
- fake deferred verifier 测试；
- 最小官方 task 端到端验证。

### P3：外层 Harness Evolution

- train/validation/replay/OOD 切分；
- failure taxonomy 和 evidence store；
- harness patch proposal；
- regression gate；
- 多 lineage、fork、rollback；
- 成本和 token budget 记录。

## 8. 需要特别避免的误区

- 不要把 Terminal-Bench 的最终 verifier 包装成 `submit_candidate` 工具暴露给 Agent。
- 不要在 Agent 运行期间生成一个 Famou 内部“正式 score”替代官方 verifier。
- 不要把 Surrogate Verifier 的 coverage、confidence 或 audit result 标成官方通过率。
- 不要让同一个 Agent 在没有独立证据的情况下同时定义 requirement、编写实现并宣布通过。
- 不要用 `best_k_mean`、`best_score` 这类 SOTA 指标描述单次 terminal task 的结果。
- 不要把多次独立 rollout 的最好结果标成 pass@1。
- 不要只在训练任务上判断 harness 是否改进。
- 不要把完整 trajectory 无筛选地塞回下一轮 prompt。
- 不要在没有记录权限、网络、镜像、模型和 Harness 版本的情况下比较分数。
- 不要把一个高分论文的数字直接当作当前 leaderboard 的可复现结果。

## 9. 参考资料

### Benchmark 与 Harness

- [Terminal-Bench official leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.1)
- [Terminal-Bench paper](https://arxiv.org/abs/2601.11868)
- [Harbor framework](https://github.com/harbor-framework/harbor)
- [TerminalWorld](https://arxiv.org/abs/2605.22535)
- [Long-Horizon-Terminal-Bench](https://arxiv.org/abs/2607.08964)

### Harness、状态和轨迹

- [Agentic Harness Engineering](https://arxiv.org/abs/2604.25850)
- [Self-Harness](https://arxiv.org/abs/2606.09498)
- [DarwinX](https://arxiv.org/abs/2608.07545)
- [Do Agent Optimizers Compound?](https://arxiv.org/abs/2607.14004)
- [SEAGym](https://arxiv.org/abs/2606.17546)
- [APEX](https://arxiv.org/abs/2606.15363)
- [Fantastic Adaptive Taxonomies and How to Use Them](https://arxiv.org/abs/2607.16387)
- [LongHorizon-Harness](https://arxiv.org/abs/2608.01964)
- [Remember When It Matters](https://arxiv.org/abs/2607.08716)
- [CompactionRL](https://arxiv.org/abs/2607.05378)
- [Scaling Test-Time Compute for Agentic Coding](https://arxiv.org/abs/2604.16529)
- [Shepherd](https://arxiv.org/abs/2605.10913)

### 数据、训练和任务合成

- [NexForge](https://arxiv.org/abs/2607.14186)
- [Meta-Task](https://arxiv.org/abs/2607.27929)
- [Recursive Synthesis for Long-Horizon Terminal Tasks](https://arxiv.org/abs/2608.05466)
- [SETA](https://arxiv.org/abs/2607.10891)
- [CalibForge](https://arxiv.org/abs/2608.06352)
- [Tmax](https://arxiv.org/abs/2606.23321)
- [What Makes Interaction Trajectories Effective](https://arxiv.org/abs/2606.03461)
- [Qwen3-Coder-Next Technical Report](https://arxiv.org/abs/2603.00729)
- [Composer 2 Technical Report](https://arxiv.org/abs/2603.24477)

### Verifier、安全和泛化

- [Cross-Benchmark Generalization](https://arxiv.org/abs/2608.00181)
- [Permission Denied](https://arxiv.org/abs/2608.02670)
- [Hardening Agent Benchmarks with Adversarial Hacker-Fixer Loops](https://arxiv.org/abs/2606.08960)
- [LLM-as-a-Verifier](https://arxiv.org/abs/2607.05391)
- [CODESKILL](https://arxiv.org/abs/2605.25430)

## 10. 最终判断

Terminal-Bench 高分研究支持统一 Infra、Evaluator、Agent DAG 三层架构，但要求单任务执行与
跨任务演化使用不同 DAG：

```text
统一 Infra：执行、资源、状态、控制、轨迹和 artifact 能力只实现一次
TerminalTaskGraph：单任务内一次长程 Agent 执行和公开自检
Terminal-Bench Evaluator：任务结束后由官方 verifier 唯一评分
HarnessEvolutionGraph：跨任务更新 harness/memory，并执行 regression control
```

因此 Famou 不应把 Terminal-Bench 改造成另一个 SOTA candidate benchmark，也不应为它新增
一套独立 Runner。更合理的目标是：在统一 Infra 上增加严格兼容 Harbor 的 Terminal-Bench
Evaluator Adapter 和 TerminalTaskGraph，之后再按需增加 HarnessEvolutionGraph。
