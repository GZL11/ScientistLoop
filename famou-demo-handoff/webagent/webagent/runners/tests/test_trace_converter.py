"""trace_converter 的单元测试：turn 时间字段语义、token 统计。"""

import json
import tempfile
from pathlib import Path

from webagent.runners.trace_converter import _parse_cc_session, _parse_opencode_session


# ── CC converter ──────────────────────────────────────────────────────────────


def test_cc_text_only_turn_times():
    """纯文本 turn：responded_at == finished_at，started_at 来自上一条 user 行。"""
    lines = [
        {"timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "hello"}},
        {"timestamp": "2026-01-01T00:00:05Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
        path = Path(f.name)

    schema = _parse_cc_session(path)
    path.unlink()

    turn = [t for t in schema["turns"] if t["role"] == "assistant"][0]
    assert turn["started_at"] == "2026-01-01T00:00:00Z"  # from user msg
    assert turn["responded_at"] == "2026-01-01T00:00:05Z"
    assert turn["finished_at"] == "2026-01-01T00:00:05Z"  # text-only: same as responded


def test_cc_tool_turn_three_timestamps():
    """有 tool 的 turn：started_at < responded_at < finished_at。"""
    lines = [
        {"timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "run it"}},
        {"timestamp": "2026-01-01T00:00:05Z", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "sleep 30"}},
        ]}},
        {"timestamp": "2026-01-01T00:00:35Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "done"},
        ]}},
        {"timestamp": "2026-01-01T00:00:40Z", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "done"},
        ]}},
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
        path = Path(f.name)

    schema = _parse_cc_session(path)
    path.unlink()

    turns = schema["turns"]
    tool_turn = [t for t in turns if t["tool_calls"]][0]
    assert tool_turn["started_at"] == "2026-01-01T00:00:00Z"   # from user msg
    assert tool_turn["responded_at"] == "2026-01-01T00:00:05Z"  # model response
    assert tool_turn["finished_at"] == "2026-01-01T00:00:35Z"   # tool_result

    # next turn's started_at = previous tool_result timestamp
    text_turn = [t for t in turns if t["role"] == "assistant" and not t["tool_calls"]][0]
    assert text_turn["started_at"] == "2026-01-01T00:00:35Z"

    # session finished_at = last turn's finished_at
    assert schema["session"]["finished_at"] == text_turn["finished_at"]


def test_cc_token_no_double_counting():
    """cache_write 不应被重复计入 total。"""
    lines = [
        {"timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "go"}},
        {"timestamp": "2026-01-01T00:00:05Z", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "ok"},
        ], "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 30,
        }}},
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
        path = Path(f.name)

    schema = _parse_cc_session(path)
    path.unlink()

    tok = schema["stats"]["tokens"]
    assert tok["input"] == 100
    assert tok["output"] == 50
    assert tok["cache_read"] == 200
    assert tok["cache_write"] == 30
    assert tok["total"] == 100 + 50 + 200 + 30


# ── OpenCode converter ────────────────────────────────────────────────────────


def test_opencode_tool_turn_three_timestamps():
    """OpenCode: 有 tool 的 turn，started_at/responded_at/finished_at 分离。"""
    data = {
        "info": {
            "id": "ses_test",
            "directory": "/tmp/test",
            "time": {"created": 1700000000000, "updated": 1700000100000},
        },
        "messages": [
            {
                "info": {"role": "user", "time": {"created": 1700000000000}},
                "parts": [{"type": "text", "text": "go"}],
            },
            {
                "info": {"role": "assistant", "time": {"created": 1700000010000}},
                "parts": [
                    {"type": "step-start", "id": "1", "sessionID": "s", "messageID": "m"},
                    {"type": "reasoning", "text": "...", "time": {"start": 1700000010100, "end": 1700000010500}, "id": "1", "sessionID": "s", "messageID": "m"},
                    {"type": "tool", "tool": "bash", "callID": "c1", "state": {
                        "status": "completed",
                        "input": {"command": "echo"},
                        "output": "hi",
                        "time": {"start": 1700000015000, "end": 1700000040000},
                    }, "id": "1", "sessionID": "s", "messageID": "m"},
                    {"type": "step-finish", "reason": "done", "tokens": {}, "cost": 0, "id": "1", "sessionID": "s", "messageID": "m"},
                ],
            },
            {
                "info": {"role": "assistant", "time": {"created": 1700000041000}},
                "parts": [
                    {"type": "step-start", "id": "2", "sessionID": "s", "messageID": "m"},
                    {"type": "text", "text": "done", "time": {}, "id": "2", "sessionID": "s", "messageID": "m"},
                    {"type": "step-finish", "reason": "done", "tokens": {}, "cost": 0, "id": "2", "sessionID": "s", "messageID": "m"},
                ],
            },
        ],
    }

    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(data, f)
        path = Path(f.name)

    schema = _parse_opencode_session(path)
    path.unlink()

    turns = schema["turns"]

    # tool turn: three distinct timestamps
    tool_turn = [t for t in turns if t["tool_calls"]][0]
    assert tool_turn["started_at"] is not None
    assert tool_turn["responded_at"] is not None
    assert tool_turn["finished_at"] is not None
    assert tool_turn["started_at"] < tool_turn["responded_at"]   # model took time
    assert tool_turn["responded_at"] <= tool_turn["finished_at"]  # tool took time

    # text-only turn: responded_at == finished_at (from session end since it's the last turn)
    text_turn = [t for t in turns if t["role"] == "assistant" and not t["tool_calls"]][0]
    assert text_turn["responded_at"] == text_turn["finished_at"]

    # session finished_at = last turn's finished_at
    assert schema["session"]["finished_at"] == turns[-1]["finished_at"]
