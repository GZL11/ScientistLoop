"""独立于 SOTA Search 的 TerminalTaskGraph Harness 组合根。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any, Mapping

from ..domain.graph import GraphContext
from ..execution.agent_turn import AgentTurnRequest
from ..execution.sandbox import sandbox_from_config
from ..execution.workspace import AgentWorkspace
from ..facilities.contracts import ArtifactRef, artifact_sha256
from ..graphs.terminal_task import (
    GT_ONLY_MODES,
    FinalAuditRunner,
    FreezeWorkspaceRunner,
    SolverTurnRunner,
    SurrogateVerifyRunner,
    TerminalTaskConfig,
    TerminalTaskGraph,
    VerifierCompilerRunner,
    VerifierPlanStore,
)
from ..runtime.graph_executor import GraphExecutor, GraphExecutorConfig
from ..storage.graph_state import GraphStateStore
from ..utils import atomic_write_json, now_ms


@dataclass(frozen=True)
class TerminalTaskHarnessConfig:
    task_id: str
    run_dir: Path
    problem_dir: Path
    final_workspace_dir: Path
    solver_agent: Mapping[str, Any]
    verifier_agent: Mapping[str, Any]
    agent_source_dir: Path | None = None
    # Deprecated compatibility field; no longer limits the refine loop.
    max_refine_rounds: int = 0
    max_agent_wall_time_sec: int = 4 * 60 * 60
    # Number of Solver refine turns triggered by Proxy (initial solve excluded).
    max_proxy_refine_rounds: int = 10
    candidate_verifier_mode: str = "proxy"
    # gt_budget 模式下 Solver 可主动申请的官方 GT 次数；FinalAudit 不计入。
    official_gt_budget: int = 1
    # Independent from Solver refine budget; controls verifier bundle repair.
    max_verifier_compile_repairs: int = 5


class TerminalTaskHarness:
    """装配双 Agent、公开 surrogate 和唯一官方 FinalAudit。"""

    def __init__(
        self,
        config: TerminalTaskHarnessConfig,
        *,
        agent_adapter: Any,
        benchmark_facility: Any,
        evaluation_facility: Any,
    ) -> None:
        self.config = config
        self.agent_adapter = agent_adapter
        self.benchmark_facility = benchmark_facility
        self.evaluation_facility = evaluation_facility

    def run(self) -> dict[str, Any]:
        config = self.config
        create_turn = getattr(self.agent_adapter, "create_turn", None)
        if not callable(create_turn):
            raise TypeError("TerminalTaskGraph 要求 AgentAdapter 实现 create_turn()")
        task_hash = artifact_sha256(config.problem_dir)
        agent_source_dir = config.agent_source_dir or config.problem_dir
        agent_root = config.run_dir / "terminal_task_agents"
        solver_workspace = self._workspace(
            agent_root,
            "solver",
            source_dir=agent_source_dir,
            metadata={"role": "terminal_solver", "task_input_hash": task_hash},
        )
        verifier_workspace = self._workspace(
            agent_root,
            "verifier",
            source_dir=agent_source_dir,
            metadata={"role": "terminal_verifier", "task_input_hash": task_hash},
        )
        solver_config = dict(config.solver_agent)
        solver_adapter = create_turn(solver_config)
        verifier_config = dict(config.verifier_agent)
        verifier_adapter = None
        if config.candidate_verifier_mode not in GT_ONLY_MODES:
            verifier_adapter = create_turn(verifier_config)
        solver_sandbox = sandbox_from_config(
            solver_config.get("sandbox"), solver_workspace.root
        )
        verifier_sandbox = (
            sandbox_from_config(verifier_config.get("sandbox"), verifier_workspace.root)
            if verifier_adapter is not None
            else None
        )
        task_view = self.benchmark_facility.task_view()
        instruction = str(task_view.instructions or "").strip()
        if not instruction:
            instruction_path = config.problem_dir / "INSTRUCTIONS.md"
            if instruction_path.is_file():
                instruction = instruction_path.read_text(encoding="utf-8")
        if not instruction:
            raise ValueError("TerminalTaskGraph 缺少公开任务 instructions")

        diagnose = None
        if config.candidate_verifier_mode not in GT_ONLY_MODES:
            diagnose = self._diagnoser(
                adapter=verifier_adapter,
                workspace=verifier_workspace,
                sandbox=verifier_sandbox,
                instruction=instruction,
                run_dir=config.run_dir,
            )
        context = GraphContext(
            run_id=config.run_dir.name,
            run_dir=config.run_dir,
            workspace_dir=solver_workspace.worktree,
            task_id=config.task_id,
            metadata={"task_input_hash": task_hash},
        )
        graph = TerminalTaskGraph(
            TerminalTaskConfig(
                max_refine_rounds=config.max_refine_rounds,
                max_agent_wall_time_sec=config.max_agent_wall_time_sec,
                max_proxy_refine_rounds=config.max_proxy_refine_rounds,
                candidate_verifier_mode=config.candidate_verifier_mode,
                official_gt_budget=config.official_gt_budget,
            )
        )
        executor = GraphExecutor(
            graph,
            {
                "agent_turn": SolverTurnRunner(
                    solver_adapter,
                    solver_workspace,
                    solver_sandbox,
                    instruction,
                    resource_limits={
                        "cpu": getattr(solver_sandbox, "cpu", None),
                        "memory": getattr(solver_sandbox, "memory", None),
                        "gpu": getattr(solver_sandbox, "gpu", None),
                        "worker_policy": "worker_count_must_not_exceed_allocated_cpu",
                    },
                ),
                "verifier_plan": VerifierCompilerRunner(
                    verifier_adapter,
                    verifier_workspace,
                    verifier_sandbox,
                    instruction,
                    task_hash,
                    task_root=config.problem_dir,
                    max_compile_repairs=config.max_verifier_compile_repairs,
                ),
                "surrogate_verify": SurrogateVerifyRunner(
                    self.benchmark_facility,
                    solver_workspace,
                    task_root=config.problem_dir,
                    diagnose=diagnose,
                    verifier_mode=config.candidate_verifier_mode,
                ),
                "freeze_workspace": FreezeWorkspaceRunner(
                    artifact_paths=getattr(self.benchmark_facility, "artifact_paths", None)
                ),
                "final_audit": FinalAuditRunner(self.evaluation_facility),
            },
            state_store=GraphStateStore(config.run_dir),
            config=GraphExecutorConfig(max_workers=2),
        )
        started_at = now_ms()
        try:
            output = executor.run(context)
        finally:
            # Persistent FMJob workers belong to this task, not to the Python
            # controller process.  Always release them after graph completion
            # or an unexpected controller exception.
            solver_sandbox.close()
            if verifier_sandbox is not None:
                verifier_sandbox.close()
            close_benchmark = getattr(self.benchmark_facility, "close", None)
            if callable(close_benchmark):
                close_benchmark()
        final_ref = output.payload.get("final_workspace_ref")
        if isinstance(final_ref, Mapping):
            artifact = ArtifactRef.from_dict(final_ref)
            artifact.verify()
            self._publish_workspace(Path(artifact.storage_path), config.final_workspace_dir)
        summary = {
            "task_id": config.task_id,
            "status": output.status,
            "outcome": (
                "final_audit_passed"
                if output.status == "completed"
                else "final_audit_failed"
                if output.payload.get("final_audit_ref")
                else "graph_failed_before_final_audit"
            ),
            "agent_graph": "terminal_task",
            "candidate_verifier_mode": config.candidate_verifier_mode,
            "graph_version": graph.version,
            "refine_rounds": int(output.payload.get("refine_round") or 0),
            "max_proxy_refine_rounds": config.max_proxy_refine_rounds,
            # 官方 GT 候选级评测预算与实际使用情况（gt_budget 模式）。
            "official_gt_budget": output.payload.get("official_gt_budget"),
            "official_gt_used": output.payload.get("official_gt_used"),
            "official_gt_requests": output.payload.get("official_gt_requests") or [],
            "solver_session_ref": output.payload.get("solver_session_ref"),
            "verifier_session_ref": output.payload.get("verifier_session_ref"),
            "verifier_plan_ref": output.payload.get("verifier_plan_ref"),
            "verifier_bundle_ref": output.payload.get("verifier_bundle_ref"),
            "verifier_bundle_hash": output.payload.get("verifier_bundle_hash"),
            "verifier_compile_status": output.payload.get("verifier_compile_status"),
            "verifier_self_test_status": output.payload.get("verifier_self_test_status"),
            "verifier_compile_attempts": output.payload.get("verifier_compile_attempts"),
            "verifier_compile_repair_count": output.payload.get(
                "verifier_compile_repair_count"
            ),
            "last_surrogate_report_ref": output.payload.get("last_surrogate_report_ref"),
            "current_candidate_artifact_ref": output.payload.get(
                "current_candidate_artifact_ref"
            ),
            "last_valid_candidate_artifact_ref": output.payload.get(
                "last_valid_candidate_artifact_ref"
            ),
            "final_workspace_ref": final_ref,
            "final_audit_ref": output.payload.get("final_audit_ref"),
            "failure": output.error,
            "workspace": str(config.final_workspace_dir),
            "timing": {
                "started_at": started_at,
                "finished_at": now_ms(),
                # Terminal-Bench 的一小时限制属于 SolverAgent；VerifierAgent
                # 与环境准备并行/独立计时，不应从 Solver 预算中扣除。
                "agent_wall_time_budget_sec": config.max_agent_wall_time_sec,
                "solver_wall_time_budget_sec": config.max_agent_wall_time_sec,
                "verifier_agent_wall_time_budget_sec": float(
                    config.verifier_agent.get("timeout_sec")
                    or config.max_agent_wall_time_sec
                ),
                "solver_elapsed_sec": float(output.payload.get("solver_elapsed_ms") or 0)
                / 1000.0,
                "verifier_runs_in_parallel": True,
                "final_audit_outside_agent_budget": True,
            },
        }
        atomic_write_json(config.run_dir / "controller" / "run_summary.json", summary)
        return summary

    @staticmethod
    def _workspace(
        root: Path,
        branch_id: str,
        *,
        source_dir: Path,
        metadata: Mapping[str, Any],
    ) -> AgentWorkspace:
        manifest = root / "branches" / branch_id / "manifest.json"
        if manifest.is_file():
            return AgentWorkspace.open(root, branch_id)
        return AgentWorkspace.create(
            root,
            branch_id,
            source_dir=source_dir,
            metadata=metadata,
        )

    @staticmethod
    def _diagnoser(*, adapter, workspace, sandbox, instruction, run_dir):
        def diagnose(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
            artifact_raw = evidence.get("artifact_ref")
            if not isinstance(artifact_raw, Mapping):
                return {"status": "verifier_error", "checks": []}
            artifact = ArtifactRef.from_dict(artifact_raw)
            artifact.verify()
            round_no = int(evidence.get("round") or 0)
            verifier_plan = VerifierPlanStore(run_dir).load()
            snapshot = workspace.worktree / "surrogate_snapshots" / f"round_{round_no}"
            if snapshot.exists():
                shutil.rmtree(snapshot)
            shutil.copytree(artifact.storage_path, snapshot)
            result = adapter.run(
                AgentTurnRequest(
                    role="terminal_verifier",
                    phase="diagnose",
                    session_key="terminal_verifier",
                    instruction=instruction,
                    workspace=workspace,
                    sandbox=sandbox,
                    context={
                        "round": round_no,
                        "snapshot": str(snapshot),
                        "verifier_plan": verifier_plan,
                        "evidence": dict(evidence),
                    },
                    completion_mode="structured_result",
                )
            )
            if result.status != "succeeded":
                return {
                    "status": "verifier_error",
                    "checks": [],
                    "error": result.error,
                }
            return dict(result.output)

        return diagnose

    @staticmethod
    def _publish_workspace(source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for child in list(destination.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)


__all__ = ["TerminalTaskHarness", "TerminalTaskHarnessConfig"]
