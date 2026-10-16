"""把 Famou canonical evidence 投影为 NatureBench 官方 Judge 输入。"""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...utils import atomic_write_json, atomic_write_text, safe_name, sha256_file


_TRACE_PATTERNS = {
    "claude": (
        "branches/*/logs/claude_home/.claude/projects/**/*.jsonl",
        "idea_agent_workspaces/branches/*/logs/claude_home/.claude/projects/**/*.jsonl",
    ),
    "codex": (
        "branches/*/logs/codex_home/.codex/sessions/**/*.jsonl",
        "idea_agent_workspaces/branches/*/logs/codex_home/.codex/sessions/**/*.jsonl",
    ),
    "gemini": (
        "branches/*/logs/gemini_home/.gemini/tmp/**/chats/*.json",
        "branches/*/logs/gemini_home/.gemini/tmp/**/chats/*.jsonl",
        "idea_agent_workspaces/branches/*/logs/gemini_home/.gemini/tmp/**/chats/*.json",
        "idea_agent_workspaces/branches/*/logs/gemini_home/.gemini/tmp/**/chats/*.jsonl",
    ),
}


def _safe_component(value: str, *, label: str) -> str:
    """校验来自请求的值可以安全地作为单个目录名使用。"""

    text = str(value).strip()
    if not text or safe_name(text) != text or Path(text).name != text:
        raise ValueError(f"无效的 {label}: {value!r}")
    return text


def _read_json(path: Path) -> dict[str, Any]:
    """读取顶层为对象的 JSON 文件。"""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 对象并忽略空行，不吞掉格式错误。"""

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL 第 {line_number} 行不是对象: {path}")
        records.append(value)
    return records


def _timestamp_iso(value: Any) -> str | None:
    """把秒、毫秒或 ISO 时间统一为 UTC ISO 8601。"""

    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = float(value)
            if abs(seconds) >= 100_000_000_000:
                seconds /= 1000.0
            parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return _timestamp_iso(float(text))
            except ValueError:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                parsed = parsed.astimezone(timezone.utc)
        else:
            return None
    except (OSError, OverflowError, ValueError):
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp_epoch(value: Any, *, fallback: float) -> float:
    """把任意受支持时间转换为用于排序的 Unix 秒。"""

    normalized = _timestamp_iso(value)
    if normalized is None:
        return fallback
    try:
        return datetime.fromisoformat(
            normalized.replace("Z", "+00:00")
        ).timestamp()
    except ValueError:
        return fallback


def _record_timestamp(record: Mapping[str, Any], path: Path) -> float:
    """提取一次评测完成时间，旧证据缺字段时使用记录文件时间。"""

    evaluation = record.get("evaluation")
    values: list[Any] = []
    if isinstance(evaluation, Mapping):
        values.extend(
            evaluation.get(key)
            for key in ("evaluated_at", "finished_at", "created_at")
        )
    values.extend(record.get(key) for key in ("updated_at", "created_at"))
    for value in values:
        normalized = _timestamp_iso(value)
        if normalized is not None:
            return _timestamp_epoch(normalized, fallback=path.stat().st_mtime)
    return path.stat().st_mtime


def _evaluation_extra(record: Mapping[str, Any]) -> dict[str, Any]:
    """读取 ExpBank 中已脱敏且由 benchmark 声明公开的评测扩展字段。"""

    evaluation = record.get("evaluation")
    if not isinstance(evaluation, Mapping):
        return {}
    extra = evaluation.get("extra")
    return dict(extra) if isinstance(extra, Mapping) else {}


def _score(record: Mapping[str, Any]) -> float | None:
    """返回 ExpBank 记录中的有限数值分数。"""

    value = record.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _record_is_valid(record: Mapping[str, Any]) -> bool:
    """只有可信 evaluator 明确确认完整时，记录才可用于官方最佳候选。"""

    evaluation = record.get("evaluation")
    if not isinstance(evaluation, Mapping) or evaluation.get("valid") is not True:
        return False
    # 新版 evaluator 将主实例缺失/错误显式写入 extra；兼容旧记录时没有该字段，
    # 仍由 valid=true 决定，避免把历史 schema 当成失败记录。
    extra = evaluation.get("extra")
    if isinstance(extra, Mapping):
        failures = extra.get("primary_instance_failures")
        if isinstance(failures, list) and failures:
            return False
        raw_scores = extra.get("raw_scores")
        if _contains_nonempty_error(raw_scores):
            return False
    return _score(record) is not None


def _contains_nonempty_error(value: Any) -> bool:
    """识别旧 evaluator 只返回 aggregate、但实例块含错误的记录。"""

    if isinstance(value, Mapping):
        return any(
            (str(key).lower() == "error" and item not in (None, "", [], {}))
            or _contains_nonempty_error(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_nonempty_error(item) for item in value)
    return False


def _expbank_records(run_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """按 ExpBank 编号读取所有科研尝试记录。"""

    records: list[tuple[Path, dict[str, Any]]] = []
    pattern = "[0-9][0-9][0-9][0-9]/record.json"
    for path in sorted((run_dir / "expbank").glob(pattern)):
        try:
            record = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        records.append((path, record))
    return records


def _official_attempt_from_record(record: Mapping[str, Any]) -> int | None:
    """读取可信 evaluator 回传的 NatureBench 官方 attempt 编号。"""

    value = _evaluation_extra(record).get("attempt")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _candidate_id_for_attempt(run_dir: Path, attempt_id: str) -> str | None:
    """从冻结运行证据读取产生该 ExpBank 版本的 Candidate 编号。"""

    path = run_dir / "expbank" / attempt_id / "evidence" / "run.json"
    if not path.is_file():
        return None
    try:
        value = _read_json(path).get("candidate_id")
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return str(value) if isinstance(value, str) and value else None


def _submission_map(path: Path | None) -> dict[str, int]:
    """读取可信 Candidate 到 NatureBench attempt 的审计映射。"""

    if path is None or not path.is_file():
        return {}
    mapping: dict[str, int] = {}
    for record in _read_jsonl(path):
        candidate_id = record.get("candidate_id")
        attempt = record.get("attempt")
        if (
            isinstance(candidate_id, str)
            and candidate_id
            and isinstance(attempt, int)
            and not isinstance(attempt, bool)
            and attempt > 0
        ):
            mapping[candidate_id] = attempt
    return mapping


def _fallback_submissions(
    records: Iterable[tuple[Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """从旧 ExpBank 证据恢复与官方 schema 等价的提交历史。"""

    by_attempt: dict[int, dict[str, Any]] = {}
    for path, record in records:
        attempt = _official_attempt_from_record(record)
        if attempt is None:
            continue
        evaluation = record.get("evaluation")
        evaluation = dict(evaluation) if isinstance(evaluation, Mapping) else {}
        extra = _evaluation_extra(record)
        aggregate = extra.get("aggregate_improvement", _score(record))
        completed = _record_is_valid(record)
        timestamp = _record_timestamp(record, path)
        if completed:
            by_attempt[attempt] = {
                "type": "success",
                "attempt": attempt,
                "timestamp": timestamp,
                "raw_scores": extra.get("raw_scores") or {},
                "per_instance_improvement": extra.get(
                    "per_instance_improvement"
                )
                or {},
                "aggregate_improvement": aggregate,
            }
        else:
            by_attempt[attempt] = {
                "type": "failure",
                "attempt": attempt,
                "timestamp": timestamp,
                "raw_scores": None,
                "per_instance_improvement": None,
                "aggregate_improvement": None,
                "error": str(evaluation.get("error") or "evaluation failed"),
            }
    return [by_attempt[key] for key in sorted(by_attempt)]


def _validated_submissions(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """校验提交历史的关键字段并保持 benchmark 原生扩展字段。"""

    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for record in records:
        attempt = record.get("attempt")
        record_type = record.get("type", "success")
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt <= 0
            or record_type not in {"success", "failure"}
        ):
            raise ValueError("NatureBench submissions.jsonl 含无效记录")
        if attempt in seen:
            raise ValueError(f"NatureBench attempt 重复: {attempt}")
        seen.add(attempt)
        normalized.append(dict(record))
    return sorted(normalized, key=lambda item: int(item["attempt"]))


def _trace_sources(run_dir: Path, preferred_runtime: str) -> list[Path]:
    """优先使用 Infra 统一轨迹，旧 Run 才回退原生 CLI Session。"""

    canonical = run_dir / "artifacts" / "agent_trajectory.jsonl"
    if canonical.is_file() and canonical.stat().st_size > 0:
        return [canonical]

    runtimes = [preferred_runtime]
    runtimes.extend(runtime for runtime in _TRACE_PATTERNS if runtime not in runtimes)
    paths: set[Path] = set()
    for runtime in runtimes:
        for pattern in _TRACE_PATTERNS.get(runtime, ()):
            paths.update(path for path in run_dir.glob(pattern) if path.is_file())
    return sorted(paths, key=lambda path: (path.stat().st_mtime, str(path)))


def _iter_trace_records(paths: Iterable[Path]) -> Iterable[tuple[float, int, str]]:
    """读取 CLI JSONL；统一轨迹在 benchmark 边界投影回原生 payload。"""

    sequence = 0
    for path in paths:
        fallback = path.stat().st_mtime
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue
            # Infra canonical trajectory 使用统一 envelope 保存角色、Session 和
            # 来源。NatureBench Judge 需要 Agent CLI 原生记录，因此这里只在
            # benchmark adapter 边界解包；核心调度器不感知官方格式。
            projected = (
                value["payload"]
                if value.get("schema_version") and isinstance(value.get("payload"), dict)
                else value
            )
            timestamp = value.get("timestamp")
            if timestamp is None:
                timestamp = projected.get("timestamp")
            yield (
                _timestamp_epoch(timestamp, fallback=fallback),
                sequence,
                json.dumps(projected, ensure_ascii=False),
            )
            sequence += 1


def _controller_trace_records(run_dir: Path) -> list[tuple[float, int, str]]:
    """把 benchmark 无关的 Controller 事件补充成官方解析器可读记录。"""

    path = run_dir / "controller" / "trajectory.jsonl"
    if not path.is_file():
        return []
    records: list[tuple[float, int, str]] = []
    fallback = path.stat().st_mtime
    for sequence, event in enumerate(_read_jsonl(path)):
        timestamp = _timestamp_iso(event.get("timestamp_ms"))
        record = {
            "timestamp": timestamp,
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "[Famou Controller] "
                        + json.dumps(event, ensure_ascii=False),
                    }
                ]
            },
        }
        records.append(
            (
                _timestamp_epoch(timestamp, fallback=fallback),
                1_000_000_000 + sequence,
                json.dumps(record, ensure_ascii=False),
            )
        )
    return records


def _source_manifest(run_dir: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    """生成不依赖绝对 CFS 前缀的 canonical source 哈希清单。"""

    manifest: list[dict[str, Any]] = []
    for path in paths:
        manifest.append(
            {
                "path": str(path.relative_to(run_dir)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return manifest


def _copy_code_snapshot(source: Path, destination: Path) -> None:
    """复制冻结代码，并拒绝可能跨越证据边界的符号链接。"""

    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"冻结代码包含符号链接，不能交给 Judge: {path}")
    shutil.copytree(source, destination, symlinks=False)


class NatureBenchTrajectoryAdapter:
    """将完整 Famou 证据确定性转换为 NatureBench-native Judge 目录。"""

    name = "naturebench"
    judge_agent_name = "famou"

    def project(
        self,
        *,
        task_id: str,
        run_dir: str | Path,
        best_attempt_id: str,
        agent_runtime: str,
        request_id: str,
        submissions_path: str | Path | None = None,
        submission_map_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """创建官方 workspace、评分时间线、轨迹和可审计来源清单。"""

        resolved_run = Path(run_dir).expanduser().resolve()
        task_name = _safe_component(task_id, label="task_id")
        request_name = _safe_component(request_id, label="request_id")
        attempt_name = _safe_component(best_attempt_id, label="best_attempt_id")
        best_path = resolved_run / "expbank" / attempt_name / "record.json"
        if not best_path.is_file():
            raise FileNotFoundError(f"最佳 ExpBank 记录不存在: {best_path}")
        best_record = _read_json(best_path)
        if not _record_is_valid(best_record):
            raise ValueError(
                f"最佳 ExpBank attempt 不是可信完整评测结果: {attempt_name}"
            )
        best_score = _score(best_record)
        if best_score is None:
            raise ValueError(f"最佳 ExpBank attempt 没有正式数值分数: {attempt_name}")
        code_dir = resolved_run / "expbank" / attempt_name / "code"
        if not code_dir.is_dir():
            raise FileNotFoundError(f"最佳 attempt 缺少冻结代码: {code_dir}")

        native_submissions = (
            Path(submissions_path).expanduser().resolve()
            if submissions_path is not None
            else None
        )
        records = _expbank_records(resolved_run)
        submissions = _validated_submissions(
            _read_jsonl(native_submissions)
            if native_submissions is not None and native_submissions.is_file()
            else _fallback_submissions(records)
        )
        if not submissions:
            raise FileNotFoundError("没有可供 NatureBench Judge 使用的正式评测历史")

        official_attempt = _official_attempt_from_record(best_record)
        candidate_id = _candidate_id_for_attempt(resolved_run, attempt_name)
        mapping_path = (
            Path(submission_map_path).expanduser().resolve()
            if submission_map_path is not None
            else None
        )
        if candidate_id:
            official_attempt = _submission_map(mapping_path).get(
                candidate_id, official_attempt
            )
        available_attempts = {int(item["attempt"]) for item in submissions}
        if official_attempt is None:
            score_matches = [
                int(item["attempt"])
                for item in submissions
                if isinstance(item.get("aggregate_improvement"), (int, float))
                and math.isclose(
                    float(item["aggregate_improvement"]),
                    best_score,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ]
            if len(score_matches) == 1:
                official_attempt = score_matches[0]
        if official_attempt not in available_attempts:
            raise ValueError(
                "无法把最佳 ExpBank attempt 精确映射到 NatureBench 官方 attempt"
            )

        judge_root = (
            resolved_run / "controller" / "naturebench_judge" / request_name
        )
        manifest_path = judge_root / "judge_input_manifest.json"
        if manifest_path.is_file():
            existing = _read_json(manifest_path)
            if (
                existing.get("task_id") == task_name
                and existing.get("best_attempt_id") == attempt_name
            ):
                return existing
            raise FileExistsError(f"Judge request_id 已被其他输入占用: {request_name}")

        task_out_dir = judge_root / task_name
        workspace = task_out_dir / "workspace"
        workspace.parent.mkdir(parents=True, exist_ok=False)
        _copy_code_snapshot(code_dir, workspace)
        atomic_write_text(
            task_out_dir / "submissions.jsonl",
            "".join(
                json.dumps(item, ensure_ascii=False) + "\n" for item in submissions
            ),
        )
        atomic_write_json(
            judge_root / "run_summary.json",
            {
                "results": [
                    {
                        "task_name": task_name,
                        "best_attempt": official_attempt,
                        "best_aggregate_improvement": best_score,
                        "total_attempts": len(submissions),
                    }
                ]
            },
        )

        trace_sources = _trace_sources(resolved_run, str(agent_runtime))
        trace_records = list(_iter_trace_records(trace_sources))
        trace_records.extend(_controller_trace_records(resolved_run))
        trace_records.sort(key=lambda item: (item[0], item[1]))
        trace_path = task_out_dir / "famou.jsonl"
        atomic_write_text(
            trace_path,
            "".join(item[2] + "\n" for item in trace_records),
        )
        canonical_sources = list(trace_sources)
        for path in (
            resolved_run / "artifacts" / "artifact_index.jsonl",
            resolved_run / "controller" / "trajectory.jsonl",
        ):
            if path.is_file() and path not in canonical_sources:
                canonical_sources.append(path)

        manifest = {
            "adapter": self.name,
            "task_id": task_name,
            "request_id": request_name,
            "best_attempt_id": attempt_name,
            "candidate_id": candidate_id,
            "score_attempt": official_attempt,
            "best_score": best_score,
            "code_source": str(code_dir.relative_to(resolved_run)),
            "task_out_dir": str(task_out_dir),
            "submissions": {
                "target": str(task_out_dir / "submissions.jsonl"),
                "records": len(submissions),
                "source": (
                    "trusted_evaluator_history"
                    if native_submissions is not None and native_submissions.is_file()
                    else "expbank_fallback"
                ),
                "source_sha256": (
                    sha256_file(native_submissions)
                    if native_submissions is not None and native_submissions.is_file()
                    else None
                ),
            },
            "trace": {
                "judge_agent": self.judge_agent_name,
                "target": str(trace_path),
                "records": len(trace_records),
                "sources": _source_manifest(resolved_run, trace_sources),
            },
            "canonical_sources": _source_manifest(
                resolved_run, canonical_sources
            ),
        }
        atomic_write_json(manifest_path, manifest)
        return manifest


__all__ = ["NatureBenchTrajectoryAdapter"]
