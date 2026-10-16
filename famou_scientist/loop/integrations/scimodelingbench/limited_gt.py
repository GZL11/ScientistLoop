"""Agent-directed GT queries with a durable deadline and sealed final selection.

All mutations run under the harness's WorkspaceRunLock. Query reservations are
persisted before calling the evaluator, including failed/uncertain calls. A
restart never renews time, refunds a query, or retries an uncertain final audit.
"""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any, Callable

from ...execution.agent_turn import AgentTurnRequest
from ...execution.sandbox import sandbox_from_config
from ...execution.workspace import AgentWorkspace
from ...facilities import ArtifactRef
from ...facilities.contracts import EvaluationRequest
from ...facilities.contracts import artifact_sha256
from ...utils import atomic_write_json, new_id, now_ms
from .benchmark import _validate_submission_size
from .task_catalog import task_spec


PROTOCOL = "scimodelingbench-limited-gt-v1"
RESULT_FILENAME = "famou_scimodeling_result.json"


class LimitedGTSession:
    """Trusted task-wide budget, frozen selections, and final-audit journal."""

    def __init__(
        self, *, run_dir: Path, task_id: str, budget: int, wall_time_sec: float,
        evaluator: Any, clock: Callable[[], int] = now_ms,
        experiment: dict[str, Any] | None = None,
    ):
        if budget < 0 or not math.isfinite(wall_time_sec) or wall_time_sec <= 0:
            raise ValueError("GT budget must be nonnegative and wall time positive")
        self.run_dir = run_dir.resolve()
        self.task_id = task_spec(task_id).task_id
        self.evaluator = evaluator
        self.clock = clock
        self.root = self.run_dir / "controller" / "limited_gt"
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.path = self.root / "state.json"
        contract = dict(protocol=PROTOCOL, task_id=self.task_id,
                        gt_budget=budget, wall_time_sec=wall_time_sec,
                        experiment=experiment or {})
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if any(self.state.get(key) != value for key, value in contract.items()):
                raise ValueError("cannot change limited-GT protocol/budget on resume; use a new run")
        else:
            if (self.run_dir / "research_state.yaml").exists():
                raise ValueError("limited GT requires an independent run, not a legacy search run")
            started = clock()
            self.state = {
                **contract, "started_at": started,
                "deadline_at": started + int(wall_time_sec * 1000),
                "status": "researching", "queries": [], "turns": 0,
                "selected_artifact": None, "events": [], "feedback": None,
            }
            self.save()

    def save(self) -> None:
        atomic_write_json(self.path, self.state)

    def remaining_sec(self) -> float:
        return max(0.0, (self.state["deadline_at"] - self.clock()) / 1000)

    def public_context(self) -> dict[str, Any]:
        used = len(self.state["queries"])
        selected = self.state["selected_artifact"]
        return {
            "protocol": PROTOCOL, "task_id": self.task_id,
            "gt_budget": self.state["gt_budget"], "gt_used": used,
            "gt_remaining": self.state["gt_budget"] - used,
            "deadline_unix_ms": self.state["deadline_at"],
            "remaining_seconds": self.remaining_sec(),
            "selected_submission_sha256": selected["sha256"] if selected else None,
            "feedback": self.state["feedback"],
            "uncertain_queries": [q["number"] for q in self.state["queries"]
                                  if q["status"] == "reserved"],
        }

    def freeze(self, worktree: Path, relative: str) -> ArtifactRef:
        """Copy a regular JSON file into a controller-owned candidate snapshot."""
        rel = Path(relative)
        if not relative or not rel.parts or rel.is_absolute() or ".." in rel.parts:
            raise ValueError("submission must be a relative path inside the worktree")
        # Open components relative to pinned directory descriptors so replacing
        # a parent with a symlink cannot race the trusted snapshot reader.
        parent_fd = os.open(worktree, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in rel.parts[:-1]:
                child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = child_fd
            fd = os.open(rel.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024**2:
                raise ValueError("submission must be a regular file <= 64 MiB")
            raw = stream.read(64 * 1024**2 + 1)
        if len(raw) > 64 * 1024**2:
            raise ValueError("submission exceeds 64 MiB")
        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            raise ValueError("submission must be a JSON array")
        _validate_submission_size(candidates, task_spec(self.task_id))
        # Re-encoding rejects NaN/Infinity anywhere in the submitted object.
        encoded = json.dumps(candidates, allow_nan=False).encode()
        candidate_id = new_id("limited_gt_candidate")
        candidate_root = self.run_dir / "candidates" / candidate_id
        artifact = candidate_root / "output" / "submission"
        artifact.mkdir(parents=True)
        candidate_root.chmod(0o700)
        target = artifact / "submission.json"
        target.write_bytes(encoded)
        target.chmod(0o444)
        artifact.chmod(0o555)
        return ArtifactRef.from_path(
            artifact, artifact_id=candidate_id, kind="candidate_submission",
            producer=PROTOCOL,
        )

    def _evaluate(self, artifact: ArtifactRef, phase: str) -> dict[str, Any]:
        artifact.verify()
        result = self.evaluator.evaluate(EvaluationRequest(
            task_id=self.task_id, attempt_id=artifact.artifact_id,
            artifact_ref=artifact, metadata={"phase": phase, "protocol": PROTOCOL},
        ))
        return result.to_dict()

    def act(self, output: dict[str, Any], worktree: Path) -> dict[str, Any]:
        """Process an explicit action after the Agent yields its current turn."""
        if self.state["status"] != "researching" or self.remaining_sec() <= 0:
            return {"accepted": False, "reason": "research_closed"}
        action = output.get("action")
        feedback: dict[str, Any] = {"action": action, "accepted": False}
        if action == "query" and len(self.state["queries"]) >= self.state["gt_budget"]:
            feedback["reason"] = "gt_budget_exhausted; continue public-data research"
        elif action in {"query", "select"}:
            try:
                artifact = self.freeze(worktree, str(output.get("submission") or ""))
                if self.remaining_sec() <= 0:
                    return {"accepted": False, "reason": "deadline_reached_during_snapshot"}
                if action == "select":
                    self.state["selected_artifact"] = artifact.to_dict()
                    feedback.update(accepted=True, sha256=artifact.sha256)
                else:
                    entry = {"number": len(self.state["queries"]) + 1,
                             "requested_at": self.clock(), "artifact": artifact.to_dict(),
                             "reason": str(output.get("reason") or ""),
                             "status": "reserved"}
                    self.state["queries"].append(entry)
                    self.save()  # Spend before I/O: crashes cannot refund/replay GT.
                    try:
                        entry["result"] = self._evaluate(artifact, "research_query")
                        entry["status"] = "completed"
                    except Exception as exc:
                        entry.update(status="error", error=f"{type(exc).__name__}: {exc}")
                    entry["finished_at"] = self.clock()
                    feedback.update(accepted=True, query_number=entry["number"],
                                    result=entry.get("result"), error=entry.get("error"))
            except (OSError, ValueError, TypeError) as exc:
                feedback["reason"] = f"public_format_error: {exc}"
        elif action == "finish":
            if self.state["selected_artifact"] is None:
                feedback["reason"] = "select a submission before finishing"
            else:
                self.state["status"] = "locked"
                self.state["locked_at"] = self.clock()
                feedback["accepted"] = True
        elif action == "continue":
            feedback["accepted"] = True
        else:
            feedback["reason"] = "write action=query/select/continue/finish and end this turn"
        self.state["feedback"] = feedback
        self.state["events"].append({"at": self.clock(), **feedback})
        self.save()
        return feedback

    def finalize(self) -> dict[str, Any]:
        """Audit only the Agent's frozen selection; never select by GT score."""
        if "summary" in self.state:
            return self.state["summary"]
        self.state["status"] = "locked"
        self.state.setdefault("locked_at", self.clock())
        self.save()
        raw = self.state["selected_artifact"]
        audit = self.state.get("final_audit")
        if raw is not None and audit is None:
            audit = {"status": "started", "started_at": self.clock()}
            self.state["final_audit"] = audit
            self.save()  # No automatic re-audit after an uncertain crash.
            try:
                audit["result"] = self._evaluate(ArtifactRef.from_dict(raw), "final_audit")
                audit["status"] = "completed"
            except Exception as exc:
                audit.update(status="error", error=f"{type(exc).__name__}: {exc}")
            audit["finished_at"] = self.clock()
            self.save()
        result = (audit or {}).get("result") or {}
        valid = result.get("valid") is True
        metrics = result.get("metrics") or {}
        score = metrics.get("score") if valid else None
        if not isinstance(score, (float, int)) or not math.isfinite(score):
            score = None
        summary = {
            "task_id": self.task_id, "protocol": PROTOCOL,
            "agent_graph": "scimodeling_budget", "status": "completed",
            "outcome": "final_scored" if score is not None else
                       "no_final_submission" if raw is None else "final_evaluation_failed",
            "official_gt_budget": self.state["gt_budget"],
            "official_gt_used": len(self.state["queries"]),
            "experiment": self.state["experiment"],
            "final_score": score, "final_evaluation": audit,
            "selected_artifact": raw,
            "timing": {key: self.state[key] for key in
                       ("started_at", "deadline_at", "locked_at", "wall_time_sec")},
        }
        self.state.update(status="completed", summary=summary)
        self.save()
        atomic_write_json(self.run_dir / "controller" / "run_summary.json", summary)
        return summary


def run_limited_gt(harness: Any) -> dict[str, Any]:
    """Compose the existing CLI session runtime with the budget controller."""
    config = harness.config
    root = harness.run_dir / "limited_gt_agents"
    manifest = root / "branches" / "researcher" / "manifest.json"
    workspace = (AgentWorkspace.open(root, "researcher") if manifest.exists()
                 else AgentWorkspace.create(root, "researcher"))
    seconds = (config.max_wall_time_hours if config.max_wall_time_hours is not None else 2) * 3600
    session = LimitedGTSession(
        run_dir=harness.run_dir, task_id=config.task_id,
        budget=config.official_gt_budget, wall_time_sec=seconds,
        evaluator=harness.evaluation_facility,
        experiment={
            "public_input_sha256": artifact_sha256(config.problem_dir),
            "model": harness._model_for_role("scimodeling_researcher"),
            "runtime": config.solver_runtime or config.implement_runtime or config.agent_runtime,
            "cpu": config.available_cpu, "gpu": config.available_gpu,
            "memory_gib": config.available_memory_gib,
        },
    )
    agent_config = harness._agent_config(role="scimodeling_researcher", timeout_override_sec=seconds)
    adapter = harness.agent_adapter.create_turn(agent_config)
    sandbox = sandbox_from_config(agent_config.get("sandbox"), workspace.root)
    from ...prompts import load_prompt

    instruction = load_prompt("benchmark_managed/scimodeling_limited_gt_v1.md")
    try:
        while session.state["status"] == "researching" and session.remaining_sec() > 0:
            session.state["turns"] += 1
            session.save()
            context = {
                **session.public_context(),
                "problem_dir": str(config.problem_dir.resolve()),
                "data_dir": str(config.problem_dir.resolve() / "data"),
                "resource_limits": {
                    **harness.resource_envelope,
                    "cpu": config.available_cpu,
                    "memory": (f"{config.available_memory_gib}Gi"
                               if config.available_memory_gib is not None else None),
                },
                "action_file": str(workspace.worktree / RESULT_FILENAME),
                "task_contract": harness.benchmark_facility.task_view().to_dict(),
            }
            workspace.write_public_json("budget.json", context)
            result = adapter.run(AgentTurnRequest(
                role="scimodeling_researcher", phase="research",
                session_key="scimodeling_researcher", instruction=instruction,
                workspace=workspace, sandbox=sandbox, context=context,
                completion_mode="natural_exit", timeout_sec=session.remaining_sec(),
            ))
            atomic_write_json(session.root / f"turn_{session.state['turns']:05d}.json", {
                "status": result.status, "output": dict(result.output),
                "error": result.error, "telemetry": dict(result.telemetry),
            })
            if result.status == "succeeded":
                session.act(dict(result.output), workspace.worktree)
            else:
                # An infrastructure/runtime failure is resumable but does not
                # grant a fresh deadline or consume a GT query.
                session.state["feedback"] = {"agent_error": result.error}
                session.save()
                timed_out = (result.failure.get("timed_out") is True or
                             result.failure.get("error_code") in {"timeout", "timed_out"})
                if session.remaining_sec() > 0 and not timed_out:
                    raise RuntimeError(f"research agent failed: {result.error}")
        return session.finalize()
    finally:
        sandbox.close()
