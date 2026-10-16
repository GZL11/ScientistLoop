#!/usr/bin/env python3
"""调用 NatureBench 自带 evaluator 和 AutoSOTA 评分逻辑。"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from types import ModuleType


def _find_naturebench_root(task_dir: Path) -> Path:
    """从任务目录向上查找 NatureBench 代码库根目录。"""
    for parent in (task_dir, *task_dir.parents):
        if (parent / "eval_service.py").is_file() and (parent / "_evaluator_runner.py").is_file():
            return parent
    raise FileNotFoundError(f"无法从任务目录找到 NatureBench 根目录: {task_dir}")


def _load_eval_service(root: Path) -> ModuleType:
    """动态加载当前 NatureBench 版本的官方评分实现。"""
    path = root / "eval_service.py"
    spec = importlib.util.spec_from_file_location("famou_naturebench_eval_service", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 NatureBench eval_service: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _find_metric_value(value: object, metric_name: str) -> tuple[dict[str, object], str] | None:
    """在官方 evaluator 的 instance 结果中定位一个指标字段。"""

    if not isinstance(value, dict):
        return None
    normalized_name = _normalize_metric_name(metric_name)
    for key, item in value.items():
        if _normalize_metric_name(str(key)) == normalized_name:
            return value, str(key)
        found = _find_metric_value(item, metric_name)
        if found is not None:
            return found
    return None


def _normalize_metric_name(name: str) -> str:
    """按 NatureBench 官方规则规范化指标名。"""

    return name.lower().replace("_", "").replace(" ", "").replace("-", "")


def _find_nonempty_errors(value: object, *, path: str) -> list[dict[str, str]]:
    """递归收集 evaluator instance 结果中的非空错误字段。"""

    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() == "error" and item not in (None, "", [], {}):
                found.append({"path": item_path, "error": str(item)})
            else:
                found.extend(_find_nonempty_errors(item, path=item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_nonempty_errors(item, path=f"{path}[{index}]"))
    return found


def _validate_primary_scores(
    raw_scores: object,
    primary_table: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """确认每个官方主实例都成功返回有限主指标。

    NatureBench 的 AutoSOTA 聚合会用 ``-1`` 代替缺失实例。这个规则适合
    Leaderboard 计分，但不能把格式错误或 evaluator 异常伪装成一次成功实验，
    否则 Controller 可能把不完整 Candidate 选成最佳并向 ExpBank 写入错误结论。
    """

    failures: list[dict[str, object]] = []
    if not isinstance(raw_scores, dict):
        return [
            {
                "kind": "invalid_evaluator_response",
                "message": "evaluator 响应不是 instance 映射",
            }
        ]
    for instance, info in primary_table.items():
        instance_block = raw_scores.get(instance)
        if not isinstance(instance_block, dict):
            failures.append(
                {
                    "kind": "missing_instance",
                    "instance": instance,
                    "message": "evaluator 未返回该官方主实例",
                }
            )
            continue
        errors = _find_nonempty_errors(instance_block, path=instance)
        if errors:
            failures.append(
                {
                    "kind": "instance_error",
                    "instance": instance,
                    "errors": errors,
                    "message": "evaluator 报告实例执行或产物校验错误",
                }
            )
            continue
        metric_name = str(info.get("metric") or "")
        located = _find_metric_value(instance_block, metric_name)
        score = located[0][located[1]] if located is not None else None
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(float(score))
        ):
            failures.append(
                {
                    "kind": "missing_primary_metric",
                    "instance": instance,
                    "metric": metric_name,
                    "value": score,
                    "message": "evaluator 未返回有限的官方主指标",
                }
            )
    return failures


def _validate_public_submission_contract(
    task_dir: Path,
    submission_dir: Path,
) -> list[dict[str, object]]:
    """Validate public prediction IDs before treating a score as complete.

    This check intentionally uses only the public test directory. It catches
    stale snapshots, train/validation leakage, and accidental ID expansion
    without reading hidden ground truth.
    """

    if task_dir.name != "s42256-023-00628-2":
        return []
    # The evaluator receives the Run root, while the public NatureBench task
    # is staged below ``Run/problem``.  Keep compatibility with direct task
    # invocation, where ``task_dir`` itself is the problem directory.
    problem_dir = task_dir / "problem"
    if not problem_dir.is_dir():
        problem_dir = task_dir
    test_dir = problem_dir / "data" / "band_gap" / "test"
    expected = {
        path.stem
        for path in test_dir.glob("*.graphdata")
        if path.is_file()
    }
    failures: list[dict[str, object]] = []
    if len(expected) != 2037:
        failures.append(
            {
                "kind": "public_input_contract",
                "instance": "band_gap",
                "message": (
                    "public band_gap test input count is "
                    f"{len(expected)}, expected 2037"
                ),
            }
        )
        return failures
    prediction_path = submission_dir / "band_gap" / "predictions.json"
    if not prediction_path.is_file():
        return [
            {
                "kind": "missing_submission_file",
                "instance": "band_gap",
                "path": "band_gap/predictions.json",
                "message": "public submission contract file is missing",
            }
        ]
    try:
        predictions = json.loads(prediction_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            {
                "kind": "invalid_submission_json",
                "instance": "band_gap",
                "message": repr(exc),
            }
        ]
    if not isinstance(predictions, dict):
        return [
            {
                "kind": "invalid_submission_schema",
                "instance": "band_gap",
                "message": "band_gap/predictions.json must contain a JSON object",
            }
        ]
    actual = {str(key) for key in predictions}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if not missing and not extra:
        return []
    return [
        {
            "kind": "public_output_id_mismatch",
            "instance": "band_gap",
            "expected_count": len(expected),
            "actual_count": len(actual),
            "missing_count": len(missing),
            "extra_count": len(extra),
            "missing_sample": missing[:10],
            "extra_sample": extra[:10],
            "message": (
                "band_gap prediction IDs must exactly match public test IDs"
            ),
        }
    ]


def _enable_evaluator_subprocess_compatibility() -> None:
    """让官方 evaluator 子进程加载 Famou 的只读兼容补丁。"""

    compatibility_dir = Path(__file__).resolve().parent
    current = os.environ.get("PYTHONPATH")
    entries = current.split(os.pathsep) if current else []
    if str(compatibility_dir) not in entries:
        os.environ["PYTHONPATH"] = os.pathsep.join(
            [str(compatibility_dir), *entries]
        )


def _load_primary_units(metadata_path: Path) -> dict[tuple[str, str], str | None]:
    """读取公开 metadata 中主指标的单位，不读取 ground truth。"""

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    units: dict[tuple[str, str], str | None] = {}
    for entry in metadata.get("performance_entries", []):
        if not isinstance(entry, dict):
            continue
        instance = str(entry.get("dataset_name") or "")
        for metric in entry.get("metrics", []):
            if not isinstance(metric, dict) or not metric.get("is_primary"):
                continue
            units[(instance, str(metric.get("name") or ""))] = metric.get("unit")
    return units


def _normalize_metric_units(
    raw_scores: dict[str, object],
    primary_table: dict[str, dict[str, object]],
    metadata_path: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """把官方小数形式的百分比指标转换为声明单位，并保留转换记录。"""

    normalized = copy.deepcopy(raw_scores)
    units = _load_primary_units(metadata_path)
    records: list[dict[str, object]] = []
    for instance, info in primary_table.items():
        metric_name = str(info.get("metric") or "")
        unit = units.get((instance, metric_name))
        sota = info.get("sota")
        if unit != "%" or not isinstance(sota, (int, float)) or abs(float(sota)) <= 1:
            continue
        located = _find_metric_value(normalized.get(instance), metric_name)
        if located is None:
            continue
        block, key = located
        score = block[key]
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(float(score))
            or abs(float(score)) > 1
        ):
            continue
        converted = float(score) * 100.0
        block[key] = converted
        records.append(
            {
                "instance": instance,
                "metric": metric_name,
                "from_unit": "fraction",
                "to_unit": "%",
                "original_value": float(score),
                "normalized_value": converted,
            }
        )
    return normalized, records


def main(argv: list[str] | None = None) -> int:
    """执行正式评测并输出 Famou BenchmarkAdapter 结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--submission-dir", required=True)
    args = parser.parse_args(argv)
    task_dir = Path(args.task_dir).expanduser().resolve()
    submission_dir = Path(args.submission_dir).expanduser().resolve()
    raw_scores: dict[str, object] = {}
    normalized_scores: dict[str, object] = {}
    per_instance: dict[str, float] = {}
    score_normalization: list[dict[str, object]] = []
    completeness_failures: list[dict[str, object]] = []
    aggregate: float | None = None
    issues: list[object] = []

    try:
        _enable_evaluator_subprocess_compatibility()
        root = _find_naturebench_root(task_dir)
        service = _load_eval_service(root)
        raw_scores = service.run_evaluator(task_dir, submission_dir)
        primary_table, issues = service._get_per_instance_primaries(
            task_dir / "metadata.json",
            task_dir.name,
        )
        normalized_scores, score_normalization = _normalize_metric_units(
            raw_scores,
            primary_table,
            task_dir / "metadata.json",
        )
        per_instance, aggregate = service._compute_improvements(
            normalized_scores,
            primary_table,
        )
        completeness_failures = _validate_primary_scores(
            normalized_scores,
            primary_table,
        )
        completeness_failures.extend(
            _validate_public_submission_contract(task_dir, submission_dir)
        )
        evaluation_completed = True
        score_available = aggregate is not None
        # valid 是 Famou EvaluationResult 的协议字段，只表示本次数值结果可用；
        # NatureBench Validity Judge 的结论在最终收尾阶段单独写入 is_valid。
        valid = score_available and not completeness_failures
        if completeness_failures:
            failed_instances = ", ".join(
                str(item.get("instance") or item.get("kind"))
                for item in completeness_failures
            )
            error = f"NatureBench 主实例评测不完整: {failed_instances}"
        else:
            error = None if score_available else "NatureBench 未返回可聚合的主指标"
    except Exception as exc:  # noqa: BLE001 - 正式评测错误必须形成证据
        raw_scores = {}
        per_instance = {}
        aggregate = None
        issues = []
        evaluation_completed = False
        score_available = False
        valid = False
        error = repr(exc)

    result = {
        "valid": valid,
        "official_metrics": {"aggregate_improvement": aggregate},
        "diagnostics_public": {
            "task_id": task_dir.name,
            "evaluated_instances": len(per_instance),
            "scoring": "naturebench_autosota",
            "evaluation_completed": evaluation_completed,
            "score_available": score_available,
            "all_primary_instances_valid": not completeness_failures,
            "primary_instance_failures": completeness_failures,
            "validity_judge": "not_run_in_numeric_evaluator",
        },
        "extra": {
            "raw_scores": raw_scores,
            "normalized_raw_scores": normalized_scores,
            "per_instance_improvement": per_instance,
            "score_normalization": score_normalization,
            "metadata_issues": issues,
            "primary_instance_failures": completeness_failures,
        },
        "extra_public": {
            # 与 NatureBench 官方 /evaluate 响应使用相同字段名。attempt、best
            # 分数和 best_attempt 由长生命周期 trusted worker 统一补充。
            "task_name": task_dir.name,
            "raw_scores": raw_scores,
            "normalized_raw_scores": normalized_scores,
            "per_instance_improvement": per_instance,
            "aggregate_improvement": aggregate,
            "score_normalization": score_normalization,
            "primary_instance_failures": completeness_failures,
        },
        "error_public": error,
        "error": error,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
