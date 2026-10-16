"""给存量 run 重跑演化复盘 Agent，把经验补进跨任务经验库。

## 为什么需要它

跨任务经验库有两道正交闸门：合规通过（Judge Valid）**且**有 Agent 手写的
``evolution_markdown``。实测系统层 232 条里：

```
judge_valid 且有手写总结     58   ← 目前 Agent 能看到的全部
judge_valid 但没有手写总结  127   ← 本脚本的目标：覆盖 82 个不同任务
有手写总结但没过合规判定     17
两样都没有                   30
```

那 127 条当时的复盘 Agent 调用失败了（``summary_agent_error`` 里记着原因，多数
是要求写 JSON 而没写出来、或 ``Prompt is too long``），控制器只留下「方法标题 +
分数 + refine 血缘」的兜底罗列。它们的 run 目录都还在盘上（127/127 有
``source_run_dir``），ExpBank 证据完整，所以复盘可以事后重跑。

补完之后库从 58 条 / 25 个任务变成约 185 条 / 85 个任务，cellular_omics 从 4 个
任务涨到约 40 条——这是让跨任务经验库 A/B 有意义的前提。2026-09-06 那次 A/B 的
处理臂里，有 4 个任务落到 Idea Agent 手上的有内容条目是 **0** 条。

## 与离线补写脚本的区别

``offline_cross_task_summary.py`` 是**机器拼装**：从 run 目录按模板拼出 Markdown，
34/34 都没有 ``When to use`` / ``When not to use``，可迁移经验只有两句按分数拼的
模板话。它产出的记录带 ``offline_generated`` 标记，被内容闸门排除。

本脚本**真的起一个复盘 Agent**，走 Loop 收尾时那条通路（同一份提示词、同一个
``summarize_experience`` worker），所以产出与正常 run 的复盘同质，不打
``offline_generated``；只额外记 ``resummarized`` 做溯源。

## 用法

```
export ANTHROPIC_BASE_URL=... ANTHROPIC_AUTH_TOKEN=...
python -m famou_scientist.loop.examples.naturebench.fmjob.resummarize_run \
    --bank-root .famou/cross_task_expbank \
    --model glm-5.3 --runtime claude \
    --limit 5                      # 先试几个
python -m ...resummarize_run --bank-root ... --list-only   # 只列待补 run
```

产出写在每个 run 的 ``controller/cross_task_experience_record.json``（outbox），
再由 ``sync_cross_task_expbank.py --runs-root ... --bank-root ...`` 统一合并发布
——判定票据的解析和发布口径都在那一步，本脚本不直接写库。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from famou_scientist.loop.agents.workers import workers_from_goal
from famou_scientist.loop.runtime.orchestrator import Orchestrator
from famou_scientist.loop.storage.cross_task_expbank import (
    CrossTaskExpBank,
    load_naturebench_domain,
    resolve_experience_domain,
)
from famou_scientist.loop.storage.expbank import ExpBank
from famou_scientist.loop.storage.state import ResearchState
from famou_scientist.loop.utils import atomic_write_json


class _RunView:
    """只为复用 Orchestrator 的两个上下文构造函数而存在的最小外壳。

    ``_experience_summary_context`` 和 ``_base_experience_summary`` 只用到
    ``goal_doc`` / ``workspace`` / ``workflow_type`` 三个属性和几个兄弟方法，
    没有队列、facility 或 evaluator 依赖。借用它们而不是抄一遍，是因为「复盘
    Agent 看到什么」必须与正常 run 逐字一致，否则补出来的经验和原生的不同质。
    """

    _experience_summary_context = Orchestrator._experience_summary_context
    _base_experience_summary = Orchestrator._base_experience_summary
    _attempt_index = Orchestrator._attempt_index
    _public_task_summary = Orchestrator._public_task_summary
    # 下面几个在 Orchestrator 上是 staticmethod，取出来是普通函数，
    # 直接塞进类体会变成实例方法（self 会占掉第一个参数），必须重新包一层。
    _finite_attempt_score = staticmethod(Orchestrator._finite_attempt_score)
    _experience_text = staticmethod(Orchestrator._experience_text)
    _achievement_level = staticmethod(Orchestrator._achievement_level)
    _contains_nonempty_error = staticmethod(Orchestrator._contains_nonempty_error)

    def __init__(self, workspace: Path, goal_doc: dict[str, Any]):
        self.workspace = workspace
        self.goal_doc = goal_doc
        self.workflow_type = "benchmark_managed"


def pending_records(bank_root: Path) -> list[dict[str, Any]]:
    """列出「合规通过但缺 Agent 手写总结」的系统记录。"""

    bank = CrossTaskExpBank(bank_root)
    pending: list[dict[str, Any]] = []
    for record in bank.records():
        verdict = record.get("judge_verdict")
        valid = verdict is True or (
            isinstance(verdict, str) and verdict.strip().lower() == "valid"
        )
        if not valid:
            continue
        markdown = str(record.get("evolution_markdown") or "").strip()
        if markdown and not record.get("offline_generated"):
            continue
        source = record.get("source_run_dir")
        if not isinstance(source, str) or not Path(source).is_dir():
            continue
        pending.append(record)
    # 同一任务多条时先补分数高的：它们的经验更值得传播。
    pending.sort(
        key=lambda item: (
            -(item["best_score"] if isinstance(item.get("best_score"), (int, float)) else -1e9),
            str(item.get("task_id") or ""),
        )
    )
    return pending


def _goal_doc(run_dir: Path, task_id: str, *, model: str, runtime: str,
              timeout_sec: float) -> dict[str, Any]:
    """构造只含复盘所需字段的 goal 文档。

    `public_dir` 必须给对：``_public_task_summary`` 要从 ``problem/README.md``
    取任务一句话说明，缺了它补出来的记录在目录里还是没法做相关性判断。

    ``workers`` 有两处不能省，否则 ``workers_from_goal`` 会静默回退到
    ``DummyWorkerSet``——它的 ``summarize_experience`` 返回一个固定字典，于是
    整批「跑完了但没有 evolution_markdown」，看不出是没起 Agent：

    - ``type: "prompt"``：不写就走不到 ``PromptWorkerSet``。
    - ``idea`` / ``implement`` 也声明成 agent：这样 ``all_benchmark_nodes_are_agents``
      成立，``llm_from_goal`` 不会被调用（复盘不需要 LLM 通道，那条路会因为缺
      配置直接报错）。这两个 worker 在本脚本里不会被使用。
    """

    def agent(role: str) -> dict[str, Any]:
        return {
            "type": "agent",
            "adapter": "cli",
            "runtime": runtime,
            "role": role,
            "model": model,
            "timeout_sec": timeout_sec,
            "title": f"famou-resummarize-{task_id}-{role}",
            "auto_approve": True,
        }

    return {
        "goal": {"id": task_id, "name": task_id},
        "workflow": {"type": "benchmark_managed"},
        "benchmark_task": {
            "type": "naturebench",
            "task_id": task_id,
            "public_dir": str(run_dir / "problem"),
        },
        "workers": {
            "type": "prompt",
            "idea": agent("idea"),
            "implement": agent("implement"),
            "experience_summary": agent("experience_summary"),
        },
    }


_NUMBER = re.compile(r"[-+]?\d+\.\d{2,}")
_UNCONFIRMED = re.compile(r"未确认|无可迁移内容|没有可引用的公开证据")


def summary_defects(markdown: str) -> list[str]:
    """判断复盘产出是不是「跑完了但什么都没写出来」。

    实测 127 篇补库产出里有 5 篇是这样：Agent 拿到了正确的 ``expbank_dir``
    绝对路径和 14 条 attempt 索引，却在自己的隔离 worktree 里执行
    ``ls -la expbank/``（相对路径，当然是空的），据此断定「ExpBank 未挂载或
    为空」，然后写出一篇章节齐全、每节都是「未确认」的总结。

    它格式完整、也是 Agent 手写的，所以能过库的内容闸门——闸门查的是
    「有没有人写」，不是「写出来的有没有内容」。这道校验补上后一维。
    """

    defects: list[str] = []
    numbers = len(_NUMBER.findall(markdown))
    if numbers == 0:
        defects.append("正文没有任何具体数值（分数/指标），无法核查")
    unconfirmed = len(_UNCONFIRMED.findall(markdown))
    if unconfirmed >= 4:
        defects.append(f"出现 {unconfirmed} 处「未确认/无可迁移」，疑似未读取证据")
    if len(markdown) < 1200:
        defects.append(f"正文仅 {len(markdown)} 字符，短于任何正常复盘")
    return defects


def resummarize(
    run_dir: Path,
    task_id: str,
    *,
    model: str,
    runtime: str,
    timeout_sec: float,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """重跑一个 run 的复盘，把结果写回该 run 的 outbox。

    产出不合格时自动重试一次（``max_attempts``）：这类失败是 Agent 单次采样
    的操作失误（用相对路径找证据），换一次采样通常就好，122/127 是正常的。
    """

    last_defects: list[str] = []
    for attempt in range(1, max_attempts + 1):
        summary = _resummarize_once(
            run_dir, task_id, model=model, runtime=runtime, timeout_sec=timeout_sec
        )
        defects = summary_defects(summary["evolution_markdown"])
        if not defects:
            outbox = run_dir / "controller" / "cross_task_experience_record.json"
            atomic_write_json(outbox, summary)
            return {
                "run_dir": str(run_dir),
                "task_id": task_id,
                "domain": summary["domain"],
                "attempts": summary["attempt_count"],
                "markdown_chars": len(summary["evolution_markdown"]),
                "agent_calls": attempt,
                "outbox": str(outbox),
            }
        last_defects = defects
        print(
            f"  [{task_id}] 第 {attempt} 次产出不合格：{'；'.join(defects)}",
            flush=True,
        )
    raise RuntimeError(
        f"复盘产出连续 {max_attempts} 次不合格：{'；'.join(last_defects)}"
    )


def _resummarize_once(
    run_dir: Path,
    task_id: str,
    *,
    model: str,
    runtime: str,
    timeout_sec: float,
) -> dict[str, Any]:
    """跑一次复盘 Agent，返回合并后的记录（不落盘）。"""

    goal_doc = _goal_doc(
        run_dir, task_id, model=model, runtime=runtime, timeout_sec=timeout_sec
    )
    domain = resolve_experience_domain(goal_doc) or load_naturebench_domain(task_id)
    if domain is None:
        raise ValueError(f"无法解析领域: {task_id}")

    attempts = ExpBank(run_dir).all_attempts()
    if not attempts:
        raise ValueError(f"ExpBank 为空，没有可复盘的证据: {run_dir}")
    state = ResearchState(run_dir).load()
    state = state if isinstance(state, dict) else {}

    view = _RunView(run_dir, goal_doc)
    base = view._base_experience_summary(state, attempts, domain)
    context = view._experience_summary_context(state, attempts, domain)

    workers = workers_from_goal(goal_doc, run_dir, cwd=run_dir)
    if getattr(workers, "experience_summary_agent", None) is None:
        # DummyWorkerSet 的 summarize_experience 会返回一个固定字典，跑完却没有
        # 正文；宁可在这里炸掉，也不要整批「成功但空手而归」。
        raise RuntimeError(
            "复盘 Agent 没被装配起来（workers 回退到了 Dummy 或 single_call）"
        )
    agent_summary = workers.summarize_experience(context)
    if not isinstance(agent_summary, dict):
        raise RuntimeError(f"复盘 Agent 返回类型异常: {type(agent_summary).__name__}")

    summary = Orchestrator._merge_experience_summary(base, agent_summary)
    markdown = agent_summary.get("evolution_markdown")
    if isinstance(markdown, str) and markdown.strip():
        summary["evolution_markdown"] = markdown.strip()
    if not str(summary.get("evolution_markdown") or "").strip():
        raise RuntimeError("复盘 Agent 没有写出 evolution_markdown")
    # 溯源标记。刻意**不**打 offline_generated：那是给机器拼装的记录用的，
    # 会被内容闸门排除，而这份是复盘 Agent 真写的。
    summary["resummarized"] = True
    summary["resummarize_model"] = model
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--model", default=os.environ.get("RESUMMARIZE_MODEL", "glm-5.3"))
    parser.add_argument("--runtime", default="claude")
    parser.add_argument("--timeout-sec", type=float, default=1800.0)
    parser.add_argument("--limit", type=int, default=0, help="0 = 不限")
    parser.add_argument("--task-id", action="append", help="只处理指定任务，可重复")
    parser.add_argument(
        "--run-dir",
        action="append",
        type=Path,
        help=(
            "强制重跑指定 run（可重复），不看它是否在待补列表里。"
            "用于修复「已产出但质量不合格」的记录——它们已经有 evolution_markdown，"
            "不会出现在 --list-only 里。"
        ),
    )
    parser.add_argument(
        "--shards",
        type=int,
        default=1,
        help="把待补列表切成 N 片，配合 --shard 并行跑（列表是确定性的，分片不重不漏）",
    )
    parser.add_argument("--shard", type=int, default=0, help="本进程处理第几片（0 起）")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        help="逐条结果写入该 JSONL，便于并行分片后汇总",
    )
    args = parser.parse_args(argv)

    if args.run_dir:
        # 强制模式：绕过待补列表，直接按 run 目录重跑。task_id 从系统记录里取，
        # 取不到就退回目录名解析。
        bank = CrossTaskExpBank(args.bank_root.expanduser().resolve())
        by_dir = {
            str(item.get("source_run_dir")): item
            for item in bank.records()
            if item.get("source_run_dir")
        }
        pending = []
        for path in args.run_dir:
            resolved = str(path.expanduser().resolve())
            record = by_dir.get(resolved)
            if record is None:
                parser.error(f"系统记录里找不到该 run：{resolved}")
            pending.append(record)
    else:
        pending = pending_records(args.bank_root.expanduser().resolve())
    if args.task_id:
        wanted = set(args.task_id)
        pending = [item for item in pending if str(item.get("task_id")) in wanted]
    if args.limit:
        pending = pending[: args.limit]
    if args.shards > 1:
        if not 0 <= args.shard < args.shards:
            parser.error("--shard 必须落在 [0, --shards)")
        pending = pending[args.shard :: args.shards]

    if args.list_only:
        for record in pending:
            print(
                json.dumps(
                    {
                        "task_id": record.get("task_id"),
                        "run_dir": record.get("source_run_dir"),
                        "best_score": record.get("best_score"),
                        "domain": record.get("domain"),
                        "previous_error": str(record.get("summary_agent_error") or "")[:120],
                    },
                    ensure_ascii=False,
                )
            )
        print(f"# pending={len(pending)}", file=sys.stderr)
        return 0

    ok = 0
    failed = 0
    for index, record in enumerate(pending, start=1):
        run_dir = Path(str(record["source_run_dir"]))
        task_id = str(record.get("task_id") or "")
        try:
            result = resummarize(
                run_dir,
                task_id,
                model=args.model,
                runtime=args.runtime,
                timeout_sec=args.timeout_sec,
            )
            result["status"] = "ok"
            ok += 1
        except Exception as exc:  # noqa: BLE001 - 单个 run 失败不能中断整批
            result = {
                "status": "failed",
                "run_dir": str(run_dir),
                "task_id": task_id,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=3),
            }
            failed += 1
        line = json.dumps(result, ensure_ascii=False)
        print(f"[{index}/{len(pending)}] {line}", flush=True)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    print(json.dumps({"ok": ok, "failed": failed}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
