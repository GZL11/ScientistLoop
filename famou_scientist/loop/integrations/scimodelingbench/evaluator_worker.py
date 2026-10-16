"""Trusted SciModelingBench evaluator worker for the signed file channel."""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ...utils import atomic_write_json, now_ms
from ..evaluator_logs import write_agent_log_copy
from .benchmark import _load_submission
from .task_catalog import DEFAULT_HF_REVISION, task_spec


_TASK_CLASS_BY_CONFIG = {
    "tfbind8": "TFBind8BlackBoxOptimizationTask",
    "tfbind10_pho4": "TFBind10Pho4BlackBoxOptimizationTask",
    "cell_dag_nas": "CellDAGNASBlackBoxOptimizationTask",
    "superconductor": "SuperconductorCandidatePoolRankingTask",
    "hopper_controller": "HopperControllerCandidatePoolRankingTask",
    "utr_mrl_egfp_unmodified": "UTRMRLCompositionalRankingTask",
    "gfp": "GFPCandidatePoolRankingTask",
    "drugmatrix_clinical_pathology": "DrugMatrixCandidatePoolRankingTask",
}


def _sign(path: Path, signature_path: Path, private_key: Path) -> None:
    """Sign a redacted response with the trusted private key."""

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


def _load_callable(spec: str) -> Callable[..., Any]:
    """Load ``module:callable`` used to customize task construction."""

    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"task loader must be module:callable, got {spec!r}")
    module = importlib.import_module(module_name)
    value = getattr(module, attribute)
    if not callable(value):
        raise TypeError(f"task loader is not callable: {spec}")
    return value


def _default_load_task(
    task_id: str,
    *,
    revision: str | None,
    cache_dir: str | Path | None = None,
) -> Any:
    """Load a SciModelingBench task using the public package API when available."""

    spec = task_spec(task_id)
    module = importlib.import_module("sci_modeling_bench.suites.design_bench")
    class_name = _TASK_CLASS_BY_CONFIG[spec.config]
    task_cls = getattr(module, class_name)
    from_hub = getattr(task_cls, "from_hub")
    kwargs: dict[str, Any] = {}
    if revision:
        kwargs["revision"] = revision
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    if spec.endpoint:
        kwargs["endpoint"] = spec.endpoint
    try:
        return from_hub(**kwargs)
    except TypeError:
        kwargs.pop("endpoint", None)
        task = from_hub(**kwargs)
        if spec.endpoint and hasattr(task, "with_endpoint"):
            return task.with_endpoint(spec.endpoint)
        return task


def _load_task(
    task_id: str,
    *,
    revision: str | None,
    loader: str | None,
    cache_dir: str | Path | None = None,
) -> Any:
    """Load the trusted task through an override or the default package mapping."""

    if loader:
        return _load_callable(loader)(
            task_id=task_id,
            revision=revision,
            cache_dir=cache_dir,
        )
    return _default_load_task(task_id, revision=revision, cache_dir=cache_dir)


def _scalar_metrics(value: Any) -> dict[str, Any]:
    """Keep only scalar metrics in the signed public response."""

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


def _to_public_result(
    *,
    request: dict[str, Any],
    task_id: str,
    evaluation: Any,
) -> dict[str, Any]:
    """Convert package-specific evaluation output to the signed Famou schema."""

    spec = task_spec(task_id)
    if isinstance(evaluation, dict):
        score = evaluation.get("score")
        metrics = evaluation.get("metrics")
        valid = evaluation.get("valid", evaluation.get("submission_valid", True))
        diagnostics = evaluation.get("diagnostics_public") or {}
    else:
        score = getattr(evaluation, "score", None)
        metrics = getattr(evaluation, "metrics", {})
        valid = getattr(
            evaluation,
            "evaluation_eligible",
            getattr(evaluation, "submission_valid", True),
        )
        diagnostics = {}
        for key in ("valid_candidates", "invalid_candidates", "submission_valid"):
            if hasattr(evaluation, key):
                diagnostics[key] = getattr(evaluation, key)
    public_metrics = _scalar_metrics(metrics)
    public_metrics.setdefault("score", score)
    public_metrics.setdefault("primary_metric", spec.primary_metric)
    if isinstance(score, (int, float)) and spec.primary_metric not in public_metrics:
        public_metrics[spec.primary_metric] = score
    return {
        "request_id": request["request_id"],
        "kind": "evaluate",
        "attempt_id": request.get("attempt_id"),
        "benchmark": f"scimodelingbench/{spec.task_id}",
        "valid": bool(valid),
        "metrics": public_metrics,
        "official_metrics": public_metrics,
        "diagnostics_public": _scalar_metrics(diagnostics),
        "error": None,
        "redacted_for_agent": True,
        "evaluated_at": now_ms(),
    }


def _evaluate_request(
    *,
    request: dict[str, Any],
    workspace_dir: Path,
    task_id: str,
    revision: str | None,
    task_loader: str | None,
    cache_dir: str | Path | None,
) -> dict[str, Any]:
    """Run one trusted SciModelingBench evaluation."""

    if request.get("kind") != "evaluate":
        return {
            "request_id": request["request_id"],
            "kind": request.get("kind"),
            "attempt_id": request.get("attempt_id"),
            "benchmark": f"scimodelingbench/{task_spec(task_id).task_id}",
            "valid": False,
            "metrics": {},
            "official_metrics": {},
            "diagnostics_public": {},
            "error": f"unsupported evaluator operation: {request.get('kind')}",
            "redacted_for_agent": True,
            "evaluated_at": now_ms(),
        }
    attempt_id = str(request.get("attempt_id") or "")
    submission_dir = workspace_dir / "output" / "submission"
    if attempt_id.startswith("limited_gt_candidate_"):
        if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in attempt_id):
            raise ValueError("invalid limited-GT candidate id")
        submission_dir = workspace_dir / "output" / "limited_gt_inputs" / attempt_id
    submission = _load_submission(submission_dir)
    task = _load_task(
        task_id,
        revision=revision,
        loader=task_loader,
        cache_dir=cache_dir,
    )
    evaluation = task.evaluate(submission)
    return _to_public_result(request=request, task_id=task_id, evaluation=evaluation)


def _iter_requests(channel_dir: Path):
    """Yield request files until the controller signals completion."""

    requests = channel_dir / "requests"
    claims = channel_dir / "claimed_requests"
    claims.mkdir(parents=True, exist_ok=True)
    claims.chmod(0o700)
    seen: set[str] = set()
    while True:
        for path in sorted(requests.glob("*.json")):
            if path.name in seen:
                continue
            seen.add(path.name)
            if ((channel_dir / "responses" / path.name).is_file()
                    and (channel_dir / "responses" / f"{path.stem}.sig").is_file()):
                continue
            # Persist before executing GT. A crash leaves an uncertain request;
            # restarting a worker must never silently execute it a second time.
            try:
                with (claims / path.name).open("x") as claim:
                    claim.write(str(now_ms()))
            except FileExistsError:
                continue
            yield path
        if (channel_dir / "CLIENT_DONE.json").exists():
            return
        time.sleep(0.2)


def _build_parser() -> argparse.ArgumentParser:
    """Build the trusted worker CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--workspace-dir", required=True)
    parser.add_argument("--channel-dir", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--agent-log-dir")
    parser.add_argument("--revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--cache-dir")
    parser.add_argument(
        "--task-loader",
        help="Optional trusted module:callable override for constructing tasks.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Serve signed SciModelingBench evaluator responses."""

    args = _build_parser().parse_args(argv)
    channel_dir = Path(args.channel_dir).expanduser().resolve()
    agent_log_dir = (
        Path(args.agent_log_dir).expanduser().resolve()
        if args.agent_log_dir
        else channel_dir.parent / "evaluator_agent_logs"
    )
    workspace_dir = Path(args.workspace_dir).expanduser().resolve()
    private_key = Path(args.private_key).expanduser().resolve()
    responses = channel_dir / "responses"
    responses.mkdir(parents=True, exist_ok=True)
    (channel_dir / "requests").mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        channel_dir / "EVALUATOR_READY.json",
        {
            "task_id": args.task_id,
            "revision": args.revision,
            "workspace_dir": str(workspace_dir),
            "created_at": now_ms(),
        },
    )

    for request_path in _iter_requests(channel_dir):
        request = None
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if not isinstance(request, dict) or not request.get("request_id"):
                raise ValueError(f"invalid evaluator request: {request_path}")
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(
                stderr_buffer
            ):
                response = _evaluate_request(
                    request=request,
                    workspace_dir=workspace_dir,
                    task_id=args.task_id,
                    revision=args.revision,
                    task_loader=args.task_loader,
                    cache_dir=args.cache_dir,
                )
            response.update(
                write_agent_log_copy(
                    agent_log_dir,
                    request_id=response["request_id"],
                    stdout=stdout_buffer.getvalue(),
                    stderr=stderr_buffer.getvalue(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - failures still need signed responses
            request_id = request.get("request_id") if isinstance(request, dict) else request_path.stem
            response = {
                "request_id": str(request_id),
                "kind": "evaluate",
                "attempt_id": request.get("attempt_id") if isinstance(request, dict) else None,
                "benchmark": f"scimodelingbench/{args.task_id}",
                "valid": False,
                "metrics": {},
                "official_metrics": {},
                "diagnostics_public": {},
                "error": f"{type(exc).__name__}: {exc}",
                "redacted_for_agent": True,
                "evaluated_at": now_ms(),
                **write_agent_log_copy(
                    agent_log_dir,
                    request_id=request.get("request_id", request_path.stem)
                    if isinstance(request, dict)
                    else request_path.stem,
                    stdout="",
                    stderr=f"{type(exc).__name__}: {exc}",
                ),
            }
        response_path = responses / f"{response['request_id']}.json"
        signature_path = responses / f"{response['request_id']}.sig"
        atomic_write_json(response_path, response)
        _sign(response_path, signature_path, private_key)
    atomic_write_json(
        channel_dir / "EVALUATOR_DONE.json",
        {
            "task_id": args.task_id,
            "revision": args.revision,
            "finished_at": now_ms(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
