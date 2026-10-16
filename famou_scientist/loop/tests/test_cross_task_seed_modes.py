"""跨任务经验库 A/B 批次的 seed 模式。

对照实验需要两件在原实现里没有的东西：

1. ``--empty-seed``：处理组读完整库，对照组读一个**空的但结构完好的**库。
   不能改成"不建目录"——那会让两条臂走不同的代码分支，多出第二个变量。
2. ``--seed-bank-root``：outbox 合并仍写进项目库，但 Run 快照从冻结副本 seed。
   否则先跑完的那一臂会把自己的经验写进库，后起的另一臂读到的就不是同一份库。

另外锁住已有的自任务屏蔽行为：被排除的任务不只是从 index 里去掉，
它的 Markdown 也必须从快照里物理删除，否则 Agent 绕过 index 直接 ls 就能读到。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from famou_scientist.loop.examples.naturebench.fmjob import sync_cross_task_expbank as sync


JUDGE = "gpt-5.5"


def _bank(root: Path, entries: list[tuple[str, str, str]]) -> Path:
    """构造一个最小可用的库：(task_id, domain, verdict) -> index + system + md。"""

    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("bank readme\n", encoding="utf-8")
    public: list[str] = []
    system: list[str] = []
    for task_id, domain, verdict in entries:
        relative = f"{domain}/{task_id}--run-{task_id}.md"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {task_id}\n", encoding="utf-8")
        public.append(
            json.dumps(
                {"domain": domain, "summary_path": relative, "best_score": 0.1},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        system.append(
            json.dumps(
                {
                    "task_id": task_id,
                    "run_id": f"run-{task_id}",
                    "summary_path": relative,
                    "judge_verdict": verdict,
                    "judge_model": JUDGE,
                    # 内容闸门：只有 Agent 手写总结才进目录。
                    "evolution_markdown": f"## 演化摘要\n\n{task_id} 的结论。\n",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    (root / "index.jsonl").write_text("\n".join(public) + "\n", encoding="utf-8")
    (root.parent / f".{root.name}.system.jsonl").write_text(
        "\n".join(system) + "\n", encoding="utf-8"
    )
    return root


def _snapshot(run_dir: Path) -> Path:
    return run_dir / "shared_experience_pool" / "cross_task_expbank"


def _index_paths(run_dir: Path) -> set[str]:
    text = (_snapshot(run_dir) / "index.jsonl").read_text(encoding="utf-8")
    return {
        json.loads(line)["summary_path"] for line in text.splitlines() if line.strip()
    }


def _markdown_names(run_dir: Path) -> set[str]:
    return {p.name for p in _snapshot(run_dir).glob("*/**/*.md")}


@pytest.fixture()
def bank(tmp_path: Path) -> Path:
    return _bank(
        tmp_path / "bank",
        [
            ("task-a", "physical_modeling", "valid"),
            ("task-b", "physical_modeling", "valid"),
            ("task-c", "cellular_omics", "valid"),
            ("task-d", "cellular_omics", "invalid"),
        ],
    )


# --- 对照臂：空快照 -------------------------------------------------------


def test_empty_seed_publishes_no_entries(bank: Path, tmp_path: Path):
    run = tmp_path / "run"
    result = sync.seed_run(bank, run, exclude_task_id="task-a", empty=True)

    assert result["published"] == 0
    assert _index_paths(run) == set()


def test_empty_seed_removes_every_markdown(bank: Path, tmp_path: Path):
    run = tmp_path / "run"
    sync.seed_run(bank, run, empty=True)

    # 不是"没索引到"，是文件根本不在快照里——Agent 绕过 index 也读不到。
    assert _markdown_names(run) == set()


def test_empty_seed_keeps_a_wellformed_directory(bank: Path, tmp_path: Path):
    """目录和 README 必须在：两条臂要走同一条代码分支。"""

    run = tmp_path / "run"
    sync.seed_run(bank, run, empty=True)

    snapshot = _snapshot(run)
    assert snapshot.is_dir()
    assert (snapshot / "README.md").is_file()
    assert (snapshot / "index.jsonl").is_file()


def test_empty_seed_survives_a_bank_without_readme(tmp_path: Path):
    source = _bank(tmp_path / "bank", [("task-a", "physical_modeling", "valid")])
    (source / "README.md").unlink()
    run = tmp_path / "run"

    sync.seed_run(source, run, empty=True)

    assert (_snapshot(run) / "index.jsonl").read_text(encoding="utf-8") == ""


def test_empty_seed_overwrites_an_existing_snapshot(bank: Path, tmp_path: Path):
    """重投同一个 RUN_DIR 时，上一次的完整快照必须被清掉。"""

    run = tmp_path / "run"
    sync.seed_run(bank, run, exclude_task_id="task-a")
    assert _markdown_names(run)

    sync.seed_run(bank, run, exclude_task_id="task-a", empty=True)

    assert _index_paths(run) == set()
    assert _markdown_names(run) == set()


# --- 处理臂：完整快照 + 自任务屏蔽 ---------------------------------------


def test_full_seed_drops_the_current_task_from_the_index(bank: Path, tmp_path: Path):
    run = tmp_path / "run"
    sync.seed_run(bank, run, exclude_task_id="task-a", judge_model=JUDGE)

    assert _index_paths(run) == {
        "physical_modeling/task-b--run-task-b.md",
        "cellular_omics/task-c--run-task-c.md",
    }


def test_full_seed_physically_deletes_the_current_task_markdown(
    bank: Path, tmp_path: Path
):
    run = tmp_path / "run"
    sync.seed_run(bank, run, exclude_task_id="task-a", judge_model=JUDGE)

    assert "task-a--run-task-a.md" not in _markdown_names(run)
    assert "task-b--run-task-b.md" in _markdown_names(run)


def test_full_seed_drops_invalid_verdicts(bank: Path, tmp_path: Path):
    run = tmp_path / "run"
    sync.seed_run(bank, run, exclude_task_id="task-a", judge_model=JUDGE)

    assert "task-d--run-task-d.md" not in _markdown_names(run)


def test_full_seed_drops_other_judge_models(bank: Path, tmp_path: Path):
    run = tmp_path / "run"
    sync.seed_run(bank, run, exclude_task_id="task-a", judge_model="some-other-judge")

    assert _index_paths(run) == set()


# --- seed bank 与 merge bank 分离 ----------------------------------------


def test_seed_bank_root_selects_the_frozen_bank(tmp_path: Path):
    live = _bank(tmp_path / "live", [("task-live", "physical_modeling", "valid")])
    frozen = _bank(tmp_path / "frozen", [("task-frozen", "physical_modeling", "valid")])
    run = tmp_path / "run"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    sync.main(
        [
            "--runs-root",
            str(runs_root),
            "--bank-root",
            str(live),
            "--seed-bank-root",
            str(frozen),
            "--seed-run",
            str(run),
            "--exclude-task-id",
            "task-x",
            "--judge-model",
            JUDGE,
        ]
    )

    assert _index_paths(run) == {"physical_modeling/task-frozen--run-task-frozen.md"}


def test_seed_defaults_to_the_merge_bank(tmp_path: Path):
    live = _bank(tmp_path / "live", [("task-live", "physical_modeling", "valid")])
    run = tmp_path / "run"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    sync.main(
        [
            "--runs-root",
            str(runs_root),
            "--bank-root",
            str(live),
            "--seed-run",
            str(run),
            "--judge-model",
            JUDGE,
        ]
    )

    assert _index_paths(run) == {"physical_modeling/task-live--run-task-live.md"}


def test_seeding_never_mutates_the_frozen_bank(tmp_path: Path):
    """冻结库必须逐字节稳定，否则两条臂读到的不是同一份。"""

    live = _bank(tmp_path / "live", [("task-live", "physical_modeling", "valid")])
    frozen = _bank(
        tmp_path / "frozen",
        [
            ("task-1", "physical_modeling", "valid"),
            ("task-2", "cellular_omics", "valid"),
        ],
    )
    before = {
        p.relative_to(frozen).as_posix(): p.read_bytes()
        for p in sorted(frozen.rglob("*"))
        if p.is_file()
    }
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    for index, task in enumerate(("task-1", "task-2")):
        sync.main(
            [
                "--runs-root",
                str(runs_root),
                "--bank-root",
                str(live),
                "--seed-bank-root",
                str(frozen),
                "--seed-run",
                str(tmp_path / f"run-{index}"),
                "--exclude-task-id",
                task,
                "--judge-model",
                JUDGE,
            ]
        )

    after = {
        p.relative_to(frozen).as_posix(): p.read_bytes()
        for p in sorted(frozen.rglob("*"))
        if p.is_file()
    }
    assert after == before


def test_empty_seed_flag_reaches_seed_run(tmp_path: Path):
    frozen = _bank(tmp_path / "frozen", [("task-1", "physical_modeling", "valid")])
    run = tmp_path / "run"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    sync.main(
        [
            "--runs-root",
            str(runs_root),
            "--bank-root",
            str(frozen),
            "--seed-run",
            str(run),
            "--empty-seed",
            "--judge-model",
            JUDGE,
        ]
    )

    assert _index_paths(run) == set()
    assert _markdown_names(run) == set()


# --- 两条臂的差异必须只有目录内容 ----------------------------------------


def test_both_arms_produce_the_same_snapshot_location(bank: Path, tmp_path: Path):
    treatment = tmp_path / "with"
    control = tmp_path / "without"

    sync.seed_run(bank, treatment, exclude_task_id="task-a", judge_model=JUDGE)
    sync.seed_run(bank, control, exclude_task_id="task-a", empty=True)

    assert _snapshot(treatment).is_dir()
    assert _snapshot(control).is_dir()
    # 唯一的差别是目录里有没有条目。
    assert _index_paths(treatment)
    assert not _index_paths(control)


# --- 自任务屏蔽的硬断言 -------------------------------------------------


def _bank_with_repeats(root: Path, task_id: str, runs: int, other: str) -> Path:
    """同一任务多条记录的库。实测单题最多 7 条（同题跑过 7 次）。"""

    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("bank readme\n", encoding="utf-8")
    public: list[str] = []
    system: list[str] = []
    entries = [(task_id, f"run-{index}") for index in range(runs)]
    entries.append((other, "run-other"))
    for tid, run_id in entries:
        relative = f"cellular_omics/{tid}--{run_id}.md"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {tid}\n", encoding="utf-8")
        public.append(
            json.dumps(
                {"domain": "cellular_omics", "summary_path": relative, "best_score": 0.1},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        system.append(
            json.dumps(
                {
                    "task_id": tid,
                    "run_id": run_id,
                    "summary_path": relative,
                    "judge_verdict": "valid",
                    "judge_model": JUDGE,
                    "evolution_markdown": f"## 演化摘要\n\n{tid} 的结论。\n",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    (root / "index.jsonl").write_text("\n".join(public) + "\n", encoding="utf-8")
    (root.parent / f".{root.name}.system.jsonl").write_text(
        "\n".join(system) + "\n", encoding="utf-8"
    )
    return root


def test_seed_excludes_every_entry_of_the_task(tmp_path: Path):
    """同一任务的多条记录必须全部剔除，不能只删掉一条。"""

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 4, "task-b")
    run = tmp_path / "runs" / "run-new"

    result = sync.seed_run(bank, run, exclude_task_id="task-a")

    assert result["published"] == 1
    assert not [
        name for name in _markdown_names(run) if name.startswith("task-a--")
    ]


def test_seed_refuses_to_leak_the_current_task(tmp_path: Path, monkeypatch):
    """漏删不会报错、只会安静泄漏，所以 seed 完必须自检。

    这里打掉「物理删 .md」那一步，模拟只删了索引没删文件的情形——Agent 绕过
    索引直接 ``ls`` 就能读到自己上一次的解法。
    """

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 2, "task-b")
    run = tmp_path / "runs" / "run-new"
    real_unlink = Path.unlink

    def keep_task_a(self, *args, **kwargs):
        if self.name.startswith("task-a--"):
            return None
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", keep_task_a)
    with pytest.raises(RuntimeError, match="自任务经验未被完全剔除"):
        sync.seed_run(bank, run, exclude_task_id="task-a")


# --- 同任务自身经验臂：--only-task-id ------------------------------------
#
# 跨任务 A/B（20260909）是 null：读取、迁移进方法字段、引入新技术三段链路都通，
# 但分数没动。所以把迁移距离缩到最短再测一次——快照里只放这道题自己前几轮的
# 复盘。过滤方向翻转，断言也得跟着翻转：``_assert_task_excluded`` 在参数为空时
# 静默返回，两个参数又互斥，所以 only 臂必须有自己的那道断言。


def _manifest(run_dir: Path) -> dict:
    path = (
        run_dir / "shared_experience_pool" / "cross_task_expbank_seed_manifest.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_only_task_id_keeps_just_that_task(tmp_path: Path):
    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 4, "task-b")
    run = tmp_path / "runs" / "run-new"

    result = sync.seed_run(bank, run, only_task_id="task-a")

    assert result["published"] == 4
    assert all(name.startswith("task-a--") for name in _markdown_names(run))


def test_only_task_id_physically_deletes_other_tasks(tmp_path: Path):
    """和排除侧同理：Agent 绕过索引 ``ls`` 也不能读到别的任务。"""

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 2, "task-b")
    run = tmp_path / "runs" / "run-new"

    sync.seed_run(bank, run, only_task_id="task-a")

    assert "task-b--run-other.md" not in _markdown_names(run)


def test_only_task_id_still_applies_the_judge_and_content_gates(
    bank: Path, tmp_path: Path
):
    """反向过滤不能顺手放行不合规条目：task-d 的裁决是 invalid。"""

    run = tmp_path / "run"
    sync.seed_run(bank, run, only_task_id="task-d", judge_model=JUDGE)

    assert _index_paths(run) == set()
    assert _markdown_names(run) == set()


def test_only_task_id_records_the_dose_in_the_manifest(tmp_path: Path):
    """剂量必须开跑前落盘：self 臂的剂量就是本任务有几条历史复盘。"""

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 3, "task-b")
    run = tmp_path / "runs" / "run-new"

    sync.seed_run(bank, run, only_task_id="task-a")

    manifest = _manifest(run)
    assert manifest["included_task_id"] == "task-a"
    assert manifest["excluded_task_id"] is None
    assert manifest["published"] == 3


def test_the_two_task_filters_are_mutually_exclusive(bank: Path, tmp_path: Path):
    """同时给两个方向没有合理语义，必须炸而不是静默取其一。"""

    with pytest.raises(ValueError, match="互斥"):
        sync.seed_run(
            bank, tmp_path / "run", exclude_task_id="task-a", only_task_id="task-b"
        )


def test_only_task_id_refuses_to_leak_other_tasks(tmp_path: Path, monkeypatch):
    """漏删同样只会安静泄漏——这里打掉物理删除，断言必须拦住。"""

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 2, "task-b")
    run = tmp_path / "runs" / "run-new"
    real_unlink = Path.unlink

    def keep_task_b(self, *args, **kwargs):
        if self.name.startswith("task-b--"):
            return None
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", keep_task_b)
    with pytest.raises(RuntimeError, match="自任务快照里混进了其他任务"):
        sync.seed_run(bank, run, only_task_id="task-a")


def test_only_task_id_flag_reaches_seed_run(tmp_path: Path):
    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 2, "task-b")
    run = tmp_path / "run"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    sync.main(
        [
            "--runs-root",
            str(runs_root),
            "--bank-root",
            str(bank),
            "--seed-run",
            str(run),
            "--only-task-id",
            "task-a",
            "--judge-model",
            JUDGE,
        ]
    )

    assert _index_paths(run) == {
        "cellular_omics/task-a--run-0.md",
        "cellular_omics/task-a--run-1.md",
    }


def test_cli_rejects_both_task_filters(tmp_path: Path):
    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 1, "task-b")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    with pytest.raises(SystemExit):
        sync.main(
            [
                "--runs-root",
                str(runs_root),
                "--bank-root",
                str(bank),
                "--seed-run",
                str(tmp_path / "run"),
                "--exclude-task-id",
                "task-a",
                "--only-task-id",
                "task-b",
            ]
        )


def test_self_arm_and_control_arm_share_the_snapshot_location(tmp_path: Path):
    """self 臂的对照臂仍是 ``--empty-seed``，与跨任务实验完全同构。"""

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 3, "task-b")
    treatment = tmp_path / "with"
    control = tmp_path / "without"

    sync.seed_run(bank, treatment, only_task_id="task-a", judge_model=JUDGE)
    sync.seed_run(bank, control, empty=True)

    assert _snapshot(treatment).is_dir() and _snapshot(control).is_dir()
    assert _index_paths(treatment)
    assert not _index_paths(control)


# --- --skip-merge --------------------------------------------------------


def test_skip_merge_does_not_touch_the_project_bank(tmp_path: Path):
    """合并是批次级维护动作，不该挂在每次提交上。

    每条记录都要抢一次库锁，40 个并发提交会在 NFS 锁上排成车队（实测 39 个
    进程卡在 ``nfs4_retry_setlk``，零 IO 进展）。这里锁住「--skip-merge 时
    项目库逐字节不变」，以及「不带 --skip-merge 又没给 --runs-root 时报错」。
    """

    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 2, "task-b")
    outbox_run = tmp_path / "runs" / "finished"
    (outbox_run / "controller").mkdir(parents=True)
    (outbox_run / "controller" / "cross_task_experience_record.json").write_text(
        json.dumps(
            {
                "task_id": "task-new",
                "run_id": "run-new",
                "domain": "cellular_omics",
                "judge_verdict": "valid",
                "judge_model": JUDGE,
                "evolution_markdown": "## 演化摘要\n\n新结论。\n",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before = {
        p.relative_to(bank).as_posix(): p.read_bytes()
        for p in sorted(bank.rglob("*"))
        if p.is_file()
    }

    sync.main(
        [
            "--bank-root",
            str(bank),
            "--skip-merge",
            "--seed-run",
            str(tmp_path / "run"),
            "--only-task-id",
            "task-a",
            "--judge-model",
            JUDGE,
        ]
    )

    after = {
        p.relative_to(bank).as_posix(): p.read_bytes()
        for p in sorted(bank.rglob("*"))
        if p.is_file()
    }
    assert after == before


def test_merging_requires_a_runs_root(tmp_path: Path):
    bank = _bank_with_repeats(tmp_path / "bank", "task-a", 1, "task-b")

    with pytest.raises(SystemExit):
        sync.main(["--bank-root", str(bank), "--seed-run", str(tmp_path / "run")])
