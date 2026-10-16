"""Human、Master 与 Loop 控制面及 fork 语义测试。"""
from __future__ import annotations

import json
from pathlib import Path

from famou_scientist.loop import cli
from famou_scientist.loop.runtime.control import ControlEventStore
from famou_scientist.loop.storage.experience import ExperienceStore
from famou_scientist.loop.storage.queues import QueueSet
from famou_scientist.loop.storage.state import ResearchState


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _goal_file() -> Path:
    """返回可用于控制面测试的最小研究目标。"""
    return FIXTURES / "goals" / "dummy_algorithm_innovation.yaml"


def _init_loop(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """创建一个只初始化状态、不消费任务的 Loop。"""
    root = tmp_path / name
    assert (
        cli.main(
            [
                "run",
                "--goal-file",
                str(_goal_file()),
                "--root",
                str(root),
                "--max-ticks",
                "0",
                "--fresh",
            ]
        )
        == 0
    )
    return root, root / "dummy_algorithm_innovation"


def test_control_event_store_is_append_only_and_cursored(tmp_path: Path) -> None:
    """多条人类命令应按顺序保留，并可用游标逐条消费。"""
    store = ControlEventStore(tmp_path / "loop")
    first = store.submit("message", {"text": "先看速度"})
    second = store.submit("message", {"text": "再看可解释性"})

    pending = store.pending_commands()
    assert [item["command_id"] for item in pending] == [
        first["command_id"],
        second["command_id"],
    ]
    store.acknowledge(first, accepted=True, payload={"action": "message_recorded"})
    store.advance(pending[0]["_line_number"])
    assert [item["command_id"] for item in store.pending_commands()] == [
        second["command_id"]
    ]
    assert len(store.read_events()) == 1


def test_continue_current_defers_goal_to_next_loop(tmp_path: Path) -> None:
    """continue_current 不应原地修改当前目标。"""
    root, workspace = _init_loop(tmp_path, "continue")
    before = ResearchState(workspace).load()["research_state"]["goal"]

    assert (
        cli.main(
            [
                "goal-change",
                "--goal-id",
                "dummy_algorithm_innovation",
                "--root",
                str(root),
                "--decision",
                "continue_current",
                "--instruction",
                "下一 Loop 重点考察鲁棒性",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "run",
                "--goal-file",
                str(_goal_file()),
                "--root",
                str(root),
                "--max-ticks",
                "1",
            ]
        )
        == 0
    )

    state = ResearchState(workspace).load()["research_state"]
    assert state["goal"] == before
    assert state["pending_goal_change"]["decision"] == "continue_current"
    assert state["pending_goal_change"]["instruction"] == "下一 Loop 重点考察鲁棒性"


def test_stop_current_cancels_queue_and_writes_handoff(tmp_path: Path) -> None:
    """stop_current 应取消未完成条目并保存交接证据。"""
    root, workspace = _init_loop(tmp_path, "stop")
    QueueSet(workspace).ideaspark.push(
        {"id": "queued-idea", "title": "queued", "mechanism": "test"},
        item_type="idea",
    )

    assert (
        cli.main(
            [
                "goal-change",
                "--goal-id",
                "dummy_algorithm_innovation",
                "--root",
                str(root),
                "--decision",
                "stop_current",
                "--instruction",
                "立即停止并转入新目标",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "run",
                "--goal-file",
                str(_goal_file()),
                "--root",
                str(root),
                "--max-ticks",
                "1",
            ]
        )
        == 0
    )

    state = ResearchState(workspace).load()["research_state"]
    assert state["status"] == "stopped"
    assert state["lifecycle"] == "superseded_by_user"
    assert state["termination_reason"] == "superseded_by_user_goal_change"
    assert QueueSet(workspace).summary()["ideaspark"]["cancelled"] == 1
    assert (workspace / "handoff.md").is_file()
    assert (workspace / "handoff.json").is_file()

    commands = (workspace / "control" / "commands.jsonl").read_text(encoding="utf-8")
    events = (workspace / "control" / "events.jsonl").read_text(encoding="utf-8")
    assert "stop_current" in commands
    assert "command_applied" in events


def test_async_stop_still_consumes_control_event(tmp_path: Path) -> None:
    """异步模式在 admission 关闭后仍应生成控制命令回执。"""
    root, workspace = _init_loop(tmp_path, "async-stop")
    assert (
        cli.main(
            [
                "stop",
                "--goal-id",
                "dummy_algorithm_innovation",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "run",
                "--goal-file",
                str(_goal_file()),
                "--root",
                str(root),
                "--max-ticks",
                "1",
                "--async-pipeline",
            ]
        )
        == 0
    )
    events = (workspace / "control" / "events.jsonl").read_text(encoding="utf-8")
    assert "command_applied" in events


def test_fork_creates_new_workspace_with_read_only_parent_lineage(tmp_path: Path) -> None:
    """fork 不复制旧 artifacts，但新 Loop 可以检索父 Loop 经验。"""
    root, parent = _init_loop(tmp_path, "fork")
    sentinel = parent / "artifacts" / "parent-only.txt"
    sentinel.write_text("must stay in parent", encoding="utf-8")
    ExperienceStore(parent).upsert(
        {
            "type": "attempted_idea",
            "title": "父 Loop 经验",
            "summary": "历史失败方案",
        }
    )

    child_id = "child_algorithm_innovation"
    assert (
        cli.main(
            [
                "fork",
                "--parent-goal-id",
                "dummy_algorithm_innovation",
                "--new-goal-id",
                child_id,
                "--goal-file",
                str(_goal_file()),
                "--root",
                str(root),
            ]
        )
        == 0
    )

    child = root / child_id
    assert child.is_dir()
    assert not (child / "artifacts" / "parent-only.txt").exists()
    goal = json.loads((child / "goal.yaml").read_text(encoding="utf-8"))
    lineage = goal["lineage"]
    assert lineage["parent_loop_id"] == "dummy_algorithm_innovation"
    assert str(parent.resolve()) in lineage["prior_loop_dirs"]
    assert str((parent / "shared_experience_pool").resolve()) in lineage[
        "experience_sources"
    ]
    state = ResearchState(child).load()["research_state"]
    assert state["lineage"] == lineage

    experience = ExperienceStore(
        child,
        source_roots=lineage["experience_sources"],
    ).search("父 Loop 经验")
    assert experience
    assert experience[0]["title"] == "父 Loop 经验"


def test_resume_from_creates_new_workspace_without_reviving_stopped_work(
    tmp_path: Path,
) -> None:
    """resume-from 继承可见历史，但不复活旧任务中被 stop 的 active work。"""

    root, source = _init_loop(tmp_path, "resume-src")
    (source / "artifacts" / "old.txt").write_text("old artifact", encoding="utf-8")

    state = ResearchState(source).load()
    state["research_state"]["status"] = "stopped"
    state["research_state"]["lifecycle"] = "stopped_by_user"
    state["research_state"]["termination_reason"] = "stopped_by_user"
    ResearchState(source).save(state)

    queue = QueueSet(source).ideaspark
    item = queue.push({"title": "resume idea", "mechanism": "test"}, item_type="idea")
    queue.lease(item["id"], owner_id="worker-1", purpose="resume-test")

    resumed_id = "resume-target"
    assert (
        cli.main(
            [
                "run",
                "--goal-file",
                str(_goal_file()),
                "--root",
                str(root),
                "--goal-id",
                resumed_id,
                    "--resume-from",
                    str(source),
                    "--max-ticks",
                    "0",
                ]
        )
        == 0
    )

    target = root / resumed_id
    assert target.is_dir()
    assert (target / "artifacts" / "old.txt").read_text(encoding="utf-8") == "old artifact"

    resumed = ResearchState(target).load()["research_state"]
    assert resumed["status"] == "running"
    assert resumed["termination_reason"] is None
    assert str(source) in resumed["lineage"]["prior_loop_dirs"]

    resumed_queue = QueueSet(target).summary()["ideaspark"]
    assert resumed_queue["queued"] == 0
    assert resumed_queue["running"] == 0
    assert QueueSet(source).ideaspark.get(item["id"])["status"] == "leased"
