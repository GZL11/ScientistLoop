"""SOTA Search Validity Verifier 的 contract 和持久化测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from famou_scientist.loop.domain.goal import load_goal
from famou_scientist.loop.evaluation.evaluator import DummyEvaluatorAdapter
from famou_scientist.loop.facilities import validate_validity_verdict
from famou_scientist.loop.runtime.orchestrator import Orchestrator, OrchestratorConfig


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_validity_verdict_requires_binary_status_and_reason_for_invalid():
    valid = validate_validity_verdict({"status": "valid"})
    assert valid["status"] == "valid"
    assert valid["reasons"] == []

    invalid = validate_validity_verdict(
        {
            "status": "invalid",
            "reasons": ["target extraction"],
            "evidence_refs": ["candidate/run.py"],
            "violations": [
                {
                    "rule": "no target lookup",
                    "evidence": "loaded validation target as answer table",
                    "evidence_refs": ["candidate/run.py"],
                }
            ],
        }
    )
    assert invalid["status"] == "invalid"
    assert invalid["violations"][0]["rule"] == "no target lookup"

    with pytest.raises(ValueError, match="valid 或 invalid"):
        validate_validity_verdict({"status": "uncertain"})
    with pytest.raises(ValueError, match="至少一个 reason"):
        validate_validity_verdict({"status": "invalid"})
    with pytest.raises(ValueError, match="至少一个 evidence_ref"):
        validate_validity_verdict({"status": "invalid", "reasons": ["violation"]})


class _Verifier:
    def __init__(self):
        self.calls = []

    def verify_candidate(self, candidate, *, context, session_key, resume):
        self.calls.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "task_id": context["task_id"],
                "task": dict(context["task"]),
                "session_key": session_key,
                "resume": resume,
            }
        )
        if len(self.calls) == 1:
            return {
                "status": "invalid",
                "reasons": ["hard-coded target mapping"],
                "evidence_refs": ["candidate/run.py:12"],
                "violations": [],
                "session_ref": "verifier-session-1",
            }
        return {"status": "valid", "session_ref": "verifier-session-2"}


def test_validity_verifier_persists_feedback_and_resumes(tmp_path: Path):
    goal = load_goal(FIXTURES / "goals" / "dummy_algorithm_innovation.yaml")
    goal["benchmark_task"] = {
        "type": "naturebench",
        "task_id": "task-validity-test",
        "private_dir": "/must-not-be-forwarded",
    }
    verifier = _Verifier()
    orchestrator = Orchestrator(
        tmp_path / "run",
        goal,
        evaluator=DummyEvaluatorAdapter(),
        validity_verifier=verifier,
        config=OrchestratorConfig(
            min_ideas=0,
            max_ticks=1,
            validity_verifier_enabled=True,
        ),
    )
    state = orchestrator.state_store.init(goal)
    attempt_id = orchestrator.expbank.create_attempt(
        idea={"id": "idea-1", "title": "candidate"},
        lineage_id="lineage-1",
    )
    branch = {
        "branch_id": "branch-1",
        "expbank_attempt_id": attempt_id,
    }
    source = tmp_path / "candidate-source"
    source.mkdir()
    source.joinpath("run.py").write_text("print('ok')\n", encoding="utf-8")
    branch.update(
        orchestrator.candidates.create(
            {
                "worktree": str(source),
                "branch_id": "branch-1",
                "expbank_attempt_id": attempt_id,
            }
        )
    )

    verdict = orchestrator._run_validity_verifier(
        state,
        branch,
        public_result={"valid": True, "metrics": {"score": 1.0}},
        official_result=None,
        evaluator_refs=["artifacts/public_eval.json"],
    )
    assert verdict["status"] == "invalid"
    assert verifier.calls[0]["resume"] is False
    assert verifier.calls[0]["task_id"] == "task-validity-test"
    assert "private_dir" not in verifier.calls[0]["task"]
    branch["validity_invalid"] = True
    orchestrator._record_benchmark_result(
        state,
        {"id": "evaluation-item-1"},
        branch,
        {"valid": True, "metrics": {"score": 1.0}},
        None,
        ["artifacts/public_eval.json"],
    )
    assert state["research_state"]["branches"][0]["status"] == "failed"
    orchestrator._run_validity_verifier(
        state,
        branch,
        public_result={"valid": True, "metrics": {"score": 2.0}},
        official_result=None,
        evaluator_refs=["artifacts/public_eval-2.json"],
    )
    assert verifier.calls[1]["resume"] is True
    assert state["research_state"]["validity_verifier"]["last_status"] == "valid"
    assert state["research_state"]["validity_verifier"]["session_ref"] == "verifier-session-2"
    record = orchestrator.expbank.read_attempt(attempt_id)
    assert (orchestrator.expbank.root / attempt_id / "evidence/validity_verdict.json").is_file()
    assert record["attempt_id"] == attempt_id
