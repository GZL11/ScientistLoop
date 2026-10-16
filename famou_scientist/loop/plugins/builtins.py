"""Famou 随包提供的通用 Adapter。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class CliAgentAdapter:
    """把 Claude Code、Codex、OpenCode 或自定义命令接到统一 Agent Runtime。"""

    name = "cli"

    def create(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: str | Path | None = None,
    ) -> Any:
        """延迟导入并创建现有命令行 Agent 实现。"""

        from ..execution.agent_runtime import CommandImplementAgent

        return CommandImplementAgent(config, config_dir=config_dir)

    def create_turn(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: str | Path | None = None,
    ) -> Any:
        """创建以自然退出和显式 session_key 为契约的 Agent turn。"""

        from ..execution.agent_turn import CommandAgentTurn

        return CommandAgentTurn(config, config_dir=config_dir)


__all__ = ["CliAgentAdapter"]
