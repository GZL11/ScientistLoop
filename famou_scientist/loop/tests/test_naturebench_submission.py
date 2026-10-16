"""测试 NatureBench 官方 Leaderboard 目录导出。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from famou_scientist.loop.examples.naturebench.export_submission import (
    export_submission,
)


def _write_json(path: Path, value: object) -> None:
    """为测试夹具写入 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_metadata(path: Path) -> list[str]:
    """生成符合导出器 90-case 约束的测试元数据。"""

    case_ids = [f"case-{index:03d}" for index in range(90)]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "domain"])
        writer.writerows((case_id, "Test Domain") for case_id in case_ids)
    return case_ids


def _make_reviewed_run(
    runs_dir: Path,
    case_id: str,
    *,
    relative_run_dir: str = "reviewed-run",
    score: float = 0.25,
    finished_at: int = 42,
) -> Path:
    """生成一个带官方 attempts、Judge 和完整轨迹的最小运行。"""

    run_dir = runs_dir / relative_run_dir
    summary = {
        "task_id": case_id,
        "status": "completed",
        "best_score": score,
        "finished_at": finished_at,
        "workspace": str(run_dir / "workspace"),
        "final_evaluation": {
            "valid": True,
            "reason": "The method trains on the provided data.",
            "transport_request_id": "judge-request",
        },
    }
    _write_json(run_dir / "controller" / "run_summary.json", summary)
    _write_json(
        run_dir / "controller" / "judge_verdict.json",
        {"is_valid": True, "reason": "The method trains on the provided data."},
    )
    projection = run_dir / "controller" / "naturebench_judge" / "judge-request" / case_id
    projection.mkdir(parents=True)
    (projection / "submissions.jsonl").write_text(
        json.dumps(
            {
                "attempt": 1,
                "aggregate_improvement": 0.1,
                "diagnostic": f"missing output under {run_dir}/workspace/output",
            }
        )
        + "\n"
        + json.dumps({"attempt": 2, "aggregate_improvement": score})
        + "\n",
        encoding="utf-8",
    )
    (projection / "famou.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "cwd": str(run_dir / "workspace"),
                "message": "API_KEY=should-not-leak endpoint=http://10.1.2.3:9000",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = projection / "workspace"
    workspace.mkdir()
    (workspace / "run.py").write_text(
        f'RUN_DIR = "{run_dir}"\n',
        encoding="utf-8",
    )
    return run_dir


def test_export_submission_writes_official_layout_and_redacts(tmp_path: Path) -> None:
    """导出器应生成全部 90 个目录并脱敏完整轨迹。"""

    metadata_path = tmp_path / "case_metadata.csv"
    case_ids = _make_metadata(metadata_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _make_reviewed_run(runs_dir, case_ids[0])
    output_dir = tmp_path / "submission"
    args = argparse.Namespace(
        runs_dir=runs_dir,
        output_dir=output_dir,
        case_metadata=metadata_path,
        model="Test Model",
        agent="Famou Scientist",
        organization="Independent",
        url="https://example.org/famou",
        contact="test@example.org",
        submission_date="2026-08-08",
        timeout_seconds=14400,
        web_search=False,
        compute="test compute",
        judge_model="test judge",
        human_intervention="none",
        deviations_from_reference="none",
    )

    report = export_submission(args)

    assert report["valid_case_count"] == 1
    assert len(list((output_dir / "raw-results").glob("case-*"))) == 90
    with (output_dir / "results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["best_score"] == "0.25"
    assert rows[0]["judge_verdict"] == "valid"
    assert rows[1]["final_status"] == "not_run"
    assert (output_dir / "raw-results" / case_ids[1] / "submissions.jsonl").read_text() == ""

    trajectory = (
        output_dir / "raw-results" / case_ids[0] / "trajectory.famou.jsonl"
    ).read_text(encoding="utf-8")
    assert "should-not-leak" not in trajectory
    assert "10.1.2.3" not in trajectory
    assert "<RUN_DIR>" in trajectory
    assert "<REDACTED>" in trajectory
    assert "<PRIVATE_ENDPOINT>" in trajectory
    submissions = (
        output_dir / "raw-results" / case_ids[0] / "submissions.jsonl"
    ).read_text(encoding="utf-8")
    assert str(runs_dir / "reviewed-run") not in submissions
    assert "<RUN_DIR>" in submissions


def test_export_submission_discovers_snapshot_rerun(tmp_path: Path) -> None:
    """共享题面快照下的 reruns/ 结果应参与最新正式运行选择。"""

    metadata_path = tmp_path / "case_metadata.csv"
    case_ids = _make_metadata(metadata_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _make_reviewed_run(
        runs_dir,
        case_ids[0],
        relative_run_dir="prior/reruns/new-run",
        score=0.5,
        finished_at=84,
    )
    output_dir = tmp_path / "submission"
    args = argparse.Namespace(
        runs_dir=runs_dir,
        output_dir=output_dir,
        case_metadata=metadata_path,
        model="Test Model",
        agent="Famou Scientist",
        organization="Independent",
        url="https://example.org/famou",
        contact="test@example.org",
        submission_date="2026-08-11",
        timeout_seconds=14400,
        web_search=False,
        compute="test compute",
        judge_model="test judge",
        human_intervention="none",
        deviations_from_reference="none",
    )

    report = export_submission(args)

    assert report["valid_case_count"] == 1
    with (output_dir / "results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["best_score"] == "0.5"
