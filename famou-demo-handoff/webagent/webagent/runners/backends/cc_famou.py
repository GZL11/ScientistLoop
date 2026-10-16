"""
CCFamouRunner — 使用 claude_agent_sdk 运行 CC，同时注入 Famou 双 agent 配置。

与 NativeCCRunner 的唯一区别：
- start() 时将 RunnerConfig.agent_config_dir (.claude/) 复制到 workspace/.claude/
- CC 启动后自动发现 workspace/.claude/agents/，加载 famou-master / famou-build
"""

import shutil
from pathlib import Path

from .base import AgentRunner, RunnerConfig
from .native_cc import NativeCCSession


class CCFamouRunner(AgentRunner):
    """
    CC + Famou 双 agent runner。
    需要 RunnerConfig.agent_config_dir 指向 agents/.claude/。
    """

    async def start(self, workspace: Path) -> NativeCCSession:
        workspace.mkdir(parents=True, exist_ok=True)

        # 复制基础配置（settings.json 等）并组装 agents/ 目录
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

        return NativeCCSession(workspace, self.config)
