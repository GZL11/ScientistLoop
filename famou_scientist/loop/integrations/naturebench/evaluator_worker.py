"""以 root 可信进程消费固定路径 NatureBench 评测请求。"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping

from ...utils import append_jsonl, atomic_write_json, now_ms
from ..evaluator_logs import write_agent_log_copy
from .benchmark import _safe_public_data, _safe_scalar_metrics


_NATUREBENCH_EVALUATE_PUBLIC_FIELDS = (
    "task_name",
    "attempt",
    "raw_scores",
    "normalized_raw_scores",
    "per_instance_improvement",
    "aggregate_improvement",
    "score_normalization",
    "best_aggregate_improvement",
    "best_attempt",
)


def _validate_trusted_evidence_dir(
    trusted_evidence_dir: Path,
    agent_log_dir: Path | None = None,
    *,
    run_dir: Path | None,
) -> None:
    """确认可信证据位于 Agent 运行树外或受权限保护的 trusted/ 内。"""
    if run_dir is None:
        return
    try:
        relative = trusted_evidence_dir.relative_to(run_dir)
    except ValueError:
        # 独立部署的 Evaluator 可以把证据保存在 Agent 挂载树之外。
        return
    if not relative.parts or relative.parts[0] != "trusted":
        raise ValueError(
            "trusted evaluator evidence inside the run directory must be below trusted/"
        )
    trusted_root = run_dir / "trusted"
    if not trusted_root.is_dir():
        raise FileNotFoundError(f"trusted run directory not found: {trusted_root}")
    mode = trusted_root.stat().st_mode & 0o777
    if mode & 0o077:
        raise PermissionError(
            "trusted run directory must not grant group/other permissions: "
            f"{trusted_root} mode={mode:o}"
        )


def _load_last_json_object(stdout: str, *, required_key: str) -> dict[str, Any]:
    """从子进程标准输出尾部读取包含指定字段的 JSON 对象。"""
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and required_key in value:
            return value
    raise ValueError(
        f"NatureBench subprocess produced no JSON object with {required_key!r}"
    )


def _load_trusted_settings(path: Path | None) -> None:
    """从 Agent 不可见的可信副本加载独立 Judge API 配置。"""
    if path is None:
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("env") if isinstance(raw, dict) else None
    if not isinstance(values, dict):
        raise ValueError(f"trusted judge settings contains no env mapping: {path}")
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key.startswith(("JUDGE_", "ANTHROPIC_")):
            os.environ[key] = value
    # Claude CLI 常用 ANTHROPIC_AUTH_TOKEN，而 NatureBench 官方 Judge
    # 只读取 API_KEY 命名。该兼容别名仅存在于 Trusted Evaluator 进程中。
    #
    # judge_core 按模型名分流 provider：Anthropic 分支读 JUDGE_ANTHROPIC_API_KEY，
    # OpenAI 分支（gpt-5.5 等）只读 JUDGE_OPENAI_API_KEY / JUDGE_API_KEY。此前只
    # 补了 Anthropic 一侧，导致 JUDGE_MODEL=gpt-5.5 时判定必然以
    # "judge_error: no API key" 失败——is_valid 写成 null，既让提交包错判，也让
    # 跨任务经验因 agent_visible=False 无法回流。两侧都要补齐。
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if auth_token:
        if not any(
            os.environ.get(key)
            for key in (
                "JUDGE_ANTHROPIC_API_KEY",
                "JUDGE_API_KEY",
                "ANTHROPIC_API_KEY",
            )
        ):
            os.environ["JUDGE_ANTHROPIC_API_KEY"] = auth_token
        if not any(
            os.environ.get(key)
            for key in ("JUDGE_OPENAI_API_KEY", "JUDGE_API_KEY")
        ):
            os.environ["JUDGE_OPENAI_API_KEY"] = auth_token
    # 网关同时服务两类模型，但 OpenAI 分支不会回落到 ANTHROPIC_BASE_URL；
    # 缺省时 judge 会打到官方 api.openai.com 而非本部署网关。
    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL")
    if anthropic_base and not any(
        os.environ.get(key)
        for key in ("JUDGE_OPENAI_BASE_URL", "JUDGE_BASE_URL")
    ):
        os.environ["JUDGE_OPENAI_BASE_URL"] = anthropic_base.rstrip("/") + "/v1"


def _judge_provider_for_model(model: str | None) -> str:
    """按模型名判定 judge_core 会走哪条 provider 分支。

    与 judge_core.clients._provider_for_model 保持一致：非 claude 前缀走 OpenAI。
    """

    name = (model or "").strip().lower()
    if not name or name.startswith("claude"):
        return "anthropic"
    return "openai"


def _assert_judge_credentials(model: str | None) -> None:
    """启动即校验 Judge 凭据，不把配置错误留到判定时才发现。

    历史问题：缺 key 时判定仍"成功"返回 is_valid=null，运行照常结束，直到
    事后翻 judge_verdict.json 才发现整批都没判。这类错误必须在 Run 开始前
    就失败，而不是产出一份看起来完整、实则未判定的结果。
    """

    provider = _judge_provider_for_model(model)
    if provider == "openai":
        names = ("JUDGE_OPENAI_API_KEY", "JUDGE_API_KEY")
    else:
        names = ("JUDGE_ANTHROPIC_API_KEY", "JUDGE_API_KEY", "ANTHROPIC_API_KEY")
    if any(os.environ.get(name) for name in names):
        return
    raise RuntimeError(
        f"Judge 模型 {model!r} 走 {provider} 分支，但 {' / '.join(names)} 均未设置。"
        " Judge 会以 is_valid=null 结束且不影响 Run 退出码，因此这里提前失败："
        " 请在 trusted judge settings 或环境变量中提供凭据。"
    )


def _atomic_write_text(path: Path, text: str) -> None:
    """以原子替换方式写入可信文本证据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _sign(path: Path, signature_path: Path, private_key: Path) -> None:
    """使用可信进程私钥签署脱敏公共响应文件。"""
    temporary = signature_path.with_suffix(signature_path.suffix + f".tmp.{os.getpid()}")
    process = subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(temporary),
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            "failed to sign evaluator response: "
            + (process.stderr or process.stdout or "unknown openssl error").strip()
        )
    temporary.replace(signature_path)


# NatureBench 官方为全部 90 道题声明了**独立的评测环境** `naturebench-eval`
# （见 NatureBench 仓库根的 `eval_env_mapping.json` 与 `conda_env_eval.yml`：
# numpy 2.3.1 / pandas 2.3.2 / rdkit 2025.03.2 / meeko 0.5.1）。而 Agent 任务镜像
# 的 `/opt/py311` 被 torch cu118 的 `numpy<2.0` 反向锁死在 numpy 1.26 / pandas 2.2，
# 两者不可能共存于同一个解释器。
#
# 之前我们用同一个解释器同时跑 Agent 和评测器，后果是**评测器读不了官方 GT**：
#   - s43588-025-00878-7：GT 是 pandas≥2.3 写的 pickle，2.2.3 反序列化时
#     `StringDtype.__init__()` 签名对不上，被 `pandas/compat/pickle_compat.py`
#     掩成 `issubclass() arg 1 must be a class`，14/14 次 attempt 全军覆没；
#   - s42256-023-00712-7：镜像里的 meeko 0.6.0 不带 `meeko/data/params/`，
#     `MoleculePreparation()` 抛 ValueError，被 evaluator 的 `except Exception:
#     return None` 吞掉，每个分子 Vina Score 都是 null → aggregate 直接 −1。
# 两道题与模型能力无关，任何 Agent 都不可能通过。
#
# 因此评测器改走独立解释器。这个路径会经 `sys.executable` 一路传给
# `eval_service.run_evaluator`（它也用 `sys.executable` 拉起 `_evaluator_runner.py`），
# 所以只要在最外层换掉解释器，整条评测链就都落在评测环境里。
# 适配器 `evaluate_task.py` 本身只用标准库，换解释器不会引入新依赖。
_EVAL_PYTHON_ENV = "NATUREBENCH_EVAL_PYTHON"
_EVAL_PYTHON_DEFAULT = Path("/opt/pyeval/bin/python")


def _resolve_eval_python() -> str:
    """挑选跑官方评测器的解释器。

    优先级：显式环境变量 > 镜像里的 `/opt/pyeval` > 当前解释器。
    **回退到当前解释器是有意为之**——老镜像里没有 `/opt/pyeval`，此时行为与
    改动前完全一致，不会因为镜像没更新就把评测打挂。
    """

    override = os.environ.get(_EVAL_PYTHON_ENV, "").strip()
    if override:
        return override
    if _EVAL_PYTHON_DEFAULT.is_file() and os.access(_EVAL_PYTHON_DEFAULT, os.X_OK):
        return str(_EVAL_PYTHON_DEFAULT)
    return sys.executable


def _evaluate(
    *,
    adapter_script: Path,
    task_dir: Path,
    output_dir: Path,
    timeout_sec: float,
) -> tuple[dict[str, Any], str, str, int]:
    """调用当前 Famou 版本的 NatureBench 官方评分薄适配器。"""
    try:
        process = subprocess.run(
            [
                _resolve_eval_python(),
                str(adapter_script),
                "--task-dir",
                str(task_dir),
                "--submission-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return (
            {
                "valid": False,
                "official_metrics": {"aggregate_improvement": None},
                "diagnostics_public": {
                    "evaluation_completed": False,
                    "score_available": False,
                },
                "extra": {},
                "error_public": "NatureBench evaluator timed out",
                "error": f"evaluation timed out after {timeout_sec} seconds",
            },
            stdout,
            stderr,
            124,
        )
    try:
        result = _load_last_json_object(process.stdout, required_key="valid")
    except Exception as exc:  # noqa: BLE001 - 适配器错误需要形成签名响应
        result = {
            "valid": False,
            "official_metrics": {"aggregate_improvement": None},
            "diagnostics_public": {},
            "extra": {},
            "error": repr(exc),
        }
    return result, process.stdout, process.stderr, process.returncode


_RETRYABLE_JUDGE_ERROR = re.compile(
    r"""
    HTTP\s+(?:429|5\d\d)        # 网关/上游错误，含实测的 HTTP 502
    | \b(?:429|500|502|503|504)\b
    | too\s+many\s+requests
    | rate\s*limit
    | \btimeout\b | timed\s+out
    | connection\s+(?:reset|refused|error|aborted)
    | temporarily\s+unavailable
    | bad\s+gateway | service\s+unavailable
    | remote\s+end\s+closed
    | \bEOF\s+occurred\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# 每次尝试之间的退避秒数。判定跑在可信评测进程里，整个 Run 只判一次，
# 因此宁可多等几十秒也不要让一次网关抖动废掉 4 小时的运行结果。
_JUDGE_RETRY_BACKOFF_SEC = (5.0, 20.0, 60.0)


def _is_retryable_judge_error(verdict: Mapping[str, Any]) -> bool:
    """判定失败是否属于「重试可能成功」的一类。

    只有 ``is_valid`` 不是布尔值才算失败——明确的 True/False 是有效结论，
    绝不能重判（那会退化成挑一个更宽松的判官）。

    实测背景：容器内 judge 打网关时会间歇性拿到 ``HTTP 502``，同一天里成功与
    502 混着出现（2026-09-06 本批 25 次里 15 次 502）。此前没有重试，一次抖动
    就把 ``is_valid`` 永久写成 ``null``，导致该 Run 既被提交包排除、又因
    ``judge_verdict = None`` 进不了跨任务经验目录，只能事后手工补判——
    从 08-27 到 09-07 积压了 35 个。
    """

    if isinstance(verdict.get("is_valid"), bool):
        return False
    reason = str(verdict.get("reason") or "")
    return bool(_RETRYABLE_JUDGE_ERROR.search(reason))


def _judge(
    *,
    judge_script: Path | None,
    task_dir: Path,
    run_dir: Path,
    best_attempt_id: str,
    request_id: str,
    agent_runtime: str,
    model: str | None,
    timeout_sec: float,
    submissions_path: Path,
    submission_map_path: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], str, str, int]:
    """调用 NatureBench 官方 post-hoc Judge 的 Famou 证据适配器。

    网关抖动类失败会退避重试；每次尝试都记进 verdict 的 ``judge_attempts``，
    否则事后无法区分「一次就成」和「重试后才成」，也看不出抖动有多频繁
    （这次就是靠比对按日成败分布才判断出 502 是间歇而非端点配错）。
    """

    argv = [sys.executable]
    if judge_script is None:
        # 默认入口必须按模块运行，确保包内相对导入在独立子进程中有效。
        argv.extend(
            ["-m", "famou_scientist.loop.integrations.naturebench.judge_adapter"]
        )
    else:
        # 测试和外部 benchmark patch 仍可显式传入自定义 Judge 脚本。
        argv.append(str(judge_script))
    argv.extend(
        [
            "--task-dir",
            str(task_dir),
            "--run-dir",
            str(run_dir),
            "--best-attempt-id",
            best_attempt_id,
            "--request-id",
            request_id,
            "--agent-runtime",
            agent_runtime,
            "--submissions-path",
            str(submissions_path),
            "--submission-map-path",
            str(submission_map_path),
        ]
    )
    if model:
        argv.extend(["--model", model])

    attempts: list[dict[str, Any]] = []
    verdict: dict[str, Any] = {}
    stdout = stderr = ""
    returncode = 0
    for index in range(len(_JUDGE_RETRY_BACKOFF_SEC) + 1):
        process = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        stdout, stderr, returncode = process.stdout, process.stderr, process.returncode
        try:
            verdict = _load_last_json_object(stdout, required_key="is_valid")
        except Exception as exc:  # noqa: BLE001 - Judge 失败也必须形成签名响应
            verdict = {
                "is_valid": None,
                "reason": f"judge_error: {exc}",
                "model": model,
                "expbank_attempt_id": best_attempt_id,
            }
        attempts.append(
            {
                "attempt": index + 1,
                "is_valid": verdict.get("is_valid"),
                "reason": verdict.get("reason"),
                "returncode": returncode,
            }
        )
        if not _is_retryable_judge_error(verdict) or index >= len(
            _JUDGE_RETRY_BACKOFF_SEC
        ):
            break
        sleep(_JUDGE_RETRY_BACKOFF_SEC[index])

    if len(attempts) > 1:
        # 只在真重试过时才写，避免给绝大多数一次成功的判定增加噪声字段。
        verdict = {**verdict, "judge_attempts": attempts}
    return verdict, stdout, stderr, returncode


def _raw_response_for(
    *,
    request: dict[str, Any],
    adapter_result: dict[str, Any],
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, Any]:
    """构造完整评测响应，供可信目录留存而不直接发布给 Agent。"""
    official_metrics = adapter_result.get("official_metrics")
    metrics = dict(official_metrics) if isinstance(official_metrics, dict) else {}
    extra = adapter_result.get("extra")
    declared_public = adapter_result.get("extra_public")
    public_response = (
        {
            key: declared_public.get(key)
            for key in _NATUREBENCH_EVALUATE_PUBLIC_FIELDS
            if key in declared_public
        }
        if isinstance(declared_public, dict)
        else {}
    )
    return {
        "request_id": request["request_id"],
        "kind": "evaluate",
        "attempt_id": request.get("attempt_id"),
        "valid": bool(adapter_result.get("valid")),
        "metrics": metrics,
        "official_metrics": metrics,
        "diagnostics_public": adapter_result.get("diagnostics_public") or {},
        "stdout": stdout,
        "stderr": stderr,
        "extra": {
            "adapter_extra": extra if isinstance(extra, dict) else {},
            "adapter_extra_public": public_response,
            "adapter_returncode": returncode,
        },
        "extra_public": public_response,
        "stdout_public": adapter_result.get("stdout_public"),
        "stderr_public": adapter_result.get("stderr_public"),
        "error_public": adapter_result.get("error_public"),
        "error": adapter_result.get("error"),
        "evaluated_at": now_ms(),
    }


def _attach_evaluation_session_state(
    adapter_result: dict[str, Any],
    *,
    task_name: str,
    session: dict[str, Any],
) -> dict[str, Any]:
    """补齐 NatureBench /evaluate 的 attempt 与历史最佳字段。"""

    result = dict(adapter_result)
    public = dict(result.get("extra_public") or {})
    session["attempt"] = int(session.get("attempt") or 0) + 1
    attempt = session["attempt"]
    metrics = result.get("official_metrics")
    aggregate = (
        metrics.get("aggregate_improvement")
        if isinstance(metrics, dict)
        else None
    )
    if (
        result.get("valid") is True
        and isinstance(aggregate, (int, float))
        and not isinstance(aggregate, bool)
        and math.isfinite(float(aggregate))
    ):
        current_best = session.get("best_aggregate_improvement")
        if current_best is None or float(aggregate) > float(current_best):
            session["best_aggregate_improvement"] = float(aggregate)
            session["best_attempt"] = attempt
    public.update(
        {
            "task_name": str(public.get("task_name") or task_name),
            "attempt": attempt,
            "aggregate_improvement": aggregate,
            "best_aggregate_improvement": session.get(
                "best_aggregate_improvement"
            ),
            "best_attempt": session.get("best_attempt"),
        }
    )
    result["extra_public"] = public
    return result


def _load_evaluation_session(submissions_path: Path) -> dict[str, Any]:
    """从官方格式历史恢复 evaluator attempt 和最佳分数，支持 Job 重启。"""

    session: dict[str, Any] = {
        "attempt": 0,
        "best_aggregate_improvement": None,
        "best_attempt": None,
    }
    if not submissions_path.is_file():
        return session
    for line in submissions_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        attempt = record.get("attempt")
        if isinstance(attempt, int) and not isinstance(attempt, bool):
            session["attempt"] = max(int(session["attempt"]), attempt)
        aggregate = record.get("aggregate_improvement")
        if (
            record.get("valid") is True
            and isinstance(aggregate, (int, float))
            and not isinstance(aggregate, bool)
            and math.isfinite(float(aggregate))
            and (
                session["best_aggregate_improvement"] is None
                or float(aggregate)
                > float(session["best_aggregate_improvement"])
            )
        ):
            session["best_aggregate_improvement"] = float(aggregate)
            session["best_attempt"] = attempt
    return session


def _append_native_submission(
    *,
    submissions_path: Path,
    submission_map_path: Path,
    request: dict[str, Any],
    response: dict[str, Any],
) -> None:
    """按 NatureBench Evaluation Service schema 留存成功或失败提交。"""

    public = response.get("extra_public")
    public = dict(public) if isinstance(public, dict) else {}
    private = response.get("extra")
    private = dict(private) if isinstance(private, dict) else {}
    adapter_extra = private.get("adapter_extra")
    adapter_extra = (
        dict(adapter_extra) if isinstance(adapter_extra, dict) else {}
    )
    attempt = public.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        raise ValueError("NatureBench evaluator response contains no valid attempt")
    evaluated_at = response.get("evaluated_at")
    timestamp = (
        float(evaluated_at) / 1000.0
        if isinstance(evaluated_at, (int, float))
        and not isinstance(evaluated_at, bool)
        else time.time()
    )
    diagnostics = response.get("diagnostics_public")
    evaluation_completed = (
        response.get("valid") is True
        or (
            isinstance(diagnostics, dict)
            and diagnostics.get("evaluation_completed") is True
        )
    )
    if evaluation_completed:
        record = {
            "type": "success",
            "valid": response.get("valid") is True,
            "attempt": attempt,
            "timestamp": timestamp,
            "raw_scores": adapter_extra.get("raw_scores") or {},
            "per_instance_improvement": adapter_extra.get(
                "per_instance_improvement"
            )
            or {},
            "aggregate_improvement": response.get("official_metrics", {}).get(
                "aggregate_improvement"
            ),
            "primary_instance_failures": (
                public.get("primary_instance_failures") or []
            ),
        }
    else:
        record = {
            "type": "failure",
            "attempt": attempt,
            "timestamp": timestamp,
            "raw_scores": None,
            "per_instance_improvement": None,
            "aggregate_improvement": None,
            "error": str(response.get("error") or "evaluation failed"),
            "traceback": str(response.get("stderr") or ""),
        }
    append_jsonl(submissions_path, record)
    append_jsonl(
        submission_map_path,
        {
            "request_id": request.get("request_id"),
            "candidate_id": request.get("attempt_id"),
            "attempt": attempt,
            "timestamp": timestamp,
        },
    )


def _public_response_for(raw_response: dict[str, Any]) -> dict[str, Any]:
    """从完整评测响应生成可写入 Agent 工作目录的白名单响应。"""
    official_metrics = raw_response.get("official_metrics")
    safe_metrics = _safe_scalar_metrics(official_metrics)
    public_extra = raw_response.get("extra_public")
    if not isinstance(public_extra, dict):
        public_extra = {}
    valid = raw_response.get("valid") is True
    # stdout_public/stderr_public 必须由可信适配器显式提供，绝不从原始输出回退。
    stdout_public = raw_response.get("stdout_public")
    stderr_public = raw_response.get("stderr_public")
    return {
        "request_id": raw_response.get("request_id"),
        "kind": raw_response.get("kind") or "evaluate",
        "attempt_id": raw_response.get("attempt_id"),
        "valid": valid,
        "metrics": safe_metrics,
        "official_metrics": safe_metrics,
        "diagnostics_public": _safe_scalar_metrics(
            raw_response.get("diagnostics_public")
        ),
        "stdout": stdout_public if isinstance(stdout_public, str) else "",
        "stderr": stderr_public if isinstance(stderr_public, str) else "",
        "extra": _safe_public_data(public_extra),
        "error": (
            str(raw_response.get("error_public"))
            if raw_response.get("error_public")
            else None
            if valid
            else "trusted evaluator returned an invalid result"
        ),
        "redacted_for_agent": True,
        "raw_evidence": {
            "available": True,
            "visibility": "trusted_only",
        },
        "evaluated_at": raw_response.get("evaluated_at") or now_ms(),
    }


def _judge_response_for(
    *,
    request: dict[str, Any],
    verdict: dict[str, Any],
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, Any]:
    """把官方 Judge verdict 转换为带审计信息的统一签名响应。"""
    completed = type(verdict.get("is_valid")) is bool
    return {
        "request_id": request["request_id"],
        "kind": "validity_judge",
        "attempt_id": request.get("attempt_id"),
        "valid": completed,
        "judge": verdict,
        "metrics": {},
        "diagnostics_public": {
            "judge_completed": completed,
            "score_attempt": verdict.get("score_attempt"),
        },
        "stdout": stdout,
        "stderr": stderr,
        "extra": {"judge_returncode": returncode},
        "error": None if completed else verdict.get("reason"),
        "evaluated_at": now_ms(),
    }


def _public_judge_response_for(raw_response: dict[str, Any]) -> dict[str, Any]:
    """生成 Agent 可见的 Judge 响应，隐藏原始进程输出。"""
    verdict = raw_response.get("judge")
    public_verdict: dict[str, Any] = {}
    if isinstance(verdict, dict):
        # Judge 的结论字段是收尾协议；其他模型调试字段仍属于可信证据。
        for key in ("is_valid", "reason", "model", "score_attempt", "expbank_attempt_id"):
            value = verdict.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                public_verdict[key] = value
    return {
        "request_id": raw_response.get("request_id"),
        "kind": "validity_judge",
        "attempt_id": raw_response.get("attempt_id"),
        "valid": raw_response.get("valid") is True,
        "judge": public_verdict,
        "metrics": {},
        "diagnostics_public": _safe_scalar_metrics(
            raw_response.get("diagnostics_public")
        ),
        "stdout": "",
        "stderr": "",
        "extra": {"judge_completed": bool(raw_response.get("valid"))},
        "error": raw_response.get("error"),
        "redacted_for_agent": True,
        "raw_evidence": {
            "available": True,
            "visibility": "trusted_only",
        },
        "evaluated_at": raw_response.get("evaluated_at") or now_ms(),
    }


def _persist_trusted_evidence(
    trusted_evidence_dir: Path,
    *,
    request: dict[str, Any],
    response: dict[str, Any],
    stdout: str,
    stderr: str,
) -> Path:
    """将一次评测的完整证据写入 Agent 不可见的可信目录。"""
    request_id = str(request["request_id"])
    if Path(request_id).name != request_id or request_id in {"", ".", ".."}:
        raise ValueError(f"invalid request id for trusted evidence: {request_id!r}")
    evidence_dir = trusted_evidence_dir / request_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(evidence_dir / "request.json", request)
    atomic_write_json(evidence_dir / "response.json", response)
    _atomic_write_text(evidence_dir / "stdout.txt", stdout)
    _atomic_write_text(evidence_dir / "stderr.txt", stderr)
    atomic_write_json(
        evidence_dir / "manifest.json",
        {
            "request_id": request_id,
            "kind": response.get("kind"),
            "stored_at": now_ms(),
            "files": ["request.json", "response.json", "stdout.txt", "stderr.txt"],
        },
    )
    return evidence_dir


def _public_worker_failure(request: dict[str, Any], error: str) -> dict[str, Any]:
    """生成不包含 traceback、路径和 evaluator 内部细节的失败响应。"""
    return {
        "request_id": request.get("request_id"),
        "kind": request.get("kind") or "evaluate",
        "attempt_id": request.get("attempt_id"),
        "valid": False,
        "metrics": {},
        "diagnostics_public": {"worker_error": "trusted evaluator failure"},
        "stdout": "",
        "stderr": "",
        "extra": {},
        "error": error,
        "redacted_for_agent": True,
        "raw_evidence": {"available": True, "visibility": "trusted_only"},
        "evaluated_at": now_ms(),
    }


def _process_request(
    request_path: Path,
    *,
    responses_dir: Path,
    adapter_script: Path,
    task_dir: Path,
    output_dir: Path,
    private_key: Path,
    trusted_evidence_dir: Path,
    timeout_sec: float,
    run_dir: Path | None,
    judge_script: Path | None,
    judge_enabled: bool,
    judge_timeout_sec: float,
    agent_runtime: str,
    judge_model: str | None,
    evaluation_session: dict[str, Any],
    submissions_path: Path,
    submission_map_path: Path,
    agent_log_dir: Path | None = None,
) -> None:
    """按请求类型执行正式评分或最佳 attempt 有效性审查。"""
    raw = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("request_id"), str):
        raise ValueError(f"invalid evaluator request: {request_path}")
    request_id = raw["request_id"]
    if request_path.name != f"{request_id}.json":
        raise ValueError("request filename and request_id do not match")
    kind = str(raw.get("kind") or "evaluate")
    if kind == "evaluate":
        result, stdout, stderr, returncode = _evaluate(
            adapter_script=adapter_script,
            task_dir=task_dir,
            output_dir=output_dir,
            timeout_sec=timeout_sec,
        )
        result = _attach_evaluation_session_state(
            result,
            task_name=task_dir.name,
            session=evaluation_session,
        )
        response = _raw_response_for(
            request=raw,
            adapter_result=result,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
        # 该历史由 Trusted Evaluator 持有；Core/Agent 只得到签名后的公开响应。
        # 字段与 NatureBench 官方 Evaluation Service 写出的 schema 保持一致。
        _append_native_submission(
            submissions_path=submissions_path,
            submission_map_path=submission_map_path,
            request=raw,
            response=response,
        )
    elif kind == "validity_judge":
        if run_dir is None or not judge_enabled:
            raise RuntimeError("trusted worker was not configured for validity judge")
        attempt_id = str(raw.get("attempt_id") or "")
        if not attempt_id:
            raise ValueError("validity_judge request requires attempt_id")
        verdict, stdout, stderr, returncode = _judge(
            judge_script=judge_script,
            task_dir=task_dir,
            run_dir=run_dir,
            best_attempt_id=attempt_id,
            request_id=request_id,
            agent_runtime=agent_runtime,
            model=judge_model,
            timeout_sec=judge_timeout_sec,
            submissions_path=submissions_path,
            submission_map_path=submission_map_path,
        )
        response = _judge_response_for(
            request=raw,
            verdict=verdict,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
    else:
        raise ValueError(f"unsupported trusted request kind: {kind!r}")
    _persist_trusted_evidence(
        trusted_evidence_dir,
        request=raw,
        response=response,
        stdout=stdout,
        stderr=stderr,
    )
    public_response = (
        _public_judge_response_for(response)
        if kind == "validity_judge"
        else _public_response_for(response)
    )
    public_response = {
        **public_response,
        **write_agent_log_copy(
            agent_log_dir or trusted_evidence_dir.parent / "evaluator_agent_logs",
            request_id=request_id,
            stdout=stdout,
            stderr=stderr,
        ),
    }
    response_path = responses_dir / f"{request_id}.json"
    signature_path = responses_dir / f"{request_id}.sig"
    atomic_write_json(response_path, public_response)
    _sign(response_path, signature_path, private_key)


def _build_parser() -> argparse.ArgumentParser:
    """构建可信 evaluator worker 的参数解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--channel-dir", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument(
        "--trusted-evidence-dir",
        required=True,
        help="保存原始 evaluator 证据的 Agent 不可见目录",
    )
    parser.add_argument("--agent-log-dir")
    parser.add_argument("--adapter-script")
    parser.add_argument("--run-dir")
    parser.add_argument("--agent-runtime", default="claude")
    parser.add_argument("--validity-judge-script")
    parser.add_argument("--judge-settings")
    parser.add_argument("--judge-model")
    parser.add_argument("--evaluation-timeout-sec", type=float, default=3600)
    parser.add_argument("--judge-timeout-sec", type=float, default=900)
    parser.add_argument("--idle-timeout-sec", type=float, default=7200)
    parser.add_argument("--poll-interval-sec", type=float, default=1.0)
    parser.add_argument("--min-requests", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动可信文件队列 worker，直到 Agent 写入结束标记。"""
    args = _build_parser().parse_args(list(argv or sys.argv[1:]))
    task_dir = Path(args.task_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    channel_dir = Path(args.channel_dir).expanduser().resolve()
    private_key = Path(args.private_key).expanduser().resolve()
    trusted_evidence_dir = Path(args.trusted_evidence_dir).expanduser().resolve()
    agent_log_dir = (
        Path(args.agent_log_dir).expanduser().resolve()
        if args.agent_log_dir
        else channel_dir.parent / "evaluator_agent_logs"
    )
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else None
    adapter_script = (
        Path(args.adapter_script).expanduser().resolve()
        if args.adapter_script
        else Path(__file__).resolve().parents[2] / "examples" / "naturebench" / "evaluate_task.py"
    )
    judge_script = (
        Path(args.validity_judge_script).expanduser().resolve()
        if args.validity_judge_script
        else None
    )
    judge_enabled = run_dir is not None
    judge_settings = (
        Path(args.judge_settings).expanduser().resolve()
        if args.judge_settings
        else None
    )
    judge_model = None if args.judge_model in (None, "", "-") else str(args.judge_model)
    _load_trusted_settings(judge_settings)
    if judge_enabled:
        _assert_judge_credentials(judge_model)
    for path, label in (
        (task_dir, "task directory"),
        (private_key, "private key"),
        (adapter_script, "adapter script"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")
    if run_dir is not None and not run_dir.is_dir():
        raise FileNotFoundError(f"run directory not found: {run_dir}")
    _validate_trusted_evidence_dir(
        trusted_evidence_dir,
        agent_log_dir,
        run_dir=run_dir,
    )
    if judge_script is not None and not judge_script.is_file():
        raise FileNotFoundError(f"validity judge script not found: {judge_script}")
    requests_dir = channel_dir / "requests"
    responses_dir = channel_dir / "responses"
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)
    trusted_evidence_dir.mkdir(parents=True, exist_ok=True)
    submissions_path = trusted_evidence_dir / "submissions.jsonl"
    submission_map_path = trusted_evidence_dir / "submission_map.jsonl"
    atomic_write_json(
        channel_dir / "EVALUATOR_READY.json",
        {
            "task_id": task_dir.name,
            "output_binding": "trusted_worker_fixed_output",
            "validity_judge": judge_enabled,
            "native_submission_history": True,
            "ready_at": now_ms(),
        },
    )
    # 已签名响应表示该请求完整提交过；Evaluator 进程重启时不可重复计分。
    processed: set[str] = {
        path.name for path in responses_dir.glob("*.json") if path.is_file()
    }
    evaluation_session = _load_evaluation_session(submissions_path)
    last_activity = time.monotonic()
    while True:
        pending = [
            path
            for path in sorted(requests_dir.glob("*.json"))
            if path.name not in processed
        ]
        for request_path in pending:
            try:
                _process_request(
                    request_path,
                    responses_dir=responses_dir,
                    adapter_script=adapter_script,
                    task_dir=task_dir,
                    output_dir=output_dir,
                    private_key=private_key,
                    trusted_evidence_dir=trusted_evidence_dir,
                    agent_log_dir=agent_log_dir,
                    timeout_sec=args.evaluation_timeout_sec,
                    run_dir=run_dir,
                    judge_script=judge_script,
                    judge_enabled=judge_enabled,
                    judge_timeout_sec=args.judge_timeout_sec,
                    agent_runtime=str(args.agent_runtime),
                    judge_model=judge_model,
                    evaluation_session=evaluation_session,
                    submissions_path=submissions_path,
                    submission_map_path=submission_map_path,
                )
            except Exception as exc:  # noqa: BLE001 - worker 失败也必须返回签名证据
                try:
                    request = json.loads(request_path.read_text(encoding="utf-8"))
                    request_id = str(request["request_id"])
                    response_path = responses_dir / f"{request_id}.json"
                    traceback_text = traceback.format_exc()
                    raw_failure = {
                        "request_id": request_id,
                        "kind": request.get("kind") or "evaluate",
                        "attempt_id": request.get("attempt_id"),
                        "valid": False,
                        "metrics": {},
                        "official_metrics": {},
                        "diagnostics_public": {},
                        "stdout": "",
                        "stderr": traceback_text,
                        "extra": {"worker_error": repr(exc)},
                        "error": repr(exc),
                        "evaluated_at": now_ms(),
                    }
                    _persist_trusted_evidence(
                        trusted_evidence_dir,
                        request=request,
                        response=raw_failure,
                        stdout="",
                        stderr=traceback_text,
                    )
                    failure_public = {
                        **_public_worker_failure(
                            request,
                            "trusted evaluator failed; see trusted evidence",
                        ),
                        **write_agent_log_copy(
                            agent_log_dir
                            or trusted_evidence_dir.parent / "evaluator_agent_logs",
                            request_id=request_id,
                            stdout="",
                            stderr=traceback_text,
                        ),
                    }
                    atomic_write_json(
                        response_path,
                        failure_public,
                    )
                    _sign(
                        response_path,
                        responses_dir / f"{request_id}.sig",
                        private_key,
                    )
                except Exception:
                    raise RuntimeError(
                        f"unable to persist evaluator failure for {request_path}"
                    ) from exc
            processed.add(request_path.name)
            last_activity = time.monotonic()
        done = (channel_dir / "CLIENT_DONE.json").is_file()
        if done and len(processed) >= args.min_requests and not pending:
            break
        # Task-local worker 与 Agent 属于同一个 fm-job。首次 Candidate 之前可能有
        # 较长的 Idea/Implement 阶段，不能把“尚未提交”误判为 evaluator 超时。
        if processed and time.monotonic() - last_activity > args.idle_timeout_sec:
            raise TimeoutError(
                f"evaluator worker idle timeout after {args.idle_timeout_sec:g}s"
            )
        time.sleep(max(0.05, args.poll_interval_sec))
    atomic_write_json(
        channel_dir / "EVALUATOR_DONE.json",
        {"processed_requests": len(processed), "finished_at": now_ms()},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
