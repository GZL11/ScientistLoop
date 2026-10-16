"""Summarize completed limited-GT trials without selecting the best repetition."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


PROTOCOL = "scimodelingbench-limited-gt-v1"
EXPERIMENT_FIELDS = ("model", "runtime", "cpu", "gpu", "memory_gib", "public_input_sha256")
FIELDS = ("run_dir", "task_id", "k", "gt_used", "final_score", "outcome",
          "wall_time_sec", *EXPERIMENT_FIELDS)
GROUP_FIELDS = ("task_id", "k", "wall_time_sec", *EXPERIMENT_FIELDS)


def read_rows(paths: list[Path]) -> list[dict]:
    rows = []
    seen = set()
    for path in paths:
        summary = path / "controller/run_summary.json" if path.is_dir() else path
        summary = summary.resolve()
        if summary in seen:
            continue
        seen.add(summary)
        if not summary.is_file():
            print(f"Missing summary (not counted): {summary}", file=sys.stderr)
            continue
        record = json.loads(summary.read_text())
        if record.get("protocol") != PROTOCOL:
            print(f"Skipping other protocol: {summary}", file=sys.stderr)
            continue
        score = record.get("final_score")
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score):
            score = None
        experiment = record.get("experiment") or {}
        rows.append({
            "run_dir": str(summary.parent.parent), "task_id": record["task_id"],
            "k": record["official_gt_budget"], "gt_used": record["official_gt_used"],
            "final_score": score, "outcome": record["outcome"],
            "wall_time_sec": record.get("timing", {}).get("wall_time_sec"),
            **{key: experiment.get(key) for key in EXPERIMENT_FIELDS},
        })
    return sorted(rows, key=lambda row: (row["task_id"], row["k"], row["run_dir"]))


def grouped_rows(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in GROUP_FIELDS)].append(row)
    results = []
    for key, group in groups.items():
        scores = [row["final_score"] for row in group if row["final_score"] is not None]
        results.append({
            **dict(zip(GROUP_FIELDS, key)),
            "n_total": len(group), "n_scored": len(scores),
            "mean_final_score": statistics.mean(scores) if scores else None,
            "std_final_score": statistics.stdev(scores) if len(scores) > 1 else None,
            "mean_gt_used": statistics.mean(row["gt_used"] for row in group),
        })
    return results


def write_csv(path: Path, rows: list[dict], fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="Run directories or run_summary.json files")
    parser.add_argument("--output", required=True, type=Path, help="Per-run CSV; also writes <stem>_grouped.csv")
    args = parser.parse_args()
    rows = read_rows(args.runs)
    if not rows:
        parser.error("no completed limited-GT summaries found")
    write_csv(args.output, rows, FIELDS)
    grouped = args.output.with_name(args.output.stem + "_grouped.csv")
    write_csv(grouped, grouped_rows(rows), (*GROUP_FIELDS, "n_total", "n_scored",
                                         "mean_final_score", "std_final_score", "mean_gt_used"))
    print(f"{len(rows)} runs: {args.output}\nGrouped results: {grouped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
