"""
OpenCode ACP runners — 通过 ACP (ndJSON-RPC over stdio) 运行 OpenCode。

对应原 B3/run_case_opencode.py 的逻辑，搬移至 runner 层。

主要改动：
- ACPClient.call() 返回 (result, text)，text 为本次调用积累的 agent 输出
- agent 配置由 RunnerConfig.agent_config_dir 指定，复制到 workspace/.opencode/
- 数据复制由 benchmark 层负责，runner 层不感知 case 结构

Runner 类型：
  OpenCodeACPRunner    — 注入指定配置（opencode.jsonc + agents/），路由由 default_agent 控制
  OpenCodeNativeRunner — 不注入配置，走 OpenCode 内置 build agent
所有 runner 共用 OpenCodeSession（不传 agent 字段），路由完全交由配置层控制。
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from .base import AgentEvent, AgentRunner, AgentSession
from ..defaults import resolve_model

os.environ.setdefault("OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX", "64000")
# 关掉 plugins/lib/log.ts 的 HTTP sink:runners 离线没有日志服务,
# 不设的话 plugin 每 60s 会在 stderr 打一行 endpoint unreachable warning。
# 显式设了别的值(http URL)就尊重 caller 的选择。
os.environ.setdefault("WEBAGENT_LOG_ENDPOINT_URL", "")


# ── ACP 客户端 ────────────────────────────────────────────────────────────────

class ACPClient:
    """极简 ACP ndJSON-RPC 客户端，运行在 opencode acp 子进程之上。"""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self._emit = None  # AgentEvent callback, set by OpenCodeSession
        self._next_id = 0
        self._pending: dict[int, tuple[threading.Event, list, list]] = {}
        self._lock = threading.Lock()
        self._text_buffer: list[str] = []
        self._dead = False  # reader 线程退出后置 True，用于快速失败
        self._stop_on_tools: set[str] | None = None  # B2 early stop
        self._early_stopped = False

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()

    def _send(self, msg: dict):
        try:
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            self.proc.stdin.write(line.encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._dead = True
            raise RuntimeError(f"ACP subprocess disconnected: {e}") from e

    # RPC 响应超时（秒）。session/prompt 可能运行很久，此超时仅用于
    # 检测子进程意外退出，正常运行不会触发。
    _RPC_TIMEOUT = 3600  # 1 小时

    def call(self, method: str, params: dict) -> tuple[dict, str]:
        """
        发送 JSON-RPC 请求，阻塞等待响应。
        返回 (result_dict, accumulated_agent_text)。
        """
        if self._dead:
            raise RuntimeError("ACP subprocess is no longer running")

        # 重置本次调用的文本缓冲
        self._text_buffer = []

        with self._lock:
            self._next_id += 1
            rid = self._next_id
            event = threading.Event()
            result_box: list = [None]
            error_box: list = [None]
            self._pending[rid] = (event, result_box, error_box)

        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})

        if not event.wait(timeout=self._RPC_TIMEOUT):
            raise RuntimeError(
                f"ACP {method} timed out after {self._RPC_TIMEOUT}s "
                f"(subprocess alive={self.proc.poll() is None})"
            )

        if error_box[0] and not self._early_stopped:
            raise RuntimeError(f"ACP {method} 返回错误: {error_box[0]}")

        # RPC 响应可能先于最后几条 session/update 到达（opencode 内部
        # HTTP 响应与 SSE 事件流是两条独立异步路径，无同步保证）。
        # 短暂等待让 _read_loop 有机会消费迟到的 update。
        import time
        time.sleep(0.2)

        text = "".join(self._text_buffer)
        return result_box[0] or {}, text

    def _read_loop(self):
        try:
            for raw in self.proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[warn] 非 JSON 行: {line[:200]}", file=sys.stderr)
                    continue

                # JSON-RPC 响应（有 id，无 method）
                if "id" in msg and "method" not in msg:
                    rid = msg["id"]
                    with self._lock:
                        entry = self._pending.pop(rid, None)
                    if entry:
                        event, result_box, error_box = entry
                        if "error" in msg:
                            error_box[0] = msg["error"]
                        else:
                            result_box[0] = msg.get("result")
                        event.set()
                    continue

                method = msg.get("method", "")
                params = msg.get("params", {})

                # 流式更新通知
                if method == "session/update":
                    self._handle_update(params.get("update", {}))
                    continue

                # 权限请求（server → client RPC）
                if method == "session/request_permission" and "id" in msg:
                    self._auto_allow(msg["id"])
                    continue
        finally:
            # 子进程 stdout 关闭（正常退出或崩溃），唤醒所有等待者避免死锁
            self._dead = True
            with self._lock:
                for event, _result_box, error_box in self._pending.values():
                    error_box[0] = {"code": -1, "message": "ACP subprocess exited"}
                    event.set()
                self._pending.clear()

    def _handle_update(self, update: dict):
        utype = update.get("sessionUpdate", "")
        if utype == "agent_message_chunk":
            text = update.get("content", {}).get("text", "")
            if text:
                self._text_buffer.append(text)
                if self._emit:
                    self._emit(AgentEvent(type="text_chunk", content=text))
        elif utype == "tool_call":
            tool = update.get("toolName") or update.get("title", "?")
            if self._stop_on_tools and tool.lower() in {t.lower() for t in self._stop_on_tools}:
                self._early_stopped = True
                if self._emit:
                    self._emit(AgentEvent(type="info",
                        content=f"[early stop] 检测到 {tool}，终止 session"))
                # 解锁等待中的 RPC call
                with self._lock:
                    for _rid, (event, result_box, _err) in self._pending.items():
                        if result_box[0] is None:
                            result_box[0] = {}
                        event.set()
                try:
                    self.proc.terminate()
                except OSError:
                    pass
                return
            if self._emit:
                self._emit(AgentEvent(type="tool_call", tool=tool, tool_input=""))

    def _auto_allow(self, rpc_id):
        reply = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"outcome": {"outcome": "selected", "optionId": "once"}},
        }
        self._send(reply)

    def _read_stderr(self):
        for raw in self.proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            if line:
                print(f"[opencode] {line}", file=sys.stderr)

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=3)
        # 等待 reader 线程退出，确保有序清理
        self._reader.join(timeout=3)
        self._stderr_reader.join(timeout=3)


# ── ACP 启动辅助 ──────────────────────────────────────────────────────────────

async def _start_acp(workspace: Path) -> tuple[ACPClient, str]:
    """启动 opencode acp 子进程，完成握手，返回 (client, session_id)。"""
    proc = subprocess.Popen(
        ["opencode", "acp", "--cwd", str(workspace)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workspace),
    )
    client = ACPClient(proc)

    await asyncio.to_thread(client.call, "initialize", {
        "protocolVersion": 1,
        "clientCapabilities": {"terminal": False},
        "clientInfo": {"name": "famou-bench-runner", "version": "1.0"},
    })

    result, _ = await asyncio.to_thread(client.call, "session/new", {
        "cwd": str(workspace),
        "mcpServers": [],
    })
    session_id = result.get("sessionId")
    return client, session_id


# ── Session ───────────────────────────────────────────────────────────────────

class OpenCodeSession(AgentSession):
    """
    基于 ACP 协议的 session，不在 session/prompt 中指定 agent 字段。
    路由完全由 opencode.jsonc 中的 default_agent 字段控制：
      - opencode_famou:  default_agent = "famou-master"
      - opencode_single: default_agent = "famou-single"（待添加）
      - opencode_native: 无注入配置，走 OpenCode 内置 build agent
    同一 session_id 支持多轮 session/prompt 调用（B2 多轮场景）。
    """

    def __init__(self, client: ACPClient, session_id: str):
        self.session_id = session_id
        self.on_event = None
        self._client = client
        # Wire client's emit to our _emit
        client._emit = self._emit
        self._emit(AgentEvent(type="info", content=f"session_id: {session_id}"))

    async def send(self, message: str, *, stop_on_tools: set[str] | None = None) -> str:
        self._client._stop_on_tools = stop_on_tools
        self._client._early_stopped = False
        _, text = await asyncio.to_thread(
            self._client.call,
            "session/prompt",
            {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": message}],
            },
        )
        return text

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)


# ── Runner ────────────────────────────────────────────────────────────────────

def _inject_model(workspace: Path, model: str | None, runner_type: str) -> None:
    """将 model 写入 workspace/.opencode/opencode.jsonc（已有则合并，没有则新建）。"""
    resolved = resolve_model(model, runner_type)
    if resolved is None:
        return
    config_dir = workspace / ".opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "opencode.jsonc"
    if config_path.exists():
        import re
        text = config_path.read_text(encoding="utf-8")
        # JSONC → JSON: 去掉整行注释，再去掉尾逗号
        stripped = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        stripped = re.sub(r",\s*([}\]])", r"\1", stripped)
        data = json.loads(stripped)
    else:
        data = {"$schema": "https://opencode.ai/config.json"}
    data["model"] = resolved
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class OpenCodeACPRunner(AgentRunner):
    """
    通过 opencode acp 子进程运行 agent，注入指定配置。
    路由由 opencode.jsonc 中的 default_agent 控制。
    需要 RunnerConfig.agent_config_dir 指向对应的 runners/configs/.opencode*/。
    """

    async def start(self, workspace: Path) -> OpenCodeSession:
        workspace.mkdir(parents=True, exist_ok=True)

        # 复制基础配置（opencode.jsonc 等）并组装 agents/ 目录
        if self.config.agent_config_dir:
            from ..agent_builder import copy_base_config, assemble_agents, copy_skills
            copy_base_config(self.config.agent_config_dir, workspace)
            assemble_agents(
                self.config.agent_config_dir,
                self.config.prompt_variant,
                workspace,
                self.config.prompt_variants_dir,
            )
            copy_skills(self.config.skill_set, self.config.agent_config_dir, workspace)

        _inject_model(workspace, self.config.model, self.config.runner_type)
        client, session_id = await _start_acp(workspace)
        return OpenCodeSession(client, session_id)


class OpenCodeNativeRunner(AgentRunner):
    """
    OpenCode 原生 runner，不注入任何配置。
    走 OpenCode 内置 build agent。
    """

    async def start(self, workspace: Path) -> OpenCodeSession:
        workspace.mkdir(parents=True, exist_ok=True)

        if self.config.skill_set != "none":
            from ..agent_builder import copy_skills
            copy_skills(self.config.skill_set, None, workspace, platform=".opencode")

        _inject_model(workspace, self.config.model, self.config.runner_type)
        client, session_id = await _start_acp(workspace)
        return OpenCodeSession(client, session_id)
