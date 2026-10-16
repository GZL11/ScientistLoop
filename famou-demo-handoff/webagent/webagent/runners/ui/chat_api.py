"""
runners/ui/chat_api.py — 交互式 Agent 聊天 API

提供 FastAPI router，挂载到主 server 上：
  - POST /api/chat/sessions              创建新会话
  - GET  /api/chat/sessions               列出历史会话
  - POST /api/chat/sessions/{id}/upload   上传文件
  - POST /api/chat/sessions/{id}/send     发送消息（SSE 流式返回）
  - POST /api/chat/sessions/{id}/fork     从末尾 fork 出新 session
  - GET  /api/chat/sessions/{id}/files    列出 workspace 文件
  - GET  /api/chat/sessions/{id}/messages 获取消息历史
  - GET  /api/chat/sessions/{id}/trace    查看 trace

session 永远可继续：用户只看到一个 session_id。后端进程的死活对用户透明，
任何时刻收到 send 请求都会按需懒重建（基于 .chat_meta.json + agent 的 resume 机制）。

Fork 模型：被 fork 过的 session 自动 frozen（不能再发消息），用户只能继续在 fork
里聊。frozen 状态完全由 lineage 派生（child_count > 0），不存为字段。
"""

from __future__ import annotations

import asyncio
import json
import random
import shutil
import string
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from typing import List
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# ── 延迟导入 runner 依赖，避免 server 启动时加载 claude_agent_sdk ──

from ..defaults import DEFAULT_AGENT_CONFIG

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ── 会话状态（单用户，内存中） ──
# _sessions 仅作为热缓存，缺失时按需从 .chat_meta.json 重建。
_sessions: dict[str, dict] = {}
_sending_lock: dict[str, asyncio.Lock] = {}  # session_id -> Lock，防止同一 session 并发发送


def _messages_file(workspace: Path) -> Path:
    return workspace / ".chat_messages.json"


def _meta_file(workspace: Path) -> Path:
    return workspace / ".chat_meta.json"


def _save_messages(workspace: Path, messages: list) -> None:
    """将消息历史持久化到磁盘，页面刷新/服务重启后仍可恢复。"""
    try:
        _messages_file(workspace).write_text(
            json.dumps(messages, indent=2, ensure_ascii=False)
        )
    except Exception:
        pass


def _load_messages_from_disk(workspace: Path) -> list:
    p = _messages_file(workspace)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _load_meta(workspace: Path) -> dict | None:
    p = _meta_file(workspace)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_meta(workspace: Path, meta: dict) -> None:
    _meta_file(workspace).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )


def _iter_session_metas() -> list[tuple[str, dict]]:
    """扫描 INTERACTIVE_DIR 下所有合法 session，返回 [(session_id, meta), ...]。"""
    out = []
    interactive_dir = _get_interactive_dir()
    if not interactive_dir.exists():
        return out
    for d in interactive_dir.iterdir():
        if not d.is_dir():
            continue
        meta = _load_meta(d)
        if meta:
            out.append((d.name, meta))
    return out


def _child_counts() -> dict[str, int]:
    """构建 parent_session_id -> 直接子 fork 数量 的映射。"""
    counts: dict[str, int] = {}
    for _, meta in _iter_session_metas():
        parent = meta.get("parent_session_id")
        if parent:
            counts[parent] = counts.get(parent, 0) + 1
    return counts


def _is_frozen(session_id: str) -> bool:
    """frozen ≡ 有任何 child fork。"""
    return _child_counts().get(session_id, 0) > 0


# ── CC session JSONL 桶迁移 ──
# CC 把 session 文件存在 ~/.claude/projects/<workspace-hash>/ 下，
# workspace-hash 就是绝对路径里的 / 替换为 -。
# Fork 到新 workspace 时要把 parent JSONL 复制到新桶，CC 才能在新 cwd 下 --resume。

def _cc_config_root() -> Path:
    """CC 的配置根目录：默认 ~/.claude/，可被 CLAUDE_CONFIG_DIR 覆盖。"""
    import os
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def _cc_bucket_dir(workspace: Path) -> Path:
    """复刻 CC 的 bucket 命名：绝对路径里所有非 [a-zA-Z0-9-] 字符都被替换成 `-`。"""
    import re
    raw = str(workspace.resolve())
    bucket_name = re.sub(r"[^a-zA-Z0-9-]", "-", raw)
    return _cc_config_root() / "projects" / bucket_name


def _copy_cc_session_jsonl(parent_workspace: Path, fork_workspace: Path, agent_sid: str) -> bool:
    """复制 parent 的 JSONL 到 fork 的 bucket。返回是否复制成功。"""
    src = _cc_bucket_dir(parent_workspace) / f"{agent_sid}.jsonl"
    if not src.exists():
        return False
    dst_dir = _cc_bucket_dir(fork_workspace)
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_dir / f"{agent_sid}.jsonl")
    return True


class CreateSessionRequest(BaseModel):
    runner_type: str = "opencode_famou"
    prompt_variant: str = "default"
    skill_set: str = "default"
    model: str = "sonnet"


class SendMessageRequest(BaseModel):
    message: str


def _get_interactive_dir() -> Path:
    from ..bench_config import INTERACTIVE_DIR
    return INTERACTIVE_DIR


def _build_runner_config(meta: dict, workspace: Path):
    """根据持久化的 meta 构建 RunnerConfig（含 sandbox）。"""
    from ..backends.base import RunnerConfig
    from ..sandbox import SandboxConfig
    from ..bench_config import CASES_DIR, RESULTS_DIR, SANDBOX_EXTRA_DENY_READ

    interactive_dir = _get_interactive_dir()
    sandbox_cfg = SandboxConfig(
        deny_read=[
            str(CASES_DIR), str(RESULTS_DIR), str(interactive_dir),
            *SANDBOX_EXTRA_DENY_READ,
        ],
        allow_read=[str(workspace)],
    )

    runner_type = meta["runner_type"]
    return RunnerConfig(
        runner_type=runner_type,
        agent_config_dir=DEFAULT_AGENT_CONFIG.get(runner_type),
        prompt_variant=meta.get("prompt_variant", "default"),
        skill_set=meta.get("skill_set", "default"),
        model=meta.get("model", "sonnet"),
        sandbox=sandbox_cfg,
    )


async def _resume_session(session_id: str) -> dict:
    """从 .chat_meta.json 懒重建一个 session 状态字典。

    被 send/upload/files 等接口共用：用户随时能继续对话，server 重启完全透明。
    """
    interactive_dir = _get_interactive_dir()
    workspace = interactive_dir / session_id
    meta = _load_meta(workspace)
    if meta is None:
        raise HTTPException(404, f"Session not found: {session_id}")

    from ..backends.factory import runner_from_config
    config = _build_runner_config(meta, workspace)
    runner = runner_from_config(config)
    agent_session = await runner.start(workspace)

    # 关键：把持久化的 agent 端 session_id 注入回去，
    # CC 的 --resume / OpenCode 的 --session 才能续接历史。
    persisted_agent_sid = meta.get("agent_session_id")
    if persisted_agent_sid:
        agent_session.session_id = persisted_agent_sid

    info = {
        "agent_session": agent_session,
        "workspace": workspace,
        "runner_type": meta["runner_type"],
        "prompt_variant": meta.get("prompt_variant", "default"),
        "skill_set": meta.get("skill_set", "default"),
        "model": meta.get("model", "sonnet"),
        "created_at": meta.get("created_at", ""),
        "messages": _load_messages_from_disk(workspace),
    }
    _sessions[session_id] = info
    return info


async def _get_or_resume(session_id: str) -> dict:
    info = _sessions.get(session_id)
    if info is not None:
        return info
    return await _resume_session(session_id)


def _resolve_workspace(session_id: str) -> Path:
    """轻量解析：仅校验 workspace 存在，不重建 agent。用于 upload/list_files。"""
    info = _sessions.get(session_id)
    if info is not None:
        return info["workspace"]
    workspace = _get_interactive_dir() / session_id
    if not _meta_file(workspace).exists():
        raise HTTPException(404, f"Session not found: {session_id}")
    return workspace


def _persist_agent_sid(workspace: Path, agent_sid: str) -> None:
    meta = _load_meta(workspace) or {}
    if meta.get("agent_session_id") != agent_sid:
        meta["agent_session_id"] = agent_sid
        _save_meta(workspace, meta)


def _collect_trace_safe(runner_type: str, workspace: Path, agent_sid: str | None) -> None:
    """每轮 send 后异步采集 trace，失败静默——不阻塞用户体验。"""
    if not agent_sid:
        return
    try:
        from ..trace_converter import collect_trace, convert_trace
        collect_trace(runner_type, workspace, agent_sid)
        convert_trace(runner_type, workspace, agent_sid)
    except Exception:
        pass


# ── POST /sessions — 创建新会话 ──

@router.post("/sessions")
async def create_session(req: CreateSessionRequest):
    if req.runner_type not in DEFAULT_AGENT_CONFIG:
        raise HTTPException(400, f"Unknown runner_type: {req.runner_type}")

    from ..backends.factory import runner_from_config

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    session_id = f"chat_{ts}_{rand}"

    interactive_dir = _get_interactive_dir()
    workspace = interactive_dir / session_id
    workspace.mkdir(parents=True, exist_ok=True)

    # 先把 meta 落盘，后续即使 server 重启也能从 disk 恢复
    meta = {
        "session_id": session_id,
        "runner_type": req.runner_type,
        "prompt_variant": req.prompt_variant,
        "skill_set": req.skill_set,
        "model": req.model,
        "created_at": ts,
    }
    _save_meta(workspace, meta)

    config = _build_runner_config(meta, workspace)
    runner = runner_from_config(config)
    agent_session = await runner.start(workspace)

    _sessions[session_id] = {
        "agent_session": agent_session,
        "workspace": workspace,
        "runner_type": req.runner_type,
        "prompt_variant": req.prompt_variant,
        "skill_set": req.skill_set,
        "model": req.model,
        "created_at": ts,
        "messages": [],
    }

    return {"session_id": session_id, "workspace": str(workspace)}


# ── GET /sessions — 列出会话 ──

@router.get("/sessions")
async def list_sessions():
    """列出磁盘上所有 session。

    返回里 child_count 用于前端推导 frozen 状态、parent_session_id 用于树形展示。
    """
    metas = _iter_session_metas()
    counts: dict[str, int] = {}
    for _, m in metas:
        p = m.get("parent_session_id")
        if p:
            counts[p] = counts.get(p, 0) + 1

    sessions = []
    for sid, meta in metas:
        workspace = _get_interactive_dir() / sid
        messages = (
            _sessions[sid]["messages"]
            if sid in _sessions
            else _load_messages_from_disk(workspace)
        )
        sessions.append({
            "session_id": sid,
            "runner_type": meta.get("runner_type", "?"),
            "prompt_variant": meta.get("prompt_variant", "default"),
            "skill_set": meta.get("skill_set", "default"),
            "model": meta.get("model", "sonnet"),
            "created_at": meta.get("created_at", ""),
            "message_count": len(messages),
            "parent_session_id": meta.get("parent_session_id"),
            "child_count": counts.get(sid, 0),
        })

    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return sessions


# ── POST /sessions/{id}/upload — 上传文件 ──

@router.post("/sessions/{session_id}/upload")
async def upload_file(
    session_id: str,
    files: List[UploadFile] = File(...),
    relative_paths: List[str] = Form(default=[]),
):
    """支持批量上传文件或整个文件夹。

    前端传 files 数组 + 可选的 relative_paths 数组（含子目录结构，如 data/subdir/file.csv）。
    relative_paths[i] 对应 files[i] 在本地选择时的相对路径；缺省时退化为文件名。
    """
    workspace = _resolve_workspace(session_id)

    results = []
    for i, file in enumerate(files):
        # 优先使用前端传来的相对路径（保留目录层级）
        if i < len(relative_paths) and relative_paths[i]:
            rel_path = relative_paths[i]
        else:
            rel_path = file.filename or "uploaded_file"

        # 安全性：规范化路径，防止路径穿越（去掉绝对路径前缀 / 及 ..）
        parts = [p for p in Path(rel_path).parts if p not in ('..', '.', '/')]
        if not parts:
            parts = [file.filename or "uploaded_file"]
        safe_rel = Path(*parts)
        dest = workspace / safe_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = await file.read()
        dest.write_bytes(data)
        results.append({"filename": str(safe_rel), "size": len(data), "path": str(dest)})

    # 向后兼容：单文件时返回与旧接口相同的扁平结构，同时附 files 列表
    if len(results) == 1:
        r = results[0]
        return {"filename": r["filename"], "size": r["size"], "path": r["path"], "files": results}
    return {"files": results, "count": len(results)}


# ── GET /sessions/{id}/files — 列出 workspace 文件 ──

@router.get("/sessions/{session_id}/files")
async def list_files(session_id: str):
    workspace = _resolve_workspace(session_id)
    files = []
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            rel = f.relative_to(workspace)
            files.append({
                "name": str(rel),
                "size": f.stat().st_size,
            })
    return files


# ── GET /sessions/{id}/messages — 获取消息历史 ──

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    info = _sessions.get(session_id)
    if info:
        return {"messages": info["messages"]}
    workspace = _get_interactive_dir() / session_id
    if not _meta_file(workspace).exists():
        raise HTTPException(404, f"Session not found: {session_id}")
    return {"messages": _load_messages_from_disk(workspace)}


# ── GET /sessions/{id}/trace — 查看 trace ──

@router.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str):
    workspace = _get_interactive_dir() / session_id
    if not _meta_file(workspace).exists():
        raise HTTPException(404, f"Session not found: {session_id}")

    trace_dir = workspace / ".eval" / "trace"
    if not trace_dir.exists():
        return {"sessions": []}

    sessions = []
    for f in sorted(trace_dir.glob("*.json")):
        try:
            sessions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue

    # root session 在前
    sessions.sort(key=lambda s: (
        s.get("session", {}).get("parent_id") is not None,
        s.get("session", {}).get("started_at") or "",
    ))

    return {"sessions": sessions}


# ── POST /sessions/{id}/fork — 从末尾 fork 出新 session ──

@router.post("/sessions/{session_id}/fork")
async def fork_session(session_id: str):
    """从 parent session 的末尾 fork 出一个新 session。

    动作：
      1. 复制 parent workspace 到新目录
      2. 复制 messages 历史
      3. CC: 把 parent JSONL 拷贝到新 workspace 对应的桶（OpenCode 不需要）
      4. 写新 meta，记录 parent_session_id 和 _pending_fork=True
         下次 send 时会带 --fork-session/--fork 标记，并在 prompt 前注入 workspace 变更提示

    Parent session 不发生任何修改；它有了 child 之后会被前端识别为 frozen。
    """
    interactive_dir = _get_interactive_dir()
    parent_workspace = interactive_dir / session_id
    parent_meta = _load_meta(parent_workspace)
    if parent_meta is None:
        raise HTTPException(404, f"Session not found: {session_id}")

    parent_messages = _load_messages_from_disk(parent_workspace)
    if not parent_messages:
        raise HTTPException(400, "Cannot fork an empty session — send at least one message first")

    parent_agent_sid = parent_meta.get("agent_session_id")
    if not parent_agent_sid:
        raise HTTPException(400, "Parent session has no agent_session_id yet — wait for first reply")

    # 生成新 session_id + workspace
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    new_session_id = f"chat_{ts}_{rand}"
    new_workspace = interactive_dir / new_session_id

    # 复制 workspace 文件（含数据、配置；agent 后续操作不会污染 parent）
    shutil.copytree(parent_workspace, new_workspace)

    # 清掉从 parent 拷过来的 trace 文件——它们记录的是 parent 的对话，
    # 跟这个 fork 没关系。fork 自己 send 之后会重新采集出独立的 trace。
    for sub in (".eval/trace", ".eval/trace_opencode", ".eval/trace_cc"):
        p = new_workspace / sub
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    # 重写新 workspace 里的 meta + messages，丢掉 parent 的旧痕迹
    runner_type = parent_meta["runner_type"]
    if runner_type.startswith("cc"):
        if not _copy_cc_session_jsonl(parent_workspace, new_workspace, parent_agent_sid):
            # 没找到 parent JSONL：可能 sandbox 隔离或 home 不一致；继续，但 fork 实际效果有疑问
            pass

    new_meta = {
        "session_id": new_session_id,
        "runner_type": runner_type,
        "prompt_variant": parent_meta.get("prompt_variant", "default"),
        "skill_set": parent_meta.get("skill_set", "default"),
        "model": parent_meta.get("model", "sonnet"),
        "created_at": ts,
        "parent_session_id": session_id,
        # agent_session_id 设为 parent 的 id：下次 send 走 --resume <parent_sid> --fork-session
        "agent_session_id": parent_agent_sid,
        "_pending_fork": True,
        # workspace 变更通知，下次 send 会插到 prompt 前面
        "_workspace_changed_from": str(parent_workspace),
    }
    _save_meta(new_workspace, new_meta)
    _save_messages(new_workspace, parent_messages)

    return {"session_id": new_session_id}


# ── POST /sessions/{id}/send — 发消息（SSE 流式） ──

@router.post("/sessions/{session_id}/send")
async def send_message(session_id: str, req: SendMessageRequest):
    # frozen guard：被 fork 过的 session 不允许再发消息
    if _is_frozen(session_id):
        raise HTTPException(409, "Session is frozen (already forked) — fork it again to continue")

    info = await _get_or_resume(session_id)

    # 同一 session 的并发 send 串行化，防止消息乱序
    lock = _sending_lock.setdefault(session_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(409, "Session is already processing a message")

    agent_session = info["agent_session"]
    workspace: Path = info["workspace"]
    runner_type: str = info["runner_type"]

    info["messages"].append({"role": "user", "content": req.message})
    _save_messages(workspace, info["messages"])  # 用户消息立即落盘

    # fork 后第一次 send 的特殊处理：
    #  1. 在 prompt 前注入 workspace 变更通知（让 agent 知道路径变了）
    #  2. send 时带 fork=True，CLI 会用 --fork-session/--fork 创建新的 agent session id
    meta_now = _load_meta(workspace) or {}
    pending_fork = bool(meta_now.get("_pending_fork"))
    workspace_changed_from = meta_now.get("_workspace_changed_from")
    if pending_fork and workspace_changed_from:
        note = (
            f"[Note: this conversation was forked. The workspace has moved from "
            f"`{workspace_changed_from}` to `{workspace}`. All files referenced earlier "
            f"are available at the new location — use the new path for any tool calls.]"
        )
        prompt = f"{note}\n\n{req.message}"
    else:
        prompt = req.message

    async def event_stream():
        """通过 AgentEvent callback 将结构化事件转为 SSE。"""
        from ..backends.base import AgentEvent

        async with lock:
            queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
            loop = asyncio.get_event_loop()

            def on_event(event: AgentEvent):
                loop.call_soon_threadsafe(queue.put_nowait, event)

            prev_callback = agent_session.on_event
            agent_session.on_event = on_event

            async def run_agent():
                try:
                    return await agent_session.send(prompt, fork=pending_fork)
                finally:
                    await queue.put(None)  # sentinel
                    agent_session.on_event = prev_callback

            task = asyncio.create_task(run_agent())

            while True:
                event = await queue.get()
                if event is None:
                    break
                yield {"event": event.type, "data": json.dumps(asdict(event), ensure_ascii=False)}

            result = await task
            info["messages"].append({"role": "assistant", "content": result})
            _save_messages(workspace, info["messages"])

            # agent 端的 session_id 在第一次 send 时才确定，落盘以便后续 resume。
            # fork 后的第一次 send 也会在 init 事件里拿到全新的 fork sid，覆盖到这里。
            if agent_session.session_id:
                _persist_agent_sid(workspace, agent_session.session_id)

            # 清掉 fork 一次性标记，避免下次 send 还带 --fork-session
            if pending_fork:
                m = _load_meta(workspace) or {}
                m.pop("_pending_fork", None)
                m.pop("_workspace_changed_from", None)
                _save_meta(workspace, m)

            # 每轮自动采集 trace —— View Trace 任何时刻都能看到最新内容
            await asyncio.to_thread(
                _collect_trace_safe, runner_type, workspace, agent_session.session_id
            )

            yield {"event": "done", "data": json.dumps({"status": "ok"})}

    return EventSourceResponse(event_stream())
