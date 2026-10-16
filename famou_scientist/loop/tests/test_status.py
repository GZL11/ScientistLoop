"""科研循环统一状态定义的契约测试。"""
from __future__ import annotations

import json

from famou_scientist.loop.domain import GOAL_STATUSES, QUEUE_STATUSES, LoopStatus


def test_loop_status_records_each_business_scope() -> None:
    """不同作用域应集中定义，同时保持各自独立的允许值集合。"""
    assert LoopStatus.ExpBank.values() == {
        "implementing",
        "implemented",
        "not_executed",
        "engineering_failed",
        "evaluated",
        "best",
        "failed",
    }
    assert LoopStatus.Queue.values() == {
        "queued",
        "leased",
        "waiting_resources",
        "running",
        "finished",
        "failed",
        "archived",
        "cancelled",
        "not_executed",
    }
    assert LoopStatus.Research.values() == {
        "running",
        "paused",
        "stopped",
        "completed",
        "failed",
    }
    assert LoopStatus.Implementation.values() == {
        "implemented",
        "implementation_failed",
    }
    assert LoopStatus.Actor.CANCELLED.value == "cancelled"
    assert LoopStatus.Candidate.CANCELLED.value == "cancelled"
    assert LoopStatus.Branch.values() == {
        "benchmark_attempt_queued",
        "evaluation_queued",
        "waiting_resources",
        "evaluation_running",
        "analysis_queued",
        "retry_queued",
        "evaluated",
        "archived",
        "engineering_failed",
        "failed",
        "paper_candidate",
        "analyzed",
        "cancelled",
    }


def test_loop_status_preserves_plain_string_persistence() -> None:
    """枚举写入 JSON 后应保持既有普通字符串格式。"""
    payload = {
        "expbank": LoopStatus.ExpBank.IMPLEMENTING,
        "queue": LoopStatus.Queue.QUEUED,
        "research": LoopStatus.Research.RUNNING,
    }

    assert json.loads(json.dumps(payload)) == {
        "expbank": "implementing",
        "queue": "queued",
        "research": "running",
    }
    assert LoopStatus.ExpBank.IMPLEMENTING == "implementing"


def test_legacy_status_sets_follow_the_unified_definition() -> None:
    """旧状态集合应由统一定义派生，避免出现两份事实来源。"""
    assert QUEUE_STATUSES == LoopStatus.Queue.values()
    assert GOAL_STATUSES == LoopStatus.Research.values()
    assert LoopStatus.RESEARCH_TERMINAL == {
        LoopStatus.Research.PAUSED,
        LoopStatus.Research.STOPPED,
        LoopStatus.Research.COMPLETED,
        LoopStatus.Research.FAILED,
    }
