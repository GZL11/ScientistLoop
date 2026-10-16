"""跨任务经验库的两道闸门：合规 + 内容。

历史故障：``agent_visible`` 只看合规判定（``judge_verdict``），与总结质量正交。
结果目录里 107 条有 90 条是复盘失败后的兜底残次品（只有方法标题 + 分数 + refine
血缘，没有 ``When to use`` / ``When not to use``），而 39 条 Agent 手写的好总结
因为缺一张合规票据（其中 35 条 ``judge_verdict`` 为 ``None``，从没判过）被挡在
目录外——过滤器与质量正交，且恰好是反的。

库的写入、重建、分发是三个独立关口，任何一处漏改都会让闸门失效：

- ``CrossTaskExpBank.upsert_summary``  写入
- ``CrossTaskExpBank.rebuild_catalog`` 重建
- ``sync_cross_task_expbank.seed_run`` 分发

本组把三处一起锁住。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from famou_scientist.loop.examples.naturebench.fmjob import sync_cross_task_expbank as sync
from famou_scientist.loop.storage.cross_task_expbank import (
    CrossTaskExpBank,
    is_agent_visible,
)


AGENT_MD = "## 演化摘要\n\n把逐实例反馈接进选择规则。\n\n## When to use\n- 有逐实例回执\n"


def _summary(**overrides):
    base = {
        "task_id": "s41592-022-01709-7",
        "run_id": "run-1",
        "domain": "Cellular Omics",
        "result": "completed",
        "judge_verdict": "valid",
        "evolution_markdown": AGENT_MD,
    }
    base.update(overrides)
    return base


# --- 判据本身 -------------------------------------------------------------


def test_agent_written_and_judge_valid_is_visible():
    assert is_agent_visible(_summary()) is True


def test_fallback_summary_is_hidden_even_when_judge_valid():
    """兜底总结没有 evolution_markdown —— 这是它与 Agent 手写的唯一可靠区别。"""

    record = _summary()
    record.pop("evolution_markdown")
    record.update(
        {
            "method_summary": "正式评测有效，当前候选成为新的最佳方法。",
            "successful_ideas": ["0001: Shell-count-agnostic radial profile; score=0.39"],
            "refine_summary": ["0005 基于 0001: ..."],
        }
    )

    assert is_agent_visible(record) is False


def test_offline_backfill_is_hidden_although_it_has_markdown():
    """离线补写有 markdown，光看字段存在性挡不住它。"""

    assert is_agent_visible(_summary(offline_generated=True)) is False


def test_blank_markdown_counts_as_absent():
    assert is_agent_visible(_summary(evolution_markdown="   \n  ")) is False


@pytest.mark.parametrize("verdict", ["invalid", None, "", "unknown"])
def test_non_valid_verdicts_stay_hidden(verdict):
    """合规闸门不能被内容闸门抵消：作弊方案的经验传播出去有害。"""

    assert is_agent_visible(_summary(judge_verdict=verdict)) is False


def test_missing_verdict_key_stays_hidden():
    record = _summary()
    record.pop("judge_verdict")
    assert is_agent_visible(record) is False


@pytest.mark.parametrize(
    "verdict",
    ["valid", "Valid", " VALID ", True, {"is_valid": True}, {"status": "valid"}],
)
def test_verdict_shapes_that_count_as_valid(verdict):
    assert is_agent_visible(_summary(judge_verdict=verdict)) is True


# --- 关口一：写入 ---------------------------------------------------------


def test_upsert_publishes_markdown_for_a_visible_record(tmp_path: Path):
    bank = CrossTaskExpBank(tmp_path / "bank")
    record = bank.upsert_summary(_summary())

    assert record["agent_visible"] is True
    assert (bank.root / record["summary_path"]).is_file()
    assert record["summary_path"] in _catalog_paths(bank)


def test_upsert_withholds_a_fallback_record(tmp_path: Path):
    bank = CrossTaskExpBank(tmp_path / "bank")
    fallback = _summary()
    fallback.pop("evolution_markdown")

    record = bank.upsert_summary(fallback)

    assert record["agent_visible"] is False
    assert not (bank.root / record["summary_path"]).is_file()
    assert _catalog_paths(bank) == set()
    # 但审计层必须留档，否则事后无法诊断复盘为什么失败。
    assert len(bank.records()) == 1


def test_upsert_retracts_a_previously_published_summary(tmp_path: Path):
    """同一 Run 重跑后复盘失败时，旧的好总结不能继续留在目录里冒充新结论。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    good = bank.upsert_summary(_summary())
    assert (bank.root / good["summary_path"]).is_file()

    degraded = _summary()
    degraded.pop("evolution_markdown")
    bank.upsert_summary(degraded)

    assert not (bank.root / good["summary_path"]).is_file()
    assert _catalog_paths(bank) == set()


# --- 关口二：重建 ---------------------------------------------------------


def test_rebuild_catalog_applies_both_gates(tmp_path: Path):
    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_summary(task_id="t-good", run_id="r-good"))
    fallback = _summary(task_id="t-fallback", run_id="r-fallback")
    fallback.pop("evolution_markdown")
    bank.upsert_summary(fallback)
    bank.upsert_summary(
        _summary(task_id="t-invalid", run_id="r-invalid", judge_verdict="invalid")
    )
    bank.upsert_summary(
        _summary(task_id="t-offline", run_id="r-offline", offline_generated=True)
    )

    published = bank.rebuild_catalog()

    assert published == 1
    assert _catalog_paths(bank) == {"cellular_omics/t-good--r-good.md"}


def test_rebuild_is_idempotent(tmp_path: Path):
    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_summary())

    assert bank.rebuild_catalog() == bank.rebuild_catalog() == 1


def test_rebuild_removes_orphan_markdown(tmp_path: Path):
    """口径收紧后，旧的已发布文件会留在库里成为孤儿。

    ``upsert_summary`` 只撤回它当次写的那一篇，所以新增内容闸门之后，
    之前按旧口径发布的 .md 仍在磁盘上——实测一次收紧后磁盘 88 篇、
    目录只收录 58 篇。它们不会被 Agent 读到（``seed_run`` 会物理删除
    快照里未收录的文件），但会在事后诊断时误导。
    """

    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_summary(task_id="t-keep", run_id="r-keep"))
    orphan = bank.root / "cellular_omics" / "t-orphan--r-orphan.md"
    orphan.write_text("# 旧口径遗留\n", encoding="utf-8")

    bank.rebuild_catalog()

    assert not orphan.exists()
    assert (bank.root / "cellular_omics" / "t-keep--r-keep.md").is_file()


def test_rebuild_keeps_the_readme(tmp_path: Path):
    """README 在库根，不该被孤儿清理波及。"""

    bank = CrossTaskExpBank(tmp_path / "bank")
    bank.upsert_summary(_summary())

    bank.rebuild_catalog()

    assert (bank.root / "README.md").is_file()


# --- 关口三：分发 ---------------------------------------------------------


def _seed_bank(root: Path, rows: list[dict]) -> Path:
    """构造一个最小可用的库：index + system 兄弟文件 + md。"""

    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    public, system = [], []
    for row in rows:
        relative = f"{row['domain']}/{row['task_id']}--{row['run_id']}.md"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {row['task_id']}\n", encoding="utf-8")
        public.append(json.dumps({"domain": row["domain"], "summary_path": relative}))
        system.append(
            json.dumps(
                {
                    "task_id": row["task_id"],
                    "run_id": row["run_id"],
                    "summary_path": relative,
                    "judge_verdict": row.get("judge_verdict", "valid"),
                    "judge_model": "gpt-5.5",
                    "evolution_markdown": row.get("evolution_markdown", AGENT_MD),
                    "offline_generated": row.get("offline_generated", False),
                }
            )
        )
    (root / "index.jsonl").write_text("\n".join(public) + "\n", encoding="utf-8")
    (root.parent / f".{root.name}.system.jsonl").write_text(
        "\n".join(system) + "\n", encoding="utf-8"
    )
    return root


def _snapshot_paths(run_dir: Path) -> set[str]:
    text = (
        run_dir / "shared_experience_pool" / "cross_task_expbank" / "index.jsonl"
    ).read_text(encoding="utf-8")
    return {json.loads(l)["summary_path"] for l in text.splitlines() if l.strip()}


def test_seed_run_excludes_fallback_and_offline(tmp_path: Path):
    source = _seed_bank(
        tmp_path / "bank",
        [
            {"task_id": "t-good", "run_id": "r1", "domain": "cellular_omics"},
            {
                "task_id": "t-fallback",
                "run_id": "r2",
                "domain": "cellular_omics",
                "evolution_markdown": "",
            },
            {
                "task_id": "t-offline",
                "run_id": "r3",
                "domain": "cellular_omics",
                "offline_generated": True,
            },
            {
                "task_id": "t-invalid",
                "run_id": "r4",
                "domain": "cellular_omics",
                "judge_verdict": "invalid",
            },
        ],
    )
    run = tmp_path / "run"

    sync.seed_run(source, run, exclude_task_id="t-other", judge_model="gpt-5.5")

    assert _snapshot_paths(run) == {"cellular_omics/t-good--r1.md"}


def test_seed_run_still_excludes_the_current_task(tmp_path: Path):
    """内容闸门不能覆盖自任务屏蔽——两者都要生效。"""

    source = _seed_bank(
        tmp_path / "bank",
        [
            {"task_id": "t-self", "run_id": "r1", "domain": "cellular_omics"},
            {"task_id": "t-other", "run_id": "r2", "domain": "cellular_omics"},
        ],
    )
    run = tmp_path / "run"

    sync.seed_run(source, run, exclude_task_id="t-self", judge_model="gpt-5.5")

    assert _snapshot_paths(run) == {"cellular_omics/t-other--r2.md"}
    assert not list((run / "shared_experience_pool").rglob("*t-self*"))


def test_seed_run_drops_the_markdown_of_filtered_records(tmp_path: Path):
    """不只从 index 剔除——文件必须物理删掉，否则 Agent 绕过 index 就能读到。"""

    source = _seed_bank(
        tmp_path / "bank",
        [
            {"task_id": "t-good", "run_id": "r1", "domain": "cellular_omics"},
            {
                "task_id": "t-fallback",
                "run_id": "r2",
                "domain": "cellular_omics",
                "evolution_markdown": "",
            },
        ],
    )
    run = tmp_path / "run"

    sync.seed_run(source, run, judge_model="gpt-5.5")

    names = {
        p.name
        for p in (run / "shared_experience_pool" / "cross_task_expbank").glob("*/**/*.md")
    }
    assert names == {"t-good--r1.md"}


# --- 三处口径必须一致 -----------------------------------------------------


def test_all_three_gates_agree_on_the_same_records(tmp_path: Path):
    """一条记录在写入、重建、分发三处的可见性判定必须相同。

    历史上提示词版本解析漏改一处（``agent_runtime.py`` 的角色白名单）时，
    60 多个单测全过、只有 e2e 抓到。这里显式对齐三处。
    """

    rows = [
        {"task_id": "t-good", "run_id": "r1", "domain": "cellular_omics"},
        {
            "task_id": "t-fallback",
            "run_id": "r2",
            "domain": "cellular_omics",
            "evolution_markdown": "",
        },
        {
            "task_id": "t-offline",
            "run_id": "r3",
            "domain": "cellular_omics",
            "offline_generated": True,
        },
        {
            "task_id": "t-invalid",
            "run_id": "r4",
            "domain": "cellular_omics",
            "judge_verdict": "invalid",
        },
    ]

    # 关口一 + 二
    bank = CrossTaskExpBank(tmp_path / "live")
    for row in rows:
        bank.upsert_summary(
            _summary(
                task_id=row["task_id"],
                run_id=row["run_id"],
                domain=row["domain"],
                judge_verdict=row.get("judge_verdict", "valid"),
                evolution_markdown=row.get("evolution_markdown", AGENT_MD),
                offline_generated=row.get("offline_generated", False),
            )
        )
    bank.rebuild_catalog()
    upserted = _catalog_paths(bank)

    # 关口三
    source = _seed_bank(tmp_path / "frozen", rows)
    run = tmp_path / "run"
    sync.seed_run(source, run, judge_model="gpt-5.5")

    assert upserted == _snapshot_paths(run) == {"cellular_omics/t-good--r1.md"}


def _catalog_paths(bank: CrossTaskExpBank) -> set[str]:
    text = bank.index_path.read_text(encoding="utf-8")
    return {json.loads(l)["summary_path"] for l in text.splitlines() if l.strip()}
