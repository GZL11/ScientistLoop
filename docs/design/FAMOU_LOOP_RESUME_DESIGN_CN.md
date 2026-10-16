# Famou Loop 任务级 Resume 技术设计

> 状态：已实现并通过 Loop/Harness 回归测试。
>
> 本文描述 Famou Loop 的任务级恢复机制。这里的 resume 不是只恢复某一个
> CLI Agent session，而是重新打开同一个 `run_dir` 中尚未完成的整个科研任务图。

## 1. 目标

Resume 的目标是在进程中断、研究墙钟截止或调度器重启后，继续消费任务中仍然有效的工作，保持已有科研上下文和审计证据不变。

恢复后应满足：

- 已经完成的 attempt 不重复执行；
- 队列中仍有 Idea 时继续派发 ImplementAgent；
- ImplementActor 收到 evaluator feedback 后，可以继续 `refine`、`fuse`、`switch`，或消费新的 Idea；
- Evaluation Pool 继续处理尚未完成的 candidate；
- Actor 的 worktree、mailbox、CLI session 和 lineage 保持连续；
- ExpBank、排行榜、evaluator budget、artifact 和 trajectory 保持累积，不重新初始化；
- 恢复行为可审计、可重复调用，并且同一任务不会被两个调度器同时消费。

## 2. Resume 边界

`run_dir` 是一个任务的持久化根目录。它同时保存状态、队列、候选、Actor、实验记录和控制面，例如：

```text
<run_dir>/
  research_state.yaml
  queues/
  actors/
  candidates/
  branches/
  expbank/
  artifacts/
  controller/
  control/
  workspace/
```

## 3. 持久化对象

### 3.1 ResearchState

`research_state.yaml` 保存任务级调度快照，包括：

- 任务状态：`running`、`paused`、`stopped`、`completed`、`failed`；
- 当前阶段和 heartbeat；
- 墙钟终止原因；
- 队列摘要；
- evaluator budget；
- leaderboard 最佳候选指针；
- branch 状态；
- recovery 和 resume audit 事件。

Resume 会将任务切回 `running`，设置新的 `active_run_started_at`，并清除上一次 wall-time drain 的 `shutdown` 快照。原始 `created_at`、预算累计值和历史审计不会清除。

### 3.2 队列

所有队列使用基于文件的 JSONL event log 加 item snapshot，当前状态以 `queues/*_items/*.json` 为准。

恢复时有两类处理：

1. `running` / `leased`：调度器进程异常退出后，由启动恢复逻辑改回 `queued`，并记录 `recover` 事件。
2. `not_executed`：只有明确由 `research_wall_time_budget_exhausted` 截止产生的条目，才会在显式任务 resume 时改回 `queued`，并记录 `resume` 事件。
3. `cancelled`：MasterAgent / 控制面 stop 产生的终态。未启动、正在 Implement 或正在 Evaluation 的工作都取消并进入该状态，普通 resume 不会复活。取消同时传播到 Queue item、Candidate manifest、ImplementActor state 和 ResearchState branch 视图，避免调度已经终止但状态页仍显示 `running`。

MasterAgent / 控制面主动 stop 取消的未完成条目不会被自动复活。

这是任务级取消，不是只取消当前一个 Agent 调用：

- Ideaspark、benchmark attempt、Evaluation Pool、AnalyzeSpark 中的 active item 都进入 `cancelled`；
- 正在运行的 ImplementAgent、canonical runner 和文件 evaluator 通过 `research_stop_requested.json` 终止本地进程；
- HTTP evaluator 客户端停止等待并丢弃晚到响应。若还要求远端 evaluator 服务本身停止计算，服务端必须另外实现 cancel endpoint 或 request cancellation 协议；客户端无法单方面保证远端进程退出。
- Actor 的 session、mailbox、worktree 和 Candidate artifact 仍保留作审计，但 Actor/Candidate 状态进入 `cancelled`，不能被普通 resume 重新调度。

### 3.3 IdeaSpark 与 ImplementActor

开放科研模式使用 `ideaspark` 队列；benchmark-managed 模式的 Idea 直接进入 `benchmark_attempt_queue`。两者最终都由 ImplementActor 消费。

每个长生命周期 Actor 保存：

- 稳定 `actor_id`、`lineage_id`、`branch_id`；
- 当前 base idea 和 revision；
- `worktree`；
- CLI runtime、session id 和 session state path；
- session resume count；
- evaluator feedback mailbox；
- pending candidate；
- refine/fuse/switch 决策和多维预算。

Evaluator 返回 `evaluated` 或工程失败反馈后，Actor 会进入 `refine_ready` 或 `repair_ready`。恢复调度会重新把 Actor continuation 放入实现队列，由原 Actor 继续使用原 session/worktree。

### 3.4 Evaluation Pool

Evaluation Queue 的 candidate 是冻结后的不可变提交。Implement 完成并通过 preflight 后，candidate 进入 Evaluation Pool。

恢复会继续消费以下状态：

- `queued`；
- `waiting_resources`；
- 进程中断遗留的 `running`；
- 墙钟截止时被标记为 `not_executed` 的 candidate。

每个 EvaluationJob 仍按固定顺序执行：

```text
canonical runner
  -> artifact validation
  -> public evaluation
  -> trusted official evaluator
  -> redacted feedback to ImplementActor mailbox
```

恢复不会重新评测已经是 `finished` 或明确失败终态的 item，除非业务逻辑另外产生新的 retry/repair continuation。

## 4. 运行流程

### 4.1 启动时恢复

调度器进入 workspace 后先取得 `control/orchestrator.lock`，然后执行：

```text
acquire run lock
  -> reopen resumable task state
  -> requeue deadline-cancelled work
  -> recover running/leased queue items
  -> restore Actor readiness and session metadata
  -> start Idea / Implement / Evaluation pools
  -> consume durable queues until admission or terminal condition
```

同一 `run_dir` 同时只能有一个调度器。若目录被其他调度器占用，新的启动直接失败，不会并行消费同一 candidate。

### 4.2 研究墙钟截止

墙钟截止时：

1. 停止新的 Idea 和 Implement admission；
2. 使用 deadline control file 通知尚未提交 candidate 的 Agent 退出；
3. 未进入 Evaluation Queue 的实现项标记为 `not_executed`；
4. 已进入 Evaluation Queue 的 candidate 继续 drain；
5. 所有截止时的 Evaluation 完成后，任务进入 `stopped`，原因是 `wall_time_budget_exhausted`。

这不是删除任务。它是一个可显式恢复的任务边界。

### 4.3 显式 Resume

执行 `loop resume` 后：

1. 清除 pause/deadline control 阻断；用户 stop 产生的取消边界不清除；
2. 仅重新排队墙钟截止产生的 `not_executed` 项；
3. 恢复 `running` / `leased` 的中断条目；
4. 保留已完成的 queue item、ExpBank record、candidate artifact 和最佳分数；
5. 设置新的 active wall-clock slice；
6. 重新打开 Idea、Implement、Evaluation admission；
7. 继续运行，直到新的预算截止、用户控制或工作流自然完成。

### 4.4 终态规则

| 状态 | 是否自动继续 | 说明 |
|---|---:|---|
| `paused` | 否 | 收到 resume 后继续 |
| `stopped + wall_time_budget_exhausted` | 否 | 显式 resume 后继续 |
| `stopped + stopped_by_user` | 否 | MasterAgent / 控制面明确停止；未完成工作已取消，不能原地复活 |
| `completed` 且没有 active work | 否 | 任务已经完成 |
| `completed` 但仍有 active durable work | 可恢复 | 按状态和队列不一致处理 |
| `failed` | 否 | 需要诊断设施故障或创建新 Loop |

## 5. Session Resume 与任务 Resume 的关系

两者是不同层次：

```text
任务 Resume
  -> 恢复 queue / actor / candidate / evaluator pool
       -> ImplementActor 被重新唤醒
            -> CLI wrapper 恢复原 Claude/Codex/OpenCode session
```

任务级 resume 决定“哪些工作还要继续”；CLI session resume 决定“同一个 Agent 如何保留上下文继续对话”。前者不能只靠后者实现。

CLI wrapper 会保存 session state，例如：

```text
actors/<actor_id>/state.json
logs/<runtime>_<role>_session.json
```

恢复时复用 runtime 对应的 session id：

- Claude：使用 `--resume <session_id>`；
- Codex：使用对应 thread/session resume 参数；
- OpenCode：使用稳定 worktree 和 continuation 机制。

如果底层 CLI session 不可用，任务级状态和证据仍然保留；ImplementActor 可以在同一 lineage/worktree 中重新激活，由 wrapper 记录 session 恢复失败或新 session 事实。

## 6. 如何使用

### 6.1 普通 Loop

首次运行：

```bash
famou-scientist loop run \
  --goal-file goals/<goal>.yaml \
  --root .famou/loop \
  --max-ticks -1
```

任务中断后，使用完全相同的 `--root` 和 goal 文件再次执行同一命令即可。不要加 `--fresh`，也不要指定新输出目录：

```bash
famou-scientist loop run \
  --goal-file goals/<goal>.yaml \
  --root .famou/loop \
  --max-ticks -1
```

暂停/墙钟截止后，也可以先提交显式 resume：

```bash
famou-scientist loop resume \
  --goal-id <goal_id> \
  --root .famou/loop
```

然后再次启动原来的 `loop run`。

查看状态：

```bash
famou-scientist loop status \
  --goal-id <goal_id> \
  --root .famou/loop \
  --json
```

### 6.2 Benchmark Harness

Harness 的 resume 入口是再次执行相同的 `agent run`，并复用原 `--run-dir`：

```bash
famou-scientist agent run \
  --task-id <task_id> \
  --run-dir <run_dir> \
  --problem-dir <run_dir>/problem \
  --workspace-dir <run_dir>/workspace \
  --evaluator-channel <run_dir>/controller/evaluator_channel \
  --evaluator-public-key <run_dir>/controller/evaluator_channel/public_key.pem \
  --agent-runtime <runtime> \
  --model <model> \
  --benchmark-adapter <benchmark> \
  --evaluator-adapter <evaluator>
```

Harness 首次运行才初始化 `research_state.yaml`；已有状态时直接复用持久化队列、Actor、ExpBank 和 workspace。外部 trusted evaluator 也必须使用同一任务的 evaluator channel 和 workspace，不能切换到新目录后声称是 resume。

### 6.3 tfbind8 实际 case

之前的真实运行目录是：

```text
.famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519
```

该目录的已知结果：

```text
status: stopped
termination_reason: wall_time_budget_exhausted
attempts_completed: 35
attempts_not_executed: 1
best_attempt_id: 0016
best_score: 0.9755947589874268
```

继续运行时保持原 `RUN_DIR`：

```bash
famou_scientist agent run \
  --task-id tfbind8 \
  --run-dir .famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519 \
  --problem-dir .famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519/problem \
  --workspace-dir .famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519/workspace \
  --evaluator-channel .famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519/controller/evaluator_channel \
  --evaluator-public-key .famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519/controller/evaluator_channel/public_key.pem \
  --agent-runtime <runtime> \
  --model <model> \
  --benchmark-adapter scimodelingbench \
  --evaluator-adapter scimodelingbench \
  --no-scimodelingbench-prepare-problem
```

fm-job 场景应重新启动同一个 task supervisor，并传入相同的 `RUN_DIR`、task 参数和 evaluator channel。若使用外部 evaluator worker，先确保它已启动且使用同一 `workspace/output`；若由 Harness 管理 evaluator，则让 Harness 在本次 resume invocation 中重新启动 trusted worker。

## 7. 实际效果

### 7.1 正常恢复

一次正常恢复会追加而不是覆盖以下记录：

- `queues/queue_events.jsonl`：`recover`、`resume`、后续 `claim/update`；
- `research_state.yaml`：`audit.resume_events`、新 heartbeat 和新阶段；
- Actor state：新的 revision/session resume count；
- `controller/trajectory.jsonl`：本次新增调度和 Agent 轨迹；
- ExpBank：只增加新的 attempt，不修改旧 attempt 的不可变结果。

### 7.2 不重复执行

已完成的 attempt 仍然是 `finished`，不会重新进入实现或评测。最佳候选仍由 leaderboard 指针指向原来的 `best_attempt_id`，新的候选只有在产生更高有效分数时才更新排行榜。

### 7.3 tfbind8 的预期行为

对上述 tfbind8 目录 resume 后：

- 原有 35 个 attempt 仍保留；
- 原有最佳结果 `0016 / 0.9755947589874268` 仍保留；
- 截止时未执行的 continuation 可以重新进入 ImplementAgent；
- 后续 ImplementAgent 可以继续消费 evaluator feedback，产生 refine/fuse/switch；
- 新 Candidate 进入 Evaluation Pool 后由 trusted evaluator 继续评分；
- 新结果追加到原 ExpBank、trajectory 和 leaderboard；
- 不会因为 resume 生成新的 `tfbind8-<timestamp>` 输出目录。

## 8. 安全与并发

- `control/orchestrator.lock` 防止同一任务被两个调度器同时运行；
- `--fresh` 删除 workspace 前先获取相同运行锁，运行中拒绝删除；
- MasterAgent / 控制面 stop 会取消未完成队列项、在途 Agent 和 Candidate，并写 handoff；不能被普通 resume 偷偷恢复；
- hidden evaluator 数据、私钥和 evaluator 原始结果不因 resume 暴露给 Agent；
- Candidate artifact 仍通过 hash/immutable snapshot 校验，resume 不允许修改已冻结 artifact；
- evaluator budget 由持久化 state 控制，resume 不会通过重新初始化绕过预算。

## 9. 验证与回归

针对任务级 resume 和 stop 的核心回归覆盖：

```bash
python3 -m pytest \
  famou_scientist/loop/tests/test_loop.py::test_task_resume_reopens_all_durable_work_in_same_workspace \
  famou_scientist/loop/tests/test_loop.py::test_master_stop_cancels_unfinished_work_and_resume_does_not_revive \
  famou_scientist/loop/tests/test_loop.py::test_loop_master_bridge_pause_stop_and_clarifications \
  famou_scientist/loop/tests/test_loop.py::test_async_wall_time_drains_evaluations_and_skips_unstarted_work \
  famou_scientist/loop/tests/test_loop_execution.py::test_cli_agent_wrapper_stops_process_when_controller_cancels \
  famou_scientist/loop/tests/test_harness.py::test_http_evaluator_returns_promptly_when_task_is_stopped \
  famou_scientist/loop/tests/test_harness.py::test_benchmark_harness_runs_minimal_role_pipeline
```

当前聚焦结果：核心状态/resume/stop 组 `18 passed`，进程取消、墙钟 Evaluation drain、Harness 组 `3 passed`，HTTP evaluator 取消和 Harness smoke 组 `2 passed`。

完整 Loop suite 在本地临时盘结果为 `231 passed, 2 deselected`。两项 deselected 是当前容器禁止 `setpriv setresuid(65534)` 的特权隔离测试，不属于 resume/stop 功能失败；全部模块同时通过 `compileall` 和 `git diff --check`。

其中任务级回归明确验证：

- 同一个 workspace 中同时存在 Idea、Implement continuation 和 Evaluation candidate 时，墙钟截止后的 resume 会重新打开任务状态并将可恢复项置回 `queued`，但不重置 evaluator budget；
- MasterAgent stop 会把 Queue、Candidate、Actor、Branch 全部同步到 `cancelled`，再次执行 resume 后仍保持终态；
- 墙钟截止不会使用用户 stop 文件，因此已进入 Evaluation Pool 的 Candidate 仍会完整 drain；
- 外部 Agent 进程和本地 evaluator 等待在 stop 后退出，晚到结果不会回流。

## 10. 相关长程 Agent 调研

Resume 的 durable state、bounded mission、文件协议和异步实验设计参考了代码库中的长程 Agent 架构调研：

- [AutoML / AI Research Agent 架构对比](./AUTO_ML_RESEARCH_AGENT_ARCHITECTURES_CN.md)
- AiScientist：论文 https://arxiv.org/abs/2604.13018；GitHub https://github.com/AweAI-Team/AiScientist
- AIBuildAI：v1 https://arxiv.org/abs/2604.14455；v2 https://arxiv.org/abs/2605.27873；GitHub https://github.com/aibuildai/AI-Build-AI
- Argus：论文 https://arxiv.org/abs/2608.05144；截至文档更新时间没有可确认的官方 GitHub 仓库

## 11. 常见错误

### 把 resume 当成新输出目录

错误做法：为恢复任务指定新的 timestamp 目录。这样会丢失原队列、Actor session 和 ExpBank 的任务连续性。

正确做法：复用原 `run_dir`。

`--resume-from` 是不同操作：它从旧 Loop 的可见 artifact、ExpBank 和经验记录派生一个新的 workspace/goal lineage，不复制旧任务的 active queue，也不复活用户 stop 的工作。需要继续 Ideaspark、ImplementActor 和 Evaluation Pool 时必须使用同一 `run_dir` 的任务 resume。

### 使用 `--fresh` 做恢复

`--fresh` 会删除整个 workspace，包括队列、artifact、Actor 和历史证据。它只用于干净重跑。

### 用 `--reinit-state` 代替 resume

`--reinit-state` 会重新初始化研究状态，但保留其他持久化目录。它适合状态修复，不适合作为正常任务恢复入口；正常恢复应直接重新执行原 run 命令或使用 `loop resume`。

### 只恢复 CLI session

恢复 CLI session 不能代替恢复任务级队列。如果 Evaluation Queue、Actor mailbox 或待消费 Idea 没有恢复，Agent 即使带着原 session 重新启动，也不会获得完整任务上下文。
