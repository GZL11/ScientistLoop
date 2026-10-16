"""基准适配器与可信评测器实现。"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ..utils import now_ms


def _bounded_output(value: Any, limit_bytes: int) -> tuple[str, bool, int]:
    """截断评测进程输出并返回截断标记和原始字节数。"""
    text = value if isinstance(value, str) else str(value or "")
    raw = text.encode("utf-8", errors="replace")
    original_bytes = len(raw)
    limit = max(1, int(limit_bytes))
    if original_bytes <= limit:
        return text, False, original_bytes
    tail = raw[-limit:].decode("utf-8", errors="replace")
    return "[... evaluator output truncated ...]\n" + tail, True, original_bytes


def _safe_scalar_metrics(value: Any) -> dict[str, Any]:
    """仅保留可安全暴露的标量指标。"""
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    blocked_tokens = (
        "example",
        "sample",
        "label",
        "prediction",
        "trace",
        "raw",
        "stdout",
        "stderr",
        "debug",
    )
    for key, item in value.items():
        name = str(key)
        lowered = name.lower()
        if any(token in lowered for token in blocked_tokens):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[name] = item
    return safe


class BenchmarkAdapter:
    """定义基准评测适配器接口。"""
    def validate_artifact(self, artifact_path: str) -> dict[str, Any]:
        """校验待评测产物是否可用。"""
        return {"valid": Path(artifact_path).exists(), "artifact": artifact_path}

    def run_public_eval(self, artifact_path: str) -> dict[str, Any]:
        """运行公开评测。"""
        raise NotImplementedError

    def run_official_eval(self, artifact_path: str) -> dict[str, Any]:
        """运行正式评测。"""
        raise NotImplementedError

    def score_schema(self) -> dict[str, Any]:
        """返回评测分数字段约定。"""
        return {
            "official_metrics": {},
            "optional_metrics": {},
            "diagnostics_public": {},
            "extra": {},
            "stdout": "",
            "stderr": "",
        }

    def agent_view(self, result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
        """返回可暴露给智能体的评测视图。"""
        actual_source = str(source or result.get("source") or "")
        is_official = actual_source == "official_evaluator"
        safe: dict[str, Any] = {
            "benchmark": result.get("benchmark"),
            "source": actual_source,
            "valid": result.get("valid") is True,
        }
        metric_key = "official_metrics" if is_official else "metrics"
        safe[metric_key] = _safe_scalar_metrics(result.get(metric_key))
        public_diagnostics = result.get("diagnostics_public")
        if isinstance(public_diagnostics, dict):
            safe["diagnostics_public"] = _safe_scalar_metrics(public_diagnostics)
        # extra 只向智能体暴露安全的标量视图；完整 extra 保留在 evaluator
        # evidence 中。若 evaluator 明确提供 extra_public，则优先使用它。
        public_extra = result.get("extra_public")
        if not isinstance(public_extra, dict) or not public_extra:
            public_extra = result.get("extra")
        if isinstance(public_extra, dict):
            safe["extra"] = _safe_scalar_metrics(public_extra)
        if result.get("valid") is not True and result.get("error"):
            safe["error"] = str(result["error"])
        safe["redacted_for_agent"] = True
        return safe


class DummyEvaluatorAdapter(BenchmarkAdapter):
    """提供确定性的测试用评测适配器。"""
    def __init__(self, benchmark: dict | None = None):
        """初始化对象并保存必要配置。"""
        self.benchmark = benchmark or {"name": "dummy"}

    def run_public_eval(self, artifact_path: str) -> dict[str, Any]:
        """运行公开评测。"""
        return {
            "benchmark": self.benchmark.get("name", "dummy"),
            "source": "public_eval",
            "valid": True,
            "metrics": {"accuracy": 0.80, "latency_ms": 1.5},
            "diagnostics_public": {},
            "extra": {},
            "stdout": "",
            "stderr": "",
            "artifact": artifact_path,
            "created_at": now_ms(),
        }

    def run_official_eval(self, artifact_path: str) -> dict[str, Any]:
        """运行正式评测。"""
        return {
            "benchmark": self.benchmark.get("name", "dummy"),
            "source": "official_evaluator",
            "valid": True,
            "official_metrics": {"accuracy": 0.79},
            "diagnostics_public": {},
            "extra": {},
            "stdout": "",
            "stderr": "",
            "artifact": artifact_path,
            "created_at": now_ms(),
        }


class CommandEvaluatorAdapter(BenchmarkAdapter):
    """通过外部命令执行公开和正式评测。"""
    def __init__(self, benchmark: dict[str, Any], *, cwd: str | Path | None = None):
        """初始化对象并保存必要配置。"""
        self.benchmark = benchmark
        self.cwd = Path(cwd).resolve() if cwd else None
        adapter = benchmark.get("adapter") if isinstance(benchmark.get("adapter"), dict) else {}
        self.public_cmd = adapter.get("public_eval_cmd")
        self.official_cmd = adapter.get("official_eval_cmd")
        self.public_argv = self._validate_argv(
            adapter.get("public_eval_argv"),
            "public_eval_argv",
        )
        self.official_argv = self._validate_argv(
            adapter.get("official_eval_argv"),
            "official_eval_argv",
        )
        self.timeout_sec = int(adapter.get("timeout_sec") or 3600)
        output_limit = int(adapter.get("output_limit_bytes") or 64 * 1024)
        self.stdout_limit_bytes = int(adapter.get("stdout_limit_bytes") or output_limit)
        self.stderr_limit_bytes = int(adapter.get("stderr_limit_bytes") or output_limit)

    @staticmethod
    def _validate_argv(value: Any, field: str) -> list[str]:
        """校验无需 Shell 的评测命令参数模板。"""
        if value is None:
            return []
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(f"benchmark.adapter.{field} 必须是非空字符串列表")
        return list(value)

    def _run_cmd(
        self,
        command_template: str | list[str],
        artifact_path: str,
        source: str,
    ) -> dict[str, Any]:
        """运行评测命令并解析结果。"""
        config_dir = str(self.cwd or Path.cwd())
        values = {
            "artifact": str(artifact_path),
            "config_dir": config_dir,
            "goal_dir": config_dir,
        }
        if isinstance(command_template, list):
            invocation: str | list[str] = [
                item.format(**values) for item in command_template
            ]
            command_display = shlex.join(invocation)
            use_shell = False
        else:
            quoted_values = {key: shlex.quote(value) for key, value in values.items()}
            invocation = command_template.format(**quoted_values)
            command_display = invocation
            use_shell = True
        timed_out = False
        try:
            proc = subprocess.run(
                invocation,
                shell=use_shell,
                cwd=str(self.cwd) if self.cwd else None,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_sec,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            # 超时仍然算一次评测提交；返回可持久化的无效结果。
            # 调度器据此记录证据并扣减正式评测预算，而不是变成未追踪异常。
            timed_out = True
            proc = None
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            returncode = -1
        parsed: dict[str, Any] = {}
        parse_error = None
        if stdout.strip():
            try:
                parsed = json.loads(stdout.strip().splitlines()[-1])
            except json.JSONDecodeError as exc:
                parse_error = repr(exc)
                parsed = {}
        metrics = parsed.get("metrics") if isinstance(parsed.get("metrics"), dict) else {}
        official_metrics = parsed.get("official_metrics") if isinstance(parsed.get("official_metrics"), dict) else {}
        diagnostics_public = (
            parsed.get("diagnostics_public")
            if isinstance(parsed.get("diagnostics_public"), dict)
            else {}
        )
        extra = parsed.get("extra") if isinstance(parsed.get("extra"), dict) else {}
        extra_public = (
            parsed.get("extra_public")
            if isinstance(parsed.get("extra_public"), dict)
            else {}
        )
        if source == "official_evaluator" and not official_metrics and metrics:
            official_metrics = metrics
        bounded_stdout, stdout_truncated, stdout_bytes = _bounded_output(
            stdout,
            self.stdout_limit_bytes,
        )
        bounded_stderr, stderr_truncated, stderr_bytes = _bounded_output(
            stderr,
            self.stderr_limit_bytes,
        )
        parsed_valid = parsed.get("valid")
        valid = (
            returncode == 0
            and parse_error is None
            and not timed_out
            and parsed_valid is not False
        )
        return {
            "benchmark": self.benchmark.get("name"),
            "source": source,
            "valid": valid,
            "returncode": returncode,
            "timed_out": timed_out,
            "command": command_display,
            "metrics": metrics or official_metrics,
            "official_metrics": official_metrics if source == "official_evaluator" else {},
            "diagnostics_public": diagnostics_public,
            "extra": extra,
            "extra_public": extra_public,
            "parsed": parsed,
            "parse_error": parse_error,
            "stdout": bounded_stdout,
            "stderr": bounded_stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "error": (
                "evaluator timeout"
                if timed_out
                else parsed.get("error")
                if isinstance(parsed.get("error"), str)
                else "evaluator returned invalid result"
                if parsed_valid is False
                else None
            ),
            "created_at": now_ms(),
        }

    def run_public_eval(self, artifact_path: str) -> dict[str, Any]:
        """运行公开评测。"""
        command = self.public_argv or self.public_cmd
        if not command:
            return {
                "benchmark": self.benchmark.get("name"),
                "source": "public_eval",
                "valid": False,
                "artifact": artifact_path,
                "error": "benchmark adapter 未配置 public evaluator",
                "created_at": now_ms(),
            }
        return self._run_cmd(command, artifact_path, "public_eval")

    def run_official_eval(self, artifact_path: str) -> dict[str, Any]:
        """运行正式评测。"""
        command = self.official_argv or self.official_cmd
        if not command:
            return {
                "benchmark": self.benchmark.get("name"),
                "source": "official_evaluator",
                "valid": False,
                "artifact": artifact_path,
                "error": "benchmark adapter 未配置 official evaluator",
                "created_at": now_ms(),
            }
        return self._run_cmd(command, artifact_path, "official_evaluator")


def adapter_from_goal(goal_doc: dict[str, Any], *, cwd: str | Path | None = None) -> BenchmarkAdapter:
    """根据目标配置创建 benchmark 评测适配器。"""
    workflow = goal_doc.get("workflow")
    if isinstance(workflow, dict) and workflow.get("type") == "benchmark_managed":
        raise ValueError(
            "benchmark_managed 目标必须通过 agent run 和 Evaluator Adapter 启动，"
            "不支持 loop run 的隐式 evaluator"
        )
    benchmarks = goal_doc.get("benchmarks") or []
    benchmark = benchmarks[0] if benchmarks and isinstance(benchmarks[0], dict) else {"name": "dummy"}
    adapter = benchmark.get("adapter") if isinstance(benchmark.get("adapter"), dict) else {}
    if adapter.get("type") == "command":
        return CommandEvaluatorAdapter(benchmark, cwd=cwd)
    if adapter.get("type") == "dummy":
        return DummyEvaluatorAdapter(benchmark)
    raise ValueError("goal 未配置受支持的 benchmark evaluator，拒绝使用隐式 Dummy 评分")
