"""
OpenCode runners — 通过 opencode run --format json 运行 OpenCode。

替代原 ACP 实现，使用子进程 + stdout JSON 事件流，
解决 ACP 的事件竞争问题，并提供更丰富的事件信息（工具 input/output、token 统计）。

多轮交互通过 --session <ID> 续接 session（注意：不能同时带 --continue，
opencode 的 --continue 是"使用最近一个 session"，与 --session 互斥；
两个一起传会导致 --session 被忽略，消息发到全局最新 session 里）。

Runner 类型：
  OpenCodeRunner       — 注入指定配置（opencode.jsonc + agents/），路由由 default_agent 控制
  OpenCodeNativeRunner — 不注入配置，走 OpenCode 内置 build agent
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .base import AgentEvent, AgentRunner, AgentSession
from ..defaults import resolve_model

os.environ.setdefault("OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX", "64000")
# 关掉 plugins/lib/log.ts 的 HTTP sink:runners 离线没有日志服务,
# 不设的话 plugin 每 60s 会在 stderr 打一行 endpoint unreachable warning。
# 显式设了别的值(http URL)就尊重 caller 的选择。
os.environ.setdefault("WEBAGENT_LOG_ENDPOINT_URL", "")


def _killpg_safe(proc: subprocess.Popen) -> None:
    """杀整个进程组（opencode + 派生的 bash/工具子孙），幂等。

    依赖 Popen(start_new_session=True)：子进程会自成一个 session/group，
    killpg 不会误伤本 runner 自己。
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# ── Session ──────────────────────────────────────────────────────────────────

class OpenCodeRunSession(AgentSession):
    """
    基于 opencode run --format json 的 session。

    每次 send() 启动一个子进程，通过 stdout JSON 事件流收集结果。
    多轮对话通过 --session <ID> 复用 session。
    """

    def __init__(self, workspace: Path, config=None):
        self.session_id: str | None = None
        self.on_event = None
        self._workspace = workspace
        self._config = config

    async def send(self, message: str, *, stop_on_tools: set[str] | None = None, fork: bool = False) -> str:
        text, events = await asyncio.to_thread(
            self._run, message, stop_on_tools, fork,
        )
        return text

    def _run(self, message: str, stop_on_tools: set[str] | None, fork: bool = False) -> tuple[str, list[dict]]:
        """同步执行 opencode run，解析 stdout JSON 事件流。"""
        cmd = [
            "opencode", "run",
            "--format", "json",
            "--dir", str(self._workspace),
            "--dangerously-skip-permissions",
        ]

        if self.session_id:
            # 注意：opencode 的 --session 已经隐含"继续这个 session"，**不要**再带 --continue,
            # 否则两者一起会让 opencode 静默 fail 并新建一个 session（实测过）。
            cmd.extend(["--session", self.session_id])
            # fork=True 时带 --fork：本次 send 不污染原 session，
            # 输出事件里 sessionID 会变成新 fork 的 id。
            if fork:
                cmd.append("--fork")

        # opencode run 不像 ACP 那样自动检测 / 前缀路由 command，
        # 需要显式传 --command 才能走 sdk.session.command()
        stripped = message.strip()
        if stripped.startswith("/"):
            parts = stripped[1:].split(None, 1)
            cmd.extend(["--command", parts[0]])
            cmd.append(parts[1] if len(parts) > 1 else "")
        else:
            cmd.append(message)

        # sandbox 包裹
        if self._config and self._config.sandbox:
            from ..sandbox import wrap_command
            cmd = wrap_command(cmd, self._config.sandbox, self._workspace)

        # Fix 2：每个 workspace 独立的 opencode SQLite DB，消除并发实验之间的写锁竞争。
        # opencode 遵循 XDG 规范，DB 落在 $XDG_DATA_HOME/opencode/opencode.db。
        #
        # 老 chat 兼容：fix 之前创建的 chat session 存在全局 DB（~/.local/share/opencode/）。
        # 若 session_id 已存在但本地 DB 还没建出来，说明这是老 chat——继续走全局 DB，
        # 否则 opencode 在本地 DB 找不到 session 会新建一个，丢失历史。
        opencode_data_dir = self._workspace / ".opencode_data"
        local_db = opencode_data_dir / "opencode" / "opencode.db"
        use_isolated_xdg = (self.session_id is None) or local_db.exists()

        if use_isolated_xdg:
            opencode_data_dir.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "XDG_DATA_HOME": str(opencode_data_dir)}
        else:
            # 老 chat：留在全局 DB 以保留历史，不切 XDG
            env = None

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._workspace),
            env=env,
            start_new_session=True,  # Fix 1：让 proc 自成 process group，便于 killpg 全部子孙
        )

        # Fix 1：idle timeout 看门狗。opencode 卡死时进程仍活但不再产出 stdout 事件，
        # 用空闲时间触发 killpg；正常长跑（evolve 等）只要有事件刷新就不会被误杀。
        idle_timeout = (self._config.idle_timeout_s if self._config else None) or 7200
        last_activity = [time.time()]
        watchdog_stop = threading.Event()

        def _watchdog():
            while not watchdog_stop.wait(timeout=30):
                if proc.poll() is not None:
                    return
                idle = time.time() - last_activity[0]
                if idle > idle_timeout:
                    print(
                        f"[opencode] idle {idle:.0f}s > {idle_timeout}s, killpg pid={proc.pid}",
                        file=sys.stderr,
                    )
                    _killpg_safe(proc)
                    return

        watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
        watchdog_thread.start()

        events: list[dict] = []
        text_parts: list[str] = []
        early_stopped = False

        try:
            # opencode run --format json 的输出理论上每行一个 JSON，
            # 但 tool output 含换行时会导致 JSON 跨行，需要用 buffer 拼接。
            buf = ""
            for raw in proc.stdout:
                last_activity[0] = time.time()  # 收到任何数据就刷新 watchdog
                buf += raw.decode(errors="replace")
                # 尝试从 buffer 中解析完整的 JSON 对象
                while buf:
                    buf = buf.lstrip()
                    if not buf or buf[0] != "{":
                        # 跳过非 JSON 行（如 opencode 的日志输出）
                        nl = buf.find("\n")
                        if nl == -1:
                            break
                        skipped = buf[:nl].strip()
                        if skipped:
                            print(f"[opencode] {skipped[:200]}", file=sys.stderr)
                        buf = buf[nl + 1:]
                        continue
                    try:
                        event, end = json.JSONDecoder().raw_decode(buf)
                    except json.JSONDecodeError:
                        break  # 不完整，等更多数据
                    buf = buf[end:]

                    # ── 处理已解析的事件 ──
                    events.append(event)

                    new_sid = event.get("sessionID")
                    if new_sid and self.session_id is None:
                        self.session_id = new_sid
                        self._emit(AgentEvent(type="info", content=f"session_id: {self.session_id}"))
                    elif new_sid and fork and new_sid != self.session_id:
                        # --fork 产出全新 session_id，切换过去
                        self.session_id = new_sid
                        self._emit(AgentEvent(type="info", content=f"forked session_id: {new_sid}"))

                    etype = event.get("type", "")

                    if etype == "text":
                        text = event.get("part", {}).get("text", "")
                        if text:
                            text_parts.append(text)
                            self._emit(AgentEvent(type="text", content=text))

                    elif etype == "tool_use":
                        part = event.get("part", {})
                        tool = part.get("tool", "?")
                        state = part.get("state", {})
                        status = state.get("status", "?")
                        tool_input = json.dumps(state.get("input", {}), ensure_ascii=False)

                        if stop_on_tools and tool.lower() in {t.lower() for t in stop_on_tools}:
                            early_stopped = True
                            self._emit(AgentEvent(
                                type="info",
                                content=f"[early stop] 检测到 {tool}，终止 session",
                            ))
                            # 立即 killpg 并关闭 stdout，防止 for 循环阻塞在读上
                            _killpg_safe(proc)
                            proc.stdout.close()
                            break

                        self._emit(AgentEvent(
                            type="tool_call", tool=tool, tool_input=tool_input,
                        ))
                        if status == "error":
                            self._emit(AgentEvent(
                                type="tool_result", tool=tool,
                                content=state.get("error", ""), is_error=True,
                            ))

                    elif etype == "step_finish":
                        part = event.get("part", {})
                        tokens = part.get("tokens", {})
                        reason = part.get("reason", "")
                        if tokens:
                            self._emit(AgentEvent(
                                type="info",
                                content=f"[step] reason={reason} tokens: in={tokens.get('input', 0)} out={tokens.get('output', 0)} cache_read={tokens.get('cache', {}).get('read', 0)}",
                            ))

                    elif etype == "error":
                        error = event.get("error", {})
                        msg = error.get("data", {}).get("message", "") if isinstance(error, dict) else str(error)
                        self._emit(AgentEvent(type="info", content=f"[error] {msg}"))

                if early_stopped:
                    break

        except ValueError:
            pass  # stdout.close() 后 for 循环抛出 I/O on closed file，正常退出

        # 停掉 watchdog（proc 即将 wait/kill 收尾，watchdog 不需要再监测）
        watchdog_stop.set()

        try:
            # 确保进程退出
            if early_stopped:
                # _killpg_safe(proc) 已在 early stop 时调用
                proc.wait(timeout=5)
            else:
                proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _killpg_safe(proc)
            proc.wait(timeout=5)

        # stderr（early stop 时进程已 kill，不再读取避免阻塞）
        if not early_stopped:
            stderr = proc.stderr.read().decode(errors="replace").strip()
            if stderr and proc.returncode != 0:
                for line in stderr.split("\n")[:5]:
                    print(f"[opencode] {line}", file=sys.stderr)
        else:
            proc.stderr.close()

        if early_stopped:
            self._emit(AgentEvent(
                type="info", content="[early stop] 执行工具被拦截，已停止",
            ))

        return "\n".join(text_parts), events

    async def close(self) -> None:
        pass  # 无状态，无需关闭


# ── Runner ───────────────────────────────────────────────────────────────────

def _inject_model(workspace: Path, model: str | None, runner_type: str) -> None:
    """将 model 写入 workspace/.opencode/opencode.jsonc（已有则合并，没有则新建）。"""
    resolved = resolve_model(model, runner_type)
    if resolved is None:
        return
    config_dir = workspace / ".opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "opencode.jsonc"
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        stripped = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        stripped = re.sub(r",\s*([}\]])", r"\1", stripped)
        data = json.loads(stripped)
    else:
        data = {"$schema": "https://opencode.ai/config.json"}
    data["model"] = resolved
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class OpenCodeRunner(AgentRunner):
    """
    通过 opencode run 运行 agent，注入指定配置。
    路由由 opencode.jsonc 中的 default_agent 控制。
    """

    async def start(self, workspace: Path) -> OpenCodeRunSession:
        workspace.mkdir(parents=True, exist_ok=True)

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
        return OpenCodeRunSession(workspace, config=self.config)


class OpenCodeNativeRunner(AgentRunner):
    """
    OpenCode 原生 runner，不注入任何配置。
    走 OpenCode 内置 build agent。
    """

    async def start(self, workspace: Path) -> OpenCodeRunSession:
        workspace.mkdir(parents=True, exist_ok=True)

        if self.config.skill_set != "none":
            from ..agent_builder import copy_skills
            copy_skills(self.config.skill_set, None, workspace, platform=".opencode")

        _inject_model(workspace, self.config.model, self.config.runner_type)
        return OpenCodeRunSession(workspace, config=self.config)
