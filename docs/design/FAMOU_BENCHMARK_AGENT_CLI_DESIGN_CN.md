# Famou Benchmark Agent CLI 设计

> 状态（2026-08-05）：V1 主链路和 Agent/Bench/Evaluation 三设施边界已实现。
> 当前采用显式 `submit_candidate`、长生命周期逻辑 ImplementActor、异步
> EvaluationJob 和 Controller 托管评测。
>
> 核心决策：对于支持自定义 Agent、Claude Code、Codex CLI 或任意命令启动的
> benchmark，优先让 benchmark Harness 调用 Famou，而不是让 Famou 重新实现
> benchmark 的容器、任务协议和 evaluator。

## 1. 背景与问题

当前 Loop 的 benchmark-managed 路径采用以下控制方向：

```text
Famou Loop
    ↓
Benchmark Adapter
    ↓
实验运行器
    ↓
本地适配的 Evaluator
```

这种方式适合没有 Agent Harness 的传统数据集或评测脚本，但对于 NatureBench、
Terminal-Bench 一类已经支持 Claude Code/Codex/自定义 Agent 的 benchmark，会产生
额外的可信性问题：

1. 我们可能没有完全复现官方任务镜像和 task-specific 环境。
2. 我们可能遗漏在线评分、多次提交、best-score 跟踪等官方语义。
3. GPU、网络、代理、超时和进程回收可能与官方 Harness 不一致。
4. 官方 post-hoc judge 可能依赖 Agent trajectory，而本地 adapter 没有提供。
5. 即使调用了同一个指标函数，最终结果也不一定与官方 leaderboard 可比。

NatureBench 已经提供自定义 `AgentAdapter`：Harness 负责容器、只读任务数据、
evaluation service 和 judge；自定义 Agent 只需要提供系统提示词和容器内启动
命令。因此这里应采用控制反转。

## 2. 核心目标

把 Famou Loop 封装成一个可以被 benchmark 直接调用的 Agent CLI：

```text
Benchmark Harness
    ↓
famou-scientist agent run
    ↓
Famou 内部异步 Multi-Agent Loop
    ↓
Benchmark 提供的 Evaluator
    ↓
官方结果与轨迹
```

这条路径称为 **Harness-first / Embedded Agent Mode**。

设计目标：

- benchmark 始终拥有任务、容器、数据、环境和最终评分权；
- Famou 原样接收 benchmark 指令，不维护重复的任务描述；
- Famou 可以在一次运行内组织 Idea Agent、Implement Agent 和实验任务；
- 所有正式分数来自 benchmark 提供的 evaluator/service；
- 最佳代码和输出最终落到 benchmark 指定的正式 workspace；
- 完整保存 Agent 调用、实验、评测、决策和文件证据；
- 同一条 CLI 可以通过薄 shim 接入不同 Harness。

## 3. 不做什么

Embedded Agent Mode 第一版不负责：

- 下载 benchmark 数据；
- 构建或替代 benchmark 官方任务镜像；
- 在任务容器内再次启动 Docker；
- 读取 hidden labels、ground truth 或 evaluator 私有实现；
- 自己重新计算官方指标；
- 为完整 benchmark 增加 Master、创新性 judge 或论文 judge；
- 把 benchmark Prompt 总结成另一个可能失真的目标描述。

## 4. 职责边界

| 组件 | 职责 |
|---|---|
| Benchmark Harness | 选择任务和模型，创建容器，挂载数据，设置超时，提供 evaluator，收集最终结果 |
| Benchmark Shim | 把 Harness 上下文转换为 Famou CLI 参数和标准环境变量 |
| Famou Agent Runtime | 执行异步多智能体循环，管理分支、实验、反馈、证据和最佳方案 |
| Idea Agent | 读取原始任务和 ExpBank，产生带假设与验证方案的候选 idea，不修改代码 |
| Implement Agent | 阅读原始任务和 ExpBank，在候选分支实现、smoke test，并通过受控 `submit_candidate` 提交版本；不接触 hidden evaluator |
| Evaluation Facility | 调用 Harness 提供的正式评测接口，只返回允许暴露的结果 |
| ExpBank | 保存已实际执行的实验事实、失败记录和证据引用，供后续 Agent 检索 |
| Benchmark Judge | 在 Famou 退出后进行官方有效性、轨迹或最终产物评审 |

重要边界：Implement Agent 不给自己打分。Evaluation Facility 由 Famou Controller
调用，评分逻辑仍然位于 benchmark 的可信边界中。

Harness 原始指令可能包含 evaluator endpoint。Famou 必须原样保存原始指令作为审计
证据，但不能把 endpoint、凭据或直接请求能力传给内部 Agent。当前 Implement Agent
只被注入受控的 `submit_candidate` 命令：

```text
Implement Agent
  → 公开数据 smoke test
  → submit_candidate
  → 校验入口和相对源码路径
  → 冻结不可变代码快照并发布提交事件
  → Actor park，释放 Implement 并发槽
```

`submit_candidate` 不是 Evaluator 代理，也不返回分数。Controller 收到提交事件后创建
Candidate 和 EvaluationJob，再统一执行 canonical run、产物校验和 Evaluation Facility；
结果经审计、预算结算和字段脱敏后写入原 Actor mailbox，随后恢复同一 Session。

因此不应让子 Agent 绕过 Controller 直接请求 evaluator endpoint。未来即使需要提供更
丰富的交互式评测能力，也必须扩展 Controller 托管的 Candidate/Feedback 协议，保留
预算、审计、快照绑定和脱敏，而不是把 endpoint 暴露给 Agent。

## 5. 总体架构

```text
┌──────────────────────────────────────────────┐
│ Benchmark Harness                            │
│ Prompt / Container / Data / Model / Timeout  │
│ Evaluator Service / Final Judge              │
└──────────────────────┬───────────────────────┘
                       │ 启动命令
                       ▼
┌──────────────────────────────────────────────┐
│ Famou Agent CLI                              │
│ 1. 保存原始指令和 HarnessContext             │
│ 2. 初始化分支与证据目录                       │
│ 3. 启动 Idea / Implement / Evaluation 流水线  │
│ 4. 通过 Evaluation Facility 获取正式反馈       │
│ 5. 将最佳分支提升到正式 workspace             │
└──────────────────────┬───────────────────────┘
                       │ 最终代码、输出、轨迹
                       ▼
┌──────────────────────────────────────────────┐
│ Benchmark Harness                            │
│ 官方评分 / post-hoc judge / leaderboard      │
└──────────────────────────────────────────────┘
```

## 6. 对外 CLI 契约

### 6.1 命令

新增入口：

```bash
famou-scientist agent run \
  --workspace /workspace \
  --model "$MODEL" \
  --prompt "$SYSTEM_PROMPT" \
  --config /etc/famou/benchmark-agent.yaml \
  --time-limit-seconds 14400
```

支持三种互斥的指令输入方式：

```bash
# 参数
famou-scientist agent run --prompt "..."

# 文件
famou-scientist agent run --prompt-file /task/instruction.md

# 标准输入
cat /task/instruction.md | famou-scientist agent run
```

### 6.2 建议参数

| 参数 | 含义 |
|---|---|
| `--workspace` | benchmark 提供的正式可写工作目录，默认当前目录 |
| `--prompt` | Harness 生成的原始完整任务指令 |
| `--prompt-file` | 原始任务指令文件；与 `--prompt`、stdin 互斥 |
| `--model` | Harness 显式指定的系统默认模型；CLI Agent 模式不可缺省或使用 `-` |
| `--config` | 只描述 Famou Agent/Infra 的运行配置，不描述 benchmark |
| `--time-limit-seconds` | Harness 总时限；Famou 必须提前留出收尾时间 |
| `--trace-path` | 结构化 trajectory 输出位置 |
| `--evaluator` | `auto`、`online`、`command` 或 `deferred` |

参数优先级：

```text
CLI 显式参数 > Harness 标准环境变量 > Agent 配置默认值
```

### 6.3 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 已产生可提交的最终 workspace；预算耗尽但有最佳产物也属于成功 |
| `2` | 参数、配置或 HarnessContext 无效 |
| `3` | workspace 被另一个 Famou 进程占用 |
| `4` | 没有产生满足基本提交契约的产物 |
| `130` | 收到 SIGINT/SIGTERM，已完成受控清理 |

## 7. HarnessContext

CLI 启动后先构造统一上下文：

```python
@dataclass
class HarnessContext:
    instruction: str
    workspace: Path
    data_dir: Path | None
    output_dir: Path
    model: str
    deadline_at: float | None
    task_id: str | None
    batch_id: str | None
    evaluator_kind: str
    evaluator_endpoint: str | None
    evaluator_output_dir: str | None
```

允许读取的通用环境变量：

```text
DATA_DIR
OUTPUT_DIR
EVAL_SERVICE_URL
FAMOU_TASK_ID
FAMOU_BATCH_ID
FAMOU_EVALUATOR_KIND
FAMOU_EVALUATOR_OUTPUT_DIR
FAMOU_TIME_LIMIT_SECONDS
```

Benchmark Shim 负责把原生 Harness 字段映射到这些变量。核心 Runtime 不解析
NatureBench、Terminal-Bench 的内部配置文件。

## 8. Agent 配置

配置文件只描述 Famou 自身：

```yaml
agent:
  runtime: codex
  model: explicit-model-name   # 也可由必填且非空的 --model 显式注入
  max_turns_per_attempt: 80
  timeout_sec_per_attempt: 3600

infra:
  pipeline: async
  concurrency:
    ideas: 1
    implementations: 2
    experiments: 2

loop:
  max_attempts: 6
  finish_grace_seconds: 120
  promotion_policy: best_official_score
```

URL、API key、登录状态不能写在配置中，由环境、CLI profile、Secret Manager 或
Harness 的认证挂载提供。

在公平评测模式中，Harness 传入的模型必须覆盖所有内部 LLM 节点。第一版不允许
Idea Agent、Implement Agent 使用不同模型，避免把多模型系统伪装成单模型结果。

## 9. 原始任务指令

Harness Prompt 是最高优先级任务来源，必须原样保存：

```text
/workspace/.famou/task/instruction.md
/workspace/.famou/task/instruction.sha256
```

Famou 不创建 `domain`、`description` 或二次摘要作为替代指令。Controller 从原始
指令生成 role envelope 时必须保留任务、数据和输出要求，只能把 evaluator 的直接
调用方式替换为受控工具说明。

每个 Idea Agent 收到：

1. 原始任务内容与 Idea Agent 角色边界；
2. 当前最佳分支的公开摘要；
3. 从 ExpBank 检索出的相关成功、失败和退化实验；
4. 剩余时间、idea 数量和 evaluator 调用预算。

每个 Implement Agent 收到：

1. 原始任务内容与 Controller 角色边界；
2. 当前 benchmark 公开文件和 README；
3. 当前候选分支与允许暴露的历史实验结果；
4. workspace、输出目录和提交契约；
5. 剩余时间和尝试预算。

如果需要提取运行入口或输出约定，提取结果只能作为辅助 `TaskContract`，不能覆盖
原始指令。

## 10. 内部循环

```text
原始任务 + 公开 workspace
            ↓
   检索 ExpBank 历史经验
            ↓
┌────────────────────────────┐
│ Idea Agent Pool            │
│ 产生假设、改动与验证方案     │
└─────────────┬──────────────┘
              ↓
          IdeaSpark
              ↓
┌────────────────────────────┐
│ Implement Agent Pool       │
│ 创建 branch-1 / branch-2   │
└─────────────┬──────────────┘
              ↓
┌────────────────────────────┐
│ Evaluation Pool            │
│ run.py → 产物检查 → 正式评分 │
└─────────────┬──────────────┘
              ↓
       写入 ExpBank 实验事实
              ↓
        更新最佳候选
          ↙       ↘
  触发下一轮 idea   提升并结束
```

三个持久化对象的边界必须明确：

- `IdeaSpark`：等待 Implement Agent 消费的 idea 队列，不保存为已验证经验；
- branch workspace：某个 idea 的隔离代码实现和运行产物；
- `ExpBank`：完成实现或实验后的不可变事实记录，正式指标只能来自 evaluator。

实现失败、实验崩溃和超时也写入 ExpBank，但标明失败阶段且不包含伪造指标。完整日志、
代码和大文件进入 Artifact Store，ExpBank 只保存结构化摘要及证据引用。

单个 idea/候选的状态保持简单：

```text
generated → queued → implementing → experimenting → evaluated → recorded
                                  ↘ failed
evaluated → promoted | superseded | retry
```

Idea Agent 和 Implement Agent 是不同的 Agent 角色。Evaluator 是可信工具，不是
Agent。完整 benchmark 不经过 Master、Idea novelty gate、AnalyzeSpark 或论文候选
判定；V1 也不额外设置 Result Analyzer，下一轮 Idea Agent 直接读取 ExpBank 分析结果。

## 11. 三设施契约

### 11.1 已实现接口

```python
class AgentFacility(Protocol):
    def generate_ideas(...): ...
    def implement(...): ...

class BenchmarkFacility(Protocol):
    def task_view(self) -> TaskView: ...
    def preflight(self, candidate: CandidateRef, *, context=None) -> dict: ...
    def run(self, candidate: CandidateRef, *, context=None) -> RunResult: ...
    def validate_artifact(self, artifact: ArtifactRef) -> dict: ...
    def run_public_evaluation(self, artifact: ArtifactRef) -> dict: ...

class EvaluationFacility(Protocol):
    def evaluate(self, request: EvaluationRequest) -> EvaluationResult: ...
```

实现位置：

```text
famou_scientist/loop/facilities/
├── contracts.py     # CandidateRef / ArtifactRef / RunResult / EvaluationRequest
├── agent.py         # AgentFacility 与 Agent Worker 的装配边界
├── benchmark.py     # BenchmarkFacility 的通用命令实现
└── evaluation.py    # EvaluationFacility 的通用命令实现
```

`ArtifactRef` 不是任意路径字符串。它包含产物类型、存储路径、生产者和确定性哈希；
Evaluation Facility 在评分前重新验证哈希。`submission_bundle`、`workspace_snapshot`、
`trajectory`、`source_bundle` 都可以作为 `kind`，但一次 `EvaluationRequest` 只选择其中
一个作为该 attempt 的正式提交。

`EvaluationResult` 至少包含：

```json
{
  "valid": true,
  "metrics": {"aggregate_improvement": 0.123},
  "stdout": "...",
  "stderr": "...",
  "extra": {},
  "evidence_ref": "..."
}
```

### 11.2 三种评分能力

| 类型 | 场景 | Loop 行为 |
|---|---|---|
| `online` | NatureBench evaluation service | 每个有效候选可正式评分并迭代 |
| `command` | Harness 暴露可信评测命令 | Controller 运行命令并解析结果 |
| `deferred` | 只在 Agent 退出后统一评分 | Loop 不声称获得正式分数，只使用公开检查改进 |

`deferred` 模式非常重要。不是所有 Terminal 类 benchmark 都允许 Agent 在运行中
查看正式 verifier 结果；此时 Famou 不能伪造一个内部分数代替官方结果。

### 11.3 新 benchmark 接入步骤

一个新 benchmark 原则上只新增 `loop/integrations/<bench>/` 或 Harness shim：

1. 提供公开 `TaskView`，完成公开 problem/data 的 staging；
2. 实现 `BenchmarkFacility`，把该 benchmark 的入口、环境变量、产物位置和公开检查封装在集成层；
3. 实现 `EvaluationFacility`，只在可信环境读取 hidden data 或调用官方 service；
4. CLI/Harness 构造两个 Facility 后传给 `AsyncOrchestrator`；
5. 补充最小闭环测试：Candidate 执行、Artifact 哈希、正式评分、结果脱敏和最终提升。

不应修改 Agent、Actor、Orchestrator、队列或 ExpBank。通用 Core 不假设 `run.py`、
`DATA_DIR`、`OUTPUT_DIR` 或 submission 路径；这些约定属于具体 `BenchmarkFacility`。

当前标准插件和 NatureBench 参考实现对应：

- `loop/plugins/`：三类 Adapter 契约、注册表和第三方 entry point；
- `integrations/naturebench/benchmark.py`：NatureBench 的 `run.py` 契约与 Artifact 生成；
- `integrations/naturebench/evaluation.py`：可信 transport、canonical output 与结果映射；
- `integrations/naturebench/plugin.py`：两个 Facility 的装配和可选最终评测；
- `harness/runtime.py`：只负责装配插件、启动统一调度器和发布最终结果，不实现 benchmark 特例。

完整插件开发接口见
[`FAMOU_ADAPTER_PLUGIN_ARCHITECTURE_CN.md`](./FAMOU_ADAPTER_PLUGIN_ARCHITECTURE_CN.md)。

### 11.4 可信边界

- Implement Agent 不读取 evaluator 代码或 hidden data；
- Controller 只调用 Harness 暴露的 endpoint/command；
- evaluator 原始结果完整写证据，向内部 Agent 只暴露允许公开的字段；
- 原始 response、stdout、stderr 和完整 extra 必须写入 Agent 不可见的 trusted
  evidence store；Agent 可见的 file channel 和 artifacts 只能包含脱敏结果；
- 每次 evaluator 调用记录输入产物哈希、时间、结果和调用序号；
- 正式分数绝不由 LLM judge 自行生成。

## 12. Workspace 与分支提升

建议布局：

```text
/workspace/
├── output/                     # benchmark 要求的正式输出目录
├── run.py                      # 最终提升后的方法入口，按任务契约决定
└── .famou/
    ├── task/
    ├── state/
    ├── branches/
    │   ├── branch-1/worktree/
    │   └── branch-2/worktree/
    ├── experiments/
    ├── queues/
    │   ├── benchmark_attempt_queue.jsonl
    │   └── evaluation_queue.jsonl
    ├── expbank/
    │   ├── INDEX.md
    │   ├── 0001/
    │   │   ├── SUMMARY.md
    │   │   ├── record.json
    │   │   ├── code/
    │   │   └── evidence/
    │   └── 0002/
    ├── artifacts/
    ├── evaluator_calls.jsonl
    └── trajectory.jsonl
```

候选分支不能直接互相覆盖。评测前，Controller 把候选输出同步到 evaluator 允许的
canonical output 目录；评测完成后记录产物哈希。

结束时执行一次受控提升：

1. 停止接收新任务；
2. 等待或取消在途 Agent/实验；
3. 验证最佳分支仍然存在且产物哈希一致；
4. 将最佳代码和输出原子同步到 `/workspace`；
5. 生成 `final_result.json`；
6. 保留 `.famou` 证据目录供 Harness judge 读取。

不能只把最佳结果留在 `.famou/branches`，否则 benchmark 最终快照看不到正式方案。

## 13. 异步与并发

内部采用三个有界池，单个 EvaluationJob 原子完成运行和评分：

```text
Idea Agent Pool ──→ IdeaSpark ──→ Implement Agent Pool
                                      ↓
                              Evaluation Pool
                              run.py → evaluator
                                      ↓
                                   ExpBank
```

- `ideas` 控制同时运行的 Idea Agent 数量和 IdeaSpark 水位；
- `implementations` 控制同时运行的编码 Agent 数量；
- `evaluations` 控制同时运行的 EvaluationJob 数量；
- 每个 EvaluationJob 内部先运行代码，再调用 evaluator，不拆分成两个池；
- 实现下一候选可以与当前候选实验重叠；
- 达到 deadline grace period 后停止 admission，只做收尾和最佳分支提升。

时间边界必须区分：研究墙钟只约束 Idea/Implement admission；每个 Candidate 仍有独立的
`execution_limits.canonical_timeout_sec`。canonical run 超时不等于 Idea 失败，Controller
会把 `stage=canonical_run`、`error_code=canonical_timeout`、单次上限、命令、Candidate
路径以及 stdout/stderr 尾部写入 ExpBank 和原 Implement Actor mailbox。Actor 在修复预算
内恢复同一 Session，缩短内部算法预算后重新提交；只有修复预算耗尽才归档为
`engineering_failed`。Idea 声明的 `expected_runtime_sec` 超过 canonical 上限时，Runner
直接返回 `canonical_runtime_budget_exceeded`，不再白跑一次必然超时的任务。

研究截止后的排空阶段只消费截止前已进入 Evaluation Queue 的 Candidate。调度器每分钟在
`research_state.shutdown.evaluation_drain_progress` 记录截止总数、已完成、失败、资源等待、
运行中和 inflight 数量；排空结束后再写 `evaluation_drain_completed`。资源等待状态的重复
事件按 30 秒节流，但每轮仍会重新尝试资源装箱。

资源上限需要考虑两层乘积：

```text
总并发 ≈ Harness max_workers × Famou implementations/experiments
```

第一版应使用保守默认值 `1/1/1`，由 benchmark run 显式提高。

## 14. 模型与成本公平性

Harness 的 `--model` 是整个 Famou Agent 系统的默认评测模型，不只是 Implement 节点模型。

第一版规则：

- 默认所有内部 LLM 调用使用同一个 Harness model；
- `--idea-model`、`--implement-model`、`--idea-rank-model` 只在 benchmark 明确允许
  role-specific model 时覆盖；每个实际启用角色仍必须解析到显式模型；
- 每次调用记录 runtime、model、输入/输出 token、耗时和失败次数；
- 并发 Agent 调用全部计入总成本；
- 如果 Harness 有 token/call budget，Famou 必须在 admission 前检查剩余预算；
- 未能获得 usage 时必须明确记录 `usage_unknown`，不能写成 0；
- profile 可以提供 URL/key，但不能静默替换 Harness 指定的 model；空值和旧占位符 `-`
  必须在启动前报错。

当前 NatureBench 一键入口将三个角色都显式设为 `glm-5.2`，并在 wrapper 命令证据和最终
摘要中记录解析后的角色模型。

## 15. Trajectory 与证据

Infra 统一保存 canonical evidence，但不强制所有 benchmark 共用一个 transcript 文件。
Controller 事件的标准 JSONL 记录可以包含：

```json
{
  "event_id": "evt_...",
  "timestamp": 0,
  "type": "idea|agent_call|experiment|evaluation|expbank|decision|promotion",
  "branch_id": "branch-1",
  "model": "...",
  "usage": {},
  "artifact_refs": [],
  "payload": {}
}
```

必须记录：

- 原始指令哈希和 HarnessContext；
- Agent 启动参数、模型、stdout/stderr 和返回码；
- 文件修改清单与哈希；
- 实验命令、环境摘要、时长和产物；
- evaluator 请求、脱敏响应和证据引用；
- 分支重试、淘汰、比较和提升原因；
- 超时、信号、取消和最终收尾状态。

Agent 原生 session、Controller 事件、Candidate、Artifact、ExpBank 和 evaluator evidence
共同构成完整证据。Benchmark 如果需要特定 transcript，应在
`integrations/<benchmark>/trajectory_adapter.py` 中做确定性投影；Core 不导入该适配器，
也不理解 benchmark-native schema。

## 16. NatureBench 薄适配

NatureBench 有两种正交接入形态。官方 Harness-first 模式下，Famou 是一个负责启动命令和
上下文映射的 `AgentAdapter`：

```python
class FamouAgentAdapter(AgentAdapter):
    name = "famou"

    def system_prompt(self, ctx):
        # 复用 NatureBench 官方 Prompt，其中已经包含任务与评测协议。
        return ClaudeAgent(
            model_name=ctx.model,
            mode=ctx.mode,
        ).build_system_prompt({
            "task_name": ctx.task_name,
            "batch_name": ctx.batch_name,
            "eval_service_url": ctx.eval_service_url,
            "eval_output_dir": ctx.eval_output_dir,
            "time_limit_minutes": ctx.time_limit_minutes,
        })

    def build_command(self, ctx):
        return [
            "famou-scientist", "agent", "run",
            "--workspace", "/workspace",
            "--model", ctx.model,
            "--prompt", ctx.system_prompt,
            "--time-limit-seconds", str(ctx.time_limit_minutes * 60),
            "--evaluator", "online",
        ]
```

`extra_env()` 还需要传递：

```text
FAMOU_TASK_ID
FAMOU_BATCH_ID
FAMOU_EVALUATOR_OUTPUT_DIR
```

当前 fm-job Facility-first 模式不改 NatureBench 源码。可信收尾时，外部
`NatureBenchTrajectoryAdapter` 把 canonical evidence 投影为：

```text
<task_out_dir>/famou.jsonl
<task_out_dir>/submissions.jsonl
<task_out_dir>/workspace/
<task_out_dir>/../run_summary.json
```

随后 `NatureBenchJudgeAdapter` 在官方注册表中把 Famou 注册为一个 Agent，并令
`transcript_path()` 返回 `<task_out_dir>/famou.jsonl`。Agent Adapter 与
Trajectory Adapter 是两个独立接口：前者启动 Agent，后者只转换已留存证据。

Famou CLI 必须预装在 NatureBench 镜像内。正式方式优先构建继承
`naturebench-base:v3` 的派生镜像；开发阶段可以使用只读代码挂载。

## 17. Terminal-Bench 类 Harness

Terminal-Bench/Harbor 的具体 Agent 注册和 trajectory 协议应在实现前按当前版本
核验，但适配原则保持一致：

1. Harness 继续创建任务容器和执行 verifier；
2. shim 只把任务 Prompt、workspace、model 和 deadline 传给 Famou CLI；
3. 如果运行期没有官方 evaluator，使用 `deferred` provider；
4. Famou 退出后由 Harness verifier 给出唯一正式分数；
5. 轨迹转换由 shim 完成，不在核心 Runtime 中加入 Terminal-Bench 特例。

因此不是“零适配”，而是把适配范围从重写 benchmark 缩小到命令和轨迹协议。

## 18. 两种接入形态

```text
Harness-first：Benchmark Harness → Famou Agent CLI → 插件化 Loop
Facility-first：Famou Agent CLI → Benchmark/Evaluator Adapter → 插件化 Loop
```

选择规则：

- benchmark 已提供容器、任务协议和 Agent Harness：使用 Harness-first，官方 Harness 保持任务与评分控制权；
- benchmark 只有公开任务包和 evaluator：使用 Facility-first，在 `integrations/<bench>/` 实现两个插件；
- 官方 leaderboard 提交：优先使用官方 Harness 产生的结果；
- 两种形态都通过同一组 `BenchmarkFacility`、`EvaluationFacility` 和 `AgentAdapter` 契约，不能在 Core 中增加 benchmark 特例。

## 19. 建议模块结构

```text
famou_scientist/loop/
├── facilities/
│   ├── contracts.py           # 跨设施值对象和 Artifact 哈希
│   ├── agent.py               # Agent Facility
│   ├── benchmark.py           # Bench Facility
│   └── evaluation.py          # Evaluation Facility
├── harness/
│   ├── __init__.py
│   ├── cli.py                 # Agent CLI 与 HarnessContext 解析
│   ├── runtime.py             # Harness 两类 Facility、收尾和提升
│   ├── evaluator.py           # 可信 evaluator client
│   └── trajectory.py          # 标准 JSONL 轨迹
└── integrations/
    ├── naturebench/
    │   ├── plugin.py           # NatureBench 两个标准插件
    │   ├── benchmark.py        # 公开任务与候选执行
    │   ├── evaluation.py       # 可信评分设施
    │   ├── evaluator_worker.py # 可信请求、官方提交历史和签名
    │   ├── trajectory_adapter.py # canonical → NatureBench-native evidence
    │   └── judge_adapter.py    # 官方 post-hoc Judge
    └── terminal_bench/         # 接入时新增对应插件目录
        └── plugin.py
```

已有组件可以复用：

- `AgentWorkspace` 与 branch 隔离；
- `CommandImplementAgent` 与 Codex/Claude/OpenCode CLI wrapper；
- `AsyncOrchestrator` 的有界生产者消费者思路，但不直接继承该类；
- `ArtifactStore`、`ExperienceStore` 的持久化能力和 evidence chain；
- evaluator 脱敏视图和 stdout/stderr 证据保存。

需要替换或旁路：

- benchmark goal 文件、`ResearchState` 和 MasterBridge；
- Harness-first 模式下的 Docker ExperimentRunner；
- 本地重写的官方 evaluator；
- benchmark task/domain/metric 的重复配置。

## 20. 实施状态与后续阶段

### Phase 1：Agent CLI 骨架（已完成）

- 实现 `famou-scientist agent run`；
- 支持 prompt 参数、文件和 stdin；
- 构造并持久化 HarnessContext；
- 实现 workspace lock、deadline 和信号清理；
- 输出最小 trajectory 和 final result。

### Phase 2：Embedded Loop（已完成）

- 实现 Idea Agent、IdeaSpark 和 ExpBank；
- 复用 AgentWorkspace 和 Implement Agent；
- 在当前容器环境直接运行实验；
- 支持异步 idea/实现/实验流水线；
- 实现最佳分支原子提升。

### Phase 3：Evaluation Facility（基础接口、文件通道和 HTTP client 已完成）

- 实现 online HTTP provider；
- 实现 command provider；
- 实现 deferred provider；
- 统一 evaluator evidence 和 Agent 安全视图。

### Phase 4：NatureBench（已完成）

- 使用任务自己的 `environment/Dockerfile.v3` 构建任务镜像；
- 用 fm-job 启动一个共享资源的 Task Job，内部以 root Evaluator 和非特权 Agent 分权；
- Famou 公开源码、problem、Agent 产物和 root-only trusted 资源通过单次 CFS run 目录分层；
- 用一个 CPU case 端到端验证；
- 验证签名评测响应、best score、trajectory 和完整证据。
- 按官方 schema 保存成功/失败 `submissions.jsonl`，并保存 Candidate 到官方 attempt 映射；
- 使用独立 Trajectory/Judge Adapter 调用官方 `judge_core`。

### Phase 5：Terminal-Bench

- 核验当前版本的自定义 Agent/command 协议；
- 实现薄 shim 和 deferred verifier 流程；
- 验证超时、退出码、workspace 最终状态和轨迹采集。

### Phase 6：更多 benchmark 插件

- 按 benchmark 自身能力选择 Harness-first 或 Facility-first；
- 每个 benchmark 只在自己的 `integrations/<bench>/` 和 `examples/<bench>/` 增加适配；
- 报告明确标记结果来自官方 Harness 还是可信 Evaluator Adapter。

## 21. 第一版验收标准

NatureBench 单 case 至少满足：

1. 使用官方任务 Dockerfile、任务 evaluator 和 AutoSOTA 评分实现；
2. 通过 `famou-scientist agent run` 启动，不把 benchmark 改写成 Famou goal；
3. 公开 problem 是真实副本且逐文件哈希可核验，未被二次目标替换；
4. 所有内部 Agent 使用 Harness 指定模型；
5. 至少完成一次 idea 生成、实现、实验和可信 evaluator 调用；
6. evaluator 分数来自官方实现，非特权 Agent 进程不可读取 hidden data；
7. 最佳代码和输出位于 canonical workspace；
8. 正式响应由 root-only 私钥签名，Famou trajectory 可完整读取；
9. 超时后没有遗留 Agent/实验子进程；
10. `.famou` 中存在完整可回溯证据链，ExpBank 记录与 evaluator 证据一致；
11. Judge 的 SCORE_ATTEMPT 使用官方 evaluator attempt，而不是直接使用 ExpBank 编号；
12. benchmark-native 轨迹转换只存在于 NatureBench 集成层。

Terminal-Bench 类任务至少满足：

1. Harness 通过自定义 Agent 或 command 启动 Famou；
2. Famou 不绕过官方 verifier；
3. deferred 模式不伪造运行期正式分数；
4. 最终 workspace、退出码和 trajectory 能被 Harness 正常收集。

## 22. 最终决策摘要

1. Famou Loop 应成为 Claude Code/Codex 类的 benchmark-facing Agent CLI。
2. Harness-compatible benchmark 采用控制反转，官方 Harness 保持唯一评测权威。
3. Benchmark Shim 只转换启动命令、环境和轨迹，不重写任务或 evaluator。
4. 原始 Prompt 是唯一任务来源；模型由 Harness 注入并覆盖内部节点。
5. online、command、deferred evaluator 必须显式区分。
6. Idea Agent 与 Implement Agent 分工，异步多智能体调用和资源必须完整计量。
7. 最佳分支必须提升到正式 workspace，证据留在 `.famou`。
8. 新 benchmark 不需要修改 Agent、Controller、Orchestrator 或 ExpBank Core。

## 23. 本地调研依据

本设计中的 NatureBench 接入判断基于当前本地代码库，而不是根据接口名称推测：

- `/path/to/workspace/opensource/NatureBench/docs/custom-agents.md`：
  自定义 Agent 的注册、启动命令、环境变量和 trajectory 接口说明；
- `/path/to/workspace/opensource/NatureBench/agent/adapter.py`：
  `AgentAdapter` 抽象及现有 Claude Code/Codex 类适配器实现；
- `/path/to/workspace/opensource/NatureBench/solve.py`：
  官方 Harness 的任务调度、容器运行、评测服务和最终结果收集入口。

正式实现 NatureBench shim 时，应再次按锁定的 NatureBench commit 核验这些协议，
并在 Famou 集成测试中记录该 commit，避免上游接口变化导致结果不可复现。

多 Agent 基础设施参考了本地 CORAL 当前实现：

- `/path/to/workspace/opensource/CORAL/docs/coral-technical-architecture-zh.md`：
  manager 控制面、共享黑板、worktree 和 agent runtime 的整体关系；
- `/path/to/workspace/opensource/CORAL/coral/agent/manager.py`：
  并行 Agent 生命周期、监听、打断、恢复和退出清理；
- `/path/to/workspace/opensource/CORAL/coral/workspace/worktree.py`：
  分支隔离、公共状态映射和私有评测边界；
- `/path/to/workspace/opensource/CORAL/coral/hub/attempts.py`：
  已评测 attempt 的不可变事实记录和 leaderboard 视图。

Famou 复用这些基础设施原则，但不照搬 CORAL 的“单个长期 Coding Agent 同时产生
想法、实现并主动调用 eval”流程。Famou 使用明确的 Idea Agent、IdeaSpark、
Implement Agent、受控 Evaluator 和 ExpBank 链路。
