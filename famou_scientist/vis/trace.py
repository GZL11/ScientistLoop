# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""opencode 轨迹观察工具：把一个 session 的完整轨迹导成干净的 JSONL。

OpenCode 把会话持久化在 SQLite（`~/.local/share/opencode/opencode.db`）：
- ``session``：会话元信息（id/title/directory/agent/model/cost/tokens…）
- ``message``：每条消息（role=user/assistant、time、agent、model…，data 为 JSON）
- ``part``  ：消息内的各部分（type=text/reasoning/tool/step-*/patch…，data 为 JSON）
  其中 **tool part** 最关键：``state={status,input,output,metadata,time}``——
  工具名 + 入参 + 结果 + 耗时齐全，是轨迹里最有信息量的事件。

本工具**只读**该库，按 ``rowid``（全局单调＝真实时间序）把 message+part 拼成一条
线性轨迹，每个事件一行 JSON。用法：

    famou-scientist trace                       # 列出最近会话（找 session_id）
    famou-scientist trace <session_id>          # 导出该会话完整轨迹（JSONL→stdout）
    famou-scientist trace <session_id> --include-children   # 连同 subagent 子会话
    famou-scientist trace <session_id> --raw --out trace.jsonl

注：单次启动的 TUI 里每轮对话是一个 session；task/reviewer 子 agent 会另开
**子 session**（parent_id 指向主会话），故子 agent 轨迹需 ``--include-children``。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


# ── 定位 opencode 数据库 ──────────────────────────────────────
def default_db_path() -> Path:
    """opencode.db 默认路径：OPENCODE_DB > $XDG_DATA_HOME/opencode > ~/.local/share/opencode。"""
    env = os.environ.get("OPENCODE_DB")
    if env:
        return Path(env)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(Path.home(), ".local", "share")
    return Path(base) / "opencode" / "opencode.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    """只读打开（不锁库、不碰用户正在用的会话）。"""
    if not db_path.exists():
        raise FileNotFoundError(f"找不到 opencode 数据库：{db_path}（用 --db 指定，或设 OPENCODE_DB）")
    # CFS/跨用户 trace 库常位于当前进程不可写目录；SQLite 即便 mode=ro 也可能尝试访问
    # journal/WAL 元数据并报 unable to open database file。immutable=1 明确声明只读快照，
    # 不创建/检查旁路文件，适合 trace viewer 这种只读历史库。
    con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _iso(ms) -> str:
    """epoch 毫秒 → ISO8601 本地时间字符串（拿不到就原样返回）。"""
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ms) / 1000).isoformat(timespec="seconds")
    except Exception:
        return str(ms)


def _loads(s):
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return {}


# ── 列出会话 ──────────────────────────────────────────────────
def list_sessions(con: sqlite3.Connection, limit: int = 30, directory: str = "") -> list[dict]:
    """按最近更新列会话，附消息数，便于挑 session_id。"""
    q = "SELECT id,title,directory,agent,model,parent_id,cost,time_created,time_updated FROM session"
    params: list = []
    if directory:
        q += " WHERE directory LIKE ?"
        params.append(f"%{directory}%")
    q += " ORDER BY time_updated DESC LIMIT ?"
    params.append(limit)
    out = []
    for r in con.execute(q, params):
        n = con.execute("SELECT COUNT(*) FROM message WHERE session_id=?", (r["id"],)).fetchone()[0]
        model = _loads(r["model"]).get("modelID") or _loads(r["model"]).get("id") or ""
        out.append({
            "id": r["id"], "title": r["title"], "directory": r["directory"],
            "agent": r["agent"], "model": model, "parent_id": r["parent_id"],
            "messages": n, "cost": r["cost"], "updated": _iso(r["time_updated"]),
        })
    return out


def _resolve_session(con: sqlite3.Connection, session_id: str) -> str:
    """精确 id 命中即用；否则按前缀模糊匹配（唯一才用，多个则报错列出）。"""
    if con.execute("SELECT 1 FROM session WHERE id=?", (session_id,)).fetchone():
        return session_id
    rows = con.execute("SELECT id,title FROM session WHERE id LIKE ? ORDER BY time_updated DESC",
                       (f"{session_id}%",)).fetchall()
    if len(rows) == 1:
        return rows[0]["id"]
    if not rows:
        raise SystemExit(f"未找到 session：{session_id}（用 `trace` 不带参数列出可用会话）")
    raise SystemExit("前缀匹配到多个 session，请给更完整的 id：\n" +
                     "\n".join(f"  {r['id']}  {r['title']}" for r in rows[:10]))


# ── 拼轨迹 ────────────────────────────────────────────────────
def _message_index(con: sqlite3.Connection, sid: str) -> dict[str, dict]:
    """message_id → {role, agent, ts}，供给每个 part 贴上角色。"""
    idx = {}
    for r in con.execute("SELECT id,time_created,data FROM message WHERE session_id=?", (sid,)):
        d = _loads(r["data"])
        idx[r["id"]] = {
            "role": d.get("role", ""),
            "agent": d.get("agent", ""),
            "ts": (d.get("time") or {}).get("created") or r["time_created"],
        }
    return idx


def iter_events(con: sqlite3.Connection, sid: str, *, include_steps: bool, raw: bool):
    """按 rowid（真实时间序）产出该 session 的规范化事件 dict（或 raw part）。"""
    msgidx = _message_index(con, sid)
    seq = 0
    for r in con.execute(
        "SELECT rowid,message_id,time_created,data FROM part WHERE session_id=? ORDER BY rowid", (sid,)
    ):
        d = _loads(r["data"])
        kind = d.get("type", "")
        if kind in ("step-start", "step-finish") and not include_steps:
            continue
        m = msgidx.get(r["message_id"], {})
        seq += 1
        base = {
            "i": seq, "t": _iso(r["time_created"]), "session": sid,
            "msg": r["message_id"], "role": m.get("role", ""),
        }
        if m.get("agent"):
            base["agent"] = m["agent"]
        if raw:
            base["kind"] = kind
            base["data"] = d
            yield base
            continue
        if kind == "text":
            base.update(kind="text", text=d.get("text", ""))
        elif kind == "reasoning":
            base.update(kind="reasoning", text=d.get("text", ""))
        elif kind == "tool":
            st = d.get("state", {}) or {}
            t = st.get("time") or {}
            ev = {
                **base, "kind": "tool", "tool": d.get("tool", ""),
                "call": d.get("callID", ""), "status": st.get("status", ""),
                "input": st.get("input"), "output": st.get("output"),
            }
            if st.get("error"):
                ev["error"] = st["error"]
            if t.get("start") and t.get("end"):
                ev["ms"] = t["end"] - t["start"]
            yield ev
            continue
        elif kind in ("step-start", "step-finish"):
            base.update(kind="step", phase=kind.split("-", 1)[1], reason=d.get("reason"),
                        tokens=d.get("tokens"), cost=d.get("cost"))
        elif kind == "patch":
            base.update(kind="patch", files=d.get("files"), hash=d.get("hash"))
        else:
            base.update(kind=kind or "unknown", data=d)
        yield base


def session_header(con: sqlite3.Connection, sid: str) -> dict:
    r = con.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
    n = con.execute("SELECT COUNT(*) FROM message WHERE session_id=?", (sid,)).fetchone()[0]
    return {
        "i": 0, "kind": "session", "session": sid, "title": r["title"],
        "directory": r["directory"], "agent": r["agent"],
        "model": _loads(r["model"]).get("modelID") or _loads(r["model"]).get("id") or "",
        "parent": r["parent_id"], "created": _iso(r["time_created"]),
        "updated": _iso(r["time_updated"]), "messages": n, "cost": r["cost"],
        "tokens": {"input": r["tokens_input"], "output": r["tokens_output"],
                   "reasoning": r["tokens_reasoning"],
                   "cache_read": r["tokens_cache_read"], "cache_write": r["tokens_cache_write"]},
    }


def _child_sessions(con: sqlite3.Connection, sid: str) -> list[str]:
    return [r["id"] for r in con.execute(
        "SELECT id FROM session WHERE parent_id=? ORDER BY time_created", (sid,))]


def emit_trajectory(con, session_id, out, *, include_children, include_steps, raw):
    """把（主 + 可选子）会话轨迹按 JSONL 写到 out。返回写出的行数。"""
    sid = _resolve_session(con, session_id)
    sessions = [sid] + (_child_sessions(con, sid) if include_children else [])
    lines = 0
    for s in sessions:
        out.write(json.dumps(session_header(con, s), ensure_ascii=False) + "\n")
        lines += 1
        for ev in iter_events(con, s, include_steps=include_steps, raw=raw):
            out.write(json.dumps(ev, ensure_ascii=False) + "\n")
            lines += 1
    return lines


# ── CLI ───────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="famou-scientist trace",
        description="把 opencode 某会话的完整轨迹导成 JSONL（只读，不影响正在用的会话）。",
    )
    ap.add_argument("session_id", nargs="?", help="会话 id（可前缀）；不给则列出最近会话")
    ap.add_argument("--db", default="", help=f"opencode.db 路径（默认 {default_db_path()}）")
    ap.add_argument("--list", "-l", action="store_true", help="列出最近会话后退出")
    ap.add_argument("--limit", type=int, default=30, help="--list 显示条数（默认 30）")
    ap.add_argument("--directory", default="", help="--list 按工作目录子串过滤")
    ap.add_argument("--include-children", action="store_true", help="连同 subagent 子会话")
    ap.add_argument("--raw", action="store_true", help="每行输出原始 part.data（不规范化）")
    ap.add_argument("--no-steps", action="store_true", help="不输出 step-start/step-finish 噪声")
    ap.add_argument("--out", default="", help="写到文件（默认 stdout）")
    ap.add_argument("--web", action="store_true", help="起本地 web 页面可视化轨迹（搜 session_id 看时间线）")
    ap.add_argument("--port", type=int, default=8765, help="--web 端口（默认 8765，占用则自动 +1）")
    ap.add_argument("--host", default="127.0.0.1", help="--web 绑定地址（默认 127.0.0.1 仅本机）")
    ap.add_argument("--no-open", action="store_true", help="--web 时不自动打开浏览器")
    args = ap.parse_args(argv)

    db_path = Path(args.db) if args.db else default_db_path()

    # --web：起本地可视化服务（自带 db 存在性检查），不走 JSONL 分支
    if args.web:
        from . import trace_web
        return trace_web.serve(db_path, host=args.host, port=args.port, open_browser=not args.no_open)

    try:
        con = _connect(db_path)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    # 不给 session_id 或显式 --list → 列会话
    if not args.session_id or args.list:
        rows = list_sessions(con, limit=args.limit, directory=args.directory)
        if not rows:
            print("（无会话）", file=sys.stderr)
            return 0
        print(f"{'SESSION ID':<34} {'MSGS':>4}  {'UPDATED':<19}  {'AGENT':<10} TITLE")
        for r in rows:
            mark = " ↳子" if r["parent_id"] else ""
            print(f"{r['id']:<34} {r['messages']:>4}  {r['updated']:<19}  {r['agent'] or '':<10} {r['title']}{mark}")
        print(f"\n共 {len(rows)} 个。导出轨迹：famou-scientist trace <SESSION ID> [--include-children] [--out f.jsonl]",
              file=sys.stderr)
        return 0

    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        n = emit_trajectory(
            con, args.session_id, out,
            include_children=args.include_children,
            include_steps=not args.no_steps, raw=args.raw,
        )
    finally:
        if args.out:
            out.close()
    if args.out:
        print(f"已写 {n} 行 → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
