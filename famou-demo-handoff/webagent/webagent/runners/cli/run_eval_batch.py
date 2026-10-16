"""
runners/cli/run_eval_batch.py — 对 batch 目录统一运行 eval（extractor + evaluator）

用法：
    python -m runners.cli.run_eval_batch --batch /path/to/cc_native_20260403_002448
    python -m runners.cli.run_eval_batch --batch /path/to/cc_native_20260403_002448 --force
    python -m runners.cli.run_eval_batch --batch /path/to/cc_native_20260403_002448 --case city_delivery_routing
"""

import argparse
import json
import sys
from pathlib import Path

from ..bench_config import CASES_DIR
from ..eval import run_eval


def _find_run_dirs(batch: Path, case_filter: str | None = None):
    """找到 batch 下所有 workspace 目录（兼容 run_XX/ 子目录和单次运行直接在 case_dir 下的情况）。"""
    for case_dir in sorted(batch.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("."):
            continue
        if case_filter and case_dir.name != case_filter:
            continue
        run_dirs = sorted(case_dir.glob("run_[0-9][0-9]"))
        if not run_dirs:
            run_dirs = [case_dir]
        for run_dir in run_dirs:
            yield case_dir.name, run_dir


def main():
    parser = argparse.ArgumentParser(description="对 batch 目录统一运行 eval")
    parser.add_argument("--batch", type=Path, required=True, help="batch 目录路径")
    parser.add_argument("--case", default=None, help="只 eval 指定 case")
    parser.add_argument("--force", action="store_true", help="强制重跑（覆盖已有 result.json）")
    args = parser.parse_args()

    batch = args.batch.resolve()
    if not batch.exists():
        print(f"[ERROR] batch 目录不存在: {batch}", file=sys.stderr)
        sys.exit(1)

    total = 0
    skipped = 0
    evaluated = 0
    errors = 0

    for case_name, run_dir in _find_run_dirs(batch, args.case):
        total += 1
        agent_run_path = run_dir / ".eval" / "agent_run.json"
        result_path = run_dir / ".eval" / "result.json"

        if not agent_run_path.exists():
            print(f"[SKIP] {case_name}/{run_dir.name} — 无 agent_run.json")
            skipped += 1
            continue

        agent_run = json.loads(agent_run_path.read_text())
        if agent_run.get("status") != "done":
            print(f"[SKIP] {case_name}/{run_dir.name} — status={agent_run.get('status', '?')}")
            skipped += 1
            continue

        if result_path.exists() and not args.force:
            result = json.loads(result_path.read_text())
            score = result.get("overall_score", "?")
            print(f"[SKIP] {case_name}/{run_dir.name} — 已有 result (score={score})")
            skipped += 1
            continue

        case_dir = CASES_DIR / case_name
        if not case_dir.exists():
            print(f"[ERROR] {case_name}/{run_dir.name} — case 目录不存在: {case_dir}")
            errors += 1
            continue

        print(f"\n{'='*60}")
        print(f"  {case_name} / {run_dir.name}")
        print(f"{'='*60}")

        try:
            result = run_eval(case_dir, run_dir)
            result_path = run_dir / ".eval" / "result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            score = result.get("overall_score", 0.0)
            print(f"  overall_score: {score:.4f}")
            evaluated += 1
        except Exception as e:
            print(f"[ERROR] {case_name}/{run_dir.name} — eval 失败: {e}", file=sys.stderr)
            errors += 1

    print(f"\n{'='*60}")
    print(f"  总计: {total}  |  已评: {evaluated}  |  跳过: {skipped}  |  失败: {errors}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
