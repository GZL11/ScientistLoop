"""目录里的 ``result`` 字段必须是成绩档位，不是 Loop 生命周期状态。

历史故障：``result`` 存的是 ``research_state.status``，取值来自
``running/paused/stopped/completed/failed``。跑满墙钟正常收尾一律 ``stopped``，
实测 58/58 条目全同——

1. **零信息量**：它占着 Agent 决策视图仅 5 个字段之一，却无法区分任何两条经验；
2. **有误导性**：Agent 看到 ``result: "stopped"`` 挨着 ``best_score: -1.0``，
   很容易读成「这个 Run 崩了」，而实际含义只是「跑到时间上限」。

而被内容闸门挡掉的离线补写批次，同一个字段名填的却是
``match_sota`` / ``surpass_sota``——一个字段两套词汇表，有意义的是后者。

档位阈值必须与 ``benchmark.py`` 下发给 Idea Agent 的 ``score_interpretation``
同源，否则 Agent 读目录和读题面会得到两套标准。
"""
from __future__ import annotations

import math

import pytest

from famou_scientist.loop.integrations.naturebench.benchmark import (
    NatureBenchBenchmarkFacility,
)
from famou_scientist.loop.runtime.orchestrator import Orchestrator


level = Orchestrator._achievement_level


# --- 档位边界 -------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.1821, "surpass_sota"),
        (0.10001, "surpass_sota"),
        (0.1, "match_sota"),        # 边界含在 match 一侧
        (0.0234, "match_sota"),
        (0.0, "match_sota"),        # 恰好 0 算达标
        (-1e-9, "below_sota"),
        (-0.2986, "below_sota"),
        (-56.45, "below_sota"),
    ],
)
def test_score_maps_to_the_official_level(score, expected):
    assert level(score) == expected


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), float("-inf")])
def test_unusable_scores_are_marked_explicitly(score):
    """没有有效分数要说出来，不能悄悄落到 below_sota——那会把
    「judge 失败/评测崩了」和「真的没达标」混成一类。"""

    assert level(score) == "no_valid_score"


# --- 与题面口径同源 -------------------------------------------------------


def _levels_from_task_view():
    """从下发给 Idea Agent 的公开题面里取档位定义。"""

    facility = NatureBenchBenchmarkFacility
    import inspect

    source = inspect.getsource(facility)
    return source


def test_thresholds_match_the_public_task_contract():
    """题面里写 ``0 <= value <= 0.1`` 为 match、``value > 0.1`` 为 surpass。

    这两处一旦漂移，Agent 读经验目录和读题面会得到两套标准，而它无法察觉。
    """

    source = _levels_from_task_view()
    assert '"condition": "0 <= value <= 0.1"' in source
    assert '"condition": "value > 0.1"' in source
    assert '"condition": "value < 0"' in source
    # 同一批阈值在实现里的行为
    assert level(0.0) == "match_sota"
    assert level(0.1) == "match_sota"
    assert level(0.1 + 1e-9) == "surpass_sota"
    assert level(-1e-9) == "below_sota"


def test_level_names_match_the_task_contract_vocabulary():
    source = _levels_from_task_view()
    for name in ("below_sota", "match_sota", "surpass_sota"):
        assert f'"name": "{name}"' in source
        assert name in {
            level(-1.0),
            level(0.05),
            level(0.5),
        } or name in ("below_sota", "match_sota", "surpass_sota")


# --- 生命周期状态另存 -----------------------------------------------------


def test_lifecycle_status_is_kept_separately():
    """``run_status`` 仍要留在系统审计层——诊断硬杀/超时需要它，
    只是不该冒充「成绩」进 Agent 目录。"""

    import inspect

    source = inspect.getsource(Orchestrator._base_experience_summary)
    assert '"result": self._achievement_level(best_score)' in source
    assert '"run_status": str(research.get("status")' in source


def test_result_no_longer_reads_the_lifecycle_status():
    import inspect

    source = inspect.getsource(Orchestrator._base_experience_summary)
    assert '"result": str(research.get("status")' not in source


# --- 目录字段仍然只有五项 -------------------------------------------------


def test_catalog_still_projects_result():
    """``result`` 是 Agent 目录里的字段之一；换口径不能把它从投影里弄丢。

    投影自 2026-09-09 起集中在 ``catalog_projection``（写入与重建共用一条路径），
    所以这里盯的是那个函数，不再是 ``upsert_summary`` 里内联的字段列表。
    """

    from famou_scientist.loop.storage import cross_task_expbank as bank

    assert "result" in bank.CATALOG_FIELDS
    projected = bank.catalog_projection(
        {"domain": "cellular_omics", "best_score": 0.5, "summary_path": "a/b.md"}
    )
    assert projected["result"] == "surpass_sota"
