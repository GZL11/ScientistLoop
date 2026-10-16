#!/usr/bin/env python3
"""
reconvert_trace.py — 对已完成实验的 trace 重新转换为统一 schema

用于 trace schema 变更后，对历史实验数据批量重新生成 .eval/trace/*.json。
只做转换（raw trace → unified schema），不重新收集原始 trace。

用法：
    # 单个 batch
    python reconvert_trace.py --batch /path/to/cc_famou_20260401_001646

    # 只处理指定 case
    python reconvert_trace.py --batch /path/to/cc_famou_20260401_001646 --case city_delivery_routing

    # 指定 results 目录下所有 batch 全量重跑
    python reconvert_trace.py --all --results /path/to/results

    # 预览，不实际写入
    python reconvert_trace.py --batch /path/to/batch --dry-run
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# 确保 runners 包可以 import
_SCRIPT_DIR = Path(__file__).resolve().parent
_PACKAGE_ROOT = _SCRIPT_DIR.parent  # webagent/webagent/runners → webagent/webagent/
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

from runners.trace_converter import convert_cc_trace, convert_opencode_trace


def _detect_runner_type(workspace: Path) -> str | None:
    """从 agent_run.json 或 b2_run.json 推断 runner 类型。"""
    for name in ("agent_run.json", "b2_run.json"):
        run_file = workspace / ".eval" / name
        if run_file.exists():
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                return data.get("runner")
            except Exception:
                pass
    # 从 raw trace 目录推断
    if (workspace / ".eval" / "trace_cc").exists():
        return "cc_famou"
    if (workspace / ".eval" / "trace_opencode").exists():
        return "opencode_famou"
    return None


def _detect_session_id(workspace: Path) -> str | None:
    """从 agent_run.json 或 b2_run.json 读取 session_id。"""
    for name in ("agent_run.json", "b2_run.json"):
        run_file = workspace / ".eval" / name
        if run_file.exists():
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                return data.get("session_id")
            except Exception:
                pass
    return None


def _find_workspaces(batch: Path, case_filter: str | None = None):
    """找到 batch 下所有 workspace 目录。"""
    for case_dir in sorted(batch.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("."):
            continue
        if case_filter and case_dir.name != case_filter:
            continue
        run_dirs = sorted(case_dir.glob("run_[0-9][0-9]"))
        if not run_dirs:
            run_dirs = [case_dir]
        for run_dir in run_dirs:
            has_raw = (
                (run_dir / ".eval" / "trace_cc").exists()
                or (run_dir / ".eval" / "trace_opencode").exists()
            )
            if has_raw:
                yield case_dir.name, run_dir


def _reconvert_one(workspace: Path, dry_run: bool) -> str:
    """对单个 workspace 重新转换 trace。返回状态字符串。"""
    runner_type = _detect_runner_type(workspace)
    if not runner_type:
        return "skip:no-runner"

    eval_dir = workspace / ".eval"
    output_dir = eval_dir / "trace"

    if dry_run:
        return f"dry-run:would-reconvert ({runner_type})"

    # 清空旧的 unified trace
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if runner_type.startswith("cc"):
        session_id = _detect_session_id(workspace)
        if not session_id:
            return "skip:no-session-id"
        raw_dir = eval_dir / "trace_cc"
        if not raw_dir.exists():
            return "skip:no-raw-trace"
        convert_cc_trace(raw_dir, output_dir, session_id)

    elif runner_type.startswith("opencode"):
        raw_dir = eval_dir / "trace_opencode"
        if not raw_dir.exists():
            return "skip:no-raw-trace"
        convert_opencode_trace(raw_dir, output_dir)

    else:
        return f"skip:unknown-runner({runner_type})"

    n_files = len(list(output_dir.glob("*.json")))
    return f"ok ({n_files} sessions)"


def main():
    parser = argparse.ArgumentParser(description="对已完成实验重新转换 trace")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", type=Path, help="单个 batch 目录路径")
    group.add_argument("--all", action="store_true", help="results 目录下所有 batch")
    parser.add_argument("--results", type=Path, default=None,
                        help="results 根目录（--all 时必填，--batch 时忽略）")
    parser.add_argument("--case", default=None, help="只处理指定 case")
    parser.add_argument("--dry-run", action="store_true", help="预览，不实际写入")
    args = parser.parse_args()

    if args.all:
        if args.results is None:
            print("[ERROR] --all 需要配合 --results 指定目录", file=sys.stderr)
            sys.exit(1)
        results_dir = args.results.resolve()
        if not results_dir.exists():
            print(f"[ERROR] 目录不存在: {results_dir}", file=sys.stderr)
            sys.exit(1)
        batches = sorted(
            d for d in results_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    else:
        batch = args.batch.resolve()
        if not batch.exists():
            print(f"[ERROR] 目录不存在: {batch}", file=sys.stderr)
            sys.exit(1)
        batches = [batch]

    total = 0
    converted = 0
    skipped = 0
    errors = 0

    for batch in batches:
        workspaces = list(_find_workspaces(batch, args.case))
        if not workspaces:
            continue

        print(f"\n{'─'*60}")
        print(f"  {batch.name}  ({len(workspaces)} workspaces)")
        print(f"{'─'*60}")

        for case_name, workspace in workspaces:
            total += 1
            label = f"{case_name}/{workspace.name}" if workspace.name != case_name else case_name

            try:
                status = _reconvert_one(workspace, args.dry_run)
            except Exception as e:
                status = f"error:{e}"
                errors += 1
                print(f"  [ERROR] {label} — {e}", file=sys.stderr)
                continue

            if status.startswith("ok"):
                converted += 1
            elif status.startswith("skip"):
                skipped += 1
            elif status.startswith("dry-run"):
                converted += 1

            print(f"  {label:40s} {status}")

    print(f"\n{'='*60}")
    print(f"  总计: {total}  |  转换: {converted}  |  跳过: {skipped}  |  失败: {errors}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
