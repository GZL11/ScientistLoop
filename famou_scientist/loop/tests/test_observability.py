"""测试 Loop 级 Agent 轨迹和用量观测设施。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from famou_scientist.loop.observability import (
    ObservabilityStore,
    TokenPricingPolicy,
    export_incremental_trajectory,
    normalize_cli_telemetry,
    normalize_trajectory_telemetry,
    snapshot_jsonl_files,
)


def test_claude_telemetry_sums_internal_activations_without_model_usage_duplication() -> None:
    """Claude wrapper 内恢复多次时累加顶层 usage，不重复累加 modelUsage。"""

    stdout = "\n".join(
        json.dumps(item)
        for item in (
            {
                "type": "result",
                "num_turns": 2,
                "total_cost_usd": 1.25,
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 30,
                    "output_tokens": 40,
                },
                "modelUsage": {
                    "claude-opus": {
                        "inputTokens": 10,
                        "outputTokens": 40,
                        "costUSD": 1.25,
                    }
                },
            },
            {
                "type": "result",
                "num_turns": 1,
                "total_cost_usd": 0.5,
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 3,
                    "cache_read_input_tokens": 4,
                    "output_tokens": 5,
                },
            },
        )
    )

    telemetry = normalize_cli_telemetry(
        runtime="claude",
        stdout=stdout,
        model="glm-5.2",
    )

    assert telemetry["model"] == "glm-5.2"
    assert telemetry["provider_turns"] == 3
    assert telemetry["token_usage"] == {
        "input_tokens": 12,
        "cache_creation_input_tokens": 23,
        "cache_read_input_tokens": 34,
        "output_tokens": 45,
    }
    assert telemetry["reported_total_tokens"] == 114
    assert telemetry["cost"] == {
        "amount": 1.75,
        "currency": "USD",
        "source": "cli_reported",
    }


def test_codex_telemetry_uses_turn_completed_and_maps_cached_tokens() -> None:
    """Codex 只统计 turn.completed，并统一 cached_input_tokens 字段。"""

    stdout = "\n".join(
        (
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 70,
                        "output_tokens": 25,
                    },
                }
            ),
        )
    )

    telemetry = normalize_cli_telemetry(
        runtime="codex",
        stdout=stdout,
        model="gpt-5.3-codex",
    )

    assert telemetry["provider_turns"] == 1
    assert telemetry["token_usage"]["cache_read_input_tokens"] == 70
    assert telemetry["reported_total_tokens"] == 195
    assert telemetry["cost"]["amount"] is None


def test_incremental_trajectory_only_exports_bytes_added_after_resume(tmp_path: Path) -> None:
    """Session Resume 只导出本次新增事件，不重复旧轨迹。"""

    native_root = tmp_path / "native"
    session = native_root / "session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(json.dumps({"type": "old"}) + "\n", encoding="utf-8")
    cursors = snapshot_jsonl_files([native_root])
    with session.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "new", "timestamp": "2026-08-11T00:00:00Z"}) + "\n")

    output = tmp_path / "agent_trajectory.jsonl"
    manifest = export_incremental_trajectory(
        output_path=output,
        roots=[native_root],
        cursors=cursors,
        call_id="call-2",
        role="implement",
        runtime="claude",
        session_id="session-1",
    )

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert manifest["records"] == 1
    assert records[0]["event_id"] == "call-2:0"
    assert records[0]["payload"]["type"] == "new"


def test_trajectory_usage_fallback_deduplicates_claude_content_blocks(
    tmp_path: Path,
) -> None:
    """CLI 未输出 result 时可从增量 Session 恢复 usage，重复内容块只计一次。"""

    path = tmp_path / "trajectory.jsonl"
    usage = {
        "input_tokens": 3,
        "cache_creation_input_tokens": 4,
        "cache_read_input_tokens": 5,
        "output_tokens": 6,
    }
    records = [
        {
            "event_id": f"call-1:{index}",
            "session_id": "session-1",
            "payload": {
                "uuid": f"block-{index}",
                "message": {
                    "id": "message-1",
                    "role": "assistant",
                    "model": "glm-5.2",
                    "usage": usage,
                },
            },
        }
        for index in range(2)
    ]
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in records),
        encoding="utf-8",
    )

    telemetry = normalize_trajectory_telemetry(path)

    assert telemetry["provider_turns"] == 1
    assert telemetry["reported_total_tokens"] == 18
    assert telemetry["model"] == "glm-5.2"


def test_observability_store_concurrently_appends_and_exports(tmp_path: Path) -> None:
    """Idea/Implement 并发写入不会破坏 JSONL，摘要按角色与费用汇总。"""

    pricing = TokenPricingPolicy.from_mapping(
        {
            "currency": "USD",
            "per_million_tokens": {
                "input": 1.4,
                "cache_creation": 1.4,
                "cache_read": 0.26,
                "output": 4.4,
            },
            "source": "user_confirmed",
            "effective_at": "2026-08-11",
        }
    )
    store = ObservabilityStore(tmp_path / "run", pricing=pricing)

    def record(index: int) -> None:
        """写入一条测试调用。"""

        store.record_agent_call(
            {
                "id": f"call-{index}",
                "runtime": "claude",
                "session": {"session_id": f"session-{index}", "resumed_this_call": False},
                "telemetry": {
                    "adapter": "cli",
                    "runtime": "claude",
                    "model": "glm-5.2",
                    "duration_ms": 1000,
                    "provider_turns": 2,
                    "token_usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 1,
                        "cache_read_input_tokens": 20,
                        "output_tokens": 5,
                    },
                    "cost": {
                        "amount": 0.25,
                        "currency": "USD",
                        "source": "cli_reported",
                    },
                },
            },
            task="idea_generator" if index % 2 == 0 else "implement_agent",
            role="idea" if index % 2 == 0 else "implement",
            valid=True,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(record, range(12)))

    summary = store.write_summary()
    export_dir = store.export(tmp_path / "export")

    assert summary["total"]["calls"] == 12
    assert summary["total"]["reported_total_tokens"] == 432
    assert summary["total"]["reported_cost"] == {"USD": 3.0}
    assert summary["total"]["cli_reported_cost"] == {"USD": 3.0}
    assert summary["total"]["calculated_cost"]["USD"] == pytest.approx(0.0005112)
    breakdown = summary["total"]["calculated_cost_breakdown"]["USD"]
    assert breakdown == pytest.approx(
        {
            "input": 0.000168,
            "cache_creation": 0.0000168,
            "cache_read": 0.0000624,
            "output": 0.000264,
        }
    )
    assert summary["pricing_source"] == "user_confirmed"
    assert summary["pricing_effective_at"] == "2026-08-11"
    assert summary["by_role"]["idea"]["calls"] == 6
    assert summary["by_role"]["implement"]["calls"] == 6
    assert len(store.usage_records()) == 12
    assert (export_dir / "agent_usage.csv").is_file()
    assert (export_dir / "agent_usage_summary.json").is_file()


def test_observability_store_restores_pricing_from_research_state(
    tmp_path: Path,
) -> None:
    """离线重建摘要时从 ResearchState 恢复运行时的价格审计口径。"""

    workspace = tmp_path / "run"
    workspace.mkdir()
    (workspace / "research_state.yaml").write_text(
        json.dumps(
            {
                "research_state": {
                    "goal": {
                        "infra": {
                            "observability": {
                                "pricing": {
                                    "currency": "USD",
                                    "per_million_tokens": {
                                        "input": 1.4,
                                        "cache_creation": 1.4,
                                        "cache_read": 0.26,
                                        "output": 4.4,
                                    },
                                    "source": "user_confirmed",
                                    "effective_at": "2026-08-11",
                                }
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    summary = ObservabilityStore(workspace).build_summary()

    assert summary["pricing_policy"]["per_million_tokens"]["cache_read"] == 0.26
    assert summary["pricing_source"] == "user_confirmed"
