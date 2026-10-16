from __future__ import annotations

from collections import Counter
from pathlib import Path
from threading import Barrier

from famou_scientist.loop.domain.graph import GraphContext, NodeResult
from famou_scientist.loop.graphs.terminal_task import TerminalTaskConfig, TerminalTaskGraph
from famou_scientist.loop.runtime.graph_executor import GraphExecutor, GraphExecutorConfig
from famou_scientist.loop.storage.graph_state import GraphStateStore


def _context(tmp_path: Path) -> GraphContext:
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    return GraphContext(
        run_id="run-terminal-1",
        run_dir=run_dir,
        workspace_dir=workspace,
        task_id="terminal-task-1",
    )


def test_terminal_task_graph_parallel_plan_refine_and_final_audit(tmp_path: Path):
    context = _context(tmp_path)
    calls: list[tuple[str, str, str | None]] = []
    initial_barrier = Barrier(2, timeout=2)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(max_refine_rounds=3, max_agent_wall_time_sec=3600),
        now_ms=lambda: 1_000,
    )

    def runner(invocation, _context):
        calls.append((invocation.kind, invocation.invocation_id, invocation.payload.get("session_key")))
        if invocation.invocation_id in {"solver_turn_0", "verifier_plan_0"}:
            # 任一节点串行执行都会在这里超时，直接证明首批是并发调度。
            initial_barrier.wait()
        if invocation.kind == "agent_turn":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"phase": invocation.payload["phase"], "session_ref": "solver-session-1"},
            )
        if invocation.kind == "verifier_plan":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"plan_ref": "controller/verifier/plan.json", "session_ref": "verifier-session-1"},
            )
        if invocation.kind == "surrogate_verify":
            status = "repair_required" if invocation.payload["round"] == 0 else "passed"
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {
                    "status": status,
                    "report_ref": f"controller/surrogate/round_{invocation.payload['round']}.json",
                    "artifact_ref": f"artifacts/surrogate_{invocation.payload['round']}",
                },
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"workspace_ref": "artifacts/final_workspace"},
            )
        if invocation.kind == "final_audit":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "passed", "result_ref": "controller/final_audit/result.json"},
            )
        raise AssertionError(invocation.kind)

    output = GraphExecutor(
        graph,
        {
            "agent_turn": runner,
            "verifier_plan": runner,
            "surrogate_verify": runner,
            "freeze_workspace": runner,
            "final_audit": runner,
        },
        state_store=GraphStateStore(context.run_dir),
        config=GraphExecutorConfig(max_workers=2),
    ).run(context)

    assert output.status == "completed"
    assert output.payload["final_audit_ref"].endswith("result.json")
    assert [item[1] for item in calls if item[0] == "agent_turn"] == [
        "solver_turn_0",
        "solver_turn_1",
    ]
    assert [item[2] for item in calls if item[0] == "agent_turn"] == [
        "terminal_solver",
        "terminal_solver",
    ]
    assert [item[0] for item in calls].count("final_audit") == 1


def test_final_audit_invocation_carries_proxy_report_reference(tmp_path: Path):
    graph = TerminalTaskGraph(TerminalTaskConfig(candidate_verifier_mode="proxy"))
    context = _context(tmp_path)
    state = graph.initialize(context).with_updates(
        phase="awaiting_final_audit",
        data={
            **graph.initialize(context).data,
            "candidate_verifier_mode": "proxy",
            "last_surrogate_report_ref": "agent_control/surrogate/round_0.json",
            "last_valid_candidate_artifact_ref": {"artifact_id": "a"},
        },
    )
    invocation = graph.ready(state)[0]
    assert invocation.payload["proxy_report_ref"] == "agent_control/surrogate/round_0.json"


def test_gt_primary_skips_verifier_agent_and_enters_candidate_gt_phase(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_primary", max_refine_rounds=1),
        now_ms=lambda: 1_000,
    )
    initial = graph.initialize(context)
    ready = graph.ready(initial)
    assert [item.kind for item in ready] == ["agent_turn"]

    after_solver = graph.apply(
        initial,
        NodeResult(
            "solver_turn_0",
            "agent_turn",
            "succeeded",
            {"phase": "solve", "session_ref": "solver-session"},
        ),
    )
    assert after_solver.phase == "surrogate_verifying"
    assert graph.ready(after_solver)[0].kind == "surrogate_verify"


def test_gt_final_only_exports_candidate_without_evaluation_then_runs_final_audit_once(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_final_only"),
        now_ms=lambda: 1_000,
    )
    initial = graph.initialize(context)
    ready = graph.ready(initial)
    assert [item.kind for item in ready] == ["agent_turn"]
    assert ready[0].payload["gt_evaluation_policy"] == "final_only_once"
    assert ready[0].payload["official_gt_evaluations_allowed"] == 1

    after_solver = graph.apply(
        initial,
        NodeResult(
            "solver_turn_0",
            "agent_turn",
            "succeeded",
            {"phase": "solve", "session_ref": "solver-session"},
        ),
    )
    # The Solver's /app output only exists in the container export. It must be
    # registered as the candidate artifact before freezing, otherwise
    # FinalAudit evaluates the (empty) host worktree.
    assert after_solver.phase == "surrogate_verifying"
    export = graph.ready(after_solver)[0]
    assert export.kind == "surrogate_verify"
    assert export.payload["gt_requested"] is False

    artifact = {"artifact_id": "cand-0", "storage_path": "artifacts/round_0/payload", "sha256": "x"}
    after_export = graph.apply(
        after_solver,
        NodeResult(
            "surrogate_verify_0",
            "surrogate_verify",
            "succeeded",
            {"status": "exported", "artifact_ref": artifact, "report_ref": "agent_control/surrogate/round_0.json"},
        ),
    )
    assert after_export.phase == "freezing"
    assert after_export.data["official_gt_used"] == 0
    assert graph.ready(after_export)[0].kind == "freeze_workspace"

    after_freeze = graph.apply(
        after_export,
        NodeResult(
            "freeze_workspace_0",
            "freeze_workspace",
            "succeeded",
            {"workspace_ref": "artifacts/final_workspace"},
        ),
    )
    assert after_freeze.phase == "awaiting_final_audit"
    final = graph.ready(after_freeze)[0]
    assert final.kind == "final_audit"
    assert final.payload["candidate_verifier_mode"] == "gt_final_only"
    assert final.payload["candidate_artifact_ref"] == artifact


def test_gt_budget_grants_one_requested_gt_then_freezes_without_further_feedback(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_budget", official_gt_budget=1),
        now_ms=lambda: 1_000,
    )
    initial = graph.initialize(context)
    ready = graph.ready(initial)
    # No VerifierAgent / Proxy in this mode.
    assert [item.kind for item in ready] == ["agent_turn"]
    policy = ready[0].payload
    assert policy["gt_evaluation_policy"] == "on_request_budget"
    assert policy["official_gt_evaluations_allowed"] == 1
    assert policy["official_gt_evaluations_remaining"] == 1
    assert "gt_request_file" in policy["evaluation_policy_note"]

    # Solver exits and asks for an official evaluation.
    after_solver = graph.apply(
        initial,
        NodeResult(
            "solver_turn_0",
            "agent_turn",
            "succeeded",
            {
                "phase": "solve",
                "session_ref": "solver-session",
                "gt_request": {"requested": True, "reason": "public checks pass; need hidden GT"},
            },
        ),
    )
    assert after_solver.phase == "surrogate_verifying"
    verify = graph.ready(after_solver)[0]
    assert verify.payload["gt_requested"] is True
    assert verify.payload["official_gt_remaining"] == 1
    assert verify.payload["gt_request"]["reason"].startswith("public checks")

    artifact0 = {"artifact_id": "cand-0", "storage_path": "artifacts/round_0/payload", "sha256": "a"}
    after_gt = graph.apply(
        after_solver,
        NodeResult(
            "surrogate_verify_0",
            "surrogate_verify",
            "succeeded",
            {
                "status": "repair_required",
                "artifact_ref": artifact0,
                "report_ref": "agent_control/surrogate/round_0.json",
                "gt_consumed": True,
            },
        ),
    )
    # GT failed -> Solver gets one refine turn with the GT report; budget is spent.
    assert after_gt.phase == "refining"
    assert after_gt.data["official_gt_used"] == 1
    assert after_gt.data["official_gt_requests"] == [
        {
            "round": 0,
            "requested": True,
            "reason": "public checks pass; need hidden GT",
            "granted": True,
            "status": "repair_required",
            "report_ref": "agent_control/surrogate/round_0.json",
        }
    ]
    refine = graph.ready(after_gt)[0]
    assert refine.kind == "agent_turn"
    assert refine.payload["phase"] == "refine"
    assert refine.payload["report_ref"] == "agent_control/surrogate/round_0.json"
    assert refine.payload["official_gt_evaluations_remaining"] == 0
    assert refine.payload["official_gt_evaluations_used"] == 1

    # Solver asks again although the budget is exhausted.
    after_refine = graph.apply(
        after_gt,
        NodeResult(
            "solver_turn_1",
            "agent_turn",
            "succeeded",
            {"phase": "refine", "session_ref": "solver-session", "gt_request": {"requested": True}},
        ),
    )
    assert after_refine.phase == "surrogate_verifying"
    verify1 = graph.ready(after_refine)[0]
    assert verify1.invocation_id == "surrogate_verify_1"
    assert verify1.payload["gt_requested"] is True
    assert verify1.payload["official_gt_remaining"] == 0

    artifact1 = {"artifact_id": "cand-1", "storage_path": "artifacts/round_1/payload", "sha256": "b"}
    after_export = graph.apply(
        after_refine,
        NodeResult(
            "surrogate_verify_1",
            "surrogate_verify",
            "succeeded",
            {
                "status": "exported",
                "artifact_ref": artifact1,
                "report_ref": "agent_control/surrogate/round_1.json",
                "gt_consumed": False,
            },
        ),
    )
    assert after_export.phase == "freezing"
    assert after_export.data["official_gt_used"] == 1
    assert after_export.data["official_gt_requests"][-1]["granted"] is False
    after_freeze = graph.apply(
        after_export,
        NodeResult("freeze_workspace_0", "freeze_workspace", "succeeded", {"workspace_ref": "w"}),
    )
    final = graph.ready(after_freeze)[0]
    assert final.kind == "final_audit"
    assert final.payload["candidate_artifact_ref"] == artifact1
    assert final.payload["candidate_verifier_mode"] == "gt_budget"


def test_gt_budget_solver_that_never_requests_goes_straight_to_final_audit(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_budget", official_gt_budget=1),
        now_ms=lambda: 1_000,
    )
    initial = graph.initialize(context)
    after_solver = graph.apply(
        initial,
        NodeResult("solver_turn_0", "agent_turn", "succeeded", {"phase": "solve"}),
    )
    assert after_solver.phase == "surrogate_verifying"
    assert graph.ready(after_solver)[0].payload["gt_requested"] is False
    after_export = graph.apply(
        after_solver,
        NodeResult(
            "surrogate_verify_0",
            "surrogate_verify",
            "succeeded",
            {"status": "exported", "artifact_ref": {"artifact_id": "c"}, "gt_consumed": False},
        ),
    )
    assert after_export.phase == "freezing"
    assert after_export.data["official_gt_used"] == 0
    assert after_export.data["official_gt_requests"] == []


def test_gt_budget_killed_turn_with_pending_request_still_runs_gt(tmp_path: Path):
    """A turn that dies abnormally (SIGKILL / non-zero exit) after writing a
    valid GT request must still have that evaluation honored while budget
    remains, instead of being diverted to a refine turn that drops the request.
    """
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_budget", official_gt_budget=1),
        now_ms=lambda: 1_000,
    )
    initial = graph.initialize(context)
    # Solver turn ends FAILED (e.g. SIGKILL) but the worktree result file that
    # the wrapper recovered still carries a valid GT request.
    after_solver = graph.apply(
        initial,
        NodeResult(
            "solver_turn_0",
            "agent_turn",
            "failed",
            {
                "phase": "solve",
                "session_ref": "solver-session",
                "error": "agent killed (signal 9)",
                "gt_request": {"requested": True, "reason": "artifacts written; need GT"},
            },
        ),
    )
    # Honored: routed to SurrogateVerify (export + official GT), not refining.
    assert after_solver.phase == "surrogate_verifying"
    assert after_solver.data["solver_turn_status"] == "failed"
    verify = graph.ready(after_solver)[0]
    assert verify.payload["gt_requested"] is True
    assert verify.payload["official_gt_remaining"] == 1


def test_gt_budget_killed_turn_without_request_refines(tmp_path: Path):
    """A failed turn that did not write a GT request keeps the old behavior:
    fall back to a proxy refine turn (budget untouched)."""
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_budget", official_gt_budget=1),
        now_ms=lambda: 1_000,
    )
    initial = graph.initialize(context)
    after_solver = graph.apply(
        initial,
        NodeResult(
            "solver_turn_0",
            "agent_turn",
            "failed",
            {"phase": "solve", "session_ref": "solver-session", "error": "agent killed (signal 9)"},
        ),
    )
    assert after_solver.phase == "refining"
    assert after_solver.data["refine_round"] == 1


def test_gt_budget_passed_gt_freezes_immediately(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(candidate_verifier_mode="gt_budget", official_gt_budget=2),
        now_ms=lambda: 1_000,
    )
    state = graph.apply(
        graph.initialize(context),
        NodeResult("solver_turn_0", "agent_turn", "succeeded", {"phase": "solve", "gt_request": {"requested": True}}),
    )
    state = graph.apply(
        state,
        NodeResult(
            "surrogate_verify_0",
            "surrogate_verify",
            "succeeded",
            {"status": "passed", "artifact_ref": {"artifact_id": "c"}, "gt_consumed": True},
        ),
    )
    assert state.phase == "freezing"
    assert state.data["official_gt_used"] == 1


def test_solver_nonzero_exit_resumes_same_session_after_parallel_setup(tmp_path: Path):
    context = _context(tmp_path)
    calls: list[tuple[str, str, str | None]] = []
    graph = TerminalTaskGraph(TerminalTaskConfig(max_refine_rounds=2), now_ms=lambda: 1_000)

    def runner(invocation, _context):
        calls.append((invocation.kind, invocation.invocation_id, invocation.payload.get("session_key")))
        if invocation.invocation_id == "solver_turn_0":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "failed",
                {"phase": "solve", "session_ref": "solver-session", "telemetry": {"duration_ms": 25}},
                error="agent command failed: output writer exited 1",
            )
        if invocation.kind == "verifier_plan":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"plan_ref": "plan"})
        if invocation.invocation_id == "solver_turn_1":
            assert invocation.payload["phase"] == "refine"
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"phase": "refine", "session_ref": "solver-session"})
        if invocation.kind == "surrogate_verify":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"status": "passed", "artifact_ref": "artifact"})
        if invocation.kind == "freeze_workspace":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"workspace_ref": "frozen"})
        if invocation.kind == "final_audit":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"status": "passed", "result_ref": "result"})
        raise AssertionError(invocation.kind)

    output = GraphExecutor(
        graph,
        {kind: runner for kind in ("agent_turn", "verifier_plan", "surrogate_verify", "freeze_workspace", "final_audit")},
        state_store=GraphStateStore(context.run_dir),
    ).run(context)

    assert output.status == "completed"
    assert [item[1] for item in calls if item[0] == "agent_turn"] == ["solver_turn_0", "solver_turn_1"]
    assert output.payload["solver_session_ref"] == "solver-session"
    assert output.payload["last_solver_error"] == "agent command failed: output writer exited 1"


def test_solver_infrastructure_error_fails_without_refine_spin(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(TerminalTaskConfig(candidate_verifier_mode="gt_primary"))
    calls: list[str] = []

    def runner(invocation, _context):
        calls.append(invocation.invocation_id)
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "failed",
            {
                "phase": "solve",
                "termination_reason": "infrastructure_error",
                "telemetry": {"duration_ms": 25},
            },
            error="persistent FMJob worker failed twice",
        )

    output = GraphExecutor(
        graph,
        {"agent_turn": runner},
        state_store=GraphStateStore(context.run_dir),
    ).run(context)

    assert output.status == "failed"
    assert calls == ["solver_turn_0"]
    assert output.payload["last_solver_termination_reason"] == "infrastructure_error"


def test_graph_records_verifier_compile_repair_attempts(tmp_path: Path):
    graph = TerminalTaskGraph()
    state = graph.initialize(_context(tmp_path))
    result = NodeResult(
        "verifier_plan_0",
        "verifier_plan",
        "succeeded",
        {
            "bundle_ref": "controller/verifier/bundle",
            "session_ref": "verifier-session",
            "compile_repair_count": 1,
            "compile_attempts": [
                {"attempt": 1, "status": "failed"},
                {"attempt": 2, "status": "succeeded"},
            ],
        },
    )

    updated = graph.apply(state, result)

    assert updated.data["verifier_compile_repair_count"] == 1
    assert len(updated.data["verifier_compile_attempts"]) == 2


def test_graph_preserves_compile_attempts_when_repair_still_fails(tmp_path: Path):
    graph = TerminalTaskGraph()
    state = graph.initialize(_context(tmp_path))
    attempts = [
        {"attempt": 1, "status": "failed"},
        {"attempt": 2, "status": "failed"},
    ]

    updated = graph.apply(
        state,
        NodeResult(
            "verifier_plan_0",
            "verifier_plan",
            "failed",
            {"session_ref": "verifier-session", "compile_attempts": attempts},
            error="static validation failed",
        ),
    )

    assert updated.status == "failed"
    assert updated.data["verifier_compile_attempts"] == attempts
    assert updated.data["verifier_compile_repair_count"] == 1


def test_agent_wall_time_exhaustion_still_freezes_and_runs_final_audit(tmp_path: Path):
    context = _context(tmp_path)
    calls: list[str] = []
    clock = {"now": 1_000}
    graph = TerminalTaskGraph(
        TerminalTaskConfig(max_refine_rounds=3, max_agent_wall_time_sec=1),
        now_ms=lambda: clock["now"],
    )

    def runner(invocation, _context):
        calls.append(invocation.invocation_id)
        if invocation.kind == "agent_turn":
            clock["now"] = 2_100
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"phase": invocation.payload["phase"], "turn_status": "timed_out"},
            )
        if invocation.kind == "verifier_plan":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"plan_ref": "plan"},
            )
        if invocation.kind == "surrogate_verify":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "repair_required", "report_ref": "report"},
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"workspace_ref": "frozen"},
            )
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "succeeded",
            {"status": "passed", "result_ref": "gt-result"},
        )

    output = GraphExecutor(
        graph,
        {kind: runner for kind in (
            "agent_turn",
            "verifier_plan",
            "surrogate_verify",
            "freeze_workspace",
            "final_audit",
        )},
        state_store=GraphStateStore(context.run_dir),
    ).run(context)

    assert output.status == "completed"
    assert "solver_turn_1" not in calls
    assert calls[-2:] == ["freeze_workspace_0", "final_audit_0"]


def test_terminal_task_graph_final_audit_failure_does_not_repair_current_run(tmp_path: Path):
    context = _context(tmp_path)
    calls: list[str] = []
    graph = TerminalTaskGraph(TerminalTaskConfig(max_refine_rounds=3), now_ms=lambda: 1_000)

    def runner(invocation, _context):
        calls.append(invocation.invocation_id)
        if invocation.kind == "agent_turn":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"phase": invocation.payload["phase"], "session_ref": "solver-session"},
            )
        if invocation.kind == "verifier_plan":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"plan_ref": "plan"})
        if invocation.kind == "surrogate_verify":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "passed", "report_ref": "report", "artifact_ref": "artifact"},
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"workspace_ref": "frozen"})
        if invocation.kind == "final_audit":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "failed", "result_ref": "gt-result"},
            )
        raise AssertionError(invocation.kind)

    output = GraphExecutor(
        graph,
        {kind: runner for kind in (
            "agent_turn",
            "verifier_plan",
            "surrogate_verify",
            "freeze_workspace",
            "final_audit",
        )},
        state_store=GraphStateStore(context.run_dir),
    ).run(context)

    assert output.status == "failed"
    assert "solver_turn_1" not in calls
    assert calls[-1] == "final_audit_0"


def test_terminal_task_graph_ignores_legacy_refine_round_limit(tmp_path: Path):
    context = _context(tmp_path)
    calls: list[str] = []
    graph = TerminalTaskGraph(TerminalTaskConfig(max_refine_rounds=1), now_ms=lambda: 1_000)

    def runner(invocation, _context):
        calls.append(invocation.invocation_id)
        if invocation.kind == "agent_turn":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"phase": invocation.payload["phase"], "session_ref": "solver"},
            )
        if invocation.kind == "verifier_plan":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"plan_ref": "plan"})
        if invocation.kind == "surrogate_verify":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {
                    "status": "passed"
                    if invocation.payload["round"] >= 2
                    else "repair_required",
                    "report_ref": "report",
                    "artifact_ref": "artifact",
                },
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"workspace_ref": "frozen"})
        if invocation.kind == "final_audit":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"status": "passed"})
        raise AssertionError(invocation.kind)

    output = GraphExecutor(
        graph,
        {kind: runner for kind in (
            "agent_turn",
            "verifier_plan",
            "surrogate_verify",
            "freeze_workspace",
            "final_audit",
        )},
        state_store=GraphStateStore(context.run_dir),
    ).run(context)

    assert output.status == "completed"
    assert calls.count("solver_turn_0") == 1
    assert calls.count("solver_turn_1") == 1
    assert calls.count("solver_turn_2") == 1


def test_proxy_refine_round_limit_defaults_to_ten(tmp_path: Path):
    context = _context(tmp_path)
    graph = TerminalTaskGraph(
        TerminalTaskConfig(max_agent_wall_time_sec=3600), now_ms=lambda: 1_000
    )
    calls: list[str] = []

    def runner(invocation, _context):
        calls.append(invocation.invocation_id)
        if invocation.kind == "agent_turn":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"phase": invocation.payload["phase"], "session_ref": "solver"},
            )
        if invocation.kind == "verifier_plan":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"plan_ref": "plan"})
        if invocation.kind == "surrogate_verify":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "repair_required", "report_ref": "report", "artifact_ref": "artifact"},
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"workspace_ref": "frozen"})
        if invocation.kind == "final_audit":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"status": "passed"})
        raise AssertionError(invocation.kind)

    output = GraphExecutor(
        graph,
        {kind: runner for kind in (
            "agent_turn", "verifier_plan", "surrogate_verify", "freeze_workspace", "final_audit"
        )},
        state_store=GraphStateStore(context.run_dir),
    ).run(context)

    assert output.status == "completed"
    assert output.payload["refine_round"] == 10
    assert sum(item.startswith("solver_turn_") for item in calls) == 11
    assert sum(item.startswith("surrogate_verify_") for item in calls) == 11


def test_graph_executor_reuses_completed_terminal_run_without_new_nodes(tmp_path: Path):
    context = _context(tmp_path)
    calls = Counter()
    graph = TerminalTaskGraph(now_ms=lambda: 1_000)

    def runner(invocation, _context):
        calls[invocation.invocation_id] += 1
        if invocation.kind == "agent_turn":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"phase": "solve"})
        if invocation.kind == "verifier_plan":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"plan_ref": "plan"})
        if invocation.kind == "surrogate_verify":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "passed", "artifact_ref": "artifact"},
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"workspace_ref": "frozen"})
        return NodeResult(invocation.invocation_id, invocation.kind, "succeeded", {"status": "passed"})

    kwargs = dict(
        graph=graph,
        runners={kind: runner for kind in (
            "agent_turn",
            "verifier_plan",
            "surrogate_verify",
            "freeze_workspace",
            "final_audit",
        )},
        state_store=GraphStateStore(context.run_dir),
    )
    first = GraphExecutor(**kwargs).run(context)
    second = GraphExecutor(**kwargs).run(context)

    assert first.status == second.status == "completed"
    assert all(value == 1 for value in calls.values())


def test_graph_executor_recovers_completed_parallel_node_from_pending_result(tmp_path: Path):
    """Controller 在并行栅栏中断后，恢复时不应丢掉已完成的 Verifier。"""

    context = _context(tmp_path)
    graph = TerminalTaskGraph(TerminalTaskConfig(max_refine_rounds=0))
    store = GraphStateStore(context.run_dir)
    store.initialize(graph.initialize(context))
    store.record_pending(
        NodeResult(
            "verifier_plan_0",
            "verifier_plan",
            "succeeded",
            {"plan_ref": "controller/verifier/plan.json"},
        )
    )
    calls: list[str] = []

    def runner(invocation, _context):
        calls.append(invocation.invocation_id)
        if invocation.kind == "agent_turn":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"phase": "solve"},
            )
        if invocation.kind == "surrogate_verify":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"status": "passed", "report_ref": "report"},
            )
        if invocation.kind == "freeze_workspace":
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "succeeded",
                {"workspace_ref": "frozen"},
            )
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "succeeded",
            {"status": "passed", "result_ref": "gt"},
        )

    output = GraphExecutor(
        graph,
        {kind: runner for kind in (
            "agent_turn",
            "verifier_plan",
            "surrogate_verify",
            "freeze_workspace",
            "final_audit",
        )},
        state_store=store,
        config=GraphExecutorConfig(max_workers=2),
    ).run(context)

    assert output.status == "completed"
    assert calls[0] == "solver_turn_0"
    assert "verifier_plan_0" not in calls
    assert "surrogate_verify_0" in calls
