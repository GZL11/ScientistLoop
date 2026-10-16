"""跨任务经验从「库」到「Idea Agent」这一段的四个口径。

2026-09-06 的 A/B 之后逐条查出来的：库那边的内容闸门修好了，但 Agent 实际收到的
东西没修。实测一个 w/ 臂 run 的 `public/context.json`，20 条经验长这样：

    {"domain": "protein_biology", "result": "stopped", "best_score": 0.0904,
     "task_summary": null, "summary_path": "/.../s41467-....md"}

20 行互相无法区分——同一个 domain、`result` 全是 `stopped`、`task_summary` 全是
null，只有一个浮点数不同。Agent 只能盲开文件：222/224 次 Idea 调用确实读了库，
共打开 148 个 Markdown，其中有内容的 12 个（8.1%）。

本组锁住四条：

1. `result` 是成绩档位，投影时从 `best_score` 派生，不读存量的生命周期状态
2. 目录条目带 `evolution_summary`，索引一行就能判断相关性
3. `task_summary` 由 Loop 侧从公开题面写入，不再永远是 null
4. 库的两层形态（index.jsonl + 六个领域目录）就是 Agent 的检索面；调度器不再
   替它预选 20 条，载荷里只给目录路径
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou_scientist.loop.runtime.orchestrator import Orchestrator
from famou_scientist.loop.storage.cross_task_expbank import (
    CrossTaskExpBank,
    achievement_level,
    catalog_projection,
)


AGENT_MD = "## 演化摘要\n\n把逐实例反馈接进选择规则。\n\n## When to use\n- 有逐实例回执\n"


def _record(**overrides):
    base = {
        "task_id": "s41592-022-01709-7",
        "run_id": "run-1",
        "domain": "cellular_omics",
        "result": "stopped",
        "best_score": 0.42,
        "judge_verdict": "valid",
        "evolution_markdown": AGENT_MD,
    }
    base.update(overrides)
    return base


# --- 1. result 是成绩档位，不是生命周期状态 ---------------------------


@pytest.mark.parametrize(
    "best_score,expected",
    [
        (0.1821, "surpass_sota"),
        (0.10001, "surpass_sota"),
        (0.1, "match_sota"),          # 边界含在 match 一侧
        (0.0, "match_sota"),
        (-0.0001, "below_sota"),
        (-50.6, "below_sota"),        # 离线脚本旧实现会把这个叫 match_sota
        (None, "no_valid_score"),
        (float("nan"), "no_valid_score"),
        (float("inf"), "no_valid_score"),
        (True, "no_valid_score"),     # bool 是 int 的子类，不能当分数
    ],
)
def test_achievement_level_thresholds(best_score, expected):
    assert achievement_level(best_score) == expected


def test_projection_derives_result_and_ignores_the_stored_status():
    """存量记录里 `result` 存的是 `stopped`；目录里必须是按分数算出来的档位。"""

    item = catalog_projection(_record(result="stopped", best_score=0.42))
    assert item["result"] == "surpass_sota"


def test_rebuild_catalog_upgrades_legacy_lifecycle_values(tmp_path: Path):
    """口径变更不需要数据迁移：重建时重算，系统层保留原值做审计。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_record(best_score=-0.9))
    # 模拟旧代码写下的系统记录：result 是生命周期状态
    system = bank.system_index_path
    rows = [json.loads(line) for line in system.read_text().splitlines() if line.strip()]
    for row in rows:
        row["result"] = "stopped"
    system.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    bank.rebuild_catalog()

    catalog = [
        json.loads(line)
        for line in bank.index_path.read_text().splitlines()
        if line.strip()
    ]
    assert [item["result"] for item in catalog] == ["below_sota"]
    assert bank.records()[0]["result"] == "stopped"


# --- 2/3. 目录字段与下发载荷 -------------------------------------------


def test_catalog_carries_the_evolution_summary(tmp_path: Path):
    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_record())
    entry = json.loads(bank.index_path.read_text().splitlines()[0])
    assert "把逐实例反馈接进选择规则" in entry["evolution_summary"]


def test_catalog_keeps_the_task_summary(tmp_path: Path):
    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_record(task_summary="预测酶最适 pH；输入序列，输出连续值"))
    entry = json.loads(bank.index_path.read_text().splitlines()[0])
    assert entry["task_summary"].startswith("预测酶最适 pH")


def test_idea_payload_no_longer_pre_selects_cross_task_experience():
    """跨任务经验走目录，不进载荷——选哪几篇是 Agent 自己的活。

    以前调度器用 ``search()`` 替它选「同领域最多 20 条」塞进 ``experience[]``。
    删掉的直接理由：那个窗口按写入时间排序，同一任务的多次重跑会连成一片。
    2026-09-06 那批 A/B 里 cellular_omics 有 33 条同领域条目、其中有内容的
    3 条，前 20 条里一条都没有——那 4 个任务的处理臂等价于对照臂。
    """

    source = inspect.getsource(Orchestrator._idea_experience)
    # 只看代码，不看 docstring——那里会提到 cross_task_expbank_dir
    code = source.split('"""')[-1]
    assert "cross_task" not in code
    assert "_cross_task_expbank" not in code
    assert not hasattr(Orchestrator, "_cross_task_idea_experience")


def test_idea_context_carries_the_cross_task_directory():
    """载荷里唯一该有的跨任务字段：目录路径本身。"""

    from famou_scientist.loop.agents import workers

    source = inspect.getsource(workers.PromptWorkerSet.generate_ideas)
    assert '"cross_task_expbank_dir": self._cross_task_expbank_dir(goal)' in source


def test_base_summary_writes_a_task_summary():
    """历史上没人写这个字段，于是它在库里、在载荷里都永远是 null。"""

    source = inspect.getsource(Orchestrator._base_experience_summary)
    assert '"task_summary": self._public_task_summary()' in source


def _stub(public_dir: Path | None):
    task = {"public_dir": str(public_dir)} if public_dir is not None else {}
    return SimpleNamespace(goal_doc={"benchmark_task": task})


def test_public_task_summary_reads_title_and_objective(tmp_path: Path):
    problem = tmp_path / "problem"
    problem.mkdir()
    (problem / "README.md").write_text(
        "# Enzyme Optimum pH Prediction\n"
        "\n"
        "## 1. Scientific Problem\n"
        "\n"
        "背景段落，不应进入摘要。\n"
        "\n"
        "## 2. Task Objective\n"
        "\n"
        "Given enzyme protein sequences, predict the catalytic optimum pH.\n"
        "\n"
        "## 3. Data\n"
        "\n"
        "别的内容。\n",
        encoding="utf-8",
    )
    summary = Orchestrator._public_task_summary(_stub(problem))
    assert summary is not None
    assert summary.startswith("Enzyme Optimum pH Prediction")
    assert "predict the catalytic optimum pH" in summary
    assert "背景段落" not in summary
    assert "别的内容" not in summary


def test_public_task_summary_is_absent_without_a_public_dir():
    assert Orchestrator._public_task_summary(_stub(None)) is None


def test_public_task_summary_survives_a_missing_readme(tmp_path: Path):
    assert Orchestrator._public_task_summary(_stub(tmp_path)) is None


# --- 4. 目录形态与剂量计数 ---------------------------------------------
#
# 不再有「调度器替 Agent 选 20 条」这一步。库的形态本身就是 Agent 的检索面：
# 外层 index.jsonl + 六个领域目录，每个目录下一篇篇演化总结。


def _seed(bank: CrossTaskExpBank, task_id: str, run_id: str, score: float) -> None:
    bank.upsert_summary(
        _record(task_id=task_id, run_id=run_id, best_score=score)
    )


def test_bank_layout_is_index_plus_domain_dirs(tmp_path: Path):
    """两层结构是 Agent 自己检索的前提，不能被改掉。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    _seed(bank, "task-a", "run-a", 0.3)

    root = bank.root
    assert (root / "index.jsonl").is_file()
    assert (root / "README.md").is_file()
    assert (root / "cellular_omics" / "task-a--run-a.md").is_file()
    # 六个官方领域目录一直在，空的也在——Agent 靠 ls 就能知道有哪些领域
    assert sorted(p.name for p in root.iterdir() if p.is_dir()) == [
        "biomedical_modeling",
        "cellular_omics",
        "molecular_design",
        "physical_modeling",
        "protein_biology",
        "relational_reasoning",
    ]


def test_index_lines_are_self_describing(tmp_path: Path):
    """Agent 靠 grep 一行就要能判断相关性，所以这几个字段缺一不可。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(
        _record(task_summary="预测酶最适 pH；输入序列，输出连续值", best_score=0.42)
    )

    entry = json.loads(bank.index_path.read_text().splitlines()[0])
    assert entry["domain"] == "cellular_omics"
    assert entry["task_summary"].startswith("预测酶最适 pH")
    assert entry["result"] == "surpass_sota"
    assert entry["best_score"] == 0.42
    assert "把逐实例反馈接进选择规则" in entry["evolution_summary"]
    assert entry["summary_path"] == "cellular_omics/s41592-022-01709-7--run-1.md"


def test_grep_by_domain_is_enough_to_narrow_down(tmp_path: Path):
    """提示词让 Agent `grep '"domain": "..."'`，索引必须支持这种用法。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    _seed(bank, "task-a", "run-a", 0.3)
    bank.upsert_summary(
        _record(task_id="task-b", run_id="run-b", domain="Protein Biology")
    )

    lines = bank.index_path.read_text(encoding="utf-8").splitlines()
    hits = [line for line in lines if '"domain": "cellular_omics"' in line]
    assert len(hits) == 1
    assert "task-a--run-a" in hits[0]


def test_domain_counts_is_just_a_count(tmp_path: Path):
    """剂量指标只记客观数量，不记「我们替它选了哪些」。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    for index in range(3):
        _seed(bank, f"task-{index}", f"run-{index}", 0.1 * index)
    bank.upsert_summary(
        _record(task_id="task-p", run_id="run-p", domain="Protein Biology")
    )

    assert bank.domain_counts() == {"cellular_omics": 3, "protein_biology": 1}


def test_search_is_gone(tmp_path: Path):
    """回归点：调度器不再替 Agent 决定看哪 20 条。"""

    assert not hasattr(CrossTaskExpBank, "search")
    assert not hasattr(CrossTaskExpBank, "read_summary")
