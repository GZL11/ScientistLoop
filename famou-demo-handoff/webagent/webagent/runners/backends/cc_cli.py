"""
CC CLI runners — 通过 claude --print --output-format stream-json 运行 Claude Code。

替代 native_cc.py 的 SDK 实现，使用子进程 + stdout JSON 事件流。
好处：可被 bwrap/sandbox-exec 包裹实现文件系统隔离。

多轮交互通过 --resume <session_id> 续接。

Runner 类型：
  CCCLIRunner       — 注入 .claude/ 配置（settings.json + agents/ + skills/），同 CCFamouRunner
  CCCLINativeRunner — 不注入配置，仅注入 model 和 skills
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from .base import AgentEvent, AgentRunner, AgentSession, RunnerConfig
from ..defaults import resolve_model

os.environ.setdefault("BASH_DEFAULT_TIMEOUT_MS", "300000")  # 5 分钟
os.environ.setdefault("BASH_MAX_TIMEOUT_MS", "600000")      # 最大 10 分钟
os.environ.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "64000")


# ── Session ──────────────────────────────────────────────────────────────────

class CCCLISession(AgentSession):
    """
    基于 claude --print --output-format stream-json 的 session。

    每次 send() 启动一个子进程，通过 stdout JSON 事件流收集结果。
    多轮对话通过 --resume <session_id> 续接。
    """

    def __init__(self, workspace: Path, config: RunnerConfig):
        self.session_id: str | None = None
        self.on_event = None
        self._workspace = workspace
        self._config = config

    async def send(self, message: str, *, stop_on_tools: set[str] | None = None, fork: bool = False) -> str:
        text = await asyncio.to_thread(self._run, message, stop_on_tools, fork)
        return text

    def _run(self, message: str, stop_on_tools: set[str] | None, fork: bool = False) -> str:
        """同步执行 claude CLI，解析 stdout JSON 事件流。"""
        cmd = [
            "claude", "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", "bypassPermissions",
        ]

        if self._config.max_turns:
            cmd.extend(["--max-turns", str(self._config.max_turns)])

        if self.session_id:
            cmd.extend(["--resume", self.session_id])
            # fork=True 时同时带 --fork-session：本次 send 不污染原 session，
            # init 事件会回报新的 session_id，后续 send 续接到新 id。
            if fork:
                cmd.append("--fork-session")

        cmd.extend(["-p", message])

        # sandbox 包裹
        if self._config.sandbox:
            from ..sandbox import wrap_command
            cmd = wrap_command(cmd, self._config.sandbox, self._workspace)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._workspace),
            env={**os.environ},
        )

        text_parts: list[str] = []
        early_stopped = False

        try:
            for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                # ── init: 获取 session_id ──
                if etype == "system" and event.get("subtype") == "init":
                    new_sid = event.get("session_id")
                    if new_sid and self.session_id is None:
                        self.session_id = new_sid
                        self._emit(AgentEvent(
                            type="info",
                            content=f"session_id: {self.session_id}",
                        ))
                    elif new_sid and fork and new_sid != self.session_id:
                        # --fork-session 产出全新 session_id，切换过去
                        self.session_id = new_sid
                        self._emit(AgentEvent(
                            type="info",
                            content=f"forked session_id: {new_sid}",
                        ))

                # ── assistant: 文本 / 工具调用 / thinking ──
                elif etype == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        btype = block.get("type", "")

                        if btype == "text":
                            text = block.get("text", "")
                            if text.strip():
                                text_parts.append(text)
                                self._emit(AgentEvent(type="text", content=text))

                        elif btype == "tool_use":
                            tool_name = block.get("name", "?")
                            tool_input = block.get("input", {})
                            summary = _tool_call_summary(tool_name, tool_input)

                            # B2 early stop: 检测到执行工具时终止
                            if stop_on_tools and tool_name in stop_on_tools:
                                early_stopped = True
                                self._emit(AgentEvent(
                                    type="info",
                                    content=f"[early stop] 检测到 {tool_name}，终止 session",
                                ))
                                proc.kill()
                                proc.stdout.close()
                                break

                            self._emit(AgentEvent(
                                type="tool_call",
                                tool=tool_name,
                                tool_input=summary,
                            ))

                # ── user: 工具执行结果 ──
                elif etype == "user":
                    tool_result = event.get("tool_use_result", {})
                    if isinstance(tool_result, dict) and tool_result.get("is_error"):
                        self._emit(AgentEvent(
                            type="tool_result",
                            tool=event.get("parent_tool_use_id", ""),
                            content=str(tool_result.get("content", ""))[:300],
                            is_error=True,
                        ))

                # ── result: 最终结果 ──
                elif etype == "result":
                    if self.session_id is None:
                        self.session_id = event.get("session_id")

                    usage = event.get("usage", {})
                    cost = event.get("total_cost_usd", 0)
                    num_turns = event.get("num_turns", 0)
                    stop_reason = event.get("stop_reason", "")
                    self._emit(AgentEvent(
                        type="info",
                        content=(
                            f"[result] stop_reason={stop_reason} "
                            f"turns={num_turns} "
                            f"cost=${cost:.4f} "
                            f"tokens: in={usage.get('input_tokens', 0)} "
                            f"out={usage.get('output_tokens', 0)} "
                            f"cache_read={usage.get('cache_read_input_tokens', 0)}"
                        ),
                    ))

                    # result.result 包含最终文本（如果之前没收集到）
                    result_text = event.get("result", "")
                    if result_text and not text_parts:
                        text_parts.append(result_text)

                if early_stopped:
                    break

        except ValueError:
            pass  # stdout.close() 后 for 循环抛出 I/O on closed file

        # 确保进程退出
        try:
            if early_stopped:
                proc.wait(timeout=5)
            else:
                proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

        # stderr
        if not early_stopped:
            stderr = proc.stderr.read().decode(errors="replace").strip()
            if stderr and proc.returncode != 0:
                for line in stderr.split("\n")[:5]:
                    print(f"[claude] {line}", file=sys.stderr)
        else:
            proc.stderr.close()
            self._emit(AgentEvent(
                type="info", content="[early stop] 执行工具被拦截，已停止",
            ))

        return "\n".join(text_parts)

    async def close(self) -> None:
        pass


# ── 工具调用摘要 ──────────────────────────────────────────────────────────────

def _tool_call_summary(tool_name: str, tool_input: dict) -> str:
    """生成工具调用的摘要（复用 native_cc 的逻辑）。"""
    if tool_name in ("Read", "Glob", "Grep"):
        return str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern") or "")
    if tool_name in ("Write", "Edit"):
        return str(tool_input.get("file_path") or "")
    if tool_name == "Bash":
        return tool_input.get("command") or ""
    if tool_name == "Task":
        return tool_input.get("description") or tool_input.get("prompt") or ""
    return json.dumps(tool_input, ensure_ascii=False)[:150]


# ── 配置注入 ──────────────────────────────────────────────────────────────────

def _inject_cc_settings(workspace: Path, model: str | None, runner_type: str) -> None:
    """将 model 和 effortLevel 写入 workspace/.claude/settings.json。"""
    config_dir = workspace / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_path = config_dir / "settings.json"

    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        data = {"$schema": "https://json.schemastore.org/claude-code-settings.json"}

    resolved = resolve_model(model, runner_type)
    if resolved:
        data["model"] = resolved

    # 静态配置统一走 settings.json
    data.setdefault("effortLevel", "high")

    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Runner ────────────────────────────────────────────────────────────────────

class CCCLIRunner(AgentRunner):
    """
    通过 claude CLI 运行 agent，注入 .claude/ 配置。
    等价于 CCFamouRunner，但用 CLI 子进程而非 SDK。
    """

    async def start(self, workspace: Path) -> CCCLISession:
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

        _inject_cc_settings(workspace, self.config.model, self.config.runner_type)
        return CCCLISession(workspace, self.config)


class CCCLINativeRunner(AgentRunner):
    """
    CC CLI 原生 runner，不注入 agent 配置。
    仅注入 model/effortLevel 和可选的 skills。
    """

    async def start(self, workspace: Path) -> CCCLISession:
        workspace.mkdir(parents=True, exist_ok=True)

        if self.config.skill_set != "none":
            from ..agent_builder import copy_skills
            copy_skills(self.config.skill_set, None, workspace, platform=".claude")

        _inject_cc_settings(workspace, self.config.model, self.config.runner_type)
        return CCCLISession(workspace, self.config)
