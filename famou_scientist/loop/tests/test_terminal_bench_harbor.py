from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from famou_scientist.loop.execution.sandbox import FmJobSandbox
from famou_scientist.loop.facilities.contracts import (
    ArtifactRef,
    CandidateRef,
    EvaluationRequest,
)
from famou_scientist.loop.integrations.terminal_bench.harbor import (
    HarborArtifactSpec,
    HarborBenchmarkFacility,
    HarborEvaluationFacility,
    HarborTrialLayout,
    copy_fmjob_artifacts,
    load_harbor_artifact_specs,
    load_harbor_artifacts,
)
from famou_scientist.loop.integrations.terminal_bench.fmjob_backend import (
    FmJobHarborTaskBackend,
)


class _Backend:
    def __init__(self, *, layout, options=None):
        self.layout = layout
        self.final_calls = 0

    def export_artifacts(self, candidate, *, artifact_paths, destination):
        destination.mkdir(parents=True, exist_ok=True)
        destination.joinpath("submission.txt").write_text("ok", encoding="utf-8")
        return destination

    def preflight(self, candidate, *, context):
        return {"valid": True, "round": context["round"]}

    def validate_artifact(self, artifact):
        return {"valid": True, "status": "passed"}

    def public_evaluate(self, artifact):
        return {
            "valid": True,
            "status": "passed",
            "artifact_ref": {"storage_path": "/trusted/verifier/path"},
        }

    def final_audit(self, request):
        self.final_calls += 1
        return {
            "valid": True,
            "official_metrics": {"reward": 1.0},
            "diagnostics_public": {"ok": True},
        }

    def candidate_gt_evaluate(self, request):
        return {
            "valid": False,
            "official_metrics": {"reward": 0.0, "fmjob_returncode": 1},
            "stdout": "FAILED test_outputs.py::test_value - AssertionError: expected 2, got 1",
            "stderr": "verifier warning",
            "ctrf": {"results": {"summary": {"tests": 2, "passed": 1, "failed": 1}}},
            "diagnostics_public": {"private": "/hidden"},
        }


def _layout(tmp_path: Path) -> HarborTrialLayout:
    task = tmp_path / "task"
    task.mkdir()
    task.joinpath("instruction.md").write_text("Solve the task", encoding="utf-8")
    task.joinpath("task.toml").write_text(
        'artifacts = ["/output/result.txt"]\n', encoding="utf-8"
    )
    trial = tmp_path / "trial"
    trial.mkdir()
    artifact_root = trial / "harbor-artifacts"
    artifact_root.mkdir()
    return HarborTrialLayout.from_paths(
        trial_dir=trial,
        task_dir=task,
        artifact_root=artifact_root,
    )


def test_persistent_fmjob_worker_submits_without_waiting(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin="fm-job",
        subpath=root,
        persistent=True,
    )
    try:
        args = sandbox._fmjob_args("true", no_wait=True)
    finally:
        sandbox.close()

    assert args[0:3] == ["fm-job", "run", "--no-wait"]
    assert "--" in args


def test_one_shot_fmjob_invocation_waits_for_result(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin="fm-job",
        subpath=root,
    )

    args = sandbox._fmjob_args("true")

    assert args[0:2] == ["fm-job", "run"]
    assert "--no-wait" not in args


def test_harbor_facilities_keep_task_view_and_final_audit_separate(tmp_path: Path):
    layout = _layout(tmp_path)
    backend = _Backend(layout=layout)
    benchmark = HarborBenchmarkFacility(
        layout=layout,
        backend=backend,
        task_id="terminal-1",
    )
    assert load_harbor_artifacts(layout.task_dir) == ("/output/result.txt",)
    assert benchmark.task_view().instructions == "Solve the task"
    assert benchmark.task_view().metadata == {"source": "harbor_task_view"}

    candidate = CandidateRef(
        candidate_id="c1",
        code_path=str(tmp_path),
        metadata={"round": 0},
    )
    result = benchmark.run(candidate, context={"round": 0})
    assert result.valid is True
    assert result.artifact_ref is not None
    assert (
        Path(result.artifact_ref.storage_path).parent / "COMPLETE"
    ).is_file()
    assert benchmark.validate_artifact(result.artifact_ref)["valid"] is True
    public = benchmark.run_public_evaluation(result.artifact_ref)
    assert "artifact_ref" not in public
    assert "/trusted" not in json.dumps(public)

    evaluator = HarborEvaluationFacility(backend=backend, layout=layout)
    final = evaluator.evaluate(
        EvaluationRequest(
            task_id="terminal-1",
            attempt_id="run-1:final",
            artifact_ref=result.artifact_ref,
        )
    )
    assert final.valid is True
    assert final.metrics["reward"] == 1.0
    assert backend.final_calls == 1


def test_harbor_artifact_specs_preserve_service_scope(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    task.joinpath("task.toml").write_text(
        "artifacts = [\n"
        '  "/app/plans.json",\n'
        '  { source = "/app/sim_local/probe_usage.json", service = "sim" },\n'
        "]\n",
        encoding="utf-8",
    )

    specs = load_harbor_artifact_specs(task)

    assert specs[0].to_dict() == {"source": "/app/plans.json"}
    assert specs[1].to_dict() == {
        "source": "/app/sim_local/probe_usage.json",
        "service": "sim",
    }
    # The compatibility API still exposes only paths to old callers.
    assert load_harbor_artifacts(task) == (
        "/app/plans.json",
        "/app/sim_local/probe_usage.json",
    )


def test_harbor_candidate_gt_evaluation_is_public_and_separate(tmp_path: Path):
    layout = _layout(tmp_path)
    backend = _Backend(layout=layout)
    benchmark = HarborBenchmarkFacility(layout=layout, backend=backend, task_id="terminal-1")
    candidate = CandidateRef(candidate_id="c1", code_path=str(tmp_path), metadata={"round": 0})
    artifact = benchmark.run(candidate, context={"round": 0}).artifact_ref
    assert artifact is not None
    result = benchmark.run_gt_evaluation(artifact, round_no=2)
    assert result["verifier"] == "tbs_gt"
    assert result["status"] == "repair_required"
    assert result["reward"] == 0.0
    assert result["official_metrics"]["fmjob_returncode"] == 1
    assert "AssertionError" in result["stdout"]
    assert result["stderr"] == "verifier warning"
    assert result["ctrf"]["results"]["summary"]["failed"] == 1
    assert "private" not in result


def test_fmjob_sandbox_preserves_cfs_workspace_and_allowlisted_env(tmp_path: Path):
    fake = tmp_path / "fake-fm-job"
    fake.write_text(
        "#!/bin/sh\n"
        "while [ \"$1\" != \"--\" ]; do shift; done\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin=str(fake),
        subpath=root,
    )
    result = sandbox.run(
        ["bash", "-lc", "printf '%s' \"$FAMOU_TEST_VALUE\" > result.txt"],
        cwd=root,
        env={"FAMOU_TEST_VALUE": "cfs-ok"},
        timeout_sec=2,
    )
    assert result.valid is True
    assert root.joinpath("result.txt").read_text() == "cfs-ok"


def test_persistent_fmjob_sandbox_reuses_one_worker_and_workspace(tmp_path: Path):
    fake = tmp_path / "fake-fm-job"
    fake.write_text(
        "#!/bin/sh\n"
        "while [ \"$1\" != \"--\" ]; do shift; done\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin=str(fake),
        subpath=root,
        persistent=True,
    )
    try:
        first = sandbox.run(
            ["bash", "-lc", "printf one > persisted.txt"],
            cwd=root,
            timeout_sec=2,
        )
        second = sandbox.run(
            ["bash", "-lc", "test \"$(cat persisted.txt)\" = one && printf two > second.txt"],
            cwd=root,
            timeout_sec=2,
        )
        assert first.valid is True
        assert second.valid is True
        assert root.joinpath("second.txt").read_text() == "two"
        assert sandbox._worker_process is not None
    finally:
        sandbox.close()
    assert sandbox._worker_process is None


def test_fmjob_round_export_replaces_snapshot_without_touching_solver_artifact(
    tmp_path: Path,
):
    fake = tmp_path / "fake-fm-job"
    fake.write_text(
        "#!/bin/sh\n"
        "while [ \"$1\" != \"--\" ]; do shift; done\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    root = tmp_path / "workspace"
    source = root / "submission"
    source.mkdir(parents=True)
    export_root = root / "artifacts/fmjob-agent"
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin=str(fake),
        subpath=root,
        artifact_paths=[str(source)],
        artifact_export_root=export_root,
        persistent=True,
    )
    try:
        first = sandbox.run(
            ["bash", "-lc", f"printf old > '{source}/stale.txt'; printf one > '{source}/result.txt'"],
            cwd=root,
            env={"FAMOU_TERMINAL_ROUND": "0"},
            timeout_sec=2,
        )
        second = sandbox.run(
            ["bash", "-lc", f"rm -f '{source}/stale.txt'; printf two > '{source}/result.txt'"],
            cwd=root,
            env={"FAMOU_TERMINAL_ROUND": "0"},
            timeout_sec=2,
        )
    finally:
        sandbox.close()

    snapshot = export_root / "round_0" / str(source).lstrip("/")
    assert first.valid is True
    assert second.valid is True
    assert source.joinpath("result.txt").read_text() == "two"
    assert snapshot.joinpath("result.txt").read_text() == "two"
    assert not snapshot.joinpath("stale.txt").exists()
    assert not snapshot.joinpath(source.name, "result.txt").exists()


def test_fmjob_refine_rehydrates_declared_artifacts_from_previous_round(
    tmp_path: Path,
):
    fake = tmp_path / "fake-fm-job"
    fake.write_text(
        "#!/bin/sh\n"
        "while [ \"$1\" != \"--\" ]; do shift; done\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    root = tmp_path / "workspace"
    source = root / "submission"
    source.mkdir(parents=True)
    export_root = root / "artifacts/fmjob-agent"
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin=str(fake),
        subpath=root,
        artifact_paths=[str(source)],
        artifact_export_root=export_root,
        persistent=True,
    )
    try:
        first = sandbox.run(
            ["bash", "-lc", f"printf round-zero > '{source}/result.txt'"],
            cwd=root,
            env={"FAMOU_TERMINAL_ROUND": "0"},
            timeout_sec=2,
        )
        # Simulate loss of container-local absolute artifacts. The CFS round
        # snapshot remains the recovery source for the resumed refine turn.
        shutil.rmtree(source)
        second = sandbox.run(
            [
                "bash",
                "-lc",
                f"test \"$(cat '{source}/result.txt')\" = round-zero && printf round-one > '{source}/result.txt'",
            ],
            cwd=root,
            env={"FAMOU_TERMINAL_ROUND": "1"},
            timeout_sec=2,
        )
    finally:
        sandbox.close()

    round_zero = export_root / "round_0" / str(source).lstrip("/") / "result.txt"
    round_one = export_root / "round_1" / str(source).lstrip("/") / "result.txt"
    assert first.valid is True
    assert second.valid is True
    assert round_zero.read_text() == "round-zero"
    assert round_one.read_text() == "round-one"
    assert source.joinpath("result.txt").read_text() == "round-one"


def test_persistent_fmjob_sandbox_reports_worker_submission_failure(tmp_path: Path):
    fake = tmp_path / "failing-fm-job"
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'cluster submission rejected' >&2\n"
        "exit 42\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin=str(fake),
        subpath=root,
        persistent=True,
    )
    try:
        result = sandbox.run(["true"], cwd=root, timeout_sec=2)
    finally:
        sandbox.close()

    assert result.valid is False
    assert result.timed_out is False
    assert result.termination_reason == "infrastructure_error"
    assert "cluster submission rejected" in result.stderr
    assert root.joinpath(".fmjob-worker/launch.stderr.restart-1").is_file()


def test_persistent_fmjob_sandbox_restarts_worker_once(tmp_path: Path):
    fake = tmp_path / "flaky-fm-job"
    marker = tmp_path / "attempt"
    control = tmp_path / "workspace" / ".fmjob-worker"
    fake.write_text(
        "#!/bin/sh\n"
        f"if [ ! -f '{marker}' ]; then\n"
        f"  touch '{marker}'\n"
        "  i=0\n"
        f"  while ! ls '{control}/requests/'*.sh >/dev/null 2>&1; do\n"
        "    i=$((i + 1)); [ \"$i\" -lt 200 ] || exit 43; sleep 0.01\n"
        "  done\n"
        f"  mv '{control}/requests/'*.sh '{control}/running/'\n"
        "  exit 42\n"
        "fi\n"
        "while [ \"$1\" != \"--\" ]; do shift; done\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = FmJobSandbox(
        root,
        image="terminal-agent:test",
        fm_job_bin=str(fake),
        subpath=root,
        persistent=True,
    )
    try:
        result = sandbox.run(
            ["bash", "-lc", "printf recovered > recovered.txt"],
            cwd=root,
            timeout_sec=2,
        )
    finally:
        sandbox.close()

    assert result.valid is True
    assert root.joinpath("recovered.txt").read_text() == "recovered"
    assert root.joinpath(".fmjob-worker/launch.stdout.restart-1").is_file()


def test_copy_fmjob_artifacts_only_exports_declared_paths(tmp_path: Path):
    source = tmp_path / "round_0"
    source.joinpath("output").mkdir(parents=True)
    source.joinpath("output/result.txt").write_text("ok", encoding="utf-8")
    source.joinpath("secret.txt").write_text("must-not-copy", encoding="utf-8")
    destination = tmp_path / "payload"

    copy_fmjob_artifacts(
        source,
        artifact_paths=["/output/result.txt"],
        destination=destination,
    )
    assert destination.joinpath("output/result.txt").read_text() == "ok"
    assert not destination.joinpath("secret.txt").exists()


def test_fmjob_backend_prefers_container_export_for_absolute_artifacts(tmp_path: Path):
    layout = _layout(tmp_path)
    export = layout.artifact_root / "fmjob-agent" / "round_2"
    expected = {
        "/app/results/app.txt": "app",
        "/results/root.txt": "results",
        "/root/results/home.txt": "root",
    }
    for artifact_path, value in expected.items():
        source = export / artifact_path.lstrip("/")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(value, encoding="utf-8")

    worktree = tmp_path / "solver-worktree"
    worktree.mkdir()
    candidate = CandidateRef(
        candidate_id="fmjob-candidate",
        code_path=str(worktree),
        metadata={"round": 2},
    )
    backend = FmJobHarborTaskBackend(
        layout=layout,
        options={"verifier_image": "unused:test"},
    )
    destination = tmp_path / "payload"
    backend.export_artifacts(
        candidate,
        artifact_paths=list(expected),
        destination=destination,
    )

    for artifact_path, value in expected.items():
        assert destination.joinpath(artifact_path.lstrip("/")).read_text() == value


def test_fmjob_backend_preserves_partial_container_export(tmp_path: Path):
    layout = _layout(tmp_path)
    export = layout.artifact_root / "fmjob-agent" / "round_3"
    export.joinpath("app/plans.json").parent.mkdir(parents=True)
    export.joinpath("app/plans.json").write_text("{}\n", encoding="utf-8")
    export.joinpath("app/skills.py").write_text("# skills\n", encoding="utf-8")
    worktree = tmp_path / "solver-worktree"
    worktree.mkdir()
    candidate = CandidateRef(
        candidate_id="partial-candidate",
        code_path=str(worktree),
        metadata={"round": 3},
    )
    backend = FmJobHarborTaskBackend(
        layout=layout,
        options={"verifier_image": "unused:test"},
    )
    destination = tmp_path / "partial-payload"
    artifact_paths = [
        "/app/plans.json",
        "/app/skills.py",
        "/app/sim_local/probe_usage.json",
    ]

    backend.export_artifacts(
        candidate,
        artifact_paths=artifact_paths,
        destination=destination,
    )
    artifact = ArtifactRef.from_path(
        destination,
        artifact_id="partial-artifact",
        metadata={"artifact_paths": artifact_paths},
    )
    validation = backend.validate_artifact(artifact)

    assert destination.joinpath("app/plans.json").is_file()
    assert destination.joinpath("app/skills.py").is_file()
    assert not destination.joinpath("app/sim_local/probe_usage.json").exists()
    assert validation == {
        "valid": False,
        "checks": [
            {"path": "app/plans.json", "exists": True},
            {"path": "app/skills.py", "exists": True},
            {"path": "app/sim_local/probe_usage.json", "exists": False},
        ],
    }


def test_fmjob_backend_exports_service_artifact_from_service_snapshot(tmp_path: Path):
    layout = _layout(tmp_path)
    service_export = layout.artifact_root / "fmjob-service" / "sim" / "round_4"
    ledger = service_export / "app/sim_local/probe_usage.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"inst_001": 2}\n', encoding="utf-8")

    worktree = tmp_path / "solver-worktree"
    worktree.mkdir()
    candidate = CandidateRef(
        candidate_id="service-candidate",
        code_path=str(worktree),
        metadata={"round": 4},
    )
    backend = FmJobHarborTaskBackend(
        layout=layout,
        options={"verifier_image": "unused:test"},
    )
    destination = tmp_path / "payload"
    specs = (
        # This is intentionally absent from the Solver worktree.  It must be
        # resolved from the service export and merged into the payload.
        HarborArtifactSpec(path="/app/sim_local/probe_usage.json", service="sim"),
    )

    backend.export_artifacts(
        candidate,
        artifact_paths=["/app/sim_local/probe_usage.json"],
        artifact_specs=specs,
        destination=destination,
    )

    assert destination.joinpath("app/sim_local/probe_usage.json").read_text() == (
        '{"inst_001": 2}\n'
    )


def test_fmjob_backend_maps_frozen_workspace_suffix_to_declared_root(tmp_path: Path):
    layout = _layout(tmp_path)
    workspace = layout.artifact_root / "final-workspace"
    workspace.joinpath("results").mkdir(parents=True)
    workspace.joinpath("results/output.txt").write_text("ok", encoding="utf-8")
    backend = FmJobHarborTaskBackend(
        layout=layout,
        options={"verifier_image": "unused:test"},
    )
    assert backend._artifact_source(workspace, "/root/results/output.txt") == (
        workspace / "results/output.txt"
    ).resolve()


def test_fmjob_backend_validates_directory_artifacts(tmp_path: Path):
    layout = _layout(tmp_path)
    artifact_root = layout.artifact_root / "payload"
    artifact_root.joinpath("app/small_area_submission").mkdir(parents=True)
    artifact_root.joinpath("app/small_area_submission/solve.py").write_text(
        "print('ok')\n", encoding="utf-8"
    )
    artifact_root.joinpath("root").mkdir()
    artifact_root.joinpath("root/task_contract.json").write_text(
        "{}\n", encoding="utf-8"
    )
    artifact = ArtifactRef.from_path(
        artifact_root,
        artifact_id="directory-artifact",
        metadata={
            "artifact_paths": [
                "/app/small_area_submission",
                "/root/task_contract.json",
            ]
        },
    )
    backend = FmJobHarborTaskBackend(
        layout=layout,
        options={"verifier_image": "unused:test"},
    )

    validation = backend.validate_artifact(artifact)

    assert validation["valid"] is True
    assert all(item["exists"] for item in validation["checks"])


def test_fmjob_backend_restores_directory_as_exact_target(tmp_path: Path):
    source = tmp_path / "payload/app/small_area_submission"
    source.mkdir(parents=True)
    source.joinpath("solve.py").write_text("print('ok')\n", encoding="utf-8")

    lines = FmJobHarborTaskBackend._artifact_restore_lines(
        source,
        Path("/app/small_area_submission"),
    )

    assert lines == [
        "rm -rf -- '/app/small_area_submission'",
        "mkdir -p '/app'",
        f"cp -a -- '{source}' '/app/small_area_submission'",
    ]
    assert all("/app/small_area_submission/small_area_submission" not in line for line in lines)


def test_fmjob_backend_directory_restore_replaces_preexisting_target(tmp_path: Path):
    source = tmp_path / "payload/small_area_submission"
    source.mkdir(parents=True)
    source.joinpath("solve.py").write_text("print('ok')\n", encoding="utf-8")
    target = tmp_path / "verifier/app/small_area_submission"
    target.mkdir(parents=True)
    target.joinpath("stale.txt").write_text("stale\n", encoding="utf-8")

    lines = FmJobHarborTaskBackend._artifact_restore_lines(source, target)
    subprocess.run(["bash", "-lc", "\n".join(lines)], check=True)

    assert target.joinpath("solve.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not target.joinpath("stale.txt").exists()
    assert not target.joinpath(source.name, "solve.py").exists()


def test_fmjob_backend_missing_artifact_removes_image_owned_target(tmp_path: Path):
    target = tmp_path / "verifier/app/sim_local/probe_usage.json"
    target.parent.mkdir(parents=True)
    target.write_text("stale\n", encoding="utf-8")

    lines = FmJobHarborTaskBackend._artifact_target_reset_lines(target)
    subprocess.run(["bash", "-lc", "\n".join(lines)], check=True)

    assert not target.exists()
    assert target.parent.is_dir()


def test_fmjob_backend_refuses_verifier_control_artifact_targets(tmp_path: Path):
    source = tmp_path / "payload"
    source.mkdir()

    for target in (Path("/"), Path("/tests"), Path("/tests/test.sh"), Path("/logs/verifier")):
        try:
            FmJobHarborTaskBackend._artifact_restore_lines(source, target)
        except ValueError as exc:
            assert "control path" in str(exc)
        else:  # pragma: no cover - explicit fail keeps the loop dependency-free
            raise AssertionError(f"unsafe verifier target was accepted: {target}")


def test_fmjob_backend_assigns_stable_trial_specific_solver_uid(tmp_path: Path):
    first = FmJobHarborTaskBackend._isolated_solver_uid(tmp_path / "trial-a")
    repeated = FmJobHarborTaskBackend._isolated_solver_uid(tmp_path / "trial-a")
    second = FmJobHarborTaskBackend._isolated_solver_uid(tmp_path / "trial-b")

    assert 1_000_000 <= first < 1_001_000_000
    assert first == repeated
    assert first != second


def test_fmjob_backend_isolates_nobody_uid_for_official_verifiers(tmp_path: Path):
    trial = tmp_path / "trial-nobody"
    lines = FmJobHarborTaskBackend._uid_isolation_lines(trial, {})
    script = "\n".join(lines)
    solver_uid = FmJobHarborTaskBackend._isolated_solver_uid(trial)
    nobody_uid = FmJobHarborTaskBackend._isolated_nobody_uid(trial)
    assert nobody_uid != solver_uid
    assert nobody_uid >= 1_000_000
    # solveruser mapping is unchanged.
    assert f"usermod -u {solver_uid} solveruser" in script
    # nobody is remapped by name for setpriv/su based verifiers ...
    assert f"NOBODY_ISOLATED_UID={nobody_uid}" in script
    assert 'usermod -u "$NOBODY_ISOLATED_UID" nobody' in script
    assert 'groupmod -g "$NOBODY_ISOLATED_UID"' in script
    # ... and numeric constants in verifier sources are rewritten too.
    assert "NOBODY_UID|NOBODY_GID|WORKER_UID|WORKER_GID|SOLVER_UID|SOLVER_GID" in script
    assert "sed -i -E" in script and "/tests --include='*.py'" in script
    # Hash-pinned verifier sources (small-area-equivalence) are never edited.
    assert "hash-pinned" in script and "sha256sum" in script
    assert "/tests_run" in script and "TEST_SH=/tests_run/test.sh" in script  # hash-pinned verifiers run a shadow copy
    assert "\\b65534\\b" in script  # fixtures inside the shadow copy follow the remapped UID
    # Pre-owned files follow the new identity.
    assert "-uid 65534 -exec chown -h" in script
    # Opt-out keeps the legacy behaviour.
    legacy = "\n".join(
        FmJobHarborTaskBackend._uid_isolation_lines(trial, {"remap_nobody_uid": False})
    )
    assert "NOBODY_ISOLATED_UID" not in legacy
    assert f"usermod -u {solver_uid} solveruser" in legacy


def test_fmjob_nobody_constant_rewrite_matches_official_sources(tmp_path: Path):
    """The sed used at audit time must hit the real constants and nothing else."""
    import re, subprocess

    trial = tmp_path / "trial"
    script = "\n".join(FmJobHarborTaskBackend._uid_isolation_lines(trial, {}))
    sed_cmd = next(line.strip() for line in script.splitlines() if line.strip().startswith("sed -i -E") and "( *= *)65534" in line)
    nobody_uid = FmJobHarborTaskBackend._isolated_nobody_uid(trial)
    source = tmp_path / "test_state.py"
    source.write_text(
        "NOBODY_UID = 65534\nNOBODY_GID = 65534\nWORKER_UID = 65534\nSOLVER_UID = 65534\n"
        "CASE_TIMEOUT_SECONDS = 1800\nOTHER = 65534  # keep\nX_NOBODY_UID = 65534\n",
        encoding="utf-8",
    )
    cmd = sed_cmd.replace("$NOBODY_ISOLATED_UID", str(nobody_uid)).replace('"$f"', str(source)).replace(" || exit 67", "")
    subprocess.run(["bash", "-c", cmd], check=True)
    text = source.read_text(encoding="utf-8")
    assert f"NOBODY_UID = {nobody_uid}" in text
    assert f"NOBODY_GID = {nobody_uid}" in text
    assert f"WORKER_UID = {nobody_uid}" in text
    assert f"SOLVER_UID = {nobody_uid}" in text
    assert "CASE_TIMEOUT_SECONDS = 1800" in text
    assert "OTHER = 65534" in text
    assert "X_NOBODY_UID = 65534" in text


def test_fmjob_backend_recognizes_shared_uid_infrastructure_failures():
    detect = FmJobHarborTaskBackend._shared_uid_failure
    assert detect(
        "E   BlockingIOError: [Errno 11] Resource temporarily unavailable: '/usr/local/bin/python3'", ""
    ) == "shared_uid_nproc_eagain"
    assert detect("AssertionError: submitted worker exited with status 68: ", "") == "shared_uid_nproc_eagain"
    assert detect("FAILED test_outputs.py::test_meets_threshold - composite score 30", "") is None
    assert detect("", "") is None
