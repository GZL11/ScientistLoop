"""Loop 调度、状态、评测和命令行行为测试。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
import famou_scientist.loop.runtime.orchestrator as orchestrator_module

from famou_scientist import cmdline
from famou_scientist.loop.agents.workers import DummyWorkerSet, PromptWorkerSet
from famou_scientist.loop import cli
from famou_scientist.loop.evaluation.evaluator import (
    BenchmarkAdapter,
    CommandEvaluatorAdapter,
    DummyEvaluatorAdapter,
)
from famou_scientist.loop.evaluation.experiment import ExperimentRunner
from famou_scientist.loop.evaluation.experiment import NoopExperimentRunner
from famou_scientist.loop.facilities import (
    AdapterEvaluationFacility,
    RunnerBenchmarkFacility,
)
from famou_scientist.loop.domain.goal import GoalError, load_goal
from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.runtime.orchestrator import Orchestrator, OrchestratorConfig
from famou_scientist.loop.runtime import AsyncOrchestrator
from famou_scientist.loop.runtime.implement_actor import ImplementActorStore
from famou_scientist.loop.storage import CandidateStore, CrossTaskExpBank
from famou_scientist.loop.storage.state import ResearchState
from famou_scientist.loop.storage.queues import QueueSet
from famou_scientist.loop.storage.workspace import WorkspaceBusyError, WorkspaceRunLock, goal_workspace


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_terminal_run_writes_cross_task_experience_but_pause_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有真正结束的 Loop 才应写跨任务总结，暂停必须保留恢复语义。"""

    goal = load_goal(FIXTURES / "goals" / "dummy_algorithm_innovation.yaml")
    goal["benchmark_task"] = {
        "type": "naturebench",
        "task_id": "s41592-022-01709-7",
    }
    workspace = tmp_path / ".famou" / "naturebench-runs" / "run-1"
    orchestrator = Orchestrator(
        workspace,
        goal,
        workers=DummyWorkerSet(),
        evaluator=DummyEvaluatorAdapter(),
        config=OrchestratorConfig(min_ideas=0, max_ticks=1),
    )
    orchestrator.state_store.init(goal)
    attempt_id = orchestrator.expbank.create_attempt(
        idea={"id": "idea-1", "title": "稀疏矩阵索引修复"},
        lineage_id="lineage-1",
    )
    orchestrator.expbank.update_attempt(
        attempt_id,
        status="scored",
        score=0.25,
        evaluation={"valid": True, "metrics": {"aggregate_improvement": 0.25}},
        conclusion="公开评测有效。",
    )

    def finish_run() -> dict:
        state = orchestrator.state_store.load()
        state["research_state"]["status"] = LoopStatus.Research.COMPLETED
        orchestrator.state_store.save(state)
        return state

    monkeypatch.setattr(orchestrator, "_recover_interrupted_items", lambda: None)
    monkeypatch.setattr(orchestrator, "_run_unlocked", finish_run)
    result = orchestrator.run()

    bank = CrossTaskExpBank.for_workspace(workspace)
    assert result["research_state"]["status"] == LoopStatus.Research.COMPLETED
    assert bank.records()[0]["domain"] == "cellular_omics"
    assert bank.records()[0]["best_attempt_id"] == attempt_id
    assert bank.records()[0]["source_run_dir"] == str(workspace.resolve())
    assert bank.records()[0]["task_output_dir"] == str(
        (workspace / "workspace" / "output").resolve()
    )
    outbox = workspace / "controller" / "cross_task_experience_record.json"
    assert outbox.is_file()
    assert json.loads(outbox.read_text(encoding="utf-8"))["task_id"] == (
        "s41592-022-01709-7"
    )

    paused = orchestrator.state_store.load()
    paused["research_state"]["status"] = LoopStatus.Research.PAUSED
    assert orchestrator.finalize_cross_task_experience(paused) is None
    assert len(bank.records()) == 1

    def fail_finalize(_state: dict) -> None:
        raise RuntimeError("broken cross-task index")

    completed = orchestrator.state_store.load()
    monkeypatch.setattr(
        orchestrator,
        "_finalize_cross_task_experience",
        fail_finalize,
    )
    marker = orchestrator.finalize_cross_task_experience(completed)
    assert marker is not None
    assert marker["status"] == "failed"
    assert completed["research_state"]["status"] == LoopStatus.Research.COMPLETED


def test_research_budget_uses_continuous_wall_time_during_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并行 evaluator 不得暂停或延长 Idea/Implement 的研究墙钟。"""

    goal = _parallel_goal("evaluator-paused-budget")
    workspace = tmp_path / "workspace"
    state_store = ResearchState(workspace)
    state = state_store.init(goal)
    state["research_state"]["created_at"] = 1_000
    state_store.save(state)
    orchestrator = Orchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=DummyWorkerSet(),
        config=OrchestratorConfig(
            min_ideas=0,
            max_wall_time_hours=5 / 3_600,
        ),
    )
    clock = [5_000]
    monkeypatch.setattr(orchestrator_module, "now_ms", lambda: clock[0])

    state = state_store.load()
    assert orchestrator._remaining_wall_time_sec(state) == pytest.approx(1.0)
    assert orchestrator._wall_time_exhausted(state) is False
    clock[0] = 6_001
    assert orchestrator._wall_time_exhausted(state) is True


class _RankingWorkerSet(DummyWorkerSet):
    """记录时间感知排序调用，并按输入逆序返回严格排名。"""

    def __init__(self) -> None:
        """初始化调用证据。"""

        self.ranking_calls: list[dict[str, object]] = []

    def rank_ideas(
        self,
        goal: dict[str, object],
        ideas: list[dict[str, object]],
        runtime_context: dict[str, object],
    ) -> dict[str, object]:
        """返回用于验证队列优先级的逆序排名。"""

        self.ranking_calls.append(
            {
                "goal": goal,
                "ideas": ideas,
                "runtime_context": runtime_context,
            }
        )
        return {
            "ranking": [
                {
                    "queue_item_id": idea["queue_item_id"],
                    "idea_id": idea["idea_id"],
                    "rank": rank,
                    "reason": "逆序测试",
                    "estimated_minutes": 10,
                    "scores": {
                        "score_potential": 5,
                        "feasibility": 4,
                        "time_fit": 5,
                        "resource_fit": 5,
                    },
                    "risks": [],
                }
                for rank, idea in enumerate(reversed(ideas), start=1)
            ]
        }


def test_loop_dummy_run_and_status(tmp_path: Path):
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path),
        "--max-ticks",
        "5",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "dummy_algorithm_innovation"
    assert (ws / "research_state.yaml").exists()
    assert (ws / "artifacts" / "artifact_index.jsonl").exists()
    assert (ws / "artifacts" / "decision_log.jsonl").exists()

    state = ResearchState(ws).load()["research_state"]
    assert state["status"] == "completed"
    queues = QueueSet(ws).summary()
    assert queues["ideaspark"]["finished"] >= 1
    assert queues["evaluation_queue"]["finished"] >= 1
    assert queues["analyze_spark"]["finished"] >= 1
    assert any(branch["status"] == "paper_candidate" for branch in state["branches"])
    reusable = (ws / "shared_experience_pool" / "reusable_artifacts.jsonl").read_text(
        encoding="utf-8"
    )
    assert "promoted" in reusable
    assert "branch" in reusable

    rc = cli.main(["status", "--goal-id", "dummy_algorithm_innovation", "--root", str(tmp_path)])
    assert rc == 0


def test_loop_async_research_skips_idea_gate_by_default(tmp_path: Path):
    """默认直通 Idea 仍应由异步 Implement/Evaluation 流水线正常消费。"""

    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    rc = cli.main(
        [
            "run",
            "--goal-file",
            str(goal_file),
            "--root",
            str(tmp_path),
            "--max-ticks",
            "5",
            "--async-pipeline",
            "--reinit",
        ]
    )

    assert rc == 0
    workspace = tmp_path / "dummy_algorithm_innovation"
    state = ResearchState(workspace).load()["research_state"]
    assert state["runtime_limits"]["idea_gate_enabled"] is False
    summary = QueueSet(workspace).summary()
    assert summary["ideaspark"]["finished"] >= 1
    assert summary["evaluation_queue"]["finished"] >= 1
    types = [item["type"] for item in _artifact_records(workspace)]
    assert "idea_review" not in types
    decisions = (workspace / "artifacts" / "decision_log.jsonl").read_text(
        encoding="utf-8"
    )
    assert "enqueue_without_gate" in decisions


def test_time_aware_idea_ranking_reorders_only_unimplemented_ideas(
    tmp_path: Path,
):
    """进入冲刺窗口后应调用 Judge，且不改变 continuation 的更高优先级。"""

    goal = {
        "goal_id": "rank-test",
        "goal": {"id": "rank-test", "name": "rank-test"},
        "workflow": {"type": "benchmark_managed"},
        "objective_brief": {"primary_goal": "提高正式 benchmark 分数"},
        "benchmark_task": {"type": "test", "task_id": "rank-test"},
        "benchmarks": [
            {
                "name": "rank-test",
                "official_metric": {
                    "name": "accuracy",
                    "direction": "higher_is_better",
                },
            }
        ],
        "constraints": {"max_wall_time_hours": 4},
        "infra": {
            "pipeline": "async",
            "resources": {
                "available_cpu": 30,
                "available_gpu": 0,
                "available_memory_gib": 128,
            },
        },
    }
    state_store = ResearchState(tmp_path)
    state = state_store.init(goal)
    # 让 4 小时预算只剩约 30 分钟，确保进入 1 小时冲刺窗口。
    state["research_state"]["created_at"] = int(time.time() * 1000) - 12_600_000
    state_store.save(state)
    workers = _RankingWorkerSet()
    orchestrator = AsyncOrchestrator(
        tmp_path,
        goal,
        workers=workers,
        evaluator=DummyEvaluatorAdapter(),
        experiment_runner=NoopExperimentRunner(tmp_path),
        config=OrchestratorConfig(
            max_wall_time_hours=4,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
            idea_queue_high_watermark=3,
            evaluation_queue_capacity=3,
            time_aware_idea_ranking_enabled=True,
            idea_rank_trigger_remaining_sec=3_600,
            # 本例只验证排序逻辑本身，放开默认的三条门槛。
            idea_rank_min_items=2,
        ),
    )
    queue = QueueSet(tmp_path).benchmark_attempt
    first = queue.push(
        {"id": "idea-a", "title": "A", "mechanism": "A"},
        item_type="benchmark_attempt",
        priority=1,
    )
    second = queue.push(
        {"id": "idea-b", "title": "B", "mechanism": "B"},
        item_type="benchmark_attempt",
        priority=1,
    )
    continuation = queue.push(
        {
            "id": "repair-a",
            "continuation_reason": "run_failed",
            "actor_id": "actor-a",
        },
        item_type="actor_continuation",
        priority=3,
    )

    changed = orchestrator._maybe_rank_queued_ideas(state_store.load())

    assert changed is True
    assert len(workers.ranking_calls) == 1
    runtime_context = workers.ranking_calls[0]["runtime_context"]
    assert runtime_context["resources"]["available_cpu"] == 30
    ordered = queue.list(LoopStatus.Queue.QUEUED)
    ranked_ids = [
        idea["queue_item_id"]
        for idea in reversed(workers.ranking_calls[0]["ideas"])
    ]
    assert [item["id"] for item in ordered] == [
        continuation["id"],
        *ranked_ids,
    ]
    assert ordered[1]["time_aware_rank"]["rank"] == 1
    # 同一冲刺窗口只调用一次 Judge，不因每个调度 tick 重复调用。
    assert orchestrator._maybe_rank_queued_ideas(state_store.load()) is False
    assert len(workers.ranking_calls) == 1

    eval_item = QueueSet(tmp_path).evaluation.push(
        {"id": "evaluated-branch"},
        item_type="evaluation",
    )
    QueueSet(tmp_path).evaluation.update(
        eval_item,
        status=LoopStatus.Queue.FINISHED,
    )
    # 新的评测事实不会触发第二次排序；冲刺时间应留给 Implement/Evaluator。
    assert orchestrator._maybe_rank_queued_ideas(state_store.load()) is False
    assert len(workers.ranking_calls) == 1


def test_loop_status_json_includes_runtime_and_evidence_summary(tmp_path: Path, capsys):
    import json

    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path),
        "--max-ticks",
        "5",
        "--max-parallel-implementations",
        "2",
        "--reinit",
    ])
    assert rc == 0

    capsys.readouterr()
    rc = cli.main([
        "status",
        "--goal-id",
        "dummy_algorithm_innovation",
        "--root",
        str(tmp_path),
        "--json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    overview = json.loads(out)
    assert overview["goal_id"] == "dummy_algorithm_innovation"
    assert overview["runtime_limits"]["max_parallel_implementations"] == 2
    assert overview["queue_totals"]["finished"] >= 1
    assert overview["branches"]["total"] >= 1
    assert overview["artifacts"]["by_type"]["decision"] >= 1
    assert overview["recent_decisions"]


def test_loop_legacy_mode_flags(tmp_path: Path):
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    rc = cli.run_from_legacy_flags([
        "--mode",
        "e2e",  # 旧名称仅用于验证向后兼容。
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path),
        "--max-ticks",
        "1",
    ])
    assert rc == 0
    assert (tmp_path / "dummy_algorithm_innovation" / "research_state.yaml").exists()


@pytest.mark.parametrize(
    "prefix",
    [
        ["loop", "run"],
        ["--mode", "loop"],
        ["e2e", "run"],
    ],
)
def test_top_level_loop_entrypoints(tmp_path: Path, prefix: list[str]):
    """验证正式 Loop 入口以及旧 e2e 子命令兼容入口。"""
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / str(len(list(tmp_path.iterdir())))
    rc = cmdline.main([
        *prefix,
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--fresh",
    ])
    assert rc == 0
    assert (root / "dummy_algorithm_innovation" / "research_state.yaml").is_file()


def test_loop_resume_reinit_state_and_fresh_semantics(tmp_path: Path, capsys):
    import json

    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    goal_id = "dummy_algorithm_innovation"

    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--fresh",
    ])
    assert rc == 0
    ws = root / goal_id
    sentinel = ws / "artifacts" / "sentinel.json"
    sentinel.write_text('{"old": true}', encoding="utf-8")
    QueueSet(ws).ideaspark.push(
        {"id": "manual-idea", "title": "Manual", "mechanism": "test"},
        item_type="idea",
    )

    # Default run resumes and keeps durable queues/artifacts.
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
    ])
    assert rc == 0
    assert sentinel.exists()
    assert QueueSet(ws).summary()["ideaspark"]["queued"] == 1


    before_state = ResearchState(ws).load()["research_state"]
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--reinit-state",
    ])
    assert rc == 0
    assert "reinitialized research_state.yaml only" in capsys.readouterr().err
    after_state = ResearchState(ws).load()["research_state"]
    assert after_state["created_at"] >= before_state["created_at"]
    assert sentinel.exists()
    assert QueueSet(ws).summary()["ideaspark"]["queued"] == 1

    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--fresh",
    ])
    assert rc == 0
    assert not sentinel.exists()
    assert QueueSet(ws).summary()["ideaspark"]["queued"] == 0
    assert json.loads((ws / "research_state.yaml").read_text(encoding="utf-8"))[
        "research_state"
    ]["goal_id"] == goal_id


def test_task_resume_reopens_all_durable_work_in_same_workspace(tmp_path: Path):
    """任务级 resume 必须重新打开 Idea、Implement 和 Evaluation 消费链。"""
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    assert cli.main(
        [
            "run", "--goal-file", str(goal_file), "--root", str(root),
            "--max-ticks", "0", "--fresh",
        ]
    ) == 0
    ws = root / "dummy_algorithm_innovation"
    queues = QueueSet(ws)
    idea = queues.ideaspark.push(
        {"id": "resume-idea", "title": "resume", "mechanism": "test"},
        item_type="idea",
    )
    continuation = queues.benchmark_attempt.push(
        {"id": "resume-continuation", "actor_id": "actor-resume"},
        item_type="actor_continuation",
    )
    evaluation = queues.evaluation.push(
        {"id": "resume-candidate", "candidate_id": "candidate-resume"},
        item_type="branch",
    )
    queues.evaluation.mark_not_executed(
        reason="research_wall_time_budget_exhausted",
    )
    state_store = ResearchState(ws)
    state = state_store.load()
    state["research_state"]["status"] = LoopStatus.Research.STOPPED
    state["research_state"]["termination_reason"] = "wall_time_budget_exhausted"
    state_store.save(state)

    assert cli.main(
        ["resume", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)]
    ) == 0
    resumed = state_store.load()["research_state"]
    assert resumed["status"] == LoopStatus.Research.RUNNING
    assert resumed["termination_reason"] is None
    assert queues.ideaspark.get(idea["id"])["status"] == LoopStatus.Queue.QUEUED
    assert queues.benchmark_attempt.get(continuation["id"])["status"] == LoopStatus.Queue.QUEUED
    assert queues.evaluation.get(evaluation["id"])["status"] == LoopStatus.Queue.QUEUED
    assert resumed["evaluator_budget"]["used_submissions"] == 0


def test_master_stop_cancels_unfinished_work_and_resume_does_not_revive(
    tmp_path: Path,
):
    """Master stop 将 Idea、Implement、Evaluation 统一置为不可恢复终态。"""
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    assert cli.main(
        ["run", "--goal-file", str(goal_file), "--root", str(root), "--max-ticks", "0", "--fresh"]
    ) == 0
    ws = root / "dummy_algorithm_innovation"
    queues = QueueSet(ws)
    actor_store = ImplementActorStore(ws)
    actor = actor_store.create(
        {"id": "stop-idea", "title": "stop idea"},
        max_lifetime_sec=60,
        max_turns=2,
        max_run_attempts=2,
        max_official_evaluations=2,
        max_repairs_per_revision=1,
    )
    worktree = ws / "stop-worktree"
    worktree.mkdir()
    (worktree / "run.py").write_text("print('stop')\n", encoding="utf-8")
    candidate_store = CandidateStore(ws)
    candidate = candidate_store.create(
        {
            "id": actor["branch_id"],
            "branch_id": actor["branch_id"],
            "actor_id": actor["actor_id"],
            "idea_id": "stop-idea",
            "worktree": str(worktree),
            "entrypoint": str(worktree / "run.py"),
        }
    )
    actor_store.register_candidate(
        str(actor["actor_id"]),
        str(candidate["candidate_id"]),
        attempt_id="0001",
    )
    idea = queues.ideaspark.push({"id": "stop-idea"}, item_type="idea")
    continuation = queues.benchmark_attempt.push(
        {
            "id": "stop-impl",
            "branch_id": actor["branch_id"],
            "actor_id": actor["actor_id"],
        },
        item_type="actor_continuation",
    )
    evaluation = queues.evaluation.push(
        {
            "id": "stop-eval",
            "branch_id": actor["branch_id"],
            "actor_id": actor["actor_id"],
            "candidate_id": candidate["candidate_id"],
        },
        item_type="branch",
    )
    state_store = ResearchState(ws)
    state = state_store.load()
    state["research_state"]["branches"] = [
        {
            "branch_id": actor["branch_id"],
            "idea_id": "stop-idea",
            "status": LoopStatus.Branch.EVALUATION_RUNNING,
        }
    ]
    state_store.save(state)

    assert cli.main(["stop", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)]) == 0
    assert (ws / "agent_control" / "research_stop_requested.json").is_file()
    assert queues.ideaspark.get(idea["id"])["status"] == LoopStatus.Queue.CANCELLED
    assert queues.benchmark_attempt.get(continuation["id"])["status"] == LoopStatus.Queue.CANCELLED
    assert queues.evaluation.get(evaluation["id"])["status"] == LoopStatus.Queue.CANCELLED
    assert candidate_store.read(candidate["candidate_id"])["status"] == LoopStatus.Candidate.CANCELLED
    stopped_actor = actor_store.read(actor["actor_id"])
    assert stopped_actor["status"] == LoopStatus.Actor.CANCELLED
    assert stopped_actor["pending_candidates"] == []
    assert ResearchState(ws).load()["research_state"]["branches"][0][
        "status"
    ] == LoopStatus.Branch.CANCELLED

    assert cli.main(["resume", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)]) == 0
    state = ResearchState(ws).load()["research_state"]
    assert state["status"] == LoopStatus.Research.STOPPED
    assert queues.ideaspark.get(idea["id"])["status"] == LoopStatus.Queue.CANCELLED
    assert queues.benchmark_attempt.get(continuation["id"])["status"] == LoopStatus.Queue.CANCELLED
    assert queues.evaluation.get(evaluation["id"])["status"] == LoopStatus.Queue.CANCELLED
    assert candidate_store.read(candidate["candidate_id"])["status"] == LoopStatus.Candidate.CANCELLED
    assert actor_store.read(actor["actor_id"])["status"] == LoopStatus.Actor.CANCELLED


def test_loop_deprecated_reinit_alias_preserves_artifacts(tmp_path: Path, capsys):
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--fresh",
    ])
    assert rc == 0
    ws = root / "dummy_algorithm_innovation"
    sentinel = ws / "artifacts" / "legacy-reinit-sentinel.json"
    sentinel.write_text("{}", encoding="utf-8")

    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--reinit",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "--reinit is deprecated" in err
    assert "reinitialized research_state.yaml only" in err
    assert sentinel.exists()


def test_loop_fresh_rejects_busy_workspace(tmp_path: Path):
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(root),
        "--max-ticks",
        "0",
        "--fresh",
    ])
    assert rc == 0
    ws = root / "dummy_algorithm_innovation"
    lock = WorkspaceRunLock(ws)
    lock.acquire()
    try:
        rc = cli.main([
            "run",
            "--goal-file",
            str(goal_file),
            "--root",
            str(root),
            "--max-ticks",
            "0",
            "--fresh",
        ])
        assert rc == 3
        assert ws.exists()
    finally:
        lock.release()


def test_loop_cli_async_pipeline(tmp_path: Path):
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    rc = cli.main(
        [
            "run",
            "--goal-file",
            str(goal_file),
            "--root",
            str(tmp_path),
            "--max-ticks",
            "5",
            "--async-pipeline",
            "--reinit",
        ]
    )
    assert rc == 0
    state = ResearchState(tmp_path / "dummy_algorithm_innovation").load()
    assert state["research_state"]["status"] == "completed"


def _artifact_records(ws: Path):
    import json
    path = ws / "artifacts" / "artifact_index.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_loop_command_evaluator_official_budget(tmp_path: Path):
    goal_file = FIXTURES / "goals" / "command_evaluator_algorithm_innovation.yaml"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path),
        "--max-ticks",
        "5",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "command_evaluator_algorithm_innovation"
    state = ResearchState(ws).load()["research_state"]
    assert state["status"] == "completed"
    assert state["evaluator_budget"]["used_submissions"] == 1
    assert state["leaderboard"]["metric"] == "accuracy"
    assert state["leaderboard"]["best_value"] == 0.812
    assert state["leaderboard"]["source"] == "official"

    records = _artifact_records(ws)
    types = [r["type"] for r in records]
    assert "public_eval" in types
    assert "official_eval" in types

    official_paths = [ws / r["path"] for r in records if r["type"] == "official_eval"]
    assert official_paths
    import json
    official = json.loads(official_paths[0].read_text(encoding="utf-8"))
    assert official["source"] == "official_evaluator"
    assert official["official_metrics"]["accuracy"] == 0.812
    assert official["valid"] is True


def test_loop_command_evaluator_budget_zero_skips_official(tmp_path: Path):
    import json
    src = FIXTURES / "goals" / "command_evaluator_algorithm_innovation.yaml"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["goal"]["id"] = "command_evaluator_budget_zero"
    data["goal"]["name"] = "command_evaluator_budget_zero"
    data["constraints"]["max_evaluator_submissions"] = 0
    goal_file = tmp_path / "goal.json"
    goal_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path / "root"),
        "--max-ticks",
        "5",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "root" / "command_evaluator_budget_zero"
    state = ResearchState(ws).load()["research_state"]
    assert state["evaluator_budget"]["used_submissions"] == 0
    types = [r["type"] for r in _artifact_records(ws)]
    assert "public_eval" in types
    assert "official_eval" not in types


def test_loop_command_experiment_runner_success(tmp_path: Path):
    import json
    goal_file = FIXTURES / "goals" / "command_experiment_algorithm_innovation.yaml"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path),
        "--max-ticks",
        "5",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "command_experiment_algorithm_innovation"
    state = ResearchState(ws).load()["research_state"]
    assert state["status"] == "completed"
    records = _artifact_records(ws)
    assert "experiment_run" in [r["type"] for r in records]
    run_path = next(ws / r["path"] for r in records if r["type"] == "experiment_run")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["source"] == "command_experiment_runner"
    assert run["valid"] is True
    assert run["artifact"].endswith("trained_submission.json")
    assert Path(run["artifact"]).exists()
    assert Path(run["log_path"]).exists()

    official_path = next(ws / r["path"] for r in records if r["type"] == "official_eval")
    official = json.loads(official_path.read_text(encoding="utf-8"))
    assert official["official_metrics"]["accuracy"] == 0.812


def test_loop_command_experiment_runner_failure_archives(tmp_path: Path):
    import json
    src = FIXTURES / "goals" / "command_experiment_algorithm_innovation.yaml"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["goal"]["id"] = "command_experiment_failure"
    data["goal"]["name"] = "command_experiment_failure"
    data["experiment_runner"]["cmd"] = "python ../experiments/fake_train.py --fail --input {artifact} --output {run_dir}/trained_submission.json"
    goal_file = tmp_path / "goal.json"
    goal_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path / "root"),
        "--max-ticks",
        "5",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "root" / "command_experiment_failure"
    records = _artifact_records(ws)
    types = [r["type"] for r in records]
    assert "experiment_run" in types
    assert "public_eval" not in types
    assert "official_eval" not in types
    run_path = next(ws / r["path"] for r in records if r["type"] == "experiment_run")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["valid"] is False
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "experiment runner failed" in decisions


def test_loop_prompt_worker_command_llm_success(tmp_path: Path):
    import json
    goal_file = FIXTURES / "goals" / "prompt_worker_algorithm_innovation.yaml"
    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path),
        "--max-ticks",
        "5",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "prompt_worker_algorithm_innovation"
    state = ResearchState(ws).load()["research_state"]
    assert state["status"] == "completed"
    records = _artifact_records(ws)
    types = [r["type"] for r in records]
    assert "worker_call" in types
    assert "idea" in types
    assert "idea_review" in types
    assert "method_spec" in types
    assert "code_patch" in types
    assert "experiment_run" in types
    assert "official_eval" in types
    worker_paths = [ws / r["path"] for r in records if r["type"] == "worker_call"]
    worker_calls = [json.loads(p.read_text(encoding="utf-8")) for p in worker_paths]
    assert any(c.get("task") == "idea_generator" and c.get("valid") is True for c in worker_calls)
    assert any(c.get("task") == "idea_gate" and c.get("valid") is True for c in worker_calls)
    assert any(c.get("task") == "method_designer" and c.get("valid") is True for c in worker_calls)
    run_path = next(ws / r["path"] for r in records if r["type"] == "experiment_run")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["entrypoint"].endswith("method.py")
    assert Path(run["entrypoint"]).exists()
    assert Path(run["artifact"]).exists()
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "reject_idea" in decisions
    assert "accept_to_ideaspark" in decisions


def test_prompt_worker_method_designer_rejects_path_traversal(tmp_path: Path):
    class _MaliciousMethodLLM:
        def complete_json(self, task, prompt, context):  # noqa: ARG002
            assert task == "method_designer"
            return {
                "entrypoint": "method.py",
                "files": [
                    {"path": "../escape.py", "content": "raise RuntimeError('escape')"}
                ],
            }

    worker = PromptWorkerSet(
        {"goal": {"id": "path_safety", "name": "path_safety"}},
        tmp_path,
        llm=_MaliciousMethodLLM(),
    )
    branch = worker.implement(
        {"id": "idea_1", "title": "safe title", "mechanism": "safe mechanism"},
        tmp_path,
    )
    assert branch["status"] == "implementation_failed"
    assert branch["valid"] is False
    assert not list(tmp_path.rglob("escape.py"))


def test_loop_prompt_worker_invalid_json_fail_closed(tmp_path: Path):
    import json
    src = FIXTURES / "goals" / "prompt_worker_algorithm_innovation.yaml"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["goal"]["id"] = "prompt_worker_invalid_json"
    data["goal"]["name"] = "prompt_worker_invalid_json"
    data["workers"]["llm"]["cmd"] = "python ../llm/fake_loop_llm.py --invalid --input {input} --output {output}"
    goal_file = tmp_path / "goal.json"
    goal_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    rc = cli.main([
        "run",
        "--goal-file",
        str(goal_file),
        "--root",
        str(tmp_path / "root"),
        "--max-ticks",
        "1",
        "--reinit",
    ])
    assert rc == 0
    ws = tmp_path / "root" / "prompt_worker_invalid_json"
    state = ResearchState(ws).load()["research_state"]
    assert state["status"] == "running"
    queues = QueueSet(ws).summary()
    assert queues["ideaspark"]["queued"] == 0
    assert queues["evaluation_queue"]["queued"] == 0
    records = _artifact_records(ws)
    worker_paths = [ws / r["path"] for r in records if r["type"] == "worker_call"]
    assert worker_paths
    worker_calls = [json.loads(p.read_text(encoding="utf-8")) for p in worker_paths]
    assert any(c.get("valid") is False for c in worker_calls)


def test_loop_master_bridge_goal_patch_and_summary(tmp_path: Path):
    import json
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    # One tick initializes state and creates workspace; reinit ensures deterministic.
    rc = cli.main(["run", "--goal-file", str(goal_file), "--root", str(root), "--max-ticks", "1", "--reinit"])
    assert rc == 0
    ws = root / "dummy_algorithm_innovation"

    patch = {
        "reason": "user_feedback",
        "changes": {
            "objective_brief": {
                "preference_description": "用户现在更强调速度和可解释性。",
                "reject_examples": ["纯 ensemble 刷分"]
            },
            "constraints": {
                "ensemble_allowed": False,
                "max_evaluator_submissions": 3,
            }
        }
    }
    patch_file = tmp_path / "patch.json"
    patch_file.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["patch", "--goal-id", "dummy_algorithm_innovation", "--root", str(root), "--patch-file", str(patch_file)])
    assert rc == 0

    # Resume from running state and apply patch with one tick.
    state_store = ResearchState(ws)
    state = state_store.load()
    state["research_state"]["status"] = "running"
    state_store.save(state)
    rc = cli.main(["run", "--goal-file", str(goal_file), "--root", str(root), "--max-ticks", "1"])
    assert rc == 0
    state = state_store.load()["research_state"]
    brief = state["goal"]["objective_brief"]
    assert brief["preference_description"] == "用户现在更强调速度和可解释性。"
    assert state["goal"]["constraints"]["ensemble_allowed"] is False
    assert state["evaluator_budget"]["max_submissions"] == 3
    assert state.get("goal_patch_history")
    assert not (ws / "control" / "goal_patch.json").exists()

    rc = cli.main(["summary", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)])
    assert rc == 0
    summary = (ws / "status_summary.md").read_text(encoding="utf-8")
    assert "Loop Status Summary" in summary
    assert "Recent Goal Patches" in summary


def test_loop_goal_patch_is_validated_and_research_goal_is_synced(tmp_path: Path):
    import json

    from famou_scientist.loop.runtime.master_bridge import MasterBridge

    goal = _parallel_goal("patch-validation")
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    workers = _CaptureGoalWorkers()
    orch = Orchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=workers,
        config=OrchestratorConfig(min_ideas=1, max_ticks=1),
    )
    bridge = MasterBridge(ws)

    with pytest.raises(GoalError):
        bridge.write_goal_patch({"goal": {"id": "../escape"}})

    bridge.write_goal_patch(
        {
            "reason": "user clarified objective",
            "objective_brief": {"primary_goal": "prefer interpretable mechanisms"},
        }
    )
    stored_patch = json.loads((ws / "control" / "goal_patch.json").read_text(encoding="utf-8"))
    assert stored_patch["changes"]["objective_brief"]["primary_goal"].startswith("prefer")

    assert orch.tick() is True
    assert workers.seen_goals
    assert (
        workers.seen_goals[0]["objective_brief"]["primary_goal"]
        == "prefer interpretable mechanisms"
    )
    assert ResearchState(ws).load()["research_state"]["goal"]["objective_brief"]["primary_goal"] == (
        "prefer interpretable mechanisms"
    )

    # Simulate a malformed patch written by an external Master process.  The
    # runtime rejects and consumes it instead of repeatedly applying it.
    (ws / "control" / "goal_patch.json").write_text(
        json.dumps({"changes": {"constraints": {"max_parallel_evaluations": 0}}}),
        encoding="utf-8",
    )
    assert orch.tick() is True
    state = ResearchState(ws).load()["research_state"]
    assert state["audit"]["goal_patch_rejections"]
    assert (ws / "control" / "rejected_goal_patches.jsonl").exists()
    assert not (ws / "control" / "goal_patch.json").exists()


def test_research_idea_gate_feedback_is_synchronous_and_persisted(tmp_path: Path):
    """后一 Idea 回合必须看到前一 Gate 反馈，且 rejected/revise 证据可检索。"""

    class ConversationalIdeaWorkers(_NoPromoteWorkers):
        """模拟同一 IdeaAgent 与 Gate 的两个同步回合。"""

        def __init__(self):
            """初始化调用计数和上下文快照。"""

            self.calls = 0
            self.contexts = []

        def generate_ideas(self, goal, experience):
            """第二回合基于上一轮 revise 反馈提交修订 Idea。"""

            del experience
            self.calls += 1
            self.contexts.append(goal)
            if self.calls == 1:
                return [
                    {
                        "id": "idea-v1",
                        "title": "Initial mechanism",
                        "mechanism": "a mechanism without an interpretation test",
                    }
                ]
            return [
                {
                    "id": "idea-v2",
                    "parent_idea_id": "idea-v1",
                    "relation": "derived_from",
                    "title": "Revised mechanism",
                    "mechanism": "the mechanism plus a fidelity validation plan",
                }
            ]

        def idea_gate(self, goal, idea, experience):
            """首轮要求修改，第二轮通过。"""

            del goal
            del experience
            if idea["id"] == "idea-v1":
                return {
                    "verdict": "revise",
                    "reasons": ["缺少可解释性证据计划"],
                    "criterion_results": [
                        {
                            "criterion": "interpretability",
                            "status": "fail",
                            "diagnosis_code": "interpretability_plan_missing",
                        }
                    ],
                    "actionable_revision": ["加入 fidelity 验证"],
                }
            return {"verdict": "pass", "reasons": ["修订满足 Goal Rubric"]}

    goal = {
        "goal_id": "idea-dialogue",
        "goal": {"id": "idea-dialogue", "name": "idea-dialogue"},
        "workflow": {"type": "research", "idea_gate": {"enabled": True}},
        "benchmarks": [{"name": "dummy"}],
    }
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    workers = ConversationalIdeaWorkers()
    orchestrator = Orchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=workers,
        config=OrchestratorConfig(
            max_ticks=2,
            idea_queue_high_watermark=1,
        ),
    )

    assert orchestrator.tick(run_implementations=False, run_evaluations=False)
    assert orchestrator.tick(run_implementations=False, run_evaluations=False)

    second_runtime = workers.contexts[1]["idea_runtime"]
    assert second_runtime["last_review"]["idea_id"] == "idea-v1"
    assert second_runtime["last_review"]["review"]["verdict"] == "revise"
    assert orchestrator.idea_graph.read("idea-v1")["status"] == "revision_requested"
    assert orchestrator.idea_graph.read("idea-v2")["status"] == "accepted"
    queued = QueueSet(workspace).ideaspark.list("queued")
    assert queued[0]["payload"]["parent_idea_id"] == "idea-v1"
    experience = (
        workspace / "shared_experience_pool" / "attempted_ideas.jsonl"
    ).read_text(encoding="utf-8")
    assert "interpretability_plan_missing" in experience


def test_research_idea_gate_is_disabled_by_default(tmp_path: Path):
    """未配置 Gate 时应保留 Idea 证据并直接进入 IdeaSpark。"""

    class DirectAdmissionWorkers(_NoPromoteWorkers):
        """生成一条 Idea，并确保默认路径不会调用 Judge。"""

        def generate_ideas(self, goal, experience):
            """返回一条满足 Idea schema 的候选。"""

            del goal, experience
            return [
                {
                    "id": "idea-direct",
                    "title": "Directly admitted mechanism",
                    "mechanism": "Trust the constrained IdeaAgent instruction.",
                }
            ]

        def idea_gate(self, goal, idea, experience):
            """默认关闭时不允许调度器误调用 Gate。"""

            del goal, idea, experience
            raise AssertionError("默认关闭时不应调用 Idea Gate")

    goal = {
        "goal_id": "idea-gate-off",
        "goal": {"id": "idea-gate-off", "name": "idea-gate-off"},
        "workflow": {"type": "research"},
        "benchmarks": [{"name": "dummy"}],
    }
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    orchestrator = Orchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=DirectAdmissionWorkers(),
        config=OrchestratorConfig(max_ticks=1, idea_queue_high_watermark=1),
    )

    assert orchestrator.tick(run_implementations=False, run_evaluations=False)
    assert orchestrator.idea_gate_enabled is False
    queued = QueueSet(workspace).ideaspark.list("queued")
    assert queued[0]["payload"]["id"] == "idea-direct"
    record = orchestrator.idea_graph.read("idea-direct")
    assert record["status"] == "accepted"
    assert record["reviews"] == []
    assert record["admission"]["mode"] == "gate_disabled"
    types = [item["type"] for item in _artifact_records(workspace)]
    assert "idea_review" not in types
    decisions = (workspace / "artifacts" / "decision_log.jsonl").read_text(
        encoding="utf-8"
    )
    assert "enqueue_without_gate" in decisions


def test_loop_master_bridge_pause_stop_and_clarifications(tmp_path: Path):
    from famou_scientist.loop.runtime.master_bridge import MasterBridge
    goal_file = FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"
    root = tmp_path / "root"
    rc = cli.main(["run", "--goal-file", str(goal_file), "--root", str(root), "--max-ticks", "1", "--reinit"])
    assert rc == 0
    ws = root / "dummy_algorithm_innovation"

    rc = cli.main(["pause", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)])
    assert rc == 0
    assert ResearchState(ws).load()["research_state"]["status"] == "paused"
    assert (ws / "status_summary.md").exists()

    rc = cli.main(["resume", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)])
    assert rc == 0
    assert not (ws / "control" / "pause").exists()

    MasterBridge(ws).request_clarification({"type": "preference_request", "branch_id": "b1", "question": "速度和分数哪个优先？"})
    rc = cli.main(["clarifications", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)])
    assert rc == 0
    rows = (ws / "control" / "clarification_request.jsonl").read_text(encoding="utf-8")
    assert "速度和分数哪个优先" in rows

    rc = cli.main(["stop", "--goal-id", "dummy_algorithm_innovation", "--root", str(root)])
    assert rc == 0
    assert ResearchState(ws).load()["research_state"]["status"] == "stopped"


def test_loop_export_evidence_bundle_and_report(tmp_path: Path):
    import json
    import zipfile
    goal_file = FIXTURES / "goals" / "prompt_worker_algorithm_innovation.yaml"
    root = tmp_path / "root"
    rc = cli.main(["run", "--goal-file", str(goal_file), "--root", str(root), "--max-ticks", "5", "--reinit"])
    assert rc == 0
    goal_id = "prompt_worker_algorithm_innovation"

    rc = cli.main(["export", "--goal-id", goal_id, "--root", str(root)])
    assert rc == 0
    ws = root / goal_id
    bundle = ws / "artifacts" / "evidence_bundle"
    assert (bundle / "manifest.json").exists()
    assert (bundle / "claim_evidence_map.json").exists()
    assert (bundle / "final_report.md").exists()
    assert (bundle / "evidence_bundle.zip").exists()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["goal_id"] == goal_id
    claim_map = json.loads((bundle / "claim_evidence_map.json").read_text(encoding="utf-8"))
    assert claim_map["claims"]
    assert "Claims and Evidence" in (bundle / "final_report.md").read_text(encoding="utf-8")
    with zipfile.ZipFile(bundle / "evidence_bundle.zip") as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "final_report.md" in names

    report_path = tmp_path / "final_report.md"
    rc = cli.main(["report", "--goal-id", goal_id, "--root", str(root), "--output", str(report_path)])
    assert rc == 0
    assert "Loop Final Report" in report_path.read_text(encoding="utf-8")


class _NoPromoteWorkers:
    """让并发测试只关注实验执行阶段。"""

    def generate_ideas(self, goal, experience):
        return []

    def idea_gate(self, goal, idea, experience):
        del goal
        return {"accept": False, "reasons": ["not used in this test"]}

    def implement(self, idea, workspace):
        raise AssertionError("implementation stage should not run in this test")

    def analyze_result(self, branch, results):
        return {
            "id": f"analysis-{branch['branch_id']}",
            "branch_id": branch["branch_id"],
            "promote": False,
            "retry": False,
            "reasons": ["test branch archived"],
        }

    def analyze_deep(self, branch):
        raise AssertionError("deep analysis stage should not run in this test")


class _CaptureGoalWorkers(_NoPromoteWorkers):
    def __init__(self):
        self.seen_goals = []

    def generate_ideas(self, goal, experience):
        self.seen_goals.append(goal)
        return []


class _ImplementingNoPromoteWorkers(_NoPromoteWorkers):
    def implement(self, idea, workspace):
        branch_id = f"branch-{idea['id']}"
        artifact = Path(workspace) / "inputs" / f"{branch_id}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}", encoding="utf-8")
        return {
            "id": branch_id,
            "branch_id": branch_id,
            "idea_id": idea["id"],
            "artifact": str(artifact),
        }


class _BenchmarkOnlyWorkers:
    """验证 benchmark 直通工作流只调用 Idea 与 Implement Agent。"""

    def __init__(self):
        self.idea_calls = 0

    def generate_ideas(self, goal, experience):
        self.idea_calls += 1
        return [
            {
                "id": f"idea-{self.idea_calls}",
                "title": f"benchmark idea {self.idea_calls}",
                "mechanism": "implement one concrete benchmark method",
            }
        ]

    def idea_gate(self, goal, idea, experience):
        del goal
        raise AssertionError("benchmark 工作流不应调用 Idea Gate")

    def implement(self, attempt, workspace):
        branch_id = f"branch-{attempt['attempt_number']}"
        artifact = Path(workspace) / "inputs" / f"{branch_id}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}", encoding="utf-8")
        return {
            "id": branch_id,
            "branch_id": branch_id,
            "idea_id": attempt["id"],
            "artifact": str(artifact),
            "status": "implemented",
        }

    def analyze_result(self, branch, results):
        raise AssertionError("benchmark 工作流不应调用 result analyst")

    def analyze_deep(self, branch):
        raise AssertionError("benchmark 工作流不应调用 deep analyzer")


class _TrackingImplementWorkers(_NoPromoteWorkers):
    def __init__(self, *, synchronize_first_batch: bool = False):
        self.lock = threading.Lock()
        self.first_batch_barrier = threading.Barrier(2) if synchronize_first_batch else None
        self.active = 0
        self.max_active = 0
        self.entered = 0
        self.calls: list[str] = []

    def implement(self, idea, workspace):
        idea_id = str(idea["id"])
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.entered += 1
            ordinal = self.entered
            self.calls.append(idea_id)
        if self.first_batch_barrier and ordinal <= 2:
            self.first_batch_barrier.wait(timeout=2)
        try:
            time.sleep(0.01)
            branch_id = f"branch-{idea_id}"
            artifact = Path(workspace) / "inputs" / f"{branch_id}.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}", encoding="utf-8")
            return {
                "id": branch_id,
                "branch_id": branch_id,
                "idea_id": idea_id,
                "artifact": str(artifact),
                "status": "implemented",
            }
        finally:
            with self.lock:
                self.active -= 1


class _DeadlineAwareImplementWorkers(_NoPromoteWorkers):
    """模拟在研究截止前持续运行、收到 Controller 信号后退出的 Agent。"""

    def __init__(self):
        self.started = threading.Event()
        self.saw_cancel_file = False

    def implement(self, idea, workspace):
        """等待截止文件，并返回仅用于验证证据归档的未完成分支。"""

        self.started.set()
        cancel_file = Path(workspace) / "agent_control" / "research_deadline_reached.json"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not cancel_file.is_file():
            time.sleep(0.01)
        self.saw_cancel_file = cancel_file.is_file()
        return {
            "id": f"branch-{idea['id']}",
            "branch_id": f"branch-{idea['id']}",
            "idea_id": idea["id"],
            "status": "implementation_failed",
            "error": "controller cancelled at research deadline",
        }


class _RejectingArtifactEvaluator(DummyEvaluatorAdapter):
    def validate_artifact(self, artifact_path):
        return {
            "valid": False,
            "artifact": artifact_path,
            "reason": "synthetic evaluator rejection",
        }

    def run_public_eval(self, artifact_path):
        raise AssertionError("invalid artifacts must not reach public evaluation")


class _InvalidPublicEvaluator(DummyEvaluatorAdapter):
    def run_public_eval(self, artifact_path):
        return {
            "valid": False,
            "source": "public_eval",
            "artifact": artifact_path,
            "error": "synthetic public evaluator failure",
        }


class _InvalidOfficialEvaluator(DummyEvaluatorAdapter):
    def run_official_eval(self, artifact_path):
        return {
            "valid": False,
            "source": "official_evaluator",
            "artifact": artifact_path,
            "error": "synthetic official evaluator failure",
        }


class _LeakyEvaluator(DummyEvaluatorAdapter):
    def run_public_eval(self, artifact_path):
        return {
            "valid": True,
            "source": "public_eval",
            "artifact": artifact_path,
            "metrics": {"accuracy": 0.83, "per_example_error": [0, 1]},
            "diagnostics_public": {"format_check": "passed"},
            "parsed": {"hidden_labels": ["secret"]},
            "stdout": "secret raw output",
        }

    def run_official_eval(self, artifact_path):
        return {
            "valid": True,
            "source": "official_evaluator",
            "artifact": artifact_path,
            "official_metrics": {"accuracy": 0.84},
            "parsed": {"hidden_labels": ["secret"]},
            "stderr": "secret official output",
        }


class _CaptureEvaluatorViewWorkers(_NoPromoteWorkers):
    def __init__(self):
        self.results = None

    def analyze_result(self, branch, results):
        self.results = results
        return super().analyze_result(branch, results)


class _CaptureOfficialWorkers(_NoPromoteWorkers):
    def analyze_result(self, branch, results):
        assert results["official"] is None
        return super().analyze_result(branch, results)


class _RetryAnalysisWorkers(_NoPromoteWorkers):
    def analyze_result(self, branch, results):
        return {
            "id": f"analysis-{branch['branch_id']}",
            "branch_id": branch["branch_id"],
            "promote": False,
            "retry": True,
            "reasons": ["try a revised mechanism"],
            "revised_idea": {
                "title": "Revised mechanism",
                "mechanism": "Add a gated correction path.",
            },
        }

    def idea_gate(self, goal, idea, experience):
        del goal
        return {
            "id": f"review-{idea['id']}",
            "idea_id": idea["id"],
            "accept": True,
            "reasons": ["revised idea has a concrete mechanism"],
        }


class _TrackingExperimentRunner(ExperimentRunner):
    def __init__(
        self,
        *,
        failures: set[str] | None = None,
        fail_once: set[str] | None = None,
        synchronize_first_batch: bool = False,
    ):
        self.failures = failures or set()
        self.fail_once = fail_once or set()
        self.synchronize_first_batch = synchronize_first_batch
        self.lock = threading.Lock()
        self.first_batch_barrier = threading.Barrier(2) if synchronize_first_batch else None
        self.active = 0
        self.max_active = 0
        self.entered = 0
        self.calls: list[str] = []
        self.call_counts: dict[str, int] = {}

    def run(self, branch):
        branch_id = str(branch["branch_id"])
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.entered += 1
            ordinal = self.entered
            self.calls.append(branch_id)
            self.call_counts[branch_id] = self.call_counts.get(branch_id, 0) + 1
            branch_call_count = self.call_counts[branch_id]
        if self.first_batch_barrier and ordinal <= 2:
            self.first_batch_barrier.wait(timeout=2)
        try:
            time.sleep(0.01)
            if branch_id in self.failures or (branch_id in self.fail_once and branch_call_count == 1):
                raise RuntimeError(f"synthetic failure for {branch_id}")
            return {
                "id": f"run-{branch_id}",
                "branch_id": branch_id,
                "source": "tracking_test_runner",
                "valid": True,
                "artifact": branch["artifact"],
            }
        finally:
            with self.lock:
                self.active -= 1


class _BlockingExperimentRunner(ExperimentRunner):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, branch):
        self.started.set()
        assert self.release.wait(timeout=2), "test runner was not released"
        return {
            "id": f"run-{branch['branch_id']}",
            "branch_id": branch["branch_id"],
            "source": "blocking_test_runner",
            "valid": True,
            "artifact": branch["artifact"],
        }


def _parallel_goal(goal_id: str) -> dict:
    return {
        "goal_id": goal_id,
        "goal": {"id": goal_id, "name": goal_id},
        "benchmarks": [],
        "baselines": [],
        "objective_brief": {},
        "constraints": {"max_evaluator_submissions": 0},
        "outputs": {},
    }


def test_loop_benchmark_managed_uses_only_benchmark_evaluator(tmp_path: Path):
    """完整 benchmark 应绕过 Master 和所有额外智能体裁判。"""
    goal = {
        "goal_id": "benchmark-managed",
        "goal": {
            "id": "benchmark-managed",
            "name": "benchmark-managed",
        },
        "workflow": {"type": "benchmark_managed"},
        "benchmarks": [
            {
                "name": "dummy",
                "official_metric": {
                    "name": "accuracy",
                    "direction": "higher_is_better",
                },
                "hidden_test_access": "forbidden",
            }
        ],
        "baselines": [],
        "objective_brief": {},
        "constraints": {
            "max_benchmark_attempts": 1,
            "max_evaluator_submissions": 1,
        },
        "outputs": {},
    }
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    workers = _BenchmarkOnlyWorkers()
    evaluator = DummyEvaluatorAdapter(goal["benchmarks"][0])
    orch = Orchestrator(
        ws,
        goal,
        workers=workers,
        benchmark_facility=RunnerBenchmarkFacility(
            NoopExperimentRunner(ws), evaluator, task_id="benchmark-managed"
        ),
        evaluation_facility=AdapterEvaluationFacility(evaluator),
        config=OrchestratorConfig(max_ticks=2),
    )

    state = orch.run()["research_state"]

    assert orch.master_bridge is None
    assert workers.idea_calls == 1
    assert state["status"] == "completed"
    assert state["termination_reason"] == "benchmark_attempt_budget_exhausted"
    assert state["leaderboard"]["best_value"] == 0.79
    queues = QueueSet(ws).summary()
    assert queues["benchmark_attempt_queue"]["finished"] == 1
    assert queues["ideaspark"]["finished"] == 0
    assert queues["analyze_spark"]["finished"] == 0
    artifact_types = [record["type"] for record in _artifact_records(ws)]
    assert "benchmark_attempt" in artifact_types
    assert "official_eval" in artifact_types
    assert "idea_review" not in artifact_types
    assert "analysis_report" not in artifact_types
    assert "deep_analysis" not in artifact_types


def test_loop_async_benchmark_managed_iterates_without_judges(tmp_path: Path):
    """异步直通工作流应在尝试预算耗尽后自动收尾。"""
    goal = {
        "goal_id": "async-benchmark-managed",
        "goal": {
            "id": "async-benchmark-managed",
            "name": "async-benchmark-managed",
        },
        "workflow": {"type": "benchmark_managed"},
        "benchmarks": [
            {
                "name": "dummy",
                "official_metric": {
                    "name": "accuracy",
                    "direction": "higher_is_better",
                },
            }
        ],
        "baselines": [],
        "objective_brief": {},
        "constraints": {
            "max_benchmark_attempts": 2,
            "max_evaluator_submissions": 2,
        },
        "outputs": {},
    }
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    workers = _BenchmarkOnlyWorkers()
    evaluator = DummyEvaluatorAdapter(goal["benchmarks"][0])
    orch = AsyncOrchestrator(
        ws,
        goal,
        workers=workers,
        benchmark_facility=RunnerBenchmarkFacility(
            NoopExperimentRunner(ws), evaluator, task_id="async-benchmark-managed"
        ),
        evaluation_facility=AdapterEvaluationFacility(evaluator),
        config=OrchestratorConfig(
            max_ticks=20,
            interval_sec=0.001,
        ),
    )

    state = orch.run()["research_state"]

    assert state["status"] == "completed"
    assert workers.idea_calls == 2
    assert state["evaluator_budget"]["used_submissions"] == 2
    queues = QueueSet(ws).summary()
    assert queues["benchmark_attempt_queue"]["finished"] == 2
    assert queues["evaluation_queue"]["finished"] == 2
    assert queues["analyze_spark"]["finished"] == 0


def test_async_benchmark_idea_and_implement_overlap_at_single_concurrency(
    tmp_path: Path,
):
    """Idea=1、Implement=1 时两个独立阶段仍应形成异步流水线。"""

    class OverlappingWorkers(_BenchmarkOnlyWorkers):
        """通过双向事件约束证明 Idea 与 Implement 同时在途。"""

        def __init__(self):
            """初始化阶段同步事件。"""
            super().__init__()
            self.implement_started = threading.Event()
            self.second_idea_started = threading.Event()

        def generate_ideas(self, goal, experience):
            """第二次 Idea 调用必须发生在第一次 Implement 尚未结束时。"""
            self.idea_calls += 1
            if self.idea_calls == 2:
                assert self.implement_started.wait(timeout=2)
                self.second_idea_started.set()
            return [
                {
                    "id": f"idea-{self.idea_calls}",
                    "title": f"overlap idea {self.idea_calls}",
                    "mechanism": "verify independent async stages",
                }
            ]

        def implement(self, attempt, workspace):
            """第一次 Implement 等到第二个 Idea 启动后才允许完成。"""
            if attempt["attempt_number"] == 1:
                self.implement_started.set()
                assert self.second_idea_started.wait(timeout=2)
            return super().implement(attempt, workspace)

    goal = {
        "goal_id": "async-idea-implement-overlap",
        "goal": {
            "id": "async-idea-implement-overlap",
            "name": "async-idea-implement-overlap",
        },
        "workflow": {"type": "benchmark_managed"},
        "benchmarks": [
            {
                "name": "dummy",
                "official_metric": {
                    "name": "accuracy",
                    "direction": "higher_is_better",
                },
            }
        ],
        "constraints": {
            "max_benchmark_attempts": 2,
            "max_evaluator_submissions": 2,
        },
    }
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    workers = OverlappingWorkers()
    evaluator = DummyEvaluatorAdapter(goal["benchmarks"][0])
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        workers=workers,
        benchmark_facility=RunnerBenchmarkFacility(
            NoopExperimentRunner(workspace),
            evaluator,
            task_id="async-idea-implement-overlap",
        ),
        evaluation_facility=AdapterEvaluationFacility(evaluator),
        config=OrchestratorConfig(
            max_ticks=30,
            interval_sec=0.001,
            max_parallel_ideas=1,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
        ),
    )

    state = orchestrator.run()["research_state"]

    assert workers.implement_started.is_set()
    assert workers.second_idea_started.is_set()
    assert workers.idea_calls == 2
    assert state["status"] == "completed"
    assert state["runtime_limits"]["max_parallel_ideas"] == 1
    assert state["runtime_limits"]["max_parallel_implementations"] == 1


def test_benchmark_validation_failure_is_redacted_in_expbank(tmp_path: Path):
    """提交校验失败时，ExpBank 只能保存 evaluator 的安全视图。"""

    class RejectingEvaluator(BenchmarkAdapter):
        def validate_artifact(self, artifact_path):
            return {
                "valid": False,
                "artifact": artifact_path,
                "error": "submission format rejected",
                "stdout": "SECRET_GROUND_TRUTH",
                "extra": {"hidden_labels": [1, 2, 3], "format_code": 7},
            }

        def run_public_eval(self, artifact_path):
            raise AssertionError("invalid artifact must not reach public evaluator")

        def run_official_eval(self, artifact_path):
            raise AssertionError("invalid artifact must not reach official evaluator")

    goal = {
        "goal_id": "benchmark-validation-failure",
        "goal": {"id": "benchmark-validation-failure", "name": "failure"},
        "workflow": {"type": "benchmark_managed"},
        "benchmarks": [{"name": "dummy"}],
        "constraints": {
            "max_benchmark_attempts": 1,
            "max_evaluator_submissions": 1,
        },
    }
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    workers = _BenchmarkOnlyWorkers()
    evaluator = RejectingEvaluator()
    orchestrator = Orchestrator(
        workspace,
        goal,
        workers=workers,
        benchmark_facility=RunnerBenchmarkFacility(
            NoopExperimentRunner(workspace), evaluator, task_id="benchmark-validation-failure"
        ),
        evaluation_facility=AdapterEvaluationFacility(evaluator),
        config=OrchestratorConfig(max_ticks=2),
    )

    state = orchestrator.run()["research_state"]

    assert state["status"] == "completed"
    record = orchestrator.expbank.read_attempt("0001")
    assert record["status"] == "engineering_failed"
    assert record["evaluation"]["redacted_for_agent"] is True
    serialized = (workspace / "expbank" / "0001" / "record.json").read_text(
        encoding="utf-8"
    )
    assert "SECRET_GROUND_TRUTH" not in serialized
    assert "hidden_labels" not in serialized


def _seed_evaluation_queue(ws: Path, count: int) -> None:
    queue = QueueSet(ws).evaluation
    for index in range(count):
        branch_id = f"branch-{index}"
        artifact = ws / "inputs" / f"{branch_id}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}", encoding="utf-8")
        queue.push(
            {
                "branch_id": branch_id,
                "artifact": str(artifact),
                "idea_id": f"idea-{index}",
            },
            item_type="branch",
        )


def _parallel_orchestrator(
    tmp_path: Path,
    *,
    count: int,
    max_parallel: int,
    runner: ExperimentRunner,
    idea_gate_enabled: bool = False,
):
    goal = _parallel_goal(f"parallel-{count}-{max_parallel}")
    goal["workflow"] = {
        "type": "research",
        "idea_gate": {"enabled": idea_gate_enabled},
    }
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    _seed_evaluation_queue(ws, count)
    orch = Orchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=_NoPromoteWorkers(),
        experiment_runner=runner,
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=1,
            max_parallel_evaluations=max_parallel,
        ),
    )
    return orch, ws


def test_loop_experiment_runner_respects_parallel_limit(tmp_path: Path):
    runner = _TrackingExperimentRunner(synchronize_first_batch=True)
    orch, ws = _parallel_orchestrator(tmp_path, count=4, max_parallel=2, runner=runner)

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["finished"] == 2
    assert summary["queued"] == 2
    assert summary["running"] == 0
    assert runner.max_active == 2

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["finished"] == 4
    assert summary["queued"] == 0
    assert runner.max_active == 2
    assert len(runner.calls) == 4


def test_loop_async_pipeline_runs_bounded_producer_consumer(tmp_path: Path):
    goal = _parallel_goal("async-producer-consumer")
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    _seed_evaluation_queue(ws, count=4)
    runner = _TrackingExperimentRunner(synchronize_first_batch=True)
    orch = AsyncOrchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=_NoPromoteWorkers(),
        experiment_runner=runner,
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=5,
            interval_sec=0.01,
            max_parallel_evaluations=2,
        ),
    )

    state = orch.run()
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["finished"] == 4
    assert summary["queued"] == 0
    assert summary["running"] == 0
    assert runner.max_active == 2
    assert len(runner.calls) == 4
    assert state["research_state"]["current_phase"] == "idle"


def test_loop_async_pipeline_zero_ticks_does_not_start_work(tmp_path: Path):
    """验证异步流水线的零 tick 模式只初始化而不启动后台任务。"""
    goal = _parallel_goal("async-zero-ticks")
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    _seed_evaluation_queue(ws, count=1)
    runner = _TrackingExperimentRunner()
    orch = AsyncOrchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=_NoPromoteWorkers(),
        experiment_runner=runner,
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=0,
            max_parallel_evaluations=1,
        ),
    )

    orch.run()

    assert runner.calls == []
    assert QueueSet(ws).summary()["evaluation_queue"]["queued"] == 1


def test_async_wall_time_drains_evaluations_and_skips_unstarted_work(
    tmp_path: Path,
):
    """研究截止后只排空已有评测，不再启动尚未进入评测池的实现。"""

    goal = _parallel_goal("wall-time-evaluation-drain")
    goal["workflow"] = {"type": "benchmark_managed"}
    goal["benchmarks"] = [
        {
            "name": "dummy",
            "official_metric": {
                "name": "accuracy",
                "direction": "higher_is_better",
            },
        }
    ]
    ws = tmp_path / "workspace"
    state_store = ResearchState(ws)
    state = state_store.init(goal)
    state["research_state"]["created_at"] = 0
    state_store.save(state)
    QueueSet(ws).benchmark_attempt.push(
        {"id": "idea-unstarted", "title": "do not start"},
        item_type="benchmark_attempt",
    )
    _seed_evaluation_queue(ws, count=2)
    waiting_item = QueueSet(ws).evaluation.list(LoopStatus.Queue.QUEUED)[1]
    QueueSet(ws).evaluation.wait_for_resources(
        waiting_item,
        request={"cpu_cores": 1, "host_memory_gib": 1, "gpu": {}},
        broker_snapshot={},
    )
    runner = _TrackingExperimentRunner()
    workers = _TrackingImplementWorkers()
    orchestrator = AsyncOrchestrator(
        ws,
        goal,
        workers=workers,
        evaluator=DummyEvaluatorAdapter(goal["benchmarks"][0]),
        experiment_runner=runner,
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=10,
            interval_sec=0.01,
            max_wall_time_hours=0.001,
            max_parallel_implementations=1,
            max_parallel_evaluations=2,
        ),
    )

    final_state = orchestrator.run()["research_state"]
    summary = QueueSet(ws).summary()

    assert workers.calls == []
    assert summary["benchmark_attempt_queue"]["not_executed"] == 1
    assert summary["evaluation_queue"]["finished"] == 2
    assert summary["evaluation_queue"]["queued"] == 0
    assert summary["evaluation_queue"]["running"] == 0
    assert summary["evaluation_queue"]["waiting_resources"] == 0
    assert sorted(runner.calls) == ["branch-0", "branch-1"]
    assert final_state["shutdown"]["phase"] == "evaluation_drain_completed"
    assert len(final_state["shutdown"]["evaluation_item_ids_at_cutoff"]) == 2
    progress = final_state["shutdown"]["evaluation_drain_progress"]
    assert progress["total_at_cutoff"] == 2
    assert progress["finished"] == 2
    assert progress["queued"] == 0
    assert progress["waiting_resources"] == 0
    assert progress["running"] == 0
    assert progress["inflight"] == 0
    assert "evaluation drain completed" in (ws / "logs" / "orchestrator.log").read_text(
        encoding="utf-8"
    )
    assert (ws / "agent_control" / "research_deadline_reached.json").is_file()


def test_async_wall_time_cancels_running_implementation_without_failure(
    tmp_path: Path,
):
    """截止时尚未提交 Candidate 的运行中实现应归档为未执行。"""

    goal = _parallel_goal("wall-time-running-implementation")
    goal["workflow"] = {"type": "research"}
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    QueueSet(ws).ideaspark.push(
        {"id": "idea-running", "title": "running idea", "mechanism": "test"},
        item_type="idea",
    )
    workers = _DeadlineAwareImplementWorkers()
    orchestrator = AsyncOrchestrator(
        ws,
        goal,
        workers=workers,
        evaluator=DummyEvaluatorAdapter(),
        experiment_runner=_TrackingExperimentRunner(),
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=100,
            interval_sec=0.01,
            max_wall_time_hours=0.00003,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
        ),
    )

    state = orchestrator.run()["research_state"]
    queue = QueueSet(ws).summary()["ideaspark"]

    assert workers.started.is_set()
    assert workers.saw_cancel_file is True
    assert queue["not_executed"] == 1
    assert queue["failed"] == 0
    record = orchestrator.expbank.read_attempt("0001")
    assert record["status"] == "not_executed"
    assert "不形成方法或工程结论" in record["conclusion"]
    assert state["shutdown"]["phase"] == "evaluation_drain_completed"


def test_loop_async_pipeline_runs_bounded_implementations(tmp_path: Path):
    goal = _parallel_goal("async-implement-producer-consumer")
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    ideas = QueueSet(ws).ideaspark
    for index in range(4):
        ideas.push(
            {"id": f"idea-{index}", "title": f"idea-{index}", "mechanism": "test"},
            item_type="idea",
        )
    workers = _TrackingImplementWorkers(synchronize_first_batch=True)
    runner = _TrackingExperimentRunner()
    orch = AsyncOrchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=workers,
        experiment_runner=runner,
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=8,
            interval_sec=0.01,
            max_parallel_implementations=2,
            max_parallel_evaluations=2,
        ),
    )

    state = orch.run()
    summary = QueueSet(ws).summary()
    assert summary["ideaspark"]["finished"] == 4
    assert summary["ideaspark"]["running"] == 0
    assert summary["evaluation_queue"]["finished"] == 4
    assert workers.max_active == 2
    assert len(workers.calls) == 4
    assert state["research_state"]["runtime_limits"]["max_parallel_implementations"] == 2


def test_loop_parallel_batch_isolates_runner_failure(tmp_path: Path):
    runner = _TrackingExperimentRunner(failures={"branch-1"})
    orch, ws = _parallel_orchestrator(tmp_path, count=3, max_parallel=3, runner=runner)

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["finished"] == 2
    assert summary["failed"] == 1
    assert summary["queued"] == 0
    assert runner.max_active == 3

    records = _artifact_records(ws)
    run_records = [record for record in records if record["type"] == "experiment_run"]
    public_records = [record for record in records if record["type"] == "public_eval"]
    assert len(run_records) == 3
    assert len(public_records) == 2
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "synthetic failure for branch-1" in decisions


def test_loop_artifact_validation_fails_closed_before_public_eval(tmp_path: Path):
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    orch.evaluator = _RejectingArtifactEvaluator()

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["failed"] == 1
    assert summary["finished"] == 0
    types = [record["type"] for record in _artifact_records(ws)]
    assert "artifact_validation" in types
    assert "public_eval" not in types
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "synthetic evaluator rejection" in decisions


def test_loop_invalid_public_eval_fails_closed_before_analysis(tmp_path: Path):
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    orch.evaluator = _InvalidPublicEvaluator()

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["failed"] == 1
    assert summary["finished"] == 0
    types = [record["type"] for record in _artifact_records(ws)]
    assert "artifact_validation" in types
    assert "public_eval" in types
    assert "analysis_report" not in types
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "synthetic public evaluator failure" in decisions


def test_loop_invalid_official_eval_is_not_passed_to_analysis(tmp_path: Path):
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    orch.evaluator = _InvalidOfficialEvaluator()
    orch.workers = _CaptureOfficialWorkers()
    state = ResearchState(ws).load()
    state["research_state"]["evaluator_budget"]["max_submissions"] = 1
    ResearchState(ws).save(state)

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["finished"] == 0
    assert summary["failed"] == 1
    state = ResearchState(ws).load()["research_state"]
    assert state["evaluator_budget"]["used_submissions"] == 1
    types = [record["type"] for record in _artifact_records(ws)]
    assert "public_eval" in types
    assert "official_eval" in types
    assert "analysis_report" not in types
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "official_eval_invalid" in decisions


def test_loop_evaluator_agent_view_redacts_raw_and_hidden_fields(tmp_path: Path):
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    evaluator = _LeakyEvaluator()
    workers = _CaptureEvaluatorViewWorkers()
    orch.evaluator = evaluator
    orch.workers = workers
    state = ResearchState(ws).load()
    state["research_state"]["evaluator_budget"]["max_submissions"] = 1
    ResearchState(ws).save(state)

    assert orch.tick() is True
    assert workers.results is not None
    public = workers.results["public"]
    official = workers.results["official"]
    assert public["metrics"]["accuracy"] == 0.83
    assert official["official_metrics"]["accuracy"] == 0.84
    assert "parsed" not in public
    assert "stdout" not in public
    assert "hidden_labels" not in official
    assert "per_example_error" not in public["metrics"]
    assert public["redacted_for_agent"] is True
    assert official["redacted_for_agent"] is True

    types = [record["type"] for record in _artifact_records(ws)]
    assert types.count("evaluator_agent_view") == 2


def test_loop_official_evaluator_timeout_is_recorded_and_charged(tmp_path: Path):
    public_script = tmp_path / "public_eval.py"
    public_script.write_text(
        "import json\n"
        "print(json.dumps({'valid': True, 'metrics': {'accuracy': 0.7}}))\n",
        encoding="utf-8",
    )
    official_script = tmp_path / "official_eval.py"
    official_script.write_text(
        "import time\n"
        "time.sleep(2)\n",
        encoding="utf-8",
    )
    benchmark = {
        "name": "timeout_bench",
        "adapter": {
            "type": "command",
            "public_eval_cmd": "python public_eval.py",
            "official_eval_cmd": "python official_eval.py",
            "timeout_sec": 1,
        },
    }
    evaluator = CommandEvaluatorAdapter(benchmark, cwd=tmp_path)
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path / "run", count=1, max_parallel=1, runner=runner)
    orch.evaluator = evaluator
    orch.workers = _CaptureOfficialWorkers()
    state = ResearchState(ws).load()
    state["research_state"]["evaluator_budget"]["max_submissions"] = 1
    ResearchState(ws).save(state)

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["finished"] == 0
    assert summary["failed"] == 1
    state = ResearchState(ws).load()["research_state"]
    assert state["evaluator_budget"]["used_submissions"] == 1

    import json

    records = _artifact_records(ws)
    official_record = next(record for record in records if record["type"] == "official_eval")
    official = json.loads((ws / official_record["path"]).read_text(encoding="utf-8"))
    assert official["valid"] is False
    assert official["timed_out"] is True
    assert official["error"] == "evaluator timeout"
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "official_eval_invalid" in decisions


def test_command_evaluator_preserves_process_output_and_extra(tmp_path: Path):
    evaluator_script = tmp_path / "evaluator.py"
    evaluator_script.write_text(
        "import json\n"
        "import sys\n"
        "print('public evaluator progress: loaded split')\n"
        "print('public evaluator warning', file=sys.stderr)\n"
        "print(json.dumps({\n"
        "    'valid': True,\n"
        "    'metrics': {'accuracy': 0.912},\n"
        "    'diagnostics_public': {'format_check': 'passed'},\n"
        "    'extra': {'num_batches': 3, 'hidden_label_count': 99},\n"
        "}))\n",
        encoding="utf-8",
    )
    evaluator = CommandEvaluatorAdapter(
        {
            "name": "output_contract_bench",
            "adapter": {
                "type": "command",
                "public_eval_cmd": "python evaluator.py",
                "output_limit_bytes": 4096,
            },
        },
        cwd=tmp_path,
    )

    result = evaluator.run_public_eval(str(tmp_path / "submission.json"))

    assert result["valid"] is True
    assert result["metrics"]["accuracy"] == 0.912
    assert result["diagnostics_public"]["format_check"] == "passed"
    assert result["extra"]["num_batches"] == 3
    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False
    assert "loaded split" in result["stdout"]
    assert "warning" in result["stderr"]
    assert result["stdout_bytes"] > 0
    assert result["stderr_bytes"] > 0

    agent_view = evaluator.agent_view(result, source="public_eval")
    assert "stdout" not in agent_view
    assert "stderr" not in agent_view
    assert agent_view["extra"] == {"num_batches": 3}


def test_loop_result_analysis_retry_returns_to_ideaspark(tmp_path: Path):
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(
        tmp_path,
        count=1,
        max_parallel=1,
        runner=runner,
        idea_gate_enabled=True,
    )
    orch.workers = _RetryAnalysisWorkers()

    assert orch.tick() is True
    summary = QueueSet(ws).summary()
    assert summary["evaluation_queue"]["finished"] == 1
    assert summary["ideaspark"]["queued"] == 1
    item = QueueSet(ws).ideaspark.list("queued")[0]
    assert item["payload"]["parent_branch_id"] == "branch-0"
    types = [record["type"] for record in _artifact_records(ws)]
    assert types.count("idea") >= 1
    assert "idea_review" in types
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "retry_idea" in decisions


def test_loop_goal_validation_rejects_unsafe_id_and_bad_constraints(tmp_path: Path):
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(
        '{"goal": {"id": "../escape"}, "benchmarks": [], "constraints": {}}',
        encoding="utf-8",
    )
    with pytest.raises(GoalError):
        load_goal(unsafe)

    bad_constraints = tmp_path / "bad_constraints.json"
    bad_constraints.write_text(
        '{"goal": {"id": "bad_constraints"}, "benchmarks": [], '
        '"constraints": {"max_parallel_evaluations": 0}}',
        encoding="utf-8",
    )
    with pytest.raises(GoalError):
        load_goal(bad_constraints)

    bad_gate = tmp_path / "bad_gate.json"
    bad_gate.write_text(
        '{"goal": {"id": "bad_gate"}, '
        '"workflow": {"type": "research", "idea_gate": {"enabled": "yes"}}, '
        '"benchmarks": [], "constraints": {}}',
        encoding="utf-8",
    )
    with pytest.raises(GoalError, match="workflow.idea_gate.enabled"):
        load_goal(bad_gate)

    with pytest.raises(ValueError):
        goal_workspace("../escape", base=tmp_path)


def test_loop_runner_failure_retries_then_succeeds(tmp_path: Path):
    runner = _TrackingExperimentRunner(fail_once={"branch-0"})
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    orch.config.max_experiment_retries = 1

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["queued"] == 1
    assert summary["failed"] == 0
    assert summary["finished"] == 0
    item = QueueSet(ws).evaluation.list("queued")[0]
    assert item["retry_count"] == 1
    assert "experiment_run" in [record["type"] for record in _artifact_records(ws)]
    assert "public_eval" not in [record["type"] for record in _artifact_records(ws)]

    assert orch.tick() is True
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["queued"] == 0
    assert summary["failed"] == 0
    assert summary["finished"] == 1
    assert runner.call_counts["branch-0"] == 2
    state = ResearchState(ws).load()["research_state"]
    assert state["branches"][0]["status"] == "archived"

    types = [record["type"] for record in _artifact_records(ws)]
    assert types.count("experiment_run") == 2
    assert "public_eval" in types
    decisions = (ws / "artifacts" / "decision_log.jsonl").read_text(encoding="utf-8")
    assert "retry_experiment" in decisions


def test_loop_wall_time_budget_stops_safely(tmp_path: Path):
    goal = _parallel_goal("wall-time-budget")
    ws = tmp_path / "workspace"
    state_store = ResearchState(ws)
    state = state_store.init(goal)
    state["research_state"]["created_at"] = 0
    state_store.save(state)
    orch = Orchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=_NoPromoteWorkers(),
        config=OrchestratorConfig(
            min_ideas=0,
            max_wall_time_hours=0.001,
        ),
    )

    assert orch.tick() is False
    state = state_store.load()["research_state"]
    assert state["status"] == "stopped"
    assert state["termination_reason"] == "wall_time_budget_exhausted"
    assert state["audit"]["termination_events"]
    assert "wall_time_budget_exhausted" in (ws / "status_summary.md").read_text(encoding="utf-8")


def test_loop_run_recovers_interrupted_running_item(tmp_path: Path):
    runner = _TrackingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    interrupted = orch.queues.evaluation.pop()
    assert interrupted is not None
    assert QueueSet(ws).summary()["evaluation_queue"]["running"] == 1

    state = orch.run()
    summary = QueueSet(ws).summary()["evaluation_queue"]
    assert summary["running"] == 0
    assert summary["finished"] == 1
    assert state["research_state"]["audit"]["recovery_events"]
    assert interrupted["id"] in state["research_state"]["audit"]["recovery_events"][0]["recovered"]["evaluation_queue"]


def test_loop_workspace_run_lock_rejects_second_owner(tmp_path: Path):
    workspace = tmp_path / "workspace"
    first = WorkspaceRunLock(workspace)
    second = WorkspaceRunLock(workspace)
    first.acquire()
    try:
        with pytest.raises(WorkspaceBusyError):
            second.acquire()
    finally:
        first.release()
        second.release()


@pytest.mark.parametrize("control_name, expected_status", [("stop", "stopped"), ("pause", "paused")])
def test_loop_external_control_is_preserved_after_long_runner(
    tmp_path: Path,
    control_name: str,
    expected_status: str,
):
    runner = _BlockingExperimentRunner()
    orch, ws = _parallel_orchestrator(tmp_path, count=1, max_parallel=1, runner=runner)
    thread = threading.Thread(target=orch.tick)
    thread.start()
    assert runner.started.wait(timeout=2)
    assert ResearchState(ws).load()["research_state"]["current_phase"] == "experiment_runner"
    (ws / "control" / control_name).write_text("1\n", encoding="utf-8")
    runner.release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    final_state = ResearchState(ws).load()["research_state"]
    assert final_state["status"] == expected_status
    assert final_state["current_phase"] == "idle"


def test_loop_ideaspark_fills_experiment_slots(tmp_path: Path):
    goal = _parallel_goal("producer-consumer")
    ws = tmp_path / "workspace"
    ResearchState(ws).init(goal)
    ideas = QueueSet(ws).ideaspark
    for index in range(3):
        ideas.push(
            {"id": f"idea-{index}", "title": f"idea-{index}", "mechanism": "test"},
            item_type="idea",
        )
    runner = _TrackingExperimentRunner(synchronize_first_batch=True)
    orch = Orchestrator(
        ws,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=_ImplementingNoPromoteWorkers(),
        experiment_runner=runner,
        config=OrchestratorConfig(
            min_ideas=0,
            max_parallel_evaluations=2,
        ),
    )

    assert orch.tick() is True
    summary = QueueSet(ws).summary()
    assert summary["ideaspark"]["finished"] == 2
    assert summary["ideaspark"]["queued"] == 1
    assert summary["evaluation_queue"]["finished"] == 2
    assert runner.max_active == 2
