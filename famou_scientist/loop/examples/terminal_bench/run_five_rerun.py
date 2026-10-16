"""Submit the five Terminal-Bench-Science verifier-loop reruns."""
from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from famou_scientist.loop.harness.runtime import BenchmarkHarness, HarnessConfig


TASKS = {
    "cilia-segmentation": "tasks/life-sciences/biology/cilia-segmentation",
    "eeg-erp-recovery": "tasks/life-sciences/neuroscience/eeg-erp-recovery",
    "ode-law-discovery": "tasks/mathematical-sciences/applied-mathematics/ode-law-discovery",
    "small-area-equivalence": "tasks/mathematical-sciences/statistics/small-area-equivalence",
    "variable-star-vetting": "tasks/physical-sciences/astronomy/variable-star-vetting",
}

RESOURCES = {
    "cilia-segmentation": ("4", "8Gi"),
    "eeg-erp-recovery": ("2", "4Gi"),
    "ode-law-discovery": ("4", "8Gi"),
    "small-area-equivalence": ("2", "8Gi"),
    "variable-star-vetting": ("2", "2Gi"),
}


def run_one(name: str, args: argparse.Namespace) -> dict:
    task_dir = args.source / TASKS[name]
    run_dir = args.root / f"tbs-{name}-rerun-20260828"
    if run_dir.exists() and not args.resume:
        shutil.rmtree(run_dir)
    view = run_dir / "task"
    view.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(task_dir / "instruction.md", view / "instruction.md")
    channel = run_dir / "evaluator-channel"
    (channel / "requests").mkdir(parents=True, exist_ok=True)
    (channel / "responses").mkdir(parents=True, exist_ok=True)
    trial = run_dir
    cpu, memory = RESOURCES[name]
    config = HarnessConfig(
        task_id=name,
        run_dir=run_dir / "famou",
        problem_dir=task_dir,
        workspace_dir=run_dir / "submission",
        agent_runtime="claude",
        agent_graph="terminal_task",
        benchmark_adapter="terminal_bench_science",
        evaluator_adapter="terminal_bench_science",
        agent_binary="claude",
        model="deepseek-v4-pro",
        solver_model="deepseek-v4-pro",
        verifier_model="deepseek-v4-pro",
        agent_python_binary="python3",
        solver_image=args.image,
        verifier_image=args.verifier_image.format(task=name),
        gt_verifier_image=args.verifier_image.format(task=name),
        harbor_trial_dir=trial,
        harbor_artifact_root=trial / "artifacts",
        harbor_famou_dir=run_dir / "famou",
        harbor_agent_task_view=view,
        harbor_backend="famou_scientist.loop.integrations.terminal_bench.fmjob_backend:FmJobHarborTaskBackend",
        fm_job_bin=args.fm_job_bin,
        fmjob_cpu=cpu,
        fmjob_memory=memory,
        max_refine_rounds=0,
    )
    # TerminalTaskGraph uses Harbor facilities directly; this placeholder only
    # satisfies the generic Harness constructor contract.
    return BenchmarkHarness(config, evaluator=object()).run()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--verifier-image",
        default=(
            "<你的镜像仓库>/famou-public/"
            "tb-science-{task}-verifier:official-v1"
        ),
    )
    parser.add_argument("--fm-job-bin", default="fm-job")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--tasks", nargs="*", choices=sorted(TASKS), default=sorted(TASKS))
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=True)
    # Keep the aggregate request schedulable. Each pair still runs Solver and
    # Verifier in parallel inside its trial.
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = {pool.submit(run_one, name, args): name for name in args.tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                print(name, future.result(), flush=True)
            except Exception as exc:
                print(name, {"status": "failed", "error": repr(exc)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
