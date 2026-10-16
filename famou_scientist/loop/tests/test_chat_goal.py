"""聊天 `/goal` 提议、确认和后台启动控制面测试。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from famou_scientist.loop.domain.goal import load_goal
from famou_scientist.loop.runtime.chat_goal import (
    ChatGoalController,
    ChatGoalError,
    ProposalStatus,
)


class _FakeProcess:
    """提供不创建真实子进程的 Popen 返回值。"""

    pid = os.getpid()


class _ProcessRecorder:
    """记录后台启动参数，供测试校验协议。"""

    def __init__(self) -> None:
        """初始化空调用列表。"""
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> _FakeProcess:
        """记录 Popen 调用并返回当前进程 PID。"""
        self.calls.append((list(command), dict(kwargs)))
        return _FakeProcess()


def _proposal(name: str = "interpretable_classifier") -> dict[str, Any]:
    """返回带显式 evaluator 的最小可启动研究提议。"""
    return {
        "raw_user_message": "设计效果更好且可解释的分类算法",
        "master_decision": "enter_loop",
        "decision_reason": "需要持续产生 idea、实现并调用正式 evaluator。",
        "confidence": 0.9,
        "goal": {"name": name},
        "workflow": {"type": "research"},
        "objective_brief": {
            "primary_goal": "在给定分类 benchmark 上形成可发表的新算法。",
            "preference_description": "优先机制创新和可解释性，不接受只做 HPO。",
            "allow_examples": ["准确率接近 SOTA，但推理更快且机制清晰。"],
            "reject_examples": ["只通过扩大网格搜索获得小幅提升。"],
            "tie_breakers": ["分数接近时优先证据完整且更简单的方法。"],
        },
        "benchmarks": [
            {
                "name": "classification_bench",
                "adapter": {"type": "dummy"},
                "official_metric": {
                    "name": "accuracy",
                    "direction": "higher_is_better",
                },
            }
        ],
        "constraints": {"max_wall_time_hours": 1},
        "infra": {
            "pipeline": "async",
            "concurrency": {"ideas": 1, "implementations": 1, "evaluations": 1},
        },
    }


def test_confirm_policy_only_creates_pending_proposal(tmp_path: Path) -> None:
    """默认策略不得在用户确认前启动后台进程。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )

    result = controller.propose(
        _proposal(),
        conversation_id="session-confirm",
        mode="confirm",
    )

    assert result["status"] == ProposalStatus.PENDING
    assert result["raw_user_message"] == "设计效果更好且可解释的分类算法"
    assert recorder.calls == []
    assert not list((tmp_path / "goal-controller" / "goals").glob("*.yaml"))
    events = (tmp_path / "goal-controller" / "events.jsonl").read_text(encoding="utf-8")
    assert "proposal_created" in events


def test_confirm_writes_goal_and_starts_existing_loop_runtime(tmp_path: Path) -> None:
    """确认后应生成标准 goal 文件，并以无限 admission + 墙钟预算后台运行。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )
    pending = controller.propose(
        _proposal(),
        conversation_id="session-start",
        mode="confirm",
    )

    started = controller.confirm(
        conversation_id="session-start",
        proposal_id=pending["proposal_id"],
    )

    assert started["status"] == ProposalStatus.RUNNING
    assert len(recorder.calls) == 1
    command, options = recorder.calls[0]
    assert command[-2:] == ["--max-ticks", "-1"]
    assert "--async-pipeline" in command
    assert options["start_new_session"] is True
    assert options["cwd"] == str(tmp_path.resolve())
    goal_file = Path(started["goal_file"])
    loaded = load_goal(goal_file)
    assert loaded["provenance"]["proposal_id"] == pending["proposal_id"]
    assert loaded["provenance"]["raw_user_message"] == "设计效果更好且可解释的分类算法"
    assert loaded["objective_brief"]["reject_examples"]
    assert loaded["constraints"]["max_wall_time_hours"] == 1

    status = controller.status("session-start")
    assert status["session"]["status"] == ProposalStatus.RUNNING
    assert status["session"]["pid"] == os.getpid()


def test_auto_mode_requires_explicit_authorization(tmp_path: Path) -> None:
    """Master 不能只靠自行判断把 confirm 提升为 auto。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )
    with pytest.raises(ChatGoalError, match="没有全自动授权"):
        controller.propose(
            _proposal("unauthorized"),
            conversation_id="session-auto",
            mode="auto",
        )

    controller.set_policy(
        "session-auto",
        "auto",
        authorization_text="后续这类目标都全自动运行",
    )
    started = controller.propose(
        _proposal("authorized"),
        conversation_id="session-auto",
        mode="auto",
    )
    assert started["status"] == ProposalStatus.RUNNING
    assert started["process"]["auto_approved"] is True
    assert len(recorder.calls) == 1


def test_persistent_auto_policy_requires_authorization_evidence(tmp_path: Path) -> None:
    """会话级全自动策略必须保留用户原始授权文本。"""
    controller = ChatGoalController(tmp_path / "loop", project_root=tmp_path)

    with pytest.raises(ChatGoalError, match="必须保留用户明确授权"):
        controller.set_policy("session-policy", "auto")

    record = controller.set_policy(
        "session-policy",
        "auto",
        authorization_text="后续适合的研究任务都由你自动进入 loop",
    )
    assert record["mode"] == "auto"
    assert record["authorization_text"] == "后续适合的研究任务都由你自动进入 loop"


def test_one_shot_auto_requires_exact_raw_user_message(tmp_path: Path) -> None:
    """一次性 auto 必须携带与原始用户消息一致的授权证据。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )
    proposal = _proposal("one_shot_auto")

    with pytest.raises(ChatGoalError, match="完全一致"):
        controller.propose(
            proposal,
            conversation_id="session-one-shot",
            mode="auto",
            auto_authorized=True,
            authorization_text="不一致的授权文本",
        )

    started = controller.propose(
        proposal,
        conversation_id="session-one-shot",
        mode="auto",
        auto_authorized=True,
        authorization_text=proposal["raw_user_message"],
    )
    assert started["status"] == ProposalStatus.RUNNING
    assert started["goal_document"]["provenance"]["auto_authorization_text"] == proposal["raw_user_message"]
    assert controller.policy("session-one-shot")["mode"] == "confirm"


def test_new_proposal_supersedes_pending_version(tmp_path: Path) -> None:
    """用户修改待确认目标时应保留旧提议并标记为 superseded。"""
    controller = ChatGoalController(tmp_path / "loop", project_root=tmp_path)
    first = controller.propose(
        _proposal("first_version"),
        conversation_id="session-revise",
    )
    second = controller.propose(
        _proposal("second_version"),
        conversation_id="session-revise",
    )

    first_path = tmp_path / "goal-controller" / "proposals" / f"{first['proposal_id']}.json"
    first_record = json.loads(first_path.read_text(encoding="utf-8"))
    assert first_record["status"] == ProposalStatus.SUPERSEDED
    assert first_record["error"] == f"superseded_by:{second['proposal_id']}"
    assert controller.status("session-revise")["proposal"]["proposal_id"] == second["proposal_id"]


def test_missing_evaluator_blocks_launch_and_requests_clarification(tmp_path: Path) -> None:
    """只有目标描述但没有 evaluator 时，确认也不能启动不可评测 Loop。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )
    pending = controller.propose(
        {
            "raw_user_message": "做一个更好的算法",
            "master_decision": "enter_loop",
            "objective_brief": {"primary_goal": "做一个更好的算法"},
        },
        conversation_id="session-missing-eval",
    )

    with pytest.raises(ChatGoalError, match="缺少 benchmark/evaluator"):
        controller.confirm(
            conversation_id="session-missing-eval",
            proposal_id=pending["proposal_id"],
        )
    assert recorder.calls == []
    status = controller.status("session-missing-eval")
    assert status["proposal"]["status"] == ProposalStatus.NEEDS_CLARIFICATION


def test_chat_control_uses_existing_master_bridge_bus(tmp_path: Path) -> None:
    """聊天暂停命令应进入现有 commands.jsonl，而不是另造控制协议。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )
    pending = controller.propose(
        _proposal("controllable"),
        conversation_id="session-control",
    )
    started = controller.confirm(
        conversation_id="session-control",
        proposal_id=pending["proposal_id"],
    )

    result = controller.control("session-control", "pause", reason="用户希望先看进展")

    workspace = tmp_path / "loop" / str(started["goal_id"])
    commands = [
        json.loads(line)
        for line in (workspace / "control" / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["action"] == "pause"
    assert commands[-1]["type"] == "pause"
    assert commands[-1]["payload"]["reason"] == "用户希望先看进展"
    assert (workspace / "control" / "pause").is_file()


def test_chat_message_and_goal_change_use_existing_bus(tmp_path: Path) -> None:
    """运行中的补充意见和目标变更应进入同一个 commands.jsonl。"""
    recorder = _ProcessRecorder()
    controller = ChatGoalController(
        tmp_path / "loop",
        project_root=tmp_path,
        process_launcher=recorder,
    )
    pending = controller.propose(
        _proposal("bridge_messages"),
        conversation_id="session-bridge",
    )
    started = controller.confirm(
        conversation_id="session-bridge",
        proposal_id=pending["proposal_id"],
    )

    controller.submit_message("session-bridge", "解释性优先，不要使用 ensemble")
    controller.answer_clarification("session-bridge", "clarification-1", "允许少量精度下降")
    controller.request_goal_change(
        "session-bridge",
        decision="continue_current",
        instruction="新方向留给下一轮，当前任务继续完成",
    )

    workspace = tmp_path / "loop" / str(started["goal_id"])
    commands = [
        json.loads(line)
        for line in (workspace / "control" / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["type"] for item in commands[-3:]] == [
        "message",
        "clarification_response",
        "goal_change",
    ]
    assert commands[-1]["payload"]["decision"] == "continue_current"
