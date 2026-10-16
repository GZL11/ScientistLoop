"""
runners/trace_converter.py — trace 收集与转换

职责：
  1. collect_trace()  — 从 CC / OpenCode 原始存储收集 trace 到 workspace/.eval/
  2. convert_trace()  — 将收集到的 trace 转换为统一 schema（见 docs/trace_collection_design.md）

每个 session（root + 每个 sub-agent）输出一个 JSON 文件到 workspace/.eval/trace/
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── CC converter ──────────────────────────────────────────────────────────────

def _parse_cc_session(jsonl_path: Path) -> dict:
    """Parse a single CC JSONL session file into the unified schema."""
    lines = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Agent name from first agent-setting line
    agent_name = None
    session_id = None
    cwd = None
    for line in lines:
        if line.get("type") == "agent-setting":
            agent_name = line.get("agentSetting")
            session_id = line.get("sessionId")
        if cwd is None and line.get("cwd"):
            cwd = line["cwd"]
        if agent_name and session_id and cwd:
            break

    # Collect timestamps
    timestamps = [l.get("timestamp") for l in lines if l.get("timestamp")]
    started_at = timestamps[0] if timestamps else None
    finished_at = timestamps[-1] if timestamps else None

    turns = []
    stats_tokens = {"input": 0, "output": 0, "total": 0, "cache_read": 0, "cache_write": 0}
    tool_usage: dict[str, int] = {}
    has_thinking = False

    # Build turns: iterate messages, merge tool results into preceding assistant turn
    pending_tool_calls: dict[str, dict] = {}  # tool_use_id → tool_call dict
    last_assistant_turn: dict | None = None  # 用于 tool_result 回填 finished_at
    # CC 的 started_at 需要从上一条 user/tool_result 行的 timestamp 推算
    prev_line_ts: str | None = None  # 上一条 user/tool_result 行的 timestamp

    turn_index = 0
    for line in lines:
        msg = line.get("message")
        if not msg or not isinstance(msg, dict):
            continue

        role = msg.get("role")
        content = msg.get("content", [])
        if not isinstance(content, list):
            content = [{"type": "text", "text": content}] if isinstance(content, str) else []

        if role == "assistant":
            responded = line.get("timestamp")
            turn: dict = {
                "index": turn_index,
                "role": "assistant",
                "thinking": None,
                "text": None,
                "tool_calls": [],
                "tokens": None,
                "started_at": prev_line_ts or started_at,  # 上一条 user/tool_result 的时间
                "responded_at": responded,                  # 模型响应到达
                "finished_at": responded,                   # 无 tool 时等于 responded_at，有 tool 时由 tool_result 回填
            }

            thinking_parts = []
            text_parts = []

            for block in content:
                if not isinstance(block, dict):
                    continue
                t = block.get("type")
                if t == "thinking":
                    has_thinking = True
                    thinking_parts.append(block.get("thinking", ""))
                elif t == "redacted_thinking":
                    has_thinking = True
                    thinking_parts.append("<redacted>")
                elif t == "text":
                    text_parts.append(block.get("text", ""))
                elif t == "tool_use":
                    tool_name = block.get("name", "").lower()
                    tc = {
                        "id": block.get("id", ""),
                        "name": tool_name,
                        "input": block.get("input", {}),
                        "output": None,
                        "status": "running",
                    }
                    turn["tool_calls"].append(tc)
                    pending_tool_calls[block.get("id", "")] = tc
                    tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1

            if thinking_parts:
                turn["thinking"] = "\n".join(thinking_parts)
            if text_parts:
                turn["text"] = "\n".join(text_parts)

            # Token usage from assistant message
            usage = msg.get("usage", {})
            if usage:
                inp = usage.get("input_tokens") or 0
                out = usage.get("output_tokens") or 0
                cache_read = usage.get("cache_read_input_tokens") or 0
                cache_write = usage.get("cache_creation_input_tokens") or 0
                stats_tokens["input"] += inp
                stats_tokens["output"] += out
                stats_tokens["cache_read"] += cache_read
                stats_tokens["cache_write"] += cache_write

            last_assistant_turn = turn
            turns.append(turn)
            turn_index += 1

            # 纯文本 turn 结束后更新 prev_line_ts，避免下一个 turn 拿到旧的 started_at
            if not turn["tool_calls"]:
                prev_line_ts = responded

        elif role == "user":
            # content may be a plain string (initial instruction) or a list of blocks
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            text_parts = []
            has_tool_results = False
            for block in content:
                if not isinstance(block, dict):
                    continue
                t = block.get("type")
                if t == "tool_result":
                    has_tool_results = True
                    # Fill in pending tool call output
                    tool_use_id = block.get("tool_use_id", "")
                    if tool_use_id in pending_tool_calls:
                        tc = pending_tool_calls.pop(tool_use_id)
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = "\n".join(
                                b.get("text", "") for b in result_content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        tc["output"] = result_content
                        tc["status"] = "error" if block.get("is_error") else "success"
                elif t == "text":
                    text_parts.append(block.get("text", ""))

            # tool_result 行的 timestamp = tool 执行完成时间，回填到所属 assistant turn
            if has_tool_results and last_assistant_turn is not None:
                last_assistant_turn["finished_at"] = line.get("timestamp")

            # 记录 user/tool_result 行的 timestamp，作为下一个 assistant turn 的 started_at
            prev_line_ts = line.get("timestamp")

            # Include user turns that have text content (e.g. initial instruction)
            if text_parts:
                ts = line.get("timestamp")
                turns.append({
                    "index": turn_index,
                    "role": "user",
                    "thinking": None,
                    "text": "\n".join(text_parts),
                    "tool_calls": [],
                    "tokens": None,
                    "started_at": ts,
                    "responded_at": ts,
                    "finished_at": ts,
                })
                turn_index += 1

    stats_tokens["total"] = (
        stats_tokens["input"] + stats_tokens["output"]
        + stats_tokens["cache_read"] + stats_tokens["cache_write"]
    )

    # session finished_at = 最后一个 turn 的 finished_at
    if turns:
        finished_at = turns[-1].get("finished_at") or finished_at

    return {
        "schema_version": "1",
        "session": {
            "id": session_id,
            "agent": agent_name,
            "runner": "cc",
            "parent_id": None,      # filled by caller for sub-agents
            "workspace": cwd,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "turns": turns,
        "stats": {
            "turn_count": len([t for t in turns if t["role"] == "assistant"]),
            "tokens": stats_tokens,
            "tool_usage": tool_usage,
            "has_thinking": has_thinking,
        },
    }


def convert_cc_trace(trace_cc_dir: Path, output_dir: Path, root_session_id: str) -> None:
    """Convert all CC JSONL files in trace_cc_dir to unified schema in output_dir."""
    if not trace_cc_dir.exists():
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Root session file: matches root_session_id
    root_jsonl = trace_cc_dir / f"{root_session_id}.jsonl"
    if root_jsonl.exists():
        schema = _parse_cc_session(root_jsonl)
        # session_id from parse may be None if agent-setting missing; fallback
        sid = schema["session"]["id"] or root_session_id
        schema["session"]["id"] = sid
        (output_dir / f"{sid}.json").write_text(
            json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Sub-agent sessions: agent-*.jsonl
    for jsonl_path in sorted(trace_cc_dir.glob("agent-*.jsonl")):
        schema = _parse_cc_session(jsonl_path)
        # Sub-agents: parent is root session
        schema["session"]["parent_id"] = root_session_id

        # Agent name from meta.json if available
        meta_path = jsonl_path.with_suffix("").with_suffix(".meta.json")
        if not meta_path.exists():
            meta_path = trace_cc_dir / (jsonl_path.stem + ".meta.json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                schema["session"]["agent"] = meta.get("agentType", schema["session"]["agent"])
            except Exception:
                pass

        # Use agentId from filename as session id for sub-agents
        agent_id = jsonl_path.stem  # e.g. "agent-aabd057266f6390d9"
        schema["session"]["id"] = schema["session"]["id"] or agent_id
        sid = schema["session"]["id"]
        (output_dir / f"{sid}.json").write_text(
            json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# ── OpenCode converter ────────────────────────────────────────────────────────

def _parse_opencode_session(export_path: Path) -> dict:
    """Parse an OpenCode export JSON file into the unified schema."""
    data = json.loads(export_path.read_text(encoding="utf-8"))
    info = data.get("info", {})

    session_id = info.get("id")
    parent_id = info.get("parentID") or None
    workspace = info.get("directory")
    time_info = info.get("time", {})
    started_at = _ms_to_iso(time_info.get("created"))
    finished_at = _ms_to_iso(time_info.get("updated"))

    # Agent name: parse from title "xxx (@agent-name subagent)" or fall back to config
    title = info.get("title", "")
    m = re.search(r'\(@([\w-]+)\s+subagent\)', title)
    agent_name = m.group(1) if m else None

    turns = []
    stats_tokens = {"input": 0, "output": 0, "total": 0, "cache_read": 0, "cache_write": 0}
    tool_usage: dict[str, int] = {}
    has_thinking = False
    turn_index = 0

    for msg in data.get("messages", []):
        msg_info = msg.get("info", {})
        role = msg_info.get("role")
        if role not in ("user", "assistant"):
            continue

        parts = msg.get("parts", [])

        # Skip messages with only step-start/finish
        meaningful = [p for p in parts if p.get("type") not in ("step-start", "step-finish", "compaction")]
        if not meaningful and role == "assistant":
            continue

        turn_started = _ms_to_iso(msg_info.get("time", {}).get("created"))
        # user turn: 三个时间字段都等于 created；assistant turn: 后续填充
        is_user = (role == "user")
        turn: dict = {
            "index": turn_index,
            "role": role,
            "thinking": None,
            "text": None,
            "tool_calls": [],
            "tokens": None,
            "started_at": turn_started,
            "responded_at": turn_started if is_user else None,
            "finished_at": turn_started if is_user else None,
        }

        thinking_parts = []
        text_parts = []
        first_tool_start_ms: int | None = None
        last_tool_end_ms: int | None = None

        for part in parts:
            pt = part.get("type")
            if pt == "reasoning":          # OpenCode uses "reasoning", not "thinking"
                has_thinking = True
                thinking_parts.append(part.get("text", ""))
            elif pt == "text":
                text_parts.append(part.get("text", ""))
            elif pt == "tool":
                state = part.get("state", {})
                tool_name = part.get("tool", "").lower()
                raw_status = state.get("status", "running")
                status = "success" if raw_status == "completed" else raw_status
                output = state.get("output")
                if isinstance(output, dict):
                    output = json.dumps(output, ensure_ascii=False)
                tc = {
                    "id": part.get("callID", ""),
                    "name": tool_name,
                    "input": state.get("input", {}),
                    "output": output,
                    "status": status,
                }
                turn["tool_calls"].append(tc)
                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
                # 记录第一个 tool 开始时间和最后一个 tool 结束时间
                tool_start = state.get("time", {}).get("start")
                tool_end = state.get("time", {}).get("end")
                if tool_start and (first_tool_start_ms is None or tool_start < first_tool_start_ms):
                    first_tool_start_ms = tool_start
                if tool_end and (last_tool_end_ms is None or tool_end > last_tool_end_ms):
                    last_tool_end_ms = tool_end

        if first_tool_start_ms is not None:
            turn["responded_at"] = _ms_to_iso(first_tool_start_ms)
        if last_tool_end_ms is not None:
            turn["finished_at"] = _ms_to_iso(last_tool_end_ms)
        elif first_tool_start_ms is not None:
            # tool 有 start 但没 end（running/崩溃），finished_at 降级为 responded_at
            turn["finished_at"] = turn["responded_at"]

        if thinking_parts:
            turn["thinking"] = "\n".join(thinking_parts)
            has_thinking = True
        if text_parts:
            turn["text"] = "\n".join(text_parts)

        # Per-turn tokens
        tok = msg_info.get("tokens")
        if tok:
            turn["tokens"] = {
                "input": tok.get("input", 0),
                "output": tok.get("output", 0),
            }
            stats_tokens["input"] += tok.get("input", 0)
            stats_tokens["output"] += tok.get("output", 0)
            cache = tok.get("cache", {})
            stats_tokens["cache_read"] += cache.get("read", 0)
            stats_tokens["cache_write"] += cache.get("write", 0)

        turns.append(turn)
        turn_index += 1

    # 后处理：纯文本 assistant turn 的 responded_at/finished_at 从下一个 turn 的 started_at 推算
    for i, turn in enumerate(turns):
        if turn["role"] == "assistant" and turn["responded_at"] is None:
            # 纯文本 turn：模型响应到达 = turn 结束
            if i + 1 < len(turns):
                turn["responded_at"] = turns[i + 1]["started_at"]
                turn["finished_at"] = turns[i + 1]["started_at"]
            else:
                # 最后一个 turn：用 session finished_at
                turn["responded_at"] = finished_at
                turn["finished_at"] = finished_at

    stats_tokens["total"] = (
        stats_tokens["input"] + stats_tokens["output"]
        + stats_tokens["cache_read"] + stats_tokens["cache_write"]
    )

    # session finished_at = 最后一个 turn 的 finished_at
    if turns:
        finished_at = turns[-1].get("finished_at") or finished_at

    return {
        "schema_version": "1",
        "session": {
            "id": session_id,
            "agent": agent_name,
            "runner": "opencode",
            "parent_id": parent_id,
            "workspace": workspace,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "turns": turns,
        "stats": {
            "turn_count": len([t for t in turns if t["role"] == "assistant"]),
            "tokens": stats_tokens,
            "tool_usage": tool_usage,
            "has_thinking": has_thinking,
        },
    }


def convert_opencode_trace(trace_opencode_dir: Path, output_dir: Path) -> None:
    """Convert all OpenCode export JSON files to unified schema in output_dir."""
    if not trace_opencode_dir.exists():
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read default_agent from workspace opencode.jsonc (parent of .eval/trace_opencode)
    workspace = trace_opencode_dir.parent.parent
    default_agent = None
    oc_config = workspace / ".opencode" / "opencode.jsonc"
    if oc_config.exists():
        try:
            cfg = json.loads(oc_config.read_text())
            default_agent = cfg.get("default_agent")
        except Exception:
            pass

    for export_path in sorted(trace_opencode_dir.glob("*.json")):
        try:
            schema = _parse_opencode_session(export_path)
        except Exception as e:
            print(f"[WARN] failed to parse {export_path.name}: {e}", file=sys.stderr)
            continue

        # Fill agent name for root sessions
        if schema["session"]["agent"] is None and schema["session"]["parent_id"] is None:
            schema["session"]["agent"] = default_agent

        sid = schema["session"]["id"] or export_path.stem
        (output_dir / f"{sid}.json").write_text(
            json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# ── Trace collection ─────────────────────────────────────────────────────────

def _collect_cc_trace(workspace: Path, session_id: str) -> None:
    """Copy root + all sub-agent JSONL sessions to .eval/trace_cc/."""
    import shutil

    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return

    matches = list(projects_dir.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return

    project_dir = matches[0].parent
    trace_dir = workspace / ".eval" / "trace_cc"
    trace_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(matches[0], trace_dir / f"{session_id}.jsonl")

    sub_dir = project_dir / session_id / "subagents"
    if sub_dir.exists():
        for f in sub_dir.iterdir():
            if f.suffix in (".jsonl", ".json"):
                shutil.copy2(f, trace_dir / f.name)

    print(f"  trace_cc → {trace_dir}")


def _collect_opencode_trace(workspace: Path) -> None:
    """Export all sessions (root + sub-agents) for this workspace via opencode export.

    Fix 2 之后每个 workspace 自带 .opencode_data/opencode/opencode.db；
    旧实验仍指向用户全局 DB ~/.local/share/opencode/opencode.db。
    """
    import os
    import sqlite3
    import subprocess

    # 优先 workspace 本地隔离 DB（Fix 2），fallback 到全局 DB（兼容旧实验）
    local_data_home = workspace / ".opencode_data"
    local_db = local_data_home / "opencode" / "opencode.db"
    if local_db.exists():
        db = local_db
        # 让 opencode export 也读这份隔离 DB
        export_env = {**os.environ, "XDG_DATA_HOME": str(local_data_home)}
    else:
        db = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
        export_env = None

    if not db.exists():
        return

    trace_dir = workspace / ".eval" / "trace_opencode"
    trace_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db))

    def _collect_recursive(sid: str) -> None:
        out_path = trace_dir / f"{sid}.json"
        with open(out_path, "w", encoding="utf-8") as fout:
            result = subprocess.run(
                ["opencode", "export", sid],
                stdout=fout, stderr=subprocess.DEVNULL,
                env=export_env,
            )
        if result.returncode != 0 or out_path.stat().st_size == 0:
            out_path.unlink(missing_ok=True)
        children = conn.execute(
            "SELECT id FROM session WHERE parent_id = ?", (sid,)
        ).fetchall()
        for (child_id,) in children:
            _collect_recursive(child_id)

    roots = conn.execute(
        "SELECT id FROM session WHERE directory = ?", (str(workspace),)
    ).fetchall()
    for (root_id,) in roots:
        _collect_recursive(root_id)

    conn.close()
    print(f"  trace_opencode → {trace_dir}")


def collect_trace(runner_type: str, workspace: Path, session_id: str | None) -> None:
    """收集原始 trace 文件到 workspace/.eval/trace_cc 或 trace_opencode。"""
    try:
        if runner_type.startswith("cc_") and session_id:
            _collect_cc_trace(workspace, session_id)
        elif runner_type.startswith("opencode_"):
            _collect_opencode_trace(workspace)
    except Exception as e:
        print(f"[WARN] trace collection failed: {e}", file=sys.stderr)


# ── Trace conversion ─────────────────────────────────────────────────────────

def convert_trace(runner_type: str, workspace: Path, session_id: str | None) -> None:
    """Convert raw traces to unified schema. Called after collect_trace()."""
    eval_dir = workspace / ".eval"
    output_dir = eval_dir / "trace"
    try:
        if runner_type.startswith("cc_") and session_id:
            convert_cc_trace(eval_dir / "trace_cc", output_dir, session_id)
            print(f"  trace     → {output_dir}")
        elif runner_type.startswith("opencode_"):
            convert_opencode_trace(eval_dir / "trace_opencode", output_dir)
            print(f"  trace     → {output_dir}")
    except Exception as e:
        print(f"[WARN] trace conversion failed: {e}", file=sys.stderr)


def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
