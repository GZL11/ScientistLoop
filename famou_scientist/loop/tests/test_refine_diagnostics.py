"""Refine 诊断：把量化处境交给 Agent 选择 refine/switch/fuse。

Search Policy 原本只提供两条 Idea 的文字描述。历史数据显示 refine 达标率随
差距断崖下降（差距 ≤0.05 时 73%，>0.2 时仅 5%），而 Agent 的选择几乎不随
差距变化——缺的是判据，不是选项。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from famou_scientist.loop.runtime.orchestrator import Orchestrator
from famou_scientist.loop.search.policy import PairwiseImproveSearchPolicy

import json


class _FakeExpBank:
    def __init__(self, attempts: list[dict[str, Any]]):
        self._attempts = attempts

    def all_attempts(self) -> list[dict[str, Any]]:
        return list(self._attempts)

    def read_attempt(self, attempt_id: str) -> dict[str, Any]:
        for item in self._attempts:
            if str(item.get("attempt_id")) == str(attempt_id):
                return item
        raise ValueError(attempt_id)


# NatureBench 的真实契约结构：等级与条件，不是单一阈值字段。
NATUREBENCH_LEVELS = {
    "metric": "aggregate_improvement",
    "levels": [
        {"name": "below_sota", "condition": "value < 0"},
        {"name": "match_sota", "condition": "0 <= value <= 0.1"},
        {"name": "surpass_sota", "condition": "value > 0.1"},
    ],
    "primary_target": ["match_sota", "surpass_sota"],
}


def _state(criteria: dict[str, Any] | None = NATUREBENCH_LEVELS) -> dict[str, Any]:
    """构造带 benchmark_contract 的运行时 state。"""
    if criteria is None:
        return {}
    return {
        "research_state": {
            "benchmark_contract": {
                "adapters": [{"adapter": "naturebench", "score_interpretation": criteria}]
            }
        }
    }


def _orchestrator(attempts: list[dict[str, Any]]):
    orch = Orchestrator.__new__(Orchestrator)
    orch.goal_doc = {
        "benchmarks": [
            {
                "official_metric": {
                    "name": "aggregate_improvement",
                    "direction": "higher_is_better",
                }
            }
        ]
    }
    orch.expbank = _FakeExpBank(attempts)
    return orch


def _attempt(attempt_id: str, score: float, per_instance: dict | None = None):
    record: dict[str, Any] = {"attempt_id": attempt_id, "score": score}
    if per_instance is not None:
        record["evaluation"] = {"extra": {"per_instance_improvement": per_instance}}
    return record


def test_reads_threshold_from_contract_levels():
    """阈值取自契约声明的等级条件，不做推断。

    回归点：早前实现只找 benchmarks[0].score_interpretation 里的
    match_threshold 字段，而 NatureBench 把等级放在
    benchmark_contract.adapters[*]，结构也是 levels+condition——
    结果目标线从未下发。

    只给契约原始事实（当前分、当前等级、目标等级及其分数线），差距由
    Agent 自行相减，不做二次加工。
    """

    orch = _orchestrator(
        [
            _attempt("0001", -0.50),
            _attempt("0002", -0.40),
            _attempt("0003", -0.30),
        ]
    )
    diag = orch._refine_diagnostics(_state(), {"last_attempt_id": "0003"})

    assert diag["current_score"] == -0.30
    assert diag["current_level"] == "below_sota"
    assert diag["target_level"] == "match_sota"
    assert diag["target_score"] == 0.0
    assert "gap_to_target" not in diag
    assert diag["evaluated_attempts"] == 3


def test_reports_level_above_match():
    """已进入 Match 区间时如实标注等级。"""

    orch = _orchestrator([_attempt("0001", -0.10), _attempt("0002", 0.05)])
    diag = orch._refine_diagnostics(_state(), {"last_attempt_id": "0002"})

    assert diag["current_level"] == "match_sota"
    assert diag["target_score"] == 0.0


def test_flags_when_a_better_baseline_exists_elsewhere():
    """当前分支不是全场最优时，明确指出更优基线——refine 之外还有 rebase。"""

    orch = _orchestrator(
        [
            _attempt("0001", -0.30),
            _attempt("0002", -0.05),  # 另一条血统更优
            _attempt("0003", -0.60),  # 当前分支反而更差
        ]
    )
    diag = orch._refine_diagnostics(_state(), {"last_attempt_id": "0003"})

    assert diag["current_score"] == -0.60
    assert diag["run_best_score"] == -0.05
    assert diag["run_best_attempt_id"] == "0002"
    assert diag["current_is_run_best"] is False


def test_marks_current_as_run_best():
    """当前即最优时如实标注，避免误导 Agent 去 rebase。"""

    orch = _orchestrator([_attempt("0001", -0.30), _attempt("0002", -0.10)])
    diag = orch._refine_diagnostics(_state(), {"last_attempt_id": "0002"})

    assert diag["current_is_run_best"] is True
    assert diag["run_best_attempt_id"] == "0002"


def test_surfaces_worst_instance():
    """主指标是各实例平均，最差实例主导全局但在标量里看不见。"""

    orch = _orchestrator(
        [
            _attempt("0001", -0.20),
            _attempt(
                "0002",
                -0.53,
                per_instance={
                    "3bpa_dihedral": 0.213,
                    "3bpa_1200k": 0.137,
                    "3bpa_300k": -2.118,
                    "other": 0.056,
                },
            ),
        ]
    )
    diag = orch._refine_diagnostics(_state(), {"last_attempt_id": "0002"})

    worst = diag["worst_submetric"]
    assert worst["instance"] == "3bpa_300k"
    assert worst["value"] == -2.118
    assert worst["instance_count"] == 4
    # 三个实例已达标，只被一个拖垮——这正是该定向修复的信号。
    assert worst["above_target_count"] == 3
    assert worst["others_mean"] > 0


def test_marks_run_best_when_current_leads():
    """当前即最优时如实标注。"""

    orch = _orchestrator([_attempt("0001", -0.10), _attempt("0002", 0.05)])
    diag = orch._refine_diagnostics(_state(), {"last_attempt_id": "0002"})

    assert diag["current_is_run_best"] is True


def test_omits_target_without_declared_levels():
    """契约未声明等级时不臆造差距，只给出可靠字段。"""

    orch = _orchestrator([_attempt("0001", -0.30), _attempt("0002", -0.20)])
    diag = orch._refine_diagnostics(_state(None), {"last_attempt_id": "0002"})

    assert "target_score" not in diag
    assert "target_level" not in diag
    assert "current_level" not in diag
    assert diag["run_best_score"] == -0.20


def test_returns_none_when_parent_unscored():
    """父版尚无有效分数时不下发诊断，避免给出误导性数字。"""

    orch = _orchestrator([_attempt("0001", -0.30)])
    assert orch._refine_diagnostics(_state(), {"last_attempt_id": "0009"}) is None


def test_policy_passes_diagnostics_to_agent():
    """诊断随 search_opportunity 一并交给 Agent。"""

    policy = PairwiseImproveSearchPolicy(enabled=True)
    diagnostics = {"current_score": -0.3, "target_score": 0.0}
    item = {
        "id": "item-1",
        "type": "actor_continuation",
        "payload": {
            "continuation_reason": "evaluated",
            "id": "idea-1",
            "title": "current",
            "refine_diagnostics": diagnostics,
        },
    }
    offered = {"id": "q-2", "payload": {"id": "idea-2", "title": "offered"}}

    class _Queue:
        def list(self, status=None):
            return [{"id": "q-2", "type": "idea", "payload": offered["payload"]}]

        def lease(self, item, *, owner_id, purpose):
            return offered

        def update(self, item, **kwargs):
            return item

    prepared = policy.prepare_dispatch(item, _Queue())
    opportunity = prepared["payload"]["search_opportunity"]

    assert opportunity["diagnostics"] == diagnostics
    assert opportunity["allowed_actions"] == ["refine", "switch", "fuse"]


class _FakeCandidates:
    def __init__(self, record: dict[str, Any] | None):
        self._record = record

    def read(self, candidate_id: str) -> dict[str, Any]:
        if self._record is None:
            raise ValueError(candidate_id)
        return self._record


def test_last_run_surfaces_execution_failure(tmp_path):
    """方案没跑完时，必须让 Agent 看到终止原因，而不是只看到分数。"""

    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "run.json").write_text(json.dumps({
        "returncode": 1,
        "duration_ms": 1129737,
        "observed_memory_bytes": 4670615552,
        "cuda_out_of_memory": True,
        "termination_reason": "cuda_out_of_memory",
        "stdout": "x" * 5000,
        "stderr": "Traceback ...\nCUDA out of memory",
    }), encoding="utf-8")

    orch = _orchestrator([_attempt("0001", -0.30)])
    orch.candidates = _FakeCandidates({
        "status": "run_failed",
        "error": "experiment failed with CUDA out of memory",
        "paths": {"code": str(tmp_path / "code"), "output": str(tmp_path / "output"),
                  "evidence": str(ev)},
    })
    got = orch._last_run_evidence({"last_candidate_id": "candidate_1"})

    assert got["termination_reason"] == "cuda_out_of_memory"
    assert got["cuda_out_of_memory"] is True
    assert got["duration_ms"] == 1129737
    assert got["observed_memory_bytes"] == 4670615552
    # 产物目录按 ExpBank 同构给出，供 Agent 自行深入查看。
    assert set(got["paths"]) == {"code", "output", "evidence"}
    # 不搬运 stdout/stderr 正文：给出目录即可，Agent 需要时自行查看。
    assert "stdout" not in got and "stdout_tail" not in got
    assert "stderr" not in got and "stderr_tail" not in got


def test_last_run_absent_without_candidate():
    """没有上一个候选时不下发实证字段。"""

    orch = _orchestrator([_attempt("0001", -0.30)])
    orch.candidates = _FakeCandidates(None)
    assert orch._last_run_evidence({}) is None
    assert orch._last_run_evidence({"last_candidate_id": "missing"}) is None


def test_current_idea_matches_offered_detail():
    """两侧信息必须对等，否则无法"比较二者上限"。"""

    policy = PairwiseImproveSearchPolicy(enabled=True)
    item = {
        "id": "item-1",
        "type": "actor_continuation",
        "payload": {
            "continuation_reason": "evaluated",
            "id": "idea-1",
            "title": "current",
            "hypothesis": "H",
            "method": "M",
            "implementation_plan": ["step"],
            "risks": ["r"],
            "revision": 3,
            "refine_diagnostics": {
                "current_score": -0.3,
                "current_level": "below_sota",
                "current_is_run_best": False,
                "last_run": {"termination_reason": "completed"},
            },
        },
    }

    class _Queue:
        def list(self, status=None):
            return [{"id": "q-2", "type": "idea", "payload": {"id": "idea-2"}}]

        def lease(self, item, *, owner_id, purpose):
            return {"id": "q-2", "payload": {"id": "idea-2", "title": "offered"}}

        def update(self, item, **kwargs):
            return item

    cur = policy.prepare_dispatch(item, _Queue())["payload"]["search_opportunity"]["current_idea"]

    # 回归点：曾只投影 id/title/mechanism/expected_return 四个字段。
    for key in ("hypothesis", "method", "implementation_plan", "risks"):
        assert key in cur
    assert cur["revision"] == 3
    assert cur["current_score"] == -0.3
    assert cur["current_is_run_best"] is False
    assert cur["last_run"]["termination_reason"] == "completed"
