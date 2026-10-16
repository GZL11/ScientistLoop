"""IdeaSpark 水位口径与消费顺序。

历史回归：`_idea_backlog` 把 `actor_continuation` 也计入 IdeaSpark 容量。
续跑是 ImplementActor 的唤醒请求，不经过 IdeaAgent（`generate_ideas` 与该路径
无交集），push 时本就带更高 priority（repair 3 / refine 2）；把两类混在一起数，
续跑一旦堆积就把新 Idea 生产整体卡死——实测 `glm53dbt2-s41467-025-64512-w`
在 70 分钟后再未产出任何新 Idea，后续 20 次 push 全是续跑，辩论闸门（只在生产
新 Idea 时检查）因此一次都没开。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.runtime.orchestrator import Orchestrator, OrchestratorConfig
from famou_scientist.loop.storage.queues import JsonlQueue, QueueSet


def _queue(tmp_path: Path, ordering: str = "weighted") -> JsonlQueue:
    return JsonlQueue(tmp_path, "benchmark_attempt_queue", ordering=ordering)


# --- 水位只数新 Idea -------------------------------------------------


def test_continuations_do_not_consume_ideaspark_capacity(tmp_path: Path):
    q = _queue(tmp_path)
    for _ in range(5):
        q.push({"continuation_reason": "evaluated"}, item_type="actor_continuation", priority=2)
    assert Orchestrator._idea_backlog(q) == 0


def test_new_ideas_consume_capacity(tmp_path: Path):
    q = _queue(tmp_path)
    for _ in range(3):
        q.push({"title": "T"}, item_type="benchmark_attempt", priority=1)
    assert Orchestrator._idea_backlog(q) == 3


def test_leased_new_idea_still_counts(tmp_path: Path):
    """被 SearchPolicy 租走当 offered_idea 的新 Idea 仍未实现，必须继续占名额。"""

    q = _queue(tmp_path)
    item = q.push({"title": "T"}, item_type="benchmark_attempt", priority=1)
    q.lease(item, owner_id="owner", purpose="improve_choice")
    assert Orchestrator._idea_backlog(q) == 1


def test_mixed_queue_counts_only_new_ideas(tmp_path: Path):
    q = _queue(tmp_path)
    q.push({"title": "A"}, item_type="benchmark_attempt", priority=1)
    q.push({"title": "B"}, item_type="idea", priority=1)
    for _ in range(4):
        q.push({"continuation_reason": "evaluated"}, item_type="actor_continuation", priority=2)
    q.push({"continuation_reason": "run_failed"}, item_type="actor_continuation", priority=3)
    assert Orchestrator._idea_backlog(q) == 2


def test_done_items_do_not_count(tmp_path: Path):
    q = _queue(tmp_path)
    item = q.push({"title": "T"}, item_type="benchmark_attempt", priority=1)
    q.update(item, status=LoopStatus.Queue.FINISHED)
    assert Orchestrator._idea_backlog(q) == 0


def test_capacity_two_still_admits_new_ideas_under_continuation_load(tmp_path: Path):
    """回归点：容量收紧到 2 时，续跑堆积不得把新 Idea 生产降为零。"""

    q = _queue(tmp_path)
    for _ in range(6):
        q.push({"continuation_reason": "evaluated"}, item_type="actor_continuation", priority=2)
    assert Orchestrator._idea_backlog(q) < 2  # 仍低于水位，允许继续生产


# --- 消费顺序 equal / weighted ---------------------------------------


def _ids(items):
    return [i["payload"]["tag"] for i in items]


def test_weighted_ordering_puts_high_priority_first(tmp_path: Path):
    q = _queue(tmp_path, ordering="weighted")
    q.push({"tag": "new"}, item_type="benchmark_attempt", priority=1)
    q.push({"tag": "debated"}, item_type="benchmark_attempt", priority=2)
    q.push({"tag": "repair"}, item_type="actor_continuation", priority=3)
    assert _ids(q.list(LoopStatus.Queue.QUEUED)) == ["repair", "debated", "new"]


def test_weighted_ordering_is_fifo_within_a_priority(tmp_path: Path):
    q = _queue(tmp_path, ordering="weighted")
    for tag in ("a", "b", "c"):
        q.push({"tag": tag}, item_type="benchmark_attempt", priority=1)
    assert _ids(q.list(LoopStatus.Queue.QUEUED)) == ["a", "b", "c"]


def test_equal_ordering_ignores_priority(tmp_path: Path):
    """对照开关：把"插队"这一项单独关掉，priority 仍记录但不影响顺序。"""

    q = _queue(tmp_path, ordering="equal")
    q.push({"tag": "new"}, item_type="benchmark_attempt", priority=1)
    q.push({"tag": "debated"}, item_type="benchmark_attempt", priority=2)
    q.push({"tag": "repair"}, item_type="actor_continuation", priority=3)
    assert _ids(q.list(LoopStatus.Queue.QUEUED)) == ["new", "debated", "repair"]
    # priority 没有被丢弃，只是不参与排序。
    assert {i["payload"]["tag"]: i["priority"] for i in q.list()} == {
        "new": 1,
        "debated": 2,
        "repair": 3,
    }


@pytest.mark.parametrize("bad", ["fifo", "PRIORITY", "priority"])
def test_unknown_queue_ordering_is_rejected(tmp_path: Path, bad):
    with pytest.raises(ValueError, match="queue ordering"):
        JsonlQueue(tmp_path, "q", ordering=bad)


@pytest.mark.parametrize("empty", ["", None])
def test_empty_ordering_defaults_to_weighted(tmp_path: Path, empty):
    assert JsonlQueue(tmp_path, "q", ordering=empty).ordering == "weighted"


def test_queue_set_threads_ordering_to_pending_queues(tmp_path: Path):
    qs = QueueSet(tmp_path, ordering="equal")
    assert qs.benchmark_attempt.ordering == "equal"
    assert qs.ideaspark.ordering == "equal"
    # 评测队列按提交先后消费，不参与优先级实验。
    assert qs.evaluation.ordering == "weighted"


# --- 配置归一化 ------------------------------------------------------


def test_queue_ordering_defaults_to_weighted():
    assert OrchestratorConfig().queue_ordering == "weighted"


@pytest.mark.parametrize("bad", ["fifo", "", None, 7])
def test_unknown_ordering_config_falls_back_to_weighted(bad):
    """配置写错不得静默改变消费顺序。"""

    assert OrchestratorConfig(queue_ordering=bad).queue_ordering == "weighted"


def test_equal_ordering_config_is_preserved():
    assert OrchestratorConfig(queue_ordering="EQUAL").queue_ordering == "equal"


@pytest.mark.parametrize("value,expected", [(0, 0), (2, 2), (-1, 0), ("x", 1)])
def test_debate_priority_bonus_is_normalized(value, expected):
    config = OrchestratorConfig(idea_debate_priority_bonus=value)
    assert config.idea_debate_priority_bonus == expected


def test_debate_priority_bonus_defaults_to_one():
    assert OrchestratorConfig().idea_debate_priority_bonus == 1


def test_same_millisecond_pushes_keep_insertion_order(tmp_path: Path):
    """回归点：created_at 只有毫秒精度，同一 tick 连续 push 会撞时间戳。

    条目文件名带随机后缀，仅按 (priority, created_at) 排序时同级顺序不确定。
    seq 作为最后一级 tie-break 才让"同优先级 FIFO"真正成立。
    """

    q = _queue(tmp_path)
    tags = [f"t{i}" for i in range(20)]
    for tag in tags:
        q.push({"tag": tag}, item_type="benchmark_attempt", priority=1)
    assert _ids(q.list(LoopStatus.Queue.QUEUED)) == tags
    assert _ids(_queue(tmp_path, ordering="equal").list(LoopStatus.Queue.QUEUED)) == tags


def test_legacy_items_without_seq_still_sort(tmp_path: Path):
    """旧 run 目录里的条目没有 seq 字段，读取时不能崩。"""

    import json

    q = _queue(tmp_path)
    item = q.push({"tag": "new"}, item_type="benchmark_attempt", priority=1)
    legacy = dict(item)
    legacy.update({"id": "legacy_item", "tag": None, "created_at": 1, "payload": {"tag": "old"}})
    legacy.pop("seq")
    (q.items_dir / "legacy_item.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert _ids(q.list(LoopStatus.Queue.QUEUED)) == ["old", "new"]
