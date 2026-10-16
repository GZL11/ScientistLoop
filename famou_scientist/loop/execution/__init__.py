"""实现智能体的执行边界与隔离组件。"""

from .agent_runtime import (
    CommandImplementAgent,
    ImplementAgent,
    ImplementRequest,
    ImplementResult,
    SingleCallImplementer,
    ToolUsingImplementAgent,
)
from .agent_presets import (
    SUPPORTED_AGENT_RUNTIMES,
    build_agent_preset_command,
    normalize_agent_runtime,
)
from .agent_turn import AgentTurnRequest, AgentTurnResult, CommandAgentTurn
from .sandbox import (
    ExecutionIdentity,
    ExecutionSandbox,
    LocalSandbox,
    SandboxError,
    SandboxRunResult,
    sandbox_from_config,
)
from .resources import discover_gpu_devices, resource_envelope_dict
from .workspace import AgentWorkspace, WorkspacePathError

__all__ = [
    "AgentTurnRequest",
    "AgentTurnResult",
    "AgentWorkspace",
    "CommandAgentTurn",
    "CommandImplementAgent",
    "ExecutionIdentity",
    "ExecutionSandbox",
    "ImplementAgent",
    "ImplementRequest",
    "ImplementResult",
    "LocalSandbox",
    "SandboxError",
    "SandboxRunResult",
    "SingleCallImplementer",
    "SUPPORTED_AGENT_RUNTIMES",
    "ToolUsingImplementAgent",
    "WorkspacePathError",
    "build_agent_preset_command",
    "normalize_agent_runtime",
    "sandbox_from_config",
    "discover_gpu_devices",
    "resource_envelope_dict",
]
