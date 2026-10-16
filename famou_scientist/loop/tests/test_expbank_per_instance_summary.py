"""ExpBank 摘要的逐实例结果视图。

历史回归：`## 结果` 段长期只有一个聚合标量的 JSON 块。聚合分是各实例
improvement 的算术平均，单个差实例就能把它压到达标线以下，而"是哪个实例"
在标量里完全不可见。实测 79 个 opus run 的 1109 份 SUMMARY.md，含逐实例的
是 0 份；而逐实例数据本来就在同目录的 record.json（855 份）与
evidence/evaluation.json（830 份）里 —— Idea Agent 读 SUMMARY.md 的比例是
83.4%，读 evaluation.json 只有 16.8%，所以它实际看到的就是被平均掉的那个数。

同一份提取/归纳逻辑同时供 orchestrator 的 `refine_diagnostics.worst_submetric`
使用，两处口径不允许漂移。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from famou_scientist.loop.storage import ExpBank
from famou_scientist.loop.storage.expbank import (
    extract_per_instance_improvement,
    worst_instance_summary,
)


def _evaluation(per_instance: dict[str, float], **extra) -> dict:
    payload = {"per_instance_improvement": per_instance}
    payload.update(extra)
    return {
        "official_metrics": {
            "aggregate_improvement": sum(per_instance.values()) / len(per_instance)
        },
        "extra": payload,
    }


def _evaluated(bank: ExpBank, evaluation: dict, score: float) -> str:
    attempt_id = bank.create_attempt(idea={"title": "T"}, lineage_id="L")
    bank.update_attempt(
        attempt_id, status="evaluated", evaluation=evaluation, score=score
    )
    return attempt_id


def _summary(tmp_path: Path, attempt_id: str) -> str:
    return (tmp_path / "expbank" / attempt_id / "SUMMARY.md").read_text(encoding="utf-8")


# --- 提取：三处存放位置都要找到 --------------------------------------


@pytest.mark.parametrize("container", ["extra", "diagnostics_public"])
def test_extracts_per_instance_from_either_container(container: str):
    evaluation = {container: {"per_instance_improvement": {"a": 0.1, "b": -0.2}}}
    assert extract_per_instance_improvement(evaluation) == {"a": 0.1, "b": -0.2}


def test_extracts_per_instance_from_top_level():
    assert extract_per_instance_improvement(
        {"per_instance_improvement": {"a": -1.0}}
    ) == {"a": -1.0}


def test_extra_takes_precedence_over_top_level():
    """adapter 写在 extra 里的才是评测回执原文，顶层可能是旧字段。"""

    evaluation = {
        "extra": {"per_instance_improvement": {"a": 0.5}},
        "per_instance_improvement": {"a": -9.0},
    }
    assert extract_per_instance_improvement(evaluation) == {"a": 0.5}


def test_non_numeric_and_bool_values_are_dropped():
    """bool 是 int 的子类，但它不是指标。"""

    found = extract_per_instance_improvement(
        {"per_instance_improvement": {"a": 0.3, "b": "n/a", "c": True, "d": None}}
    )
    assert found == {"a": 0.3}


@pytest.mark.parametrize("evaluation", [None, {}, [], {"extra": {}}, "x"])
def test_missing_evaluation_yields_empty(evaluation):
    assert extract_per_instance_improvement(evaluation) == {}


# --- 归纳：最差实例 --------------------------------------------------


def test_worst_instance_reports_value_others_mean_and_target_count():
    worst = worst_instance_summary({"a": 0.2, "b": -0.4, "c": 0.0})
    assert worst == {
        "instance": "b",
        "value": -0.4,
        "instance_count": 3,
        # 只对非最差实例求均值，否则它会被自己拉低。
        "others_mean": pytest.approx(0.1),
        # improvement == 0 也算达标（Match 的判定是 g >= 0）。
        "above_target_count": 2,
    }


def test_worst_instance_with_single_instance_has_no_others_mean():
    worst = worst_instance_summary({"only": -0.5})
    assert worst["instance"] == "only"
    assert worst["instance_count"] == 1
    assert worst["others_mean"] is None


def test_worst_instance_empty_returns_none():
    assert worst_instance_summary({}) is None


# --- 渲染 ------------------------------------------------------------


def test_summary_renders_per_instance_table_and_worst_diagnosis(tmp_path: Path):
    bank = ExpBank(tmp_path)
    evaluation = _evaluation(
        {"human_hippocampus": -0.341732, "simulated_breast_cancer": -0.537998},
        raw_scores={
            "human_hippocampus": {"ARI": 0.394961},
            "simulated_breast_cancer": {"ARI": 0.212521},
        },
    )
    attempt_id = _evaluated(bank, evaluation, -0.439865)
    summary = _summary(tmp_path, attempt_id)

    assert "- 已达标实例：`0 / 2`" in summary
    assert (
        "- 最差实例：`simulated_breast_cancer`，improvement `-0.537998`，"
        "其余实例均值 `-0.341732`" in summary
    )
    assert "| 实例 | improvement | 原始子指标 | 达标 |" in summary
    # 最差实例排在首行并加粗，长表里不会被读漏。
    rows = [line for line in summary.splitlines() if line.startswith("| ")]
    assert rows[1].startswith("| **simulated_breast_cancer** |")
    assert "ARI=0.212521" in rows[1]
    assert "ARI=0.394961" in rows[2]
    assert rows[1].endswith("| ✗ |") and rows[2].endswith("| ✗ |")


def test_summary_marks_instances_that_already_match(tmp_path: Path):
    """部分实例达标是最关键的信号：说明该走定向补弱而不是整体重做。"""

    bank = ExpBank(tmp_path)
    per_instance = {"a": -0.0125, "b": 0.0036, "c": 0.0230}
    attempt_id = _evaluated(bank, _evaluation(per_instance), sum(per_instance.values()) / 3)
    summary = _summary(tmp_path, attempt_id)

    assert "- 已达标实例：`2 / 3`" in summary
    assert summary.count("| ✓ |") == 2
    assert summary.count("| ✗ |") == 1


def test_summary_keeps_aggregate_visible_alongside_breakdown(tmp_path: Path):
    """聚合分仍要在，否则丢掉了唯一被 leaderboard 采信的数。"""

    bank = ExpBank(tmp_path)
    attempt_id = _evaluated(bank, _evaluation({"a": -1.0, "b": 1.0}), 0.0)
    summary = _summary(tmp_path, attempt_id)

    assert "- 聚合指标：`0`（各实例 improvement 的算术平均）" in summary
    assert '"aggregate_improvement": 0.0' in summary


def test_tiny_aggregate_does_not_collapse_to_zero(tmp_path: Path):
    """近 Match 的 case 全靠这几位有效数字判断距离，不能被截断成 0。"""

    bank = ExpBank(tmp_path)
    per_instance = {"a": -0.0125181, "b": 0.0125174}
    attempt_id = _evaluated(bank, _evaluation(per_instance), -3.5325870498643645e-07)
    summary = _summary(tmp_path, attempt_id)

    assert "-3.5" in summary.split("## 结论")[0]
    assert "-0.0125181" in summary


def test_summary_without_per_instance_falls_back_to_json_block(tmp_path: Path):
    """没有逐实例数据的 adapter 不能因此丢掉聚合指标。"""

    bank = ExpBank(tmp_path)
    attempt_id = bank.create_attempt(idea={"title": "T"}, lineage_id="L")
    bank.update_attempt(
        attempt_id,
        status="evaluated",
        evaluation={"official_metrics": {"aggregate_improvement": 0.25}},
        score=0.25,
    )
    summary = _summary(tmp_path, attempt_id)

    assert '"aggregate_improvement": 0.25' in summary
    assert "最差实例" not in summary
    assert "| 实例 |" not in summary


def test_unevaluated_attempt_summary_has_no_instance_table(tmp_path: Path):
    bank = ExpBank(tmp_path)
    attempt_id = bank.create_attempt(idea={"title": "T"}, lineage_id="L")
    summary = _summary(tmp_path, attempt_id)

    assert "## 结果" in summary
    assert "最差实例" not in summary


def test_instance_names_cannot_break_the_markdown_table(tmp_path: Path):
    """实例名来自题面，含管道符会把表格切碎。"""

    bank = ExpBank(tmp_path)
    attempt_id = _evaluated(bank, _evaluation({"a|b": -0.5, "c": 0.5}), 0.0)
    summary = _summary(tmp_path, attempt_id)

    row = next(
        line
        for line in summary.splitlines()
        if line.startswith("| **a\\|b**")
    )
    # 4 列 → 5 个未转义的分隔符；转义后的那个不参与切分。
    assert row.count("|") - row.count("\\|") == 5


def test_raw_scores_accept_scalar_and_missing_entries(tmp_path: Path):
    bank = ExpBank(tmp_path)
    evaluation = _evaluation(
        {"a": -0.5, "b": 0.5}, raw_scores={"a": 0.125, "b": {"AUC": "n/a"}}
    )
    attempt_id = _evaluated(bank, evaluation, 0.0)
    summary = _summary(tmp_path, attempt_id)

    assert "| 0.125 |" in summary
    # 子指标全部非数值时留 `-`，不能渲染成 `{}`。
    assert "| - |" in summary


def test_orchestrator_worst_submetric_matches_summary_helper(tmp_path: Path):
    """两处口径共用同一实现，避免 Implement 侧与 Idea 侧诊断漂移。"""

    from famou_scientist.loop.runtime import orchestrator as orch

    assert orch.worst_instance_summary is worst_instance_summary
    assert orch.extract_per_instance_improvement is extract_per_instance_improvement
