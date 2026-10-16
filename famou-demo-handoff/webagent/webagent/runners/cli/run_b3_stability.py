"""
runners/cli/run_b3_stability.py — B3 Extractor 稳定性测试

复用已有 agent workspace，多次独立运行 extractor → evaluator，统计评分分布。

用法：
    python -m runners.cli.run_b3_stability \
        --case  city_delivery_routing \
        --run   cc_famou_20260401_001646 \
        --runs  5
"""

import argparse
import json
import sys
from pathlib import Path
from statistics import mean, stdev


def _one_run(run_dir: Path, case: Path, workspace: Path) -> dict:
    from ..eval import run_eval

    output_dir = run_dir / "normalized"
    result = run_eval(case, workspace, output_dir=output_dir)
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def _summarize(results: list[dict], n: int) -> dict:
    def stat(values: list[float]) -> dict:
        if not values:
            return {"mean": None, "std": None, "min": None, "max": None, "values": []}
        return {
            "mean":   round(mean(values), 6),
            "std":    round(stdev(values), 6) if len(values) > 1 else 0.0,
            "min":    round(min(values), 6),
            "max":    round(max(values), 6),
            "values": [round(v, 6) for v in values],
        }

    status_counts: dict[str, int] = {}
    for r in results:
        s = r.get("extraction_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total_runs":     n,
        "completed_runs": len(results),
        "scores": {
            "overall_score":  stat([r.get("overall_score",  0.0) for r in results]),
            "quality_score":  stat([r.get("quality_score",  0.0) for r in results]),
            "validity_score": stat([r.get("validity_score", 0.0) for r in results]),
        },
        "extraction_status_counts": status_counts,
        "per_run": [
            {
                "run": i,
                "overall_score":     r.get("overall_score"),
                "quality_score":     r.get("quality_score"),
                "validity_score":    r.get("validity_score"),
                "extraction_status": r.get("extraction_status"),
            }
            for i, r in enumerate(results)
        ],
    }


def main():
    from ..bench_config import resolve_case, RESULTS_DIR

    parser = argparse.ArgumentParser(description="Famou-Bench B3 Extractor 稳定性测试")
    parser.add_argument("--case", required=True,
                        help="case 名称（如 city_delivery_routing）")
    parser.add_argument("--run",  required=True,
                        help="实验目录名（如 cc_famou_20260401_001646），位于 results/ 下")
    parser.add_argument("--runs", type=int, default=5,
                        help="重复次数（默认 5）")
    args = parser.parse_args()

    try:
        case = resolve_case(args.case)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    case_dir = RESULTS_DIR / args.run / args.case
    if not case_dir.is_dir():
        print(f"[ERROR] 目录不存在: {case_dir}", file=sys.stderr)
        sys.exit(1)

    run_subdirs = sorted(case_dir.glob("run_[0-9][0-9]"))
    workspaces = run_subdirs if run_subdirs else [case_dir]

    def fmt(v):
        return f"{v:.4f}" if v is not None else "N/A"

    for workspace in workspaces:
        agent_run_path = workspace / ".eval" / "agent_run.json"
        if not agent_run_path.exists():
            print(f"[SKIP] agent_run.json 不存在，跳过: {workspace}", file=sys.stderr)
            continue

        stability_dir = workspace / ".eval" / "stability"
        stability_dir.mkdir(parents=True, exist_ok=True)

        agent_run = json.loads(agent_run_path.read_text(encoding="utf-8"))
        print(f"╔══════════════════════════════════════════════════════════╗")
        print(f"  Case:          {case.name}")
        print(f"  Workspace:     {workspace}")
        print(f"  Session ID:    {agent_run.get('session_id', 'unknown')}")
        print(f"  Stability runs:{args.runs}")
        print(f"╚══════════════════════════════════════════════════════════╝\n")

        results = []
        for i in range(args.runs):
            run_dir = stability_dir / f"run_{i:02d}"
            print(f"[{i+1}/{args.runs}] extractor + evaluator → {run_dir.name}/")
            result = _one_run(run_dir, case, workspace)
            print(f"       status={result.get('extraction_status')}  "
                  f"overall={result.get('overall_score', 0.0):.4f}")
            results.append(result)

        summary = _summarize(results, args.runs)
        summary_path = stability_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

        scores = summary["scores"]
        print(f"\n── Stability Summary ({workspace.name}) ──────────────────────────")
        os_ = scores["overall_score"]
        qs_ = scores["quality_score"]
        print(f"  overall_score:  mean={fmt(os_['mean'])}  std={fmt(os_['std'])}"
              f"  [{fmt(os_['min'])}, {fmt(os_['max'])}]")
        print(f"  quality_score:  mean={fmt(qs_['mean'])}  std={fmt(qs_['std'])}")
        print(f"  status_counts:  {summary['extraction_status_counts']}")
        print(f"  summary: {summary_path}\n")


if __name__ == "__main__":
    main()
