"""Run seven fully-failed Terminal-Bench-Science tasks with GT refine loop."""
from __future__ import annotations

import argparse
import os
import shutil
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from famou_scientist.loop.harness.runtime import BenchmarkHarness, HarnessConfig


TASKS = {
    "baseline-free-localization": "tasks/engineering-sciences/mechanical-engineering/baseline-free-localization",
    "guided-wave-localization": "tasks/engineering-sciences/mechanical-engineering/guided-wave-localization",
    "ankle-mri-findings": "tasks/life-sciences/medicine/ankle-mri-findings",
    "finite-free-stam": "tasks/mathematical-sciences/formal-mathematics/finite-free-stam",
    "ode-law-discovery": "tasks/mathematical-sciences/applied-mathematics/ode-law-discovery",
    "small-area-equivalence": "tasks/mathematical-sciences/statistics/small-area-equivalence",
    "tamp-skill-planning": "tasks/engineering-sciences/mechanical-engineering/tamp-skill-planning",
    # 2026-09-11 第二批：GT 评测耗时较长且有实际应用意义的任务。
    "linked-cell-suppression": "tasks/mathematical-sciences/operations-research/linked-cell-suppression",
    "hbv-calibration-1": "tasks/earth-sciences/geosciences/hbv-calibration-1",
    "reactor-safety-control": "tasks/engineering-sciences/chemical-engineering/reactor-safety-control",
    "rdkit-ic-constraints": "tasks/physical-sciences/chemistry/rdkit-ic-constraints",
    "traffic-flux-inversion": "tasks/mathematical-sciences/applied-mathematics/traffic-flux-inversion",
    "qsm-reconstruction": "tasks/life-sciences/neuroscience/qsm-reconstruction",
}


def _resources(task_dir: Path) -> tuple[str, str]:
    raw = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    env = raw.get("environment", {})
    cpu = str(env.get("cpus") or 4)
    memory_mb = env.get("memory_mb")
    memory = f"{int(memory_mb)}Mi" if memory_mb else "8Gi"
    return cpu, memory


def run_one(name: str, args: argparse.Namespace) -> dict:
    task_dir = args.source / TASKS[name]
    batch_label = args.root.name or "batch"
    run_dir = args.root / f"tbs-{name}-{batch_label}"
    if run_dir.exists() and not args.resume:
        shutil.rmtree(run_dir)
    task_view = run_dir / "task-view"
    task_view.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(task_dir / "instruction.md", task_view / "instruction.md")
    cpu, memory = _resources(task_dir)
    agent_image = args.image.format(task=name)
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
        verifier_model=args.model,
        solver_image=agent_image,
        # The VerifierAgent needs a CLI-capable agent image. Official GT is
        # always kept separate and uses the task-owned tests/Dockerfile image.
        verifier_image=args.verifier_agent_image.format(task=name),
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
        fmjob_cpu=cpu,
        fmjob_memory=memory,
        max_refine_rounds=0,
    )
    return BenchmarkHarness(config, evaluator=object()).run()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--image",
        default=(
            "<你的镜像仓库>/famou-public/"
            "tb-science-{task}-agent:claude-code-solveruser-v1"
        ),
    )
    parser.add_argument(
        "--verifier-image",
        default=(
            "<你的镜像仓库>/famou-public/"
            "tb-science-{task}-verifier:official-v1"
        ),
    )
    parser.add_argument(
        "--verifier-agent-image",
        default=(
            "<你的镜像仓库>/famou-public/"
            "tb-science-{task}-agent:claude-code"
        ),
        help="CLI-capable image for VerifierAgent in proxy mode",
    )
    parser.add_argument(
        "--candidate-verifier-mode",
        choices=("proxy", "gt_primary", "gt_final_only", "gt_budget", "dual_shadow"),
        default="gt_primary",
    )
    parser.add_argument(
        "--official-gt-budget",
        type=int,
        default=1,
        help="gt_budget: Solver 运行期间可主动申请的官方 GT 次数；FinalAudit 另计",
    )
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument(
        "--verifier-prompt-version",
        choices=("v0", "v1", "v2"),
        default="v2",
        help="VerifierAgent prompt contract; v2 is the current quality-aligned default.",
    )
    parser.add_argument("--fm-job-bin", default="fm-job")
    parser.add_argument("--workers", type=int, default=7)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--tasks", nargs="*", choices=sorted(TASKS), default=sorted(TASKS))
    args = parser.parse_args()
    # The prompt builder is shared by all worker threads and reads this
    # process-level selector.  Make the version explicit for reproducible
    # batches instead of silently falling back to the legacy v1 contract.
    os.environ["FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION"] = args.verifier_prompt_version
    args.source = args.source.resolve()
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(len(args.tasks), int(args.workers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, name, args): name for name in args.tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                print(name, future.result(), flush=True)
            except Exception as exc:  # pragma: no cover
                print(name, {"status": "failed", "error": repr(exc)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
