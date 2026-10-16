"""SciModelingBench trusted evaluator proxy."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

from ...facilities import EvaluationRequest, EvaluationResult
from ...facilities.contracts import artifact_sha256
from .benchmark import agent_view, attempt_id_from_artifact


def _replace_path(source: Path, destination: Path) -> None:
    """Replace the canonical evaluator input without preserving symlinks."""

    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            # copytree preserves the frozen artifact's read-only directory
            # modes. The trusted staging copy must remain replaceable on the
            # next query (including when the controller is not root).
            destination.chmod(0o700)
            for directory in destination.rglob("*"):
                if directory.is_dir() and not directory.is_symlink():
                    directory.chmod(0o700)
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False)
        destination.chmod(0o700)
        for directory in destination.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o700)
    else:
        shutil.copy2(source, destination)


def _transport_request(transport: Any, *, operation: str, attempt_id: str) -> dict[str, Any]:
    """Call the trusted evaluator transport."""

    request = getattr(transport, "request", None)
    if not callable(request):
        raise TypeError("Evaluator transport must implement request(operation, attempt_id)")
    value = request(operation=operation, attempt_id=attempt_id)
    if not isinstance(value, dict):
        raise TypeError("trusted evaluator response must be an object")
    return value


class SciModelingBenchEvaluationFacility:
    """Publish candidate submissions and request trusted SciModelingBench scoring."""

    def __init__(
        self,
        transport: Any,
        *,
        run_dir: str | Path,
        workspace_dir: str | Path,
        benchmark_name: str,
    ):
        self.transport = transport
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.benchmark_name = str(benchmark_name)
        self._official_eval_lock = threading.Lock()

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """Verify, publish, and score one frozen submission artifact."""

        request.artifact_ref.verify()
        artifact_path = request.artifact_ref.storage_path
        attempt_id = attempt_id_from_artifact(self.run_dir, artifact_path)
        artifact = Path(artifact_path).resolve()
        with self._official_eval_lock:
            if attempt_id.startswith("limited_gt_candidate_"):
                # A timed-out request may still be pending in the worker. Give
                # each limited-GT candidate a fixed input so a subsequent query
                # or final audit cannot replace the pending request's content.
                inputs = self.workspace_dir / "output" / "limited_gt_inputs"
                inputs.mkdir(parents=True, exist_ok=True)
                inputs.chmod(0o700)
                staged = inputs / attempt_id
                if not staged.exists():
                    shutil.copytree(artifact, staged, symlinks=False)
                if artifact_sha256(staged) != request.artifact_ref.sha256:
                    raise ValueError("limited-GT evaluator input hash mismatch")
            else:
                _replace_path(artifact, self.workspace_dir / "output" / "submission")
            raw = _transport_request(
                self.transport,
                operation="evaluate",
                attempt_id=attempt_id,
            )
        public = agent_view(raw, source="official_evaluator")
        metrics = public.get("official_metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        return EvaluationResult(
            request_id=str(raw.get("request_id") or f"evaluation-{attempt_id}"),
            attempt_id=attempt_id,
            valid=raw.get("valid") is True,
            metrics=metrics,
            stdout="",
            stderr="",
            extra=dict(public.get("extra") or {}),
            diagnostics_public=dict(public.get("diagnostics_public") or {}),
            error=str(public["error"]) if public.get("error") else None,
            metadata={
                "benchmark": self.benchmark_name,
                "artifact": artifact_path,
                "redacted_for_agent": True,
                **{
                    key: public[key]
                    for key in (
                        "execution_id",
                        "agent_log_dir",
                        "stdout_path",
                        "stderr_path",
                    )
                    if isinstance(public.get(key), str)
                },
            },
        )

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Return a redacted official-score view."""

        return agent_view(result, source=source)

    def close(self) -> None:
        """Close the trusted transport."""

        self.transport.close()


__all__ = ["SciModelingBenchEvaluationFacility"]
