"""ExpBank 每条 attempt 记录自身成绩的回归测试。

同一 lineage 的所有 attempt 共用一个 branch_id。历史实现用
`leaderboard["branch_id"] == branch["branch_id"]` 判定 promoted，于是某条 lineage
夺冠之后，其上每一次后续 attempt（哪怕更差）都会被标记为 BEST 并被写上排行榜的
分数，Agent 读到的经验池因此看不到回退。
"""
from __future__ import annotations

from types import SimpleNamespace

from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.runtime.orchestrator import Orchestrator


class _RecordingExpBank:
    """只记录 update_attempt 入参的极简 ExpBank 替身。"""

    def __init__(self) -> None:
        self.updates: list[dict] = []

    def write_evidence_json(self, *_args, **_kwargs) -> None:
        return None

    def read_attempt(self, _attempt_id: str) -> dict:
        return {"paths": {}}

    def update_attempt(self, attempt_id: str, **fields) -> None:
        self.updates.append({"attempt_id": attempt_id, **fields})


def _evaluation(value: float) -> dict:
    return {
        "valid": True,
        "official_metrics": {"aggregate_improvement": value},
    }


def _record_attempt(orch, state, branch, value):
    """复用被测的 leaderboard + ExpBank 记账逻辑跑一次 attempt。"""
    evaluation = _evaluation(value)
    promoted = orch._update_leaderboard(
        state, branch, {}, evaluation, evaluator_refs=[], commit=True
    )
    leaderboard = state.get("research_state", {}).get("leaderboard", {})
    metrics = evaluation["official_metrics"]
    metric_name = leaderboard.get("metric") or orch._primary_metric_spec()[0]
    raw = metrics.get(metric_name) if metric_name else None
    score = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    orch.expbank.update_attempt(
        branch["expbank_attempt_id"],
        status=LoopStatus.ExpBank.BEST if promoted else LoopStatus.ExpBank.EVALUATED,
        branch_id=branch.get("branch_id"),
        score=score,
        promoted=promoted,
    )
    return promoted


def _orchestrator() -> Orchestrator:
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
    orch.expbank = _RecordingExpBank()
    orch.artifacts = SimpleNamespace(record_decision=lambda *a, **k: None)
    return orch


def test_regressed_attempt_on_winning_branch_keeps_its_own_score():
    """同一 branch 夺冠后再退步，该 attempt 必须记自己的分数且不标 BEST。"""

    orch = _orchestrator()
    state: dict = {}
    branch = {"branch_id": "actor_branch_1", "artifact": None}

    branch["expbank_attempt_id"] = "0003"
    assert _record_attempt(orch, state, branch, -0.07748411191046167) is True

    # 同一 lineage 的后续 attempt：branch_id 不变，但成绩更差。
    branch["expbank_attempt_id"] = "0006"
    assert _record_attempt(orch, state, branch, -0.10121543996527377) is False

    first, second = orch.expbank.updates
    assert first["score"] == -0.07748411191046167
    assert first["promoted"] is True
    assert first["status"] == LoopStatus.ExpBank.BEST

    # 回归点：曾经写成 -0.0774/BEST/promoted=True。
    assert second["score"] == -0.10121543996527377
    assert second["promoted"] is False
    assert second["status"] == LoopStatus.ExpBank.EVALUATED

    # 排行榜仍保留全局最优，不被退步覆盖。
    assert state["research_state"]["leaderboard"]["best_value"] == -0.07748411191046167
    assert state["research_state"]["leaderboard"]["branch_id"] == "actor_branch_1"


def test_improving_attempt_on_winning_branch_is_promoted():
    """同一 branch 继续提升时，仍应刷新排行榜并标记 BEST。"""

    orch = _orchestrator()
    state: dict = {}
    branch = {"branch_id": "actor_branch_1", "artifact": None}

    branch["expbank_attempt_id"] = "0001"
    assert _record_attempt(orch, state, branch, -0.30) is True
    branch["expbank_attempt_id"] = "0002"
    assert _record_attempt(orch, state, branch, -0.12) is True

    first, second = orch.expbank.updates
    assert first["score"] == -0.30
    assert second["score"] == -0.12
    assert second["promoted"] is True
    assert state["research_state"]["leaderboard"]["best_value"] == -0.12


def test_losing_branch_attempt_records_own_score():
    """另一条 branch 的较差 attempt 记自身分数，且不改变排行榜。"""

    orch = _orchestrator()
    state: dict = {}
    winner = {"branch_id": "actor_branch_1", "expbank_attempt_id": "0001", "artifact": None}
    assert _record_attempt(orch, state, winner, -0.05) is True

    loser = {"branch_id": "actor_branch_2", "expbank_attempt_id": "0002", "artifact": None}
    assert _record_attempt(orch, state, loser, -0.44) is False

    assert orch.expbank.updates[1]["score"] == -0.44
    assert state["research_state"]["leaderboard"]["branch_id"] == "actor_branch_1"
    assert state["research_state"]["leaderboard"]["best_value"] == -0.05
