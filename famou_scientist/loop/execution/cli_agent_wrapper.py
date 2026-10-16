"""命令行编码智能体的非交互式包装器。"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

# CommandImplementAgent 通过脚本路径启动本文件；此时 Python 不会自动把项目根加入
# sys.path。显式加入源码/安装根，使统一 Prompt 包在独立 branch cwd 下仍可加载。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from famou_scientist.loop.prompts import load_prompt, render_prompt
from famou_scientist.loop.observability import (
    export_incremental_trajectory,
    normalize_cli_telemetry,
    normalize_trajectory_telemetry,
    snapshot_jsonl_files,
)


def _read_text(path: str | Path) -> str:
    """读取文本文件。"""
    return Path(path).read_text(encoding="utf-8") if path else ""


def _load_json(path: str | Path) -> dict[str, Any]:
    """读取结构化数据文件。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object: {path}")
    return raw


def _write_text(path: str | Path, text: str) -> None:
    """写入文本文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | Path, value: dict[str, Any]) -> None:
    """写入结构化数据文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )



def _path_is_writable_dir(path: str | Path | None) -> bool:
    """检查目录是否可写。"""
    if not path:
        return False
    try:
        candidate = Path(path).expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".famou_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _load_claude_settings_env() -> dict[str, str]:
    """加载命令行编码工具所需环境变量且不复制密钥。"""

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("env"), dict):
        return {}
    allowed_prefixes = ("ANTHROPIC_", "CLAUDE_")
    allowed_names = {"API_TIMEOUT_MS"}
    result: dict[str, str] = {}
    for key, value in raw["env"].items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key in allowed_names or key.startswith(allowed_prefixes):
            result[key] = value
    return result


def _runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    """构建子进程运行环境。"""
    env = dict(os.environ)
    if args.runtime == "codex":
        # 命令行工具会在用户目录下持久化会话和日志；托管环境中的默认目录可能只读。
        # 当继承目录不可写时，为分支提供本地可写目录；认证仍来自外部环境。
        current_home = env.get("CODEX_HOME")
        if not _path_is_writable_dir(current_home):
            codex_home = Path(args.logs_dir) / "codex_home"
            codex_home.mkdir(parents=True, exist_ok=True)
            env["CODEX_HOME"] = str(codex_home)
    elif args.runtime == "claude":
        # 命令行编码工具会在用户目录下写会话记录；托管环境中的默认目录可能只读。
        # 为每个分支提供隔离的可写目录，并只注入必要环境变量，不复制可能含密钥的配置文件。
        inherited_claude_env = _load_claude_settings_env()
        env.update({k: v for k, v in inherited_claude_env.items() if k not in env})
        # 极简模式下工具严格读取特定密钥变量；部分部署使用兼容变量名配置令牌。
        if env.get("ANTHROPIC_AUTH_TOKEN") and not env.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = env["ANTHROPIC_AUTH_TOKEN"]
        claude_home = Path(args.logs_dir) / "claude_home"
        claude_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(claude_home)
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    elif args.runtime in {"kimi-code", "z-code"}:
        # Kimi Code persists sessions below HOME/.kimi. Keep that state inside
        # the actor branch so a resumed run is isolated and reproducible.
        inherited_home = Path(env.get("HOME", str(Path.home()))).expanduser()
        kimi_home = Path(args.logs_dir) / f"{args.runtime}_home"
        kimi_home.mkdir(parents=True, exist_ok=True)
        # Kimi Code resolves model aliases from ~/.kimi-code/config.toml. Copy
        # only that runtime config into the isolated home; session history and
        # telemetry must remain branch-local.
        configured_path = env.get("KIMI_CODE_CONFIG")
        source_config = (
            Path(configured_path).expanduser()
            if configured_path
            else inherited_home / ".kimi-code" / "config.toml"
        )
        target_config = kimi_home / ".kimi-code" / "config.toml"
        if source_config.is_file() and not target_config.exists():
            target_config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_config, target_config)
        env["HOME"] = str(kimi_home)
    return env


def _native_trajectory_roots(
    args: argparse.Namespace,
    environment: dict[str, str],
) -> list[Path]:
    """返回当前 CLI Adapter 可能写入原生 Session 的隔离目录。"""

    if args.runtime == "claude":
        return [Path(environment["HOME"]) / ".claude"]
    if args.runtime == "codex":
        codex_home = Path(environment["CODEX_HOME"])
        # 兼容 Codex 把 CODEX_HOME 视为自身目录或用户目录的两种布局。
        return [codex_home, codex_home / ".codex"]
    if args.runtime == "opencode":
        return [Path(args.logs_dir) / "opencode_home"]
    if args.runtime in {"kimi-code", "z-code"}:
        return [Path(args.logs_dir) / f"{args.runtime}_home" / ".kimi"]
    return []


def _extract_last_json_object(stdout: str) -> dict[str, Any] | None:
    """从输出尾部提取结构化结果。"""

    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text or not text.startswith("{"):
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (
            "entrypoint" in obj
            or "files" in obj
            or "hypothesis" in obj
            or "ranking" in obj
            or obj.get("status") in {"implemented", "proposed"}
        ):
            return obj
    return None


def _extract_codex_session_id(stdout: str) -> str | None:
    """从 Codex JSONL 的 thread.started 事件提取真实 Session ID。"""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "thread.started":
            continue
        session_id = event.get("thread_id") or event.get("session_id")
        if session_id:
            return str(session_id)
    return None


def _extract_session_id(stdout: str, runtime: str) -> str | None:
    """Extract a native session id from Codex/Kimi stream JSON output."""

    if runtime == "codex":
        return _extract_codex_session_id(stdout)
    if runtime not in {"kimi-code", "z-code"}:
        return None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        candidates = [
            event.get("session_id"),
            event.get("sessionId"),
            (event.get("session") or {}).get("id")
            if isinstance(event.get("session"), dict)
            else None,
        ]
        event_type = str(event.get("type") or event.get("event") or "").lower()
        if any(value for value in candidates) and (
            "session" in event_type
            or "session_id" in event
            or "sessionId" in event
        ):
            return next(str(value) for value in candidates if value)
    return None


def _last_json_object(value: str) -> dict[str, Any] | None:
    """读取命令输出末尾的任意 JSON 对象。"""

    for line in reversed(value.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _is_context_overflow_result(runtime_result: Mapping[str, Any]) -> bool:
    """识别请求在生成前因上下文窗口超限而被拒绝。"""

    parts = [
        runtime_result.get("result"),
        runtime_result.get("error"),
        runtime_result.get("message"),
    ]
    text = " ".join(str(value) for value in parts if value is not None).lower()
    if not text:
        return False
    markers = (
        "maximum context length",
        "context length",
        "prompt is too long",
        "context window",
    )
    return any(marker in text for marker in markers)


def _is_session_id_conflict(stderr: str) -> bool:
    """Claude CLI 拒绝了 ``--session-id``，因为该 UUID 已经存在。

    只有**新建**会话（``--session-id``）会报这个；``--resume`` 不会。所以命中它
    就等于：会话文件已经落盘，但我们的 ``session_state["started"]`` 还是 False
    ——上一次激活在 CLI 建完会话之后、wrapper 写回状态之前被整个杀掉了。
    """

    text = stderr.lower()
    return "session id" in text and "already in use" in text


def _transparent_resume_reason(stdout: str) -> str | None:
    """识别可在 wrapper 内直接恢复 Session 的 Claude 瞬态中断。"""

    runtime_result = _last_json_object(stdout) or {}
    if _is_context_overflow_result(runtime_result):
        return "context_overflow"
    terminal_reason = str(runtime_result.get("terminal_reason") or "")
    if runtime_result.get("is_error") and terminal_reason in {
        "api_error",
        "aborted_tools",
    }:
        return terminal_reason
    return None


def _cgroup_v2_root() -> Path | None:
    """定位当前进程所属的 cgroup v2 目录。

    /proc/self/cgroup 在 v2 下形如 ``0::/path``；控制文件位于
    /sys/fs/cgroup/<path>/。
    """

    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0] == "0":
                candidate = Path("/sys/fs/cgroup") / parts[2].lstrip("/")
                if (candidate / "memory.events").is_file():
                    return candidate
    except OSError:
        return None
    return None


def _read_cgroup_memory_evidence() -> dict[str, Any]:
    """读取 cgroup 内存事件计数，用于区分容器级 OOM 与其他外部终止。

    进程被信号终止时 wrapper 自身的 RSS 采样帮不上忙：Agent 只驱动 CLI，重负载
    在 evaluator 的独立进程里，实测峰值恒定在 0.3 GiB 左右而限额是 48 GiB。而
    cgroup 的 ``memory.events.oom_kill`` 直接给出内核 OOM killer 触发次数 ——
    这是唯一能证实"容器级 OOM"的证据。

    读不到时返回 ``{"available": False}``，不猜测原因。
    """

    root = _cgroup_v2_root()
    if root is None:
        return {"available": False, "reason": "cgroup v2 memory.events 不可读"}
    evidence: dict[str, Any] = {"available": True, "cgroup": str(root)}
    for name in ("memory.events", "memory.events.local"):
        try:
            text = (root / name).read_text(encoding="utf-8")
        except OSError:
            continue
        counters: dict[str, int] = {}
        for line in text.splitlines():
            fields = line.split()
            if len(fields) == 2:
                try:
                    counters[fields[0]] = int(fields[1])
                except ValueError:
                    continue
        if counters:
            evidence[name.replace(".", "_")] = counters
    for name in ("memory.peak", "memory.current", "memory.max"):
        try:
            raw = (root / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        evidence[name.replace(".", "_")] = (
            None if raw == "max" else (int(raw) if raw.isdigit() else raw)
        )
    return evidence


def _cgroup_oom_kills(evidence: Mapping[str, Any]) -> int | None:
    """从 cgroup 证据取内核 OOM kill 次数；无法判断时返回 None。"""

    if not evidence.get("available"):
        return None
    for key in ("memory_events_local", "memory_events"):
        counters = evidence.get(key)
        if isinstance(counters, Mapping) and "oom_kill" in counters:
            try:
                return int(counters["oom_kill"])
            except (TypeError, ValueError):
                continue
    return None


def _failure_details(
    *,
    returncode: int,
    timed_out: bool,
    submitted: bool,
    cancelled_by_controller: bool,
    result_valid: bool,
    result_error: str | None,
    stdout: str,
    stderr: str,
    memory_limit_exceeded: bool = False,
    memory_limit_bytes: int | None = None,
    observed_memory_bytes: int | None = None,
    require_submit: bool = True,
) -> dict[str, Any] | None:
    """把 CLI 退出状态转换为可路由、可写入 ExpBank 的失败诊断。"""

    if result_valid and (submitted or not require_submit):
        return None
    signal_evidence: dict[str, Any] | None = None
    signal_name = None
    if returncode < 0:
        try:
            signal_name = signal.Signals(-returncode).name
        except ValueError:
            signal_name = f"SIGNAL_{-returncode}"
    elif returncode >= 128:
        try:
            signal_name = signal.Signals(returncode - 128).name
        except ValueError:
            signal_name = None

    runtime_result = _last_json_object(stdout) or {}
    runtime_message = str(runtime_result.get("result") or "").strip()
    if cancelled_by_controller:
        error_code = "agent_cancelled_by_research_deadline"
        message = "研究墙钟已截止，Controller 终止了尚未提交的 Agent 激活。"
        suggested_action = "保留当前工作区；该版本标记为 not_executed，不形成方法失败结论。"
        retryable = False
    elif memory_limit_exceeded:
        error_code = "agent_memory_limit_exceeded"
        limit_gib = (memory_limit_bytes or 0) / 1024**3
        peak_gib = (observed_memory_bytes or 0) / 1024**3
        message = (
            "Agent 及其工具进程的主存占用超过单次激活上限："
            f"峰值至少 {peak_gib:.2f} GiB，上限 {limit_gib:.2f} GiB。"
        )
        suggested_action = (
            "恢复原 Session，使用分块读取、采样或轻量 Smoke Test；"
            "完整训练和正式运行交给 submit_candidate 后的 canonical run。"
        )
        retryable = True
    elif timed_out:
        error_code = "agent_timeout_before_submit"
        message = "Implement Agent 在单次调用 DDL 前没有提交 Candidate。"
        suggested_action = "缩短依赖安装、参数搜索和全量测试，优先提交可运行的最小版本。"
        retryable = True
    elif _is_session_id_conflict(stderr):
        error_code = "agent_session_in_use"
        message = stderr.strip() or "Agent Session 仍被另一个 CLI 进程占用。"
        suggested_action = "直接恢复同一 Session，不向 Agent 注入故障原因。"
        retryable = True
    elif _is_context_overflow_result(runtime_result):
        error_code = "agent_context_overflow"
        message = runtime_message or "Agent 请求超过模型上下文窗口。"
        suggested_action = (
            "恢复原 Session 时先执行一次 /compact，再继续当前任务；"
            "若仍超限，则切换新 Session 并仅传递压缩后的任务状态。"
        )
        retryable = True
    elif runtime_result.get("terminal_reason") == "api_error":
        error_code = "agent_api_error"
        message = runtime_message or "Agent CLI 报告 API 调用失败。"
        suggested_action = "保留 worktree，并直接恢复同一 Session。"
        retryable = True
    elif runtime_result.get("terminal_reason") == "aborted_tools":
        error_code = "agent_tools_aborted"
        message = runtime_message or "Agent CLI 的工具执行链意外中止。"
        suggested_action = "保留 worktree，并直接恢复同一 Session。"
        retryable = True
    elif runtime_result.get("is_error"):
        error_code = "agent_runtime_error"
        message = runtime_message or "Agent CLI 报告运行时错误。"
        suggested_action = "保留 worktree，并直接恢复同一 Session。"
        retryable = True
    elif returncode == 0 and not submitted and require_submit:
        error_code = "missing_explicit_submit"
        message = "Agent 正常退出，但没有调用 submit_candidate。"
        suggested_action = "恢复同一 Session，要求完成轻量检查后显式提交当前版本。"
        retryable = True
    elif returncode < 0 or signal_name is not None:
        # SIGKILL 与 SIGTERM 语义不同，必须分开：内核 OOM killer 只发 SIGKILL，
        # SIGTERM 是"有东西请求它退出"。合并成一个 error_code 会让两类完全不同的
        # 故障无法区分，也无法验证是否真是 OOM。
        cgroup_evidence = _read_cgroup_memory_evidence()
        oom_kills = _cgroup_oom_kills(cgroup_evidence)
        signal_evidence = {"cgroup": cgroup_evidence, "cgroup_oom_kills": oom_kills}
        if signal_name == "SIGKILL" and oom_kills:
            error_code = "agent_killed_by_cgroup_oom"
            message = (
                f"Agent 进程被 SIGKILL 终止，且 cgroup 记录了 {oom_kills} 次内核 "
                "OOM kill：本次终止来自容器级内存不足，而非进程自身超限。"
            )
            suggested_action = (
                "降低同容器内并发的 Implement/Evaluator 数量，或为该任务申请更大"
                "容器内存；不要按单进程内存上限去优化方案。"
            )
        elif signal_name == "SIGKILL":
            error_code = "agent_killed_sigkill"
            message = (
                "Agent 进程被 SIGKILL 终止，未形成提交。"
                + (
                    "cgroup 未记录内核 OOM kill，排除容器级内存不足。"
                    if oom_kills == 0
                    else "cgroup 证据不可读，无法判断是否容器级内存不足。"
                )
            )
            suggested_action = (
                "SIGKILL 无法被进程捕获，需从容器/节点侧排查（驱逐、外部 kill）；"
                "不要在缺证据时归因为 OOM。"
            )
        else:
            error_code = "agent_terminated_by_signal"
            message = (
                f"Agent 进程被 {signal_name or returncode} 终止，未形成提交。"
                "该信号不是内核 OOM killer 的行为（后者发 SIGKILL）。"
            )
            suggested_action = (
                "检查是否有外部编排、监督进程或容器运行时请求了退出；"
                "wrapper 自身的超时、心跳、内存与取消路径均会另置标志。"
            )
        retryable = True
    elif returncode != 0:
        error_code = "agent_process_failed"
        message = stderr.strip() or runtime_message or f"Agent CLI 以 rc={returncode} 退出。"
        suggested_action = "根据 stdout/stderr 修复运行时问题后恢复原 Session。"
        retryable = True
    else:
        error_code = "invalid_agent_result"
        message = result_error or "Agent 返回结果不符合协议。"
        suggested_action = "恢复同一 Session 并重新生成合法的结构化提交。"
        retryable = True

    return {
        "failure_stage": "agent_runtime",
        "error_code": error_code,
        "return_code": returncode,
        "signal": signal_name,
        "timed_out": timed_out,
        "submitted": submitted,
        "retryable": retryable,
        "result_error": result_error,
        "message": message,
        "suggested_action": suggested_action,
        "memory_limit_bytes": memory_limit_bytes,
        "observed_memory_bytes": observed_memory_bytes,
        # 仅在进程被信号终止时非空。observed_memory_bytes 只覆盖 Agent 自身进程组，
        # 无法反映容器级压力；cgroup 计数是判断容器 OOM 的唯一直接证据。
        "signal_evidence": signal_evidence,
        "stdout_tail": stdout[-3000:],
        "stderr_tail": stderr[-3000:],
        "evidence_refs": [],
    }


def build_implement_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "python submit_candidate.py",
) -> str:
    """构建发送给实现智能体的任务提示。"""
    metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    contract = (
        metadata.get("implementation_contract")
        if isinstance(metadata.get("implementation_contract"), dict)
        else {}
    )
    expected_entrypoint = str(contract.get("entrypoint") or "")
    if expected_entrypoint:
        submission_example = (
            f"{submit_candidate_command} \\\n"
            f"  --entrypoint {shlex.quote(expected_entrypoint)} \\\n"
            "  --title '本版本方法标题' \\\n"
            "  --summary '本版本核心修改和机制' \\\n"
            f"  --file {shlex.quote(expected_entrypoint)}"
        )
        entrypoint_guidance = (
            f"入口和源码路径必须相对 worktree。任务要求入口为 "
            f"`{expected_entrypoint}`；接口契约："
            f"{contract.get('entrypoint_interface') or '由 benchmark 题面定义'}。"
        )
    else:
        submission_example = (
            f"{submit_candidate_command} \\\n"
            "  --title '本版本方法标题' \\\n"
            "  --summary '本版本核心修改和机制' \\\n"
            "  --file 'relative/source/file'"
        )
        entrypoint_guidance = (
            "该任务未规定单一入口；请用一个或多个 `--file` 声明核心源码，"
            "具体执行和产物契约以 benchmark 公开题面为准。"
        )
    idea = request.get("idea") if isinstance(request.get("idea"), dict) else {}
    search_opportunity = (
        idea.get("search_opportunity")
        if isinstance(idea.get("search_opportunity"), dict)
        else {}
    )
    if search_opportunity:
        search_decision_guidance = (
            "- 本回合同时提供当前 Refine 与一条 New Idea，你必须选择 "
            "`refine`、`switch` 或 `fuse`。提交命令必须追加 "
            "`--search-action <选择> --search-reason '证据化理由'`；选择 refine "
            "后 New Idea 会重放到 IdeaSpark 队尾。\n"
            "- 先读 `search_opportunity.diagnostics` 与 "
            "`current_idea.last_run` 判断处境，再比较两个方案的上限：\n"
            "  · `last_run.termination_reason` 非 `completed`（OOM、超时、报错）"
            "说明当前方案还没跑出真实水平，先修复执行问题，通常应 `refine`；\n"
            "  · `current_is_run_best` 为 false 时，`run_best_attempt_id` 指向本 Run "
            "更好的方案；在明显落后的版本上继续 `refine` 收益有限，可考虑改从更优"
            "基线出发或 `switch`/`fuse`；\n"
            "  · `current_score` 已接近 `target_score` 时，优先受控 `refine`、"
            "校准或残差修正；若所有子指标都严重落后于目标，应 `switch` 或 `fuse`，"
            "不要把全部预算用于表面性的 `refine`；\n"
            "  · `worst_submetric` 指出拖累主指标的实例；主指标是各实例平均，"
            "改善最差实例通常杠杆最大。\n"
            "- `current_idea.last_run.paths` 给出本方案的产物目录：`code/` 是提交的实现、"
            "`output/` 是本次产物、`evidence/run.json` 是完整执行记录（含 stdout/stderr 全文）。"
            "需要定位失败原因或核对输出时，直接进这些目录查看。"
        )
    else:
        search_decision_guidance = (
            "- 本回合没有 Search Opportunity，不要传 `--search-action`。"
        )
    max_turns_line = (
        f"- 建议最多进行 {max_turns} 个自主推理/工具调用回合。\n"
        if max_turns
        else ""
    )
    prompt_version = os.environ.get("FAMOU_IMPLEMENT_PROMPT_VERSION", "v1").strip().lower()
    if prompt_version in {"v5", "5", "weights-v5"}:
        prompt_name = "cli_agents/implement_agent_v5.md"
    elif prompt_version in {"v4", "4", "rules-v4"}:
        prompt_name = "cli_agents/implement_agent_v4.md"
    elif prompt_version in {"v3", "3", "validity-v3"}:
        prompt_name = "cli_agents/implement_agent_v3.md"
    elif prompt_version in {"v2", "2", "algorithm-v2"}:
        prompt_name = "cli_agents/implement_agent_v2.md"
    else:
        prompt_name = "cli_agents/implement_agent.md"
    return render_prompt(
        prompt_name,
        worktree=worktree,
        worktree_result_path=worktree_result_path,
        output_path=output_path,
        max_turns_line=max_turns_line,
        submission_example=submission_example,
        entrypoint_guidance=entrypoint_guidance,
        search_decision_guidance=search_decision_guidance,
        submit_candidate_command=submit_candidate_command,
        instruction=instruction,
        request_json=json.dumps(
            request, ensure_ascii=False, indent=2, sort_keys=True
        ),
    )


def build_idea_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """构建发送给想法智能体的任务提示。"""
    max_turns_line = (
        f"- 建议最多进行 {max_turns} 个自主推理/工具调用回合。\n"
        if max_turns
        else ""
    )
    prompt_version = os.environ.get("FAMOU_IDEA_PROMPT_VERSION", "v1").strip().lower()
    if prompt_version in {"v9", "9", "ensemble-v9"}:
        prompt_name = "cli_agents/idea_agent_v9.md"
    elif prompt_version in {"v8", "8", "operator-v8"}:
        prompt_name = "cli_agents/idea_agent_v8.md"
    elif prompt_version in {"v7", "7", "rules-v7"}:
        prompt_name = "cli_agents/idea_agent_v7.md"
    elif prompt_version in {"v6", "6", "selftask-v6"}:
        prompt_name = "cli_agents/idea_agent_v6.md"
    elif prompt_version in {"v5", "5", "expbank-v5"}:
        prompt_name = "cli_agents/idea_agent_v5.md"
    elif prompt_version in {"v4", "4", "debate-v4"}:
        prompt_name = "cli_agents/idea_agent_v4.md"
    elif prompt_version in {"v3", "3", "validity-v3"}:
        prompt_name = "cli_agents/idea_agent_v3.md"
    elif prompt_version in {"v2", "2", "expbank-v2"}:
        prompt_name = "cli_agents/idea_agent_v2.md"
    else:
        prompt_name = "cli_agents/idea_agent.md"
    return render_prompt(
        prompt_name,
        worktree=worktree,
        worktree_result_path=worktree_result_path,
        output_path=output_path,
        max_turns_line=max_turns_line,
        instruction=instruction,
        request_json=json.dumps(
            request, ensure_ascii=False, indent=2, sort_keys=True
        ),
    )


def build_idea_rank_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """构建发送给 Idea 排序 Judge 的任务提示。"""

    del submit_candidate_command
    max_turns_line = (
        f"- 最多使用 {max_turns} 个自主推理/工具调用回合。\n"
        if max_turns
        else ""
    )
    return render_prompt(
        "cli_agents/idea_rank_judge.md",
        worktree=worktree,
        worktree_result_path=worktree_result_path,
        output_path=output_path,
        max_turns_line=max_turns_line,
        instruction=instruction,
        request_json=json.dumps(
            request, ensure_ascii=False, indent=2, sort_keys=True
        ),
    )


def build_idea_judge_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """构建发送给 Idea 批判 Judge 的任务提示。"""

    del submit_candidate_command
    max_turns_line = (
        f"- 最多使用 {max_turns} 个自主推理/工具调用回合。\n"
        if max_turns
        else ""
    )
    return render_prompt(
        "cli_agents/idea_judge.md",
        worktree=worktree,
        worktree_result_path=worktree_result_path,
        output_path=output_path,
        max_turns_line=max_turns_line,
        instruction=instruction,
        request_json=json.dumps(
            request, ensure_ascii=False, indent=2, sort_keys=True
        ),
    )


def _summary_metadata(request: Any) -> dict[str, Any]:
    """取出复盘 Agent 的取证上下文，兼容嵌套与扁平两种入参。

    生产调用是**嵌套**的：``agents/workers.py::summarize_experience`` 把 context
    放进 ``ImplementRequest.metadata``，wrapper 在 ``main()`` 里把整个 request 交给
    builder。而这里原本写的是 ``metadata = request``——全仓只有这一个 builder 这么
    写，其余四个（``:533``/``:801``/``:808``/``:818``）都取 ``request["metadata"]``。

    后果不是报错，是三个占位符**同时**静默兜底：``run_overview`` 变成 ``{}``、
    ``expbank_dir`` 退化成相对路径 ``expbank``、``attempt_index`` 变成「本 Run 没有
    attempt 记录」。复盘 Agent 于是在工作区里 ``ls expbank/`` 扑空，如实写下「证据
    全部缺失」，而这句话被当作一条正式经验存进库。实测 ``20260909`` 批次 105 份
    复盘里 90 份如此（其中一个 run 实际跑了 14 个 attempt、最佳分 0.1163、
    surpass_sota）；2026-08 缺失率 2%，2026-09 升到 32%。

    扁平入参要继续支持：``resummarize_run.py`` 和本目录的测试都直接传 context。
    """

    nested = request.get("metadata") if isinstance(request, dict) else None
    if isinstance(nested, dict) and nested:
        return nested
    return request if isinstance(request, dict) else {}


def build_experience_summary_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """构建发送给跨任务经验总结 Agent 的提示。

    这里刻意**不**内联完整请求。复盘 Agent 是带 Read/Grep/Glob 的 CLI Agent，
    ExpBank 已经作为只读目录挂进它的工作区，让它自己按需取证即可。此前把整个
    ``context``（含全部 attempt 的完整 record）``indent=2`` 灌进提示词正文，
    实测 286 KB ~ 1.16 MB，且同一份数据在 ``public/context.json`` 里已经有一份
    ——纯冗余，还在 2026-08 造成 24 次 ``Prompt is too long``，专挑 attempt 数
    最多、最值得复盘的 Run 打。
    """

    del submit_candidate_command
    max_turns_line = (
        f"- 最多使用 {max_turns} 个自主推理/工具调用回合。\n"
        if max_turns
        else ""
    )
    metadata = _summary_metadata(request)
    return render_prompt(
        "cli_agents/evolution_summarizer.md",
        worktree=worktree,
        worktree_result_path=worktree_result_path,
        output_path=output_path,
        max_turns_line=max_turns_line,
        instruction=instruction,
        run_overview=json.dumps(
            {
                key: metadata.get(key)
                for key in ("goal_name", "domain", "workflow_type", "research_state")
                if metadata.get(key) is not None
            },
            ensure_ascii=False,
        ),
        # 兜底串刻意写成不可执行的中文标记。原来这里兜的是相对路径 "expbank"，
        # 看着像个合法挂载点，Agent 会真的去 ls 它——而它的 cwd 是 worktree，
        # 必然扑空。静默降级成一条看似合理的错路径，正是这个故障活了一个月没被
        # 发现的原因：没有异常、没有日志，只有一份写着「证据缺失」的复盘。
        expbank_dir=str(metadata.get("expbank_dir") or "（未提供 expbank 路径）"),
        attempt_index=_render_attempt_index(metadata.get("attempt_index")),
    )


def _render_attempt_index(value: Any) -> str:
    """把 attempt 目录渲染成一行一条的表格，而不是嵌套 JSON。

    目录的用途是让 Agent 挑该打开哪几条（最好、最差、失败的），所以按可读性
    排版比结构完整更重要；完整字段在 ``record_path`` 指向的文件里。
    """

    rows = value if isinstance(value, list) else []
    if not rows:
        return "（本 Run 没有 attempt 记录）"
    lines = ["| attempt | 状态 | 正式分数 | 方案标题 | 完整记录 |", "|---|---|---:|---|---|"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = row.get("score")
        score_text = f"{score:.6f}" if isinstance(score, (int, float)) and not isinstance(score, bool) else "—"
        title = str(row.get("idea_title") or "").replace("|", "/")
        lines.append(
            f"| `{row.get('attempt_id')}` | {row.get('status')} | {score_text} "
            f"| {title[:90]} | `{row.get('record_path')}` |"
        )
    return "\n".join(lines)


def _terminal_phase(request: dict[str, Any], default: str) -> str:
    metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    return str(metadata.get("terminal_phase") or default).strip().lower()


def _terminal_evaluation_policy(request: dict[str, Any]) -> str:
    """Return the GT evaluation policy id carried in the Terminal Solver context."""

    metadata = request.get("metadata")
    context = metadata.get("terminal_context") if isinstance(metadata, dict) else None
    if isinstance(context, dict) and context.get("evaluation_policy"):
        return str(context["evaluation_policy"]).strip().lower()
    return ""


def _terminal_evaluation_policy_note(request: dict[str, Any]) -> str:
    """Return the explicit evaluation budget note for Terminal Solver prompts."""

    metadata = request.get("metadata")
    context = metadata.get("terminal_context") if isinstance(metadata, dict) else None
    if isinstance(context, dict) and context.get("evaluation_policy_note"):
        return str(context["evaluation_policy_note"])
    return "按公开任务上下文工作；系统将在需要时提供评测反馈。"


def build_scimodeling_researcher_prompt(
    *, request, instruction, output_path, worktree_result_path, worktree,
    max_turns, submit_candidate_command="",
) -> str:
    """Expose only the limited-GT action protocol and current public budget."""
    del output_path, max_turns, submit_candidate_command
    context = (request.get("metadata") or {}).get("terminal_context") or {}
    return (f"{instruction}\n\nWorktree: {worktree}\n"
            f"Action file: {worktree_result_path}\n\nPublic context:\n"
            + json.dumps(context, ensure_ascii=False, indent=2))


def build_terminal_solver_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """构建 TerminalTask Solver 的 solve/refine 提示。"""

    del output_path, worktree_result_path, submit_candidate_command
    phase = _terminal_phase(request, "solve")
    # 提示词只新增版本、不原地改。v2 仅放宽“不生成结果 JSON”这一条，以便
    # gt_budget 模式的 Solver 能按评测策略写入官方 GT 申请文件；其余模式仍用 v1。
    suffix = "v2" if _terminal_evaluation_policy(request) == "on_request_budget" else "v1"
    template = (
        f"cli_agents/terminal_task/solver_refine_{suffix}.md"
        if phase == "refine"
        else f"cli_agents/terminal_task/solver_solve_{suffix}.md"
    )
    return render_prompt(
        template,
        worktree=worktree,
        max_turns=str(max_turns or "由运行时预算限制"),
        instruction=instruction,
        evaluation_policy_note=_terminal_evaluation_policy_note(request),
        request_json=json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True),
    )


def build_terminal_verifier_prompt(
    *,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """构建 TerminalTask Verifier 的 compiler/diagnose 提示。"""

    del output_path, submit_candidate_command
    phase = _terminal_phase(request, "compile_plan")
    verifier_prompt_version = os.environ.get(
        "FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION", "v1"
    ).strip().lower()
    if verifier_prompt_version in {"v0", "0", "legacy"}:
        suffix = "v0"
    elif verifier_prompt_version in {"v2", "2", "quality-v2"}:
        suffix = "v2"
    else:
        # v1 is retained as the compatibility default for existing runs. Unknown values fail closed
        # to the current default so a typo cannot silently select the legacy contract.
        suffix = "v1"
    if phase == "diagnose":
        template = f"cli_agents/terminal_task/verifier_diagnose_{suffix}.md"
    elif phase == "repair_compile":
        template = f"cli_agents/terminal_task/verifier_repair_compile_{suffix}.md"
    else:
        template = f"cli_agents/terminal_task/verifier_compile_{suffix}.md"
    shared_instruction = (
        load_prompt(f"cli_agents/terminal_task/verifier_instruction_{suffix}.md")
        if suffix in {"v1", "v2"}
        else ""
    )
    return render_prompt(
        template,
        worktree=worktree,
        worktree_result_path=worktree_result_path,
        max_turns=str(max_turns or "由运行时预算限制"),
        instruction=instruction,
        verifier_instruction=shared_instruction,
        request_json=json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True),
    )


def build_prompt(
    *,
    role: str,
    request: dict[str, Any],
    instruction: str,
    output_path: Path,
    worktree_result_path: Path,
    worktree: Path,
    max_turns: str | None,
    submit_candidate_command: str = "",
) -> str:
    """按照节点角色构建智能体提示。"""
    builders = {
        "idea": build_idea_prompt,
        "idea_rank": build_idea_rank_prompt,
        "idea_judge": build_idea_judge_prompt,
        "experience_summary": build_experience_summary_prompt,
        "implement": build_implement_prompt,
        "terminal_solver": build_terminal_solver_prompt,
        "scimodeling_researcher": build_scimodeling_researcher_prompt,
        "terminal_verifier": build_terminal_verifier_prompt,
    }
    builder = builders[role]
    return builder(
        request=request,
        instruction=instruction,
        output_path=output_path,
        worktree_result_path=worktree_result_path,
        worktree=worktree,
        max_turns=max_turns,
        submit_candidate_command=submit_candidate_command,
    )


def _read_submission(path: Path) -> dict[str, Any] | None:
    """读取已经原子发布的 Candidate 提交事件。"""

    if not path.is_file():
        return None
    try:
        event = _load_json(path)
    except Exception:
        return None
    if not event.get("submission_id"):
        return None
    return event


def _stop_process_group(
    proc: subprocess.Popen[Any],
    *,
    force_after_sec: float = 5.0,
) -> int:
    """终止已完成提交但仍未自行退出的 Agent 进程组。"""

    if proc.poll() is not None:
        return int(proc.returncode or 0)
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:  # pragma: no cover - Windows 回退
            proc.terminate()
        return proc.wait(timeout=max(0.1, force_after_sec))
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows 回退
            proc.kill()
        return proc.wait(timeout=10)


def _process_group_rss_bytes(process_group_id: int) -> int:
    """汇总 Agent 进程组 RSS，覆盖其 Bash、Python 等工具子进程。"""

    page_size = os.sysconf("SC_PAGE_SIZE")
    total = 0
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if os.getpgid(pid) != process_group_id:
                continue
            fields = Path(entry.path, "statm").read_text(encoding="utf-8").split()
            if len(fields) >= 2:
                total += int(fields[1]) * page_size
        except (OSError, ValueError):
            # 采样期间进程可能恰好退出。
            continue
    return total


def _wait_for_agent_event(
    proc: subprocess.Popen[Any],
    *,
    timeout_sec: float | None,
    submission_path: Path | None,
    submission_grace_sec: float,
    cancel_file: Path | None = None,
    heartbeat_after_sec: float | None = None,
    memory_limit_bytes: int | None = None,
    memory_state: dict[str, Any] | None = None,
) -> tuple[int, bool, dict[str, Any] | None, bool, bool, bool]:
    """等待 Agent，并区分提交、取消、超时和 DDL 心跳事件。"""

    started = time.monotonic()
    # ``0`` 表示预算已经耗尽，不能按 falsy 值误判为“不设超时”。这在 DDL
    # 心跳结束首个激活、恢复同一 Session 时尤其重要。
    deadline = started + timeout_sec if timeout_sec is not None else None
    heartbeat_at = (
        started + heartbeat_after_sec
        if heartbeat_after_sec is not None
        else None
    )
    submission: dict[str, Any] | None = None
    submitted_at: float | None = None
    if memory_state is not None:
        memory_state.update({"peak_bytes": 0, "exceeded": False})
    while True:
        # 先读事件再检查退出码：快速 Agent 可能在两次轮询之间完成提交并自然退出，
        # 不能因为先观察到进程结束而漏掉已经原子落盘的 Candidate。
        if submission is None and submission_path is not None:
            submission = _read_submission(submission_path)
            if submission is not None:
                submitted_at = time.monotonic()
        returncode = proc.poll()
        if returncode is not None:
            return returncode, False, submission, False, False, False
        if memory_limit_bytes is not None:
            usage = _process_group_rss_bytes(proc.pid)
            if memory_state is not None:
                memory_state["peak_bytes"] = max(
                    int(memory_state.get("peak_bytes") or 0),
                    usage,
                )
            if usage > memory_limit_bytes:
                if memory_state is not None:
                    memory_state["exceeded"] = True
                # 只结束本次 Agent 激活。外层 Controller、其他 Actor 和可信
                # Evaluator 不在该进程组中，因而不会被单个探索命令拖垮。
                returncode = _stop_process_group(proc, force_after_sec=1.0)
                return returncode, False, submission, False, False, False
        if cancel_file is not None and cancel_file.is_file():
            # 研究截止与单次 Agent timeout 是不同语义：前者不形成工程失败，
            # 上层会把对应队列项记为 not_executed，并继续排空正式评测。
            returncode = _stop_process_group(proc, force_after_sec=1.0)
            return returncode, False, submission, submission is not None, True, False
        if submitted_at is not None and (
            time.monotonic() - submitted_at >= max(0.0, submission_grace_sec)
        ):
            returncode = _stop_process_group(proc)
            return returncode, False, submission, True, False, False

        if (
            submission is None
            and heartbeat_at is not None
            and time.monotonic() >= heartbeat_at
        ):
            # 非交互 CLI 无法在运行中可靠接收新消息。结束本次激活后恢复同一
            # Session，才能把 DDL 提醒作为真正的用户消息注入给 Agent。
            returncode = _stop_process_group(proc, force_after_sec=1.0)
            return returncode, False, submission, False, False, True

        if deadline is not None and time.monotonic() >= deadline:
            if submission is not None:
                returncode = _stop_process_group(proc, force_after_sec=1.0)
                return returncode, False, submission, True, False, False
            returncode = _stop_process_group(proc, force_after_sec=1.0)
            return returncode, True, submission, False, False, False
        time.sleep(0.2)


def _wait_for_agent(
    proc: subprocess.Popen[Any],
    *,
    timeout_sec: float | None,
    submission_path: Path | None,
    submission_grace_sec: float,
    cancel_file: Path | None = None,
) -> tuple[int, bool, dict[str, Any] | None, bool, bool]:
    """兼容旧调用：等待 Agent，但不触发 DDL 心跳。"""

    result = _wait_for_agent_event(
        proc,
        timeout_sec=timeout_sec,
        submission_path=submission_path,
        submission_grace_sec=submission_grace_sec,
        cancel_file=cancel_file,
    )
    return result[:5]


# Linux 对单个 exec 参数的上限是 MAX_ARG_STRLEN = 32 页 = 128 KiB（含结尾 NUL），
# 与 ARG_MAX（参数总量，通常 2 MiB）是两回事。提示词随 mailbox 与 ExpBank 证据
# 累积增长，越过该上限时 execve 直接以 E2BIG 失败，表现为 CLI 瞬间 rc=1、零 token、
# stdout/stderr 皆空——实测已导致多次 attempt 报废。留 8 KiB 余量后改走 stdin。
MAX_SINGLE_ARG_BYTES = 128 * 1024
PROMPT_ARG_SAFE_BYTES = MAX_SINGLE_ARG_BYTES - 8 * 1024

# 已验证可从 stdin 读取提示词的运行时。其余运行时把提示词作为选项值传入，
# 没有等价的 stdin 协议，超限时只能显式报错而不是让 execve 抛出晦涩的 E2BIG。
STDIN_PROMPT_RUNTIMES = frozenset({"claude"})


def prompt_needs_stdin(runtime: str, prompt: str) -> bool:
    """判断该提示词是否必须改走 stdin 才能启动。

    未超限时返回 False，保持既有 argv 交付路径不变。
    """

    if len(prompt.encode("utf-8")) <= PROMPT_ARG_SAFE_BYTES:
        return False
    if runtime not in STDIN_PROMPT_RUNTIMES:
        raise ValueError(
            f"提示词 {len(prompt.encode('utf-8'))} 字节超过单参数上限 "
            f"{MAX_SINGLE_ARG_BYTES} 字节，而运行时 {runtime!r} 不支持从 stdin "
            "读取提示词；请缩减注入证据或改用支持 stdin 的运行时。"
        )
    return True


def _spawn_stdin_writer(stream: Any, payload: str) -> threading.Thread:
    """在后台把提示词写入子进程 stdin 并关闭。

    子进程读完 stdin 才会开始工作，而提示词远超管道缓冲区，同步写会死锁在
    主流程的轮询之前。写失败只可能是子进程已退出，此时错误由退出码承载。
    """

    def _write() -> None:
        try:
            stream.write(payload)
            stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    thread = threading.Thread(target=_write, name="agent-stdin-writer", daemon=True)
    thread.start()
    return thread


def build_cli_argv(
    args: argparse.Namespace,
    prompt: str,
    last_message_path: Path,
    *,
    resume_session: bool = False,
    session_id: str | None = None,
    prompt_via_stdin: bool = False,
) -> list[str]:
    """构建首次启动或恢复命令行智能体的参数列表。

    prompt_via_stdin 为真时不把提示词写进 argv，由调用方通过 stdin 交付。
    见 PROMPT_ARG_SAFE_BYTES 的说明。
    """
    runtime = args.runtime
    binary = args.binary or runtime
    extra_args = list(args.extra_arg or [])

    if runtime == "opencode":
        argv = [
            binary,
            "run",
            "--dir",
            str(args.worktree),
            "--title",
            args.title,
        ]
        if resume_session:
            # 每个 ImplementActor 使用稳定 worktree；在该目录中继续最近会话即可
            # 恢复同一 Agent 的对话上下文。
            argv.append("--continue")
        if args.model:
            argv.extend(["--model", args.model])
        if args.agent:
            argv.extend(["--agent", args.agent])
        if args.auto_approve:
            argv.append("--auto")
        argv.extend(extra_args)
        argv.append(prompt)
        return argv

    if runtime == "codex":
        argv = [binary]
        if args.auto_approve:
            # 部分命令行工具版本只接受放在子命令前的审批和沙箱选项；这里保持兼容。
            argv.extend(["--sandbox", "workspace-write"])
            argv.extend(["--ask-for-approval", "never"])
        else:
            argv.extend(["--sandbox", "workspace-write"])
            argv.extend(["--ask-for-approval", "on-request"])
        if resume_session:
            argv.extend(["exec", "resume"])
            # 首回合从 JSONL 保存真实 thread_id，后续按 ID 精确恢复。--last 仅用于
            # 兼容早期没有记录 ID 的 Actor workspace。
            argv.append(session_id or "--last")
            argv.extend(
                [
                    "--skip-git-repo-check",
                    "--json",
                    "--output-last-message",
                    str(last_message_path),
                ]
            )
        else:
            argv.extend(
                [
                    "exec",
                    "--cd",
                    str(args.worktree),
                    "--skip-git-repo-check",
                    "--json",
                    "--output-last-message",
                    str(last_message_path),
                ]
            )
        if args.model:
            argv.extend(["--model", args.model])
        if args.profile:
            argv.extend(["--profile", args.profile])
        argv.extend(extra_args)
        argv.append(prompt)
        return argv

    if runtime == "claude":
        argv = [
            binary,
            "--bare",
            "--print",
            "--output-format",
            "json",
            "--add-dir",
            str(args.worktree),
        ]
        if resume_session:
            if not session_id:
                raise ValueError("Claude session 恢复需要 session_id")
            argv.extend(["--resume", session_id])
        elif session_id:
            # 首次启动时由 Controller 指定 UUID，后续无需从自然语言输出解析会话号。
            argv.extend(["--session-id", session_id])
        if args.auto_approve:
            # 非交互自主模式不能因权限输入而停住；真实安全边界由外层工作空间和沙箱负责。
            # 可用工具参数必须使用等号形式，避免吞掉最后的提示词参数。
            argv.extend(["--permission-mode", "dontAsk"])
            # Idea 节点只产出方案，不应启动训练或长时间数据处理；执行权限只属于实现节点。
            allowed_tools = (
                "Read,Edit"
                if args.role
                in {"idea", "idea_rank", "idea_judge", "experience_summary"}
                else "Read,Write,Edit,Bash"
            )
            # 联网工具默认关闭：NatureBench 明确禁止联网，一旦授予就可能让
            # Agent 检索到论文原文或官方结果，使成绩不可采信。需要联网的
            # benchmark 显式传 --allow-network-tools 开启。
            # 用 getattr 兜底：缺失该属性时按"不联网"处理，让默认永远是安全的一侧。
            if getattr(args, "allow_network_tools", False):
                allowed_tools += ",WebSearch,WebFetch"
            argv.append(f"--allowedTools={allowed_tools}")
        if args.model:
            argv.extend(["--model", args.model])
        if args.agent:
            argv.extend(["--agent", args.agent])
        argv.extend(extra_args)
        if not prompt_via_stdin:
            # 提示词超过单参数上限时留空，由调用方写入 stdin；claude --print
            # 在没有位置参数时从 stdin 读取提示词。
            argv.append(prompt)
        return argv

    if runtime == "kimi-code":
        # Kimi Code 0.29 uses --prompt for non-interactive input and stream-json
        # for machine-readable output.
        argv = [binary, "--output-format", "stream-json"]
        if resume_session:
            if session_id:
                argv.extend(["--session", session_id])
            else:
                argv.append("--continue")
        if args.model:
            argv.extend(["--model", args.model])
        argv.extend(extra_args)
        argv.extend(["--prompt", prompt])
        return argv

    if runtime == "z-code":
        # Baidu Comate Zulu uses query/display flags rather than Kimi's prompt
        # protocol. event-stream keeps tool and text events machine-readable.
        argv = [binary, "run", "--cwd", str(args.worktree), "--display", "event-stream"]
        if resume_session:
            if session_id:
                argv.extend(["--conversation", session_id])
            else:
                argv.append("--continue")
        if args.model:
            argv.extend(["--model", args.model])
        argv.extend(extra_args)
        argv.extend(["--query", prompt])
        return argv

    raise ValueError(f"unsupported runtime: {runtime!r}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        required=True,
        choices=["opencode", "codex", "claude", "kimi-code", "z-code"],
    )
    parser.add_argument("--binary", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--outputs-dir", required=True)
    parser.add_argument("--title", default="famou-loop-implement")
    parser.add_argument(
        "--role",
        choices=[
            "idea",
            "idea_rank",
            "idea_judge",
            "experience_summary",
            "implement",
            "terminal_solver",
            "scimodeling_researcher",
            "terminal_verifier",
        ],
        default="implement",
    )
    parser.add_argument("--session-key")
    parser.add_argument(
        "--completion-mode",
        choices=["structured_result", "natural_exit"],
        default="structured_result",
    )
    parser.add_argument("--model")
    parser.add_argument("--agent")
    parser.add_argument("--profile")
    parser.add_argument("--max-turns")
    parser.add_argument("--timeout-sec", type=float)
    parser.add_argument(
        "--memory-limit-bytes",
        type=int,
        help="单次 Agent 激活及其工具子进程允许使用的最大 RSS",
    )
    parser.add_argument("--submission-grace-sec", type=float, default=20.0)
    parser.add_argument(
        "--deadline-heartbeat-after-sec",
        type=float,
        help="运行达到该秒数时恢复同一 Session，并注入一次剩余提交时间提醒",
    )
    parser.add_argument(
        "--compact-on-context-overflow",
        dest="compact_on_context_overflow",
        action="store_true",
        help="Claude 上下文超限后，恢复同一 Session 前先执行一次 /compact",
    )
    parser.add_argument(
        "--no-compact-on-context-overflow",
        dest="compact_on_context_overflow",
        action="store_false",
        help="关闭上下文超限后的自动 /compact 恢复",
    )
    parser.add_argument(
        "--cancel-file",
        help="该文件出现时终止当前 Agent；用于研究截止后的有序收尾",
    )
    parser.add_argument(
        "--require-submit-candidate",
        action="store_true",
        help="要求 Implement Agent 必须调用显式 Candidate 提交命令",
    )
    parser.add_argument("--extra-arg", action="append", default=[])
    parser.add_argument(
        "--allow-network-tools",
        action="store_true",
        help=(
            "授予 WebSearch/WebFetch。默认关闭：NatureBench 禁止联网，"
            "联网会让成绩不可采信。仅供允许联网的 benchmark 显式开启。"
        ),
    )
    parser.add_argument("--auto-approve", dest="auto_approve", action="store_true")
    parser.add_argument("--no-auto-approve", dest="auto_approve", action="store_false")
    parser.set_defaults(auto_approve=True, compact_on_context_overflow=True)
    args = parser.parse_args(argv)
    if args.memory_limit_bytes is not None and args.memory_limit_bytes <= 0:
        parser.error("--memory-limit-bytes 必须大于 0")
    return args


def main(argv: list[str] | None = None) -> int:
    """执行命令行主入口。"""
    args = parse_args(list(argv or sys.argv[1:]))
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    instruction_path = Path(args.instruction).resolve()
    worktree = Path(args.worktree).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    outputs_dir = Path(args.outputs_dir).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # ImplementActor 用 Session 延续同一 Candidate；开放科研 IdeaActor 则用 Session
    # 复用前期调研和 Idea 图谱上下文。benchmark-managed 每次使用不同工作区，因此
    # 即便启用 Session 也不会在不同并发生产者之间串线。
    session_enabled = True
    session_key = str(args.session_key or args.role)
    if not session_key or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in session_key):
        parser_error = f"invalid session key: {session_key!r}"
        raise ValueError(parser_error)
    session_state_path = logs_dir / f"{args.runtime}_{session_key}_session.json"
    session_state: dict[str, Any] = {}
    if session_enabled and session_state_path.exists():
        try:
            session_state = _load_json(session_state_path)
        except Exception:
            session_state = {}
    if session_enabled and not session_state:
        session_state = {
            "runtime": args.runtime,
            "session_id": str(uuid.uuid4()) if args.runtime == "claude" else None,
            "started": False,
            "resume_count": 0,
            "created_at": int(time.time() * 1000),
        }
        _write_json(session_state_path, session_state)
    resume_session = bool(session_state.get("started")) if session_enabled else False

    request = _load_json(input_path)
    instruction = _read_text(instruction_path)
    result_filenames = {
        "idea": "famou_idea_result.json",
        "idea_rank": "famou_idea_rank_result.json",
        "idea_judge": "famou_idea_judge_result.json",
        # 复盘只有 Markdown 一种形态；结构化 JSON 那条路径已随
        # transferable_experiences 一起移除。
        "experience_summary": "EVOLUTION.md",
        "implement": "famou_agent_result.json",
        "terminal_solver": "famou_terminal_solver_result.json",
        "scimodeling_researcher": "famou_scimodeling_result.json",
        "terminal_verifier": "famou_terminal_verifier_result.json",
    }
    result_filename = result_filenames[args.role]
    worktree_result_path = worktree / result_filename
    if worktree_result_path.exists():
        # 两类长生命周期 Actor 都会复用 worktree。每次唤醒前移除上一回合的
        # 结构化返回值，避免本回合未提交时误把旧 JSON 当作新结果。
        worktree_result_path.unlink()
    if args.role in {"idea", "idea_rank", "idea_judge", "terminal_verifier"}:
        # Claude Code 的只读角色没有 Write 工具；预创建后可仅开放 Edit。
        _write_text(worktree_result_path, "{}\n")
    elif args.role == "experience_summary":
        _write_text(worktree_result_path, "# Evolution Summary\n\n")
    # 每次激活使用独立提交事件。结果 JSON 可以被 Agent 多次编辑，但只有该事件
    # 原子出现后，wrapper 才认为 Candidate 已正式提交并允许当前 Actor park。
    call_label = output_path.stem.replace("/", "_").replace("\\", "_")
    submission_path = outputs_dir / f"{call_label}.candidate_submission.json"
    submission_path.unlink(missing_ok=True)
    submit_script = Path(__file__).with_name("submit_candidate.py").resolve()
    submit_candidate_command = shlex.join([sys.executable, str(submit_script)])
    prompt = build_prompt(
        role=args.role,
        request=request,
        instruction=instruction,
        output_path=output_path,
        worktree_result_path=worktree_result_path,
        worktree=worktree,
        max_turns=args.max_turns,
        submit_candidate_command=submit_candidate_command,
    )
    # manager output 文件名含本次 call_id；沿用它给日志编号，避免同一 Session
    # 多次恢复时覆盖上一回合的 Prompt、stdout、stderr 和 wrapper 元数据。
    prompt_path = logs_dir / f"{call_label}.{args.runtime}_{args.role}_prompt.md"
    last_message_path = outputs_dir / f"{call_label}.{args.runtime}_last_message.txt"
    meta_path = logs_dir / f"{call_label}.{args.runtime}_wrapper_meta.json"
    _write_text(prompt_path, prompt)

    stdout_path = outputs_dir / f"{call_label}.{args.runtime}_stdout.txt"
    stderr_path = outputs_dir / f"{call_label}.{args.runtime}_stderr.txt"
    started = time.monotonic()
    absolute_deadline = (
        started + args.timeout_sec if args.timeout_sec is not None else None
    )
    timed_out = False
    child_started = False
    submission: dict[str, Any] | None = None
    parked_after_submission = False
    cancelled_by_controller = False
    memory_limit_exceeded = False
    observed_memory_bytes = 0
    heartbeat_events: list[dict[str, Any]] = []
    transparent_resume_events: list[dict[str, Any]] = []
    context_compaction_events: list[dict[str, Any]] = []
    activation_commands: list[list[str]] = []
    returncode = -1
    proc: subprocess.Popen[Any] | None = None
    goal_context = request.get("goal") if isinstance(request.get("goal"), dict) else {}
    infra_context = (
        goal_context.get("infra")
        if isinstance(goal_context.get("infra"), dict)
        else {}
    )
    resource_envelope = (
        infra_context.get("resources")
        if isinstance(infra_context.get("resources"), dict)
        else {}
    )
    idea_context = request.get("idea") if isinstance(request.get("idea"), dict) else {}
    idea_resource_request = (
        idea_context.get("resource_request")
        if isinstance(idea_context.get("resource_request"), dict)
        else {}
    )
    runtime_environment = _runtime_environment(args)
    native_trajectory_roots = _native_trajectory_roots(args, runtime_environment)
    # 在启动任何 CLI 进程前保存文件偏移。后续 Resume 只导出本次新增事件，
    # 不会把长生命周期 Session 的历史 Token/轨迹重复记到当前激活。
    native_trajectory_cursors = snapshot_jsonl_files(native_trajectory_roots)
    child_env = {
        **runtime_environment,
        "FAMOU_AGENT_ROLE": args.role,
        "FAMOU_IMPLEMENT_AGENT_INPUT": str(input_path),
        "FAMOU_IMPLEMENT_AGENT_OUTPUT": str(output_path),
        "FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT": str(worktree_result_path),
        "FAMOU_IMPLEMENT_AGENT_WORKTREE": str(worktree),
        "FAMOU_IMPLEMENT_AGENT_PROMPT": str(prompt_path),
        "FAMOU_SUBMISSION_PATH": str(submission_path),
        "FAMOU_SUBMIT_CANDIDATE": str(submit_script),
        "FAMOU_EXPECTED_ENTRYPOINT": str(
            (
                (request.get("metadata") or {}).get("implementation_contract")
                or {}
            ).get("entrypoint")
            or ""
        ),
        "FAMOU_RESOURCE_ENVELOPE_JSON": json.dumps(
            resource_envelope,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "FAMOU_IDEA_RESOURCE_REQUEST_JSON": json.dumps(
            idea_resource_request,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "FAMOU_RESOURCE_DECLARATIONS_REQUIRED": (
            "1"
            if resource_envelope.get("resource_declarations_required")
            else "0"
        ),
        "FAMOU_SEARCH_OPPORTUNITY_JSON": json.dumps(
            idea_context.get("search_opportunity")
            if isinstance(idea_context.get("search_opportunity"), dict)
            else {},
            ensure_ascii=False,
            sort_keys=True,
        ),
    }
    try:
        activation_prompt = prompt
        activation_resume = resume_session
        activation_index = 0
        heartbeat_done = False
        transparent_resume_done = False
        session_conflict_recovered = False
        context_compaction_requested = bool(
            args.runtime == "claude"
            and args.compact_on_context_overflow
            and session_state.get("context_compact_pending")
        )
        context_compaction_done = False
        activation_kind = (
            "context_compact"
            if context_compaction_requested and resume_session
            else "agent"
        )
        if activation_kind == "context_compact":
            activation_prompt = "/compact"
        heartbeat_deadline = (
            started + args.deadline_heartbeat_after_sec
            if args.role == "implement"
            and args.deadline_heartbeat_after_sec is not None
            else None
        )
        # 最多包含首次激活、一次上下文 compact、一次透明恢复和一次 DDL 心跳恢复。
        while activation_index < 5:
            session_id = (
                str(session_state.get("session_id"))
                if session_state.get("session_id")
                else None
            )
            if activation_kind == "context_compact":
                activation_prompt = "/compact"
            via_stdin = prompt_needs_stdin(args.runtime, activation_prompt)
            cli_argv = build_cli_argv(
                args,
                activation_prompt,
                last_message_path,
                resume_session=activation_resume,
                session_id=session_id,
                prompt_via_stdin=via_stdin,
            )
            activation_commands.append(
                cli_argv + ["<prompt:stdin>"]
                if via_stdin
                else cli_argv[:-1] + ["<prompt>"]
            )
            remaining_timeout = (
                max(0.0, absolute_deadline - time.monotonic())
                if absolute_deadline is not None
                else None
            )
            heartbeat_after = (
                max(0.0, heartbeat_deadline - time.monotonic())
                if heartbeat_deadline is not None and not heartbeat_done
                else None
            )
            mode = "a" if activation_index else "w"
            activation_memory: dict[str, Any] = {}
            with stdout_path.open(mode, encoding="utf-8") as stdout_file, stderr_path.open(
                mode,
                encoding="utf-8",
            ) as stderr_file:
                if activation_index:
                    stdout_file.write("\n")
                    stderr_file.write("\n")
                proc = subprocess.Popen(
                    cli_argv,
                    cwd=str(worktree),
                    env=child_env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    stdin=subprocess.PIPE if via_stdin else subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                )
                child_started = True
                if via_stdin and proc.stdin is not None:
                    # 提示词远大于管道缓冲区，必须在后台写入：主流程随后要轮询
                    # 进程与提交事件，不能阻塞在 write 上。
                    _spawn_stdin_writer(proc.stdin, activation_prompt)
                (
                    returncode,
                    timed_out,
                    submission,
                    parked_after_submission,
                    cancelled_by_controller,
                    heartbeat_triggered,
                ) = _wait_for_agent_event(
                    proc,
                    timeout_sec=remaining_timeout,
                    submission_path=(
                        submission_path if args.role == "implement" else None
                    ),
                    submission_grace_sec=args.submission_grace_sec,
                    cancel_file=(
                        Path(args.cancel_file).expanduser().resolve()
                        if args.cancel_file
                        else None
                    ),
                    heartbeat_after_sec=heartbeat_after,
                    memory_limit_bytes=args.memory_limit_bytes,
                    memory_state=activation_memory,
                )
            observed_memory_bytes = max(
                observed_memory_bytes,
                int(activation_memory.get("peak_bytes") or 0),
            )
            memory_limit_exceeded = bool(
                memory_limit_exceeded or activation_memory.get("exceeded")
            )

            current_stdout = (
                stdout_path.read_text(encoding="utf-8")
                if stdout_path.exists()
                else ""
            )
            native_session_id = _extract_session_id(current_stdout, args.runtime)
            if native_session_id:
                session_state["session_id"] = native_session_id
            current_stderr = (
                stderr_path.read_text(encoding="utf-8")
                if stderr_path.exists()
                else ""
            )
            if (
                args.runtime == "claude"
                and not activation_resume
                and not session_conflict_recovered
                and returncode != 0
                and _is_session_id_conflict(current_stderr)
            ):
                # 会话已经存在，只是我们的状态文件没记上——上一次激活在 CLI 建完
                # 会话之后、`started` 写回之前被整个杀掉了（4h 墙钟下 pod 被外部
                # kill 是常态）。CLI 直接拒绝启动，**提示词一个字都没送到**，所以
                # 这里带着原提示词改走 `--resume`，而不是发"继续当前任务。"。
                #
                # 线上代价：s42256-023-00640-6 #0009、s42256-023-00712-7 #0008
                # 两次 attempt 整个作废。原来的处理只是把它标成 retryable 的
                # `agent_session_in_use` 交回调度器——但重试会读到同一个状态文件、
                # 再次走 `--session-id`，于是必然复现同一个错误。
                session_conflict_recovered = True
                session_state["started"] = True
                session_state["updated_at"] = int(time.time() * 1000)
                _write_json(session_state_path, session_state)
                transparent_resume_events.append(
                    {
                        "event": "session_id_conflict_resume",
                        "terminal_reason": "session_id_already_in_use",
                        "triggered_at": int(time.time() * 1000),
                        "previous_returncode": returncode,
                        "session_id": session_state.get("session_id"),
                    }
                )
                activation_resume = True
                activation_kind = "agent"
                activation_prompt = prompt
                activation_index += 1
                continue
            if activation_kind == "context_compact":
                context_compaction_done = returncode == 0 and not timed_out
                if context_compaction_done:
                    session_state.pop("context_compact_pending", None)
                session_state["started"] = True
                session_state["updated_at"] = int(time.time() * 1000)
                _write_json(session_state_path, session_state)
                context_compaction_events.append(
                    {
                        "event": "context_compaction",
                        "status": (
                            "succeeded"
                            if returncode == 0 and not timed_out
                            else "failed"
                        ),
                        "triggered_at": int(time.time() * 1000),
                        "returncode": returncode,
                        "session_id": session_state.get("session_id"),
                    }
                )
                # Compact is an internal recovery turn. Regardless of whether
                # the CLI accepted the slash command, give the normal resume
                # one chance; it will produce the durable failure if the
                # session remains unusable.
                activation_kind = "agent"
                activation_prompt = "继续当前任务。"
                activation_resume = True
                activation_index += 1
                continue
            if heartbeat_triggered:
                heartbeat_done = True
                session_state["started"] = True
                session_state["updated_at"] = int(time.time() * 1000)
                _write_json(session_state_path, session_state)
                remaining_sec = (
                    max(0, int(absolute_deadline - time.monotonic()))
                    if absolute_deadline is not None
                    else None
                )
                heartbeat_event = {
                    "event": "implement_deadline_heartbeat",
                    "triggered_at": int(time.time() * 1000),
                    "elapsed_sec": round(time.monotonic() - started, 3),
                    "remaining_sec": remaining_sec,
                    "previous_returncode": returncode,
                    "session_id": session_state.get("session_id"),
                }
                heartbeat_events.append(heartbeat_event)
                heartbeat_path = logs_dir / f"{call_label}.deadline_heartbeat.json"
                _write_json(heartbeat_path, heartbeat_event)
                activation_prompt = (
                    "[Famou DDL heartbeat]\n"
                    f"当前 Implement 激活只剩约 {remaining_sec} 秒。立即停止依赖安装、"
                    "参数搜索和完整 benchmark；基于现有 worktree 完成最小可运行版本，"
                    "只做轻量 Smoke Test，然后调用 submit_candidate。不要等待正式评测。"
                )
                heartbeat_prompt_path = (
                    logs_dir / f"{call_label}.deadline_heartbeat_prompt.md"
                )
                _write_text(heartbeat_prompt_path, activation_prompt)
                activation_resume = True
                activation_kind = "agent"
                activation_index += 1
                continue

            transient_reason = (
                _transparent_resume_reason(current_stdout)
                if args.runtime == "claude"
                and not transparent_resume_done
                and submission is None
                and not timed_out
                and not memory_limit_exceeded
                and not cancelled_by_controller
                and returncode != 0
                else None
            )
            if transient_reason:
                # API/工具链突发对 Agent 完全透明：不经过失败队列，不解释原因，
                # 直接用同一 Session 和 worktree 继续当前任务。
                transparent_resume_done = True
                session_state["started"] = True
                session_state["updated_at"] = int(time.time() * 1000)
                _write_json(session_state_path, session_state)
                transparent_resume_events.append(
                    {
                        "event": "transparent_session_resume",
                        "terminal_reason": transient_reason,
                        "triggered_at": int(time.time() * 1000),
                        "previous_returncode": returncode,
                        "session_id": session_state.get("session_id"),
                    }
                )
                if (
                    transient_reason == "context_overflow"
                    and args.compact_on_context_overflow
                    and not context_compaction_requested
                ):
                    context_compaction_requested = True
                    session_state["context_compact_pending"] = True
                    session_state["started"] = True
                    session_state["updated_at"] = int(time.time() * 1000)
                    _write_json(session_state_path, session_state)
                    activation_kind = "context_compact"
                    activation_prompt = "/compact"
                else:
                    activation_kind = "agent"
                    activation_prompt = "继续当前任务。"
                activation_resume = True
                activation_index += 1
                continue
            break
    except subprocess.TimeoutExpired:  # pragma: no cover - 最终强杀失败保护
        timed_out = True
        returncode = -1
    except BaseException:
        # 轮询控制文件或解析提交事件也可能失败。无论 wrapper 自身在哪里报错，
        # 都必须回收已启动的 CLI 进程组，避免调度器重试时累积孤儿 Agent。
        if proc is not None and proc.poll() is None:
            _stop_process_group(proc, force_after_sec=1.0)
        raise
    stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
    stderr = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""

    # 复盘只有 Markdown 一种形态（结构化 JSON 那条路径已随 transferable_experiences
    # 一起移除），所以这里不再判 summary_format——那个变量随之删掉了，但这行的引用
    # 漏了下来，于是 09-07 之后**每个 run 的复盘都以 NameError 收场**，经验库从此
    # 不再增长（09-07 两个 verify run 的 outbox 里 evolution_markdown 都是 0 字符）。
    if args.role == "experience_summary":
        markdown = worktree_result_path.read_text(encoding="utf-8").strip()
        if markdown and markdown != "# Evolution Summary":
            _write_json(output_path, {"evolution_markdown": markdown})
    elif not output_path.exists() and worktree_result_path.exists():
        try:
            _write_json(output_path, _load_json(worktree_result_path))
        except Exception:
            # 保留后续校验错误作为标准失败原因。
            pass

    if not output_path.exists():
        fallback = _extract_last_json_object(stdout)
        if fallback is not None:
            _write_json(output_path, fallback)

    if args.completion_mode == "natural_exit" and not output_path.exists():
        _write_json(
            output_path,
            {
                "status": "completed" if returncode == 0 else "failed",
                "returncode": returncode,
                "last_message_path": str(last_message_path),
            },
        )

    result_valid = False
    result_error = None
    if output_path.exists():
        try:
            result = _load_json(output_path)
            result_valid = isinstance(result, dict)
        except Exception as exc:  # noqa: BLE001
            result_error = repr(exc)
    else:
        result_error = "missing result JSON"

    submitted = submission is not None
    if args.role == "implement" and args.require_submit_candidate and not submitted:
        result_valid = False
        result_error = "missing explicit submit_candidate event"

    native_session_id = _extract_session_id(stdout, args.runtime)
    session_available = child_started and (
        returncode == 0
        or timed_out
        or cancelled_by_controller
        or memory_limit_exceeded
        or result_valid
        or native_session_id is not None
        or bool(heartbeat_events)
        or (args.runtime == "claude" and bool(session_state.get("session_id")))
    )
    if session_enabled and session_available:
        # Agent 在同一个会话中可能因为代码或结果协议错误返回非零；这种情况下会话
        # 仍然包含有价值的上下文，修复回合应继续恢复它，而不是重新开始。
        session_state["started"] = True
        if native_session_id:
            session_state["session_id"] = native_session_id
        session_state["resume_count"] = int(
            session_state.get("resume_count") or 0
        ) + int(resume_session) + len(heartbeat_events) + len(transparent_resume_events) + len(
            context_compaction_events
        )
        session_state["updated_at"] = int(time.time() * 1000)
        _write_json(session_state_path, session_state)

    call_id = call_label.removesuffix(".result")
    normalized_trajectory_path = (
        outputs_dir / f"{call_label}.{args.runtime}_agent_trajectory.jsonl"
    )
    trajectory = export_incremental_trajectory(
        output_path=normalized_trajectory_path,
        roots=native_trajectory_roots,
        cursors=native_trajectory_cursors,
        call_id=call_id,
        role=args.role,
        runtime=args.runtime,
        session_id=(
            str(session_state.get("session_id"))
            if session_state.get("session_id")
            else None
        ),
        stdout=stdout,
    )
    telemetry = normalize_cli_telemetry(
        runtime=args.runtime,
        stdout=stdout,
        model=args.model,
    )
    if telemetry.get("reported_total_tokens") is None:
        # submit_candidate 后主动 park 或异常中断时，CLI 可能来不及打印最终 result。
        # 原生 Session 已经落下逐轮 usage，此时只解析游标后的增量轨迹。
        trajectory_telemetry = normalize_trajectory_telemetry(
            normalized_trajectory_path,
            model=args.model,
        )
        if trajectory_telemetry.get("reported_total_tokens") is not None:
            provider_cost = telemetry.get("cost")
            telemetry.update(trajectory_telemetry)
            if isinstance(provider_cost, dict) and provider_cost.get("amount") is not None:
                telemetry["cost"] = provider_cost
    telemetry.update(
        {
            "adapter": "cli",
            "runtime": args.runtime,
            "role": args.role,
            "status": (
                "succeeded"
                if result_valid and not timed_out and not memory_limit_exceeded
                else "cancelled"
                if cancelled_by_controller
                else "failed"
            ),
            "started_at_ms": int(time.time() * 1000)
            - int((time.monotonic() - started) * 1000),
            "finished_at_ms": int(time.time() * 1000),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "returncode": returncode,
            "resumed": resume_session,
            "trajectory": trajectory,
        }
    )

    meta = {
        "call_id": call_id,
        "role": args.role,
        "model": args.model,
        "runtime": args.runtime,
        "binary": args.binary,
        "command": activation_commands[-1] if activation_commands else [],
        "activation_commands": activation_commands,
        "prompt_path": str(prompt_path),
        "last_message_path": str(last_message_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "returncode": returncode,
        "timed_out": timed_out,
        "submitted": submitted,
        "submission": submission,
        "submission_path": str(submission_path),
        "parked_after_submission": parked_after_submission,
        "cancelled_by_controller": cancelled_by_controller,
        "memory": {
            "limit_bytes": args.memory_limit_bytes,
            "observed_peak_bytes": observed_memory_bytes,
            "limit_exceeded": memory_limit_exceeded,
        },
        "deadline_heartbeat": {
            "enabled": args.deadline_heartbeat_after_sec is not None,
            "trigger_after_sec": args.deadline_heartbeat_after_sec,
            "events": heartbeat_events,
        },
        "transparent_session_resume": {
            "events": transparent_resume_events,
        },
        "context_compaction": {
            "enabled": bool(
                args.runtime == "claude" and args.compact_on_context_overflow
            ),
            "requested": context_compaction_requested,
            "completed": context_compaction_done,
            "events": context_compaction_events,
        },
        "duration_ms": int((time.monotonic() - started) * 1000),
        "telemetry": telemetry,
        "result_path": str(output_path),
        "worktree_result_path": str(worktree_result_path),
        "result_valid": result_valid,
        "result_error": result_error,
        "session": {
            **session_state,
            "state_path": str(session_state_path),
            "resumed_this_call": resume_session,
        }
        if session_enabled
        else None,
    }
    failure = _failure_details(
        returncode=returncode,
        timed_out=timed_out,
        submitted=submitted,
        cancelled_by_controller=cancelled_by_controller,
        result_valid=result_valid,
        result_error=result_error,
        stdout=stdout,
        stderr=stderr,
        memory_limit_exceeded=memory_limit_exceeded,
        memory_limit_bytes=args.memory_limit_bytes,
        observed_memory_bytes=observed_memory_bytes,
        require_submit=bool(args.require_submit_candidate),
    )
    if failure is not None:
        failure["evidence_refs"] = [
            str(prompt_path),
            str(stdout_path),
            str(stderr_path),
            str(meta_path),
        ]
        meta["failure"] = failure
    _write_json(meta_path, meta)

    # 输出紧凑证据，供实现智能体调用日志捕获。
    print(json.dumps(meta, ensure_ascii=False, sort_keys=True))
    if stderr:
        print(stderr, file=sys.stderr)
    # 显式提交后 wrapper 可能主动终止仍在生成自然语言总结的 CLI 进程。此时
    # Candidate 结果已经原子落盘，负 returncode 是 park 行为而不是实现失败。
    if timed_out or not result_valid or (returncode != 0 and not submitted):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
