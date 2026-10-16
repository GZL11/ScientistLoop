"""扁平 ExpBank 目录、快照和索引测试。"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from famou_scientist.loop.examples.naturebench.fmjob.sync_cross_task_expbank import (
    seed_run,
)
from famou_scientist.loop.storage import CrossTaskExpBank, ExpBank, IdeaGraphStore
from famou_scientist.loop.storage.cross_task_expbank import (
    OFFICIAL_DOMAIN_SLUGS,
    load_naturebench_domain,
)



def _catalog(bank, domain: str) -> list[dict]:
    """读 Agent 目录里某领域的条目。

    以前是 ``bank.search(domain=...)``。那个函数的职责是「替 Idea Agent 决定这轮
    看哪 20 条」，已删——筛选是 Agent 自己的活（库在它工作区里，按 domain grep
    索引即可），而唯一不能交给它的自任务屏蔽在 ``seed_run`` 里做（物理删文件）。
    测试要看的只是「目录里有什么」，直接读索引。
    """

    import json as _json

    return [
        item
        for line in bank.index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for item in [_json.loads(line)]
        if item.get("domain") == domain
    ]


def _published(bank, record) -> str:
    """读已发布的 Markdown 正文。"""

    return (bank.root / record["summary_path"]).read_text(encoding="utf-8").strip()


def test_cross_task_expbank_has_only_official_domain_partitions(tmp_path: Path):
    """空经验库只包含 README、索引和 NatureBench 官方六领域。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")

    names = {path.name for path in bank.root.iterdir()}
    domains = set(OFFICIAL_DOMAIN_SLUGS.values())
    assert names == {"README.md", "index.jsonl", *domains}
    assert all((bank.root / domain).is_dir() for domain in domains)


def test_cross_task_expbank_upsert_is_idempotent_and_searchable(tmp_path: Path):
    """同一 Run 反复收尾只保留一条索引，并可按领域检索。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    summary = {
        "task_id": "s41592-022-01709-7",
        "run_id": "run-1",
        "judge_verdict": "valid",
        "domain": "Cellular Omics",
        "goal": "改进跨模态单细胞匹配",
        "result": "completed",
        "conclusion": "方法 A 在公开评测上优于方法 B。",
        "evolution_markdown": "## 演化摘要\n\n方法 A 优于方法 B。\n",
        "evidence_refs": ["/runs/run-1/expbank/0001/record.json"],
    }

    first = bank.upsert_summary(summary)
    second = bank.upsert_summary({**summary, "conclusion": "更新后的结论。"})

    assert first["experience_id"] == second["experience_id"]
    assert len(bank.records()) == 1
    assert bank.records()[0]["conclusion"] == "更新后的结论。"
    assert _catalog(bank, "cellular_omics")[0]["summary_path"].startswith(
        "cellular_omics/"
    )
    assert _catalog(bank, "protein_biology") == []


def test_cross_task_expbank_publishes_agent_markdown_but_keeps_system_fields(
    tmp_path: Path,
):
    """Markdown 是 Agent-facing 内容，来源路径仍只留在系统索引。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    record = bank.upsert_summary(
        {
            "task_id": "task-1",
            "run_id": "run-1",
            "judge_verdict": "valid",
            "domain": "cellular_omics",
            "result": "completed",
            "source_run_dir": "/private/runs/run-1",
            "task_output_dir": "/private/runs/run-1/workspace/output",
            "evolution_markdown": (
                "# Evolution Summary\n\n"
                "## Best Method\n\n使用稀疏索引。\n"
            ),
        }
    )

    assert "使用稀疏索引" in (bank.root / record["summary_path"]).read_text(
        encoding="utf-8"
    )
    assert _published(bank, record).startswith("# Evolution Summary")
    assert bank.records()[0]["source_run_dir"] == "/private/runs/run-1"
    assert bank.records()[0]["task_output_dir"].endswith("workspace/output")


def test_cross_task_catalog_is_compact_and_searchable(tmp_path: Path):
    """目录只用于筛选；完整轨迹留在宿主侧系统记录。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    record = bank.upsert_summary(
        {
            "task_id": "task-compact",
            "run_id": "run-compact",
            "judge_verdict": "valid",
            "domain": "cellular_omics",
            "task_summary": "预测细胞状态标签。",
            "result": "match_sota",
            "best_score": 0.02,
            "method_summary": "公开方法摘要。",
            "successful_ideas": ["完整尝试轨迹"],
            "source_run_dir": "/private/run",
            "task_output_dir": "/private/run/output",
            "evidence_refs": ["expbank/0001/record.json"],
            "evolution_markdown": "# Summary\n\n公开方法摘要。\n",
        }
    )

    catalog = json.loads(
        (bank.root / "index.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert set(catalog) == {
        "domain",
        "task_summary",
        "result",
        "best_score",
        "summary_path",
        "evolution_summary",
    }
    assert "evidence_refs" not in catalog
    assert _catalog(bank, "cellular_omics")[0]["task_summary"] == "预测细胞状态标签。"
    assert "evidence_refs" in bank.records()[0]
    assert _published(bank, record).startswith("# Summary")


def test_cross_task_catalog_prefers_agent_evolution_summary(tmp_path: Path):
    """目录保留 Agent 写的短摘要，详细内容仍只在 Markdown 中。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    bank.upsert_summary(
        {
            "task_id": "task-evolution",
            "run_id": "run-evolution",
            "judge_verdict": "valid",
            "domain": "cellular_omics",
            "task_summary": "细胞状态预测。",
            "result": "match_sota",
            "evolution_markdown": (
                "# 演化总结\n\n"
                "## 演化摘要\n\n"
                "先验证数据契约，再将稀疏特征与校准融合，最终获得稳定提升。\n\n"
                "## 最佳方法\n\n详细内容。\n"
            ),
        }
    )
    catalog = json.loads(
        (bank.root / "index.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert catalog["evolution_summary"].startswith("先验证数据契约")
    assert "详细内容" not in catalog["evolution_summary"]


def test_cross_task_catalog_rebuild_upgrades_legacy_entries(tmp_path: Path):
    """升级旧系统记录时只重建 Agent-facing 投影。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    bank.upsert_summary(
        {
            "task_id": "task-legacy",
            "run_id": "run-legacy",
            "judge_verdict": "valid",
            "domain": "cellular_omics",
            "result": "match_sota",
            "method_summary": "稀疏特征和校准融合。",
            "evolution_markdown": "## 演化摘要\n\n稀疏特征和校准融合。\n",
        }
    )
    lines = (bank.root / "index.jsonl").read_text(encoding="utf-8").splitlines()
    (bank.root / "index.jsonl").write_text(
        lines[0].replace(', "evolution_summary": "稀疏特征和校准融合。"', ""),
        encoding="utf-8",
    )
    assert bank.rebuild_catalog() == 1
    catalog = json.loads((bank.root / "index.jsonl").read_text(encoding="utf-8"))
    assert catalog["evolution_summary"] == "稀疏特征和校准融合。"


def test_cross_task_expbank_hides_non_valid_judge_records(tmp_path: Path):
    """Invalid、未知或缺失 Judge 的总结只能留在系统审计记录中。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    base = {
        "task_id": "task-guarded",
        "run_id": "run-guarded",
        "domain": "cellular_omics",
        "result": "match_sota",
        "method_summary": "候选方法。",
        # 内容闸门单独由 test_cross_task_visibility.py 覆盖；这里固定为
        # 「Agent 手写」，使本用例只检验合规这一维。
        "evolution_markdown": "## 演化摘要\n\n候选方法。\n",
    }

    missing = bank.upsert_summary(base)
    assert missing["agent_visible"] is False
    assert _catalog(bank, "cellular_omics") == []
    assert not (bank.root / missing["summary_path"]).exists()
    assert "judge_verdict" not in bank.records()[0]

    valid = bank.upsert_summary({**base, "judge_verdict": "valid"})
    assert valid["agent_visible"] is True
    assert len(_catalog(bank, "cellular_omics")) == 1
    assert (bank.root / valid["summary_path"]).is_file()

    invalid = bank.upsert_summary({**base, "judge_verdict": "invalid"})
    assert invalid["agent_visible"] is False
    assert _catalog(bank, "cellular_omics") == []
    assert not (bank.root / invalid["summary_path"]).exists()
    assert bank.records()[0]["judge_verdict"] == "invalid"


def test_seeded_cross_task_snapshot_requires_trusted_judge_and_excludes_task(
    tmp_path: Path,
):
    """Run 快照只发布指定 Judge 的 Valid 跨任务经验。"""

    bank = CrossTaskExpBank(tmp_path / "cross_task_expbank")
    base = {
        "domain": "cellular_omics",
        "result": "match_sota",
        "method_summary": "候选方法。",
        "evolution_markdown": "## 演化摘要\n\n候选方法。\n",
    }
    for task_id, run_id, verdict, model in (
        ("task-a", "run-self", "valid", "gpt-5.5"),
        ("task-b", "run-trusted", "valid", "gpt-5.5"),
        ("task-c", "run-old-judge", "valid", "claude-sonnet-4-6"),
        ("task-d", "run-invalid", "invalid", "gpt-5.5"),
    ):
        bank.upsert_summary(
            {
                **base,
                "task_id": task_id,
                "run_id": run_id,
                "judge_verdict": verdict,
                "judge_model": model,
            }
        )

    run_dir = tmp_path / "runs" / "run-new"
    result = seed_run(
        bank.root,
        run_dir,
        exclude_task_id="task-a",
        judge_model="gpt-5.5",
    )
    snapshot = run_dir / "shared_experience_pool" / "cross_task_expbank"
    records = [
        json.loads(line)
        for line in (snapshot / "index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"published": 1}
    assert len(records) == 1
    assert "task-b--run-trusted" in records[0]["summary_path"]
    assert (snapshot / records[0]["summary_path"]).is_file()
    assert len(list(snapshot.glob("*/*.md"))) == 1


def test_naturebench_domain_mapping_and_unknown_case():
    """NatureBench case ID 应映射到官方领域，未知任务必须显式跳过。"""

    assert load_naturebench_domain("s41592-022-01709-7") == "cellular_omics"
    assert load_naturebench_domain("unknown-case") is None


def test_expbank_creates_flat_browsable_attempt(tmp_path: Path):
    """单次尝试应生成固定的浅层目录和可读索引。"""
    bank = ExpBank(tmp_path)
    attempt_id = bank.create_attempt(
        idea={"id": "idea-1", "title": "Residual PCA", "method": "加入残差特征"},
        lineage_id="lineage-1",
        branch_id="branch-1",
    )

    assert attempt_id == "0001"
    assert sorted(path.name for path in (tmp_path / "expbank" / "0001").iterdir()) == [
        "SUMMARY.md",
        "evidence",
        "record.json",
    ]
    index = (tmp_path / "expbank" / "INDEX.md").read_text(encoding="utf-8")
    summary = (tmp_path / "expbank" / "0001" / "SUMMARY.md").read_text(
        encoding="utf-8"
    )
    assert "Residual PCA" in index
    assert "加入残差特征" in summary


def test_expbank_freezes_code_and_preserves_detailed_evidence(tmp_path: Path):
    """代码、运行、评分和日志应在同一编号目录下形成完整证据。"""
    source = tmp_path / "branch" / "worktree"
    source.mkdir(parents=True)
    (source / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "run.pyc").write_bytes(b"cache")

    bank = ExpBank(tmp_path)
    attempt_id = bank.create_attempt(
        idea={"id": "idea-1", "title": "Method"},
        lineage_id="lineage-1",
    )
    bank.freeze_code(attempt_id, source)
    bank.write_evidence_json(
        attempt_id,
        "run",
        {"valid": True, "returncode": 0, "stdout": "ok", "stderr": ""},
    )
    bank.write_evidence_json(
        attempt_id,
        "evaluation",
        {"valid": True, "metrics": {"accuracy": 0.9}},
    )
    bank.write_evidence_text(attempt_id, "stdout", "ok\n")
    record = bank.update_attempt(
        attempt_id,
        status="evaluated",
        implementation={"method_summary": "可执行方法"},
        evaluation={"valid": True, "metrics": {"accuracy": 0.9}},
        score=0.9,
        promoted=True,
        conclusion="优于基线",
        paths={
            **bank.read_attempt(attempt_id)["paths"],
            "output": "/workspace/output/submission.json",
        },
    )

    attempt_dir = tmp_path / "expbank" / "0001"
    assert (attempt_dir / "code" / "run.py").is_file()
    assert not (attempt_dir / "code" / "__pycache__").exists()
    assert (attempt_dir / "evidence" / "run.json").is_file()
    assert (attempt_dir / "evidence" / "evaluation.json").is_file()
    assert (attempt_dir / "evidence" / "stdout.log").is_file()
    assert record["code_snapshot"]["files"][0]["sha256"]
    assert "优于基线" in (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")
    assert "0.9" in (tmp_path / "expbank" / "INDEX.md").read_text(encoding="utf-8")


def test_expbank_renders_structured_failure_diagnostics(tmp_path: Path):
    """失败版本应在 record 和摘要中保留阶段、rc、资源与修复建议。"""

    bank = ExpBank(tmp_path)
    attempt_id = bank.create_attempt(
        idea={"id": "idea-failed", "title": "Large sparse classifier"},
        lineage_id="lineage-failed",
    )
    failure = {
        "failure_stage": "canonical_run",
        "error_code": "canonical_timeout",
        "return_code": 143,
        "signal": "SIGTERM",
        "timed_out": True,
        "submitted": True,
        "retryable": True,
        "message": "运行达到 3600 秒上限。",
        "suggested_action": "缩小参数搜索并恢复原 Actor。",
        "evidence_refs": ["artifacts/run.json"],
        "diagnostics": {
            "timeout_sec": 3600,
            "host_memory_gib": 64,
            "resource_request": {"cpu_cores": 8},
        },
    }

    record = bank.update_attempt(
        attempt_id,
        status="engineering_failed",
        failure=failure,
        error=failure["message"],
    )
    summary = (tmp_path / "expbank" / attempt_id / "SUMMARY.md").read_text(
        encoding="utf-8"
    )

    assert record["failure"] == failure
    assert "canonical_timeout" in summary
    assert "SIGTERM" in summary
    assert "是否可重试：`True`" in summary
    assert '"host_memory_gib": 64' in summary


def test_expbank_allocates_unique_ids_for_concurrent_writers(tmp_path: Path):
    """异步 Worker 同时创建记录时编号不得冲突。"""
    bank = ExpBank(tmp_path)

    def create(index: int) -> str:
        return bank.create_attempt(
            idea={"id": f"idea-{index}", "title": f"Method {index}"},
            lineage_id=f"lineage-{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        attempt_ids = list(executor.map(create, range(8)))

    assert sorted(attempt_ids) == [f"{index:04d}" for index in range(1, 9)]
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "expbank").glob("[0-9]*/record.json"))
    ]
    assert len(records) == 8


def test_idea_graph_persists_raw_idea_and_structured_gate_diagnosis(tmp_path: Path):
    """未实现 Idea 也必须在 Gate 前落盘，并保留逐项诊断。"""

    ExpBank(tmp_path)
    graph = IdeaGraphStore(tmp_path)
    graph.submit(
        {
            "id": "idea-1",
            "title": "Mechanistic classifier",
            "mechanism": "learn an explicit routing rule",
        },
        actor_id="idea_agent_main",
        artifact_refs=["artifact-idea-1"],
    )
    graph.begin_review("idea-1")
    graph.record_review(
        "idea-1",
        {
            "verdict": "revise",
            "reasons": ["缺少可解释性验证计划"],
            "criterion_results": [
                {
                    "criterion": "interpretability",
                    "status": "fail",
                    "diagnosis_code": "interpretability_plan_missing",
                }
            ],
            "actionable_revision": ["补充规则稳定性与忠实度实验"],
        },
        artifact_refs=["artifact-review-1"],
    )

    record = graph.read("idea-1")
    latest = graph.latest_review(actor_id="idea_agent_main")
    assert record["status"] == "revision_requested"
    assert record["reviews"][0]["criterion_results"][0]["diagnosis_code"] == (
        "interpretability_plan_missing"
    )
    assert latest and latest["review"]["verdict"] == "revise"
    assert "Mechanistic classifier" in (tmp_path / "expbank" / "IDEAS.md").read_text(
        encoding="utf-8"
    )
    assert "Idea Graph" in (tmp_path / "expbank" / "INDEX.md").read_text(
        encoding="utf-8"
    )

    graph.link_attempt("idea-1", "0001")
    graph.record_implementation("idea-1", succeeded=True, attempt_id="0001")
    implemented = graph.read("idea-1")
    assert implemented["status"] == "implemented"
    assert implemented["attempt_ids"] == ["0001"]
