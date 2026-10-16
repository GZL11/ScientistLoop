"""SciModelingBench adapter isolation tests."""
from __future__ import annotations

import json
from pathlib import Path

from famou_scientist.loop.facilities import ArtifactRef
from famou_scientist.loop.facilities.contracts import EvaluationRequest
from famou_scientist.loop.integrations.scimodelingbench import (
    SciModelingBenchBenchmarkAdapter,
    SciModelingBenchEvaluatorAdapter,
)
from famou_scientist.loop.integrations.scimodelingbench.benchmark import (
    SciModelingBenchSubmissionRunner,
)
from famou_scientist.loop.plugins import AdapterContext, available_adapters, load_adapter


class _Transport:
    """Trusted transport fixture returning intentionally over-detailed metrics."""

    def request(self, *, operation: str, attempt_id: str) -> dict[str, object]:
        """Return a signed-worker-like response."""

        return {
            "request_id": f"{operation}-{attempt_id}",
            "attempt_id": attempt_id,
            "valid": True,
            "metrics": {
                "score": 0.7,
                "best_k_mean": 0.7,
                "raw_candidate_scores": [0.1, 0.7],
                "hidden_label_mean": 0.4,
            },
            "diagnostics_public": {
                "valid_candidates": 32,
                "hidden_target_count": 100,
            },
            "redacted_for_agent": True,
        }

    def close(self) -> None:
        """No-op for tests."""


def _context(tmp_path: Path, *, task_id: str = "tfbind8") -> AdapterContext:
    """Create an adapter context with a public problem directory."""

    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    (problem / "task.md").write_text("public task only", encoding="utf-8")
    return AdapterContext(
        task_id=task_id,
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
    )


def test_scimodelingbench_adapters_are_registered() -> None:
    """The integration should be loadable through the plugin registry."""

    assert "scimodelingbench" in available_adapters("benchmark")
    assert "scimodelingbench" in available_adapters("evaluator")
    assert load_adapter("benchmark", "scimodelingbench").name == "scimodelingbench"
    assert load_adapter("evaluator", "scimodelingbench").name == "scimodelingbench"


def test_task_view_exposes_submission_contract_without_evaluator(tmp_path: Path) -> None:
    """Public task metadata should not expose hidden Objective state."""

    facility = SciModelingBenchBenchmarkAdapter().create(_context(tmp_path))
    view = facility.task_view()

    assert view.metadata["entrypoint"] == "run.py"
    assert view.metadata["submission_file"] == "submission.json"
    assert view.metadata["primary_metric"] == "best_k_mean"
    assert "Objective" not in json.dumps(view.to_dict(), ensure_ascii=False)


def test_public_adapter_validates_submission_but_refuses_official_eval(tmp_path: Path) -> None:
    """The benchmark side is allowed to check format, not score hidden labels."""

    context = _context(tmp_path)
    facility = SciModelingBenchBenchmarkAdapter().create(context)
    artifact = context.run_dir / "candidates" / "candidate-1" / "output" / "submission"
    artifact.mkdir(parents=True)
    candidates = [{"sequence": "AAAAAAAA"} for _ in range(32)]
    (artifact / "submission.json").write_text(json.dumps(candidates), encoding="utf-8")
    ref = ArtifactRef.from_path(
        artifact,
        artifact_id="artifact-1",
        kind="candidate_submission",
        producer="test",
    )

    validation = facility.validate_artifact(ref)

    assert validation["valid"] is True
    assert validation["diagnostics_public"]["candidate_count"] == 32
    public = facility.run_public_evaluation(ref)
    assert public["metrics"] == {}


def test_runner_freezes_submission_json_artifact(tmp_path: Path) -> None:
    """Canonical run should freeze only the produced submission directory."""

    run_dir = tmp_path / "run"
    problem = run_dir / "problem"
    candidate = run_dir / "candidates" / "candidate-1"
    code = candidate / "code"
    output = candidate / "output"
    problem.mkdir(parents=True)
    code.mkdir(parents=True)
    output.mkdir(parents=True)
    (code / "run.py").write_text(
        "import json, os\n"
        "out = os.environ['OUTPUT_DIR']\n"
        "os.makedirs(out, exist_ok=True)\n"
        "json.dump([{'sequence':'AAAAAAAA'} for _ in range(32)], "
        "open(os.path.join(out, 'submission.json'), 'w'))\n",
        encoding="utf-8",
    )
    runner = SciModelingBenchSubmissionRunner(
        run_dir,
        problem,
        task_id="tfbind8",
        timeout_sec=10,
    )

    result = runner.run(
        {
            "branch_id": "branch-1",
            "candidate_id": "candidate-1",
            "candidate_dir": str(candidate),
            "method_dir": str(code),
            "entrypoint": str(code / "run.py"),
            "candidate_output_dir": str(output),
        }
    )

    assert result["valid"] is True
    frozen = output / "submission" / "submission.json"
    assert frozen.is_file()
    assert not (output / ".staging_submission").exists()


def test_evaluator_facility_redacts_hidden_metric_fields(tmp_path: Path) -> None:
    """Trusted responses should be filtered again before entering Loop state."""

    context = _context(tmp_path)
    artifact = context.run_dir / "candidates" / "candidate-1" / "output" / "submission"
    artifact.mkdir(parents=True)
    (artifact / "submission.json").write_text(
        json.dumps([{"sequence": "AAAAAAAA"} for _ in range(32)]),
        encoding="utf-8",
    )
    ref = ArtifactRef.from_path(
        artifact,
        artifact_id="artifact-1",
        kind="candidate_submission",
        producer="test",
    )
    facility = SciModelingBenchEvaluatorAdapter().create(context, _Transport())

    result = facility.evaluate(
        EvaluationRequest(
            task_id="tfbind8",
            attempt_id="candidate-1",
            artifact_ref=ref,
        )
    )

    assert result.valid is True
    assert result.metrics["score"] == 0.7
    assert "best_k_mean" in result.metrics
    assert "raw_candidate_scores" not in result.metrics
    assert "hidden_label_mean" not in result.metrics
    assert "hidden_target_count" not in result.diagnostics_public
    assert (context.workspace_dir / "output" / "submission" / "submission.json").is_file()
