# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""trace_web.py（轨迹可视化 web 服务）单元测试。

复用 test_trace.py 的合成库，验证：payload 纯函数结构正确 + HTTP 端点（/、
/api/sessions、/api/trace）能起服务并返回正确内容。不依赖真实 opencode.db。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from famou_scientist.vis import trace, trace_web
from famou_scientist.tests.test_trace import _make_db  # 复用合成库构造器


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "opencode.db"
    _make_db(p)
    return p


@pytest.fixture()
def con(db_path):
    return trace._connect(db_path)


# ── 纯函数 payload ───────────────────────────────────────────
def test_build_sessions_payload(con):
    rows = trace_web.build_sessions_payload(con, limit=10)
    assert any(r["id"] == "ses_main" for r in rows)


def test_build_trace_payload_main_only(con):
    p = trace_web.build_trace_payload(con, "ses_main", include_children=False, include_steps=True)
    assert p["main"] == "ses_main"
    assert len(p["blocks"]) == 1
    blk = p["blocks"][0]
    assert blk["session"]["kind"] == "session"
    kinds = [e["kind"] for e in blk["events"]]
    assert "tool" in kinds and "text" in kinds
    tool = next(e for e in blk["events"] if e["kind"] == "tool")
    assert tool["tool"] == "arc_search_literature"
    assert tool["input"] == {"query": "X", "limit": 5}
    assert tool["output"] == "found 5 papers"


def test_build_trace_payload_with_children(con):
    p = trace_web.build_trace_payload(con, "ses_main", include_children=True, include_steps=True)
    sids = [b["session"]["session"] for b in p["blocks"]]
    assert sids == ["ses_main", "ses_child"]


def test_build_trace_payload_prefix(con):
    p = trace_web.build_trace_payload(con, "ses_ma", include_children=False, include_steps=True)
    assert p["main"] == "ses_main"


# ── HTTP 端点 smoke ──────────────────────────────────────────
@pytest.fixture()
def server(db_path):
    handler = trace_web._make_handler(db_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # 0 → 系统分配端口
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    host, port = httpd.server_address
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def test_http_index(server):
    code, body = _get(server + "/")
    assert code == 200
    assert "<html" in body.lower() and "trace" in body.lower()


def test_http_sessions(server):
    code, body = _get(server + "/api/sessions")
    assert code == 200
    data = json.loads(body)
    assert any(s["id"] == "ses_main" for s in data["sessions"])


def test_http_trace(server):
    code, body = _get(server + "/api/trace?session=ses_main")
    assert code == 200
    data = json.loads(body)
    assert data["main"] == "ses_main"
    tool = next(e for b in data["blocks"] for e in b["events"] if e["kind"] == "tool")
    assert tool["tool"] == "arc_search_literature"
    assert tool["output"] == "found 5 papers"


def test_http_trace_missing_session(server):
    # 不存在的 session → 404 + error
    try:
        _get(server + "/api/trace?session=ses_nope")
        assert False, "应返回 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
        assert "error" in json.loads(e.read().decode("utf-8"))
