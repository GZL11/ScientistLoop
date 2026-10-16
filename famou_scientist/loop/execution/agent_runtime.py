"""实现智能体运行时与命令后端。"""
from __future__ import annotations

import json
import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from ..utils import (
    atomic_write_json,
    atomic_write_text,
    new_id,
    now_ms,
    read_json,
)
from ..domain.status import LoopStatus
from ..observability import normalize_command_telemetry
from .agent_presets import build_agent_preset_command, normalize_agent_runtime
from .sandbox import ExecutionSandbox
from .workspace import AgentWorkspace


@dataclass(frozen=True)
class ImplementRequest:
    """承载一次实现任务的输入上下文。"""
    goal: Mapping[str, Any]
    idea: Mapping[str, Any]
    workspace: AgentWorkspace
    sandbox: ExecutionSandbox
    instruction: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ImplementResult:
    """承载一次实现任务的标准结果。"""

    status: str
    branch_id: str
    workspace: str
    worktree: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    failure: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可持久化的字典。"""
        value = {
            "status": self.status,
            "branch_id": self.branch_id,
            "workspace": self.workspace,
            "worktree": self.worktree,
            "output": self.output,
        }
        if self.error:
            value["error"] = self.error
        if self.failure:
            value["failure"] = self.failure
        if self.telemetry:
            value["telemetry"] = self.telemetry
        return value


@runtime_checkable
class ImplementAgent(Protocol):
    """定义实现智能体接口。"""

    def implement(self, request: ImplementRequest) -> ImplementResult:
        """实现候选研究想法并返回结果。"""
        ...


@runtime_checkable
class ToolUsingImplementAgent(ImplementAgent, Protocol):
    """标记能够使用工具的实现智能体接口。"""

    def run_turn(self, request: ImplementRequest, instruction: str) -> ImplementResult:
        """执行一次工具使用回合。"""
        ...


class SingleCallImplementer:
    """适配单次调用形式的实现节点。"""

    def __init__(self, handler):
        """初始化对象并保存必要配置。"""
        self.handler = handler

    def implement(self, request: ImplementRequest) -> ImplementResult:
        """实现候选研究想法并返回结果。"""
        try:
            output = self.handler(request)
            if not isinstance(output, dict):
                raise TypeError(
                    f"single-call implementer returned {type(output).__name__}, expected dict"
                )
            return ImplementResult(
                status=LoopStatus.Implementation.IMPLEMENTED,
                branch_id=request.workspace.branch_id,
                workspace=str(request.workspace.root),
                worktree=str(request.workspace.worktree),
                output=output,
            )
        except Exception as exc:  # noqa: BLE001 - result is persisted by caller
            return ImplementResult(
                status=LoopStatus.Implementation.FAILED,
                branch_id=request.workspace.branch_id,
                workspace=str(request.workspace.root),
                worktree=str(request.workspace.worktree),
                error=repr(exc),
            )


def _implementation_values(
    request: ImplementRequest,
    *,
    input_path: Path,
    output_path: Path,
    instruction_path: Path,
    config_dir: Path | None,
) -> dict[str, str]:
    """构建命令模板可用的安全变量。"""

    values = {
        "input": str(input_path),
        "output": str(output_path),
        "instruction": str(instruction_path),
        "workspace": str(request.workspace.root),
        "branch_dir": str(request.workspace.root),
        "worktree": str(request.workspace.worktree),
        "public_dir": str(request.workspace.public),
        "outputs_dir": str(request.workspace.outputs),
        "logs_dir": str(request.workspace.logs),
        "branch_id": request.workspace.branch_id,
        "idea_id": str(request.idea.get("id") or ""),
    }
    if config_dir is not None:
        values["config_dir"] = str(config_dir)
    else:
        values["config_dir"] = ""
    return values


class CommandImplementAgent:
    """在分支工作空间中运行外部编码智能体。"""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: str | Path | None = None,
    ):
        """初始化对象并保存必要配置。"""
        self.config = dict(config)
        self.command = str(self.config.get("cmd") or self.config.get("command") or "")
        configured_runtime = normalize_agent_runtime(self.config)
        # 显式命令是逃生口，优先级高于预设；此路径下不记录预设运行时。
        self.runtime = "" if self.command else configured_runtime
        if not self.command and not self.runtime:
            raise ValueError(
                "agent implement config requires either cmd or "
                "runtime=opencode|codex|claude"
            )
        self.timeout_sec = float(self.config.get("timeout_sec") or 3600)
        self.config_dir = Path(config_dir).expanduser().resolve() if config_dir else None
        instruction = self.config.get("instruction")
        self.instruction = str(instruction) if instruction else ""

    def _format_command(self, request: ImplementRequest, *, input_path: Path, output_path: Path, instruction_path: Path) -> list[str]:
        """格式化实现智能体命令。"""
        if not self.command:
            # 预设负责把统一请求翻译为 Claude/Codex/OpenCode 各自的 CLI 参数；
            # 调度器本身不依赖具体 Agent 产品的命令格式。
            return build_agent_preset_command(
                self.config,
                workspace=request.workspace,
                input_path=input_path,
                output_path=output_path,
                instruction_path=instruction_path,
            )

        values = _implementation_values(
            request,
            input_path=input_path,
            output_path=output_path,
            instruction_path=instruction_path,
            config_dir=self.config_dir,
        )
        # 在切分参数前引用变量，确保含空格路径仍是单个参数，且配置命令不会经由外壳执行。
        quoted = {key: shlex.quote(value) for key, value in values.items()}
        try:
            formatted = self.command.format(**quoted)
        except KeyError as exc:
            raise ValueError(f"unknown implement agent command placeholder: {exc.args[0]}") from exc
        argv = shlex.split(formatted)
        if not argv:
            raise ValueError("implement agent command resolved to an empty argv")
        return argv

    def _stage_fmjob_runtime(self, request: ImplementRequest) -> None:
        """Stage the CLI wrapper and its small runtime package inside the FMJob trial.

        FMJob mounts only the configured trial subpath.  The controller checkout
        therefore cannot be referenced directly by a command running remotely.
        Keep this bundle deliberately small: the wrapper needs prompt rendering,
        telemetry normalization, and the shared JSON/path helpers only.
        """
        sandbox = self.config.get("sandbox")
        if not isinstance(sandbox, Mapping) or str(sandbox.get("type") or "").lower() not in {
            "fmjob",
            "fm-job",
        }:
            return
        source_root = Path(__file__).resolve().parents[2]
        stage_root = request.workspace.root / ".famou_runtime"
        staged_pkg = stage_root / "famou_scientist"
        staged_loop = staged_pkg / "loop"
        staged_prompts = staged_loop / "prompts"
        staged_prompts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / "__init__.py", staged_pkg / "__init__.py")
        shutil.copy2(source_root / "loop" / "__init__.py", staged_loop / "__init__.py")
        shutil.copy2(source_root / "loop" / "utils.py", staged_loop / "utils.py")
        shutil.copy2(source_root / "loop" / "observability.py", staged_loop / "observability.py")
        shutil.copy2(source_root / "loop" / "prompts" / "__init__.py", staged_prompts / "__init__.py")
        for prompt in (source_root / "loop" / "prompts").rglob("*.md"):
            target = staged_prompts / prompt.relative_to(source_root / "loop" / "prompts")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prompt, target)
        staged_execution = staged_loop / "execution"
        staged_execution.mkdir(parents=True, exist_ok=True)
        staged_wrapper = staged_execution / "cli_agent_wrapper.py"
        shutil.copy2(Path(__file__).with_name("cli_agent_wrapper.py"), staged_wrapper)
        # The wrapper adds parents[3] to sys.path; preserve that layout in the
        # trial so imports resolve without exposing the controller checkout.
        self.config["wrapper_path"] = str(staged_wrapper)

    def implement(self, request: ImplementRequest) -> ImplementResult:
        """实现候选研究想法并返回结果。"""
        role = str(self.config.get("role") or "implement").strip().lower()
        if role not in {
            "idea",
            "idea_rank",
            "idea_judge",
            "experience_summary",
            "implement",
            "terminal_solver",
            "scimodeling_researcher",
            "terminal_verifier",
        }:
            raise ValueError(f"unsupported agent role: {role!r}")
        completion_mode = str(self.config.get("completion_mode") or "natural_exit")
        call_id = new_id("implement_agent")
        request_path = request.workspace.logs / f"{call_id}.request.json"
        result_path = request.workspace.outputs / f"{call_id}.result.json"
        instruction_path = request.workspace.public / f"{role.upper()}_INSTRUCTIONS.md"
        log_path = request.workspace.logs / f"{call_id}.log"

        # request.json 保存机器可读上下文，INSTRUCTIONS.md 保存角色说明；需要结构化
        # 结果的角色使用 result.json 作为唯一机器协议出口。
        instruction = request.instruction or self.instruction
        context = implementation_context(request)
        context["call_id"] = call_id
        context["instruction_path"] = str(instruction_path)
        context["result_path"] = str(result_path)
        summary_format = str(self.config.get("format") or "markdown").lower()
        markdown_summary = role == "experience_summary" and summary_format in {
            "markdown",
            "md",
        }
        context["agent_contract"] = {
            "must_write_result_json": (
                role not in {"implement", "terminal_solver", "scimodeling_researcher"}
                and not (role == "terminal_verifier" and completion_mode == "natural_exit")
                and not markdown_summary
            ),
            "summary_format": "markdown" if markdown_summary else (
                "structured_json" if role == "experience_summary" else None
            ),
            "result_path": str(result_path),
            "role": role,
            "must_write_code_under": (
                str(request.workspace.worktree)
                if role in {"implement", "terminal_solver", "scimodeling_researcher"}
                else None
            ),
            "hidden_evaluator": "unavailable",
            "official_evaluator": "unavailable",
            "must_submit_candidate": (
                role == "implement"
                and bool(self.runtime)
                and bool(self.config.get("require_submit_candidate"))
            ),
            "result_written_by_submit_command": role == "implement" and bool(self.runtime),
        }
        atomic_write_json(request_path, context)
        atomic_write_text(
            instruction_path,
            instruction or (
                "Implement the requested idea in the branch worktree. "
                "Do not access hidden evaluator data. "
                "Write a JSON result to the supplied result path."
            ),
        )

        meta: dict[str, Any] = {
            "id": call_id,
            "type": "command_implement_agent",
            "request_path": str(request_path),
            "result_path": str(result_path),
            "instruction_path": str(instruction_path),
            "log_path": str(log_path),
            "created_at": now_ms(),
            "role": role,
        }
        if self.runtime:
            meta["runtime"] = self.runtime
        try:
            self._stage_fmjob_runtime(request)
            argv = self._format_command(
                request,
                input_path=request_path,
                output_path=result_path,
                instruction_path=instruction_path,
            )
            meta["command"] = argv
            # 环境变量只传递当前调用的受控路径。Agent 不会收到 evaluator 路径、
            # ground truth 或其他 branch 的位置。
            env = {
                "FAMOU_IMPLEMENT_AGENT_INPUT": str(request_path),
                "FAMOU_IMPLEMENT_AGENT_OUTPUT": str(result_path),
                "FAMOU_IMPLEMENT_AGENT_WORKTREE": str(request.workspace.worktree),
                "FAMOU_IMPLEMENT_AGENT_MAX_TURNS": str(self.config.get("max_turns") or ""),
            }
            # FMJob containers do not inherit host credentials.  Forward only
            # provider variables explicitly used by the selected CLI, never
            # the complete controller environment.
            for provider_key in (
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "KIMI_API_KEY",
                "Z_CODE_API_KEY",
            ):
                provider_value = os.environ.get(provider_key)
                if provider_value:
                    env[provider_key] = provider_value
            terminal_round = request.metadata.get("terminal_context", {}).get("round")
            if terminal_round is not None:
                env["FAMOU_TERMINAL_ROUND"] = str(terminal_round)
            # Verifier prompt versions are selected by the controller, but the
            # CLI wrapper runs inside the FMJob container. Forward only this
            # non-secret selector so the remote VerifierAgent uses the same
            # version requested for the trial.
            if role == "terminal_verifier":
                verifier_prompt_version = os.environ.get(
                    "FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION"
                )
                if verifier_prompt_version:
                    env["FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION"] = (
                        verifier_prompt_version
                    )
            if role in {"terminal_solver", "scimodeling_researcher"}:
                resource_limits = request.metadata.get("terminal_context", {}).get(
                    "resource_limits", {}
                )
                if isinstance(resource_limits, Mapping):
                    if resource_limits.get("cpu") is not None:
                        env["FAMOU_ALLOCATED_CPU"] = str(resource_limits["cpu"])
                    if resource_limits.get("memory") is not None:
                        env["FAMOU_ALLOCATED_MEMORY"] = str(resource_limits["memory"])
                # Avoid multiplying a small FMJob CPU allocation through each
                # numerical library used by an Agent-authored worker process.
                env.update(
                    {
                        "OMP_NUM_THREADS": "1",
                        "OPENBLAS_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1",
                        "NUMEXPR_NUM_THREADS": "1",
                    }
                )
            run_result = request.sandbox.run(
                argv,
                cwd=request.workspace.worktree,
                env=env,
                timeout_sec=self.timeout_sec,
                cancel_file=self.config.get("cancel_file"),
            )
            meta["run"] = run_result.to_dict()
            if self.runtime:
                # wrapper 维护 Actor 级持久 Session；这里把会话引用带回调度层，
                # 使 actors/state.json 可以独立说明后续回合应恢复哪个上下文。
                session_path = (
                    request.workspace.logs
                    / f"{self.runtime}_{str(self.config.get('session_key') or role)}_session.json"
                )
                session = read_json(session_path)
                if isinstance(session, dict):
                    meta["session"] = {
                        **session,
                        "state_path": str(session_path),
                    }
            # 无论成功失败都保留完整 CLI stdout/stderr，便于定位模型、认证或代码问题。
            atomic_write_text(
                log_path,
                "[command]\n"
                + json.dumps(argv, ensure_ascii=False)
                + "\n\n[stdout]\n"
                + run_result.stdout
                + "\n\n[stderr]\n"
                + run_result.stderr
                + "\n",
            )
            parsed: dict[str, Any] = {}
            parse_error: str | None = None
            # Terminal solver/compiler 的主要结果是 worktree 产物；自然退出时不要求
            # 再写一份 JSON。其他角色以及 terminal_verifier 的 diagnose（structured_result）
            # 仍必须遵守结构化结果协议。
            allow_natural_exit = (
                completion_mode == "natural_exit"
                and role in {"terminal_solver", "terminal_verifier", "scimodeling_researcher"}
                and run_result.valid
            )
            if result_path.exists():
                # 优先读取约定的结果文件；stdout 可能包含 Agent 自身日志，不适合作为
                # 默认机器协议。
                try:
                    raw = json.loads(result_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        parsed = raw
                    else:
                        parse_error = "agent result must be a JSON object"
                except json.JSONDecodeError as exc:
                    parse_error = repr(exc)
            elif run_result.stdout.strip():
                # stdout 最后一行 JSON 只作为兼容旧 Agent wrapper 的回退路径，并立即
                # 固化到 result_path，使后续证据布局保持一致。
                try:
                    raw = json.loads(run_result.stdout.strip().splitlines()[-1])
                    if isinstance(raw, dict):
                        parsed = raw
                        atomic_write_json(result_path, raw)
                    else:
                        parse_error = "agent stdout JSON must be an object"
                except json.JSONDecodeError as exc:
                    if allow_natural_exit:
                        parsed = {
                            "status": "completed",
                            "termination_reason": "natural_exit",
                        }
                    else:
                        parse_error = repr(exc)
            else:
                if allow_natural_exit:
                    parsed = {
                        "status": "completed",
                        "termination_reason": "natural_exit",
                    }
                else:
                    parse_error = "missing agent result JSON"
            meta["parse_error"] = parse_error
            meta["valid"] = run_result.valid and parse_error is None
            wrapper_meta: dict[str, Any] = {}
            for line in reversed(run_result.stdout.splitlines()):
                try:
                    wrapper_value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(wrapper_value, dict):
                    wrapper_meta = wrapper_value
                    break
            wrapper_telemetry = wrapper_meta.get("telemetry")
            if isinstance(wrapper_telemetry, dict):
                # 预设 CLI wrapper 负责解析供应商原生 usage 和 Session 增量轨迹。
                # 上层只传递标准结构，不读取 Claude/Codex 私有目录。
                meta["telemetry"] = dict(wrapper_telemetry)
            else:
                # 自定义命令也进入同一 ledger。若命令没有主动返回 usage，Token 与
                # cost 保持为空，但调用时长、状态和证据路径仍完整留存。
                telemetry = normalize_command_telemetry(parsed)
                telemetry.update(
                    {
                        "adapter": "cli",
                        "runtime": self.runtime or "command",
                        "role": role,
                        "status": "succeeded" if meta["valid"] else "failed",
                        "started_at_ms": int(meta["created_at"]),
                        "finished_at_ms": int(meta["created_at"])
                        + int(run_result.duration_ms),
                        "duration_ms": int(run_result.duration_ms),
                        "returncode": int(run_result.returncode),
                        "model": telemetry.get("model")
                        or self.config.get("model"),
                        "trajectory": {
                            "normalized_path": None,
                            "records": 0,
                            "native_refs": [],
                            "resume_delta": False,
                        },
                    }
                )
                meta["telemetry"] = telemetry
            failure = (
                dict(wrapper_meta.get("failure"))
                if isinstance(wrapper_meta.get("failure"), dict)
                else {}
            )
            if not run_result.valid and not failure:
                diagnostic = run_result.stderr.strip() or run_result.stdout.strip()
                failure = {
                    "returncode": int(run_result.returncode),
                    "timed_out": bool(run_result.timed_out),
                    "error_code": str(
                        run_result.termination_reason or "nonzero_exit"
                    ),
                    "message": diagnostic or "agent command failed without diagnostics",
                }
            if failure:
                meta["failure"] = failure
            # 调用元数据附在内部保留字段中，由上层单独写入 worker_call artifact；
            # 生成的方法规格会显式移除该字段。
            parsed["__agent_call__"] = meta
            if not meta["valid"]:
                return ImplementResult(
                    status=LoopStatus.Implementation.FAILED,
                    branch_id=request.workspace.branch_id,
                    workspace=str(request.workspace.root),
                    worktree=str(request.workspace.worktree),
                    output=parsed,
                    error=(
                        str(failure.get("message"))
                        if failure.get("message")
                        else "agent command failed"
                        if not parse_error
                        else f"agent result invalid: {parse_error}"
                    ),
                    failure=failure,
                    telemetry=dict(meta.get("telemetry") or {}),
                )
            if str(parsed.get("status") or LoopStatus.Implementation.IMPLEMENTED) in {
                "failed",
                LoopStatus.Implementation.FAILED,
                "rejected",
            }:
                # 进程退出码为 0 不等于科研实现成功；Agent 可以通过结构化状态主动
                # 报告失败，上层会把它写入 ExpBank 而不是送去实验。
                return ImplementResult(
                    status=LoopStatus.Implementation.FAILED,
                    branch_id=request.workspace.branch_id,
                    workspace=str(request.workspace.root),
                    worktree=str(request.workspace.worktree),
                    output=parsed,
                    error=str(parsed.get("error") or "agent reported implementation failure"),
                    failure=(
                        dict(parsed.get("failure"))
                        if isinstance(parsed.get("failure"), dict)
                        else {}
                    ),
                    telemetry=dict(meta.get("telemetry") or {}),
                )
            return ImplementResult(
                status=LoopStatus.Implementation.IMPLEMENTED,
                branch_id=request.workspace.branch_id,
                workspace=str(request.workspace.root),
                worktree=str(request.workspace.worktree),
                output=parsed,
                telemetry=dict(meta.get("telemetry") or {}),
            )
        except Exception as exc:  # noqa: BLE001 - caller persists failure evidence
            # 把 wrapper 自身异常转换成普通失败结果，隔离单个 Agent 调用，避免线程池
            # Future 直接抛异常终止整个循环。
            meta["valid"] = False
            meta["error"] = repr(exc)
            atomic_write_json(request.workspace.logs / f"{call_id}.error.json", meta)
            return ImplementResult(
                status=LoopStatus.Implementation.FAILED,
                branch_id=request.workspace.branch_id,
                workspace=str(request.workspace.root),
                worktree=str(request.workspace.worktree),
                output={"__agent_call__": meta},
                error=repr(exc),
                failure={
                    "failure_stage": "agent_wrapper",
                    "error_code": "agent_wrapper_exception",
                    "return_code": None,
                    "signal": None,
                    "timed_out": False,
                    "submitted": False,
                    "retryable": True,
                    "message": repr(exc),
                    "suggested_action": "检查 wrapper 配置和日志后恢复原 Actor。",
                    "evidence_refs": [str(request.workspace.logs / f"{call_id}.error.json")],
                },
                telemetry=dict(meta.get("telemetry") or {}),
            )


def implementation_context(
    request: ImplementRequest,
    *,
    instruction_path: str | Path | None = None,
) -> dict[str, Any]:
    """构建可暴露给实现智能体的安全上下文。"""

    return {
        "goal": dict(request.goal),
        "idea": dict(request.idea),
        "branch_id": request.workspace.branch_id,
        "workspace": str(request.workspace.root),
        "worktree": str(request.workspace.worktree),
        "public_dir": str(request.workspace.public),
        "outputs_dir": str(request.workspace.outputs),
        "instruction": request.instruction,
        "instruction_path": str(instruction_path) if instruction_path else None,
        "hidden_evaluator": "unavailable",
        "metadata": dict(request.metadata),
    }


__all__ = [
    "ImplementAgent",
    "ImplementRequest",
    "ImplementResult",
    "CommandImplementAgent",
    "SingleCallImplementer",
    "ToolUsingImplementAgent",
    "implementation_context",
]
