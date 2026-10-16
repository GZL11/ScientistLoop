# Famou Agent、Benchmark 与 Evaluator 插件架构

> 状态：第一版接口与 NatureBench 参考插件已实现。Harbor 与 fm-job 的环境桥接不在
> 当前范围内，等接入对应 benchmark 时单独实现，不向 Core 添加 Harbor 特例。

## 1. 目标

Famou 的科研循环、Coding Agent、公开 Benchmark 和可信 Evaluator 必须能够独立替换：

```text
                         Famou Infra
┌──────────────────────────────────────────────────────────────┐
│ Research Workflow                                            │
│ Idea → IdeaSpark → Implement → Candidate → ExpBank          │
│                                                              │
│ Runtime Kernel                                               │
│ Queue / Pool / Budget / Workspace / Sandbox / Artifact       │
│ Session / Evidence / Evaluator Transport / State Recovery    │
└───────────────┬──────────────────┬──────────────────┬─────────┘
                │                  │                  │
                ▼                  ▼                  ▼
        Agent Adapter      Benchmark Adapter   Evaluator Adapter
        Claude/Codex       NatureBench         Official metric
        OpenCode/custom    Other benchmark     Hidden GT/Judge
                                                │
                                                └─ Trajectory/Judge Adapter
```

Core 只能理解稳定对象，例如 `TaskView`、`CandidateRef`、`ArtifactRef`、
`EvaluationRequest` 和 `EvaluationResult`，不能理解：

- Claude Code 或 Codex 的命令行参数。
- NatureBench 的 `run.py`、`DATA_DIR` 或 AutoSOTA。
- 某个 evaluator 的 GT 路径、指标名字或 Judge 操作。
- fm-job、Harbor 或某个 benchmark 的部署脚本。

## 2. Infra 与 Workflow 的边界

`Idea → IdeaSpark → Implement → ExpBank` 是 Famou 内置 Research Workflow，属于广义
Infra，但不写进 Runtime Kernel 的进程和存储原语。

```text
Runtime Kernel
  └── 提供队列、Actor、Session、Sandbox、Artifact、Evidence 等通用能力

Research Workflow
  └── 使用这些能力定义 Idea、Implement、反馈、修复和停止规则
```

Idea/Implement 是角色，不是某个 Coding Agent 产品。角色通过 Agent Adapter 执行；未来
可以增加不经过 IdeaSpark 的 Direct Coding Workflow，而不修改 Agent Adapter。

## 3. 插件发现

注册表实现位于：

```text
famou_scientist/loop/plugins/
├── contracts.py
├── registry.py
└── builtins.py
```

支持三种发现方式：

1. 内置名称，例如 `cli`、`naturebench`。
2. Python entry point，适合独立安装的第三方插件。
3. `module:Class` import path，适合源码目录内快速调试。

三个 entry point group 分别是：

```text
famou_scientist.agent_adapters
famou_scientist.benchmark_adapters
famou_scientist.evaluator_adapters
```

外部包可以这样注册：

```toml
[project.entry-points."famou_scientist.benchmark_adapters"]
my_benchmark = "my_package.benchmark:MyBenchmarkAdapter"

[project.entry-points."famou_scientist.evaluator_adapters"]
my_benchmark = "my_package.evaluator:MyEvaluatorAdapter"
```

## 4. Agent Adapter

Agent Adapter 把统一角色配置转换为一个可执行 Agent。当前最小接口是：

```python
class AgentAdapter(Protocol):
    name: str

    def create(self, config, *, config_dir=None):
        ...
```

配置示例：

```yaml
workers:
  idea:
    type: agent
    adapter: cli
    runtime: claude
    model: glm-5.2
  implement:
    type: agent
    adapter: cli
    runtime: codex
```

内置 `cli` Adapter 兼容 Claude Code、Codex、OpenCode 和显式命令。第三方 Adapter 返回的
实例需要遵守 `ImplementAgent` 契约，并把调用证据放入标准结果；Infra 统一保存：

- Session ID 和 resume 信息。
- 原始 stdout/stderr。
- Agent 原始 trajectory。
- 模型、Token、费用和运行时信息；上游没有提供的字段允许为空，但不能伪造。
- Agent 结构化提交事件。

Prompt 和 Idea/Implement 角色策略属于 Workflow 配置，不属于 Agent Adapter。

## 5. Benchmark Adapter

Benchmark Adapter 只拥有公开任务、候选执行契约和 Artifact 生成逻辑：

```python
class BenchmarkAdapter(Protocol):
    name: str

    def create(self, context: AdapterContext) -> BenchmarkFacility:
        ...
```

返回的 `BenchmarkFacility` 必须实现：

```text
task_view()             返回 Agent 可见题面
preflight(candidate)    不访问隐藏数据的候选检查
run(candidate)          执行冻结 Candidate 并生成 ArtifactRef
validate_artifact()     校验提交产物和哈希
run_public_evaluation() 可选公开检查
agent_view()            生成安全反馈
```

接入一个新的 benchmark 系列，需要实现：

1. 如何通过 `task_id` 定位公开任务。
2. 哪些文件可以进入 `TaskView`。
3. Candidate 的入口、参数、环境变量和资源契约。
4. 哪些运行结果构成 `ArtifactRef`。
5. 不接触隐藏 GT 的公开格式检查。

Benchmark Adapter 不能持有 evaluator client、GT 或官方隐藏评分实现。

## 6. Evaluator Adapter

Evaluator Adapter 相当于可信侧的 `reward_func` 接入，但评分代码不能进入 Agent 进程：

```python
class EvaluatorAdapter(Protocol):
    name: str

    def create(self, context, transport) -> EvaluationFacility:
        ...

    def finalize(self, context, facility, request):
        ...
```

`evaluate()` 处理一次 `ArtifactRef` 正式评分；`finalize()` 是可选的任务级收尾，例如
NatureBench Validity Judge。一个新 evaluator 需要实现：

1. 如何在可信环境中定位 evaluator、GT 和私有配置。
2. 如何把 `ArtifactRef` 交给官方评测代码。
3. 如何映射为 `EvaluationResult(metrics/stdout/stderr/extra/error)`。
4. 哪些字段可以通过 `agent_view()` 回传 Agent。
5. 是否存在任务结束后的官方合法性检查或汇总。

文件和 HTTP transport 现在提供通用操作：

```python
transport.request(operation="evaluate", attempt_id="...")
```

Core 不包含 `validity_judge` 等 benchmark 专用操作名。请求不能携带任意 Artifact 路径、
GT 路径或 evaluator 配置；这些由可信 Evaluator 启动时固定。

### 6.1 Trajectory Adapter 与 Judge Adapter

Infra 保存的是 benchmark 无关的 **canonical evidence**，包括 Agent 原生 session、
Controller 事件、Candidate、Artifact、ExpBank、正式评测响应引用和文件哈希。Infra 不把它
们伪装成某个 benchmark 的 transcript。

如果官方 Judge 需要特定轨迹格式，转换属于该 benchmark 的 Evaluator 集成：

```text
Infra canonical evidence（只读输入）
  └── Benchmark TrajectoryAdapter
        └── benchmark-native transcript / submissions / run summary
              └── Benchmark JudgeAdapter
                    └── official judge
```

- `TrajectoryAdapter` 是确定性、只读投影，不调用 LLM，也不重新解释实验结论；
- `JudgeAdapter` 组装官方输入并调用官方 Judge；
- Agent Adapter 负责启动 Agent，Trajectory Adapter 负责 benchmark 输出格式，二者不能合并；
- 不需要轨迹或后验 Judge 的 benchmark 可以不实现这两个组件；
- 这些组件放在 `integrations/<benchmark>/`，不会进入 Orchestrator 或通用存储层。

## 7. NatureBench 参考插件

NatureBench 的 benchmark 级实现是：

```text
famou_scientist/loop/integrations/naturebench/
├── plugin.py             # Benchmark/Evaluator Adapter 注册入口
├── benchmark.py          # 公开 TaskView、run.py 契约、ArtifactRef
├── evaluation.py         # canonical output 发布和可信 transport
├── evaluator_worker.py   # root 可信进程请求处理与 RSA 签名
├── trajectory_adapter.py # canonical evidence → NatureBench-native evidence
└── judge_adapter.py      # 注册 Famou transcript 并调用官方 judge_core
```

官方数值评分薄适配位于：

```text
famou_scientist/loop/examples/naturebench/evaluate_task.py
```

一次运行显式选择三个插件：

```bash
famou-scientist agent run \
  --agent-adapter cli \
  --agent-runtime claude \
  --benchmark-adapter naturebench \
  --evaluator-adapter naturebench \
  --task-id <task_id> \
  ...
```

可信 worker 还按 NatureBench 官方 schema 保存 `submissions.jsonl`，并额外保存
Candidate 到官方 attempt 的审计映射。这样 ExpBank 编号中包含工程失败时，Judge 仍能
聚焦真正产生最佳分数的官方 attempt。

首次接入 NatureBench benchmark 系列需要实现上述组件；现在已经完成。此后新增一个
NatureBench task 不需要新增 Python Adapter，只需要：

1. 完整官方 task package。
2. 使用该 task 的 `Dockerfile.v3` 构建精确镜像。
3. 设置 `TASK_ID` 和镜像后提交。

## 8. fm-job 的位置

fm-job 是 Infra 的 Deployment Backend，不属于任何 Adapter。当前 NatureBench 每个 case
只提交一个 Task Job：

```text
Task fm-job（共享 CPU/GPU/内存）
├── root Supervisor/Evaluator：加载 Evaluator Adapter 和官方私有资源
└── non-root Agent/Candidate：加载 Agent Adapter 和公开 Benchmark Adapter
```

文件权限与进程身份负责 hidden data 隔离，Resource Broker 负责 Candidate 级 CPU、主存和
GPU 显存装箱。是否采用同 Job、独立容器或远程服务属于 Deployment Backend，不改变三个
Adapter 的接口。

当前 `submit_one_click.sh` 是示例入口。后续可把通用提交能力提取为 `FmJobLauncher`，但
这不改变三个 Adapter 的接口。Harbor 在无 Docker socket/privileged 权限的 fm-job 环境
中需要单独的 Environment Backend，当前不实现，也不污染上述接口。

## 9. 接入检查清单

接入一个全新 benchmark 时应提交：

- 一个 Benchmark Adapter。
- 一个 Evaluator Adapter；没有官方评分时也要显式提供受控空实现，不能由 Agent 自评。
- task package 或 task discovery 实现。
- 环境和资源声明。
- 公开/私有 staging 规则。
- 官方 Judge 需要轨迹时，一个 benchmark-specific Trajectory/Judge Adapter。
- 至少一个端到端 fixture task。
- Artifact 哈希、evaluator 隔离、结果映射和证据留存测试。

不应修改：

- `AsyncOrchestrator` 的 Idea/Implement/Evaluation 调度逻辑。
- Agent CLI Adapter。
- ExpBank schema 的 benchmark 无关字段。
- Core 中的 benchmark 文件名、指标或输出路径假设。
