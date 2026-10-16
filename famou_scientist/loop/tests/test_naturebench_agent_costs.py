"""测试 NatureBench Agent 花费统计。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from famou_scientist.loop.examples.naturebench.summarize_agent_costs import (
    build_reports,
    reprice_reports,
)
from famou_scientist.loop.observability import TokenPricingPolicy


def _write_json(path: Path, value: object) -> None:
    """写入测试 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_session(path: Path, events: list[dict[str, object]]) -> None:
    """写入 Claude CLI JSONL session。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )


def test_agent_cost_report_deduplicates_usage_and_preserves_missing_cost(tmp_path: Path) -> None:
    """重复内容块不重复计 token，缺失价格时保持空值。"""
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "demo-s41467-025-63412-3-v1"
    _write_json(
        run_dir / "research_state.yaml",
        {"research_state": {"status": "completed"}},
    )
    _write_json(
        run_dir / "artifacts" / "worker_calls" / "idea.json",
        {
            "id": "idea-worker",
            "task": "idea_generator",
            "result": {
                "output": {
                    "__agent_call__": {
                        "id": "idea-call",
                        "role": "idea",
                        "command": ["claude", "--model", "glm-5.2"],
                        "run": {"duration_ms": 3_600_000},
                    }
                }
            },
        },
    )
    _write_json(
        run_dir / "artifacts" / "worker_calls" / "implement.json",
        {
            "id": "implement-call",
            "task": "implement_agent",
            "meta": {
                "id": "implement-call",
                "role": "implement",
                "command": ["claude", "--model", "glm-5.2"],
                "run": {"duration_ms": 1_800_000},
            },
        },
    )
    idea_session = (
        run_dir
        / "idea_agent_workspaces"
        / "branches"
        / "idea_agent_1"
        / "logs"
        / "claude_home"
        / ".claude"
        / "projects"
        / "project"
        / "idea-session.jsonl"
    )
    duplicated_usage = {
        "input_tokens": 10,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 20,
        "output_tokens": 5,
    }
    _write_session(
        idea_session,
        [
            {
                "sessionId": "idea-session",
                "uuid": "block-1",
                "message": {
                    "role": "assistant",
                    "id": "message-1",
                    "model": "glm-5.2",
                    "usage": duplicated_usage,
                },
            },
            {
                "sessionId": "idea-session",
                "uuid": "block-2",
                "message": {
                    "role": "assistant",
                    "id": "message-1",
                    "model": "glm-5.2",
                    "usage": duplicated_usage,
                },
            },
            {
                "sessionId": "idea-session",
                "uuid": "block-3",
                "message": {
                    "role": "assistant",
                    "id": "message-1",
                    "model": "glm-5.2",
                    "usage": {
                        "input_tokens": 3,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 4,
                        "output_tokens": 7,
                    },
                },
            },
        ],
    )
    implement_session = (
        run_dir
        / "branches"
        / "actor_branch_1"
        / "logs"
        / "claude_home"
        / ".claude"
        / "projects"
        / "project"
        / "implement-session.jsonl"
    )
    _write_session(
        implement_session,
        [
            {
                "sessionId": "implement-session",
                "uuid": "implement-block",
                "message": {
                    "role": "assistant",
                    "id": "implement-message",
                    "model": "glm-5.2",
                    "usage": {
                        "input_tokens": 30,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 40,
                        "output_tokens": 8,
                    },
                },
            }
        ],
    )

    official = tmp_path / "results.csv"
    official.write_text(
        "case_id,final_status,best_score,judge_verdict\n"
        "s41467-025-63412-3,completed,0.1,valid\n"
        "s41467-025-63418-x,no_score,,\n",
        encoding="utf-8",
    )
    case_output = tmp_path / "case.csv"
    run_output = tmp_path / "run.csv"
    summary_output = tmp_path / "summary.json"
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
    summary = build_reports(
        runs_root, official, case_output, run_output, summary_output, pricing
    )

    with case_output.open(encoding="utf-8", newline="") as handle:
        rows = {row["case_id"]: row for row in csv.DictReader(handle)}
    row = rows["s41467-025-63412-3"]
    assert row["agent_activations"] == "2"
    assert row["idea_activations"] == "1"
    assert row["implement_activations"] == "1"
    assert row["agent_active_hours"] == "1.5000"
    assert row["llm_turns"] == "3"
    assert row["input_tokens"] == "43"
    assert row["cache_creation_input_tokens"] == "2"
    assert row["cache_read_input_tokens"] == "64"
    assert row["output_tokens"] == "20"
    assert row["reported_total_tokens"] == "129"
    assert row["calculated_input_cost_usd"] == "0.000060"
    assert row["calculated_cache_creation_cost_usd"] == "0.000003"
    assert row["calculated_cache_read_cost_usd"] == "0.000017"
    assert row["calculated_output_cost_usd"] == "0.000088"
    assert row["calculated_cost_usd"] == "0.000168"
    assert row["reported_cost_usd"] == ""
    assert rows["s41467-025-63418-x"]["agent_activations"] == "0"
    assert summary["agent_activations"] == 2
    assert summary["reported_cost_usd"] is None
    assert summary["calculated_cost_usd"] == pytest.approx(0.00016764)
    assert summary["pricing_source"] == "user_confirmed"

    replacement = TokenPricingPolicy.from_mapping(
        {
            "currency": "USD",
            "per_million_tokens": {
                "input": 1,
                "cache_creation": 1,
                "cache_read": 1,
                "output": 1,
            },
            "source": "test_reprice",
        }
    )
    repriced = reprice_reports(
        case_output,
        run_output,
        summary_output,
        replacement,
    )
    with case_output.open(encoding="utf-8", newline="") as handle:
        repriced_row = {row["case_id"]: row for row in csv.DictReader(handle)}[
            "s41467-025-63412-3"
        ]
    assert repriced_row["calculated_cost_usd"] == "0.000129"
    assert repriced["calculated_cost_usd"] == pytest.approx(0.000129)
    assert repriced["pricing_source"] == "test_reprice"
