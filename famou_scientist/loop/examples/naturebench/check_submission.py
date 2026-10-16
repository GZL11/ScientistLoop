#!/usr/bin/env python3
"""在不读取隐藏标签的前提下检查 NatureBench 提交格式。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


_MATCHING_INSTANCES = {
    "s41592-022-01709-7": (
        "bone_marrow",
        "cross_species",
        "murine_spleen",
        "pbmc",
    )
}


def _check_matching_file(path: Path) -> tuple[bool, str | None, int]:
    """检查单个细胞匹配文件的字段和一对一约束。"""
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {"x_index", "y_index"}.issubset(reader.fieldnames):
                return False, "matching.csv 缺少 x_index/y_index 字段", 0
            x_seen: set[int] = set()
            y_seen: set[int] = set()
            rows = 0
            for row in reader:
                x_index = int(row["x_index"])
                y_index = int(row["y_index"])
                if x_index < 0 or y_index < 0:
                    return False, "匹配索引不能为负数", rows
                if x_index in x_seen or y_index in y_seen:
                    return False, "匹配索引必须满足一对一约束", rows
                x_seen.add(x_index)
                y_seen.add(y_index)
                rows += 1
    except Exception as exc:  # noqa: BLE001 - 转换为公开格式诊断
        return False, repr(exc), 0
    if rows == 0:
        return False, "matching.csv 不能为空", 0
    return True, None, rows


def _generic_check(submission_dir: Path) -> tuple[bool, str | None, int]:
    """对尚未注册专用格式的任务执行最小公开检查。"""
    if not submission_dir.is_dir():
        return False, "提交目录不存在", 0
    files = [path for path in submission_dir.rglob("*") if path.is_file()]
    if not files:
        return False, "提交目录为空", 0
    if any(path.is_symlink() for path in submission_dir.rglob("*")):
        return False, "提交目录不能包含符号链接", len(files)
    return True, None, len(files)


def main(argv: list[str] | None = None) -> int:
    """执行公开格式检查并输出统一 evaluator JSON。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--submission-dir", required=True)
    args = parser.parse_args(argv)
    task_dir = Path(args.task_dir).expanduser().resolve()
    submission_dir = Path(args.submission_dir).expanduser().resolve()

    expected_instances = _MATCHING_INSTANCES.get(task_dir.name)
    checked_items = 0
    error = None
    valid = True
    if expected_instances:
        for instance in expected_instances:
            path = submission_dir / instance / "matching.csv"
            if not path.is_file():
                valid, error = False, f"缺少提交文件: {instance}/matching.csv"
                break
            valid, error, rows = _check_matching_file(path)
            checked_items += rows
            if not valid:
                error = f"{instance}: {error}"
                break
    else:
        valid, error, checked_items = _generic_check(submission_dir)

    result = {
        "valid": valid,
        "metrics": {},
        "diagnostics_public": {
            "format_check": "passed" if valid else "failed",
            "checked_items": checked_items,
            "task_id": task_dir.name,
        },
        "extra_public": {"submission_dir_exists": submission_dir.is_dir()},
        "error": error,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
