from __future__ import annotations

import ast
from pathlib import Path

import pytest

from famou_scientist.loop.harness.cli import _build_parser
from famou_scientist.loop.integrations.terminal_bench.fmjob_backend import (
    FmJobHarborTaskBackend,
)
from famou_scientist.loop.integrations.terminal_bench.harbor import HarborTrialLayout


LOOP_ROOT = Path(__file__).resolve().parents[1]


def _import_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(alias.name for alias in node.names)
    return names


def test_graph_executor_has_no_benchmark_graph_dependency():
    imports = _import_names(LOOP_ROOT / "runtime" / "graph_executor.py")
    assert not any("terminal_task" in name or "sota_search" in name for name in imports)


def test_terminal_graph_has_no_sota_domain_dependency():
    imports = _import_names(LOOP_ROOT / "graphs" / "terminal_task" / "graph.py")
    forbidden = {"AsyncOrchestrator", "ResearchState", "ExpBank", "Idea", "CandidateRef"}
    assert imports.isdisjoint(forbidden)


def test_sota_orchestrator_has_no_terminal_graph_dependency():
    imports = _import_names(LOOP_ROOT / "runtime" / "orchestrator.py")
    assert not any("terminal_task" in name or "TerminalTask" in name for name in imports)


def test_terminal_cli_options_are_parsed_independently():
    args = _build_parser().parse_args(
        [
            "run",
            "--task-id",
            "terminal-1",
            "--run-dir",
            "/tmp/terminal-run",
            "--evaluator-channel",
            "/tmp/evaluator",
            "--agent-graph",
            "terminal_task",
            "--solver-runtime",
            "codex",
            "--verifier-runtime",
            "claude",
            "--solver-model",
            "solver-model",
            "--verifier-model",
            "verifier-model",
            "--max-refine-rounds",
            "4",
            "--verifier-planning-timeout-sec",
            "321",
            "--solver-image",
            "solver:image",
            "--verifier-image",
            "verifier:image",
            "--gt-verifier-image",
            "gt-verifier:image",
            "--fm-job-bin",
            "/usr/local/bin/fm-job",
        ]
    )

    assert args.agent_graph == "terminal_task"
    assert args.solver_runtime == "codex"
    assert args.verifier_runtime == "claude"
    assert args.solver_model == "solver-model"
    assert args.verifier_model == "verifier-model"
    assert args.max_refine_rounds == 4
    assert args.verifier_planning_timeout_sec == 321
    assert args.solver_image == "solver:image"
    assert args.verifier_image == "verifier:image"
    assert args.gt_verifier_image == "gt-verifier:image"
    assert args.fm_job_bin == "/usr/local/bin/fm-job"
    assert args.candidate_verifier_mode == "proxy"


def test_terminal_cli_accepts_gt_candidate_verifier_mode():
    args = _build_parser().parse_args(
        [
            "run",
            "--task-id", "terminal-1",
            "--run-dir", "/tmp/terminal-run",
            "--evaluator-channel", "/tmp/evaluator",
            "--agent-graph", "terminal_task",
            "--candidate-verifier-mode", "gt_primary",
        ]
    )
    assert args.candidate_verifier_mode == "gt_primary"


def test_terminal_cli_accepts_single_final_gt_mode():
    args = _build_parser().parse_args(
        [
            "run",
            "--task-id", "terminal-1",
            "--run-dir", "/tmp/terminal-run",
            "--evaluator-channel", "/tmp/evaluator",
            "--agent-graph", "terminal_task",
            "--candidate-verifier-mode", "gt_final_only",
        ]
    )
    assert args.candidate_verifier_mode == "gt_final_only"


def test_terminal_cli_accepts_gt_budget_mode_with_explicit_budget():
    args = _build_parser().parse_args(
        [
            "run",
            "--task-id", "terminal-1",
            "--run-dir", "/tmp/terminal-run",
            "--evaluator-channel", "/tmp/evaluator",
            "--agent-graph", "terminal_task",
            "--candidate-verifier-mode", "gt_budget",
            "--official-gt-budget", "3",
        ]
    )
    assert args.candidate_verifier_mode == "gt_budget"
    assert args.official_gt_budget == 3


def test_fmjob_harbor_backend_rejects_shared_solver_and_gt_image(tmp_path: Path):
    layout = HarborTrialLayout(
        trial_dir=tmp_path,
        task_dir=tmp_path,
        artifact_root=tmp_path / "artifacts",
        famou_dir=tmp_path / "famou",
    )

    with pytest.raises(ValueError, match="必须使用不同镜像"):
        FmJobHarborTaskBackend(
            layout=layout,
            options={
                "solver_image": "registry/task:agent",
                "gt_verifier_image": "registry/task:agent",
            },
        )


def test_official_gt_runner_uses_image_owned_test_script():
    source = (
        LOOP_ROOT
        / "integrations"
        / "terminal_bench"
        / "fmjob_backend.py"
    ).read_text(encoding="utf-8")
    final_audit = source.split("    def final_audit", 1)[1].split("    def close", 1)[0]

    assert "test -r /tests/test.sh" in final_audit
    assert "bash /tests/test.sh" in final_audit
    assert "pip install" not in final_audit
    assert "shutil.copytree" not in final_audit
    assert "_artifact_restore_lines" in final_audit


def test_terminal_harness_reads_official_verifier_timeout(tmp_path):
    from famou_scientist.loop.harness.runtime import BenchmarkHarness

    tmp_path.joinpath("task.toml").write_text(
        "[agent]\ntimeout_sec = 28800\n[verifier]\ntimeout_sec = 5400.0\n",
        encoding="utf-8",
    )

    assert BenchmarkHarness._task_agent_timeout_sec(tmp_path) == 28800
    assert BenchmarkHarness._task_verifier_timeout_sec(tmp_path) == 5400.0


def test_terminal_solver_prompt_uses_v2_only_for_on_request_gt_budget():
    from famou_scientist.loop.execution import cli_agent_wrapper as wrapper

    def render(policy: str | None) -> str:
        context = {"evaluation_policy_note": "NOTE-BODY"}
        if policy:
            context["evaluation_policy"] = policy
        return wrapper.build_terminal_solver_prompt(
            request={"metadata": {"terminal_phase": "solve", "terminal_context": context}},
            instruction="INSTRUCTION-BODY",
            output_path=Path("/tmp/out.json"),
            worktree_result_path=Path("/tmp/w/famou_terminal_solver_result.json"),
            worktree=Path("/tmp/w"),
            max_turns=None,
        )

    budget_prompt = render("on_request_budget")
    assert "Terminal Task Solver v2" in budget_prompt
    assert "官方 GT 申请文件" in budget_prompt
    assert "NOTE-BODY" in budget_prompt
    # Existing modes keep the v1 contract byte-for-byte.
    assert "Terminal Task Solver v1" in render("final_only_once")
    assert "Terminal Task Solver v1" in render(None)
    assert "也不需要生成候选结果 JSON" in render(None)
