"""外部 benchmark 调用 Famou Agent Harness 的命令行入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .evaluator import FileEvaluatorClient, HttpEvaluatorClient
from .runtime import BenchmarkHarness, HarnessConfig


def _build_parser() -> argparse.ArgumentParser:
    """构建 `famou-scientist agent` 子命令解析器。"""
    parser = argparse.ArgumentParser(
        prog="famou-scientist agent",
        description="运行可由 NatureBench、Terminal-Bench 等外部 harness 直接托管的 Agent CLI。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="启动 benchmark-managed 自主优化循环")
    run.add_argument("--task-id", required=True, help="benchmark 的稳定任务标识")
    run.add_argument("--run-dir", required=True, help="本次运行的隔离根目录")
    run.add_argument("--problem-dir", help="公开题面目录，默认 <run-dir>/problem")
    run.add_argument("--workspace-dir", help="最终提交目录，默认 <run-dir>/workspace")
    evaluator = run.add_mutually_exclusive_group(required=True)
    evaluator.add_argument("--evaluator-channel", help="可信 evaluator 的签名文件通道")
    evaluator.add_argument("--evaluator-url", help="可信固定路径 evaluator 代理地址")
    run.add_argument("--evaluator-public-key", help="签名文件通道的 PEM 公钥")
    run.add_argument(
        "--allow-unsigned-evaluator",
        action="store_true",
        help="仅用于本地测试，生产运行不得开启",
    )
    run.add_argument("--evaluator-timeout-sec", type=float, default=3600)
    run.add_argument(
        "--agent-runtime",
        default="claude",
        help="传给 Agent Adapter 的 runtime 名称",
    )
    run.add_argument(
        "--agent-graph",
        choices=["sota_search", "terminal_task", "scimodeling_budget"],
        default="sota_search",
        help="选择 SOTA Search、Terminal Task 或 SciModelingBench 有限 GT 研究模式",
    )
    run.add_argument("--idea-runtime", help="Idea Agent runtime；默认使用 --agent-runtime")
    run.add_argument(
        "--implement-runtime",
        help="Implement Agent runtime；默认使用 --agent-runtime",
    )
    run.add_argument("--solver-runtime", help="Terminal Solver runtime")
    run.add_argument("--verifier-runtime", help="Terminal Verifier runtime")
    run.add_argument(
        "--agent-adapter",
        default="cli",
        help="Agent Adapter 名称、entry point 或 module:Class",
    )
    run.add_argument(
        "--benchmark-adapter",
        default="naturebench",
        help="Benchmark Adapter 名称、entry point 或 module:Class",
    )
    run.add_argument(
        "--evaluator-adapter",
        default="naturebench",
        help="Evaluator Adapter 名称、entry point 或 module:Class",
    )
    run.add_argument("--harbor-trial-dir", help="Harbor canonical trial root")
    run.add_argument("--harbor-artifact-root", help="Harbor artifact root for this trial")
    run.add_argument(
        "--harbor-service-artifact-root",
        help="CFS root for Harbor compose-service artifact exports",
    )
    run.add_argument("--harbor-famou-dir", help="Famou namespace under the Harbor trial")
    run.add_argument("--harbor-agent-task-view", help="Harbor Agent-visible task view")
    run.add_argument(
        "--harbor-backend",
        help="Harbor backend module:Class; it owns FMJob artifact export and verifier calls",
    )
    run.add_argument("--fm-job-bin", default="fm-job", help="FMJob CLI binary")
    run.add_argument("--solver-image", help="FMJob image for Terminal Solver")
    run.add_argument("--verifier-image", help="FMJob image for Terminal VerifierAgent")
    run.add_argument("--gt-verifier-image", help="FMJob image for the official TBS GT verifier")
    run.add_argument(
        "--candidate-verifier-mode",
        choices=("proxy", "gt_primary", "gt_final_only", "gt_budget", "dual_shadow"),
        default="proxy",
        help=(
            "候选轮次校验来源；gt_final_only 仅在最终审计调用一次官方 GT；"
            "gt_budget 允许 Solver 运行期间主动申请官方 GT，次数受 --official-gt-budget 限制"
        ),
    )
    run.add_argument(
        "--official-gt-budget",
        type=int,
        default=1,
        help="gt_budget / scimodeling_budget 中主动申请的 GT 次数；最终审计另计（k 可为 0）",
    )
    run.add_argument("--fmjob-cpu", default="4")
    run.add_argument("--fmjob-memory", default="8Gi")
    run.add_argument("--fmjob-gpu", type=int, default=0)
    run.add_argument("--fmjob-shm-size", default="8Gi")
    run.add_argument("--agent-binary")
    run.add_argument("--model")
    run.add_argument("--idea-model")
    run.add_argument("--implement-model")
    run.add_argument("--idea-rank-model")
    run.add_argument("--solver-model")
    run.add_argument("--verifier-model")
    run.add_argument(
        "--iterations",
        type=int,
        help="兼容参数：显式限制全局 benchmark 尝试和正式评分次数；默认不限制",
    )
    run.add_argument("--max-turns", type=int)
    run.add_argument("--agent-timeout-sec", type=float, default=3600)
    run.add_argument(
        "--implement-agent-timeout-sec",
        type=float,
        default=None,
        help="单次 Implement 激活的墙钟上限；默认继承 --agent-timeout-sec",
    )
    run.add_argument(
        "--verifier-planning-timeout-sec",
        type=float,
        default=None,
        help="VerifierAgent 编译预算；默认继承 task.toml 的 [agent].timeout_sec",
    )
    run.add_argument(
        "--max-refine-rounds",
        type=int,
        default=0,
        help="兼容参数（已废弃）；Terminal Task refine 不设轮数上限，仅受时间预算限制",
    )
    run.add_argument(
        "--implement-deadline-heartbeat",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="在 Implement 调用接近 DDL 时恢复同一 Session 并注入提交提醒",
    )
    run.add_argument(
        "--implement-deadline-heartbeat-after-sec",
        type=float,
        default=2400,
        help="Implement 调用开始后触发 DDL 心跳的秒数",
    )
    run.add_argument("--experiment-timeout-sec", type=float, default=3600)
    run.add_argument("--max-wall-time-hours", type=float)
    run.add_argument("--max-parallel-ideas", type=int, default=1)
    run.add_argument("--max-parallel-implementations", type=int, default=1)
    run.add_argument("--max-parallel-evaluations", type=int, default=1)
    run.add_argument("--max-implement-lifetime-sec", type=float, default=14400)
    run.add_argument("--max-implement-turns-per-actor", type=int, default=3)
    run.add_argument("--max-run-attempts-per-actor", type=int)
    run.add_argument("--max-official-evaluations-per-actor", type=int)
    run.add_argument("--max-repairs-per-revision", type=int, default=1)
    run.add_argument("--idea-queue-high-watermark", type=int)
    run.add_argument("--evaluation-queue-capacity", type=int)
    run.add_argument(
        "--pairwise-improve-search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Improve 回合同时提供当前 Refine 和一条 New Idea 供 Agent 选择或融合",
    )
    run.add_argument(
        "--refine-after-evaluation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "评测出分后仍由同一 ImplementActor 就地改进；"
            "关闭后出分即收工，改进须回 IdeaAgent 看图重新提方案（演化图 v2）"
        ),
    )
    run.add_argument(
        "--max-debug-attempts-per-actor",
        type=int,
        default=None,
        help="单个方案允许 debug 的总次数；不给＝不设独立上限",
    )
    run.add_argument(
        "--idea-generation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "是否调用 IdeaAgent 产出新方案。关闭后只消费队列里已有的条目，"
            "用于 resume 已结束的 Run 重跑指定 Idea"
        ),
    )
    run.add_argument(
        "--idea-graph",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "在 benchmark 工作流里启用 Idea 图（expbank/IDEAS.md 与 ideas/*.json 的"
            " idea→idea 派生边）。默认关闭以保持既有批次行为；开放科研工作流一直启用，"
            "不受本开关影响"
        ),
    )
    run.add_argument(
        "--idea-graph-version",
        choices=["v1", "v2"],
        default="v1",
        help=(
            "方案图的 schema 版本。v1：现状（expbank/IDEAS.md，单父、无分数）；"
            "v2：方案演化图（expbank/GRAPH.md，多父 DAG、节点带最好分、算子受校验）。"
            "默认 v1 以保持既有批次行为；需与 --idea-graph 同时开启才生效"
        ),
    )
    run.add_argument(
        "--time-aware-idea-ranking",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="在剩余时间进入冲刺窗口后调用 Judge 重排待实现 Idea",
    )
    run.add_argument(
        "--idea-rank-trigger-remaining-sec",
        type=float,
        default=3600,
    )
    run.add_argument("--idea-rank-max-turns", type=int, default=30)
    run.add_argument("--idea-rank-timeout-sec", type=float, default=600)
    run.add_argument(
        "--idea-debate",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Idea 入队前先由 Judge 批判；与冲刺期排序对称，开跑一段时间且已有评测证据后才启用",
    )
    run.add_argument(
        "--idea-debate-mode",
        choices=["respond", "rewrite"],
        default="respond",
        help="respond：Judge 只给反馈，由 Idea Agent 自己回应；rewrite：Judge 直接改写",
    )
    run.add_argument("--idea-debate-max-rounds", type=int, default=1)
    run.add_argument("--idea-debate-min-elapsed-sec", type=float, default=3600)
    run.add_argument("--idea-debate-min-evaluated-attempts", type=int, default=1)
    run.add_argument(
        "--idea-debate-allow-cross-task-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="允许在本 Run 尚无评测结果时启用，此时 Judge 只能引用跨任务经验",
    )
    run.add_argument(
        "--idea-debate-emit-pair",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="内容真被改过时，原版与改写版都入队，构成同 Run 内的配对样本",
    )
    run.add_argument("--idea-debate-max-turns", type=int, default=30)
    run.add_argument("--idea-debate-timeout-sec", type=float, default=1800)
    run.add_argument("--idea-judge-model")
    run.add_argument("--available-cpu", type=float)
    run.add_argument("--available-gpu", type=int)
    run.add_argument("--available-memory-gib", type=float)
    run.add_argument(
        "--agent-process-memory-limit-gib",
        type=float,
        help="单个 CLI Agent 及其工具进程的 RSS 上限；默认按控制面保留内存自动计算",
    )
    run.add_argument("--agent-uid", type=int)
    run.add_argument("--agent-gid", type=int)
    run.add_argument("--pricing-currency", default="USD")
    run.add_argument("--input-price-per-million", type=float)
    run.add_argument("--cache-creation-price-per-million", type=float)
    run.add_argument("--cache-read-price-per-million", type=float)
    run.add_argument("--output-price-per-million", type=float)
    run.add_argument(
        "--pricing-source",
        help="价格来源说明，例如 provider_billing 或 user_confirmed",
    )
    run.add_argument(
        "--pricing-effective-at",
        help="价格生效日期或版本，原样写入审计摘要",
    )
    run.add_argument(
        "--scimodelingbench-cache-dir",
        help="SciModelingBench trusted HF cache 目录；默认放在 run_dir/trusted 下",
    )
    run.add_argument(
        "--scimodelingbench-revision",
        help="SciModelingBench dataset revision；默认使用已验证的固定 revision",
    )
    run.add_argument(
        "--scimodelingbench-task-loader",
        help="SciModelingBench trusted module:callable task loader override",
    )
    run.add_argument(
        "--scimodelingbench-overwrite-problem",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="重新生成 SciModelingBench public problem snapshot",
    )
    run.add_argument(
        "--scimodelingbench-prepare-problem",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启动前准备 SciModelingBench public problem snapshot",
    )
    run.add_argument(
        "--scimodelingbench-managed-evaluator",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="自动创建 SciModelingBench keypair 并启动 trusted evaluator worker",
    )
    run.add_argument(
        "--finalize-evaluation",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Loop 结束后调用 Evaluator Adapter 声明的可信收尾阶段",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    """解析运行上下文并启动 BenchmarkHarness。"""
    # run_dir 保存调度状态和全部科研证据；workspace_dir 只保存 benchmark 最终
    # 需要看到的最佳代码与 canonical output，两者职责不能混用。
    run_dir = Path(args.run_dir).expanduser().resolve()
    problem_dir = (
        Path(args.problem_dir).expanduser().resolve()
        if args.problem_dir
        else run_dir / "problem"
    )
    workspace_dir = (
        Path(args.workspace_dir).expanduser().resolve()
        if args.workspace_dir
        else run_dir / "workspace"
    )
    pricing_values = (
        args.input_price_per_million,
        args.cache_creation_price_per_million,
        args.cache_read_price_per_million,
        args.output_price_per_million,
    )
    pricing = None
    if any(value is not None for value in pricing_values):
        if any(value is None for value in pricing_values):
            raise ValueError("启用价格重算时必须同时提供四类 Token 单价")
        pricing = {
            "currency": args.pricing_currency,
            "per_million_tokens": {
                "input": args.input_price_per_million,
                "cache_creation": args.cache_creation_price_per_million,
                "cache_read": args.cache_read_price_per_million,
                "output": args.output_price_per_million,
            },
            "source": args.pricing_source,
            "effective_at": args.pricing_effective_at,
        }
    managed_scimodelingbench = args.scimodelingbench_managed_evaluator
    if managed_scimodelingbench is None:
        managed_scimodelingbench = (
            args.benchmark_adapter == "scimodelingbench"
            and args.evaluator_adapter == "scimodelingbench"
        )
    scimodelingbench_problem_dir = problem_dir
    scimodelingbench_channel = (
        Path(args.evaluator_channel).expanduser().resolve()
        if args.evaluator_channel
        else None
    )
    scimodelingbench_worker = None
    scimodelingbench_public_key = None
    if args.benchmark_adapter == "scimodelingbench" and (
        args.scimodelingbench_prepare_problem or managed_scimodelingbench
    ):
        from ..integrations.scimodelingbench.launcher import (
            launch_evaluator_worker,
            prepare_scimodelingbench_problem,
            ensure_keypair,
        )
        from ..integrations.scimodelingbench.task_catalog import DEFAULT_HF_REVISION

        scimodelingbench_cache_dir = (
            Path(args.scimodelingbench_cache_dir).expanduser().resolve()
            if args.scimodelingbench_cache_dir
            else run_dir / "trusted" / "scimodelingbench" / "hf_home"
        )
        scimodelingbench_revision = (
            args.scimodelingbench_revision or DEFAULT_HF_REVISION
        )
        if args.scimodelingbench_prepare_problem:
            prepare_scimodelingbench_problem(
                task_id=args.task_id,
                problem_dir=scimodelingbench_problem_dir,
                cache_dir=scimodelingbench_cache_dir,
                revision=scimodelingbench_revision,
                task_loader=args.scimodelingbench_task_loader,
                overwrite=args.scimodelingbench_overwrite_problem,
            )
        if managed_scimodelingbench:
            if scimodelingbench_channel is None:
                raise ValueError(
                    "scimodelingbench managed evaluator requires --evaluator-channel"
                )
            private_key, public_key = ensure_keypair(scimodelingbench_channel)
            scimodelingbench_public_key = public_key
            scimodelingbench_worker = launch_evaluator_worker(
                task_id=args.task_id,
                workspace_dir=workspace_dir,
                channel_dir=scimodelingbench_channel,
                private_key=private_key,
                cache_dir=scimodelingbench_cache_dir,
                revision=scimodelingbench_revision,
                task_loader=args.scimodelingbench_task_loader,
                log_path=run_dir / "controller" / "scimodelingbench_evaluator.log",
            )

    if args.evaluator_channel:
        # 文件通道隔离 Controller 与可信 Evaluator：Controller 只写请求，root
        # Evaluator 读取固定 canonical output 并写回带签名的响应。
        channel = (
            scimodelingbench_channel
            or Path(args.evaluator_channel).expanduser().resolve()
        )
        public_key = (
            scimodelingbench_public_key
            or (
                Path(args.evaluator_public_key).expanduser().resolve()
                if args.evaluator_public_key
                else channel / "public_key.pem"
            )
        )
        evaluator = FileEvaluatorClient(
            channel,
            public_key=public_key,
            timeout_sec=args.evaluator_timeout_sec,
            allow_unsigned=args.allow_unsigned_evaluator,
            cancel_file=run_dir / "agent_control" / "research_stop_requested.json",
        )
    else:
        # HTTP 模式同样只提交 attempt_id，不能让 Agent 指定 evaluator 的输入路径。
        evaluator = HttpEvaluatorClient(
            args.evaluator_url,
            token=os.environ.get("FAMOU_EVALUATOR_TOKEN"),
            timeout_sec=args.evaluator_timeout_sec,
            cancel_file=run_dir / "agent_control" / "research_stop_requested.json",
        )
    # CLI 参数在此收敛为不可变配置；后续 Harness 会把它转换成标准
    # benchmark-managed goal，再交给统一 AsyncOrchestrator。
    config = HarnessConfig(
        task_id=args.task_id,
        run_dir=run_dir,
        problem_dir=problem_dir,
        workspace_dir=workspace_dir,
        agent_runtime=args.agent_runtime,
        agent_graph=args.agent_graph,
        idea_runtime=args.idea_runtime,
        implement_runtime=args.implement_runtime,
        solver_runtime=args.solver_runtime,
        verifier_runtime=args.verifier_runtime,
        agent_adapter=args.agent_adapter,
        benchmark_adapter=args.benchmark_adapter,
        evaluator_adapter=args.evaluator_adapter,
        harbor_trial_dir=(
            Path(args.harbor_trial_dir).expanduser().resolve()
            if args.harbor_trial_dir
            else None
        ),
        harbor_artifact_root=(
            Path(args.harbor_artifact_root).expanduser().resolve()
            if args.harbor_artifact_root
            else None
        ),
        harbor_service_artifact_root=(
            Path(args.harbor_service_artifact_root).expanduser().resolve()
            if args.harbor_service_artifact_root
            else None
        ),
        harbor_famou_dir=(
            Path(args.harbor_famou_dir).expanduser().resolve()
            if args.harbor_famou_dir
            else None
        ),
        harbor_agent_task_view=(
            Path(args.harbor_agent_task_view).expanduser().resolve()
            if args.harbor_agent_task_view
            else None
        ),
        harbor_backend=args.harbor_backend,
        fm_job_bin=args.fm_job_bin,
        solver_image=args.solver_image,
        verifier_image=args.verifier_image,
        gt_verifier_image=args.gt_verifier_image,
        candidate_verifier_mode=args.candidate_verifier_mode,
        official_gt_budget=args.official_gt_budget,
        fmjob_cpu=args.fmjob_cpu,
        fmjob_memory=args.fmjob_memory,
        fmjob_gpu=args.fmjob_gpu,
        fmjob_shm_size=args.fmjob_shm_size,
        model=args.model,
        idea_model=args.idea_model,
        implement_model=args.implement_model,
        idea_rank_model=args.idea_rank_model,
        solver_model=args.solver_model,
        verifier_model=args.verifier_model,
        agent_binary=args.agent_binary,
        iterations=args.iterations,
        agent_timeout_sec=args.agent_timeout_sec,
        implement_agent_timeout_sec=args.implement_agent_timeout_sec,
        verifier_planning_timeout_sec=args.verifier_planning_timeout_sec,
        max_refine_rounds=args.max_refine_rounds,
        implement_deadline_heartbeat=args.implement_deadline_heartbeat,
        implement_deadline_heartbeat_after_sec=(
            args.implement_deadline_heartbeat_after_sec
        ),
        experiment_timeout_sec=args.experiment_timeout_sec,
        max_wall_time_hours=args.max_wall_time_hours,
        max_turns=args.max_turns,
        max_parallel_ideas=args.max_parallel_ideas,
        max_parallel_implementations=args.max_parallel_implementations,
        max_parallel_evaluations=args.max_parallel_evaluations,
        max_implement_lifetime_sec=args.max_implement_lifetime_sec,
        max_implement_turns_per_actor=args.max_implement_turns_per_actor,
        max_run_attempts_per_actor=args.max_run_attempts_per_actor,
        max_official_evaluations_per_actor=args.max_official_evaluations_per_actor,
        max_repairs_per_revision=args.max_repairs_per_revision,
        refine_after_evaluation=args.refine_after_evaluation,
        max_debug_attempts_per_actor=args.max_debug_attempts_per_actor,
        idea_queue_high_watermark=args.idea_queue_high_watermark,
        evaluation_queue_capacity=args.evaluation_queue_capacity,
        pairwise_improve_search=args.pairwise_improve_search,
        idea_generation=args.idea_generation,
        idea_graph=args.idea_graph,
        idea_graph_version=args.idea_graph_version,
        time_aware_idea_ranking=args.time_aware_idea_ranking,
        idea_rank_trigger_remaining_sec=args.idea_rank_trigger_remaining_sec,
        idea_rank_max_turns=args.idea_rank_max_turns,
        idea_rank_timeout_sec=args.idea_rank_timeout_sec,
        idea_debate=args.idea_debate,
        idea_debate_mode=args.idea_debate_mode,
        idea_debate_max_rounds=args.idea_debate_max_rounds,
        idea_debate_min_elapsed_sec=args.idea_debate_min_elapsed_sec,
        idea_debate_min_evaluated_attempts=args.idea_debate_min_evaluated_attempts,
        idea_debate_allow_cross_task_only=args.idea_debate_allow_cross_task_only,
        idea_debate_emit_pair=args.idea_debate_emit_pair,
        idea_debate_max_turns=args.idea_debate_max_turns,
        idea_debate_timeout_sec=args.idea_debate_timeout_sec,
        idea_judge_model=args.idea_judge_model,
        available_cpu=args.available_cpu,
        available_gpu=args.available_gpu,
        available_memory_gib=args.available_memory_gib,
        agent_process_memory_limit_gib=args.agent_process_memory_limit_gib,
        agent_uid=args.agent_uid,
        agent_gid=args.agent_gid,
        finalize_evaluation=args.finalize_evaluation,
        pricing=pricing,
    )
    summary = None
    run_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        summary = BenchmarkHarness(config, evaluator).run()
    except BaseException as exc:  # noqa: BLE001 - ensure cleanup still runs
        run_error = exc
    finally:
        if scimodelingbench_worker is not None:
            try:
                stop_file = run_dir / "agent_control" / "research_stop_requested.json"
                if stop_file.is_file():
                    scimodelingbench_worker.close()
                else:
                    scimodelingbench_worker.wait_for_drain(
                        timeout_sec=args.evaluator_timeout_sec
                    )
            except BaseException as exc:  # noqa: BLE001 - preserve cleanup failure
                cleanup_error = exc
    if run_error is not None:
        raise run_error
    if cleanup_error is not None:
        raise cleanup_error
    assert summary is not None
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 研究预算耗尽、没有找到有效 Candidate 都属于可审计的 benchmark 结果；
    # 只有未捕获的设施异常才由上层异常路径形成非零退出码。
    return 0 if summary.get("status") == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    """执行 Agent Harness 命令行入口。"""
    parser = _build_parser()
    args = parser.parse_args(list(argv or sys.argv[1:]))
    if args.command == "run":
        return _run(args)
    parser.error(f"unsupported command: {args.command}")
    return 2
