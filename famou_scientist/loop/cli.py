"""端到端运行时的命令行接口。

端到端科研模式的完整调用流程如下：

┌──────────────────────────────────────────────────────────────────────────────┐
│                          用户 / 外部调用方                                   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
          ┌────────────────────────┴────────────────────────┐
          │                                                 │
          ▼                                                 ▼
┌───────────────────────┐                         ┌────────────────────────────┐
│ famou-scientist loop   │                         │ famou-scientist --mode loop │
│                       │                         │ --goal-file <目标文件>      │
└───────────┬───────────┘                         └─────────────┬──────────────┘
            │                                                 │
            └────────────────────────┬────────────────────────┘
                                     ▼
                         ┌────────────────────────┐
                         │ cli.main(argv)         │
                         │ 解析子命令与参数        │
                         └───────────┬────────────┘
                                     │
                     ┌───────────────┴────────────────┐
                     │                                │
                     ▼                                ▼
          ┌────────────────────┐             ┌──────────────────────────┐
          │ run_goal(args)     │             │ 查询/控制类命令            │
          │ 启动科研循环        │             │ status / pause / stop     │
          └─────────┬──────────┘             │ resume / summary          │
                    │                        │ report / export           │
                    │                        └────────────┬─────────────┘
                    ▼                                     │
          ┌────────────────────┐                           ▼
          │ 加载并校验目标文件  │             ┌──────────────────────────┐
          │ load_goal          │             │ 读取状态、队列、证据并输出 │
          └─────────┬──────────┘             └──────────────────────────┘
                    │
                    ▼
          ┌────────────────────┐
          │ 初始化/恢复工作空间 │
          │ state / queue /     │
          │ artifacts / lock    │
          └─────────┬──────────┘
                    │
                    ┌──────────────────────────┐
                    │ 创建 worker / runner /   │
                    │ trusted evaluator        │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ workflow.type ?          │
                    └────────────┬─────────────┘
                 ┌───────────────┴────────────────┐
                 ▼                                ▼
┌────────────────────────────────┐  ┌────────────────────────────────┐
│ research                       │  │ benchmark_managed              │
│ Human ↔ MasterBridge           │  │ Human out of loop              │
│       ↓                        │  │       ↓                        │
│ 长生命周期 IdeaActor           │  │ Benchmark Task Adapter         │
│       ↓                        │  │       ↓                        │
│ 可选 Idea Gate → Idea Graph    │  │ idea agent → attempt queue     │
│       ↓ 准入                   │  │       ↓                        │
│ IdeaSpark                      │  │ ImplementActor                 │
│       ↓                        │  │       ↓                        │
│ ImplementActor                 │  │ Candidate → EvaluationJob      │
│       ↓                        │  │       ↓                        │
│ Candidate → EvaluationJob      │  │ 官方指标 → actor mailbox        │
│       ↓                        │  │       ↓                        │
│ evaluator → result analyst     │  │ 官方排行榜 → 下一轮尝试          │
│       ↓                        │  │       ↓                        │
│ AnalyzeSpark → 论文候选         │  │ ExpBank / evidence             │
└───────────────┬────────────────┘  └───────────────┬────────────────┘
                └──────────────────┬─────────────────┘
                                   ▼
                      ┌────────────────────────┐
                      │ 同步或异步调度循环       │
                      │ Orchestrator           │
                      │ AsyncOrchestrator      │
                      └────────────────────────┘

异步模式下：

  ┌──────────────┐  有界 Idea 队列  ┌──────────────────┐
  │ IdeaActor    │ ──────────────▶ │ Implement Pool   │
  │ ↕ 同步 Gate  │   IdeaSpark     │ Actor / worktree │
  └──────────────┘                 └────────┬─────────┘
                                           │ 轻量 smoke → submit_candidate → park
                                           ▼
                                  ┌──────────────────┐
                                  │ Candidate        │
                                  │ code/output 独立  │
                                  └────────┬─────────┘
                                           │ Controller preflight + 有界评测队列
                                           ▼
                                  ┌──────────────────┐
                                  │ Evaluation Pool  │
                                  │ run.py → artifact│
                                  │ → evaluator      │
                                  └────────┬─────────┘
                                           │ 脱敏反馈
                                           ▼
                            actor mailbox → repair/refine ready
                                           │
                         park 时释放并发槽；有槽后恢复原 Session

  主线程只串行提交：队列状态、正式预算、Leaderboard、ExpBank 和决策证据。
  同一 Actor 固定只有一个在途 Candidate；不同 Idea 可与慢评测异步重叠。

所有阶段共享但不混淆以下持久化对象：

    研究状态 ─ 队列 ─ Actor/worktree ─ Candidate ─ ExpBank ─ 共享经验池
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

from .agents.workers import workers_from_goal
from .utils import atomic_write_json, json_dumps, now_ms, read_jsonl, safe_name
from .runtime.master_bridge import MasterBridge
from .runtime.control import ControlEventStore
from .runtime.chat_goal import ChatGoalController
from .domain.goal import GoalError, load_goal
from .domain.status import LoopStatus
from .evaluation.evaluator import adapter_from_goal
from .evaluation.experiment import runner_from_goal
from .storage.report import (
    export_evidence_bundle,
    generate_claim_evidence_map,
    generate_final_report,
    generate_status_overview,
    render_status_overview,
)
from .runtime.orchestrator import Orchestrator, OrchestratorConfig
from .runtime.implement_actor import ImplementActorStore
from .observability import ObservabilityStore
from .storage.queues import QueueSet
from .storage.candidates import CandidateStore
from .storage.state import ResearchState
from .storage.workspace import (
    WorkspaceBusyError,
    find_workspace,
    fresh_workspace,
    goal_workspace,
    init_workspace,
    resume_workspace,
)


def run_goal(args: argparse.Namespace) -> int:
    """启动或继续执行目标工作空间。

    返回码含义：

    - 0：正常启动并完成一次运行；
    - 2：目标文件、参数或工作空间初始化过程出错；
    - 3：目标工作空间正被其他调度器占用，当前运行被拒绝。
    """
    try:
        goal_doc = load_goal(args.goal_file)
    except GoalError as exc:
        # 2：目标文件加载/校验失败。
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if getattr(args, "goal_id", None):
        goal_doc = copy.deepcopy(goal_doc)
        goal_doc["goal_id"] = args.goal_id
        goal_doc.setdefault("goal", {})["id"] = args.goal_id
        goal_doc["goal"].setdefault("name", args.goal_id)
    if args.fresh and (args.reinit or args.reinit_state):
        # 2：命令行参数组合非法。
        print("✗ --fresh cannot be combined with --reinit/--reinit-state", file=sys.stderr)
        return 2
    if getattr(args, "resume_from", None) and (args.fresh or args.reinit or args.reinit_state):
        print("✗ --resume-from cannot be combined with --fresh/--reinit/--reinit-state", file=sys.stderr)
        return 2
    try:
        if getattr(args, "resume_from", None):
            source_ws = Path(args.resume_from).expanduser().resolve()
            ws = resume_workspace(
                goal_doc,
                base=args.root,
                source_goal_file=args.goal_file,
                resume_from=source_ws,
            )
            print(f"[famou loop] resume workspace initialized: {ws}")
        elif args.fresh:
            ws = fresh_workspace(goal_doc, base=args.root, source_goal_file=args.goal_file)
            print(f"[famou loop] fresh workspace initialized: {ws}")
        else:
            ws = init_workspace(goal_doc, base=args.root, source_goal_file=args.goal_file)
    except WorkspaceBusyError as exc:
        # 3：工作空间已被其他进程占用。
        print(f"✗ {exc}", file=sys.stderr)
        return 3
    state_store = ResearchState(ws)
    if not state_store.path.exists() or args.reinit or args.reinit_state or args.fresh:
        if (args.reinit or args.reinit_state) and not args.fresh:
            compatibility_warning = (
                " --reinit is deprecated; use --reinit-state."
                if args.reinit
                else ""
            )
            print(
                "[famou loop] warning:"
                f"{compatibility_warning} "
                "reinitialized research_state.yaml only; "
                "queues/artifacts/branches/logs were preserved.",
                file=sys.stderr,
            )
        state_store.init(goal_doc)
    goal_cwd = Path(args.goal_file).resolve().parent
    evaluator = adapter_from_goal(goal_doc, cwd=goal_cwd)
    experiment_runner = runner_from_goal(goal_doc, ws, cwd=goal_cwd)
    workers = workers_from_goal(goal_doc, ws, cwd=goal_cwd)
    constraints = goal_doc.get("constraints") if isinstance(goal_doc.get("constraints"), dict) else {}
    infra = goal_doc.get("infra") if isinstance(goal_doc.get("infra"), dict) else {}
    concurrency = infra.get("concurrency") if isinstance(infra.get("concurrency"), dict) else {}
    goal_parallel_ideas = int(
        concurrency.get("ideas", constraints.get("max_parallel_ideas", 1)) or 1
    )
    max_parallel_ideas = args.max_parallel_ideas if args.max_parallel_ideas is not None else goal_parallel_ideas
    goal_parallel_impl = int(
        concurrency.get(
            "implementations",
            constraints.get(
                "max_parallel_implementations",
                constraints.get("max_parallel_evaluations", 1),
            ),
        )
        or 1
    )
    max_parallel_impl = args.max_parallel_implementations if args.max_parallel_implementations is not None else goal_parallel_impl
    goal_parallel_evaluations = int(
        concurrency.get(
            "evaluations",
            constraints.get("max_parallel_evaluations", 1),
        )
        or 1
    )
    max_parallel_evaluations = (
        args.max_parallel_evaluations
        if args.max_parallel_evaluations is not None
        else goal_parallel_evaluations
    )
    goal_retries = int(constraints.get("max_experiment_retries", 0) or 0)
    max_retries = args.max_experiment_retries if args.max_experiment_retries is not None else goal_retries
    goal_wall_time = constraints.get("max_wall_time_hours")
    max_wall_time = args.max_wall_time_hours if args.max_wall_time_hours is not None else goal_wall_time
    scheduling = (
        infra.get("scheduling")
        if isinstance(infra.get("scheduling"), dict)
        else {}
    )
    idea_ranking = (
        scheduling.get("time_aware_idea_ranking")
        if isinstance(scheduling.get("time_aware_idea_ranking"), dict)
        else {}
    )
    idea_debate = (
        scheduling.get("idea_debate")
        if isinstance(scheduling.get("idea_debate"), dict)
        else {}
    )
    debate_activation = (
        idea_debate.get("activation")
        if isinstance(idea_debate.get("activation"), dict)
        else {}
    )
    config = OrchestratorConfig(
        max_ticks=args.max_ticks,
        interval_sec=args.interval,
        async_pipeline=args.async_pipeline or infra.get("pipeline") == "async",
        min_ideas=args.min_ideas,
        max_parallel_ideas=max_parallel_ideas,
        max_parallel_implementations=max_parallel_impl,
        max_parallel_evaluations=max_parallel_evaluations,
        max_experiment_retries=max_retries,
        max_wall_time_hours=max_wall_time,
        max_implement_lifetime_sec=constraints.get("max_implement_lifetime_sec", 14_400),
        max_implement_turns_per_actor=constraints.get(
            "max_implement_turns_per_actor", 1
        ),
        max_run_attempts_per_actor=constraints.get("max_run_attempts_per_actor"),
        max_official_evaluations_per_actor=constraints.get(
            "max_official_evaluations_per_actor"
        ),
        max_repairs_per_revision=constraints.get("max_repairs_per_revision", 1),
        idea_queue_high_watermark=constraints.get("idea_queue_high_watermark"),
        evaluation_queue_capacity=constraints.get("evaluation_queue_capacity"),
        time_aware_idea_ranking_enabled=(
            idea_ranking.get("enabled") is True
        ),
        idea_rank_trigger_remaining_sec=idea_ranking.get(
            "trigger_remaining_sec",
            3_600,
        ),
        idea_rank_judge_timeout_sec=idea_ranking.get(
            "judge_timeout_sec",
            1_800,
        ),
        idea_rank_min_items=idea_ranking.get("min_items", 3),
        idea_debate_enabled=idea_debate.get("enabled") is True,
        idea_debate_mode=idea_debate.get("mode", "respond"),
        idea_debate_max_rounds=idea_debate.get("max_rounds", 1),
        idea_debate_min_elapsed_sec=debate_activation.get(
            "min_elapsed_sec",
            3_600,
        ),
        idea_debate_min_evaluated_attempts=debate_activation.get(
            "min_evaluated_attempts",
            1,
        ),
        idea_debate_allow_cross_task_only=(
            debate_activation.get("allow_cross_task_only") is True
        ),
        idea_debate_emit_pair=idea_debate.get("emit_pair") is True,
        validity_verifier_enabled=bool(
            constraints.get("validity_verifier_enabled", False)
        ),
    )
    orchestrator_cls = Orchestrator
    if config.async_pipeline:
        from .runtime import AsyncOrchestrator

        orchestrator_cls = AsyncOrchestrator
    orch = orchestrator_cls(
        ws,
        goal_doc,
        evaluator=evaluator,
        experiment_runner=experiment_runner,
        workers=workers,
        validity_verifier=(
            workers
            if config.validity_verifier_enabled
            and getattr(workers, "validity_verifier_agent", None) is not None
            else None
        ),
        config=config,
    )
    try:
        state = orch.run()
    except WorkspaceBusyError as exc:
        # 3：调度器运行期间检测到并发占用冲突。
        print(f"✗ {exc}", file=sys.stderr)
        return 3
    ObservabilityStore(ws).write_summary()
    print(f"[famou loop] goal_id={goal_doc['goal_id']}")
    print(f"[famou loop] workspace={ws}")
    print(f"[famou loop] status={state.get('research_state', {}).get('status')}")
    return 0


def status_goal(args: argparse.Namespace) -> int:
    """输出目标工作空间的当前状态。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        overview = generate_status_overview(ws)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json_dumps(overview))
    else:
        print(render_status_overview(overview), end="")
    return 0


def _control(args: argparse.Namespace, name: str, enabled: bool = True) -> int:
    """通过统一控制事件协议提交 pause 或 stop。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if not enabled:
        # 仅保留给旧调用方的文件清理行为；正式 resume 入口使用
        # resume_goal()，避免出现“清文件但没有控制事件”的隐式分支。
        path = ws / "control" / name
        path.unlink(missing_ok=True)
        print(f"[famou loop] {name} cleared for {args.goal_id}")
        return 0
    return _submit_control_event(ws, name, args.goal_id)


def _submit_control_event(ws: Path, name: str, goal_id: str) -> int:
    """提交 pause/stop 控制事件。"""

    store = MasterBridge(ws)
    record = store.request_control(
        name,
        source="loop-cli",
        goal_id=goal_id,
    )
    # There may be no resident orchestrator process. Reflect the control request
    # immediately; the next run still consumes the durable command as an audit event.
    state_store = ResearchState(ws)
    state = state_store.load()
    research = state.setdefault("research_state", {})
    if name == "pause":
        research["status"] = LoopStatus.Research.PAUSED
        research["termination_reason"] = "paused_by_user"
        state_store.save(state)
    elif name == "stop":
        research["status"] = LoopStatus.Research.STOPPED
        research["lifecycle"] = "stopped_by_user"
        research["termination_reason"] = "stopped_by_user"
        cancel_payload = {
            "reason": "stopped_by_user",
            "created_at": now_ms(),
        }
        atomic_write_json(
            ws / "agent_control" / "research_stop_requested.json",
            cancel_payload,
        )
        # 兼容现有 Agent wrapper 的单文件取消参数；显式 stop 产生的是
        # cancelled 终态，之后普通 resume 不会复活这些条目。
        atomic_write_json(
            ws / "agent_control" / "research_deadline_reached.json",
            cancel_payload,
        )
        queues = QueueSet(ws)
        cancelled = queues.cancel_unfinished(reason="stopped_by_user")
        CandidateStore(ws).cancel_unfinished(reason="stopped_by_user")
        ImplementActorStore(ws).cancel_unfinished(reason="stopped_by_user")
        cancelled_branch_ids = {
            str(payload.get("branch_id"))
            for items in cancelled.values()
            for item in items
            if isinstance((payload := item.get("payload")), dict)
            and payload.get("branch_id")
        }
        for branch in research.get("branches") or []:
            if str(branch.get("branch_id") or "") in cancelled_branch_ids:
                branch["status"] = LoopStatus.Branch.CANCELLED
        state_store.update_queues(state, queues.summary())
    _print_control_record(record, prefix=name)
    return 0


def resume_goal(args: argparse.Namespace) -> int:
    """恢复一个已存在的 Loop 工作空间。"""

    try:
        ws = find_workspace(args.goal_id, base=args.root)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    record = MasterBridge(ws).request_control(
        "resume",
        source="loop-cli",
        goal_id=args.goal_id,
    )
    state_store = ResearchState(ws)
    state = state_store.load()
    research = state.setdefault("research_state", {})
    status = research.get("status")
    reason = str(research.get("termination_reason") or "")
    queues = QueueSet(ws)
    if status == LoopStatus.Research.PAUSED:
        research["status"] = LoopStatus.Research.RUNNING
        research["lifecycle"] = "active"
        research["termination_reason"] = None
        research["active_run_started_at"] = now_ms()
        state_store.save(state)
    elif status == LoopStatus.Research.STOPPED and reason == "wall_time_budget_exhausted":
        resumed = queues.requeue_for_resume(
            reason_prefix="research_wall_time_budget_exhausted"
        )
        for actor in ImplementActorStore(ws).list():
            actor_reason = str(actor.get("termination_reason") or "")
            if actor_reason.startswith("research_runtime_") or actor_reason == (
                "research_wall_time_budget_exhausted"
            ):
                ImplementActorStore(ws).update(
                    str(actor["actor_id"]),
                    status="ready",
                    termination_reason=None,
                )
        research["status"] = LoopStatus.Research.RUNNING
        research["lifecycle"] = "active"
        research["termination_reason"] = None
        research["current_phase"] = "resuming"
        research["active_run_started_at"] = now_ms()
        research.pop("shutdown", None)
        (ws / "agent_control" / "research_deadline_reached.json").unlink(
            missing_ok=True
        )
        state_store.update_queues(state, queues.summary())
    _print_control_record(record, prefix="resume queued")
    return 0


def _load_mapping_file(path: str | Path) -> dict:
    """读取 JSON 或 YAML object 文件。"""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"文件不存在: {source}")
    text = source.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"无法解析结构化文件，且当前环境没有 PyYAML: {source}") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"结构化文件顶层必须是 object: {source}")
    return value


def _print_control_record(record: dict, *, prefix: str) -> None:
    """以稳定格式打印刚提交的控制记录。"""
    print(f"[famou loop] {prefix}: {record.get('command_id') or record.get('event_id')}")
    print(json_dumps(record))


def message_goal(args: argparse.Namespace) -> int:
    """向运行中的 Loop 追加一条人类消息。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        record = MasterBridge(ws).submit_message(
            args.text,
            source="loop-cli",
            goal_id=args.goal_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    _print_control_record(record, prefix="message queued")
    return 0


def answer_goal(args: argparse.Namespace) -> int:
    """向 Loop 提交一条澄清问题回答。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        record = MasterBridge(ws).answer_clarification(
            args.request_id,
            args.text,
            source="loop-cli",
            goal_id=args.goal_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    _print_control_record(record, prefix="clarification answer queued")
    return 0


def goal_change(args: argparse.Namespace) -> int:
    """提交继续当前 Loop 或停止当前 Loop 的目标变更请求。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        patch = _load_mapping_file(args.patch_file) if args.patch_file else None
        next_goal = (
            _load_mapping_file(args.next_goal_file)
            if args.next_goal_file
            else None
        )
        record = MasterBridge(ws).request_goal_change(
            decision=args.decision,
            instruction=args.instruction,
            goal_patch=patch,
            next_goal=next_goal,
            reason=args.reason,
            source="loop-cli",
            goal_id=args.goal_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    _print_control_record(record, prefix="goal change queued")
    return 0


def events_goal(args: argparse.Namespace) -> int:
    """读取 Loop 控制面的出站事件回执。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        rows = ControlEventStore(ws).read_events(limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json_dumps(rows))
        return 0
    if not rows:
        print("No control events.")
    for row in rows:
        print(
            f"- [{row.get('status', '')}] {row.get('type', '')} "
            f"command={row.get('command_id', '')}: {row.get('payload', {})}"
        )
    return 0


def _chat_controller(args: argparse.Namespace) -> ChatGoalController:
    """根据 CLI 参数创建聊天 Goal 控制器。"""
    return ChatGoalController(args.root, project_root=args.project_root)


def _proposal_input(args: argparse.Namespace) -> dict:
    """读取 Master 生成的 GoalProposal object。"""
    if args.proposal_file:
        value = _load_mapping_file(args.proposal_file)
    elif args.proposal_json:
        try:
            value = json.loads(args.proposal_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--proposal-json 不是合法 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("--proposal-json 顶层必须是 object")
    elif args.raw_instruction:
        value = {
            "raw_user_message": args.raw_instruction,
            "master_decision": "enter_loop",
            "decision_reason": "用户通过 /goal 显式请求创建自主科研目标。",
            "objective_brief": {"primary_goal": args.raw_instruction},
        }
    else:
        raise ValueError(
            "propose 需要 --proposal-file、--proposal-json 或 --raw-instruction"
        )
    if args.raw_instruction:
        value.setdefault("raw_user_message", args.raw_instruction)
    return value


def chat_propose(args: argparse.Namespace) -> int:
    """保存聊天目标提议，并按 confirm/auto 策略处理。"""
    try:
        result = _chat_controller(args).propose(
            _proposal_input(args),
            conversation_id=args.conversation_id,
            mode=args.mode,
            auto_authorized=args.auto_authorized,
            authorization_text=args.authorization_text,
            source=args.source,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 必须返回稳定错误码
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_confirm(args: argparse.Namespace) -> int:
    """确认最近一条 GoalProposal 并启动后台 Loop。"""
    try:
        result = _chat_controller(args).confirm(
            conversation_id=args.conversation_id,
            proposal_id=args.proposal_id,
            source=args.source,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_reject(args: argparse.Namespace) -> int:
    """拒绝最近一条 GoalProposal。"""
    try:
        result = _chat_controller(args).reject(
            conversation_id=args.conversation_id,
            proposal_id=args.proposal_id,
            reason=args.reason,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_status(args: argparse.Namespace) -> int:
    """显示当前聊天会话的提议、授权和后台 Loop 状态。"""
    try:
        result = _chat_controller(args).status(args.conversation_id)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_policy(args: argparse.Namespace) -> int:
    """记录用户对 confirm/auto 模式的会话级授权。"""
    try:
        result = _chat_controller(args).set_policy(
            args.conversation_id,
            args.mode,
            actor=args.actor,
            source=args.source,
            authorization_text=args.authorization_text,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_control(args: argparse.Namespace) -> int:
    """控制当前聊天会话关联的活动 Loop。"""
    try:
        result = _chat_controller(args).control(
            args.conversation_id,
            args.action,
            reason=args.reason,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_message(args: argparse.Namespace) -> int:
    """把聊天中的补充意见传给当前活动 Loop。"""
    try:
        result = _chat_controller(args).submit_message(
            args.conversation_id,
            args.text,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def chat_answer(args: argparse.Namespace) -> int:
    """把用户对澄清请求的回答传给当前活动 Loop。"""
    try:
        result = _chat_controller(args).answer_clarification(
            args.conversation_id,
            args.request_id,
            args.text,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def _optional_json_object(value: str | None, option: str) -> dict | None:
    """解析聊天工具传入的可选 JSON object。"""
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{option} 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{option} 顶层必须是 object")
    return parsed


def chat_goal_change(args: argparse.Namespace) -> int:
    """按用户选择把目标变更请求传给当前活动 Loop。"""
    try:
        result = _chat_controller(args).request_goal_change(
            args.conversation_id,
            decision=args.decision,
            instruction=args.instruction,
            goal_patch=_optional_json_object(args.goal_patch_json, "--goal-patch-json"),
            next_goal=_optional_json_object(args.next_goal_json, "--next-goal-json"),
            reason=args.reason,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(json_dumps(result))
    return 0


def _merge_mapping(dst: dict, src: dict) -> None:
    """递归合并 fork 目标中的 object 字段。"""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge_mapping(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


def _goal_from_parent_workspace(parent: Path, parent_goal_id: str) -> dict:
    """从父 Loop 工作空间读取可供 fork 使用的目标。"""
    source = parent / "goal.yaml"
    if source.is_file():
        goal_doc = load_goal(source)
        # goal.yaml 是初始化时的原始目标，当前运行中已应用的旧 patch 只会
        # 保存在 ResearchState；fork 必须以父 Loop 的实际目标快照为基础。
        try:
            state_goal = ResearchState(parent).load().get("research_state", {}).get(
                "goal",
                {},
            )
        except FileNotFoundError:
            state_goal = {}
        if isinstance(state_goal, dict):
            for key in ("objective_brief", "constraints", "workflow", "infra"):
                if key in state_goal:
                    goal_doc[key] = copy.deepcopy(state_goal[key])
            if state_goal.get("name"):
                goal_doc.setdefault("goal", {})["name"] = state_goal["name"]
        return goal_doc
    state = ResearchState(parent).load().get("research_state", {})
    state_goal = state.get("goal") if isinstance(state.get("goal"), dict) else {}
    return load_goal_from_state(state_goal, parent_goal_id, source_path=source)


def load_goal_from_state(
    state_goal: dict,
    goal_id: str,
    *,
    source_path: Path,
) -> dict:
    """把旧版仅保存于 ResearchState 的目标恢复为可校验 goal 文档。"""
    data = {
        "goal": {"id": goal_id, "name": state_goal.get("name") or goal_id},
        "workflow": state_goal.get("workflow") or {"type": "research"},
        "benchmarks": state_goal.get("benchmarks") or [],
        "objective_brief": state_goal.get("objective_brief") or {},
        "constraints": state_goal.get("constraints") or {},
        "infra": state_goal.get("infra") or {},
        "outputs": state_goal.get("outputs") or {},
    }
    # 不在仓库落临时文件：父工作空间可能是旧版本，只保存了 ResearchState
    # 的目标摘要，因此这里直接复用目标文档校验函数。
    from .domain.goal import _validate_goal_doc  # type: ignore

    _validate_goal_doc(data)
    data["goal_id"] = goal_id
    data["goal_file"] = str(source_path)
    return data


def _fork_goal(args: argparse.Namespace) -> int:
    """创建一个全新 Loop，并通过 lineage 只读连接父 Loop。"""
    try:
        parent = find_workspace(args.parent_goal_id, base=args.root).resolve()
        new_goal_id = str(args.new_goal_id)
        if new_goal_id != safe_name(new_goal_id):
            raise ValueError(f"非法 new goal id: {new_goal_id!r}")
        if new_goal_id == args.parent_goal_id:
            raise ValueError("new goal id 不能与 parent goal id 相同")
        target = goal_workspace(new_goal_id, args.root)
        if target.exists():
            raise FileExistsError(f"新 Loop workspace 已存在，不覆盖: {target}")

        parent_goal = _goal_from_parent_workspace(parent, args.parent_goal_id)
        if args.goal_file:
            goal_doc = load_goal(args.goal_file)
        else:
            goal_doc = parent_goal
            if not args.patch_file:
                raise ValueError("fork 必须提供 --goal-file 或 --patch-file")

        if args.patch_file:
            from .domain.goal import validate_goal_patch

            normalized = validate_goal_patch(_load_mapping_file(args.patch_file))
            changes = normalized["changes"]
            if isinstance(changes.get("objective_brief"), dict):
                goal_doc.setdefault("objective_brief", {})
                _merge_mapping(goal_doc["objective_brief"], changes["objective_brief"])
            if isinstance(changes.get("constraints"), dict):
                goal_doc.setdefault("constraints", {})
                _merge_mapping(goal_doc["constraints"], changes["constraints"])

        goal_doc = copy.deepcopy(goal_doc)
        goal_doc.setdefault("goal", {})["id"] = new_goal_id
        goal_doc["goal"]["name"] = goal_doc["goal"].get("name") or new_goal_id
        goal_doc["goal_id"] = new_goal_id
        old_lineage = (
            parent_goal.get("lineage")
            if isinstance(parent_goal.get("lineage"), dict)
            else {}
        )

        def unique_paths(values: list[object]) -> list[str]:
            """规范化并去重 lineage 路径。"""
            out: list[str] = []
            seen: set[str] = set()
            for value in values:
                if not value:
                    continue
                path = str(Path(str(value)).expanduser().resolve())
                if path not in seen:
                    seen.add(path)
                    out.append(path)
            return out

        goal_doc["lineage"] = {
            "parent_loop_id": args.parent_goal_id,
            "parent_workspace": str(parent),
            "parent_handoff": str(parent / "handoff.md"),
            "forked_at": now_ms(),
            "prior_loop_dirs": unique_paths(
                [parent, *(old_lineage.get("prior_loop_dirs") or [])]
            ),
            "experience_sources": unique_paths(
                [
                    parent / "shared_experience_pool",
                    *(old_lineage.get("experience_sources") or []),
                ]
            ),
        }
        goal_doc["goal_file"] = str(target / "goal.yaml")
        target = init_workspace(goal_doc, base=args.root)
        atomic_write_json(target / "goal.yaml", goal_doc)
        atomic_write_json(target / "lineage.json", goal_doc["lineage"])
        ResearchState(target).init(goal_doc)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    goal_path = target / "goal.yaml"
    print(f"[famou loop] forked {args.parent_goal_id} -> {new_goal_id}")
    print(f"[famou loop] workspace={target}")
    print(
        "[famou loop] run="
        f"famou-scientist loop run --goal-file {goal_path} --root {Path(args.root or '.famou/loop').resolve()}"
    )
    return 0


def patch_goal(args: argparse.Namespace) -> int:
    """写入用户或主控提供的目标补丁。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        import json
        patch = json.loads(Path(args.patch_file).read_text(encoding="utf-8"))
        MasterBridge(ws).write_goal_patch(patch)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(f"[famou loop] goal patch queued for {args.goal_id}: {ws / 'control' / 'goal_patch.json'}")
    return 0


def summary_goal(args: argparse.Namespace) -> int:
    """输出目标工作空间摘要。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        state = ResearchState(ws).load()
        text = MasterBridge(ws).render_status_summary(state, QueueSet(ws).summary())
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(text, end="")
    return 0


def clarifications_goal(args: argparse.Namespace) -> int:
    """输出待澄清的问题列表。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        path = ws / "control" / "clarification_request.jsonl"
        rows = read_jsonl(path)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json_dumps(rows))
    else:
        if not rows:
            print("No clarification requests.")
        for row in rows:
            print(f"- [{row.get('status', 'open')}] {row.get('type', '')} branch={row.get('branch_id', '')}: {row.get('question', '')}")
    return 0


def export_goal(args: argparse.Namespace) -> int:
    """导出目标工作空间证据包。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        bundle = export_evidence_bundle(ws, output=args.output)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print(f"[famou loop] evidence bundle: {bundle}")
    print(f"[famou loop] zip: {bundle / 'evidence_bundle.zip'}")
    return 0


def report_goal(args: argparse.Namespace) -> int:
    """生成目标工作空间报告。"""
    try:
        ws = find_workspace(args.goal_id, base=args.root)
        claim_map = generate_claim_evidence_map(ws)
        text = generate_final_report(ws, claim_map=claim_map)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"[famou loop] report: {args.output}")
        else:
            print(text, end="")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    return 0


def telemetry_goal(args: argparse.Namespace) -> int:
    """汇总或导出任意 Loop/Harness Run 的统一 Agent 观测数据。"""

    try:
        workspace = (
            Path(args.workspace).expanduser().resolve()
            if args.workspace
            else find_workspace(args.goal_id, base=args.root)
        )
        if not workspace.is_dir():
            raise FileNotFoundError(f"Run 工作空间不存在: {workspace}")
        store = ObservabilityStore(workspace)
        summary = store.write_summary()
        export_dir = store.export(args.output) if args.output else None
    except Exception as exc:  # noqa: BLE001 - CLI 返回稳定错误码
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json_dumps(summary))
    else:
        total = summary["total"]
        print(f"[famou loop] workspace={workspace}")
        print(
            "[famou loop] agent calls="
            f"{total['calls']} duration_hours={total['duration_ms'] / 3_600_000:.3f}"
        )
        print(
            "[famou loop] reported tokens="
            f"{total['reported_total_tokens']} "
            f"covered_calls={total['calls_with_token_usage']}/{total['calls']}"
        )
        print(
            "[famou loop] CLI/adapter-reported cost="
            f"{total['cli_reported_cost'] or 'unavailable'} "
            f"covered_calls={total['calls_with_reported_cost']}/{total['calls']}"
        )
        print(
            "[famou loop] configured-price cost="
            f"{total['calculated_cost'] or 'unavailable'} "
            f"covered_calls={total['calls_with_calculated_cost']}/{total['calls']}"
        )
        print(f"[famou loop] summary={store.summary_path}")
        if export_dir is not None:
            print(f"[famou loop] export={export_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    p = argparse.ArgumentParser(prog="famou-scientist loop", description="Famou Scientist Loop autonomous research runtime (V1)")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="运行一个 Loop 目标")
    run.add_argument("--goal-file", required=True)
    run.add_argument("--goal-id", default=None, help="override the goal workspace id")
    run.add_argument("--root", default=None, help="loop root directory (default .famou/loop)")
    run.add_argument(
        "--resume-from",
        default=None,
        help="resume into a fresh workspace seeded from an older workspace directory",
    )
    run.add_argument(
        "--max-ticks",
        type=int,
        default=5,
        help="调度周期上限；0 只初始化，负数持续运行直到预算/停止条件生效",
    )
    run.add_argument("--interval", type=float, default=0.1)
    run.add_argument("--min-ideas", type=int, default=1)
    run.add_argument(
        "--max-parallel-ideas",
        type=int,
        default=None,
        help="override infra.concurrency.ideas (default: goal file)",
    )
    run.add_argument(
        "--max-parallel-implementations",
        type=int,
        default=None,
        help="override infra.concurrency.implementations (default: goal file)",
    )
    run.add_argument(
        "--max-parallel-evaluations",
        type=int,
        default=None,
        help="override infra.concurrency.evaluations (default: goal file)",
    )
    run.add_argument(
        "--max-experiment-retries",
        type=int,
        default=None,
        help="override constraints.max_experiment_retries (default: goal file)",
    )
    run.add_argument(
        "--max-wall-time-hours",
        type=float,
        default=None,
        help="override constraints.max_wall_time_hours (default: goal file)",
    )
    run.add_argument(
        "--async-pipeline",
        action="store_true",
        help="run producer/consumer pipeline while experiment runners stay in flight",
    )
    run.add_argument(
        "--fresh",
        action="store_true",
        help="delete and recreate this goal workspace before running",
    )
    run.add_argument(
        "--reinit-state",
        action="store_true",
        help="reinitialize only research_state.yaml; keep queues/artifacts/branches",
    )
    run.add_argument(
        "--reinit",
        action="store_true",
        help="deprecated alias for --reinit-state",
    )
    run.set_defaults(func=run_goal)

    chat = sub.add_parser(
        "chat",
        help="从聊天会话提议、确认并启动自主科研 Loop",
    )
    chat_sub = chat.add_subparsers(dest="chat_cmd", required=True)

    def add_chat_context(parser: argparse.ArgumentParser) -> None:
        """为聊天控制子命令增加统一的会话与目录参数。"""
        parser.add_argument(
            "--conversation-id",
            default=os.environ.get("FAMOU_CHAT_SESSION_ID", "default"),
            help="聊天会话标识；OpenCode 工具会自动传入 session id",
        )
        parser.add_argument(
            "--root",
            default=None,
            help="Loop 根目录，默认当前项目的 .famou/loop",
        )
        parser.add_argument(
            "--project-root",
            default=None,
            help="后台 Loop 的工作目录，默认当前目录",
        )
        parser.add_argument("--source", default="loop-cli")

    propose = chat_sub.add_parser("propose", help="创建待确认的 GoalProposal")
    add_chat_context(propose)
    propose.add_argument("--proposal-file")
    propose.add_argument("--proposal-json")
    propose.add_argument("--raw-instruction")
    propose.add_argument("--mode", choices=["confirm", "auto"], default=None)
    propose.add_argument(
        "--auto-authorized",
        action="store_true",
        help="原始用户消息已明确授权全自动；该事实会进入审计记录",
    )
    propose.add_argument(
        "--authorization-text",
        default=None,
        help="一次性 auto 的用户授权原文，必须与 proposal.raw_user_message 一致",
    )
    propose.set_defaults(func=chat_propose)

    confirm = chat_sub.add_parser("confirm", help="确认提议并后台启动 Loop")
    add_chat_context(confirm)
    confirm.add_argument("--proposal-id", default=None)
    confirm.set_defaults(func=chat_confirm)

    reject = chat_sub.add_parser("reject", help="拒绝提议但保留审计证据")
    add_chat_context(reject)
    reject.add_argument("--proposal-id", default=None)
    reject.add_argument("--reason", default="rejected_by_user")
    reject.set_defaults(func=chat_reject)

    chat_state = chat_sub.add_parser("status", help="查看聊天 Goal 与后台 Loop 状态")
    add_chat_context(chat_state)
    chat_state.set_defaults(func=chat_status)

    policy = chat_sub.add_parser("policy", help="设置 confirm/auto 会话授权策略")
    add_chat_context(policy)
    policy.add_argument("--mode", required=True, choices=["confirm", "auto"])
    policy.add_argument("--actor", default="human")
    policy.add_argument("--authorization-text", default=None)
    policy.set_defaults(func=chat_policy)

    chat_control_parser = chat_sub.add_parser(
        "control",
        help="暂停、恢复或停止当前聊天关联的 Loop",
    )
    add_chat_context(chat_control_parser)
    chat_control_parser.add_argument(
        "--action",
        required=True,
        choices=["pause", "resume", "stop"],
    )
    chat_control_parser.add_argument("--reason", default="chat_goal_control")
    chat_control_parser.set_defaults(func=chat_control)

    chat_message_parser = chat_sub.add_parser(
        "message",
        help="把用户补充意见传给当前活动 Loop",
    )
    add_chat_context(chat_message_parser)
    chat_message_parser.add_argument("--text", required=True)
    chat_message_parser.set_defaults(func=chat_message)

    chat_answer_parser = chat_sub.add_parser(
        "answer",
        help="回答当前 Loop 的澄清请求",
    )
    add_chat_context(chat_answer_parser)
    chat_answer_parser.add_argument("--request-id", required=True)
    chat_answer_parser.add_argument("--text", required=True)
    chat_answer_parser.set_defaults(func=chat_answer)

    chat_change_parser = chat_sub.add_parser(
        "goal-change",
        help="提交用户确认过的目标变更处置",
    )
    add_chat_context(chat_change_parser)
    chat_change_parser.add_argument(
        "--decision",
        required=True,
        choices=["continue_current", "stop_current"],
    )
    chat_change_parser.add_argument("--instruction", required=True)
    chat_change_parser.add_argument("--goal-patch-json", default=None)
    chat_change_parser.add_argument("--next-goal-json", default=None)
    chat_change_parser.add_argument("--reason", default="human_goal_change")
    chat_change_parser.set_defaults(func=chat_goal_change)

    st = sub.add_parser("status", help="show loop goal status")
    st.add_argument("--goal-id", required=True)
    st.add_argument("--root", default=None)
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=status_goal)

    stop = sub.add_parser("stop", help="request stop")
    stop.add_argument("--goal-id", required=True)
    stop.add_argument("--root", default=None)
    stop.set_defaults(func=lambda a: _control(a, "stop", True))

    pause = sub.add_parser("pause", help="request pause")
    pause.add_argument("--goal-id", required=True)
    pause.add_argument("--root", default=None)
    pause.set_defaults(func=lambda a: _control(a, "pause", True))

    resume = sub.add_parser("resume", help="clear pause/stop flags")
    resume.add_argument("--goal-id", required=True)
    resume.add_argument("--root", default=None)
    resume.set_defaults(func=resume_goal)

    message = sub.add_parser("message", help="向当前 Loop 追加人类消息")
    message.add_argument("--goal-id", required=True)
    message.add_argument("--root", default=None)
    message.add_argument("--text", required=True)
    message.set_defaults(func=message_goal)

    answer = sub.add_parser("answer", help="回答 Loop 的澄清请求")
    answer.add_argument("--goal-id", required=True)
    answer.add_argument("--root", default=None)
    answer.add_argument("--request-id", required=True)
    answer.add_argument("--text", required=True)
    answer.set_defaults(func=answer_goal)

    change = sub.add_parser("goal-change", help="提交当前 Loop 的目标变更决策")
    change.add_argument("--goal-id", required=True)
    change.add_argument("--root", default=None)
    change.add_argument(
        "--decision",
        required=True,
        choices=["continue_current", "stop_current"],
    )
    change.add_argument("--instruction", default=None)
    change.add_argument("--patch-file", default=None)
    change.add_argument("--next-goal-file", default=None)
    change.add_argument("--reason", default="human_goal_change")
    change.set_defaults(func=goal_change)

    events = sub.add_parser("events", help="读取 Loop 控制事件回执")
    events.add_argument("--goal-id", required=True)
    events.add_argument("--root", default=None)
    events.add_argument("--limit", type=int, default=None)
    events.add_argument("--json", action="store_true")
    events.set_defaults(func=events_goal)

    fork = sub.add_parser("fork", help="从旧 Loop 创建新的独立 Loop")
    fork.add_argument("--parent-goal-id", required=True)
    fork.add_argument("--new-goal-id", required=True)
    fork.add_argument("--root", default=None)
    fork.add_argument(
        "--goal-file",
        default=None,
        help="新目标文件；不提供时从父 Loop 目标复制并配合 --patch-file",
    )
    fork.add_argument(
        "--patch-file",
        default=None,
        help="应用于新目标的 goal patch JSON/YAML",
    )
    fork.set_defaults(func=_fork_goal)

    patch = sub.add_parser("patch", help="queue a goal_patch JSON file for Master bridge")
    patch.add_argument("--goal-id", required=True)
    patch.add_argument("--patch-file", required=True)
    patch.add_argument("--root", default=None)
    patch.set_defaults(func=patch_goal)

    summary = sub.add_parser("summary", help="render status_summary.md and print it")
    summary.add_argument("--goal-id", required=True)
    summary.add_argument("--root", default=None)
    summary.set_defaults(func=summary_goal)

    clar = sub.add_parser("clarifications", help="list clarification requests")
    clar.add_argument("--goal-id", required=True)
    clar.add_argument("--root", default=None)
    clar.add_argument("--json", action="store_true")
    clar.set_defaults(func=clarifications_goal)

    export = sub.add_parser("export", help="export evidence bundle")
    export.add_argument("--goal-id", required=True)
    export.add_argument("--root", default=None)
    export.add_argument("--output", default=None, help="output directory; default workspace/artifacts/evidence_bundle")
    export.set_defaults(func=export_goal)

    report = sub.add_parser("report", help="render final report")
    report.add_argument("--goal-id", required=True)
    report.add_argument("--root", default=None)
    report.add_argument("--output", default=None)
    report.set_defaults(func=report_goal)

    telemetry = sub.add_parser(
        "telemetry",
        aliases=["observability"],
        help="汇总并导出 Agent 轨迹、Token、时长和供应商费用",
    )
    source = telemetry.add_mutually_exclusive_group(required=True)
    source.add_argument("--workspace", help="Loop 或 Harness Run 根目录")
    source.add_argument("--goal-id", help="普通 Loop 的 goal id")
    telemetry.add_argument("--root", default=None)
    telemetry.add_argument(
        "--output",
        default=None,
        help="可选导出目录；生成 usage JSONL/CSV、trajectory JSONL 和摘要",
    )
    telemetry.add_argument("--json", action="store_true")
    telemetry.set_defaults(func=telemetry_goal)

    return p


def main(argv: list[str] | None = None) -> int:
    """执行命令行主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def run_from_mode_flags(argv: list[str]) -> int:
    """将 ``--mode loop`` 参数式入口转换为 ``loop run`` 子命令。"""
    args = list(argv)
    goal_file = None
    max_ticks = None
    async_pipeline = False
    max_parallel_evaluations = None
    max_parallel_ideas = None
    max_parallel_implementations = None
    max_experiment_retries = None
    max_wall_time_hours = None
    root = None
    fresh = False
    reinit_state = False
    reinit = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--goal-file" and i + 1 < len(args):
            goal_file = args[i + 1]; i += 2; continue
        if arg.startswith("--goal-file="):
            goal_file = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--max-ticks" and i + 1 < len(args):
            max_ticks = args[i + 1]; i += 2; continue
        if arg.startswith("--max-ticks="):
            max_ticks = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--max-parallel-evaluations" and i + 1 < len(args):
            max_parallel_evaluations = args[i + 1]; i += 2; continue
        if arg.startswith("--max-parallel-evaluations="):
            max_parallel_evaluations = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--max-parallel-ideas" and i + 1 < len(args):
            max_parallel_ideas = args[i + 1]; i += 2; continue
        if arg.startswith("--max-parallel-ideas="):
            max_parallel_ideas = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--max-parallel-implementations" and i + 1 < len(args):
            max_parallel_implementations = args[i + 1]; i += 2; continue
        if arg.startswith("--max-parallel-implementations="):
            max_parallel_implementations = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--max-experiment-retries" and i + 1 < len(args):
            max_experiment_retries = args[i + 1]; i += 2; continue
        if arg.startswith("--max-experiment-retries="):
            max_experiment_retries = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--max-wall-time-hours" and i + 1 < len(args):
            max_wall_time_hours = args[i + 1]; i += 2; continue
        if arg.startswith("--max-wall-time-hours="):
            max_wall_time_hours = arg.split("=", 1)[1]; i += 1; continue
        if arg == "--root" and i + 1 < len(args):
            root = args[i + 1]; i += 2; continue
        if arg in {"--async-pipeline", "--async"}:
            async_pipeline = True; i += 1; continue
        if arg == "--fresh":
            fresh = True; i += 1; continue
        if arg == "--reinit-state":
            reinit_state = True; i += 1; continue
        if arg == "--reinit":
            reinit = True; i += 1; continue
        i += 1
    if not goal_file:
        print("✗ --mode loop 需要 --goal-file <path>", file=sys.stderr)
        return 2
    new_argv = ["run", "--goal-file", goal_file]
    if max_ticks is not None:
        new_argv += ["--max-ticks", str(max_ticks)]
    if root is not None:
        new_argv += ["--root", root]
    if async_pipeline:
        new_argv.append("--async-pipeline")
    if max_parallel_evaluations is not None:
        new_argv += ["--max-parallel-evaluations", str(max_parallel_evaluations)]
    if max_parallel_ideas is not None:
        new_argv += ["--max-parallel-ideas", str(max_parallel_ideas)]
    if max_parallel_implementations is not None:
        new_argv += ["--max-parallel-implementations", str(max_parallel_implementations)]
    if max_experiment_retries is not None:
        new_argv += ["--max-experiment-retries", str(max_experiment_retries)]
    if max_wall_time_hours is not None:
        new_argv += ["--max-wall-time-hours", str(max_wall_time_hours)]
    if fresh:
        new_argv.append("--fresh")
    if reinit_state:
        new_argv.append("--reinit-state")
    if reinit:
        new_argv.append("--reinit")
    return main(new_argv)


def run_from_legacy_flags(argv: list[str]) -> int:
    """兼容旧调用方，并转发到参数式 Loop 入口。"""
    return run_from_mode_flags(argv)


if __name__ == "__main__":
    raise SystemExit(main())
