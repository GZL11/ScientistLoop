#!/usr/bin/env python3
"""把 Famou NatureBench 运行证据导出为官方 Leaderboard 提交目录。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


_RESULT_FIELDS = (
    "case_id",
    "final_status",
    "best_score",
    "judge_verdict",
    "judge_reason",
)
_SCORE_TOLERANCE = 1e-9
_PRIVATE_PATH_RE = re.compile(r"/mnt/cfs(?:_[^\s\"'`]+)?")
_PRIVATE_ENDPOINT_RE = re.compile(
    r"(?i)https?://[^\s\"'`]*(?:baidu-int\.com|icode\.baidu\.com|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})[^\s\"'`]*"
)
_PRIVATE_IP_RE = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?::\d+)?"
)
_BEARER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(?:API[_-]?KEY|AUTH[_-]?TOKEN|ACCESS[_-]?TOKEN|"
    r"SECRET|PASSWORD|PASSWD)[A-Z0-9_]*\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/@\s]+@")


@dataclass(frozen=True)
class ReviewedRun:
    """表示一个已有数值分数且完成布尔 Judge 判定的运行。"""

    task_id: str
    run_dir: Path
    summary: dict[str, Any]
    is_valid: bool
    judge_reason: str
    finished_at: int


@dataclass
class RedactionStats:
    """累计公开导出过程中的脱敏替换数量。"""

    replacements: int = 0

    def add(self, count: int) -> None:
        """增加脱敏替换计数。"""

        self.replacements += count


def _read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 对象并在结构不正确时给出明确错误。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return value


def _finite_number(value: Any) -> float | None:
    """把有限数值规范化为 float，拒绝布尔值、NaN 和无穷大。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _load_case_metadata(path: Path) -> list[tuple[str, str]]:
    """按官方顺序读取全部 case ID 与领域。"""

    try:
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise ValueError(f"无法读取 case metadata {path}: {exc}") from exc
    if not rows or not {"case_id", "domain"}.issubset(rows[0]):
        raise ValueError(f"case metadata 缺少 case_id/domain: {path}")
    metadata: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        case_id = (row.get("case_id") or "").strip()
        domain = (row.get("domain") or "").strip()
        if not case_id or not domain or case_id in seen:
            raise ValueError(f"case metadata 存在空值或重复 ID: {case_id!r}")
        seen.add(case_id)
        metadata.append((case_id, domain))
    if len(metadata) != 90:
        raise ValueError(f"NatureBench 官方 case 数应为 90，实际为 {len(metadata)}")
    return metadata


def _extract_judge(summary: Mapping[str, Any], run_dir: Path) -> tuple[bool, str] | None:
    """读取严格布尔 Judge 结论；基础设施错误保持为未评审。"""

    final_evaluation = summary.get("final_evaluation")
    candidates: list[Mapping[str, Any]] = []
    if isinstance(final_evaluation, Mapping):
        candidates.append(final_evaluation)
    judge_path = run_dir / "controller" / "judge_verdict.json"
    if judge_path.is_file():
        candidates.append(_read_json(judge_path))

    for value in candidates:
        verdict = value.get("is_valid")
        if not isinstance(verdict, bool):
            verdict = value.get("valid")
        reason = value.get("reason")
        if isinstance(verdict, bool) and isinstance(reason, str) and reason.strip():
            return verdict, reason.strip()
    return None


def load_adopted_runs(path: Path | None) -> dict[str, dict[str, Any]] | None:
    """读取人工策展的采用清单：case_id -> {run_id, is_valid, reason}。"""

    if path is None:
        return None
    adopted = _read_json(path)
    if not isinstance(adopted, Mapping) or not adopted:
        raise ValueError(f"采用清单为空或格式不正确: {path}")
    for case_id, entry in adopted.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"采用清单条目格式不正确: {case_id}")
        if not entry.get("run_id") or not isinstance(entry.get("is_valid"), bool):
            raise ValueError(f"采用清单缺少 run_id 或布尔 is_valid: {case_id}")
    return dict(adopted)


def discover_reviewed_runs(
    runs_dir: Path,
    official_case_ids: set[str],
    adopted: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, ReviewedRun], list[dict[str, Any]]]:
    """扫描运行目录，并为每个 case 选择最新的可正式上报运行。

    给定采用清单时改为严格按清单选取 Run 与 Judge 结论，使提交包与当前事实表
    保持一致；未给出清单时沿用「finished_at 最新」的自动选择。
    """

    selected: dict[str, ReviewedRun] = {}
    excluded: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        raise ValueError(f"NatureBench 运行目录不存在: {runs_dir}")

    top_level_runs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    # 超大公开数据可以由旧 Run 的 reruns/ 共享只读快照；只扫描这一层明确约定，
    # 避免递归进入包含百万文件的 problem/、candidate output 或 trusted/。
    nested_runs: list[Path] = []
    for parent in top_level_runs:
        reruns = parent / "reruns"
        if reruns.is_dir():
            nested_runs.extend(
                child for child in sorted(reruns.iterdir()) if child.is_dir()
            )
    for run_dir in [*top_level_runs, *nested_runs]:
        summary_path = run_dir / "controller" / "run_summary.json"
        if not summary_path.is_file():
            continue
        summary = _read_json(summary_path)
        task_id = str(summary.get("task_id") or "").strip()
        if task_id not in official_case_ids:
            excluded.append(
                {"run_id": run_dir.name, "task_id": task_id, "reason": "非官方 case ID"}
            )
            continue
        score = _finite_number(summary.get("best_score"))
        entry = adopted.get(task_id) if adopted is not None else None
        if adopted is not None:
            # 清单模式：只接受被指定的 Run，Judge 结论直接采用清单值。
            if entry is None or run_dir.name != entry["run_id"]:
                continue
            if score is None:
                excluded.append(
                    {
                        "run_id": run_dir.name,
                        "task_id": task_id,
                        "reason": "采用清单指定的运行缺少有限 best_score",
                        "best_score": score,
                    }
                )
                continue
            judge = (
                bool(entry["is_valid"]),
                str(entry.get("reason") or "").strip() or "采用当前事实表判定",
            )
        else:
            judge = _extract_judge(summary, run_dir)
            if score is None or judge is None:
                excluded.append(
                    {
                        "run_id": run_dir.name,
                        "task_id": task_id,
                        "reason": "缺少有限 best_score 或布尔 Judge 结论",
                        "best_score": score,
                    }
                )
                continue
        finished_at = int(summary.get("finished_at") or 0)
        reviewed = ReviewedRun(
            task_id=task_id,
            run_dir=run_dir,
            summary=summary,
            is_valid=judge[0],
            judge_reason=judge[1],
            finished_at=finished_at,
        )
        previous = selected.get(task_id)
        if previous is None or reviewed.finished_at > previous.finished_at:
            if previous is not None:
                excluded.append(
                    {
                        "run_id": previous.run_dir.name,
                        "task_id": task_id,
                        "reason": "同一 case 已选择更新的已评审运行",
                        "best_score": previous.summary.get("best_score"),
                    }
                )
            selected[task_id] = reviewed
        else:
            excluded.append(
                {
                    "run_id": run_dir.name,
                    "task_id": task_id,
                    "reason": "同一 case 已有更新的已评审运行",
                    "best_score": score,
                }
            )
    return selected, excluded


def _find_judge_projection(run: ReviewedRun) -> Path:
    """定位官方 Judge 已消费的 submissions、轨迹和最佳 workspace 投影。"""

    root = run.run_dir / "controller" / "naturebench_judge"
    final_evaluation = run.summary.get("final_evaluation")
    request_id = None
    if isinstance(final_evaluation, Mapping):
        request_id = final_evaluation.get("transport_request_id")
        extra = final_evaluation.get("extra")
        if not request_id and isinstance(extra, Mapping):
            request_id = extra.get("transport_request_id")
    candidates: list[Path] = []
    if isinstance(request_id, str) and request_id:
        candidates.append(root / request_id)
    if root.is_dir():
        candidates.extend(sorted((path for path in root.iterdir() if path.is_dir()), reverse=True))

    for candidate in candidates:
        task_dir = candidate / run.task_id
        if (
            (task_dir / "submissions.jsonl").is_file()
            and (task_dir / "famou.jsonl").is_file()
        ):
            return candidate
    raise ValueError(f"{run.task_id}: 找不到完整 NatureBench Judge 证据投影")


def _read_attempts(path: Path) -> tuple[list[dict[str, Any]], float]:
    """读取官方 submissions.jsonl 并返回全部记录与最高数值分数。"""

    attempts: list[dict[str, Any]] = []
    scores: list[float] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as exc:
        raise ValueError(f"无法读取 submissions.jsonl {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} 不是合法 JSONL: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
        attempts.append(value)
        score = _finite_number(value.get("aggregate_improvement"))
        if score is not None:
            scores.append(score)
    if not scores:
        raise ValueError(f"{path}: 已评审运行没有数值 evaluator attempt")
    return attempts, max(scores)


def _substitute(pattern: re.Pattern[str], replacement: str, text: str, stats: RedactionStats) -> str:
    """执行一次正则脱敏并累计实际替换数量。"""

    updated, count = pattern.subn(replacement, text)
    stats.add(count)
    return updated


def _sanitize_text(text: str, run_dir: Path | None, stats: RedactionStats) -> str:
    """移除公开包中的凭据、内网 endpoint 和 CFS 绝对路径。"""

    if run_dir is not None:
        variants = {str(run_dir), str(run_dir.resolve())}
        for value in sorted(variants, key=len, reverse=True):
            if value:
                count = text.count(value)
                if count:
                    text = text.replace(value, "<RUN_DIR>")
                    stats.add(count)
    text = _substitute(_BEARER_RE, r"\1<REDACTED>", text, stats)
    text = _substitute(_SECRET_ASSIGNMENT_RE, r"\1<REDACTED>", text, stats)
    text = _substitute(_URL_USERINFO_RE, r"\1<REDACTED>@", text, stats)
    text = _substitute(_PRIVATE_ENDPOINT_RE, "<PRIVATE_ENDPOINT>", text, stats)
    text = _substitute(_PRIVATE_IP_RE, "<PRIVATE_ENDPOINT>", text, stats)
    text = _substitute(_PRIVATE_PATH_RE, "<PRIVATE_PATH>", text, stats)
    return text


def _sanitize_value(value: Any, run_dir: Path | None, stats: RedactionStats) -> Any:
    """递归脱敏 JSON 兼容对象中的所有字符串值。"""

    if isinstance(value, str):
        return _sanitize_text(value, run_dir, stats)
    if isinstance(value, list):
        return [_sanitize_value(item, run_dir, stats) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item, run_dir, stats)
            for key, item in value.items()
        }
    return value


def _write_json(path: Path, value: Any) -> None:
    """以稳定、可审计的格式写入 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    """逐行写入 JSON 对象，保持官方 submissions/trajectory 结构。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _export_trajectory(
    source: Path,
    destination: Path,
    run_dir: Path,
    stats: RedactionStats,
) -> None:
    """导出完整 JSONL 轨迹，同时保持每行仍是合法 JSON。"""

    records: list[Mapping[str, Any]] = []
    try:
        lines = source.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as exc:
        raise ValueError(f"无法读取 trajectory {source}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source}:{line_number} 不是合法 JSONL: {exc}") from exc
        if not isinstance(value, Mapping):
            raise ValueError(f"{source}:{line_number} 必须是 JSON 对象")
        records.append(_sanitize_value(value, run_dir, stats))
    if not records:
        raise ValueError(f"完整轨迹为空: {source}")
    _write_jsonl(destination, records)


def _copy_workspace(
    source: Path,
    destination: Path,
    run_dir: Path,
    stats: RedactionStats,
) -> int:
    """复制 Judge 使用的最佳 workspace 源码，并跳过二进制文件和符号链接。"""

    if not source.is_dir():
        return 0
    copied = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_sanitize_text(text, run_dir, stats), encoding="utf-8")
        copied += 1
    return copied


def _assert_public_tree(root: Path) -> None:
    """拒绝发布仍含明显私有路径、endpoint 或明文凭据的文本产物。"""

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            continue
        residual = (
            _PRIVATE_PATH_RE.search(text)
            or _PRIVATE_ENDPOINT_RE.search(text)
            or _PRIVATE_IP_RE.search(text)
            or _BEARER_RE.search(text)
            or _URL_USERINFO_RE.search(text)
        )
        if residual is not None:
            raise ValueError(f"公开包仍含私有信息 {path}: {residual.group(0)!r}")
        for match in _SECRET_ASSIGNMENT_RE.finditer(text):
            if "<REDACTED>" not in match.group(0):
                raise ValueError(f"公开包仍含疑似明文凭据 {path}: {match.group(1)!r}")


def _sha256(path: Path) -> str:
    """计算单个公开产物的 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_placeholder(case_dir: Path, case_id: str) -> None:
    """为未上报 case 生成官方校验器要求的诚实占位记录。"""

    _write_json(
        case_dir / "result.json",
        {
            "task_id": case_id,
            "status": "not_run",
            "outcome": "not_run",
            "reason": "No reviewed Famou run is included in this submission.",
        },
    )
    (case_dir / "submissions.jsonl").write_text("", encoding="utf-8")
    _write_jsonl(
        case_dir / "trajectory.placeholder.jsonl",
        [
            {
                "type": "submission-placeholder",
                "case_id": case_id,
                "status": "not_run",
                "message": "This case has no reviewed run in the submitted result set.",
            }
        ],
    )


def _export_reviewed_case(
    run: ReviewedRun,
    case_dir: Path,
    stats: RedactionStats,
) -> dict[str, Any]:
    """导出一个已评审 case 的全部官方必需证据和最佳源码快照。"""

    projection = _find_judge_projection(run)
    projected_task = projection / run.task_id
    attempts, attempts_best = _read_attempts(projected_task / "submissions.jsonl")
    summary_score = _finite_number(run.summary.get("best_score"))
    if summary_score is None or not math.isclose(
        summary_score,
        attempts_best,
        rel_tol=_SCORE_TOLERANCE,
        abs_tol=_SCORE_TOLERANCE,
    ):
        raise ValueError(
            f"{run.task_id}: run_summary best_score={summary_score} 与 "
            f"submissions 最大值={attempts_best} 不一致"
        )

    sanitized_summary = _sanitize_value(run.summary, run.run_dir, stats)
    _write_json(case_dir / "result.json", sanitized_summary)
    safe_attempts = _sanitize_value(attempts, run.run_dir, stats)
    if not isinstance(safe_attempts, list):
        raise ValueError(f"{run.task_id}: submissions.jsonl 脱敏后结构损坏")
    if any(not isinstance(item, Mapping) for item in safe_attempts):
        raise ValueError(f"{run.task_id}: submissions.jsonl 脱敏后记录类型损坏")
    _write_jsonl(
        case_dir / "submissions.jsonl",
        safe_attempts,
    )
    _write_json(
        case_dir / "judge_verdict.json",
        {"is_valid": run.is_valid, "reason": run.judge_reason},
    )
    _export_trajectory(
        projected_task / "famou.jsonl",
        case_dir / "trajectory.famou.jsonl",
        run.run_dir,
        stats,
    )
    workspace_files = _copy_workspace(
        projected_task / "workspace",
        case_dir / "workspace",
        run.run_dir,
        stats,
    )
    return {
        "case_id": run.task_id,
        "source_run_id": run.run_dir.name,
        "best_score": summary_score,
        "judge_verdict": "valid" if run.is_valid else "invalid",
        "attempt_count": len(attempts),
        "workspace_text_files": workspace_files,
    }


def _write_submission_yaml(path: Path, args: argparse.Namespace) -> None:
    """写入官方字段严格匹配的 submission.yaml。"""

    payload = {
        "submission": {
            "model": args.model,
            "agent": args.agent,
            "organization": args.organization,
            "url": args.url,
            "submission_date": args.submission_date,
            "contact": args.contact,
        },
        "evaluation": {
            "timeout_seconds": args.timeout_seconds,
            "web_search": args.web_search,
            "compute": args.compute,
            "judge_model": args.judge_model,
            "human_intervention": args.human_intervention,
            "deviations_from_reference": args.deviations_from_reference,
        },
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def export_submission(args: argparse.Namespace) -> dict[str, Any]:
    """执行完整官方目录导出，并以原子重命名发布结果。"""

    metadata = _load_case_metadata(args.case_metadata)
    official_case_ids = {case_id for case_id, _ in metadata}
    adopted = load_adopted_runs(getattr(args, "adopted_runs", None))
    reviewed, excluded = discover_reviewed_runs(args.runs_dir, official_case_ids, adopted)
    if adopted is not None:
        missing = sorted(set(adopted) - set(reviewed))
        if missing:
            raise ValueError(
                "采用清单中的以下 case 未能在运行目录中定位到指定 Run: "
                + ", ".join(missing)
            )
    destination = args.output_dir
    if destination.exists():
        raise ValueError(f"输出目录已存在，请更换名称或先人工归档: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    stats = RedactionStats()
    exported_cases: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    try:
        _write_submission_yaml(staging / "submission.yaml", args)
        raw_results = staging / "raw-results"
        raw_results.mkdir()
        for case_id, domain in metadata:
            case_dir = raw_results / case_id
            case_dir.mkdir()
            run = reviewed.get(case_id)
            if run is None:
                _write_placeholder(case_dir, case_id)
                rows.append(
                    {
                        "case_id": case_id,
                        "final_status": "not_run",
                        "best_score": "",
                        "judge_verdict": "not_applicable",
                        "judge_reason": "not_applicable",
                    }
                )
                continue
            exported = _export_reviewed_case(run, case_dir, stats)
            exported["domain"] = domain
            exported_cases.append(exported)
            rows.append(
                {
                    "case_id": case_id,
                    "final_status": str(run.summary.get("status") or "completed"),
                    "best_score": repr(float(run.summary["best_score"])),
                    "judge_verdict": "valid" if run.is_valid else "invalid",
                    "judge_reason": run.judge_reason,
                }
            )

        with (staging / "results.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=_RESULT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        (raw_results / "README.md").write_text(
            "# Famou NatureBench raw results\n\n"
            "Scored cases contain the official evaluator attempt history, the exact Boolean "
            "validity verdict, a redacted complete Famou trajectory, and the text-source "
            "workspace used by the validity judge. Unscored cases use explicit `not_run` "
            "placeholder records because the official validator requires all 90 case "
            "directories. Internal CFS paths, credentials, and private endpoints are redacted; "
            "the immutable originals remain in the private Famou evidence store.\n",
            encoding="utf-8",
        )
        _assert_public_tree(raw_results)
        _write_json(
            staging / "export_manifest.json",
            {
                "format": "NatureBench leaderboard submission",
                "official_case_count": len(metadata),
                "reviewed_case_count": len(exported_cases),
                "valid_case_count": sum(item["judge_verdict"] == "valid" for item in exported_cases),
                "invalid_case_count": sum(item["judge_verdict"] == "invalid" for item in exported_cases),
                "redaction_replacements": stats.replacements,
                "selected_runs": exported_cases,
                "excluded_runs": excluded,
                "required_file_hashes": {
                    "submission.yaml": _sha256(staging / "submission.yaml"),
                    "results.csv": _sha256(staging / "results.csv"),
                },
            },
        )
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "output_dir": str(destination),
        "official_case_count": len(metadata),
        "reviewed_case_count": len(exported_cases),
        "valid_case_count": sum(item["judge_verdict"] == "valid" for item in exported_cases),
        "invalid_case_count": sum(item["judge_verdict"] == "invalid" for item in exported_cases),
        "redaction_replacements": stats.replacements,
    }


def build_parser() -> argparse.ArgumentParser:
    """构造 Leaderboard 导出命令行参数。"""

    default_metadata = Path(__file__).with_name("leaderboard") / "case_metadata.csv"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=Path(".famou/naturebench-runs"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-metadata", type=Path, default=default_metadata)
    parser.add_argument(
        "--adopted-runs",
        type=Path,
        default=None,
        help="采用清单 JSON：case_id -> {run_id, is_valid, reason}。"
        "给定时严格按清单选取 Run 与 Judge 结论，否则自动选 finished_at 最新的已评审运行。",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--contact", required=True)
    parser.add_argument("--submission-date", default=date.today().isoformat())
    parser.add_argument("--timeout-seconds", type=int, default=14400)
    parser.add_argument("--web-search", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--compute", required=True)
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--human-intervention", default="none")
    parser.add_argument("--deviations-from-reference", default="none")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """运行导出命令并打印机器可读摘要。"""

    args = build_parser().parse_args(argv)
    try:
        report = export_submission(args)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
