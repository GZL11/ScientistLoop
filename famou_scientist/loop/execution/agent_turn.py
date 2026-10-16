"""与 SOTA Candidate contract 解耦的通用 Agent turn 适配器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..domain.status import LoopStatus
from .agent_runtime import CommandImplementAgent, ImplementRequest
from .sandbox import ExecutionSandbox
from .workspace import AgentWorkspace


@dataclass(frozen=True)
class AgentTurnRequest:
    """一次可恢复 Agent session 的激活请求。"""

    role: str
    phase: str
    session_key: str
    instruction: str
    workspace: AgentWorkspace
    sandbox: ExecutionSandbox
    context: Mapping[str, Any] = field(default_factory=dict)
    completion_mode: str = "natural_exit"
    timeout_sec: float | None = None


@dataclass(frozen=True)
class AgentTurnResult:
    """Agent 自主退出一个 turn 后的标准结果。"""

    status: str
    phase: str
    session_ref: str | None = None
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    failure: Mapping[str, Any] = field(default_factory=dict)
    telemetry: Mapping[str, Any] = field(default_factory=dict)


class CommandAgentTurn:
    """复用现有 CLI wrapper 执行 Terminal Solver/Verifier turn。"""

    _ROLES = {"terminal_solver", "terminal_verifier", "scimodeling_researcher"}

    def __init__(self, config: Mapping[str, Any], *, config_dir=None):
        self.config = dict(config)
        self.config_dir = config_dir

    def run(self, request: AgentTurnRequest) -> AgentTurnResult:
        if request.role not in self._ROLES:
            raise ValueError(f"unsupported terminal agent role: {request.role!r}")
        if request.completion_mode not in {"natural_exit", "structured_result"}:
            raise ValueError(f"unsupported completion mode: {request.completion_mode!r}")

        config = {
            **self.config,
            "role": request.role,
            "session_key": request.session_key,
            "completion_mode": request.completion_mode,
            "require_submit_candidate": False,
        }
        if request.timeout_sec is not None:
            configured_timeout = float(config.get("timeout_sec") or request.timeout_sec)
            config["timeout_sec"] = max(
                0.1,
                min(configured_timeout, float(request.timeout_sec)),
            )
        agent = CommandImplementAgent(config, config_dir=self.config_dir)
        result = agent.implement(
            ImplementRequest(
                goal={"goal": dict(request.context)},
                idea={
                    "id": f"{request.role}:{request.phase}",
                    "title": request.phase,
                    "mechanism": "terminal_task_agent_turn",
                },
                workspace=request.workspace,
                sandbox=request.sandbox,
                instruction=request.instruction,
                metadata={
                    "terminal_phase": request.phase,
                    "terminal_context": dict(request.context),
                },
            )
        )
        call = result.output.get("__agent_call__")
        call = call if isinstance(call, dict) else {}
        session = call.get("session") if isinstance(call.get("session"), dict) else {}
        session_ref = str(session.get("state_path")) if session.get("state_path") else None
        status = (
            "succeeded"
            if result.status == LoopStatus.Implementation.IMPLEMENTED
            else "failed"
        )
        return AgentTurnResult(
            status=status,
            phase=request.phase,
            session_ref=session_ref,
            output={key: value for key, value in result.output.items() if key != "__agent_call__"},
            error=result.error,
            failure=dict(result.failure),
            telemetry=dict(result.telemetry),
        )


__all__ = ["AgentTurnRequest", "AgentTurnResult", "CommandAgentTurn"]
