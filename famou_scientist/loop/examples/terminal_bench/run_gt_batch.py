"""Run a Terminal-Bench-Science batch with the official GT verifier path."""
from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from famou_scientist.loop.harness.runtime import BenchmarkHarness, HarnessConfig


TASKS = {
    "energy-routing": "tasks/mathematical-sciences/operations-research/energy-routing",
    "frustrated-heisenberg-nqs": "tasks/physical-sciences/physics/frustrated-heisenberg-nqs",
    "spin-glass-groundstate": "tasks/physical-sciences/physics/spin-glass-groundstate",
    "variable-star-vetting": "tasks/physical-sciences/astronomy/variable-star-vetting",
    "traffic-flux-inversion": "tasks/mathematical-sciences/applied-mathematics/traffic-flux-inversion",
}


def run_one(name: str, args: argparse.Namespace) -> dict:
    task_dir = args.source / TASKS[name]
    run_dir = args.root / f"tbs-{name}-gt-v1"
    if run_dir.exists() and not args.resume:
        shutil.rmtree(run_dir)
    task_view = run_dir / "task-view"
    task_view.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(task_dir / "instruction.md", task_view / "instruction.md")
    (run_dir / "evaluator-channel" / "requests").mkdir(parents=True, exist_ok=True)
    (run_dir / "evaluator-channel" / "responses").mkdir(parents=True, exist_ok=True)
    # The official verifier is a separate image built from this task's
    # tests/Dockerfile. The backend never stages tests into the Agent image.
    verifier_image = args.verifier_image.format(task=name)
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
        model=args.model,
        solver_model=args.model,
        solver_image=args.image,
        verifier_image=verifier_image,
        gt_verifier_image=verifier_image,
        candidate_verifier_mode=args.candidate_verifier_mode,
        official_gt_budget=args.official_gt_budget,
        agent_python_binary="python3",
        harbor_trial_dir=run_dir,
        harbor_artifact_root=run_dir / "artifacts",
        harbor_famou_dir=run_dir / "famou",
        harbor_agent_task_view=task_view,
        harbor_backend=(
            "famou_scientist.loop.integrations.terminal_bench.fmjob_backend:"
            "FmJobHarborTaskBackend"
        ),
        fm_job_bin=args.fm_job_bin,
        fmjob_cpu=args.cpu,
        fmjob_memory=args.memory,
        max_refine_rounds=args.max_refine_rounds,
    )
    return BenchmarkHarness(config, evaluator=object()).run()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--verifier-image",
        default="<你的镜像仓库>/famou-public/tb-science-{task}-verifier:official-v1",
    )
    parser.add_argument(
        "--candidate-verifier-mode",
        choices=("gt_primary", "gt_final_only", "gt_budget"),
        default="gt_primary",
        help="gt_final_only 只在最终审计调用一次官方 GT，不提供候选级 GT 反馈",
    )
    parser.add_argument(
        "--official-gt-budget",
        type=int,
        default=1,
        help="gt_budget: Solver 运行期间可主动申请的官方 GT 次数；FinalAudit 另计",
    )
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--fm-job-bin", default="fm-job")
    parser.add_argument("--cpu", default="4")
    parser.add_argument("--memory", default="8Gi")
    parser.add_argument(
        "--max-refine-rounds",
        type=int,
        default=0,
        help="兼容参数（已废弃）；refine 不设轮数上限，仅受 Solver 时间预算限制",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="并行 task 数；默认等于本次选择的 task 数",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--tasks", nargs="*", choices=sorted(TASKS), default=sorted(TASKS))
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=True)
    # Different tasks are independent and should be submitted concurrently.
    # Solver and GT verifier are also parallel inside each trial.
    workers = max(1, min(len(args.tasks), int(args.workers or len(args.tasks))))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, name, args): name for name in args.tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                print(name, future.result(), flush=True)
            except Exception as exc:  # pragma: no cover - CLI reporting path
                print(name, {"status": "failed", "error": repr(exc)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
