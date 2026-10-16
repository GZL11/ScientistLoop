"""Candidate 快照和长生命周期 ImplementActor 测试。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.evaluation.evaluator import DummyEvaluatorAdapter
from famou_scientist.loop.evaluation.evaluator import BenchmarkAdapter
from famou_scientist.loop.evaluation.experiment import ExperimentRunner
from famou_scientist.loop.runtime import AsyncOrchestrator, ImplementActorStore, OrchestratorConfig
from famou_scientist.loop.storage import CandidateStore, QueueSet, ResearchState


class _ActorWorkers:
    """生成一个 Idea，并在同一 actor worktree 连续写入多个 revision。"""

    def __init__(self):
        """初始化每个实现回合看到的 mailbox 反馈记录。"""
        self.seen_feedback: list[list[str]] = []
        self.seen_feedback_payloads: list[list[dict[str, object]]] = []
        self.actor_sequence: list[str] = []

    def generate_ideas(self, goal, experience):
        """返回唯一的初始算法路线。"""
        del goal, experience
        return [{"id": "idea-1", "title": "Actor method", "mechanism": "iterate"}]

    def idea_gate(self, goal, idea, experience):
        """benchmark-managed 流程不应调用该节点。"""
        del goal
        raise AssertionError("benchmark-managed 不应调用 Idea Gate")

    def implement(self, idea, workspace):
        """复用 actor branch，并把当前 revision 写入可执行入口。"""
        mailbox = Path(str(idea.get("feedback_mailbox") or ""))
        records: list[dict[str, object]] = []
        if mailbox.is_file():
            records = [
                json.loads(line)
                for line in mailbox.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        messages = [str(record.get("kind") or "") for record in records]
        payloads = [dict(record.get("payload") or {}) for record in records]
        self.seen_feedback.append(messages)
        self.seen_feedback_payloads.append(payloads)
        self.actor_sequence.append(str(idea.get("actor_id") or ""))
        branch_id = str(idea["actor_branch_id"])
        worktree = Path(workspace) / "branches" / branch_id / "worktree"
        worktree.mkdir(parents=True, exist_ok=True)
        revision = int(idea["revision"])
        run_py = worktree / "run.py"
        run_py.write_text(f"REVISION = {revision}\n", encoding="utf-8")
        manifest = worktree / "method_manifest.json"
        manifest.write_text(
            json.dumps({"entrypoint": "run.py", "revision": revision}),
            encoding="utf-8",
        )
        return {
            "id": branch_id,
            "branch_id": branch_id,
            "idea_id": idea["id"],
            "status": LoopStatus.Implementation.IMPLEMENTED,
            "artifact": str(manifest),
            "worktree": str(worktree),
            "method_dir": str(worktree),
            "workdir": str(worktree),
            "entrypoint": str(run_py),
            "method_summary": f"revision {revision}",
        }

    def analyze_result(self, branch, results):
        """benchmark-managed 流程不应调用该节点。"""
        raise AssertionError("benchmark-managed 不应调用 result analyst")

    def analyze_deep(self, branch):
        """benchmark-managed 流程不应调用该节点。"""
        raise AssertionError("benchmark-managed 不应调用 deep analyzer")


class _CandidateRunner(ExperimentRunner):
    """读取冻结代码并返回该 Candidate 自己的清单。"""

    def run(self, branch):
        """返回有效的冻结产物，供 Dummy evaluator 评分。"""
        artifact = Path(branch["artifact"])
        candidate_id = str(branch.get("candidate_id") or branch["branch_id"])
        return {
            "id": f"run-{candidate_id}",
            "branch_id": branch["branch_id"],
            "candidate_id": branch.get("candidate_id"),
            "valid": artifact.is_file(),
            "returncode": 0,
            "artifact": str(artifact),
            "stdout": "ok",
            "stderr": "",
        }


class _ConcurrentEvaluator(BenchmarkAdapter):
    """记录完整 EvaluationJob 的实际并发度。"""

    def __init__(self):
        """初始化并发计数器。"""
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def validate_artifact(self, artifact_path):
        """接受测试工作空间内的现有产物。"""
        return {"valid": Path(artifact_path).is_file()}

    def run_public_eval(self, artifact_path):
        """延迟返回，以便观察两个 evaluator Future 重叠。"""
        del artifact_path
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return {"valid": True, "metrics": {"accuracy": 0.5}}
        finally:
            with self.lock:
                self.active -= 1

    def run_official_eval(self, artifact_path):
        """本测试没有正式评测预算，因此不应被调用。"""
        raise AssertionError(f"不应调用 official evaluator: {artifact_path}")


class _FailFirstRevisionRunner(_CandidateRunner):
    """让首个冻结版本运行失败，后续版本恢复成功。"""

    def run(self, branch):
        """根据 Candidate revision 构造确定性的运行结果。"""
        result = super().run(branch)
        if int(branch.get("revision") or 0) == 1:
            result.update(
                {
                    "valid": False,
                    "returncode": 1,
                    "error": "experiment exceeded canonical memory limit",
                    "stderr": "MemoryError: synthetic allocation",
                    "memory_limit_bytes": 1024,
                    "memory_limit_exceeded": True,
                    "termination_reason": "memory_limit_exceeded",
                    "process_group_isolated": True,
                }
            )
        return result


class _TimeoutFirstRevisionRunner(_CandidateRunner):
    """让首个 revision canonical 超时，验证结构化反馈后的原 Actor 修复。"""

    def run(self, branch):
        """首版返回 timeout，修复版返回有效产物。"""

        result = super().run(branch)
        if int(branch.get("revision") or 0) == 1:
            result.update(
                {
                    "valid": False,
                    "returncode": -15,
                    "stage": "canonical_run",
                    "error_code": "canonical_timeout",
                    "error": "experiment exceeded canonical time limit",
                    "retryable": True,
                    "timed_out": True,
                    "timeout_sec": 3600,
                    "expected_runtime_sec": 3000,
                    "termination_reason": "timeout",
                    "duration_ms": 3_600_123,
                    "command": "python run.py",
                    "candidate_dir": branch.get("candidate_dir"),
                    "method_dir": branch.get("method_dir"),
                    "entrypoint": branch.get("entrypoint"),
                    "stdout": "completed 22/23 cases",
                    "stderr": "",
                    "process_group_isolated": True,
                }
            )
        return result


class _OrderedRunner(_CandidateRunner):
    """记录 EvaluationJob 中 Runner 的调用顺序。"""

    def __init__(self, events: list[str]):
        """保存共享事件列表。"""
        self.events = events

    def run(self, branch):
        """先记录 Runner，再返回有效产物。"""
        self.events.append("runner")
        return super().run(branch)


class _OrderedEvaluator(BenchmarkAdapter):
    """断言 evaluator 只能在 Runner 结束后执行。"""

    def __init__(self, events: list[str]):
        """保存共享事件列表。"""
        self.events = events

    def validate_artifact(self, artifact_path):
        """记录产物校验并确认 Runner 已完成。"""
        assert self.events == ["runner"]
        self.events.append("validate")
        return {"valid": Path(artifact_path).is_file()}

    def run_public_eval(self, artifact_path):
        """记录公开评分。"""
        del artifact_path
        assert self.events == ["runner", "validate"]
        self.events.append("public_eval")
        return {"valid": True, "metrics": {"accuracy": 0.5}}

    def run_official_eval(self, artifact_path):
        """本测试不允许正式评分。"""
        raise AssertionError(f"不应调用 official evaluator: {artifact_path}")


def _actor_goal() -> dict:
    """构造启用三回合 actor 的最小 benchmark 目标。"""
    return {
        "goal_id": "actor-loop",
        "goal": {"id": "actor-loop", "name": "actor-loop"},
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
            "max_benchmark_attempts": 3,
            "max_evaluator_submissions": 3,
        },
        "infra": {"pipeline": "async"},
    }


def test_candidate_store_freezes_code_and_separates_outputs(tmp_path: Path):
    """后续源码修改不得改变已提交代码，不同 Candidate 输出不得覆盖。"""
    worktree = tmp_path / "branches" / "branch-1" / "worktree"
    worktree.mkdir(parents=True)
    run_py = worktree / "run.py"
    run_py.write_text("VALUE = 1\n", encoding="utf-8")
    manifest = worktree / "method_manifest.json"
    manifest.write_text('{"entrypoint": "run.py"}\n', encoding="utf-8")
    branch = {
        "branch_id": "branch-1",
        "idea_id": "idea-1",
        "worktree": str(worktree),
        "entrypoint": str(run_py),
        "artifact": str(manifest),
    }
    store = CandidateStore(tmp_path)

    first = store.create(branch, revision=1)
    run_py.write_text("VALUE = 2\n", encoding="utf-8")
    second = store.create(
        branch,
        revision=2,
        parent_candidate_id=first["candidate_id"],
    )

    assert (Path(first["method_dir"]) / "run.py").read_text() == "VALUE = 1\n"
    assert (Path(second["method_dir"]) / "run.py").read_text() == "VALUE = 2\n"
    assert first["candidate_output_dir"] != second["candidate_output_dir"]
    assert store.read(second["candidate_id"])["parent_candidate_id"] == first["candidate_id"]


def test_implement_actor_store_tracks_mailbox_and_budgets(tmp_path: Path):
    """actor 状态应持久化回合、运行、正式评测和脱敏反馈。"""
    store = ImplementActorStore(tmp_path)
    actor = store.create(
        {"id": "idea-1", "title": "Idea", "mechanism": "test"},
        max_lifetime_sec=60,
        max_turns=2,
        max_run_attempts=2,
        max_official_evaluations=1,
        max_repairs_per_revision=1,
    )
    actor_id = actor["actor_id"]

    first_turn = store.begin_turn(actor_id)
    store.register_candidate(actor_id, "candidate-1", attempt_id="0001")
    store.record_run(actor_id)
    message = store.add_feedback(
        actor_id,
        candidate_id="candidate-1",
        kind="evaluated",
        payload={"metrics": {"accuracy": 0.8}},
    )
    final = store.complete_candidate(
        actor_id,
        "candidate-1",
        official_evaluated=True,
    )

    assert first_turn["revision"] == 1
    assert final["completed_candidates"] == 1
    assert final["budget"]["used_run_attempts"] == 1
    assert final["budget"]["used_official_evaluations"] == 1
    assert store.mailbox(actor_id)[0]["id"] == message["id"]


def test_implement_actor_allows_only_one_inflight_candidate(tmp_path: Path):
    """同一 Actor 在收到反馈前不得提交第二个 Candidate。"""
    store = ImplementActorStore(tmp_path)
    actor = store.create(
        {"id": "idea-1", "title": "Idea", "mechanism": "test"},
        max_lifetime_sec=60,
        max_turns=2,
        max_run_attempts=3,
        max_official_evaluations=2,
        max_repairs_per_revision=1,
    )
    actor_id = actor["actor_id"]

    store.begin_turn(actor_id)
    store.register_candidate(actor_id, "candidate-1", attempt_id="0001")

    try:
        store.register_candidate(actor_id, "candidate-2", attempt_id="0002")
    except RuntimeError as exc:
        assert "已有在途 Candidate" in str(exc)
    else:  # pragma: no cover - 明确说明该不变量不能被静默放宽
        raise AssertionError("同一 Actor 不应允许两个在途 Candidate")


def test_engineering_repair_does_not_consume_research_turn(tmp_path: Path):
    """工程修复会唤醒 Session，但不占有效研究/refine 回合预算。"""
    store = ImplementActorStore(tmp_path)
    actor = store.create(
        {"id": "idea-1", "title": "Idea", "mechanism": "test"},
        max_lifetime_sec=60,
        max_turns=1,
        max_run_attempts=2,
        max_official_evaluations=1,
        max_repairs_per_revision=1,
    )
    actor_id = actor["actor_id"]

    store.begin_turn(actor_id)
    repaired = store.begin_turn(actor_id, repair=True)

    assert repaired["budget"]["used_turns"] == 1
    assert repaired["revision"] == 2
    assert repaired["activation_kind"] == "repair"


def test_debug_budget_is_per_actor_not_per_revision(tmp_path: Path):
    """`max_debug_attempts` 限的是「这个方案一共 debug 了几次」。

    必须和 `max_repairs_per_revision` 分开测：后者每次 register_candidate 都清零
    （`implement_actor.py:210`），所以它**从来拦不住**「一个方案反复修一整天」。
    """
    store = ImplementActorStore(tmp_path)
    actor = store.create(
        {"id": "idea-1", "title": "Idea", "mechanism": "test"},
        max_lifetime_sec=60,
        max_turns=1,
        max_run_attempts=99,
        max_official_evaluations=None,
        max_repairs_per_revision=1,
        max_debug_attempts=3,
    )
    actor_id = actor["actor_id"]

    store.begin_turn(actor_id)
    for expected in (1, 2, 3):
        allowed, reason = store.can_start_turn(actor_id, repair=True)
        assert allowed, reason
        state = store.begin_turn(actor_id, repair=True)
        assert state["budget"]["used_debug_attempts"] == expected
        # 每次提交都会清零 repair_count，模拟「修完又交、交完又挂」。
        store.register_candidate(actor_id, f"cand-{expected}", attempt_id=None)
        store.complete_candidate(
            actor_id,
            f"cand-{expected}",
            official_evaluated=False,
        )
        assert store.read(actor_id)["repair_count"] == 0

    allowed, reason = store.can_start_turn(actor_id, repair=True)
    assert allowed is False
    assert reason == "actor_debug_budget_exhausted"
    # 研究回合预算没被 debug 吃掉——两条轴互不干扰。
    assert store.read(actor_id)["budget"]["used_turns"] == 1


def test_debug_budget_unset_keeps_historical_behaviour(tmp_path: Path):
    """不给上限时按历史行为走：debug 不受这一轴限制。"""
    store = ImplementActorStore(tmp_path)
    actor = store.create(
        {"id": "idea-1", "title": "Idea", "mechanism": "test"},
        max_lifetime_sec=60,
        max_turns=1,
        max_run_attempts=99,
        max_official_evaluations=None,
        max_repairs_per_revision=1,
    )
    actor_id = actor["actor_id"]
    store.begin_turn(actor_id)
    for _ in range(8):
        store.begin_turn(actor_id, repair=True)
    allowed, reason = store.can_start_turn(actor_id, repair=True)
    assert allowed is True and reason is None
    assert store.read(actor_id)["budget"]["max_debug_attempts"] is None


def test_refine_disabled_retires_actor_but_keeps_debug_alive(tmp_path: Path):
    """关掉 refine 后：出分即收工，但代码有 bug 仍能 resume debug。

    这两件事必须一起断言。`_long_lived_actors_enabled()` 老判据是 `turns > 1`，
    照 v2 的配置（turns=1）会把 actor 整个关掉，**连 debug 一起没**——那样
    「有 bug 的方案」直接判死，和设计要的正好相反。
    """
    config = OrchestratorConfig(
        max_implement_turns_per_actor=1,
        refine_after_evaluation=False,
        max_debug_attempts_per_actor=3,
    )
    assert config.refine_after_evaluation is False

    orchestrator = AsyncOrchestrator.__new__(AsyncOrchestrator)
    orchestrator.config = config
    assert orchestrator._long_lived_actors_enabled() is True

    # 一次 debug 都不给时，actor 没有任何再唤醒的理由，退回「完全关掉」。
    orchestrator.config = OrchestratorConfig(
        max_implement_turns_per_actor=1,
        refine_after_evaluation=False,
        max_debug_attempts_per_actor=0,
    )
    assert orchestrator._long_lived_actors_enabled() is False

    # 默认（refine 开着）时与改动前逐字等价：判据仍然只是 turns > 1。
    orchestrator.config = OrchestratorConfig(max_implement_turns_per_actor=1)
    assert orchestrator._long_lived_actors_enabled() is False
    orchestrator.config = OrchestratorConfig(max_implement_turns_per_actor=2)
    assert orchestrator._long_lived_actors_enabled() is True


def test_async_actor_reuses_branch_and_evaluates_three_frozen_revisions(tmp_path: Path):
    """Idea、Implement 和 Eval 三池应完成同一 lineage 的三次有界迭代。"""
    goal = _actor_goal()
    # 只允许一个初始 Idea；Actor continuation 不占初始 Idea 名额。
    goal["constraints"]["max_benchmark_attempts"] = 1
    goal["constraints"]["max_evaluator_submissions"] = 3
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=_ActorWorkers(),
        experiment_runner=_CandidateRunner(),
        config=OrchestratorConfig(
            max_ticks=20,
            interval_sec=0.001,
            max_parallel_ideas=1,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
            max_implement_turns_per_actor=3,
            max_run_attempts_per_actor=3,
            max_official_evaluations_per_actor=3,
            idea_queue_high_watermark=1,
            evaluation_queue_capacity=2,
        ),
    )

    state = orchestrator.run()["research_state"]

    actors = orchestrator.actors.list()
    candidates = sorted((workspace / "candidates").glob("*/manifest.json"))
    revisions = [
        json.loads(path.read_text(encoding="utf-8"))["revision"]
        for path in candidates
    ]
    branch_ids = {
        json.loads(path.read_text(encoding="utf-8"))["branch_id"]
        for path in candidates
    }
    assert state["status"] == LoopStatus.Research.COMPLETED
    assert QueueSet(workspace).summary()["benchmark_attempt_queue"]["finished"] == 3
    assert len(actors) == 1
    assert actors[0]["completed_candidates"] == 3
    assert len(actors[0]["pending_candidates"]) == 0
    assert revisions == [1, 2, 3]
    assert len(branch_ids) == 1
    assert len(orchestrator.actors.mailbox(actors[0]["actor_id"])) == 3


def test_async_evaluation_pool_runs_concurrently_but_commits_serially(tmp_path: Path):
    """Evaluation Pool 可并发，队列和预算结果仍应完整串行落盘。"""
    goal = _actor_goal()
    goal["goal_id"] = "parallel-evaluator"
    goal["goal"] = {"id": "parallel-evaluator", "name": "parallel-evaluator"}
    goal["constraints"] = {
        "max_benchmark_attempts": 1,
        "max_evaluator_submissions": 0,
    }
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    queue = QueueSet(workspace).evaluation
    for index in range(4):
        artifact = workspace / "inputs" / f"submission-{index}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}\n", encoding="utf-8")
        queue.push(
            {
                "id": f"branch-{index}",
                "branch_id": f"branch-{index}",
                "artifact": str(artifact),
            },
            item_type="branch",
        )
    evaluator = _ConcurrentEvaluator()
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=evaluator,
        workers=_ActorWorkers(),
        experiment_runner=_CandidateRunner(),
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=10,
            interval_sec=0.001,
            max_parallel_ideas=1,
            max_parallel_implementations=1,
            max_parallel_evaluations=2,
            evaluation_queue_capacity=4,
        ),
    )

    orchestrator.run()

    summary = QueueSet(workspace).summary()["evaluation_queue"]
    assert summary["finished"] == 4
    assert summary["running"] == 0
    assert evaluator.max_active == 2
    state = ResearchState(workspace).load()["research_state"]
    assert state["evaluator_budget"]["used_submissions"] == 0


def test_parked_actor_releases_slot_and_is_resumed_after_feedback(tmp_path: Path):
    """慢评测期间应运行新 Idea，反馈回来后再恢复原 Actor。"""
    goal = _actor_goal()
    goal["constraints"]["max_benchmark_attempts"] = 2
    goal["constraints"]["max_evaluator_submissions"] = 0
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    workers = _ActorWorkers()
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=_ConcurrentEvaluator(),
        workers=workers,
        experiment_runner=_CandidateRunner(),
        config=OrchestratorConfig(
            max_ticks=40,
            interval_sec=0.001,
            max_parallel_ideas=1,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
            max_implement_turns_per_actor=2,
            max_run_attempts_per_actor=2,
            max_official_evaluations_per_actor=0,
            idea_queue_high_watermark=1,
            evaluation_queue_capacity=2,
        ),
    )

    orchestrator.run()

    sequence = workers.actor_sequence
    assert len(set(sequence)) == 2
    assert sequence[0] != sequence[1]
    assert sequence.count(sequence[0]) == 2
    assert "evaluated" in workers.seen_feedback[2]


def test_evaluation_job_runs_code_before_evaluator(tmp_path: Path):
    """单个 EvaluationJob 必须顺序完成 Runner 和 Evaluator。"""
    events: list[str] = []
    artifact = tmp_path / "submission.json"
    artifact.write_text("{}\n", encoding="utf-8")
    item = {
        "id": "evaluation-item",
        "payload": {
            "branch_id": "branch-1",
            "artifact": str(artifact),
        },
    }
    goal = _actor_goal()
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=_OrderedEvaluator(events),
        workers=_ActorWorkers(),
        experiment_runner=_OrderedRunner(events),
        config=OrchestratorConfig(max_parallel_evaluations=1),
    )

    result = orchestrator._run_evaluation_job(item, allow_official=False)

    assert result["run_result"]["valid"] is True
    assert result["evaluation_bundle"]["valid"] is True
    assert events == ["runner", "validate", "public_eval"]


def test_actor_repairs_run_failure_without_charging_official_budget(tmp_path: Path):
    """canonical run 失败应回流 actor 修复，且失败版本不扣正式评测次数。"""
    goal = _actor_goal()
    goal["constraints"]["max_benchmark_attempts"] = 1
    goal["constraints"]["max_evaluator_submissions"] = 2
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    workers = _ActorWorkers()
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=workers,
        experiment_runner=_FailFirstRevisionRunner(),
        config=OrchestratorConfig(
            max_ticks=20,
            interval_sec=0.001,
            max_parallel_ideas=1,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
            max_implement_turns_per_actor=2,
            max_run_attempts_per_actor=2,
            max_official_evaluations_per_actor=2,
            max_repairs_per_revision=1,
            idea_queue_high_watermark=1,
            evaluation_queue_capacity=1,
        ),
    )

    state = orchestrator.run()["research_state"]

    actor = orchestrator.actors.list()[0]
    assert state["status"] == LoopStatus.Research.COMPLETED
    assert state["evaluator_budget"]["used_submissions"] == 1
    assert actor["budget"]["used_run_attempts"] == 2
    assert actor["budget"]["used_official_evaluations"] == 1
    assert workers.seen_feedback[0] == []
    assert "run_failed" in workers.seen_feedback[1]
    repair_payload = workers.seen_feedback_payloads[1][-1]
    assert repair_payload["memory_limit_exceeded"] is True
    assert repair_payload["termination_reason"] == "memory_limit_exceeded"
    assert repair_payload["memory_limit_bytes"] == 1024
    assert repair_payload["process_group_isolated"] is True
    records = sorted((workspace / "expbank").glob("[0-9]*/record.json"))
    assert (
        json.loads(records[0].read_text(encoding="utf-8"))["status"]
        == "engineering_failed"
    )
    assert json.loads(records[1].read_text(encoding="utf-8"))["status"] in {
        "evaluated",
        "best",
    }


def test_actor_resumes_same_session_after_canonical_timeout(tmp_path: Path):
    """canonical 超时应携带结构化诊断恢复原 Actor，并重新运行修复版本。"""

    goal = _actor_goal()
    goal["constraints"]["max_benchmark_attempts"] = 1
    goal["constraints"]["max_evaluator_submissions"] = 2
    workspace = tmp_path / "workspace"
    ResearchState(workspace).init(goal)
    workers = _ActorWorkers()
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        workers=workers,
        experiment_runner=_TimeoutFirstRevisionRunner(),
        config=OrchestratorConfig(
            max_ticks=20,
            interval_sec=0.001,
            max_parallel_ideas=1,
            max_parallel_implementations=1,
            max_parallel_evaluations=1,
            max_implement_turns_per_actor=2,
            max_run_attempts_per_actor=2,
            max_official_evaluations_per_actor=2,
            max_repairs_per_revision=1,
            idea_queue_high_watermark=1,
            evaluation_queue_capacity=1,
        ),
    )

    state = orchestrator.run()["research_state"]

    actor = orchestrator.actors.list()[0]
    assert state["status"] == LoopStatus.Research.COMPLETED
    assert state["evaluator_budget"]["used_submissions"] == 1
    assert actor["budget"]["used_run_attempts"] == 2
    assert len(set(workers.actor_sequence)) == 1
    feedback = workers.seen_feedback_payloads[1][-1]
    assert feedback["stage"] == "canonical_run"
    assert feedback["error_code"] == "canonical_timeout"
    assert feedback["timed_out"] is True
    assert feedback["timeout_sec"] == 3600
    assert feedback["expected_runtime_sec"] == 3000
    assert feedback["command"] == "python run.py"
    assert feedback["run_evidence_ref"]
    assert feedback["stdout"] == "completed 22/23 cases"
