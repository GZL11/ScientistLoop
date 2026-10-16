from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from famou_scientist.loop.domain.graph import GraphContext, NodeInvocation
from famou_scientist.loop.execution.agent_turn import AgentTurnResult
from famou_scientist.loop.execution.sandbox import LocalSandbox
from famou_scientist.loop.execution.workspace import AgentWorkspace
from famou_scientist.loop.facilities.contracts import (
    ArtifactRef,
    EvaluationResult,
    RunResult,
    TaskView,
)
from famou_scientist.loop.graphs.terminal_task.nodes import (
    FinalAuditRunner,
    FreezeWorkspaceRunner,
    SolverTurnRunner,
    SurrogateVerifyRunner,
    VerifierPlanRunner,
    _materialize_solver_runtime_view,
    _verifier_candidate_root,
    _resolve_verifier_task_root,
)
from famou_scientist.loop.graphs.terminal_task.verifier import (
    VerifierBundleStore,
    VerifierPlanStore,
    validate_verifier_plan,
    validate_verifier_source,
)


def _plan(task_hash: str = "task-hash") -> dict:
    return {
        "schema_version": 1,
        "task_input_hash": task_hash,
        "rubrics": [
            {
                "id": "R1",
                "requirement_ref": "instructions:1",
                "severity": "critical",
                "checker": {"kind": "file", "path": "solution.txt"},
                "pass_criteria": "file exists",
                "required_evidence": ["solution.txt"],
            }
        ],
    }


def test_verifier_plan_is_validated_and_cannot_drift(tmp_path: Path):
    store = VerifierPlanStore(tmp_path)
    path = store.freeze(_plan(), task_input_hash="task-hash")

    assert path.is_file()
    assert store.load()["rubrics"][0]["id"] == "R1"
    assert store.freeze(_plan(), task_input_hash="task-hash") == path

    changed = _plan()
    changed["rubrics"][0]["pass_criteria"] = "different"
    with pytest.raises(ValueError, match="已冻结"):
        store.freeze(changed, task_input_hash="task-hash")
    with pytest.raises(ValueError, match="task_input_hash"):
        validate_verifier_plan(_plan("wrong"), expected_task_input_hash="expected")


def test_proxy_runtime_view_matches_dockerfile_app_contents(tmp_path: Path):
    environment = tmp_path / "environment"
    environment.mkdir()
    environment.joinpath("study").mkdir()
    environment.joinpath("study/image.dcm").write_text("dicom", encoding="utf-8")
    environment.joinpath("vocabularies.json").write_text("{}\n", encoding="utf-8")
    environment.joinpath("study_checksums.sha256").write_text("build only\n", encoding="utf-8")
    environment.joinpath("Dockerfile").write_text(
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY study/ /app/study/\n"
        "COPY vocabularies.json /app/vocabularies.json\n"
        "COPY study_checksums.sha256 /tmp/study_checksums.sha256\n",
        encoding="utf-8",
    )
    runtime_app = tmp_path / "runtime" / "app"

    result = _materialize_solver_runtime_view(environment, runtime_app)

    assert result == runtime_app.resolve()
    assert runtime_app.joinpath("study/image.dcm").read_text(encoding="utf-8") == "dicom"
    assert runtime_app.joinpath("vocabularies.json").is_file()
    assert not runtime_app.joinpath("Dockerfile").exists()
    assert not runtime_app.joinpath("study_checksums.sha256").exists()


def _verifier_source(root: Path, *, dangerous: bool = False) -> Path:
    root.mkdir(exist_ok=True)
    verifier = """
from pathlib import Path

def describe():
    return [{"requirement_ref": "instructions:1", "severity": "critical", "pass_criteria": "ok"}]

def verify(candidate_root: Path, task_root: Path, output_dir: Path):
    return {"checks": [], "status": "passed"}
"""
    if dangerous:
        verifier = "import os\nos.system('echo unsafe')\n" + verifier
    (root / "verifier.py").write_text(verifier, encoding="utf-8")
    (root / "verifier_spec.md").write_text("# Checks\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_verifier.py").write_text(
        "def test_smoke():\n    assert True\n", encoding="utf-8"
    )
    (root / ".verifier_self_test.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "case_count": 1,
                "exit_code": 0,
                "command": "pytest -q tests/test_verifier.py",
                "log_ref": "verifier_self_test.log",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_verifier_source_static_check_and_bundle_freeze(tmp_path: Path):
    source = _verifier_source(tmp_path / "source")
    report = validate_verifier_source(source)
    assert report["status"] == "passed"
    assert report["self_test"]["status"] == "agent_reported_passed"

    store = VerifierBundleStore(tmp_path / "run")
    bundle, manifest = store.freeze_source(
        source,
        task_id="task-1",
        task_input_hash="hash-1",
        verifier_agent_session_ref="session-1",
    )
    assert bundle.joinpath("verifier.py").is_file()
    assert manifest["frozen"] is True
    assert manifest["self_test"]["case_count"] == 1
    assert not (bundle / "verifier.py").stat().st_mode & 0o222
    assert store.load_manifest()["verifier_bundle_hash"].startswith("sha256:")

    changed = _verifier_source(tmp_path / "changed")
    (changed / "verifier_spec.md").write_text("# Changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="已冻结"):
        store.freeze_source(changed, task_id="task-1", task_input_hash="hash-1")


def test_verifier_bundle_freezes_top_level_helper_modules(tmp_path: Path):
    source = _verifier_source(tmp_path / "source")
    (source / "dicom_mini.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = VerifierBundleStore(tmp_path / "run")
    bundle, _ = store.freeze_source(
        source,
        task_id="task-1",
        task_input_hash="hash-1",
    )
    assert bundle.joinpath("dicom_mini.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_verifier_source_rejects_dangerous_code(tmp_path: Path):
    report = validate_verifier_source(_verifier_source(tmp_path / "source", dangerous=True))
    assert report["status"] == "failed"
    assert any("禁止调用 .system()" in item for item in report["errors"])


def test_verifier_self_tests_may_use_isolation_helpers(tmp_path: Path):
    source = _verifier_source(tmp_path / "source")
    (source / "tests" / "test_verifier.py").write_text(
        "import subprocess\n"
        "def test_dynamic_fixture():\n"
        "    __import__('json')\n"
        "    assert subprocess.run(['true']).returncode == 0\n",
        encoding="utf-8",
    )

    report = validate_verifier_source(source)

    assert report["status"] == "passed"


def test_verifier_compiler_runner_freezes_agent_source(tmp_path: Path):
    source = _verifier_source(tmp_path / "verifier-worktree")
    workspace = AgentWorkspace.create(tmp_path / "agents", "verifier")
    for path in source.iterdir():
        target = workspace.worktree / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)

    class _Adapter:
        def run(self, request):
            del request
            return AgentTurnResult(status="succeeded", phase="compile_plan", session_ref="s1")

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    runner = VerifierPlanRunner(
        _Adapter(),
        workspace,
        LocalSandbox(sandbox_root),
        "instructions",
        "task-hash",
    )
    context = GraphContext("run-1", tmp_path / "run", workspace.worktree, "task-1")
    result = runner(NodeInvocation("verifier_plan_0", "verifier_plan", {}), context)
    assert result.status == "succeeded"
    assert result.output["bundle_ref"] == "controller/verifier/bundle"
    assert (context.run_dir / "controller/verifier/manifest.json").is_file()


def test_verifier_compiler_probes_controller_runtime_before_freeze(tmp_path: Path):
    """A real helper/runtime failure is sent back to VerifierAgent first."""

    source = _verifier_source(tmp_path / "verifier-worktree")
    (source / "verifier.py").write_text(
        "import verifier_study as vs\n" + (source / "verifier.py").read_text(),
        encoding="utf-8",
    )
    workspace = AgentWorkspace.create(tmp_path / "agents", "verifier")
    for path in source.iterdir():
        target = workspace.worktree / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
    task_root = tmp_path / "task"
    (task_root / "study").mkdir(parents=True)
    phases: list[str] = []

    class _Adapter:
        def run(self, request):
            phases.append(request.phase)
            helper = workspace.worktree / "verifier_study.py"
            if request.phase == "compile_plan":
                helper.write_text(
                    "class Study:\n"
                    "    def __init__(self, root): raise RuntimeError('jpeg codec mismatch')\n",
                    encoding="utf-8",
                )
            else:
                helper.write_text(
                    "class _Series:\n"
                    "    instances = [object()]\n"
                    "    def pixels(self, inst): return [0.0]\n"
                    "class Study:\n"
                    "    def __init__(self, root): self.root = root\n"
                    "    diagnostic = [_Series()]\n",
                    encoding="utf-8",
                )
            return AgentTurnResult(
                status="succeeded",
                phase=request.phase,
                session_ref="same-verifier-session",
            )

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    runner = VerifierPlanRunner(
        _Adapter(),
        workspace,
        LocalSandbox(sandbox_root),
        "instructions",
        "task-hash",
        task_root=task_root,
    )
    context = GraphContext("run-1", tmp_path / "run", workspace.worktree, "task-1")
    result = runner(NodeInvocation("verifier_plan_0", "verifier_plan", {}), context)

    assert result.status == "succeeded"
    assert phases == ["compile_plan", "repair_compile"]
    assert "jpeg codec mismatch" in " ".join(
        item["errors"][0] for item in result.output["compile_attempts"] if item["errors"]
    )
    manifest = json.loads(
        (context.run_dir / "controller/verifier/manifest.json").read_text()
    )
    assert manifest["controller_runtime_check"]["status"] == "passed"


def test_verifier_compiler_accepts_valid_bundle_when_result_protocol_fails(tmp_path: Path):
    """源码 bundle 是编译器产物的权威出口，不被空 JSON wrapper 误判阻断。"""

    source = _verifier_source(tmp_path / "verifier-worktree")
    workspace = AgentWorkspace.create(tmp_path / "agents", "verifier")
    for path in source.iterdir():
        target = workspace.worktree / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)

    class _Adapter:
        def run(self, request):
            del request
            return AgentTurnResult(
                status="failed",
                phase="compile_plan",
                error="empty legacy result JSON",
            )

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    runner = VerifierPlanRunner(
        _Adapter(),
        workspace,
        LocalSandbox(sandbox_root),
        "instructions",
        "task-hash",
    )
    context = GraphContext("run-1", tmp_path / "run", workspace.worktree, "task-1")
    result = runner(NodeInvocation("verifier_plan_0", "verifier_plan", {}), context)
    assert result.status == "succeeded"
    assert result.output["bundle_ref"] == "controller/verifier/bundle"


def test_verifier_compiler_resumes_same_session_after_static_failure(tmp_path: Path):
    workspace = AgentWorkspace.create(tmp_path / "agents", "verifier")
    phases: list[str] = []
    contexts: list[dict] = []

    class _Adapter:
        def run(self, request):
            phases.append(request.phase)
            contexts.append(dict(request.context))
            if request.phase == "compile_plan":
                _verifier_source(workspace.worktree)
                verifier = workspace.worktree / "verifier.py"
                verifier.write_text(
                    "import subprocess\n" + verifier.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            else:
                verifier = workspace.worktree / "verifier.py"
                verifier.write_text(
                    verifier.read_text(encoding="utf-8").replace("import subprocess\n", ""),
                    encoding="utf-8",
                )
            return AgentTurnResult(
                status="succeeded",
                phase=request.phase,
                session_ref="same-verifier-session",
            )

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    runner = VerifierPlanRunner(
        _Adapter(),
        workspace,
        LocalSandbox(sandbox_root),
        "instructions",
        "task-hash",
    )
    context = GraphContext("run-1", tmp_path / "run", workspace.worktree, "task-1")
    result = runner(
        NodeInvocation(
            "verifier_plan_0",
            "verifier_plan",
            {"session_key": "terminal_verifier"},
        ),
        context,
    )

    assert result.status == "succeeded"
    assert phases == ["compile_plan", "repair_compile"]
    assert "禁止导入 subprocess" in " ".join(contexts[1]["compile_errors"])
    assert result.output["compile_repair_count"] == 1
    assert [item["status"] for item in result.output["compile_attempts"]] == [
        "failed",
        "succeeded",
    ]
    assert result.output["session_ref"] == "same-verifier-session"


def test_verifier_compiler_defaults_to_five_repair_attempts(tmp_path: Path):
    workspace = AgentWorkspace.create(tmp_path / "agents", "verifier")
    phases: list[str] = []

    class _Adapter:
        def run(self, request):
            phases.append(request.phase)
            _verifier_source(workspace.worktree)
            verifier = workspace.worktree / "verifier.py"
            verifier.write_text(
                "import subprocess\n" + verifier.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return AgentTurnResult(
                status="succeeded",
                phase=request.phase,
                session_ref="same-verifier-session",
            )

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    runner = VerifierPlanRunner(
        _Adapter(),
        workspace,
        LocalSandbox(sandbox_root),
        "instructions",
        "task-hash",
    )
    context = GraphContext("run-1", tmp_path / "run", workspace.worktree, "task-1")
    result = runner(NodeInvocation("verifier_plan_0", "verifier_plan", {}), context)

    assert result.status == "failed"
    assert phases == ["compile_plan", *("repair_compile" for _ in range(5))]
    assert len(result.output["compile_attempts"]) == 6
    assert {item["session_ref"] for item in result.output["compile_attempts"]} == {
        "same-verifier-session"
    }


class _Benchmark:
    def __init__(self, root: Path):
        self.root = root

    def task_view(self):
        return TaskView(task_id="task")

    def preflight(self, candidate, *, context=None):
        return {
            "valid": True,
            "round": (context or {}).get("round"),
            "trusted_path": "/trusted/must-not-leak",
        }

    def run(self, candidate, *, context=None):
        round_no = int((context or {}).get("round") or 0)
        artifact_path = self.root / f"artifact_{round_no}"
        if artifact_path.exists():
            shutil.rmtree(artifact_path)
        shutil.copytree(candidate.code_path, artifact_path)
        artifact = ArtifactRef.from_path(
            artifact_path,
            artifact_id=f"artifact-{round_no}",
            producer="fake-benchmark",
        )
        return RunResult(
            run_id=f"run-{round_no}",
            candidate_id=candidate.candidate_id,
            valid=True,
            artifact_ref=artifact,
        )

    def validate_artifact(self, artifact):
        artifact.verify()
        return {"valid": True}

    def run_public_evaluation(self, artifact):
        passed = (Path(artifact.storage_path) / "solution.txt").read_text() == "fixed"
        return {"valid": passed, "message": "ok" if passed else "needs repair"}

    def agent_view(self, result, *, source=None):
        return {"valid": result["valid"], "message": result["message"], "source": source}


def test_surrogate_verify_uses_frozen_plan_and_public_facility(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("broken")
    VerifierPlanStore(run_dir).freeze(_plan(), task_input_hash="task-hash")
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    runner = SurrogateVerifyRunner(_Benchmark(tmp_path / "bench"), workspace)

    first = runner(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0}),
        context,
    )
    workspace.worktree.joinpath("solution.txt").write_text("fixed")
    second = runner(
        NodeInvocation("surrogate_verify_1", "surrogate_verify", {"round": 1}),
        context,
    )

    assert first.output["status"] == "repair_required"
    assert second.output["status"] == "passed"
    first_report = json.loads((run_dir / first.output["report_ref"]).read_text())
    assert first_report["checks"][2]["details"]["message"] == "needs repair"
    assert "/trusted/must-not-leak" not in json.dumps(first_report)
    assert first_report["agent_workspace_path"] == ".famou/surrogate/round_0.json"
    assert all(
        item["evidence_refs"] == [".famou/surrogate/round_0.json"]
        for item in first_report["checks"]
    )
    solver_report = json.loads(
        workspace.worktree.joinpath(first_report["agent_workspace_path"]).read_text()
    )
    assert solver_report == first_report
    system_report = json.loads(
        (run_dir / first.output["system_report_ref"]).read_text()
    )
    assert system_report["checks"][0]["details"]["trusted_path"].startswith("/trusted")


def test_gt_primary_preserves_complete_verifier_feedback_for_solver(tmp_path: Path):
    class _GTBenchmark(_Benchmark):
        def run_gt_evaluation(self, artifact, *, round_no):
            artifact.verify()
            assert round_no == 0
            return {
                "status": "repair_required",
                "verifier": "tbs_gt",
                "reward": 0.0,
                "valid": False,
                "official_metrics": {"reward": 0.0, "fmjob_returncode": 1},
                "stdout": "AssertionError: target_31 expected 0.259452, got 0.129726",
                "stderr": "pytest warning",
                "ctrf": {
                    "results": {"summary": {"tests": 8, "passed": 6, "failed": 2}}
                },
            }

    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("candidate")
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    result = SurrogateVerifyRunner(
        _GTBenchmark(tmp_path / "bench"),
        workspace,
        verifier_mode="gt_primary",
    )(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0}),
        context,
    )

    agent_report = json.loads((run_dir / result.output["report_ref"]).read_text())
    feedback = agent_report["gt_evaluation"]
    assert "target_31" in feedback["stdout"]
    assert feedback["stderr"] == "pytest warning"
    assert feedback["ctrf"]["results"]["summary"] == {
        "tests": 8,
        "passed": 6,
        "failed": 2,
    }
    assert feedback["official_metrics"]["fmjob_returncode"] == 1
    assert agent_report["repair_instructions"]


def test_surrogate_verify_accepts_boolean_passed_protocol_from_frozen_verifier(
    tmp_path: Path,
):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("fixed")
    bundle = run_dir / "controller" / "verifier" / "bundle"
    bundle.mkdir(parents=True)
    bundle.joinpath("verifier.py").write_text(
        """
def verify(candidate_root, task_root, output_dir):
    return {
        "passed": True,
        "checks": [
            {"id": "output_exists", "passed": True, "summary": "present"},
            {"id": "shape", "status": "passed", "summary": "valid"},
        ],
    }
""",
        encoding="utf-8",
    )
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    result = SurrogateVerifyRunner(_Benchmark(tmp_path / "bench"), workspace)(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0}),
        context,
    )

    assert result.output["status"] == "passed"
    report = json.loads((run_dir / result.output["system_report_ref"]).read_text())
    assert [item["status"] for item in report["checks"][-2:]] == ["passed", "passed"]


def test_surrogate_verify_allows_nonblocking_unknown_checks_when_verifier_passes(
    tmp_path: Path,
):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("fixed")
    bundle = run_dir / "controller" / "verifier" / "bundle"
    bundle.mkdir(parents=True)
    bundle.joinpath("verifier.py").write_text(
        """
def verify(candidate_root, task_root, output_dir):
    return {
        "status": "passed",
        "checks": [
            {"id": "public_value_proxy", "status": "passed"},
            {"id": "hidden_reference", "status": "unknown", "coverage": "uncovered"},
        ],
    }
""",
        encoding="utf-8",
    )
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    result = SurrogateVerifyRunner(_Benchmark(tmp_path / "bench"), workspace)(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0}),
        context,
    )

    assert result.output["status"] == "passed"
    report = json.loads((run_dir / result.output["system_report_ref"]).read_text())
    assert report["checks"][-1]["status"] == "unknown"


def test_frozen_verifier_side_effects_do_not_mutate_artifact_snapshot(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("fixed")
    workspace.worktree.joinpath("solution.py").write_text("VALUE = 1\n")
    bundle = run_dir / "controller" / "verifier" / "bundle"
    bundle.mkdir(parents=True)
    bundle.joinpath("verifier.py").write_text(
        """
from pathlib import Path

def verify(candidate_root, task_root, output_dir):
    # A real verifier can trigger __pycache__; this explicit write models any
    # runtime side effect and must stay inside the disposable evaluation copy.
    Path(candidate_root, "runtime.tmp").write_text("generated")
    return {"status": "passed", "checks": [{"id": "output", "status": "passed"}]}
""",
        encoding="utf-8",
    )
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    result = SurrogateVerifyRunner(_Benchmark(tmp_path / "bench"), workspace)(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0}),
        context,
    )

    assert result.output["status"] == "passed"
    artifact = ArtifactRef.from_dict(result.output["artifact_ref"])
    artifact.verify()
    assert not Path(artifact.storage_path, "runtime.tmp").exists()


def test_generated_verifier_root_preserves_declared_container_prefix(tmp_path: Path):
    payload = tmp_path / "payload"
    payload.joinpath("root/results").mkdir(parents=True)
    payload.joinpath("root/results/output.csv").write_text("ok", encoding="utf-8")
    artifact = ArtifactRef.from_path(
        payload,
        artifact_id="artifact",
        metadata={"artifact_paths": ["/root/results/output.csv"]},
    )
    assert _verifier_candidate_root(artifact) == (payload / "root").resolve()


def test_surrogate_verify_reports_missing_declared_artifact_for_solver_repair(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")

    class _MissingArtifactBenchmark(_Benchmark):
        def run(self, candidate, *, context=None):
            raise FileNotFoundError("candidate 缺少声明 artifact /app/results/output.csv")

    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    result = SurrogateVerifyRunner(_MissingArtifactBenchmark(tmp_path / "bench"), workspace)(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0}),
        context,
    )

    assert result.output["status"] == "repair_required"
    report = json.loads((run_dir / result.output["system_report_ref"]).read_text())
    assert report["checks"][0]["id"] == "artifact_export"
    assert report["repair_instructions"]


def test_verifier_task_root_uses_public_environment_data(tmp_path: Path):
    (tmp_path / "environment" / "data").mkdir(parents=True)
    (tmp_path / "environment" / "data" / "metadata.json").write_text("{}")
    assert _resolve_verifier_task_root(tmp_path) == (tmp_path / "environment" / "data").resolve()


def test_verifier_task_root_uses_direct_public_environment_layout(tmp_path: Path):
    environment = tmp_path / "environment"
    (environment / "study").mkdir(parents=True)
    (environment / "vocabularies.json").write_text("{}")
    (environment / "icd10_candidates.tsv").write_text("icd10_code\tdescription\n")
    assert _resolve_verifier_task_root(tmp_path) == environment.resolve()


def test_verifier_task_root_uses_tbs_environment_data_api_layout(tmp_path: Path):
    """TBS public api/instances data lives below environment/data."""

    data_root = tmp_path / "environment" / "data"
    (data_root / "api").mkdir(parents=True)
    (data_root / "instances").mkdir(parents=True)
    assert _resolve_verifier_task_root(tmp_path) == data_root.resolve()


class _Evaluator:
    def __init__(self):
        self.calls = 0
        self.requests = []

    def evaluate(self, request):
        self.calls += 1
        self.requests.append(request)
        request.artifact_ref.verify()
        return EvaluationResult(
            request_id="official-1",
            attempt_id=request.attempt_id,
            valid=True,
            metrics={"reward": 1.0},
        )

    def agent_view(self, result, *, source=None):
        raise AssertionError("GT must not be sent to the current agent")

    def close(self):
        pass


def test_freeze_workspace_and_final_audit_are_immutable_and_idempotent(tmp_path: Path):
    run_dir = tmp_path / "run"
    worktree = run_dir / "workspace"
    worktree.mkdir(parents=True)
    worktree.joinpath("solution.txt").write_text("fixed")
    context = GraphContext("run-1", run_dir, worktree, "task-1")
    frozen = FreezeWorkspaceRunner()(
        NodeInvocation("freeze_workspace_0", "freeze_workspace"),
        context,
    )
    frozen_path = Path(frozen.output["workspace_ref"]["storage_path"])
    assert frozen_path.joinpath("solution.txt").read_text() == "fixed"
    assert frozen_path.stat().st_mode & 0o222 == 0

    evaluator = _Evaluator()
    runner = FinalAuditRunner(evaluator)
    invocation = NodeInvocation(
        "final_audit_0",
        "final_audit",
        {"workspace_ref": frozen.output["workspace_ref"]},
    )
    first = runner(invocation, context)
    second = runner(invocation, context)

    assert first.output["status"] == second.output["status"] == "passed"
    assert evaluator.calls == 1


def test_final_audit_records_proxy_gt_comparison(tmp_path: Path):
    run_dir = tmp_path / "run"
    worktree = run_dir / "workspace"
    worktree.mkdir(parents=True)
    worktree.joinpath("solution.txt").write_text("candidate")
    context = GraphContext("run-1", run_dir, worktree, "task-1")
    frozen = FreezeWorkspaceRunner()(
        NodeInvocation("freeze_workspace_0", "freeze_workspace"), context
    )
    proxy_report = run_dir / "agent_control" / "surrogate" / "round_0.json"
    proxy_report.parent.mkdir(parents=True)
    proxy_report.write_text(
        json.dumps(
            {
                "status": "passed",
                "checks": [
                    {"id": "schema", "status": "passed"},
                    {"id": "quality", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    class _GtEvaluator(_Evaluator):
        def evaluate(self, request):
            self.calls += 1
            self.requests.append(request)
            request.artifact_ref.verify()
            return EvaluationResult(
                request_id="official-1",
                attempt_id=request.attempt_id,
                valid=False,
                metrics={"reward": 0.0},
                stdout="1 failed, 16 passed",
                metadata={
                    "ctrf": {
                        "results": {"summary": {"passed": 12, "failed": 1}}
                    }
                },
            )

    result = FinalAuditRunner(_GtEvaluator())(
        NodeInvocation(
            "final_audit_0",
            "final_audit",
            {
                "workspace_ref": frozen.output["workspace_ref"],
                "proxy_report_ref": "agent_control/surrogate/round_0.json",
                "candidate_verifier_mode": "proxy",
            },
        ),
        context,
    )

    assert result.output["status"] == "failed"
    comparison = json.loads(
        (run_dir / "controller" / "final_audit" / "proxy_gt_comparison.json").read_text()
    )
    assert comparison["proxy"]["checks_passed"] == 2
    assert comparison["gt"]["checks_passed"] == 16
    assert comparison["gt"]["checks_failed"] == 1
    assert comparison["gt"]["checks_count_source"] == "pytest_stdout"
    assert comparison["difference"]["status_diff"] is True


def test_final_audit_repairs_missing_proxy_comparison_for_existing_gt_result(
    tmp_path: Path,
):
    run_dir = tmp_path / "run"
    worktree = run_dir / "workspace"
    worktree.mkdir(parents=True)
    worktree.joinpath("solution.txt").write_text("candidate")
    context = GraphContext("run-1", run_dir, worktree, "task-1")
    frozen = FreezeWorkspaceRunner()(
        NodeInvocation("freeze_workspace_0", "freeze_workspace"), context
    )
    proxy_report = run_dir / "controller" / "surrogate" / "round_0.json"
    proxy_report.parent.mkdir(parents=True)
    proxy_report.write_text(
        json.dumps({"status": "passed", "checks": [{"status": "passed"}]}),
        encoding="utf-8",
    )
    final_audit = run_dir / "controller" / "final_audit"
    final_audit.mkdir(parents=True)
    (final_audit / "result.json").write_text(
        json.dumps(
            {
                "valid": False,
                "official_metrics": {"reward": 0.0},
                "stdout": "1 failed, 2 passed",
            }
        ),
        encoding="utf-8",
    )

    result = FinalAuditRunner(_Evaluator())(
        NodeInvocation(
            "final_audit_0",
            "final_audit",
            {
                "workspace_ref": frozen.output["workspace_ref"],
                "proxy_report_ref": "controller/surrogate/round_0.json",
                "candidate_verifier_mode": "proxy",
            },
        ),
        context,
    )

    assert result.output["status"] == "failed"
    persisted = json.loads((final_audit / "result.json").read_text(encoding="utf-8"))
    assert persisted["proxy_gt_comparison_ref"] == (
        "controller/final_audit/proxy_gt_comparison.json"
    )
    comparison = json.loads(
        (final_audit / "proxy_gt_comparison.json").read_text(encoding="utf-8")
    )
    assert comparison["proxy"]["checks_passed"] == 1
    assert comparison["gt"]["checks_passed"] == 2
    assert comparison["gt"]["checks_failed"] == 1


def test_final_audit_prefers_latest_container_artifact_even_when_partial(tmp_path: Path):
    run_dir = tmp_path / "run"
    worktree = run_dir / "workspace"
    worktree.mkdir(parents=True)
    worktree.joinpath("notes.txt").write_text("workspace only", encoding="utf-8")
    context = GraphContext("run-1", run_dir, worktree, "task-1")
    frozen = FreezeWorkspaceRunner()(
        NodeInvocation("freeze_workspace_0", "freeze_workspace"),
        context,
    )
    payload = run_dir / "artifacts" / "round_5" / "payload"
    payload.joinpath("app").mkdir(parents=True)
    payload.joinpath("app/plans.json").write_text("{}\n", encoding="utf-8")
    candidate = ArtifactRef.from_path(
        payload,
        artifact_id="task-1:surrogate:5",
        kind="harbor_submission_artifacts",
        metadata={
            "artifact_paths": [
                "/app/plans.json",
                "/app/skills.py",
            ]
        },
    )
    evaluator = _Evaluator()

    result = FinalAuditRunner(evaluator)(
        NodeInvocation(
            "final_audit_0",
            "final_audit",
            {
                "workspace_ref": frozen.output["workspace_ref"],
                "candidate_artifact_ref": candidate.to_dict(),
            },
        ),
        context,
    )

    assert result.output["status"] == "passed"
    assert evaluator.requests[0].artifact_ref.storage_path == str(payload.resolve())


def test_freeze_workspace_skips_symlink_without_following(tmp_path: Path):
    run_dir = tmp_path / "run"
    worktree = run_dir / "workspace"
    worktree.mkdir(parents=True)
    worktree.joinpath("kept.txt").write_text("ok")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    worktree.joinpath("leak").symlink_to(outside)
    context = GraphContext("run-1", run_dir, worktree, "task-1")

    result = FreezeWorkspaceRunner()(
        NodeInvocation("freeze_workspace_0", "freeze_workspace"),
        context,
    )

    frozen = run_dir / "artifacts" / "final_workspace"
    assert result.status == "succeeded"
    assert (frozen / "kept.txt").read_text() == "ok"
    # Solver scratch symlinks must not abort the run, but they are never
    # followed: the target content does not leak into the frozen snapshot.
    assert not (frozen / "leak").exists() and not (frozen / "leak").is_symlink()
    assert result.output["workspace_ref"]["metadata"]["skipped_symlinks"] == [str(worktree / "leak")]


def test_solver_timeout_is_a_controlled_turn_end(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")

    class TimedOutTurn:
        def run(self, request):
            return AgentTurnResult(
                status="failed",
                phase=request.phase,
                session_ref="solver-session",
                error="turn deadline reached",
                failure={
                    "error_code": "agent_timeout_before_submit",
                    "timed_out": True,
                },
            )

    result = SolverTurnRunner(
        TimedOutTurn(),
        workspace,
        LocalSandbox(workspace.root),
        "solve",
    )(
        NodeInvocation(
            "solver_turn_0",
            "agent_turn",
            {"phase": "solve", "turn_timeout_sec": 0.1},
        ),
        GraphContext("run-1", run_dir, workspace.worktree, "task-1"),
    )

    assert result.status == "succeeded"
    assert result.error is None
    assert result.output["turn_status"] == "timed_out"
    assert result.output["termination_reason"] == "agent_timeout_before_submit"


def test_solver_receives_single_final_gt_budget_in_public_context(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    captured = {}

    class CapturingTurn:
        def run(self, request):
            captured.update(request.context)
            return AgentTurnResult(status="succeeded", phase=request.phase)

    result = SolverTurnRunner(
        CapturingTurn(),
        workspace,
        LocalSandbox(workspace.root),
        "solve",
    )(
        NodeInvocation(
            "solver_turn_0",
            "agent_turn",
            {
                "phase": "solve",
                "gt_evaluation_policy": "final_only_once",
                "official_gt_evaluations_allowed": 1,
                "evaluation_policy_note": "官方 GT 仅在最终审计调用一次。",
            },
        ),
        GraphContext("run-1", run_dir, workspace.worktree, "task-1"),
    )

    assert result.status == "succeeded"
    assert captured["evaluation_policy"] == "final_only_once"
    assert captured["official_gt_evaluations_allowed"] == 1
    assert captured["evaluation_policy_note"] == "官方 GT 仅在最终审计调用一次。"


class _GTCountingBenchmark(_Benchmark):
    """Fake facility that records official GT calls."""

    def __init__(self, root: Path, *, status: str = "repair_required"):
        super().__init__(root)
        self.gt_calls: list[int] = []
        self.gt_status = status

    def run_gt_evaluation(self, artifact, *, round_no):
        artifact.verify()
        self.gt_calls.append(round_no)
        return {
            "status": self.gt_status,
            "verifier": "tbs_gt",
            "reward": 1.0 if self.gt_status == "passed" else 0.0,
            "valid": self.gt_status == "passed",
            "official_metrics": {"reward": 1.0 if self.gt_status == "passed" else 0.0},
            "stdout": "FAILED test_outputs.py::test_meets_threshold",
            "stderr": "",
            "ctrf": {"results": {"summary": {"tests": 5, "passed": 4, "failed": 1}}},
        }


def test_gt_final_only_surrogate_exports_candidate_without_any_evaluation(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("candidate")
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    benchmark = _GTCountingBenchmark(tmp_path / "bench")

    result = SurrogateVerifyRunner(benchmark, workspace, verifier_mode="gt_final_only")(
        NodeInvocation("surrogate_verify_0", "surrogate_verify", {"round": 0, "gt_requested": False}),
        context,
    )

    assert result.output["status"] == "exported"
    assert result.output["gt_consumed"] is False
    assert benchmark.gt_calls == []
    artifact = ArtifactRef.from_dict(result.output["artifact_ref"])
    artifact.verify()
    assert (Path(artifact.storage_path) / "solution.txt").read_text() == "candidate"
    report = json.loads((run_dir / result.output["report_ref"]).read_text())
    assert report["verifier_mode"] == "gt_final_only"
    assert [check["id"] for check in report["checks"]] == ["artifact_export"]
    assert "gt_evaluation" not in report


def test_gt_budget_surrogate_runs_official_gt_only_when_requested_and_affordable(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("candidate")
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    benchmark = _GTCountingBenchmark(tmp_path / "bench")
    runner = SurrogateVerifyRunner(benchmark, workspace, verifier_mode="gt_budget")

    # Not requested: export only.
    silent = runner(
        NodeInvocation(
            "surrogate_verify_0",
            "surrogate_verify",
            {"round": 0, "gt_requested": False, "official_gt_remaining": 1},
        ),
        context,
    )
    assert silent.output["status"] == "exported"
    assert silent.output["gt_consumed"] is False
    assert benchmark.gt_calls == []

    # Requested with budget: official GT runs and the complete feedback reaches the Solver.
    granted = runner(
        NodeInvocation(
            "surrogate_verify_1",
            "surrogate_verify",
            {
                "round": 1,
                "gt_requested": True,
                "gt_request": {"requested": True, "reason": "ready"},
                "official_gt_remaining": 1,
            },
        ),
        context,
    )
    assert granted.output["status"] == "repair_required"
    assert granted.output["gt_consumed"] is True
    assert benchmark.gt_calls == [1]
    agent_report = json.loads((run_dir / granted.output["report_ref"]).read_text())
    assert agent_report["verifier_mode"] == "gt_budget"
    assert agent_report["official_gt_consumed"] is True
    assert "test_meets_threshold" in agent_report["gt_evaluation"]["stdout"]
    assert agent_report["gt_evaluation"]["ctrf"]["results"]["summary"]["failed"] == 1
    solver_copy = json.loads(
        workspace.worktree.joinpath(agent_report["agent_workspace_path"]).read_text()
    )
    assert solver_copy["gt_evaluation"]["stdout"] == agent_report["gt_evaluation"]["stdout"]
    system_report = json.loads((run_dir / granted.output["system_report_ref"]).read_text())
    assert system_report["official_gt_request"] == {"requested": True, "reason": "ready"}

    # Requested without budget: ignored, export only, explicit skipped check.
    denied = runner(
        NodeInvocation(
            "surrogate_verify_2",
            "surrogate_verify",
            {"round": 2, "gt_requested": True, "official_gt_remaining": 0},
        ),
        context,
    )
    assert denied.output["status"] == "exported"
    assert denied.output["gt_consumed"] is False
    assert benchmark.gt_calls == [1]
    denied_report = json.loads((run_dir / denied.output["report_ref"]).read_text())
    assert [check["id"] for check in denied_report["checks"]] == [
        "artifact_export",
        "official_gt_request",
    ]
    assert denied_report["checks"][1]["status"] == "skipped"


def test_gt_budget_verifier_error_does_not_consume_budget(tmp_path: Path):
    class _BrokenGT(_Benchmark):
        def run_gt_evaluation(self, artifact, *, round_no):
            raise RuntimeError("fm-job unavailable")

    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    workspace.worktree.joinpath("solution.txt").write_text("candidate")
    context = GraphContext("run-1", run_dir, workspace.worktree, "task-1")
    result = SurrogateVerifyRunner(_BrokenGT(tmp_path / "bench"), workspace, verifier_mode="gt_budget")(
        NodeInvocation(
            "surrogate_verify_0",
            "surrogate_verify",
            {"round": 0, "gt_requested": True, "official_gt_remaining": 1},
        ),
        context,
    )
    assert result.output["status"] == "verifier_error"
    assert result.output["gt_consumed"] is False


def test_solver_turn_surfaces_official_gt_request_and_budget_context(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")
    captured = {}

    class RequestingTurn:
        def run(self, request):
            captured.update(request.context)
            return AgentTurnResult(
                status="succeeded",
                phase=request.phase,
                output={"request_official_gt": True, "reason": "public checks pass"},
            )

    result = SolverTurnRunner(
        RequestingTurn(),
        workspace,
        LocalSandbox(workspace.root),
        "solve",
    )(
        NodeInvocation(
            "solver_turn_0",
            "agent_turn",
            {
                "phase": "solve",
                "gt_evaluation_policy": "on_request_budget",
                "official_gt_evaluations_allowed": 1,
                "official_gt_evaluations_used": 0,
                "official_gt_evaluations_remaining": 1,
                "evaluation_policy_note": "可申请一次官方 GT。",
            },
        ),
        GraphContext("run-1", run_dir, workspace.worktree, "task-1"),
    )

    assert result.status == "succeeded"
    assert result.output["gt_request"] == {"requested": True, "reason": "public checks pass"}
    assert captured["evaluation_policy"] == "on_request_budget"
    assert captured["official_gt_evaluations_remaining"] == 1
    assert captured["gt_request_file"] == str(
        workspace.worktree / "famou_terminal_solver_result.json"
    )


def test_solver_turn_without_request_reports_no_gt_request(tmp_path: Path):
    run_dir = tmp_path / "run"
    workspace = AgentWorkspace.create(run_dir, "solver")

    class QuietTurn:
        def run(self, request):
            return AgentTurnResult(status="succeeded", phase=request.phase, output={"status": "completed"})

    result = SolverTurnRunner(QuietTurn(), workspace, LocalSandbox(workspace.root), "solve")(
        NodeInvocation("solver_turn_0", "agent_turn", {"phase": "solve"}),
        GraphContext("run-1", run_dir, workspace.worktree, "task-1"),
    )
    assert result.output["gt_request"] is None
