"""New Idea 与 Improve 配对 Search Policy 的契约测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from famou_scientist.loop.agents.workers import PromptWorkerSet
from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.evaluation.evaluator import DummyEvaluatorAdapter
from famou_scientist.loop.evaluation.experiment import NoopExperimentRunner
from famou_scientist.loop.execution.submit_candidate import main as submit_candidate_main
from famou_scientist.loop.runtime.implement_actor import ImplementActorStore
from famou_scientist.loop.runtime.orchestrator import Orchestrator
from famou_scientist.loop.search import PairwiseImproveSearchPolicy
from famou_scientist.loop.storage.queues import JsonlQueue


def _idea(identifier: str) -> dict[str, str]:
    """构造最小可追踪 Idea。"""

    return {
        "id": identifier,
        "title": identifier,
        "mechanism": f"mechanism-{identifier}",
    }


def _improve_queue(tmp_path: Path) -> tuple[JsonlQueue, dict, dict, dict]:
    """构造一个 Improve continuation 和两条 FIFO New Idea。"""

    queue = JsonlQueue(tmp_path, "benchmark_attempt_queue")
    first = queue.push(_idea("idea-a"), item_type="benchmark_attempt", priority=5)
    second = queue.push(_idea("idea-b"), item_type="benchmark_attempt", priority=1)
    first["created_at"] = 1
    second["created_at"] = 2
    queue.update(first)
    queue.update(second)
    continuation = queue.push(
        {
            **_idea("current"),
            "actor_id": "actor-1",
            "continuation_reason": "evaluated",
        },
        item_type="actor_continuation",
        priority=10,
    )
    claimed = queue.claim(continuation)
    return queue, claimed, first, second


def test_refine_replays_offered_idea_to_fifo_tail(tmp_path: Path) -> None:
    """选择 Refine 后保留同一 Idea，并把它重放到队尾。"""

    queue, claimed, first, second = _improve_queue(tmp_path)
    policy = PairwiseImproveSearchPolicy(enabled=True)

    prepared = policy.prepare_dispatch(claimed, queue)
    opportunity = prepared["payload"]["search_opportunity"]
    assert opportunity["offered_idea"]["id"] == "idea-a"
    assert queue.get(first["id"])["status"] == LoopStatus.Queue.LEASED

    settlement = policy.settle(
        prepared,
        {
            "search_decision": {
                "action": "refine",
                "reason": "当前有效路线的局部上限更高。",
                "offered_idea_id": "idea-a",
            }
        },
        queue,
    )

    queued_ids = [item["payload"]["id"] for item in queue.list("queued")]
    assert settlement.replayed is True
    assert queued_ids == ["idea-b", "idea-a"]
    replayed = queue.get(first["id"])
    assert replayed["offer_count"] == 1
    assert replayed["id"] == first["id"]
    assert replayed["priority"] == 1
    assert replayed["last_replay_previous_priority"] == 5
    assert queue.get(second["id"])["status"] == LoopStatus.Queue.QUEUED


@pytest.mark.parametrize("action", ["switch", "fuse"])
def test_switch_or_fuse_consumes_offered_idea(
    tmp_path: Path,
    action: str,
) -> None:
    """Switch/Fuse 会消费租用 Idea，并留下明确归因。"""

    queue, claimed, first, _second = _improve_queue(tmp_path)
    policy = PairwiseImproveSearchPolicy(enabled=True)
    prepared = policy.prepare_dispatch(claimed, queue)

    settlement = policy.settle(
        prepared,
        {
            "search_decision": {
                "action": action,
                "reason": "备选机制的预期上限更高。",
                "offered_idea_id": "idea-a",
            }
        },
        queue,
        evidence_refs=["artifact://branch"],
    )

    consumed = queue.get(first["id"])
    assert settlement.consumed is True
    assert consumed["status"] == LoopStatus.Queue.FINISHED
    assert consumed["lease_resolution"] == action
    assert "artifact://branch" in consumed["evidence_refs"]


def test_repair_bypasses_pairing_policy(tmp_path: Path) -> None:
    """工程 Debug 不得租用或消费 IdeaSpark 中的新方案。"""

    queue = JsonlQueue(tmp_path, "benchmark_attempt_queue")
    idea = queue.push(_idea("idea-a"), item_type="benchmark_attempt", priority=1)
    repair = queue.push(
        {
            **_idea("current"),
            "actor_id": "actor-1",
            "continuation_reason": "run_failed",
        },
        item_type="actor_continuation",
        priority=3,
    )
    claimed = queue.claim(repair)

    prepared = PairwiseImproveSearchPolicy(enabled=True).prepare_dispatch(
        claimed,
        queue,
    )

    assert "search_opportunity" not in prepared["payload"]
    assert queue.get(idea["id"])["status"] == LoopStatus.Queue.QUEUED


def test_disabled_policy_preserves_original_dispatch(tmp_path: Path) -> None:
    """策略关闭时不租用 Idea，也不改变原 continuation。"""

    queue, claimed, first, _second = _improve_queue(tmp_path)

    prepared = PairwiseImproveSearchPolicy(enabled=False).prepare_dispatch(
        claimed,
        queue,
    )

    assert "search_opportunity" not in prepared["payload"]
    assert queue.get(first["id"])["status"] == LoopStatus.Queue.QUEUED


def test_missing_agent_decision_keeps_controller_fallback_attribution(
    tmp_path: Path,
) -> None:
    """缺失显式选择时应回退 Refine，并保留 Controller 归因。"""

    queue, claimed, first, _second = _improve_queue(tmp_path)
    policy = PairwiseImproveSearchPolicy(enabled=True)
    prepared = policy.prepare_dispatch(claimed, queue)

    settlement = policy.settle(prepared, {}, queue)

    assert settlement.replayed is True
    assert settlement.decision is not None
    assert settlement.decision["action"] == "refine"
    assert settlement.decision["source"] == "controller_fallback"
    assert queue.get(first["id"])["status"] == LoopStatus.Queue.QUEUED


def test_orchestrator_claim_delegates_pairing_to_search_policy(
    tmp_path: Path,
) -> None:
    """Controller 的实现领取接缝应调用独立策略，而非内嵌配对规则。"""

    workspace = tmp_path / "workspace"
    goal = {
        "goal": {"id": "search-wiring", "name": "search-wiring"},
        "workflow": {"type": "benchmark_managed"},
        "benchmark_task": {"task_id": "case"},
        "benchmarks": [],
        "infra": {
            "scheduling": {
                "search_policy": {
                    "type": "pairwise_improve",
                    "enabled": True,
                }
            }
        },
    }
    orchestrator = Orchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        experiment_runner=NoopExperimentRunner(workspace),
    )
    queue = orchestrator.queues.benchmark_attempt
    offered = queue.push(
        _idea("idea-a"),
        item_type="benchmark_attempt",
        priority=1,
    )
    queue.push(
        {
            **_idea("current"),
            "actor_id": "actor-1",
            "continuation_reason": "evaluated",
        },
        item_type="actor_continuation",
        priority=2,
    )

    claimed = orchestrator._claim_implementation_item()

    assert claimed is not None
    assert claimed["payload"]["search_opportunity"]["offered_idea"]["id"] == "idea-a"
    assert queue.get(offered["id"])["status"] == LoopStatus.Queue.LEASED
    assert orchestrator._idea_backlog(queue) == 1


def test_orchestrator_persists_controller_fallback_attribution(
    tmp_path: Path,
) -> None:
    """Controller 收口时不能把缺失选择误记成 Agent 主动 Refine。"""

    workspace = tmp_path / "workspace"
    goal = {
        "goal": {"id": "fallback-audit", "name": "fallback-audit"},
        "workflow": {"type": "benchmark_managed"},
        "benchmark_task": {"task_id": "case"},
        "benchmarks": [],
        "infra": {
            "scheduling": {
                "search_policy": {
                    "type": "pairwise_improve",
                    "enabled": True,
                }
            }
        },
    }
    orchestrator = Orchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        experiment_runner=NoopExperimentRunner(workspace),
    )
    queue = orchestrator.queues.benchmark_attempt
    offered = queue.push(
        _idea("idea-a"),
        item_type="benchmark_attempt",
        priority=1,
    )
    queue.push(
        {
            **_idea("current"),
            "continuation_reason": "evaluated",
        },
        item_type="actor_continuation",
        priority=2,
    )
    claimed = orchestrator._claim_implementation_item()
    assert claimed is not None

    orchestrator._process_implementation_result(
        {"research_state": {"status": "running", "branches": []}},
        claimed,
        {
            "id": "failed-branch",
            "branch_id": "failed-branch",
            "idea_id": "current",
            "status": LoopStatus.Implementation.FAILED,
            "error": "adapter returned no explicit search decision",
        },
    )

    records = list(
        (workspace / "artifacts" / "search_policy_decision").glob("*.json")
    )
    assert len(records) == 1
    decision = json.loads(records[0].read_text(encoding="utf-8"))
    assert decision["action"] == "refine"
    assert decision["source"] == "controller_fallback"
    assert queue.get(offered["id"])["status"] == LoopStatus.Queue.QUEUED


def test_actor_records_switch_and_uses_new_base_idea(tmp_path: Path) -> None:
    """Switch 后 Actor 下一回合应基于被采用的新 Idea，而非旧标题。"""

    store = ImplementActorStore(tmp_path)
    actor = store.create(
        _idea("current"),
        max_lifetime_sec=600,
        max_turns=3,
        max_run_attempts=3,
        max_official_evaluations=None,
        max_repairs_per_revision=1,
    )

    updated = store.record_search_decision(
        actor["actor_id"],
        {
            "action": "switch",
            "reason": "新机制上限更高。",
            "offered_idea_id": "idea-a",
        },
        offered_idea=_idea("idea-a"),
    )

    assert updated["idea_id"] == "idea-a"
    assert updated["base_idea"]["id"] == "idea-a"
    # 换之前在做哪个方案要留住（record["idea_id"] 已被覆盖，别处查不到），
    # 但**不能写成图上的父指针**——switch 是「放弃 previous 改做 offered」，
    # offered 不是从 previous 派生的，安一个父就是造假边。
    assert updated["base_idea"]["switched_from_idea_id"] == "current"
    assert "parent_idea_id" not in updated["base_idea"]
    assert "relation" not in updated["base_idea"]
    decisions = (tmp_path / "actors" / actor["actor_id"] / "search_decisions.jsonl")
    assert decisions.is_file()


def test_fuse_records_sources_without_fabricating_a_relation(tmp_path: Path) -> None:
    """Fuse 只累积 `fused_ideas`，不写 `relation="combines"` 这类自报标签。

    「融合过」这件事由 `fused_ideas` 非空直接表达，而且该列表随 `base_idea` 进
    continuation 载荷、真的递到 implement agent 眼前——有消费者。再加一个自报标签
    只会多一个没人校验的证据来源，正是 20260915 那批 `alternative_to` 44%/63%
    的来路（三个 `relation` 取值全部由代码路径写入，没有一个是 agent 的判断）。
    """

    store = ImplementActorStore(tmp_path)
    actor = store.create(
        _idea("current"),
        max_lifetime_sec=600,
        max_turns=3,
        max_run_attempts=3,
        max_official_evaluations=None,
        max_repairs_per_revision=1,
    )
    actor_id = actor["actor_id"]

    def _fuse(idea_id: str) -> dict:
        return store.record_search_decision(
            actor_id,
            {"action": "fuse", "reason": "两者互补。", "offered_idea_id": idea_id},
            offered_idea=_idea(idea_id),
        )

    updated = _fuse("idea-a")
    base = updated["base_idea"]
    assert [value["id"] for value in base["fused_ideas"]] == ["idea-a"]
    # fuse 不换基础方案——switch 才换。
    assert base["id"] == "current"
    assert updated["idea_id"] == actor["idea_id"]
    assert "relation" not in base
    assert "parent_idea_id" not in base
    assert "parents" not in base

    # 第二次融合累积；同一条再来一次不重复入列（幂等，重放不会把来源数吹大）。
    assert [
        value["id"] for value in _fuse("idea-b")["base_idea"]["fused_ideas"]
    ] == ["idea-a", "idea-b"]
    assert [
        value["id"] for value in _fuse("idea-a")["base_idea"]["fused_ideas"]
    ] == ["idea-a", "idea-b"]

    # 每一次决策都留痕，与去重无关——去重的是来源列表，不是决策流水。
    decisions = (tmp_path / "actors" / actor_id / "search_decisions.jsonl")
    assert len(decisions.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_submit_candidate_requires_explicit_search_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """配对回合缺少选择时拒绝提交，补齐后在原回合成功。"""

    worktree = tmp_path / "worktree"
    outputs = tmp_path / "outputs"
    worktree.mkdir()
    outputs.mkdir()
    (worktree / "run.py").write_text("print('ok')\n", encoding="utf-8")
    manager_result = outputs / "manager.json"
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_WORKTREE", str(worktree))
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_OUTPUT", str(manager_result))
    monkeypatch.setenv(
        "FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT",
        str(worktree / "famou_agent_result.json"),
    )
    monkeypatch.setenv(
        "FAMOU_SUBMISSION_PATH",
        str(outputs / "candidate_submission.json"),
    )
    monkeypatch.setenv("FAMOU_EXPECTED_ENTRYPOINT", "run.py")
    monkeypatch.setenv(
        "FAMOU_IDEA_RESOURCE_REQUEST_JSON",
        json.dumps(
            {
                "cpu_cores": 1,
                "host_memory_gib": 2,
                "gpu": {"device_count": 0, "memory_gib_per_device": 0},
                "expected_runtime_sec": 60,
            }
        ),
    )
    offered_idea = {
        **_idea("idea-a"),
        "resource_request": {
            "cpu_cores": 2,
            "host_memory_gib": 4,
            "gpu": {"device_count": 0, "memory_gib_per_device": 0},
            "expected_runtime_sec": 120,
        },
    }
    monkeypatch.setenv(
        "FAMOU_SEARCH_OPPORTUNITY_JSON",
        json.dumps(
            {
                "current_idea": _idea("current"),
                "offered_idea": offered_idea,
                "allowed_actions": ["refine", "switch", "fuse"],
            }
        ),
    )

    assert submit_candidate_main([]) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert "--search-action" in rejected["error"]
    assert not manager_result.exists()

    assert (
        submit_candidate_main(
            [
                "--search-action",
                "switch",
                "--search-reason",
                "新 Idea 的预期上限和资源可行性更高。",
            ]
        )
        == 0
    )
    accepted = json.loads(capsys.readouterr().out)
    result = json.loads(manager_result.read_text(encoding="utf-8"))
    assert accepted["search_action"] == "switch"
    assert result["search_decision"]["offered_idea_id"] == "idea-a"
    assert result["resource_request"]["cpu_cores"] == 2.0
    assert result["resource_request"]["host_memory_gib"] == 4.0


def test_single_call_switch_preserves_decision_and_offered_resources(
    tmp_path: Path,
) -> None:
    """Single-call Implement 切换 Idea 时应保留决策并继承新方案资源。"""

    class SwitchingLLM:
        """返回不重复声明资源的 Switch 实现。"""

        def complete_json(self, task, prompt, context):  # noqa: ANN001, ARG002
            """生成最小可执行实现和结构化搜索选择。"""

            assert task == "method_designer"
            return {
                "entrypoint": "method.py",
                "files": [{"path": "method.py", "content": "print('ok')\n"}],
                "search_decision": {
                    "action": "switch",
                    "reason": "新机制的预期收益更高。",
                    "offered_idea_id": "idea-a",
                },
            }

    current_resources = {
        "cpu_cores": 1,
        "host_memory_gib": 2,
        "gpu": {"device_count": 0, "memory_gib_per_device": 0},
        "expected_runtime_sec": 60,
    }
    offered_resources = {
        "cpu_cores": 4,
        "host_memory_gib": 8,
        "gpu": {"device_count": 0, "memory_gib_per_device": 0},
        "expected_runtime_sec": 120,
    }
    idea = {
        **_idea("current"),
        "resource_request": current_resources,
        "search_opportunity": {
            "current_idea": _idea("current"),
            "offered_idea": {
                **_idea("idea-a"),
                "resource_request": offered_resources,
            },
            "allowed_actions": ["refine", "switch", "fuse"],
        },
    }
    goal = {"goal": {"id": "pairwise", "name": "pairwise"}}
    worker = PromptWorkerSet(goal, tmp_path, llm=SwitchingLLM())

    branch = worker.implement(idea, tmp_path)

    assert branch["status"] == LoopStatus.Implementation.IMPLEMENTED
    assert branch["search_decision"]["action"] == "switch"
    assert branch["resource_request"] == offered_resources
