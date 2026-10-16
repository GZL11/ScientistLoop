"""核对 A/B 批次的「run 目录 ↔ 集群作业」，找出半成品和缺臂的配对。

## 为什么需要

`submit_one_click.sh` 是分步做的：建 run 目录 → stage 源码/题面 → seed 经验库 →
写凭据 → **最后才提交 fm-job**。中间被打断就留下「目录已建、作业没提」的半成品，
而 `submit.sh` 开头有 `if [[ -e run_dir ]] then 跳过`，所以这个 task-arm 之后
**永远不会被重发**——配对静默地只剩一条臂，分析时才发现。

2026-09-10 起 `submit_one_click.sh` 会把提交回执写进
``<run>/controller/fmjob.json``（作业名 + 退出码 + 该 Run 的实验配置），
本脚本优先读它。回执之前的批次（如 r1）没有这个文件，退回到用 `fm-job list`
按 task_id 交叉核对——**注意 fm-job 作业名是 `famou-nb-<task>-<时间戳>`，
不含臂标识**，所以同题两臂只能按数量核对，无法一一对应。这正是要落回执的原因。

    python -m famou_scientist.loop.examples.naturebench.fmjob.audit_batch \
        --runs-root .famou/naturebench-runs --pattern 'xt2w*-r1-*'
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

JOB_LINE = re.compile(
    r"\s*(famou-nb-(?P<task>s\d[A-Za-z0-9.\-]*?)-(?P<ts>2026\d{4}-\d{6}))\s+(?P<state>\S+)"
)


def _cluster_jobs(fm_job_bin: str) -> dict[str, collections.Counter]:
    """按 task_id 汇总集群上的作业状态。"""

    try:
        out = subprocess.run(
            [fm_job_bin, "list"], capture_output=True, text=True, timeout=300
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"WARN: 无法读取 fm-job list：{exc}", file=sys.stderr)
        return {}
    jobs: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for line in out.splitlines():
        m = JOB_LINE.match(line)
        if m:
            jobs[m.group("task")][m.group("state")] += 1
    return jobs


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def audit(runs_root: Path, pattern: str, fm_job_bin: str) -> dict[str, Any]:
    jobs = _cluster_jobs(fm_job_bin)
    by_task: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    for run_dir in sorted(runs_root.glob(pattern)):
        name = run_dir.name
        # 约定：<prefix>-r<N>-<task>-<stamp>，prefix 以 wo 结尾的是对照臂
        prefix = name.split("-r", 1)[0]
        arm = "without" if prefix.endswith("wo") else "with"
        rest = name.split("-r", 1)[1]
        task = rest.split("-", 1)[1].rsplit("-2026", 1)[0]
        receipt = _read_json(run_dir / "controller" / "fmjob.json")
        summary = _read_json(run_dir / "controller" / "run_summary.json")
        by_task[task][arm] = {
            "run_dir": str(run_dir),
            "receipt": receipt,
            "job_name": (receipt or {}).get("job_name"),
            "fmjob_exit_code": (receipt or {}).get("fmjob_exit_code"),
            "finished": summary is not None,
            "effective_score": (summary or {}).get("effective_score"),
        }

    problems: list[dict[str, Any]] = []
    for task, arms in sorted(by_task.items()):
        states = jobs.get(task, collections.Counter())
        if len(arms) != 2:
            problems.append(
                {"task": task, "kind": "missing_arm", "have": sorted(arms)}
            )
        for arm, info in arms.items():
            if info["receipt"] is not None:
                if info["fmjob_exit_code"] not in (0, "0"):
                    problems.append(
                        {
                            "task": task,
                            "arm": arm,
                            "kind": "submit_failed",
                            "exit": info["fmjob_exit_code"],
                            "run_dir": info["run_dir"],
                        }
                    )
                elif not info["job_name"]:
                    problems.append(
                        {"task": task, "arm": arm, "kind": "job_name_unparsed"}
                    )
        if not jobs:
            continue
        total = sum(states.values())
        if total < len(arms):
            # 没有回执时唯一能查的信号：集群上的作业数少于目录数
            problems.append(
                {
                    "task": task,
                    "kind": "fewer_jobs_than_dirs",
                    "dirs": len(arms),
                    "jobs": total,
                    "states": dict(states),
                }
            )
    return {"by_task": by_task, "problems": problems, "cluster": {k: dict(v) for k, v in jobs.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--pattern", required=True, help="如 'xt2w*-r1-*'")
    parser.add_argument(
        "--fm-job-bin",
        default="/path/to/workspace/yingjiahua/FM-JOB/fm-job",
    )
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args(argv)

    result = audit(args.runs_root.expanduser().resolve(), args.pattern, args.fm_job_bin)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not result["problems"] else 1

    by_task = result["by_task"]
    print("%-24s %-8s %-40s %-10s %s" % ("任务", "臂", "作业名", "已完成", "分数"))
    for task, arms in sorted(by_task.items()):
        for arm in ("with", "without"):
            info = arms.get(arm)
            if info is None:
                print("%-24s %-8s %-40s %-10s %s" % (task, arm, "—（无目录）", "-", "-"))
                continue
            score = info["effective_score"]
            print(
                "%-24s %-8s %-40s %-10s %s"
                % (
                    task,
                    arm,
                    info["job_name"] or "（无回执）",
                    "是" if info["finished"] else "否",
                    ("%.4f" % score) if isinstance(score, (int, float)) else "-",
                )
            )
    print()
    pairs = sum(1 for arms in by_task.values() if len(arms) == 2)
    both_done = sum(
        1
        for arms in by_task.values()
        if len(arms) == 2 and all(a["finished"] for a in arms.values())
    )
    print(f"题数 {len(by_task)}｜双臂齐全 {pairs}｜双臂都跑完 {both_done}")
    if result["problems"]:
        print(f"\n需关注 {len(result['problems'])} 项：")
        for item in result["problems"]:
            print("  " + json.dumps(item, ensure_ascii=False))
        return 1
    print("未发现半成品或缺臂")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
