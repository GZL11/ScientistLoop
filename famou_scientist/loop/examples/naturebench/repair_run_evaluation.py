#!/usr/bin/env python3
"""在不重跑 Agent 的前提下，审计并修复 NatureBench 历史 Run 的评测证据。"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# 该工具既支持 ``python -m``，也支持从 fm-job 脚本按文件路径直接执行。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from famou_scientist.loop.integrations.naturebench.judge_adapter import (
    NatureBenchJudgeAdapter,
)
from famou_scientist.loop.storage.expbank import ExpBank
from famou_scientist.loop.utils import (
    atomic_write_json,
    atomic_write_text,
    now_ms,
    read_json,
    sha256_file,
)


@dataclass(frozen=True)
class Candidate:
    """描述一次已冻结、可重新交给官方 evaluator 的 Candidate。"""

    candidate_id: str
    expbank_attempt_id: str
    branch_id: str
    created_at: int
    directory: Path
    submission_dir: Path


def _json_object(path: Path) -> dict[str, Any]:
    """读取 JSON 对象并拒绝缺失或非对象内容。"""

    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return value


def _last_json_object(stdout: str) -> dict[str, Any]:
    """从 evaluator 标准输出末尾提取统一结果对象。"""

    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "valid" in value:
            return value
    raise ValueError("evaluator 未输出包含 valid 字段的 JSON 对象")


def _finite_score(result: Mapping[str, Any]) -> float | None:
    """读取有限 aggregate_improvement；无效结果不能参与最佳候选选择。"""

    metrics = result.get("official_metrics")
    value = metrics.get("aggregate_improvement") if isinstance(metrics, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _discover_candidates(run_dir: Path) -> list[Candidate]:
    """按原始提交时间发现带 ExpBank 映射和提交产物的 Candidate。"""

    candidates: list[Candidate] = []
    for directory in sorted((run_dir / "candidates").glob("candidate_*")):
        manifest_path = directory / "manifest.json"
        submission_dir = directory / "output" / "submission"
        if not manifest_path.is_file() or not submission_dir.is_dir():
            continue
        manifest = _json_object(manifest_path)
        attempt_id = manifest.get("expbank_attempt_id")
        candidate_id = manifest.get("candidate_id") or directory.name
        if not isinstance(attempt_id, str) or not attempt_id:
            continue
        candidates.append(
            Candidate(
                candidate_id=str(candidate_id),
                expbank_attempt_id=attempt_id,
                branch_id=str(manifest.get("branch_id") or ""),
                created_at=int(manifest.get("created_at") or 0),
                directory=directory,
                submission_dir=submission_dir,
            )
        )
    return sorted(candidates, key=lambda item: (item.created_at, item.candidate_id))


def _repair_evaluator_executables(evaluation_dir: Path) -> list[str]:
    """恢复官方任务包中 ELF/shebang 工具遗漏的属主执行位。"""

    repaired: list[str] = []
    for path in sorted(evaluation_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            prefix = stream.read(4)
        if (prefix == b"\x7fELF" or prefix.startswith(b"#!")) and not (
            path.stat().st_mode & stat.S_IXUSR
        ):
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            repaired.append(str(path.relative_to(evaluation_dir)))
    return repaired


def _evaluate_candidate(
    candidate: Candidate,
    *,
    task_dir: Path,
    adapter_script: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    """调用薄适配器重评一个 Candidate，并保留完整子进程证据。"""

    command = [
        sys.executable,
        str(adapter_script),
        "--task-dir",
        str(task_dir),
        "--submission-dir",
        str(candidate.submission_dir),
    ]
    started_at = now_ms()
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        try:
            result = _last_json_object(process.stdout)
        except Exception as exc:  # noqa: BLE001 - 解析错误属于重评证据
            result = {
                "valid": False,
                "official_metrics": {},
                "diagnostics_public": {},
                "extra": {},
                "extra_public": {},
                "error": repr(exc),
            }
        returncode = process.returncode
        stdout = process.stdout
        stderr = process.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        result = {
            "valid": False,
            "official_metrics": {},
            "diagnostics_public": {"evaluation_completed": False},
            "extra": {},
            "extra_public": {},
            "error": f"post-hoc evaluation timed out after {timeout_sec} seconds",
        }
        returncode = 124
    return {
        "candidate_id": candidate.candidate_id,
        "expbank_attempt_id": candidate.expbank_attempt_id,
        "branch_id": candidate.branch_id,
        "command": command,
        "started_at": started_at,
        "finished_at": now_ms(),
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "result": result,
    }


def _load_existing_evaluation(path: Path, candidate: Candidate) -> dict[str, Any] | None:
    """兼容读取完整重评包装或早期仅保存 evaluator 结果的文件。"""

    if not path.is_file():
        return None
    value = _json_object(path)
    result = value.get("result")
    if isinstance(result, dict):
        return value
    if "valid" not in value:
        return None
    return {
        "candidate_id": candidate.candidate_id,
        "expbank_attempt_id": candidate.expbank_attempt_id,
        "branch_id": candidate.branch_id,
        "command": [],
        "started_at": None,
        "finished_at": None,
        "returncode": 0 if value.get("valid") is True else 2,
        "stdout": "",
        "stderr": "",
        "result": value,
        "imported_from_legacy_repair_output": True,
    }


def _official_attempt_map(run_dir: Path, candidates: list[Candidate]) -> dict[str, int]:
    """尽量沿用原始官方 attempt 编号，新增 Candidate 才按时间补号。"""

    mapping: dict[str, int] = {}
    path = run_dir / "trusted" / "raw_evaluator_artifacts" / "submission_map.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            candidate_id = value.get("candidate_id")
            attempt = value.get("attempt")
            if isinstance(candidate_id, str) and isinstance(attempt, int) and attempt > 0:
                mapping[candidate_id] = attempt
    next_attempt = max(mapping.values(), default=0) + 1
    for candidate in candidates:
        if candidate.candidate_id not in mapping:
            mapping[candidate.candidate_id] = next_attempt
            next_attempt += 1
    return mapping


def _public_evaluation(task_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """把薄适配器结果转换为 ExpBank 使用的公开正式评测结构。"""

    public_extra = result.get("extra_public")
    if not isinstance(public_extra, Mapping):
        public_extra = result.get("extra") if isinstance(result.get("extra"), Mapping) else {}
    return {
        "benchmark": f"naturebench/{task_id}",
        "source": "official_evaluator",
        "valid": result.get("valid") is True,
        "official_metrics": dict(result.get("official_metrics") or {}),
        "redacted_for_agent": True,
        "diagnostics_public": dict(result.get("diagnostics_public") or {}),
        "extra": dict(public_extra),
        "error": result.get("error_public") or result.get("error"),
    }


def _write_native_history(
    repair_dir: Path,
    evaluations: Mapping[str, dict[str, Any]],
    attempt_map: Mapping[str, int],
) -> tuple[Path, Path]:
    """重建 NatureBench 原生提交历史及 Candidate 映射。"""

    submissions: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for candidate_id, attempt in sorted(attempt_map.items(), key=lambda item: item[1]):
        wrapper = evaluations.get(candidate_id)
        if wrapper is None:
            continue
        result = wrapper["result"]
        extra = result.get("extra") if isinstance(result.get("extra"), Mapping) else {}
        score = _finite_score(result)
        timestamp = float(wrapper.get("finished_at") or now_ms()) / 1000.0
        if result.get("valid") is True and score is not None:
            record = {
                "type": "success",
                "attempt": attempt,
                "timestamp": timestamp,
                "raw_scores": extra.get("raw_scores") or {},
                "per_instance_improvement": extra.get("per_instance_improvement") or {},
                "aggregate_improvement": score,
            }
        else:
            record = {
                "type": "failure",
                "attempt": attempt,
                "timestamp": timestamp,
                "raw_scores": None,
                "per_instance_improvement": None,
                "aggregate_improvement": None,
                "error": str(result.get("error") or "evaluation invalid"),
            }
        submissions.append(record)
        mappings.append(
            {
                "candidate_id": candidate_id,
                "attempt": attempt,
                "timestamp": timestamp,
                "repair_id": repair_dir.name,
            }
        )
    submissions_path = repair_dir / "submissions.jsonl"
    mapping_path = repair_dir / "submission_map.jsonl"
    atomic_write_text(
        submissions_path,
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in submissions),
    )
    atomic_write_text(
        mapping_path,
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in mappings),
    )
    return submissions_path, mapping_path


def _backup_json(path: Path, run_dir: Path, repair_dir: Path) -> None:
    """在首次修改前按 Run 相对路径保存 JSON 快照。"""

    if not path.is_file():
        return
    destination = repair_dir / "before" / path.relative_to(run_dir)
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def _load_judge_settings(path: Path) -> None:
    """仅在可信修复进程中加载官方 Judge 所需环境变量。"""

    raw = _json_object(path)
    values = raw.get("env")
    if not isinstance(values, Mapping):
        raise ValueError(f"Judge settings 缺少 env: {path}")
    for key, value in values.items():
        if isinstance(key, str) and isinstance(value, str) and key.startswith(("JUDGE_", "ANTHROPIC_")):
            os.environ[key] = value
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if token and not any(
        os.environ.get(name)
        for name in ("JUDGE_ANTHROPIC_API_KEY", "JUDGE_API_KEY", "ANTHROPIC_API_KEY")
    ):
        os.environ["JUDGE_ANTHROPIC_API_KEY"] = token


def _apply_repair(
    *,
    run_dir: Path,
    task_dir: Path,
    task_id: str,
    repair_dir: Path,
    candidates: list[Candidate],
    evaluations: Mapping[str, dict[str, Any]],
    submissions_path: Path,
    submission_map_path: Path,
    run_judge: bool,
    judge_model: str | None,
    agent_runtime: str,
) -> dict[str, Any]:
    """原子更新公开科研记录，并可选重新执行官方 Validity Judge。"""

    valid_candidates = [
        (candidate, _finite_score(evaluations[candidate.candidate_id]["result"]))
        for candidate in candidates
        if candidate.candidate_id in evaluations
        and evaluations[candidate.candidate_id]["result"].get("valid") is True
        and _finite_score(evaluations[candidate.candidate_id]["result"]) is not None
    ]
    if not valid_candidates:
        raise RuntimeError("重评后没有完整有效的 Candidate，不能覆盖历史最佳记录")
    best_candidate, best_score_value = max(valid_candidates, key=lambda item: float(item[1]))
    best_score = float(best_score_value)
    expbank = ExpBank(run_dir)

    controller_paths = [
        run_dir / "controller" / name
        for name in (
            "run_summary.json",
            "promoted_best.json",
            "final_evaluation.json",
            "judge_verdict.json",
        )
    ]
    for path in controller_paths:
        _backup_json(path, run_dir, repair_dir)

    for candidate, score in valid_candidates:
        wrapper = evaluations[candidate.candidate_id]
        result = wrapper["result"]
        evaluation = _public_evaluation(task_id, result)
        record_path = run_dir / "expbank" / candidate.expbank_attempt_id / "record.json"
        candidate_evaluation_path = candidate.directory / "evidence" / "evaluation.json"
        expbank_evaluation_path = (
            run_dir / "expbank" / candidate.expbank_attempt_id / "evidence" / "evaluation.json"
        )
        for path in (record_path, candidate_evaluation_path, expbank_evaluation_path):
            _backup_json(path, run_dir, repair_dir)

        is_best = candidate.candidate_id == best_candidate.candidate_id
        record = expbank.read_attempt(candidate.expbank_attempt_id)
        metadata = dict(record.get("metadata") or {})
        metadata["posthoc_evaluation_repair"] = {
            "repair_id": repair_dir.name,
            "candidate_id": candidate.candidate_id,
            "evidence": str(
                (repair_dir / "evaluations" / f"{candidate.candidate_id}.json").relative_to(run_dir)
            ),
            "applied_at": now_ms(),
        }
        expbank.update_attempt(
            candidate.expbank_attempt_id,
            evaluation=evaluation,
            score=float(score),
            status="best" if is_best else "evaluated",
            promoted=is_best,
            conclusion=(
                "修复 evaluator 基础设施后重评，当前候选成为新的最佳方法。"
                if is_best
                else "修复 evaluator 基础设施后重评，得到完整有效分数。"
            ),
            error=None,
            metadata=metadata,
        )
        expbank.write_evidence_json(candidate.expbank_attempt_id, "evaluation", evaluation)
        candidate_evidence = (
            _json_object(candidate_evaluation_path)
            if candidate_evaluation_path.is_file()
            else {}
        )
        candidate_evidence["official"] = evaluation
        candidate_evidence["posthoc_evaluation_repair"] = metadata[
            "posthoc_evaluation_repair"
        ]
        atomic_write_json(candidate_evaluation_path, candidate_evidence)

    promoted = {
        "branch_id": best_candidate.branch_id,
        "expbank_attempt_id": best_candidate.expbank_attempt_id,
        "candidate_id": best_candidate.candidate_id,
        "score": best_score,
        "code": str(run_dir / "expbank" / best_candidate.expbank_attempt_id / "code"),
        "output": str(best_candidate.submission_dir),
        "promoted_at": now_ms(),
        "source": "posthoc_evaluation_repair",
        "repair_id": repair_dir.name,
    }
    atomic_write_json(run_dir / "controller" / "promoted_best.json", promoted)

    summary_path = run_dir / "controller" / "run_summary.json"
    summary = _json_object(summary_path)
    summary.update(
        {
            "best_score": best_score,
            "effective_score": best_score,
            "best_branch": best_candidate.branch_id,
            "best_attempt_id": best_candidate.expbank_attempt_id,
            "finished_at": now_ms(),
        }
    )
    repairs = list(summary.get("posthoc_evaluation_repairs") or [])
    repairs.append(
        {
            "repair_id": repair_dir.name,
            "reason": "benchmark evaluator infrastructure correction",
            "candidate_count": len(evaluations),
            "valid_candidate_count": len(valid_candidates),
            "best_candidate_id": best_candidate.candidate_id,
            "best_attempt_id": best_candidate.expbank_attempt_id,
            "best_score": best_score,
            "applied_at": now_ms(),
        }
    )
    summary["posthoc_evaluation_repairs"] = repairs

    judge: dict[str, Any] | None = None
    if run_judge:
        settings_path = run_dir / "trusted" / "judge_settings.json"
        _load_judge_settings(settings_path)
        request_id = f"repair_{repair_dir.name}"
        judge = NatureBenchJudgeAdapter().judge(
            task_dir=task_dir,
            run_dir=run_dir,
            best_attempt_id=best_candidate.expbank_attempt_id,
            agent_runtime=agent_runtime,
            request_id=request_id,
            model=judge_model,
            submissions_path=submissions_path,
            submission_map_path=submission_map_path,
        )
        if type(judge.get("is_valid")) is bool:
            final_evaluation = {
                "valid": True,
                "reason": str(judge.get("reason") or ""),
                "invalidate_primary_score": judge["is_valid"] is False,
                "metrics": {},
                "extra": dict(judge),
                **judge,
            }
            summary["effective_score"] = best_score if judge["is_valid"] else None
        else:
            final_evaluation = {
                "is_valid": None,
                "reason": str(judge.get("reason") or "Judge 未完成"),
                "model": judge_model,
                "expbank_attempt_id": best_candidate.expbank_attempt_id,
            }
            summary["effective_score"] = None
        summary["final_evaluation"] = final_evaluation
        atomic_write_json(run_dir / "controller" / "final_evaluation.json", final_evaluation)
        atomic_write_json(run_dir / "controller" / "judge_verdict.json", final_evaluation)
    else:
        pending = {
            "is_valid": None,
            "reason": "数值重评已完成，Validity Judge 待补跑。",
            "expbank_attempt_id": best_candidate.expbank_attempt_id,
        }
        summary["final_evaluation"] = pending
        summary["effective_score"] = None
        atomic_write_json(run_dir / "controller" / "final_evaluation.json", pending)
        atomic_write_json(run_dir / "controller" / "judge_verdict.json", pending)

    atomic_write_json(summary_path, summary)
    report = {
        "repair_id": repair_dir.name,
        "task_id": task_id,
        "candidate_count": len(evaluations),
        "valid_candidate_count": len(valid_candidates),
        "best_candidate_id": best_candidate.candidate_id,
        "best_attempt_id": best_candidate.expbank_attempt_id,
        "best_score": best_score,
        "judge": judge,
        "applied": True,
        "applied_at": now_ms(),
    }
    atomic_write_json(repair_dir / "report.json", report)
    return report


def _apply_judge_only(
    *,
    run_dir: Path,
    task_dir: Path,
    repair_dir: Path,
    judge_model: str | None,
    agent_runtime: str,
) -> dict[str, Any]:
    """对已经完成数值修复的最佳 Candidate 单独补跑官方 Judge。"""

    report_path = repair_dir / "report.json"
    report = _json_object(report_path)
    best_attempt_id = report.get("best_attempt_id")
    best_score = report.get("best_score")
    if not isinstance(best_attempt_id, str) or not best_attempt_id:
        raise ValueError(f"修复报告缺少 best_attempt_id: {report_path}")
    if isinstance(best_score, bool) or not isinstance(best_score, (int, float)):
        raise ValueError(f"修复报告缺少 best_score: {report_path}")
    submissions_path = repair_dir / "submissions.jsonl"
    submission_map_path = repair_dir / "submission_map.jsonl"
    if not submissions_path.is_file() or not submission_map_path.is_file():
        raise FileNotFoundError("Judge-only 需要已经生成的 submissions 和映射证据")

    _load_judge_settings(run_dir / "trusted" / "judge_settings.json")
    request_id = f"repair_{repair_dir.name}"
    judge = NatureBenchJudgeAdapter().judge(
        task_dir=task_dir,
        run_dir=run_dir,
        best_attempt_id=best_attempt_id,
        agent_runtime=agent_runtime,
        request_id=request_id,
        model=judge_model,
        submissions_path=submissions_path,
        submission_map_path=submission_map_path,
    )
    summary_path = run_dir / "controller" / "run_summary.json"
    summary = _json_object(summary_path)
    if type(judge.get("is_valid")) is bool:
        final_evaluation = {
            "valid": True,
            "reason": str(judge.get("reason") or ""),
            "invalidate_primary_score": judge["is_valid"] is False,
            "metrics": {},
            "extra": dict(judge),
            **judge,
        }
        summary["effective_score"] = float(best_score) if judge["is_valid"] else None
    else:
        final_evaluation = {
            "is_valid": None,
            "reason": str(judge.get("reason") or "Judge 未完成"),
            "model": judge_model,
            "expbank_attempt_id": best_attempt_id,
        }
        summary["effective_score"] = None
    summary["final_evaluation"] = final_evaluation
    summary["finished_at"] = now_ms()
    atomic_write_json(run_dir / "controller" / "final_evaluation.json", final_evaluation)
    atomic_write_json(run_dir / "controller" / "judge_verdict.json", final_evaluation)
    atomic_write_json(summary_path, summary)
    report.update(
        {
            "judge": judge,
            "judge_completed": type(judge.get("is_valid")) is bool,
            "judge_updated_at": now_ms(),
        }
    )
    atomic_write_json(report_path, report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    """构建历史 Run 重评命令参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--repair-id", required=True)
    parser.add_argument("--task-dir")
    parser.add_argument("--adapter-script")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--evaluation-timeout-sec", type=float, default=3600)
    parser.add_argument("--force-evaluate", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-only", action="store_true")
    parser.add_argument("--judge-model")
    parser.add_argument("--agent-runtime", default="claude")
    return parser


def main(argv: list[str] | None = None) -> int:
    """重评全部历史 Candidate，并按选项应用修复和补跑 Judge。"""

    args = _build_parser().parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    summary = _json_object(run_dir / "controller" / "run_summary.json")
    task_id = str(summary.get("task_id") or "")
    if not task_id:
        raise ValueError("run_summary 缺少 task_id")
    task_dir = (
        Path(args.task_dir).expanduser().resolve()
        if args.task_dir
        else run_dir
        / "trusted"
        / "naturebench"
        / "data"
        / "naturebench_data"
        / "tasks"
        / task_id
    )
    adapter_script = (
        Path(args.adapter_script).expanduser().resolve()
        if args.adapter_script
        else Path(__file__).resolve().parent / "evaluate_task.py"
    )
    if not (task_dir / "evaluation").is_dir():
        raise FileNotFoundError(f"可信 task evaluator 不存在: {task_dir}")
    repair_dir = run_dir / "trusted" / "repairs" / args.repair_id
    if args.judge_only:
        report = _apply_judge_only(
            run_dir=run_dir,
            task_dir=task_dir,
            repair_dir=repair_dir,
            judge_model=(
                None if args.judge_model in (None, "", "-") else args.judge_model
            ),
            agent_runtime=str(args.agent_runtime),
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report.get("judge_completed") is True else 3
    candidates = _discover_candidates(run_dir)
    if not candidates:
        raise FileNotFoundError("Run 中没有可重评 Candidate")

    evaluations_dir = repair_dir / "evaluations"
    evaluations_dir.mkdir(parents=True, exist_ok=True)
    repaired_executables = _repair_evaluator_executables(task_dir / "evaluation")
    evaluations: dict[str, dict[str, Any]] = {}
    pending: list[Candidate] = []
    for candidate in candidates:
        path = evaluations_dir / f"{candidate.candidate_id}.json"
        existing = None if args.force_evaluate else _load_existing_evaluation(path, candidate)
        if existing is None:
            pending.append(candidate)
        else:
            evaluations[candidate.candidate_id] = existing
            if existing.get("imported_from_legacy_repair_output") is True:
                atomic_write_json(path, existing)

    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = {
            executor.submit(
                _evaluate_candidate,
                candidate,
                task_dir=task_dir,
                adapter_script=adapter_script,
                timeout_sec=max(1.0, float(args.evaluation_timeout_sec)),
            ): candidate
            for candidate in pending
        }
        for future in as_completed(futures):
            candidate = futures[future]
            wrapper = future.result()
            evaluations[candidate.candidate_id] = wrapper
            atomic_write_json(evaluations_dir / f"{candidate.candidate_id}.json", wrapper)

    attempt_map = _official_attempt_map(run_dir, candidates)
    submissions_path, submission_map_path = _write_native_history(
        repair_dir,
        evaluations,
        attempt_map,
    )
    valid_scores = {
        candidate_id: _finite_score(wrapper["result"])
        for candidate_id, wrapper in evaluations.items()
        if wrapper["result"].get("valid") is True
    }
    manifest = {
        "repair_id": args.repair_id,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "adapter_script": str(adapter_script),
        "adapter_sha256": sha256_file(adapter_script),
        "candidate_count": len(candidates),
        "evaluated_candidate_count": len(evaluations),
        "valid_scores": valid_scores,
        "repaired_evaluator_executables": repaired_executables,
        "created_at": now_ms(),
    }
    atomic_write_json(repair_dir / "manifest.json", manifest)

    if args.apply:
        report = _apply_repair(
            run_dir=run_dir,
            task_dir=task_dir,
            task_id=task_id,
            repair_dir=repair_dir,
            candidates=candidates,
            evaluations=evaluations,
            submissions_path=submissions_path,
            submission_map_path=submission_map_path,
            run_judge=bool(args.judge),
            judge_model=(None if args.judge_model in (None, "", "-") else args.judge_model),
            agent_runtime=str(args.agent_runtime),
        )
    else:
        report = {
            **manifest,
            "applied": False,
            "best_preview": max(
                (
                    {"candidate_id": candidate_id, "score": score}
                    for candidate_id, score in valid_scores.items()
                    if score is not None
                ),
                key=lambda item: float(item["score"]),
                default=None,
            ),
        }
        atomic_write_json(repair_dir / "report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    if args.judge and not (
        isinstance(report.get("judge"), Mapping)
        and type(report["judge"].get("is_valid")) is bool
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
