"""
runner_from_config — 根据 RunnerConfig 创建对应的 AgentRunner 实例。
"""

from .base import AgentRunner, RunnerConfig
from .cc_cli import CCCLIRunner, CCCLINativeRunner
from .opencode_run import OpenCodeRunner, OpenCodeNativeRunner

_REGISTRY = {
    "cc_native":        CCCLINativeRunner,
    "cc_famou":         CCCLIRunner,
    "cc_single":        CCCLIRunner,        # 复用，注入 .claude-single/ 配置
    "opencode_native":  OpenCodeNativeRunner,
    "opencode_famou":   OpenCodeRunner,
    "opencode_single":  OpenCodeRunner,     # 复用，注入 .opencode-single/ 配置
}


def runner_from_config(config: RunnerConfig) -> AgentRunner:
    cls = _REGISTRY.get(config.runner_type)
    if cls is None:
        valid = ", ".join(_REGISTRY)
        raise ValueError(
            f"Unknown runner_type: '{config.runner_type}'. Valid options: {valid}"
        )
    return cls(config)
