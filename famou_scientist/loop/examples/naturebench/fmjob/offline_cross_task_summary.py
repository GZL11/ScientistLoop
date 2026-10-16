"""Generate cross-task ExpBank summaries from completed NatureBench runs.

This is intentionally a deterministic, host-side migration tool.  It reads
the public result package and Run-local ExpBank records; it does not invoke an
agent, rerun a benchmark, or copy trusted/private evaluator artifacts.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

# Support direct invocation from the fmjob directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from famou_scientist.loop.storage.cross_task_expbank import (
    CrossTaskExpBank,
    achievement_level,
    load_naturebench_domain,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("summary", "title", "claim", "mechanism", "description"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "").strip()


def _shorten(value: str, limit: int = 600) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _attempt_records(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "expbank").glob("*/record.json")):
        record = _read_json(path)
        if record is not None:
            records.append(record)
    return records


def _task_summary(run_dir: Path, task_id: str, domain: Any) -> str:
    """Extract a short public task description for the compact catalog."""

    path = run_dir / "problem" / "README.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return f"NatureBench {task_id}（{domain or 'unknown domain'}）"
    title = next(
        (line.lstrip("# ").strip() for line in lines if line.startswith("# ")),
        f"NatureBench {task_id}",
    )
    objective_index = next(
        (i for i, line in enumerate(lines) if line.lower().startswith("## 2.")),
        None,
    )
    detail = ""
    if objective_index is not None:
        for line in lines[objective_index + 1 :]:
            if line.startswith("## "):
                break
            value = line.strip().lstrip("*- ").strip()
            if value:
                detail = value
                break
    return _shorten(f"{title}：{detail}" if detail else title, 320)


def _attempt_description(record: Mapping[str, Any]) -> str:
    implementation = record.get("implementation")
    if isinstance(implementation, Mapping):
        value = implementation.get("method_summary")
        if isinstance(value, str) and value.strip():
            return _shorten(value)
    idea = record.get("idea")
    if isinstance(idea, Mapping):
        for key in ("title", "summary", "hypothesis", "method"):
            value = idea.get(key)
            if isinstance(value, str) and value.strip():
                return _shorten(value)
    return _shorten(_text(record.get("conclusion")) or "未命名方案")


def _failure_description(record: Mapping[str, Any]) -> str:
    error = record.get("error") or record.get("failure")
    if error:
        return _shorten(_text(error))
    status = str(record.get("status") or "")
    if status in {"not_executed", "skipped"}:
        return "未执行，不能据此判断方法有效性。"
    score = _finite_score(record.get("score"))
    if score is not None and score < 0:
        return f"正式评测有效，但 score={score:.6g}，未达到 Match-SOTA。"
    return ""


def _bullet_lines(values: list[str], limit: int = 8) -> list[str]:
    if not values:
        return ["- 无"]
    lines = [f"- {value}" for value in values[:limit]]
    if len(values) > limit:
        lines.append(f"- 其余 {len(values) - limit} 条保留在系统侧完整记录中。")
    return lines


def _evolution_markdown(summary: Mapping[str, Any]) -> str:
    """Render a compact offline summary while retaining the full index record."""

    score = summary.get("best_score")
    score_text = f"{score:.6g}" if isinstance(score, (int, float)) else "无"
    lines = [
        "# 演化总结",
        "",
        f"- 领域：`{summary.get('domain')}`",
        f"- 任务概述：{summary.get('task_summary') or '未记录'}",
        f"- 结果：`{summary.get('result')}`",
        f"- 最佳尝试：`{summary.get('best_attempt_id') or '无'}`",
        f"- 最佳分数：`{score_text}`",
        f"- 尝试数量：`{summary.get('attempt_count', 0)}`",
        "",
        "## 最好的方法",
        "",
        str(summary.get("method_summary") or "未形成可验证的方法总结。"),
        "",
        "## 演化过程中发现的点",
        "",
        *_bullet_lines(summary.get("successful_ideas") or []),
        "",
        "## 失败和意外",
        "",
        *_bullet_lines(summary.get("failed_ideas") or []),
        "",
        "## Refine 轨迹",
        "",
        *_bullet_lines(summary.get("refine_summary") or []),
        "",
        "## 何时值得迁移",
        "",
        *_bullet_lines(summary.get("transferable_experiences") or [], limit=4),
        "",
        "## 不应直接迁移",
        "",
        *_bullet_lines(summary.get("negative_transfer") or [], limit=4),
        "",
    ]
    return "\n".join(lines)


def _resolve_run(run_root: Path, task_id: str, source_run_id: str | None, score: float) -> Path | None:
    if source_run_id:
        direct = run_root / source_run_id
        if (direct / "controller/run_summary.json").is_file():
            return direct
    # Some older result packages omitted source_run_id from export_manifest.
    # Restrict the fallback to directories named for this case and an exact
    # completed score match, so an unrelated run cannot be imported.
    candidates: list[Path] = []
    for path in sorted(run_root.glob(f"*{task_id}*")):
        summary = _read_json(path / "controller/run_summary.json")
        if not summary or str(summary.get("task_id") or "") != task_id:
            continue
        if str(summary.get("status") or "") not in {"completed", "stopped", "failed"}:
            continue
        candidate_score = _finite_score(summary.get("best_score"))
        if candidate_score is not None and math.isclose(
            candidate_score, score, rel_tol=1e-12, abs_tol=1e-12
        ):
            candidates.append(path)
    return candidates[0] if candidates else None


def _build_summary(
    *,
    case: Mapping[str, Any],
    result: Mapping[str, Any],
    run_dir: Path,
    records: list[dict[str, Any]],
    package_root: Path,
) -> dict[str, Any]:
    task_id = str(case.get("case_id") or result.get("case_id") or "").strip()
    run_id = run_dir.name
    package_score = _finite_score(result.get("best_score"))
    score = package_score
    summary = _read_json(run_dir / "controller/run_summary.json") or {}
    summary_score = _finite_score(summary.get("best_score"))

    scored = [
        (value, record)
        for record in records
        if (value := _finite_score(record.get("score"))) is not None
    ]
    best_score, best = max(scored, key=lambda item: item[0]) if scored else (score, {})
    best_attempt_id = str(summary.get("best_attempt_id") or best.get("attempt_id") or "") or None
    if best_attempt_id:
        for record in records:
            if str(record.get("attempt_id") or "") == best_attempt_id:
                best = record
                break
    if package_score is not None:
        # The official package is the source of truth for the exported score.
        best_score = package_score
    elif best_score is None:
        best_score = _finite_score(best.get("score"))

    successful: list[str] = []
    failed: list[str] = []
    refinements: list[str] = []
    for record in records:
        attempt_id = str(record.get("attempt_id") or "unknown")
        value = _finite_score(record.get("score"))
        description = _attempt_description(record)
        if value is not None and value >= 0:
            successful.append(f"{attempt_id}: {description}; score={value:.6g}")
        failure = _failure_description(record)
        if failure:
            failed.append(f"{attempt_id}: {description}; {failure}")
        parent = record.get("parent_attempt_id")
        if parent:
            refinements.append(f"{attempt_id} 基于 {parent}: {description}")

    successful_count = len(successful)
    failed_count = len(failed)
    refine_count = len(refinements)
    successful = successful[:12]
    failed = failed[:12]
    refinements = refinements[:12]
    method_summary = _attempt_description(best) if best else "尚未形成方法总结。"
    # 原实现是 `>0.1 则 surpass，否则一律 match_sota`——没有 below_sota 分支，
    # 于是 −50 分的 run 也被标成「达到 SOTA」。档位口径只此一处。
    result_label = achievement_level(best_score)
    evidence = [
        "controller/run_summary.json",
        *[
            f"expbank/{record.get('attempt_id')}/record.json"
            for record in records
            if record.get("attempt_id")
        ],
    ]
    domain = case.get("domain") or load_naturebench_domain(task_id)
    output = {
        "task_id": task_id,
        "run_id": run_id,
        "domain": domain,
        "task_summary": _task_summary(run_dir, task_id, domain),
        "result": result_label,
        "best_score": best_score,
        "attempt_count": len(records),
        "scored_attempt_count": len(scored),
        "successful_idea_count": successful_count,
        "failed_idea_count": failed_count,
        "refine_count": refine_count,
        "best_attempt_id": best_attempt_id,
        "method_summary": method_summary,
        "successful_ideas": successful,
        "failed_ideas": failed,
        "refine_summary": refinements,
        "transferable_experiences": [
            f"最佳尝试达到 {result_label}（score={best_score:.6g}）；迁移时优先复用方法机制，需在目标任务的公开验证数据上重新调参和验证。"
            if best_score is not None
            else "仅可迁移已由公开证据支持的方法机制，不能直接迁移任务专属参数。"
        ],
        "negative_transfer": [
            "该 Run 的数据预处理、特征和超参数可能依赖具体 case；不要未经验证直接复制到其他任务。"
        ],
        "evidence_refs": evidence,
        # System audit fields are retained in the index but are not used as
        # Agent-facing experience text.
        "source_run_dir": str(run_dir.resolve()),
        "task_output_dir": str((run_dir / "workspace" / "output").resolve()),
        "run_status": summary.get("status"),
        "run_summary_score": summary_score,
        "judge_verdict": result.get("judge_verdict"),
        "source_result_package": str(package_root.resolve()),
        "offline_generated": True,
    }
    output["evolution_markdown"] = _evolution_markdown(output)
    return output


def _load_cases(package_root: Path) -> list[dict[str, Any]]:
    results = {
        str(row.get("case_id") or ""): row
        for row in csv.DictReader((package_root / "results.csv").open(encoding="utf-8", newline=""))
    }
    manifest = _read_json(package_root / "export_manifest.json") or {}
    selected = manifest.get("selected_runs")
    if not isinstance(selected, list):
        raise ValueError("export_manifest.json 缺少 selected_runs")
    cases: list[dict[str, Any]] = []
    for value in selected:
        if not isinstance(value, Mapping):
            continue
        case_id = str(value.get("case_id") or "")
        row = results.get(case_id)
        if row is None:
            continue
        score = _finite_score(row.get("best_score"))
        if row.get("judge_verdict") != "valid" or score is None or score < 0:
            continue
        cases.append(dict(value))
    # Include valid Match/Surpass results that an older manifest forgot to
    # select; the run resolver will locate their historical Run by exact score.
    selected_ids = {str(value.get("case_id") or "") for value in cases}
    for case_id, row in results.items():
        score = _finite_score(row.get("best_score"))
        if case_id in selected_ids or row.get("judge_verdict") != "valid" or score is None or score < 0:
            continue
        cases.append({"case_id": case_id, "domain": None, "source_run_id": None})
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--limit", type=int, help="只处理排序后的前 N 个 case")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    package_root = args.package_root.expanduser().resolve()
    runs_root = args.runs_root.expanduser().resolve()
    bank = CrossTaskExpBank(args.bank_root.expanduser().resolve())
    results = {
        str(row.get("case_id") or ""): row
        for row in csv.DictReader((package_root / "results.csv").open(encoding="utf-8", newline=""))
    }
    cases = _load_cases(package_root)
    if args.task_ids:
        wanted = set(args.task_ids)
        cases = [case for case in cases if case.get("case_id") in wanted]
    cases.sort(key=lambda case: str(case.get("case_id") or ""))
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]

    output: list[dict[str, Any]] = []
    for case in cases:
        task_id = str(case.get("case_id") or "")
        result = results[task_id]
        score = _finite_score(result.get("best_score"))
        run_dir = _resolve_run(runs_root, task_id, case.get("source_run_id"), score or 0.0)
        if run_dir is None:
            output.append({"task_id": task_id, "status": "skipped", "reason": "source_run_not_found"})
            continue
        records = _attempt_records(run_dir)
        if not records:
            output.append({"task_id": task_id, "run_id": run_dir.name, "status": "skipped", "reason": "empty_expbank"})
            continue
        summary = _build_summary(case=case, result=result, run_dir=run_dir, records=records, package_root=package_root)
        if not args.dry_run:
            try:
                bank.upsert_summary(summary)
            except (OSError, ValueError) as exc:
                output.append({
                    "task_id": task_id,
                    "run_id": run_dir.name,
                    "status": "skipped",
                    "reason": f"write_error: {exc}",
                })
                continue
        output.append({
            "task_id": task_id,
            "run_id": run_dir.name,
            "result": summary["result"],
            "best_score": summary["best_score"],
            "attempt_count": summary["attempt_count"],
            "status": "planned" if args.dry_run else "written",
        })
    print(json.dumps({"processed": len(output), "written": sum(x.get("status") == "written" for x in output), "items": output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
