# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""opencode 轨迹可视化 web 服务（`famou-scientist trace --web`）。

纯 stdlib 的本地 HTTP 服务，给一个**直观的网页**看会话轨迹：搜索 / 选择
``session_id`` → 渲染完整时间线（对话气泡 + 工具调用入参/结果 + skill 加载等）。

数据逻辑全部复用 ``trace.py``（``list_sessions`` / ``session_header`` /
``iter_events`` / ``_child_sessions`` / ``_resolve_session``），本模块只做
HTTP + JSON 封装。前端是同目录的单文件 ``trace_viewer.html``（vanilla JS，无构建）。

端点（仅 GET，只读 opencode.db）：
- ``/``                                  → 返回 trace_viewer.html
- ``/api/sessions?limit=&directory=``    → 会话列表（侧栏/搜索）
- ``/api/trace?session=&children=&steps=`` → 某会话轨迹（blocks/events）

安全：默认绑 ``127.0.0.1``（会话含对话内容，不默认对外）；只读连接，不影响正在跑的 opencode。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import trace

VIEWER_HTML = Path(__file__).parent / "trace_viewer.html"


# ── 纯函数 payload（可单测，不起 HTTP）────────────────────────
def build_sessions_payload(con, limit: int = 50, directory: str = "") -> list[dict]:
    """会话列表（复用 trace.list_sessions）。"""
    return trace.list_sessions(con, limit=limit, directory=directory)


def build_trace_payload(con, session_id: str, *, include_children: bool, include_steps: bool) -> dict:
    """某会话（+可选子会话）的轨迹：{main, blocks:[{session, events:[...]}, ...]}。"""
    sid = trace._resolve_session(con, session_id)
    sids = [sid] + (trace._child_sessions(con, sid) if include_children else [])
    blocks = []
    for s in sids:
        events = list(trace.iter_events(con, s, include_steps=include_steps, raw=False))
        blocks.append({"session": trace.session_header(con, s), "events": events})
    return {"main": sid, "blocks": blocks}


# ── HTTP ──────────────────────────────────────────────────────
def _make_handler(db_path: Path):
    """闭包出一个带 db_path 的 handler 类。"""

    class Handler(BaseHTTPRequestHandler):
        # 静默默认的逐请求 stderr 日志（保留致命错误）
        def log_message(self, fmt, *args):  # noqa: N802
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            path, q = u.path, parse_qs(u.query)
            try:
                if path == "/" or path == "/index.html":
                    if not VIEWER_HTML.exists():
                        self._send(500, b"trace_viewer.html missing", "text/plain; charset=utf-8")
                        return
                    self._send(200, VIEWER_HTML.read_bytes(), "text/html; charset=utf-8")
                    return

                if path == "/api/sessions":
                    con = trace._connect(db_path)
                    try:
                        rows = build_sessions_payload(
                            con,
                            limit=int((q.get("limit") or ["80"])[0]),
                            directory=(q.get("directory") or [""])[0],
                        )
                    finally:
                        con.close()
                    self._json({"sessions": rows})
                    return

                if path == "/api/trace":
                    sid = (q.get("session") or [""])[0].strip()
                    if not sid:
                        self._json({"error": "缺少 session 参数"}, 400)
                        return
                    con = trace._connect(db_path)
                    try:
                        payload = build_trace_payload(
                            con, sid,
                            include_children=(q.get("children") or ["0"])[0] in ("1", "true"),
                            include_steps=(q.get("steps") or ["1"])[0] in ("1", "true"),
                        )
                    finally:
                        con.close()
                    self._json(payload)
                    return

                self._send(404, b"not found", "text/plain; charset=utf-8")
            except SystemExit as e:  # _resolve_session 未命中
                self._json({"error": str(e)}, 404)
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    """起本地 web 服务看轨迹。端口被占用则自动 +1 试几个。"""
    if not db_path.exists():
        print(f"找不到 opencode 数据库：{db_path}（用 --db 指定，或设 OPENCODE_DB）", file=sys.stderr)
        return 2
    if not VIEWER_HTML.exists():
        print(f"缺少前端文件：{VIEWER_HTML}", file=sys.stderr)
        return 2

    handler = _make_handler(db_path)
    httpd = None
    chosen = port
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer((host, p), handler)
            chosen = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"端口 {port}~{port + 9} 都被占用，换 --port 指定。", file=sys.stderr)
        return 2

    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{chosen}"
    print(f"轨迹可视化已启动：{url}   （读 {db_path}，只读）", file=sys.stderr)
    print("按 Ctrl-C 停止。", file=sys.stderr)
    if host == "0.0.0.0":
        print("⚠️ 绑定 0.0.0.0：会话内容（含对话）会对同网段开放，注意安全。", file=sys.stderr)
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0
