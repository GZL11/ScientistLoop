from __future__ import annotations

import json
from pathlib import Path

from famou_scientist.loop.execution.agent_turn import AgentTurnRequest, CommandAgentTurn
from famou_scientist.loop.execution.sandbox import LocalSandbox
from famou_scientist.loop.execution.workspace import AgentWorkspace


def test_terminal_solver_turn_natural_exit_resumes_same_session(tmp_path: Path):
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, sys",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "calls_path = worktree / 'solver_calls.json'",
                "calls = json.loads(calls_path.read_text()) if calls_path.exists() else []",
                "calls.append(sys.argv[1:])",
                "calls_path.write_text(json.dumps(calls), encoding='utf-8')",
                "print('solver turn finished')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    workspace = AgentWorkspace.create(tmp_path / "goal", "terminal_solver")
    adapter = CommandAgentTurn(
        {"runtime": "opencode", "binary": str(fake_bin), "timeout_sec": 10}
    )

    first = adapter.run(
        AgentTurnRequest(
            role="terminal_solver",
            phase="solve",
            session_key="terminal_solver",
            instruction="solve task",
            workspace=workspace,
            sandbox=LocalSandbox(workspace.root),
        )
    )
    second = adapter.run(
        AgentTurnRequest(
            role="terminal_solver",
            phase="refine",
            session_key="terminal_solver",
            instruction="repair failed public check",
            workspace=workspace,
            sandbox=LocalSandbox(workspace.root),
        )
    )

    assert first.status == second.status == "succeeded"
    assert first.session_ref == second.session_ref
    assert first.session_ref and first.session_ref.endswith(
        "opencode_terminal_solver_session.json"
    )
    calls = json.loads((workspace.worktree / "solver_calls.json").read_text())
    assert "--continue" not in calls[0]
    assert "--continue" in calls[1]


def test_terminal_verifier_compile_natural_exit_allows_workspace_only_output(
    tmp_path: Path,
):
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "#!/usr/bin/env python3\nprint('compiler finished')\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    workspace = AgentWorkspace.create(tmp_path / "goal", "terminal_verifier")
    adapter = CommandAgentTurn(
        {"runtime": "opencode", "binary": str(fake_bin), "timeout_sec": 10}
    )

    result = adapter.run(
        AgentTurnRequest(
            role="terminal_verifier",
            phase="compile_plan",
            session_key="terminal_verifier",
            instruction="compile verifier",
            workspace=workspace,
            sandbox=LocalSandbox(workspace.root),
            completion_mode="natural_exit",
        )
    )

    assert result.status == "succeeded"
    assert result.error is None


def test_terminal_verifier_turn_returns_structured_plan(tmp_path: Path):
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib",
                "path = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT'])",
                "path.write_text(json.dumps({",
                "  'schema_version': 1,",
                "  'task_input_hash': 'task-hash',",
                "  'rubrics': [{'id': 'R1', 'severity': 'critical'}],",
                "}), encoding='utf-8')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    workspace = AgentWorkspace.create(tmp_path / "goal", "terminal_verifier")
    adapter = CommandAgentTurn(
        {"runtime": "opencode", "binary": str(fake_bin), "timeout_sec": 10}
    )

    result = adapter.run(
        AgentTurnRequest(
            role="terminal_verifier",
            phase="compile_plan",
            session_key="terminal_verifier",
            instruction="build public verification rubric",
            workspace=workspace,
            sandbox=LocalSandbox(workspace.root),
            completion_mode="structured_result",
        )
    )

    assert result.status == "succeeded"
    assert result.output["task_input_hash"] == "task-hash"
    assert result.output["rubrics"][0]["id"] == "R1"
