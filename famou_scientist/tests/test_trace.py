# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""trace.py（opencode 轨迹观察）单元测试。

用合成的临时 sqlite（与 opencode.db 同结构的最小子集）验证：列会话、按 rowid 拼
轨迹、tool 事件含 input/output/耗时、前缀解析、子会话折叠。不依赖真实 opencode.db。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import io
import json
import sqlite3

import pytest

from famou_scientist.vis import trace


def _make_db(path):
    """建一个含 session/message/part 的最小库，塞一条主会话 + 一条子会话轨迹。"""
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, title TEXT,
            directory TEXT, model TEXT, agent TEXT, cost REAL DEFAULT 0,
            time_created INTEGER, time_updated INTEGER,
            tokens_input INTEGER DEFAULT 0, tokens_output INTEGER DEFAULT 0,
            tokens_reasoning INTEGER DEFAULT 0, tokens_cache_read INTEGER DEFAULT 0,
            tokens_cache_write INTEGER DEFAULT 0
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
            time_created INTEGER, data TEXT
        );
        """
    )
    # 主会话
    con.execute(
        "INSERT INTO session(id,project_id,parent_id,title,directory,model,agent,cost,time_created,time_updated)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("ses_main", "p", None, "测试会话", "/tmp/run",
         json.dumps({"id": "claude-sonnet-4-6", "modelID": "claude-sonnet-4-6"}),
         "build", 0.01, 1000, 2000),
    )
    # 子会话（subagent）
    con.execute(
        "INSERT INTO session(id,project_id,parent_id,title,directory,model,agent,time_created,time_updated)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        ("ses_child", "p", "ses_main", "代码审查 subagent", "/tmp/run", "{}", "general", 1500, 1600),
    )
    # 主会话消息：user 文本 + assistant（文本 + tool）
    con.execute("INSERT INTO message(id,session_id,time_created,data) VALUES(?,?,?,?)",
                ("m1", "ses_main", 1001, json.dumps({"role": "user", "time": {"created": 1001}})))
    con.execute("INSERT INTO message(id,session_id,time_created,data) VALUES(?,?,?,?)",
                ("m2", "ses_main", 1002, json.dumps({"role": "assistant", "agent": "build", "time": {"created": 1002}})))
    # part 按插入顺序（rowid 单调）= 期望轨迹顺序
    parts = [
        ("p1", "m1", "ses_main", 1001, {"type": "text", "text": "帮我研究 X"}),
        ("p2", "m2", "ses_main", 1002, {"type": "text", "text": "好的，先建目录"}),
        ("p3", "m2", "ses_main", 1003, {"type": "step-start", "snapshot": "h"}),
        ("p4", "m2", "ses_main", 1004, {
            "type": "tool", "tool": "arc_search_literature", "callID": "c1",
            "state": {"status": "completed", "input": {"query": "X", "limit": 5},
                      "output": "found 5 papers", "time": {"start": 1004, "end": 1010}}}),
        ("p5", "m2", "ses_main", 1005, {"type": "patch", "hash": "abc", "files": ["/tmp/run/a.md"]}),
    ]
    for pid, mid, sid, ts, d in parts:
        con.execute("INSERT INTO part(id,message_id,session_id,time_created,data) VALUES(?,?,?,?,?)",
                    (pid, mid, sid, ts, json.dumps(d, ensure_ascii=False)))
    # 子会话一条 tool
    con.execute("INSERT INTO message(id,session_id,time_created,data) VALUES(?,?,?,?)",
                ("mc", "ses_child", 1501, json.dumps({"role": "assistant", "agent": "general"})))
    con.execute("INSERT INTO part(id,message_id,session_id,time_created,data) VALUES(?,?,?,?,?)",
                ("pc", "mc", "ses_child", 1501,
                 json.dumps({"type": "text", "text": "审查通过"}, ensure_ascii=False)))
    con.commit()
    con.close()


def _emit(con, sid, **kw):
    buf = io.StringIO()
    opts = dict(include_children=False, include_steps=True, raw=False)
    opts.update(kw)
    trace.emit_trajectory(con, sid, buf, **opts)
    return [json.loads(x) for x in buf.getvalue().splitlines()]


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "opencode.db"
    _make_db(p)
    return trace._connect(p)


def test_list_sessions(db):
    rows = trace.list_sessions(db, limit=10)
    ids = {r["id"]: r for r in rows}
    assert "ses_main" in ids and "ses_child" in ids
    assert ids["ses_main"]["messages"] == 2
    assert ids["ses_main"]["model"] == "claude-sonnet-4-6"
    assert ids["ses_child"]["parent_id"] == "ses_main"


def test_trajectory_order_and_tool(db):
    lines = _emit(db, "ses_main")
    assert lines[0]["kind"] == "session"
    assert lines[0]["title"] == "测试会话"
    kinds = [l["kind"] for l in lines[1:]]
    # rowid 顺序：text, text, step, tool, patch
    assert kinds == ["text", "text", "step", "tool", "patch"]
    tool = next(l for l in lines if l["kind"] == "tool")
    assert tool["tool"] == "arc_search_literature"
    assert tool["input"] == {"query": "X", "limit": 5}
    assert tool["output"] == "found 5 papers"
    assert tool["ms"] == 6  # end-start
    assert tool["role"] == "assistant"
    # user 文本带 user 角色
    assert lines[1]["role"] == "user" and lines[1]["text"] == "帮我研究 X"


def test_no_steps_filter(db):
    kinds = [l["kind"] for l in _emit(db, "ses_main", include_steps=False)]
    assert "step" not in kinds


def test_prefix_resolution(db):
    lines = _emit(db, "ses_ma")  # 前缀
    assert lines[0]["session"] == "ses_main"


def test_include_children(db):
    lines = _emit(db, "ses_main", include_children=True)
    sessions = [l["session"] for l in lines if l["kind"] == "session"]
    assert sessions == ["ses_main", "ses_child"]


def test_raw_mode(db):
    lines = _emit(db, "ses_main", raw=True)
    # raw 行保留原始 part.data
    tool = next(l for l in lines if l.get("data", {}).get("type") == "tool")
    assert tool["data"]["tool"] == "arc_search_literature"


def test_unknown_session_raises(db):
    with pytest.raises(SystemExit):
        _emit(db, "ses_nope")
