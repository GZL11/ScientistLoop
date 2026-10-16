"""Budget, deadline, final-selection and real CLI-wrapper contract tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from famou_scientist.loop.facilities.contracts import EvaluationResult
from famou_scientist.loop.harness.runtime import BenchmarkHarness, HarnessConfig
from famou_scientist.loop.integrations.scimodelingbench.limited_gt import LimitedGTSession
from famou_scientist.loop.storage.workspace import WorkspaceRunLock, WorkspaceBusyError


class Clock:
    def __init__(self):
        self.value = 1_000_000

    def __call__(self):
        return self.value


class Evaluator:
    def __init__(self):
        self.requests = []
        self.fail = False

    def evaluate(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("transport failed")
        rows = json.loads((Path(request.artifact_ref.storage_path) / "submission.json").read_text())
        return EvaluationResult(request_id=f"req-{len(self.requests)}",
                                attempt_id=request.attempt_id, valid=True,
                                metrics={"score": rows[0]["predicted_score"]})


def submission(worktree, score=0.5):
    worktree.mkdir(parents=True, exist_ok=True)
    (worktree / "submission.json").write_text(json.dumps([
        {"sequence": "AAAAAAAA", "predicted_score": score} for _ in range(32)
    ]))


def session(tmp_path, k, clock, evaluator):
    return LimitedGTSession(run_dir=tmp_path / "run", task_id="tfbind8",
                            budget=k, wall_time_sec=7200,
                            evaluator=evaluator, clock=clock)


@pytest.mark.parametrize("k", [0, 1, 5, 20])
def test_query_budget_shared_across_sources_and_resume(tmp_path, k):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, k, clock, evaluator)
    deadline = controller.state["deadline_at"]
    worktrees = [tmp_path / "actor_a", tmp_path / "actor_b"]
    for tree in worktrees:
        submission(tree)
    for index in range(k + 2):
        result = controller.act({"action": "query", "submission": "submission.json"},
                                worktrees[index % 2])
        assert result["accepted"] is (index < k)
        clock.value += 1000
        controller = session(tmp_path, k, clock, evaluator)
        assert controller.state["deadline_at"] == deadline
    assert len(evaluator.requests) == k
    assert controller.public_context()["gt_remaining"] == 0
    assert controller.act({"action": "select", "submission": "submission.json"}, worktrees[0])["accepted"]
    summary = controller.finalize()
    assert len(evaluator.requests) == k + 1
    assert summary["official_gt_used"] == k
    assert summary["final_score"] == 0.5
    assert evaluator.requests[-1].metadata["phase"] == "final_audit"
    assert session(tmp_path, k, clock, evaluator).finalize() == summary
    assert len(evaluator.requests) == k + 1


def test_agent_selection_not_best_gt_and_snapshot_is_immutable(tmp_path):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, 1, clock, evaluator)
    tree = tmp_path / "worktree"
    submission(tree, 0.9)
    controller.act({"action": "query", "submission": "submission.json"}, tree)
    assert controller.state["selected_artifact"] is None
    submission(tree, 0.4)
    controller.act({"action": "select", "submission": "submission.json"}, tree)
    submission(tree, 1.0)
    clock.value = controller.state["deadline_at"]
    assert not controller.act({"action": "select", "submission": "submission.json"}, tree)["accepted"]
    assert controller.finalize()["final_score"] == 0.4
    # No audit feedback is passed back into the Agent's public context.
    assert controller.public_context()["feedback"]["action"] == "select"
    assert not controller.act({"action": "query", "submission": "submission.json"}, tree)["accepted"]
    assert len(evaluator.requests) == 2


def test_evaluator_failure_spends_budget_and_missing_selection_has_no_audit(tmp_path):
    clock, evaluator = Clock(), Evaluator()
    evaluator.fail = True
    controller = session(tmp_path, 1, clock, evaluator)
    tree = tmp_path / "worktree"
    submission(tree)
    controller.act({"action": "query", "submission": "submission.json"}, tree)
    controller = session(tmp_path, 1, clock, evaluator)
    assert controller.public_context()["gt_remaining"] == 0
    assert controller.finalize()["outcome"] == "no_final_submission"
    assert len(evaluator.requests) == 1


def test_invalid_public_file_does_not_spend_gt(tmp_path):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, 1, clock, evaluator)
    tree = tmp_path / "worktree"
    submission(tree)
    (tree / "alias.json").symlink_to(tree / "submission.json")
    (tree / "bad.json").write_text("{}")
    for name in ["../outside.json", "alias.json", "bad.json", str(tree / "submission.json")]:
        assert not controller.act({"action": "query", "submission": name}, tree)["accepted"]
    assert len(evaluator.requests) == 0
    assert controller.public_context()["gt_remaining"] == 1


def test_gt_wait_consumes_time(tmp_path, monkeypatch):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, 2, clock, evaluator)
    tree = tmp_path / "worktree"
    submission(tree)
    controller.act({"action": "select", "submission": "submission.json"}, tree)
    original = evaluator.evaluate

    def slow(request):
        clock.value = controller.state["deadline_at"] + 1
        return original(request)

    monkeypatch.setattr(evaluator, "evaluate", slow)
    controller.act({"action": "query", "submission": "submission.json"}, tree)
    assert controller.remaining_sec() == 0
    assert not controller.act({"action": "query", "submission": "submission.json"}, tree)["accepted"]
    controller.finalize()
    assert len(evaluator.requests) == 2  # one research query plus final audit


@pytest.mark.parametrize("action", ["query", "select"])
def test_deadline_crossed_during_snapshot_rejects_action(tmp_path, monkeypatch, action):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, 1, clock, evaluator)
    tree = tmp_path / "worktree"
    submission(tree)
    original = controller.freeze

    def slow(*args):
        artifact = original(*args)
        clock.value = controller.state["deadline_at"]
        return artifact

    monkeypatch.setattr(controller, "freeze", slow)
    assert not controller.act({"action": action, "submission": "submission.json"}, tree)["accepted"]
    assert controller.state["selected_artifact"] is None
    assert not controller.state["queries"]
    assert not evaluator.requests


def test_uncertain_query_is_spent_and_never_replayed(tmp_path):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, 1, clock, evaluator)
    controller.state["queries"].append({"number": 1, "status": "reserved"})
    controller.save()
    resumed = session(tmp_path, 1, clock, evaluator)
    assert resumed.public_context()["uncertain_queries"] == [1]
    assert resumed.public_context()["gt_remaining"] == 0
    assert not resumed.act({"action": "query", "submission": "missing.json"}, tmp_path)["accepted"]
    assert not evaluator.requests


def test_worker_restart_never_replays_completed_or_uncertain_requests(tmp_path):
    from famou_scientist.loop.integrations.scimodelingbench.evaluator_worker import _iter_requests

    requests = tmp_path / "requests"
    responses = tmp_path / "responses"
    requests.mkdir()
    responses.mkdir()
    (requests / "completed.json").write_text("{}")
    (responses / "completed.json").write_text("{}")
    (responses / "completed.sig").write_text("signed")
    (requests / "uncertain.json").write_text("{}")
    (tmp_path / "CLIENT_DONE.json").write_text("{}")
    assert [p.name for p in _iter_requests(tmp_path)] == ["uncertain.json"]
    # No response: the worker could have crashed after GT and before signing.
    assert list(_iter_requests(tmp_path)) == []
    (requests / "fresh.json").write_text("{}")
    assert [p.name for p in _iter_requests(tmp_path)] == ["fresh.json"]


def test_delayed_worker_reads_each_frozen_query_not_latest_submission(tmp_path, monkeypatch):
    from famou_scientist.loop.integrations.scimodelingbench.evaluation import SciModelingBenchEvaluationFacility
    from famou_scientist.loop.integrations.scimodelingbench import evaluator_worker

    pending = []

    class Transport:
        def request(self, *, operation, attempt_id):
            pending.append({"request_id": str(len(pending)), "kind": operation,
                            "attempt_id": attempt_id})
            raise TimeoutError("worker has not read the input yet")

    class Task:
        def evaluate(self, rows):
            return {"score": rows[0]["predicted_score"], "valid": True}

    monkeypatch.setattr(evaluator_worker, "_load_task", lambda *args, **kwargs: Task())
    workspace = tmp_path / "run/workspace"
    facility = SciModelingBenchEvaluationFacility(
        Transport(), run_dir=tmp_path / "run", workspace_dir=workspace,
        benchmark_name="scimodelingbench/tfbind8")
    controller = session(tmp_path, 1, Clock(), facility)
    tree = tmp_path / "worktree"
    submission(tree, 0.9)
    controller.act({"action": "query", "submission": "submission.json"}, tree)
    submission(tree, 0.4)
    controller.act({"action": "select", "submission": "submission.json"}, tree)
    controller.finalize()
    scores = [evaluator_worker._evaluate_request(
        request=request, workspace_dir=workspace, task_id="tfbind8",
        revision=None, task_loader=None, cache_dir=None)["metrics"]["score"]
        for request in pending]
    assert scores == [0.9, 0.4]


def test_resume_cannot_change_budget_and_does_not_retry_uncertain_audit(tmp_path):
    clock, evaluator = Clock(), Evaluator()
    controller = session(tmp_path, 1, clock, evaluator)
    with pytest.raises(ValueError, match="cannot change"):
        session(tmp_path, 20, clock, evaluator)
    tree = tmp_path / "worktree"
    submission(tree)
    controller.act({"action": "select", "submission": "submission.json"}, tree)
    controller.state["status"] = "locked"
    controller.state["final_audit"] = {"status": "started"}
    controller.save()
    summary = session(tmp_path, 1, clock, evaluator).finalize()
    assert summary["outcome"] == "final_evaluation_failed"
    assert not evaluator.requests


def test_concurrent_harness_cannot_acquire_same_run(tmp_path):
    with WorkspaceRunLock(tmp_path):
        with pytest.raises(WorkspaceBusyError):
            with WorkspaceRunLock(tmp_path):
                pytest.fail("concurrent controller acquired the lock")


@pytest.mark.parametrize("k", [0, 1])
def test_harness_real_cli_wrapper_actions_and_final_audit(tmp_path, k):
    """Fake CLI executable, real adapter/session/wrapper/sandbox/evaluator proxy."""
    binary = tmp_path / "opencode"
    binary.write_text('''#!/usr/bin/env python3
import json, os
from pathlib import Path
w = Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])
c = w / 'calls.json'
n = json.loads(c.read_text()) if c.exists() else 0
c.write_text(json.dumps(n + 1))
(w / 'submission.json').write_text(json.dumps([{'sequence': 'AAAAAAAA'}]*32))
actions = ['query', 'select', 'finish']
(w / 'famou_scimodeling_result.json').write_text(json.dumps({
    'action': actions[n], 'submission': 'submission.json'
}))
print('research turn complete')
''')
    binary.chmod(0o755)
    problem = tmp_path / "problem"
    problem.mkdir()
    (problem / "task.md").write_text("public test task")

    class Transport:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def request(self, *, operation, attempt_id):
            self.calls += 1
            return {"request_id": f"r{self.calls}", "valid": True,
                    "metrics": {"score": 0.7, "primary_metric": "best_k_mean"}}

        def close(self):
            self.closed = True

    transport = Transport()
    config = HarnessConfig(
        task_id="tfbind8", run_dir=tmp_path / "run", problem_dir=problem,
        workspace_dir=tmp_path / "run/workspace", agent_runtime="opencode",
        agent_binary=str(binary), agent_graph="scimodeling_budget", model="test-model",
        benchmark_adapter="scimodelingbench", evaluator_adapter="scimodelingbench",
        official_gt_budget=k, max_wall_time_hours=0.05,
    )
    summary = BenchmarkHarness(config, transport).run()
    assert summary["final_score"] == 0.7
    assert summary["official_gt_used"] == k
    assert transport.calls == k + 1
    assert transport.closed
    calls = tmp_path / "run/limited_gt_agents/branches/researcher/worktree/calls.json"
    assert json.loads(calls.read_text()) == 3
    # Completed resume must neither reactivate the CLI nor rerun final audit.
    assert BenchmarkHarness(config, transport).run() == summary
    assert transport.calls == k + 1
    assert json.loads(calls.read_text()) == 3


def test_new_graph_rejects_attempt_limit(tmp_path):
    config = HarnessConfig(task_id="tfbind8", run_dir=tmp_path, problem_dir=tmp_path,
                           workspace_dir=tmp_path, agent_runtime="claude",
                           agent_graph="scimodeling_budget", iterations=20,
                           benchmark_adapter="scimodelingbench", evaluator_adapter="scimodelingbench")
    with pytest.raises(ValueError, match="official-gt-budget"):
        config.validate()
