"""SciModelingBench public task and submission-artifact adapter."""
from __future__ import annotations

import ast
import errno
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from ...execution.sandbox import (
    ExecutionIdentity,
    LocalSandbox,
    process_failure_message,
    signal_name,
)
from ...facilities import CandidateRef, RunnerBenchmarkFacility, TaskView
from ...utils import new_id, now_ms
from .task_catalog import SciModelingBenchTaskSpec, task_spec


def attempt_id_from_artifact(run_dir: Path, artifact_path: str) -> str:
    """Extract the candidate id from a controlled SciModelingBench artifact."""

    artifact = Path(artifact_path).expanduser().resolve()
    try:
        relative = artifact.relative_to(run_dir / "candidates")
    except ValueError as exc:
        raise ValueError("submission artifact is outside the run candidates") from exc
    if len(relative.parts) != 3 or relative.parts[1:] != (
        "output",
        "submission",
    ):
        raise ValueError("submission artifact does not follow the candidate contract")
    return relative.parts[0]


def _load_submission(artifact_path: str | Path) -> list[Any]:
    """Load the public submission list without touching hidden evaluator state."""

    artifact = Path(artifact_path).expanduser().resolve()
    path = artifact / "submission.json" if artifact.is_dir() else artifact
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("submission artifact must contain submission.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("submission", "candidates"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("submission.json must be a list or contain submission/candidates list")


def _safe_metrics(value: Any) -> dict[str, Any]:
    """Keep only scalar aggregate metrics safe to show to an agent."""

    if not isinstance(value, dict):
        return {}
    blocked = ("candidate", "label", "target", "rank", "raw", "lookup", "objective")
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if any(token in name.lower() for token in blocked):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[name] = item
    return result


def agent_view(result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """Redact any trusted response before it can reach the agent mailbox."""

    actual_source = str(source or result.get("source") or "")
    metric_key = "official_metrics" if actual_source == "official_evaluator" else "metrics"
    metrics = result.get(metric_key)
    if actual_source == "official_evaluator" and not isinstance(metrics, dict):
        metrics = result.get("metrics")
    safe: dict[str, Any] = {
        "benchmark": result.get("benchmark"),
        "source": actual_source,
        "valid": result.get("valid") is True,
        metric_key: _safe_metrics(metrics),
        "redacted_for_agent": True,
    }
    for key in ("execution_id", "agent_log_dir", "stdout_path", "stderr_path"):
        if isinstance(result.get(key), str):
            safe[key] = result[key]
    diagnostics = result.get("diagnostics_public")
    if isinstance(diagnostics, dict):
        safe["diagnostics_public"] = _safe_metrics(diagnostics)
    if result.get("valid") is not True and result.get("error"):
        safe["error"] = str(result["error"])
    return safe


class SciModelingBenchSubmissionRunner:
    """Run an agent-owned ``run.py`` that emits ``submission.json``."""

    def __init__(
        self,
        run_dir: str | Path,
        problem_dir: str | Path,
        *,
        task_id: str,
        timeout_sec: float,
        memory_limit_bytes: int | None = None,
        agent_uid: int | None = None,
        agent_gid: int | None = None,
    ):
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.problem_dir = Path(problem_dir).expanduser().resolve()
        self.spec = task_spec(task_id)
        self.timeout_sec = float(timeout_sec)
        self.memory_limit_bytes = (
            int(memory_limit_bytes) if memory_limit_bytes is not None else None
        )
        self.agent_identity = (
            ExecutionIdentity(
                uid=int(agent_uid),
                gid=int(agent_gid),
                prepare_root_owner=False,
            )
            if agent_uid is not None and agent_gid is not None
            else None
        )

    def preflight(self, branch: dict[str, Any]) -> dict[str, Any]:
        """Check only the public entrypoint and syntax."""

        entrypoint_value = branch.get("entrypoint")
        if not entrypoint_value:
            return {
                "valid": False,
                "source": "scimodelingbench_runner_preflight",
                "error": "SciModelingBench candidate must declare run.py",
            }
        entrypoint = Path(str(entrypoint_value)).expanduser().resolve()
        method_dir = Path(
            str(branch.get("method_dir") or entrypoint.parent)
        ).expanduser().resolve()
        checks: dict[str, Any] = {
            "entrypoint_exists": entrypoint.is_file(),
            "entrypoint_in_method_dir": False,
            "python_syntax": None,
        }
        try:
            entrypoint.relative_to(method_dir)
            checks["entrypoint_in_method_dir"] = True
        except ValueError:
            pass
        error: str | None = None
        if not checks["entrypoint_exists"]:
            error = f"entrypoint not found: {entrypoint}"
        elif not checks["entrypoint_in_method_dir"]:
            error = "entrypoint is outside the candidate code directory"
        elif entrypoint.suffix == ".py":
            try:
                ast.parse(entrypoint.read_text(encoding="utf-8"), filename=str(entrypoint))
                checks["python_syntax"] = True
            except (OSError, SyntaxError, UnicodeError) as exc:
                checks["python_syntax"] = False
                error = repr(exc)
        return {
            "valid": error is None,
            "source": "scimodelingbench_runner_preflight",
            "entrypoint": str(entrypoint),
            "method_dir": str(method_dir),
            "checks": checks,
            "error": error,
        }

    def run(self, branch: dict[str, Any]) -> dict[str, Any]:
        """Execute the candidate and freeze its submission directory."""

        branch_id = str(branch.get("branch_id") or branch.get("id") or "")
        candidate_id = str(branch.get("candidate_id") or "")
        candidate_root = Path(str(branch.get("candidate_dir") or "")).resolve()
        worktree = Path(
            str(branch.get("method_dir") or branch.get("worktree") or "")
        ).resolve()
        entrypoint = Path(str(branch.get("entrypoint") or "")).resolve()
        outputs_dir = Path(
            str(branch.get("candidate_output_dir") or branch.get("outputs_dir") or "")
        ).resolve()
        expected_candidate = self.run_dir / "candidates" / candidate_id
        valid_layout = (
            bool(candidate_id)
            and candidate_root == expected_candidate.resolve()
            and worktree == candidate_root / "code"
            and outputs_dir == candidate_root / "output"
        )
        try:
            entrypoint.relative_to(worktree)
        except ValueError:
            valid_layout = False
        if not valid_layout or not entrypoint.is_file():
            return {
                "id": new_id("run_failed"),
                "branch_id": branch_id,
                "source": "scimodelingbench_runner",
                "valid": False,
                "returncode": 2,
                "artifact": "",
                "error": "invalid branch workspace or missing entrypoint",
                "stage": "canonical_run",
                "error_code": "canonical_invalid_workspace",
                "retryable": True,
                "timeout_sec": self.timeout_sec,
                "created_at": now_ms(),
            }

        submission = outputs_dir / "submission"
        staging = outputs_dir / ".staging_submission"
        for path in (submission, staging):
            if path.exists():
                shutil.rmtree(path)
        staging.mkdir(parents=True)
        if self.agent_identity is not None:
            if os.geteuid() != 0:
                raise PermissionError("non-root supervisor cannot chown staging dir")
            try:
                os.chown(staging, self.agent_identity.uid, self.agent_identity.gid)
            except OSError as exc:
                if exc.errno not in {errno.EINVAL, errno.EPERM, errno.EOPNOTSUPP}:
                    raise
                staging.chmod(0o707)
            else:
                staging.chmod(0o700)

        resource_request = (
            branch.get("resource_request")
            if isinstance(branch.get("resource_request"), dict)
            else {}
        )
        requested_memory = resource_request.get("host_memory_gib")
        requested_memory_bytes = (
            int(float(requested_memory) * 1024**3)
            if requested_memory is not None
            else None
        )
        memory_limit_bytes = requested_memory_bytes
        if self.memory_limit_bytes is not None:
            memory_limit_bytes = min(
                self.memory_limit_bytes,
                requested_memory_bytes or self.memory_limit_bytes,
            )
        sandbox = LocalSandbox(
            candidate_root,
            memory_limit_bytes=memory_limit_bytes,
            identity=self.agent_identity,
            memory_limit_strategy="address_space",
        )
        try:
            result = sandbox.run(
                [sys.executable, str(entrypoint)],
                cwd=worktree,
                env={
                    "BENCHMARK_TASK_DIR": str(self.problem_dir),
                    "DATA_DIR": str(self.problem_dir / "data"),
                    "OUTPUT_DIR": str(staging),
                    "FAMOU_TASK_ID": self.spec.task_id,
                    "SCIMODELINGBENCH_TASK_ID": self.spec.task_id,
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                timeout_sec=self.timeout_sec,
                cancel_file=self.run_dir / "agent_control" / "research_stop_requested.json",
            )
        finally:
            sandbox.close()

        unsafe = [
            path
            for path in staging.rglob("*")
            if path.is_symlink() or (not path.is_file() and not path.is_dir())
        ]
        public_error: str | None = None
        if result.valid and not unsafe:
            try:
                candidates = _load_submission(staging)
                _validate_submission_size(candidates, self.spec)
            except Exception as exc:  # noqa: BLE001 - returned to agent as repairable
                public_error = str(exc)
        if result.valid and not unsafe and public_error is None:
            shutil.copytree(staging, submission, symlinks=False)
            for path in (submission, *submission.rglob("*")):
                path.chmod(0o555 if path.is_dir() else 0o444)
        shutil.rmtree(staging, ignore_errors=True)

        if result.cancelled:
            # 研究墙钟到点 / 任务被停时**是我们自己**给 canonical 进程发的 SIGTERM。
            # 这不是方法失败，不能进 ExpBank 当作"你的脚本挂了"喂回 Agent。
            error = "canonical run cancelled by controller (research stop)"
            error_code = "canonical_cancelled_by_controller"
        elif result.memory_limit_exceeded:
            error = "candidate exceeded canonical memory limit"
            error_code = "canonical_memory_limit_exceeded"
        elif result.timed_out:
            error = "candidate exceeded canonical time limit"
            error_code = "canonical_timeout"
        elif not result.valid and result.returncode < 0:
            # 非取消、非超时、非内存上限的信号死亡：外部（pod 抢占、内核 OOM
            # killer、容器重启）把进程打掉了，通常连 stderr 都不会留下。
            error = f"canonical run killed by {signal_name(result.returncode)}"
            error_code = "canonical_killed_by_signal"
        elif not result.valid:
            error = process_failure_message(result, subject="candidate")
            error_code = "canonical_process_failed"
        elif unsafe:
            error = "submission contains unsafe files"
            error_code = "canonical_unsafe_submission"
        elif public_error is not None:
            error = public_error
            error_code = "canonical_invalid_submission_json"
        else:
            error = None
            error_code = None
        return {
            "id": new_id("experiment"),
            "branch_id": branch_id,
            "candidate_id": candidate_id or None,
            "source": "scimodelingbench_runner",
            "valid": result.valid and not unsafe and public_error is None,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "artifact": str(submission),
            "artifact_kind": "candidate_submission",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": error,
            "stage": "canonical_run",
            "error_code": error_code,
            "retryable": error is not None,
            "timeout_sec": self.timeout_sec,
            "duration_ms": result.duration_ms,
            "memory_limit_bytes": result.memory_limit_bytes,
            "memory_limit_exceeded": result.memory_limit_exceeded,
            "observed_memory_bytes": result.observed_memory_bytes,
            "termination_reason": result.termination_reason,
            "resource_request": resource_request,
            "unsafe_submission_files": [str(path) for path in unsafe],
            "finished_at": now_ms(),
        }


def _validate_submission_size(candidates: list[Any], spec: SciModelingBenchTaskSpec) -> None:
    """Validate the public candidate count contract."""

    count = len(candidates)
    if spec.exact_submission_size and count != spec.submission_size:
        raise ValueError(
            f"{spec.task_id} requires exactly {spec.submission_size} candidates, got {count}"
        )
    if not spec.exact_submission_size and count < spec.submission_size:
        raise ValueError(
            f"{spec.task_id} requires at least {spec.submission_size} candidates, got {count}"
        )
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, (dict, str, int, float, bool)):
            raise ValueError(f"candidate {index} is not JSON scalar/object")


class _SciModelingBenchPublicAdapter:
    """Public-only artifact checker for SciModelingBench submissions."""

    def __init__(self, *, run_dir: str | Path, benchmark_name: str, spec: SciModelingBenchTaskSpec):
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.benchmark_name = str(benchmark_name)
        self.spec = spec

    def validate_artifact(self, artifact_path: str) -> dict[str, Any]:
        """Validate submission shape without loading hidden objectives."""

        try:
            attempt_id = attempt_id_from_artifact(self.run_dir, artifact_path)
            candidates = _load_submission(artifact_path)
            _validate_submission_size(candidates, self.spec)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "valid": False,
                "artifact": artifact_path,
                "error": str(exc),
                "diagnostics_public": {"format_check": "failed"},
            }
        return {
            "valid": True,
            "artifact": artifact_path,
            "error": None,
            "diagnostics_public": {
                "format_check": "passed",
                "attempt_id": attempt_id,
                "candidate_count": len(candidates),
                "scored_prefix": self.spec.submission_size,
            },
        }

    def run_public_eval(self, artifact_path: str) -> dict[str, Any]:
        """Return only public format diagnostics."""

        validation = self.validate_artifact(artifact_path)
        return {
            "benchmark": self.benchmark_name,
            "source": "scimodelingbench_public_preflight",
            "valid": validation.get("valid") is True,
            "metrics": {},
            "diagnostics_public": validation.get("diagnostics_public") or {},
            "extra": {},
            "stdout": "",
            "stderr": "",
            "artifact": artifact_path,
            "error": validation.get("error"),
            "created_at": now_ms(),
        }

    def run_official_eval(self, artifact_path: str) -> dict[str, Any]:
        """Fail closed: hidden scoring is only available through trusted transport."""

        raise RuntimeError("SciModelingBench public adapter does not run official scoring")

    def agent_view(self, result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
        """Redact public diagnostics."""

        return agent_view(result, source=source)


class SciModelingBenchBenchmarkFacility(RunnerBenchmarkFacility):
    """Benchmark facility exposing only public SciModelingBench task inputs."""

    def __init__(
        self,
        runner: SciModelingBenchSubmissionRunner,
        *,
        run_dir: str | Path,
        benchmark_name: str,
    ):
        super().__init__(
            runner,
            _SciModelingBenchPublicAdapter(
                run_dir=run_dir,
                benchmark_name=benchmark_name,
                spec=runner.spec,
            ),
            task_id=runner.spec.task_id,
        )

    def task_view(self) -> TaskView:
        """Return the public task contract staged into the agent worktree."""

        spec = self.runner.spec
        return TaskView(
            task_id=spec.task_id,
            public_path=str(self.runner.problem_dir),
            instructions=(
                "Read only the public SciModelingBench task files under "
                "benchmark_task/. Write a JSON candidate list to "
                "OUTPUT_DIR/submission.json. Do not call Task.evaluate or load "
                "hidden labels."
            ),
            metadata={
                "entrypoint": "run.py",
                "entrypoint_interface": (
                    "read BENCHMARK_TASK_DIR/DATA_DIR; write OUTPUT_DIR/submission.json"
                ),
                "input_environment": "BENCHMARK_TASK_DIR",
                "output_environment": "OUTPUT_DIR",
                "submission_file": "submission.json",
                "task_form": spec.task_form,
                "domain": spec.domain,
                "submission_size": spec.submission_size,
                "exact_submission_size": spec.exact_submission_size,
                "primary_metric": spec.primary_metric,
                "score_interpretation": {
                    "metric": spec.primary_metric,
                    "direction": spec.direction,
                    "target_instruction": (
                        f"Maximize {spec.primary_metric} by submitting "
                        f"{'exactly' if spec.exact_submission_size else 'at least'} "
                        f"{spec.submission_size} valid candidates. Official score "
                        "comes only from the trusted evaluator."
                    ),
                },
            },
        )

    def preflight(
        self,
        candidate: CandidateRef,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Require root ``run.py`` so the submission path stays deterministic."""

        expected = (Path(candidate.code_path) / "run.py").resolve()
        actual = Path(candidate.entrypoint).resolve() if candidate.entrypoint else None
        if actual != expected or not expected.is_file():
            return {
                "valid": False,
                "source": "scimodelingbench_task_contract",
                "checks": {"required_entrypoint": "run.py"},
                "error": "SciModelingBench task requires candidate entrypoint run.py",
            }
        return super().preflight(candidate, context=context)


__all__ = [
    "SciModelingBenchBenchmarkFacility",
    "SciModelingBenchSubmissionRunner",
    "agent_view",
    "attempt_id_from_artifact",
]
