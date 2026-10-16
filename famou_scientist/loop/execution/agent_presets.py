"""命令行智能体预设配置。"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .workspace import AgentWorkspace


# These runtimes share the same request/result wrapper, while the wrapper
# keeps each CLI's native flags separate.
SUPPORTED_AGENT_RUNTIMES = frozenset(
    {"opencode", "codex", "claude", "kimi-code", "z-code"}
)


def normalize_agent_runtime(config: Mapping[str, Any]) -> str:
    """归一化命令行智能体运行时配置。"""

    runtime = str(config.get("runtime") or config.get("preset") or "").strip().lower()
    if runtime in {"", "command", "cmd", "custom"}:
        return ""
    if runtime not in SUPPORTED_AGENT_RUNTIMES:
        raise ValueError(
            f"unsupported implement agent runtime: {runtime!r}; "
            f"supported runtimes: {', '.join(sorted(SUPPORTED_AGENT_RUNTIMES))}"
        )
    return runtime


def _string_list(value: Any) -> list[str]:
    """将配置值转换为字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    raise ValueError("agent preset extra_args must be a string or a list of strings")


def _bool_config(value: Any, *, default: bool) -> bool:
    """解析布尔配置值。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean config value: {value!r}")


def build_agent_preset_command(
    config: Mapping[str, Any],
    *,
    workspace: AgentWorkspace,
    input_path: Path,
    output_path: Path,
    instruction_path: Path,
) -> list[str]:
    """构建命令行智能体预设命令。"""

    runtime = normalize_agent_runtime(config)
    if not runtime:
        raise ValueError(
            "agent preset command requires runtime=opencode|codex|claude|kimi-code|z-code"
        )

    # FMJob containers only mount the trial subpath.  Launchers may stage the
    # wrapper inside that subpath and provide its path without exposing the
    # controller checkout to the remote Agent.
    wrapper_path = Path(
        str(config.get("wrapper_path") or os.environ.get("FAMOU_AGENT_WRAPPER_PATH") or
            Path(__file__).with_name("cli_agent_wrapper.py").resolve())
    ).expanduser().resolve()
    if not wrapper_path.is_file():
        raise FileNotFoundError(f"CLI agent wrapper not found: {wrapper_path}")

    default_binaries = {
        # The installed Kimi Code CLI is named `kimi`, while the runtime name
        # remains `kimi-code` in goal files for provider clarity.
        "kimi-code": "kimi",
        # z-code is the project-facing name for Baidu Comate Zulu.
        "z-code": "zulu",
    }
    python_binary = str(
        config.get("python_binary")
        or os.environ.get("FAMOU_AGENT_PYTHON")
        or sys.executable
    )
    argv = [
        python_binary,
        str(wrapper_path),
        "--runtime",
        runtime,
        "--binary",
        str(config.get("binary") or default_binaries.get(runtime) or runtime),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--instruction",
        str(instruction_path),
        "--worktree",
        str(workspace.worktree),
        "--logs-dir",
        str(workspace.logs),
        "--outputs-dir",
        str(workspace.outputs),
        "--title",
        str(config.get("title") or f"famou-loop-{workspace.branch_id}"),
    ]

    role = str(config.get("role") or "implement").strip().lower()
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
    argv.extend(["--role", role])

    session_key = config.get("session_key")
    if session_key not in (None, ""):
        argv.extend(["--session-key", str(session_key)])
    completion_mode = config.get("completion_mode")
    if completion_mode not in (None, ""):
        argv.extend(["--completion-mode", str(completion_mode)])

    for key, option in (
        ("model", "--model"),
        ("agent", "--agent"),
        ("profile", "--profile"),
        ("max_turns", "--max-turns"),
    ):
        value = config.get(key)
        if value not in (None, ""):
            argv.extend([option, str(value)])

    timeout = config.get("timeout_sec")
    wrapper_timeout: float | None = None
    if timeout not in (None, ""):
        timeout_value = float(timeout)
        # 预设包装器需要一点宽限时间，以便在外层沙箱超时前终止底层命令并写入元数据。
        wrapper_timeout = max(1.0, timeout_value - min(30.0, max(5.0, timeout_value * 0.1)))
        argv.extend(["--timeout-sec", str(wrapper_timeout)])

    memory_limit = config.get("process_memory_limit_bytes")
    if memory_limit not in (None, ""):
        memory_limit_bytes = int(memory_limit)
        if memory_limit_bytes <= 0:
            raise ValueError("process_memory_limit_bytes 必须大于 0")
        argv.extend(["--memory-limit-bytes", str(memory_limit_bytes)])

    # Claude sessions can exceed a custom gateway's context limit before the
    # CLI's default compaction heuristic recognizes the model. Keep the
    # recovery enabled by default in the wrapper, while allowing benchmark
    # configs to opt out explicitly.
    if runtime == "claude" and config.get("compact_on_context_overflow") is not None:
        if _bool_config(config.get("compact_on_context_overflow"), default=True):
            argv.append("--compact-on-context-overflow")
        else:
            argv.append("--no-compact-on-context-overflow")

    heartbeat = config.get("deadline_heartbeat")
    if isinstance(heartbeat, Mapping) and _bool_config(
        heartbeat.get("enabled"),
        default=False,
    ):
        if role != "implement":
            raise ValueError("deadline_heartbeat 只支持 Implement Agent")
        if wrapper_timeout is None:
            raise ValueError("启用 deadline_heartbeat 时必须配置 timeout_sec")
        trigger_after_sec = float(heartbeat.get("trigger_after_sec") or 2400)
        if trigger_after_sec <= 0 or trigger_after_sec >= wrapper_timeout:
            raise ValueError(
                "deadline_heartbeat.trigger_after_sec 必须大于 0 且小于 Agent timeout"
            )
        argv.extend(
            ["--deadline-heartbeat-after-sec", str(trigger_after_sec)]
        )

    submission_grace = config.get("submission_grace_sec")
    if submission_grace not in (None, ""):
        argv.extend(
            ["--submission-grace-sec", str(max(0.0, float(submission_grace)))]
        )
    if role == "implement" and _bool_config(
        config.get("require_submit_candidate"),
        default=False,
    ):
        argv.append("--require-submit-candidate")

    # 默认不联网。允许联网的 benchmark 在 workers 配置里显式打开。
    if _bool_config(config.get("allow_network_tools"), default=False):
        argv.append("--allow-network-tools")

    cancel_file = config.get("cancel_file")
    if cancel_file not in (None, ""):
        argv.extend(["--cancel-file", str(cancel_file)])

    if _bool_config(config.get("auto_approve"), default=True):
        argv.append("--auto-approve")
    else:
        argv.append("--no-auto-approve")

    for extra in _string_list(config.get("extra_args")):
        argv.extend(["--extra-arg", extra])

    return argv


__all__ = [
    "SUPPORTED_AGENT_RUNTIMES",
    "build_agent_preset_command",
    "normalize_agent_runtime",
]
