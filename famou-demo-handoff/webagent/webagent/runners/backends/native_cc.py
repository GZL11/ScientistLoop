"""
NativeCCRunner — 直接使用 claude_agent_sdk 运行 Claude Code。

对应原 B3/run_case.py 的 agent 运行逻辑，搬移至 runner 层。
"""

import os
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from .base import AgentEvent, AgentRunner, AgentSession, RunnerConfig
from ..defaults import resolve_model

os.environ.setdefault("BASH_DEFAULT_TIMEOUT_MS", "300000")  # 5 分钟
os.environ.setdefault("BASH_MAX_TIMEOUT_MS", "600000")      # 最大 10 分钟
os.environ.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "64000")

MAX_RESUME_ATTEMPTS = 2


def _tool_call_summary(tool_name: str, tool_input: dict) -> str:
    """生成工具调用的摘要。"""
    if tool_name in ("Read", "Glob", "Grep"):
        path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern") or ""
        return str(path)
    if tool_name in ("Write", "Edit"):
        path = tool_input.get("file_path") or ""
        return str(path)
    if tool_name == "Bash":
        return tool_input.get("command") or ""
    if tool_name == "Task":
        return tool_input.get("description") or tool_input.get("prompt") or ""
    return str(tool_input)


def _make_workspace_guard(workspace: Path):
    """PreToolUse hook：阻止 agent 在 workspace 外读写文件。"""
    workspace_str = str(workspace.resolve())

    async def guard(input_data, _tool_use_id, _context):
        # SDK 传入的 input_data 直接就是工具输入字典（如 {"file_path": "..."}）
        tool_input = input_data if isinstance(input_data, dict) else {}
        file_path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern") or ""
        if not file_path:
            return {}
        p = Path(file_path)
        resolved = str((workspace / p).resolve() if not p.is_absolute() else p.resolve())
        if not resolved.startswith(workspace_str + "/") and resolved != workspace_str:
            return {
                "continue_": False,
                "stopReason": (
                    f"File access blocked: '{file_path}' is outside the workspace. "
                    f"Only read/write files within: {workspace}"
                ),
            }
        return {}

    return guard


class NativeCCSession(AgentSession):
    """
    基于 claude_agent_sdk.query() 的 session。

    - 第一次 send()：新会话，从 SystemMessage(init) 获取 session_id
    - 后续 send()：resume=session_id，实现多轮对话
    - stop_reason=tool_use 时自动 resume（最多 MAX_RESUME_ATTEMPTS 次）
    """

    def __init__(self, workspace: Path, config: RunnerConfig):
        self.session_id: str | None = None
        self._workspace = workspace
        self._config = config
        self._model = resolve_model(config.model, config.runner_type)

    async def send(self, message: str, *, stop_on_tools: set[str] | None = None) -> str:
        text_parts: list[str] = []
        stop_reason: str | None = None
        early_stopped = False

        workspace_guard = _make_workspace_guard(self._workspace)
        file_tools = ["Write", "Edit", "Read", "Glob", "Grep"]
        hooks = {
            "PreToolUse": [
                HookMatcher(matcher=tool, hooks=[workspace_guard])
                for tool in file_tools
            ]
        }

        # B2 模式：通过 PreToolUse hook 拦截执行工具。
        # CC 收到 continue_=False 后会自行停止，无需外部杀进程。
        if stop_on_tools:
            async def _block_exec_tool(_input_data, _tool_use_id, _context):
                nonlocal early_stopped
                early_stopped = True
                return {
                    "continue_": False,
                    "stopReason": "Clarification-only mode: this tool is not permitted.",
                }
            for tool in stop_on_tools:
                hooks["PreToolUse"].append(
                    HookMatcher(matcher=tool, hooks=[_block_exec_tool])
                )

        for attempt in range(MAX_RESUME_ATTEMPTS + 1):
            if early_stopped:
                break

            use_resume = self.session_id is not None
            prompt = "" if attempt > 0 else message
            max_turns = 40 if attempt > 0 else self._config.max_turns

            if attempt > 0:
                self._emit(AgentEvent(type="info", content=f"[auto-resume #{attempt}] stop_reason=tool_use, resuming {self.session_id}..."))

            # CCFamouRunner 场景：.claude/settings.json 中指定了默认 agent，
            # 需要 setting_sources=["project"] 才会生效
            use_project_settings = (
                self._config.agent_config_dir is not None
                or self._config.skill_set != "none"
            )

            model_opts = {"model": self._model} if self._model else {}
            gen = query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    cwd=str(self._workspace),
                    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                    permission_mode="bypassPermissions",
                    max_turns=max_turns,
                    resume=self.session_id if use_resume else None,
                    hooks=hooks,
                    thinking={"type": "adaptive"},
                    effort="high",
                    **({"setting_sources": ["project"]} if use_project_settings else {}),
                    **model_opts,
                ),
            )
            try:
                async for msg in gen:
                    if isinstance(msg, SystemMessage) and msg.subtype == "init":
                        if self.session_id is None:
                            self.session_id = msg.data.get("session_id")
                            self._emit(AgentEvent(type="info", content=f"session_id: {self.session_id}"))

                    elif isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock) and block.text.strip():
                                text_parts.append(block.text)
                                self._emit(AgentEvent(type="text", content=block.text))
                            elif isinstance(block, ToolUseBlock):
                                tool_name = block.name
                                tool_input = block.input or {}
                                summary = _tool_call_summary(tool_name, tool_input)
                                self._emit(AgentEvent(type="tool_call", tool=tool_name, tool_input=summary))

                    elif isinstance(msg, ResultMessage):
                        stop_reason = msg.stop_reason
            finally:
                await gen.aclose()

            if early_stopped:
                self._emit(AgentEvent(type="info",
                    content="[early stop] 执行工具被 hook 拦截，CC 已停止"))
                break
            if stop_reason != "tool_use":
                break

        return "\n".join(text_parts)

    async def close(self) -> None:
        pass  # CC session 无需显式关闭


class NativeCCRunner(AgentRunner):
    """直接使用 claude_agent_sdk 运行 CC，无需额外配置文件。"""

    async def start(self, workspace: Path) -> NativeCCSession:
        workspace.mkdir(parents=True, exist_ok=True)

        if self.config.skill_set != "none":
            from ..agent_builder import copy_skills
            copy_skills(self.config.skill_set, None, workspace, platform=".claude")

        return NativeCCSession(workspace, self.config)
