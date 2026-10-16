"""
runners/cli/run_bench.py — 统一评测入口（B2 澄清 / B3 端到端）

B2 = 只运行到澄清结束（检测到 Write/Edit/Task 即终止），不跑 eval
B3 = 完整端到端（澄清 → 执行 → 评估）

用法：
    python -m runners.cli.run_bench --benchmark b2 --case city_delivery_routing --runner cc_famou --answerer api
    python -m runners.cli.run_bench --benchmark b3 --case all --runner cc_famou --answerer api --runs 3

兼容入口（等价调用）：
    python -m runners.cli.run_b2 --case city_delivery_routing --runner cc_famou --answerer api
    python -m runners.cli.run_b3 --case all --runner cc_famou --answerer api --runs 3
"""

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anyio

from ..defaults import DEFAULT_AGENT_CONFIG, RUNNER_CHOICES
from ..workspace import prepare_workspace, build_instruction, build_query, save_json, write_result, write_meta

_RE_CLARIFY = re.compile(r"<clarify>(.*?)(?:</clarify>|\Z)", re.DOTALL)

# B2 在检测到这些工具调用时提前终止：说明 agent 已结束澄清、开始执行
B2_STOP_TOOLS = {"Write", "Edit", "Task"}


# ── 构建 answerer ────────────────────────────────────────────────────────────

def _parse_answerer_arg(value: str) -> tuple[str, str]:
    """解析 --answerer 参数，支持 'api' 或 'api:style' 格式。"""
    if ":" in value:
        kind, style = value.split(":", 1)
        return kind, style
    return value, "default"


def _build_answerer(case: Path, args):
    """根据 CLI 参数构建 answerer 实例。"""
    kind, style = _parse_answerer_arg(args.answerer)

    if kind == "api":
        bg_path = args.background if args.background is not None else case / "gt.json"
        if not bg_path.is_file():
            raise FileNotFoundError(
                f"背景文件不存在: {bg_path}\n"
                f"请在 {case}/ 下创建 gt.json，或通过 --background 指定"
            )

        background_text = bg_path.read_text(encoding="utf-8")

        instruction_text = ""
        instruction_file = case / "instruction.md"
        if instruction_file.is_file():
            instruction_text = instruction_file.read_text(encoding="utf-8")

        information = ""
        info_file = case / "information.md"
        if info_file.is_file():
            information = info_file.read_text(encoding="utf-8")
        else:
            # 兼容旧目录结构：information.md 不存在时回退到 data_schema.md
            schema_file = case / "data_schema.md"
            if schema_file.is_file():
                information = schema_file.read_text(encoding="utf-8")

        from ..answerer import ApiAnswerer
        answerer_obj = ApiAnswerer(
            background=background_text,
            instruction_text=instruction_text,
            information=information,
            style=style,
            model=args.answer_model,
        )
        print(f"  [背景文件] {bg_path}  [style] {style}")
        return answerer_obj

    if kind == "default-value":
        from ..answerer import DefaultValueAnswerer
        return DefaultValueAnswerer()

    from ..answerer import HumanAnswerer
    return HumanAnswerer()


# ── 评估工具 ──────────────────────────────────────────────────────────────────

def _run_eval(case: Path, workspace: Path):
    extractor = case / "tests" / "extractor_agent.py"
    if not extractor.exists():
        print(f"[eval] 跳过：{case.name} 暂无 tests/extractor_agent.py")
        return

    from ..eval import run_eval

    print("[eval 1/2] Running extractor...")
    result = run_eval(case, workspace)

    status = result.get("extraction_status", "?")
    print(f"    extraction_status: {status}")
    if result.get("extraction_notes"):
        print(f"    notes: {result['extraction_notes']}")
    if status == "success":
        print("[eval 2/2] Evaluator done.")

    write_result(workspace, result)


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def _run(
    case: Path,
    workspace: Path,
    runner_type: str,
    prompt_variant: str,
    skill_set: str,
    query_variant: str | None,
    answerer_obj,
    benchmark: str,
    no_eval: bool,
    model: str | None = None,
    evolve: int | None = None,
    sandbox: bool = False,
    idle_timeout_s: int = 7200,
):
    from ..backends.factory import runner_from_config
    from ..backends.base import RunnerConfig

    case_name = case.name
    answerer_name = type(answerer_obj).__name__
    prompt_source = f"queries/{query_variant}.md" if query_variant else "instruction.md"
    is_b2 = benchmark == "b2"
    stop_on_tools = B2_STOP_TOOLS if is_b2 else None
    skip_eval = is_b2 or no_eval

    tag = "B2" if is_b2 else "B3"
    print(f"╔══════════════════════════════════════════════════════════╗")
    print(f"  [{tag}] Case:        {case_name}")
    print(f"  Runner:            {runner_type}")
    print(f"  Model:             {model or '(platform default)'}")
    print(f"  Answerer:          {answerer_name}")
    print(f"  Prompt:            {prompt_source}")
    print(f"  Skill-set:         {skill_set}")
    print(f"  Workspace:         {workspace}")
    print(f"╚══════════════════════════════════════════════════════════╝\n")

    # ── 1. 准备 workspace ────────────────────────────────────────────────────
    prepare_workspace(case, workspace)
    if query_variant:
        query_text = build_query(case, workspace, variant=query_variant)
    else:
        query_text = build_instruction(case, workspace)

    # ── 2. 启动 runner ───────────────────────────────────────────────────────
    sandbox_cfg = None
    if sandbox:
        from ..sandbox import SandboxConfig
        from ..bench_config import (
            CASES_DIR, RESULTS_DIR, INTERACTIVE_DIR,
            SANDBOX_EXTRA_DENY_READ,
        )
        sandbox_cfg = SandboxConfig(
            deny_read=[
                str(CASES_DIR), str(RESULTS_DIR), str(INTERACTIVE_DIR),
                *SANDBOX_EXTRA_DENY_READ,
            ],
            allow_read=[str(workspace)],
        )

    config = RunnerConfig(
        runner_type=runner_type,
        agent_config_dir=DEFAULT_AGENT_CONFIG[runner_type],
        prompt_variant=prompt_variant,
        skill_set=skill_set,
        model=model,
        sandbox=sandbox_cfg,
        idle_timeout_s=idle_timeout_s,
    )
    runner = runner_from_config(config)

    dialog: list[dict] = []
    started_at = datetime.now(timezone.utc).isoformat()

    agent_run_path = workspace / ".eval" / "agent_run.json"
    save_json(agent_run_path, {
        "case": case_name,
        "benchmark": benchmark,
        "runner": runner_type,
        "answerer": answerer_name,
        "prompt_variant": prompt_variant,
        "skill_set": skill_set,
        "model": model,
        "prompt_source": prompt_source,
        "query_variant": query_variant,
        "workspace": str(workspace),
        "started_at": started_at,
        "status": "running",
    })

    final_response = ""
    clarify_turns = 0
    session_id = None
    run_error = None

    async with await runner.start(workspace) as session:

        try:
            # ── 3. 澄清循环 ─────────────────────────────────────────────────
            # agent 收到 prompt 后自行决定是否澄清；
            # 框架只在检测到 <clarify> 时介入回答，其余时间等 agent 自行完成。
            # B2 模式下 stop_on_tools 会在检测到 Write/Edit/Task 时提前终止。
            message = query_text
            turn = 0

            while True:
                turn += 1
                role = "user" if turn == 1 else "operator"
                print(f"\n{'─'*60}")
                print(f"[Turn {turn}] Sending {'initial query' if turn == 1 else 'answerer reply'}...\n")

                dialog.append({
                    "role": role,
                    "content": message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                response = await session.send(message, stop_on_tools=stop_on_tools)

                dialog.append({
                    "role": "agent",
                    "content": response,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                final_response = response

                # 检测 <clarify>：有则回答，无则澄清结束
                clarify_match = _RE_CLARIFY.search(response)
                if not clarify_match:
                    print(f"\n{'─'*60}")
                    if is_b2:
                        print(f"[{tag}] 响应中无 <clarify>，澄清阶段结束。")
                    else:
                        print(f"[{tag}] 无 <clarify>，agent 已完成澄清并自行执行。")
                    break

                question = clarify_match.group(1).strip()
                print(f"\n{'='*60}")
                print(f"[澄清问题]\n{question}")
                print(f"{'='*60}")

                message = answerer_obj.answer(question)
                if answerer_name != "HumanAnswerer":
                    print(f"[Auto] 回答: {message}")
                clarify_turns += 1

            # ── 3b. 演化阶段 ────────────────────────────────────────────────
            if evolve and not is_b2:
                evolve_cmd = f"/evolve {evolve}"
                print(f"\n{'─'*60}")
                print(f"[Evolve] Sending '{evolve_cmd}' for deep evolution...\n")

                dialog.append({
                    "role": "operator",
                    "content": evolve_cmd,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                evolve_response = await session.send(evolve_cmd)

                dialog.append({
                    "role": "agent",
                    "content": evolve_response,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                final_response = evolve_response
                print(f"\n{'─'*60}")
                print(f"[Evolve] 演化完成。")

        except Exception as e:
            run_error = e
            print(f"\n[ERROR] agent 运行失败: {e}", file=sys.stderr)
        finally:
            session_id = session.session_id

    # ── 4. 保存产物（无论成功或失败都执行）─────────────────────────────────
    finished_at = datetime.now(timezone.utc).isoformat()
    status = "done" if run_error is None else "error"

    if final_response and not is_b2:
        (workspace / "_agent_summary.md").write_text(final_response, encoding="utf-8")

    save_json(workspace / ".eval" / "dialog.json", dialog)

    agent_run_meta = {
        "case": case_name,
        "benchmark": benchmark,
        "runner": runner_type,
        "answerer": answerer_name,
        "prompt_variant": prompt_variant,
        "skill_set": skill_set,
        "model": model,
        "prompt_source": prompt_source,
        "query_variant": query_variant,
        "workspace": str(workspace),
        "session_id": session_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "evolve": evolve,
        "clarify_turns": clarify_turns,
        "total_dialog_turns": len([d for d in dialog if d["role"] == "agent"]),
    }
    if run_error is not None:
        agent_run_meta["error"] = str(run_error)
    save_json(agent_run_path, agent_run_meta)

    # ── 5. trace 收集 + 转换（无论成功或失败都尝试）─────────────────────────
    if session_id:
        from ..trace_converter import collect_trace, convert_trace
        try:
            collect_trace(runner_type, workspace, session_id)
        except Exception as e:
            print(f"[WARN] trace collection failed: {e}", file=sys.stderr)

        try:
            convert_trace(runner_type, workspace, session_id)
        except Exception as e:
            print(f"[WARN] trace conversion failed: {e}", file=sys.stderr)

    print(f"\n── {tag} {'完成' if run_error is None else '失败'} ───────────────────────────────────────────────")
    print(f"  session_id:        {session_id}")
    print(f"  status:            {status}")
    print(f"  clarify_turns:     {clarify_turns}")
    print(f"  dialog:            {workspace / '.eval' / 'dialog.json'}")
    if not is_b2:
        print(f"  agent_summary:     {workspace / '_agent_summary.md'}")
    if run_error is not None:
        print(f"  error:             {run_error}")
    print()

    if run_error is not None:
        raise run_error

    if skip_eval:
        if not is_b2 and no_eval:
            print("  (--no-eval: skipping evaluation)")
        return

    # ── 6. 评估 ───────────────────────────────────────────────────────────────
    time.sleep(3)
    print(f"[eval] Running evaluation...\n")
    _run_eval(case, workspace)


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    from ..bench_config import resolve_case, RESULTS_DIR, CASES_DIR

    parser = argparse.ArgumentParser(description="Famou-Bench 统一评测（B2 澄清 / B3 端到端）")
    parser.add_argument("--benchmark", choices=["b2", "b3"], required=True,
                        help="评测模式: b2（澄清阶段）| b3（端到端）")
    parser.add_argument("--case", nargs="+", required=True,
                        help="case 名称，支持多个或 'all'")
    parser.add_argument("--runner", choices=RUNNER_CHOICES, required=True,
                        help="runner 类型")
    parser.add_argument("--runs", type=int, default=1,
                        help="每个 case 运行次数（默认 1）")
    parser.add_argument("--answerer", default="human",
                        help="回答方式: human | api | api:minimal | default-value（默认 human）")
    parser.add_argument("--background", type=Path, default=None,
                        help="背景知识文件路径（默认自动读取 case/gt.json）")
    parser.add_argument("--answer-model", default=None,
                        help="API 回答使用的模型（默认读取 bench_config.toml）")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="agent 工作目录（仅限单 case 单次运行）")
    parser.add_argument("--no-eval", action="store_true",
                        help="跳过 extract + evaluate（B2 始终跳过）")
    parser.add_argument("--query-variant", default=None,
                        help="query 变体名称（queries/ 下的文件名）；B2 默认 'default'，B3 默认使用 instruction.md")
    parser.add_argument("--prompt-variant", default="default",
                        help="prompt variant 名称（默认: default）")
    parser.add_argument("--skill-set", default="default",
                        help="注入的 skill 集名称（默认: default）")
    parser.add_argument("--model", default="sonnet",
                        help="agent 模型（别名: sonnet/opus/haiku，或完整 ID；默认: sonnet）")
    parser.add_argument("--evolve", type=int, default=None,
                        help="首次执行完成后触发深度演化的迭代次数（如 --evolve 25）")
    parser.add_argument("--sandbox", action="store_true",
                        help="启用文件系统沙箱（deny benchmark cases + 同 batch 其他 run）")
    parser.add_argument("--idle-timeout", type=int, default=7200,
                        help="opencode 子进程多久无 stdout 事件就 killpg（秒，默认 7200=120min）")
    args = parser.parse_args()

    # ── 应用 benchmark 模式默认值 ─────────────────────────────────────────────
    # B2 默认用 queries/default.md；B3 默认用 instruction.md
    if args.query_variant is None and args.benchmark == "b2":
        args.query_variant = "default"

    # ── 解析 cases ────────────────────────────────────────────────────────────
    def _has_prompt(p: Path) -> bool:
        if args.query_variant:
            return (p / "queries" / f"{args.query_variant}.md").exists()
        return (p / "instruction.md").exists()

    if args.case == ["all"]:
        cases = sorted(
            p for p in CASES_DIR.iterdir()
            if p.is_dir() and _has_prompt(p)
            and (args.benchmark == "b2" or (p / "tests").is_dir())
        )
        if not cases:
            prompt_desc = f"queries/{args.query_variant}.md" if args.query_variant else "instruction.md"
            extra = " + tests/" if args.benchmark == "b3" else ""
            print(f"[ERROR] CASES_DIR 下无任何包含 {prompt_desc}{extra} 的 case: {CASES_DIR}",
                  file=sys.stderr)
            sys.exit(1)
        print(f"[All] 发现 {len(cases)} 个 case: {[c.name for c in cases]}")
    else:
        cases = []
        for name in args.case:
            try:
                case = resolve_case(name)
                if args.query_variant:
                    prompt_file = case / "queries" / f"{args.query_variant}.md"
                    if not prompt_file.is_file():
                        print(f"[SKIP] {name}: {prompt_file} not found", file=sys.stderr)
                        continue
                else:
                    prompt_file = case / "instruction.md"
                    if not prompt_file.is_file():
                        print(f"[SKIP] {name}: instruction.md not found", file=sys.stderr)
                        continue
                if args.benchmark == "b3" and not (case / "tests").is_dir():
                    print(f"[SKIP] {name}: tests/ not found", file=sys.stderr)
                    continue
                cases.append(case)
            except FileNotFoundError as e:
                print(f"[ERROR] {e}", file=sys.stderr)
                sys.exit(1)

    if not cases:
        print("[ERROR] 没有可运行的 case", file=sys.stderr)
        sys.exit(1)

    # ── 校验 ──────────────────────────────────────────────────────────────────
    if args.workspace is not None and (len(cases) > 1 or args.runs > 1):
        print("[ERROR] --workspace 只能在单 case 单次运行时使用", file=sys.stderr)
        sys.exit(1)

    agent_config = DEFAULT_AGENT_CONFIG[args.runner]
    if agent_config is not None and not agent_config.is_dir():
        print(f"[ERROR] agent 配置目录不存在: {agent_config}", file=sys.stderr)
        sys.exit(1)

    # ── 运行 ──────────────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = RESULTS_DIR / f"{args.benchmark}_{args.runner}_{timestamp}"
    total = len(cases) * args.runs

    write_meta(batch_dir, {
        "benchmark": args.benchmark,
        "runner": args.runner,
        "prompt_variant": args.prompt_variant,
        "skill_set": args.skill_set,
        "model": args.model,
        "query_variant": args.query_variant,
        "answerer": args.answerer,
        "answer_model": args.answer_model if args.answerer.startswith("api") else None,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "cases": [c.name for c in cases],
        "runs_per_case": args.runs,
    })

    failed: list[str] = []

    for case in cases:
        try:
            answerer_obj = _build_answerer(case, args)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            failed.append(case.name)
            continue

        for run_idx in range(1, args.runs + 1):
            if args.workspace is not None:
                workspace = args.workspace.resolve()
            elif args.runs == 1:
                workspace = (batch_dir / case.name).resolve()
            else:
                workspace = (batch_dir / case.name / f"run_{run_idx:02d}").resolve()

            if total > 1:
                label = f"{case.name}" + (f"  run {run_idx}/{args.runs}" if args.runs > 1 else "")
                print(f"\n{'─'*62}")
                print(f"  {label}")
                print(f"{'─'*62}")

            try:
                anyio.run(
                    _run,
                    case, workspace, args.runner, args.prompt_variant,
                    args.skill_set, args.query_variant, answerer_obj,
                    args.benchmark, args.no_eval, args.model, args.evolve,
                    args.sandbox, args.idle_timeout,
                )
            except Exception as exc:
                print(f"[ERROR] case {case.name!r} 运行失败: {exc}", file=sys.stderr)
                failed.append(case.name)

    # ── 更新 meta 状态 ───────────────────────────────────────────────────────
    write_meta(batch_dir, {
        "benchmark": args.benchmark,
        "runner": args.runner,
        "prompt_variant": args.prompt_variant,
        "skill_set": args.skill_set,
        "model": args.model,
        "query_variant": args.query_variant,
        "answerer": args.answerer,
        "answer_model": args.answer_model if args.answerer.startswith("api") else None,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "done" if not failed else "partial",
        "cases": [c.name for c in cases],
        "runs_per_case": args.runs,
        "failed": failed if failed else None,
    })

    # ── 汇总 ─────────────────────────────────────────────────────────────────
    if total > 1:
        print(f"\n{'═'*60}")
        print(f"[汇总] 共 {len(cases)} 个 case × {args.runs} 次，"
              f"成功 {total - len(failed)}，失败 {len(failed)}")
        if failed:
            print(f"[汇总] 失败列表: {failed}")
        print(f"[汇总] 实验目录: {batch_dir}")


if __name__ == "__main__":
    main()
