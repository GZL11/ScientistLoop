from __future__ import annotations

import json
from pathlib import Path
import shutil

from famou_scientist.loop.facilities.contracts import (
    ArtifactRef,
    EvaluationResult,
    RunResult,
    TaskView,
)
from famou_scientist.loop.harness.runtime import BenchmarkHarness, HarnessConfig
from famou_scientist.loop.plugins import register_adapter


class _TerminalBenchmarkFacility:
    def __init__(self, context):
        self.context = context
        self.rounds = 0

    def task_view(self):
        return TaskView(
            task_id=self.context.task_id,
            public_path=str(self.context.problem_dir),
            instructions=(self.context.problem_dir / "INSTRUCTIONS.md").read_text(),
        )

    def preflight(self, candidate, *, context=None):
        return {"valid": True}

    def run(self, candidate, *, context=None):
        round_no = int((context or {}).get("round") or 0)
        target = self.context.run_dir / "public_artifacts" / f"round_{round_no}"
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate.code_path, target)
        artifact = ArtifactRef.from_path(
            target,
            artifact_id=f"surrogate-{round_no}",
            producer="fake-terminal-benchmark",
        )
        self.rounds += 1
        return RunResult(
            run_id=f"public-{round_no}",
            candidate_id=candidate.candidate_id,
            valid=True,
            artifact_ref=artifact,
        )

    def validate_artifact(self, artifact):
        artifact.verify()
        return {"valid": True}

    def run_public_evaluation(self, artifact):
        value = Path(artifact.storage_path, "solution.txt").read_text()
        return {"valid": value == "fixed", "observed": value}

    def agent_view(self, result, *, source=None):
        return {"valid": result["valid"], "observed": result["observed"]}


class _TerminalBenchmarkAdapter:
    name = "test_terminal_graph_benchmark"

    def create(self, context):
        return _TerminalBenchmarkFacility(context)


class _TerminalEvaluationFacility:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def evaluate(self, request):
        self.calls += 1
        request.artifact_ref.verify()
        value = Path(request.artifact_ref.storage_path, "solution.txt").read_text()
        return EvaluationResult(
            request_id="gt-1",
            attempt_id=request.attempt_id,
            valid=value == "fixed",
            metrics={"reward": float(value == "fixed")},
        )

    def agent_view(self, result, *, source=None):
        raise AssertionError("FinalAudit must not feed the current agent")

    def close(self):
        self.closed = True


class _TerminalEvaluatorAdapter:
    name = "test_terminal_graph_evaluator"
    facility = None

    def create(self, context, transport):
        del context, transport
        self.facility = _TerminalEvaluationFacility()
        return self.facility

    def finalize(self, context, facility, request):
        raise AssertionError("TerminalTask must use evaluate(), not SOTA finalize()")


def test_terminal_harness_isolated_from_sota_loop(tmp_path: Path, monkeypatch):
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, sys",
                "role = os.environ['FAMOU_AGENT_ROLE']",
                "request = json.loads(pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_INPUT']).read_text())",
                "phase = request['metadata']['terminal_phase']",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "if role == 'terminal_solver':",
                "    value = 'fixed' if phase == 'refine' else 'broken'",
                "    (worktree / 'solution.txt').write_text(value, encoding='utf-8')",
                "    (worktree / f'{phase}_argv.json').write_text(json.dumps(sys.argv), encoding='utf-8')",
                "else:",
                "    output = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT'])",
                "    context = request['metadata']['terminal_context']",
                "    if phase == 'diagnose':",
                "        (worktree / 'diagnose_context.json').write_text(json.dumps(context), encoding='utf-8')",
                "    if phase == 'compile_plan':",
                "        result = {",
                "          'schema_version': 1,",
                "          'task_input_hash': context['task_input_hash'],",
                "          'rubrics': [{",
                "            'id': 'R1', 'requirement_ref': 'instructions:1',",
                "            'severity': 'critical',",
                "            'checker': {'kind': 'file', 'spec': 'solution.txt'},",
                "            'pass_criteria': 'solution.txt contains fixed',",
                "            'required_evidence': ['solution.txt'],",
                "          }],",
                "        }",
                "    else:",
                "        valid = context['evidence']['public_evaluation']['valid']",
                "        result = {",
                "          'status': 'passed' if valid else 'repair_required',",
                "          'checks': [{'rubric_id': 'R1', 'status': 'passed' if valid else 'failed'}],",
                "          'repair_instructions': [] if valid else ['write fixed'],",
                "        }",
                "    output.write_text(json.dumps(result), encoding='utf-8')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    problem = tmp_path / "problem"
    problem.mkdir()
    problem.joinpath("INSTRUCTIONS.md").write_text(
        "Create solution.txt containing exactly fixed.\n",
        encoding="utf-8",
    )
    benchmark_adapter = _TerminalBenchmarkAdapter()
    evaluator_adapter = _TerminalEvaluatorAdapter()
    register_adapter("benchmark", benchmark_adapter.name, benchmark_adapter)
    register_adapter("evaluator", evaluator_adapter.name, evaluator_adapter)

    def fail_if_sota_runs(*args, **kwargs):
        raise AssertionError("TerminalTask entered AsyncOrchestrator")

    monkeypatch.setattr(
        "famou_scientist.loop.harness.runtime.AsyncOrchestrator",
        fail_if_sota_runs,
    )
    run_dir = tmp_path / "run"
    workspace = tmp_path / "submission"
    summary = BenchmarkHarness(
        HarnessConfig(
            task_id="terminal-1",
            run_dir=run_dir,
            problem_dir=problem,
            workspace_dir=workspace,
            agent_runtime="opencode",
            agent_graph="terminal_task",
            benchmark_adapter=benchmark_adapter.name,
            evaluator_adapter=evaluator_adapter.name,
            agent_binary=str(fake_bin),
            model="fake-model",
            max_refine_rounds=2,
            max_wall_time_hours=1,
        ),
        evaluator=object(),
    ).run()

    assert summary["status"] == "completed"
    assert summary["agent_graph"] == "terminal_task"
    assert summary["refine_rounds"] == 1
    assert workspace.joinpath("solution.txt").read_text() == "fixed"
    assert evaluator_adapter.facility.calls == 1
    assert evaluator_adapter.facility.closed is True
    solver_worktree = run_dir / "terminal_task_agents" / "branches" / "solver" / "worktree"
    refine_argv = json.loads(solver_worktree.joinpath("refine_argv.json").read_text())
    assert "--continue" in refine_argv
    verifier_worktree = run_dir / "terminal_task_agents" / "branches" / "verifier" / "worktree"
    diagnose_context = json.loads(
        verifier_worktree.joinpath("diagnose_context.json").read_text()
    )
    assert diagnose_context["verifier_plan"]["rubrics"][0]["id"] == "R1"
    assert not (run_dir / "state" / "research_state.json").exists()
    assert not (run_dir / "expbank").exists()


class _GTBudgetBenchmarkFacility(_TerminalBenchmarkFacility):
    """Adds the official candidate-level GT hook used by gt_primary/gt_budget."""

    def __init__(self, context):
        super().__init__(context)
        self.gt_rounds: list[int] = []

    def run_gt_evaluation(self, artifact, *, round_no):
        artifact.verify()
        self.gt_rounds.append(int(round_no))
        value = Path(artifact.storage_path, "solution.txt").read_text()
        passed = value == "fixed"
        return {
            "status": "passed" if passed else "repair_required",
            "verifier": "tbs_gt",
            "reward": float(passed),
            "valid": passed,
            "official_metrics": {"reward": float(passed)},
            "stdout": "PASSED test_solution" if passed else "FAILED test_solution - expected fixed",
            "stderr": "",
            "ctrf": {"results": {"summary": {"tests": 1, "passed": int(passed), "failed": int(not passed)}}},
        }


class _GTBudgetBenchmarkAdapter:
    name = "test_terminal_gt_budget_benchmark"
    facility = None

    def create(self, context):
        self.facility = _GTBudgetBenchmarkFacility(context)
        return self.facility


class _GTBudgetEvaluatorAdapter(_TerminalEvaluatorAdapter):
    name = "test_terminal_gt_budget_evaluator"


_GT_MODE_FAKE_SOLVER = "\n".join(
    [
        "#!/usr/bin/env python3",
        "import json, os, pathlib, sys",
        "request = json.loads(pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_INPUT']).read_text())",
        "phase = request['metadata']['terminal_phase']",
        "context = request['metadata']['terminal_context']",
        "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
        "(worktree / f'{phase}_context.json').write_text(json.dumps(context), encoding='utf-8')",
        "if phase == 'solve':",
        "    (worktree / 'solution.txt').write_text('broken', encoding='utf-8')",
        "    if context.get('evaluation_policy') == 'on_request_budget':",
        "        pathlib.Path(context['gt_request_file']).write_text(",
        "            json.dumps({'request_official_gt': True, 'reason': 'public checks done'}), encoding='utf-8')",
        "else:",
        "    (worktree / 'solution.txt').write_text('fixed', encoding='utf-8')",
    ]
) + "\n"


def _gt_mode_problem(tmp_path: Path) -> Path:
    problem = tmp_path / "problem"
    problem.mkdir()
    problem.joinpath("INSTRUCTIONS.md").write_text(
        "Create solution.txt containing exactly fixed.\n", encoding="utf-8"
    )
    return problem


def _gt_mode_fake_bin(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(_GT_MODE_FAKE_SOLVER, encoding="utf-8")
    fake_bin.chmod(0o755)
    return fake_bin


# The plugin registry is process-wide and rejects a second, different provider
# under the same name, so both GT-mode tests share these singletons; create()
# hands out a fresh facility per harness run.
_GT_MODE_BENCHMARK_ADAPTER = _GTBudgetBenchmarkAdapter()
_GT_MODE_EVALUATOR_ADAPTER = _GTBudgetEvaluatorAdapter()


def _register_gt_mode_adapters():
    register_adapter("benchmark", _GT_MODE_BENCHMARK_ADAPTER.name, _GT_MODE_BENCHMARK_ADAPTER)
    register_adapter("evaluator", _GT_MODE_EVALUATOR_ADAPTER.name, _GT_MODE_EVALUATOR_ADAPTER)
    return _GT_MODE_BENCHMARK_ADAPTER, _GT_MODE_EVALUATOR_ADAPTER


def test_terminal_harness_gt_budget_grants_requested_gt_then_final_audit_once(tmp_path: Path):
    benchmark_adapter, evaluator_adapter = _register_gt_mode_adapters()
    run_dir = tmp_path / "run"
    workspace = tmp_path / "submission"
    summary = BenchmarkHarness(
        HarnessConfig(
            task_id="terminal-gt-budget",
            run_dir=run_dir,
            problem_dir=_gt_mode_problem(tmp_path),
            workspace_dir=workspace,
            agent_runtime="opencode",
            agent_graph="terminal_task",
            benchmark_adapter=benchmark_adapter.name,
            evaluator_adapter=evaluator_adapter.name,
            agent_binary=str(_gt_mode_fake_bin(tmp_path)),
            model="fake-model",
            candidate_verifier_mode="gt_budget",
            official_gt_budget=1,
            max_wall_time_hours=1,
        ),
        evaluator=object(),
    ).run()

    assert summary["status"] == "completed", summary
    assert summary["candidate_verifier_mode"] == "gt_budget"
    assert summary["official_gt_budget"] == 1
    assert summary["official_gt_used"] == 1
    assert summary["refine_rounds"] == 1
    assert [entry["granted"] for entry in summary["official_gt_requests"]] == [True]
    assert summary["official_gt_requests"][0]["reason"] == "public checks done"
    # Exactly one candidate-level GT (round 0) and exactly one FinalAudit.
    assert benchmark_adapter.facility.gt_rounds == [0]
    assert evaluator_adapter.facility.calls == 1
    assert workspace.joinpath("solution.txt").read_text() == "fixed"
    # No VerifierAgent turn ran in this mode (the branch directory is pre-created
    # by the harness but never activated).
    assert summary["verifier_session_ref"] is None
    assert summary["verifier_bundle_ref"] is None
    solver_worktree = run_dir / "terminal_task_agents" / "branches" / "solver" / "worktree"
    solve_context = json.loads(solver_worktree.joinpath("solve_context.json").read_text())
    assert solve_context["evaluation_policy"] == "on_request_budget"
    assert solve_context["official_gt_evaluations_remaining"] == 1
    refine_context = json.loads(solver_worktree.joinpath("refine_context.json").read_text())
    assert refine_context["official_gt_evaluations_remaining"] == 0
    assert refine_context["surrogate_report"]["official_gt_consumed"] is True
    assert "expected fixed" in refine_context["surrogate_report"]["gt_evaluation"]["stdout"]


def test_terminal_harness_gt_final_only_audits_exported_candidate_not_host_worktree(tmp_path: Path):
    benchmark_adapter, evaluator_adapter = _register_gt_mode_adapters()
    run_dir = tmp_path / "run"
    workspace = tmp_path / "submission"
    summary = BenchmarkHarness(
        HarnessConfig(
            task_id="terminal-gt-final-only",
            run_dir=run_dir,
            problem_dir=_gt_mode_problem(tmp_path),
            workspace_dir=workspace,
            agent_runtime="opencode",
            agent_graph="terminal_task",
            benchmark_adapter=benchmark_adapter.name,
            evaluator_adapter=evaluator_adapter.name,
            agent_binary=str(_gt_mode_fake_bin(tmp_path)),
            model="fake-model",
            candidate_verifier_mode="gt_final_only",
            max_wall_time_hours=1,
        ),
        evaluator=object(),
    ).run()

    # The fake Solver writes "broken" in the solve phase and never gets a refine
    # turn in this mode, so the single FinalAudit must fail on the exported
    # candidate rather than on a missing file.
    assert summary["status"] == "failed"
    assert summary["outcome"] == "final_audit_failed"
    assert summary["refine_rounds"] == 0
    assert summary["official_gt_used"] == 0
    assert benchmark_adapter.facility.gt_rounds == []
    assert evaluator_adapter.facility.calls == 1
    request = json.loads((run_dir / "controller" / "final_audit" / "request.json").read_text())
    assert request["artifact_ref"]["artifact_id"] == "surrogate-0"
    assert Path(request["artifact_ref"]["storage_path"], "solution.txt").read_text() == "broken"
