"""Resume 一个已按墙钟结束的 NatureBench Run，并重放被冲刺期排序过的 Idea。

## 为什么需要这个脚本

冲刺期排序（`time_aware_idea_ranking`）确实决定了谁能被实现——按 Judge 给的 rank 分组，
rank 1 拿到分数的概率是 rank 2 的 4.4 倍（27% vs 6%）。但**无法判断它选得对不对**：
336 条被排序的 Idea 只有 13.1% 最终拿到分数，被排在后面的那些根本没有分数，
反事实不存在。

也不能新建 Run 重跑：375/375（100%）的被排序 Idea 正文都引用了原 Run 的具体 attempt
编号（`基于 0004`、`relation=derived_from`），在全新工作区里 ImplementAgent 不知道
0004 是什么。

所以只能 resume 原 Run，在原有 ExpBank 和代码基线上把被排序的 Idea **全部**重跑一次
（含当时已实现的 rank 1），同一模型、同时并发、同样时间预算——位置优势因此被消掉，
剩下的就是纯粹"Judge 的顺序和实际分数顺序是否保序"。

## 这个脚本做三件事，其余全部复用现成机制

resume 本身**不需要状态手术**：`AsyncOrchestrator.run()` 启动时会调用 `resume_task()`，
它在 `termination_reason == "wall_time_budget_exhausted"` 时自动重排队、重置 actor、
清 shutdown、并把 `active_run_started_at` 重置为 now（墙钟预算完整重置）。
实测目标 Run 中 129/132 正是这个终止原因，且被排序 Idea 的 240/240 个 `not_executed`
条目原因都是 `research_wall_time_budget_exhausted`，与 `requeue_for_resume` 的前缀完全匹配。

本脚本只补三个 resume 无法自动完成的动作：

1. **刷新 staged 源码**。容器跑的是 `<RUN>/famou-scientist`（`PYTHONPATH`），老 Run 里
   那份是当时的快照——不含 `--no-idea-generation` 等新开关，也不含之后的全部修复。
2. **清理 evaluator channel 标记**。`evaluator_worker` 启动即读 `CLIENT_DONE.json`，
   存在就会排空退出；`task_entrypoint.sh` 等 `EVALUATOR_READY.json`，旧文件在会让它
   误判"已就绪"。不清掉 resume 必然失败。
3. **重放已实现过的 Idea**。`requeue_for_resume` 只处理 `not_executed`；当时已经跑过的
   rank 1 队列条目是 `finished`，不会被重排，需要以新条目重新入队才能在同等条件下再跑一次。

## 边界

- 不改任何已有 attempt、分数或 judge 产物；新产物一律追加。
- 不重新 seed 跨任务经验快照——保留原 Run 当时读到的那一份，维持条件一致。
- 不改 Idea 正文：title / hypothesis / method / rationale / implementation_plan /
  resource_request / expected_return / risks 全部逐字保留，任何改写都会毁掉比较。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from famou_scientist.loop.storage.queues import JsonlQueue  # noqa: E402
from famou_scientist.loop.utils import new_id, now_ms  # noqa: E402

from prepare_run import (  # noqa: E402
    _ignore_repository_files,
    _ignore_trusted_repository_files,
    _set_tree_mode,
    _set_tree_owner,
    _stage_claude_settings,
    _stage_judge_settings,
)


CHANNEL_MARKERS = ("CLIENT_DONE.json", "EVALUATOR_DONE.json", "EVALUATOR_READY.json")


def restage_credentials(
    run_dir: Path,
    settings_source: Path,
    *,
    agent_uid: int,
    agent_gid: int,
    stage_judge: bool,
    dry_run: bool,
) -> list[str]:
    """重新写入 Agent 与 Judge 凭据。

    ``task_entrypoint.sh`` 的 EXIT trap 会 ``rm -f agent_home/.claude/settings.json``
    ——凭据用完即焚。原 Run 结束时已经删掉，resume 跳过了 ``prepare_run.py`` 就没人
    写回去，Agent 一启动就是 ``Not logged in · Please run /login``，5 个 attempt
    在 2 分钟内全部 ``agent_api_error``（试水第一次即命中）。

    Judge 凭据（``trusted/judge_settings.json``）虽然没被删，但那是原 Run 当时的
    token，可能已轮换，一并刷新。
    """

    actions: list[str] = []
    if not settings_source.is_file():
        raise FileNotFoundError(f"settings source not found: {settings_source}")
    actions.append(f"restage agent settings: {run_dir / 'agent_home/.claude/settings.json'}")
    if not dry_run:
        _stage_claude_settings(
            settings_source, run_dir, agent_uid=agent_uid, agent_gid=agent_gid
        )
        # 必须紧跟属主/权限修正。_stage_claude_settings 以宿主 root 身份写出
        # mode=0600、uid=0 的文件，Agent 以 uid 10001 运行时读不到——试水第二次
        # 仍然是 "Not logged in"，就是漏了这一步。prepare_run.py 首次 staging 时
        # 在末尾对整个 agent_home 统一做，resume 路径必须自己补。
        #
        # 但**只能修 .claude 这一支**：resume 时 agent_home 已经累积了上一轮的
        # HuggingFace 缓存，而 HF hub 用 snapshots/ → blobs/ 的符号链接，
        # _set_tree_mode 有一条"拒绝符号链接"的安全守卫会直接抛错。
        # 那条守卫是对的，不能为了走通 resume 去放宽它——我们本来也只写了一个文件。
        claude_dir = run_dir / "agent_home" / ".claude"
        owner_isolated = _set_tree_owner(claude_dir, uid=agent_uid, gid=agent_gid)
        _set_tree_mode(
            claude_dir,
            # CFS 不支持 chown 时退回到组外可读，与首次 staging 同口径。
            directory_mode=0o700 if owner_isolated else 0o707,
            file_mode=0o600 if owner_isolated else 0o606,
        )
        actions.append(
            f"chown/chmod {claude_dir.name} (owner_isolated={owner_isolated})"
        )
    if stage_judge:
        trusted = run_dir / "trusted" / "judge_settings.json"
        actions.append(f"restage judge settings: {trusted}")
        if not dry_run:
            _stage_judge_settings(settings_source, trusted)
    return actions


def refresh_staged_source(run_dir: Path, famou_source: Path, *, dry_run: bool) -> list[str]:
    """把 Run 里 staged 的 Famou 源码换成当前仓库版本。

    公开侧与可信侧用各自的忽略规则：可信侧保留 evaluator 实现，公开侧不保留
    （与 ``prepare_run.py`` 首次 staging 的口径一致，不能在 resume 时放宽）。
    """

    actions: list[str] = []
    targets = [
        (run_dir / "famou-scientist" / "famou_scientist", _ignore_repository_files),
        (
            run_dir / "trusted" / "famou-scientist" / "famou_scientist",
            _ignore_trusted_repository_files,
        ),
    ]
    source = famou_source / "famou_scientist"
    if not source.is_dir():
        raise FileNotFoundError(f"famou source not found: {source}")
    for destination, ignore in targets:
        if not destination.parent.is_dir():
            actions.append(f"skip (no staged tree): {destination}")
            continue
        actions.append(f"refresh: {destination}")
        if dry_run:
            continue
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False, ignore=ignore)
    return actions


def clear_channel_markers(run_dir: Path, *, dry_run: bool) -> list[str]:
    """删除上一轮留下的通道完成标记。

    只删标记文件。``public_key.pem`` 与 ``requests/`` / ``responses/`` 必须保留：
    密钥对的私钥在 trusted 侧，重新生成会让已落盘的响应无法验签。
    """

    channel = run_dir / "controller" / "evaluator_channel"
    actions: list[str] = []
    for name in CHANNEL_MARKERS:
        path = channel / name
        if not path.is_file():
            continue
        actions.append(f"remove: {path}")
        if not dry_run:
            path.unlink()
    return actions


def _ranking(run_dir: Path) -> list[dict[str, Any]]:
    """读取该 Run 的冲刺期排序结果，按 rank 升序。"""

    artifacts = sorted((run_dir / "artifacts" / "idea_ranking").glob("*.json"))
    if not artifacts:
        return []
    # 冲刺期排序只触发一次；多份产物时取最新的一份。
    try:
        payload = json.loads(artifacts[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = [e for e in (payload.get("ranking") or []) if e.get("idea_id")]
    entries.sort(key=lambda e: int(e.get("rank") or 999))
    return entries


def _queue_items(run_dir: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """按 payload 里的 Idea id 索引 benchmark_attempt 队列条目。"""

    out: dict[str, tuple[Path, dict[str, Any]]] = {}
    items_dir = run_dir / "queues" / "benchmark_attempt_queue_items"
    for path in sorted(items_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = item.get("payload")
        if isinstance(payload, dict) and payload.get("id"):
            out[str(payload["id"])] = (path, item)
    return out


def reset_run_state(run_dir: Path, *, dry_run: bool) -> list[str]:
    """把 ResearchState 复位到"墙钟耗尽"，让 resume_task() 愿意重开。

    ``resume_task()`` 只在 ``termination_reason == "wall_time_budget_exhausted"``
    （或 COMPLETED 且仍有可恢复工作）时动作，而它是唯一会重置
    ``active_run_started_at`` 的地方——不重置墙钟起点，新一轮一启动就判定超时。

    一次失败的 resume 会把状态留在 ``running`` / ``termination_reason=None``，
    此后再也 resume 不了。这个函数让整套流程可重复执行。
    原状态先备份到 ``controller/research_state.pre_resume_<ts>.yaml``，不丢证据。
    """

    path = run_dir / "research_state.yaml"
    state = json.loads(path.read_text(encoding="utf-8"))
    research = state.setdefault("research_state", {})
    actions = [
        f"reset run state: status={research.get('status')} -> stopped, "
        f"termination_reason={research.get('termination_reason')} -> wall_time_budget_exhausted"
    ]
    if dry_run:
        return actions
    backup = run_dir / "controller" / f"research_state.pre_resume_{now_ms()}.yaml"
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    actions.append(f"backup: {backup}")
    research["status"] = "stopped"
    research["termination_reason"] = "wall_time_budget_exhausted"
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return actions


def replay_ranked_ideas(run_dir: Path, *, dry_run: bool) -> list[str]:
    """把**全部**被排序的 Idea 各重新入队一条。

    不依赖 ``requeue_for_resume`` 挑 ``not_executed``：它按 reason 前缀重排，会把
    与本实验无关的条目一并捞回（试水那次多捞了 1 条），而已实现过的 rank 1
    又不在它的处理范围内。统一新建条目，三条 Idea 因此获得完全对等的处理。

    先撤掉上一轮遗留的重放条目，使本函数可重复执行而不会累积。
    """

    actions: list[str] = []
    entries = _ranking(run_dir)
    if not entries:
        actions.append(f"no idea_ranking artifact: {run_dir.name}")
        return actions

    items_dir = run_dir / "queues" / "benchmark_attempt_queue_items"
    for path in sorted(items_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = item.get("payload")
        if isinstance(payload, dict) and payload.get("replay_of_idea_id"):
            actions.append(f"drop stale replay: {path.name}")
            if not dry_run:
                path.unlink()

    # 取消其余一切"可执行"条目。
    #
    # 不变量：resume 准备完成后，benchmark_attempt 队列里唯一可执行的就是这 N 条
    # 重放。否则会同时跑三类东西——重放、resume_task 从 not_executed 重排回来的
    # 旧条目、以及上一轮遗留的 queued/running。实测某个 Run 里 3 条被排序 Idea
    # 对应出 6 个队列条目，而真正在跑的 3 个 attempt 既不是重放、也不是被排序的
    # Idea，测量对象完全跑偏。
    #
    # 只盯 not_executed 不够：它们可能已被上一轮 resume 改成 queued。
    # 改成 cancelled 而不是删除，保留可追溯性。
    active = {"queued", "leased", "waiting_resources", "running", "not_executed"}
    cancelled = 0
    for path in sorted(items_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(item.get("status")) not in active:
            continue
        payload = item.get("payload")
        if isinstance(payload, dict) and payload.get("replay_of_idea_id"):
            continue  # 本轮重放，稍后会被整体撤换重建
        item["status"] = "cancelled"
        item["cancel_reason"] = "superseded_by_rank_replay"
        cancelled += 1
        if not dry_run:
            path.write_text(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    if cancelled:
        actions.append(f"cancel {cancelled} 个非重放的可执行条目（只留重放）")

    items = _queue_items(run_dir)
    queue = JsonlQueue(run_dir, "benchmark_attempt_queue")
    for entry in entries:
        idea_id = str(entry["idea_id"])
        rank = int(entry.get("rank") or 0)
        found = items.get(idea_id)
        if found is None:
            actions.append(f"MISSING idea payload rank={rank} {idea_id}")
            continue
        _, item = found
        payload = dict(item.get("payload") or {})
        replay = dict(payload)
        # 换新 id：沿用原 id 会让 ExpBank 的 lineage 与已有 attempt 相撞，
        # 事后分不清哪条 attempt 属于重放。正文其余部分逐字不动。
        replay["id"] = new_id("idea")
        replay["replay_of_idea_id"] = idea_id
        replay["judge_rank"] = rank
        replay["status"] = "proposed"
        actions.append(
            f"replay rank={rank} {idea_id} -> {replay['id']}"
            f"  «{str(payload.get('title'))[:56]}»"
        )
        if not dry_run:
            queue.push(replay, item_type="benchmark_attempt", priority=1)
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--famou-source", type=Path, required=True)
    parser.add_argument(
        "--claude-settings",
        type=Path,
        help="Agent/Judge 凭据来源；entrypoint 的 EXIT trap 会删掉上一轮的凭据，resume 必须重写",
    )
    parser.add_argument("--agent-uid", type=int, default=10001)
    parser.add_argument("--agent-gid", type=int, default=10001)
    parser.add_argument(
        "--no-judge-settings",
        action="store_true",
        help="不刷新 trusted/judge_settings.json（合规判定关闭时使用）",
    )
    parser.add_argument(
        "--skip-source-refresh",
        action="store_true",
        help="不刷新 staged 源码（仅当已确认该 Run 的源码已是当前版本时使用）",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2

    actions: list[str] = []
    if args.claude_settings is not None:
        actions += restage_credentials(
            run_dir,
            args.claude_settings.expanduser().resolve(),
            agent_uid=args.agent_uid,
            agent_gid=args.agent_gid,
            stage_judge=not args.no_judge_settings,
            dry_run=args.dry_run,
        )
    if not args.skip_source_refresh:
        actions += refresh_staged_source(
            run_dir, args.famou_source.expanduser().resolve(), dry_run=args.dry_run
        )
    actions += clear_channel_markers(run_dir, dry_run=args.dry_run)
    actions += reset_run_state(run_dir, dry_run=args.dry_run)
    actions += replay_ranked_ideas(run_dir, dry_run=args.dry_run)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{run_dir.name}")
    for line in actions:
        print(f"  {prefix}{line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
