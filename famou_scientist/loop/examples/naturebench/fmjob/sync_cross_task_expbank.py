"""Merge NatureBench Run outboxes into the project cross-task ExpBank.

The fm-job mounts a Run directory, so publishing directly to the project root
from inside a task is not reliable. This small host-side step merges completed
Run records and can seed a new Run with the current public snapshot.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# This file is also invoked directly by submit_one_click.sh, where Python's
# import path starts at the fmjob directory rather than the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from famou_scientist.loop.storage.cross_task_expbank import CrossTaskExpBank
from famou_scientist.loop.utils import safe_name


def _read_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _judge_model(verdict: dict[str, object]) -> str | None:
    """Return the model that produced a validity verdict, if recorded."""

    for source in (verdict, verdict.get("extra")):
        if isinstance(source, dict):
            value = source.get("model") or source.get("judge_model")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _resolve_verdict(run_dir: Path) -> dict[str, object] | None:
    """解析该 Run 的最终 validity verdict。

    容器内 judge 可能因缺凭据写出 is_valid=null 的占位结论，事后补判则写在
    controller/naturebench_judge/<batch>/judge_verdict.json（刻意不覆盖原文件，
    以保留原始证据）。只读 controller/judge_verdict.json 会永远看到 null，
    使补判过的 Run 也无法回流经验——按 mtime 取最新的确定性结论。
    """

    candidates: list[tuple[float, dict[str, object]]] = []
    judge_dir = run_dir / "controller" / "naturebench_judge"
    if judge_dir.is_dir():
        for path in judge_dir.glob("*/judge_verdict.json"):
            value = _read_object(path)
            if value is None:
                continue
            decided = value.get("is_valid")
            if decided is None:
                decided = value.get("valid")
            if isinstance(decided, bool):
                try:
                    candidates.append((path.stat().st_mtime, value))
                except OSError:
                    continue
    if candidates:
        # 目录名不可按字典序比较：gpt-5.5-formal-rejudge-20260820 会排在
        # gpt-5.5-rejudge-20260819 之前。
        return max(candidates, key=lambda item: item[0])[1]
    return _read_object(run_dir / "controller" / "judge_verdict.json")


def _carry_over_backfilled_fields(
    record: dict[str, object],
    existing: dict[str, object] | None,
) -> dict[str, object]:
    """合并时不要用「outbox 里没有」擦掉「库里已经有」的字段。

    ``upsert_summary`` 是整条替换，而 outbox 是 run 结束那一刻写的快照。有些字段
    是事后回填进库的（``task_summary`` 由 ``backfill_task_summary.py`` 从各 run 的
    公开题面算出来），旧 run 的 outbox 里根本没有这个键——于是每次合并都会把
    回填结果冲掉一批。实测一次：184 条里 57 条的 ``task_summary`` 被擦回 null。
    """

    if not existing:
        return record
    merged = dict(record)
    for key in ("task_summary",):
        if not str(merged.get(key) or "").strip():
            value = existing.get(key)
            if str(value or "").strip():
                merged[key] = value
    return merged


def merge_outboxes(runs_root: Path, bank_root: Path) -> int:
    bank = CrossTaskExpBank(bank_root)
    bank.rebuild_catalog()
    existing = {
        str(item.get("experience_id")): item
        for item in bank.records()
        if item.get("experience_id")
    }
    merged = 0
    for path in sorted(runs_root.glob("*/controller/cross_task_experience_record.json")):
        record = _read_object(path)
        if not record:
            continue
        # The worker may have seen a container-specific mount path. Resolve
        # system-only output locations from the host-side outbox location.
        run_dir = path.parent.parent.resolve()
        record["source_run_dir"] = str(run_dir)
        record["task_output_dir"] = str(run_dir / "workspace" / "output")
        verdict = _resolve_verdict(run_dir)
        if verdict is not None:
            is_valid = verdict.get("is_valid")
            if is_valid is None:
                is_valid = verdict.get("valid")
            record["judge_verdict"] = (
                "valid" if is_valid is True else "invalid" if is_valid is False else None
            )
            model = _judge_model(verdict)
            if model:
                record["judge_model"] = model
        task_id = str(record.get("task_id") or record.get("goal_id") or "").strip()
        run_id = str(record.get("run_id") or "").strip()
        record = _carry_over_backfilled_fields(
            record, existing.get(safe_name(f"{task_id}--{run_id}"))
        )
        bank.upsert_summary(record)
        merged += 1
    return merged


def _record_judge_metadata(record: dict[str, object]) -> dict[str, object]:
    """Fill metadata for legacy system records written before ``judge_model``."""

    if record.get("judge_model"):
        return record
    source_run_dir = record.get("source_run_dir")
    if not isinstance(source_run_dir, str) or not source_run_dir.strip():
        return record
    verdict = _read_object(Path(source_run_dir) / "controller" / "judge_verdict.json")
    if verdict is None:
        return record
    model = _judge_model(verdict)
    if model:
        record = dict(record)
        record["judge_model"] = model
    return record


def _write_seed_manifest(
    run_dir: Path,
    *,
    source: Path,
    kept: list[dict[str, object]],
    exclude_task_id: str | None,
    only_task_id: str | None,
    judge_model: str | None,
    empty: bool,
) -> dict[str, int]:
    """把「这个 Run 实际拿到了多少条经验」写成清单，放在快照目录**外**。

    2026-09-06 的 A/B 事后才发现处理臂剂量接近零：cellular_omics 的 4 个 run 在
    Idea Agent 能看到的 20 条窗口里，有内容的条目是 0 条——开跑前没有任何一处
    记录过剂量，只能靠事后翻 220 个 agent trajectory 才算出来。

    清单写在 `shared_experience_pool/` 下、快照目录之外，避免进入 Agent 可读的
    经验目录（Agent 不需要知道自己被发了多少条）。
    """

    by_domain: dict[str, int] = {}
    for item in kept:
        domain = str(item.get("domain") or "unknown")
        by_domain[domain] = by_domain.get(domain, 0) + 1
    manifest = {
        "published": len(kept),
        "empty_arm": bool(empty),
        "by_domain": dict(sorted(by_domain.items())),
        "excluded_task_id": exclude_task_id,
        "included_task_id": only_task_id,
        "judge_model": judge_model,
        "seeded_from": str(source),
    }
    path = run_dir / "shared_experience_pool" / "cross_task_expbank_seed_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return by_domain


def _assert_task_excluded(target: Path, exclude_task_id: str | None) -> None:
    """seed 完成后强断言：快照里不能残留本任务自己的经验。

    自任务屏蔽是整条链路上**唯一不能交给 Agent 自觉遵守**的约束——读到自己上一次
    的解法，这个 run 就不再是独立的一次搜索。而它靠两步保证：从索引里删条目、
    并物理删除对应的 ``.md``（防止 Agent 绕过索引直接 ``ls``）。两步任何一步漏掉
    都不会报错，只会安静地泄漏，所以这里落一道断言。

    单个任务在库里可能有多条（同题跑过多次，实测最多 7 条），按 ``task_id`` 前缀
    统一检查，避免只删掉一条就以为干净了。
    """

    if not exclude_task_id:
        return
    index_path = target / "index.jsonl"
    leaked_index = [
        line
        for line in (
            index_path.read_text(encoding="utf-8").splitlines()
            if index_path.is_file()
            else []
        )
        if f'/{exclude_task_id}--' in line
    ]
    leaked_files = [
        path.name
        for path in target.glob("*/**/*.md")
        if path.name.startswith(f"{exclude_task_id}--")
    ]
    if leaked_index or leaked_files:
        raise RuntimeError(
            "自任务经验未被完全剔除："
            f"索引残留 {len(leaked_index)} 条、磁盘残留 {leaked_files}"
        )


def _assert_only_task_included(target: Path, only_task_id: str | None) -> None:
    """``--only-task-id`` 的镜像断言：快照里不能混进别的任务。

    同任务自身经验 A/B（`20260911-selftask-expbank-ab-15x3`）的处理臂要求快照
    **只**含本任务自己的历史复盘。混进一条别的任务，这条臂就同时含有自身经验
    和跨任务经验，两个变量搅在一起，整个批次作废。

    不能指望 ``_assert_task_excluded`` 兜底：它在参数为空时静默返回，而
    ``--only-task-id`` 与 ``--exclude-task-id`` 互斥，走 only 分支时前者拿不到
    值。检查维度与排除侧对称——索引与磁盘各查一遍，因为 Agent 可以绕过索引
    直接 ``ls`` 领域目录。
    """

    if not only_task_id:
        return
    index_path = target / "index.jsonl"
    foreign_index = [
        line
        for line in (
            index_path.read_text(encoding="utf-8").splitlines()
            if index_path.is_file()
            else []
        )
        if line.strip() and f'/{only_task_id}--' not in line
    ]
    foreign_files = [
        path.name
        for path in target.glob("*/**/*.md")
        if not path.name.startswith(f"{only_task_id}--")
    ]
    if foreign_index or foreign_files:
        raise RuntimeError(
            "自任务快照里混进了其他任务："
            f"索引残留 {len(foreign_index)} 条、磁盘残留 {foreign_files[:10]}"
        )


def seed_run(
    bank_root: Path,
    run_dir: Path,
    *,
    exclude_task_id: str | None = None,
    only_task_id: str | None = None,
    judge_model: str | None = None,
    empty: bool = False,
) -> dict[str, int]:
    """Copy an Agent-facing projection, excluding the current task.

    The project bank remains the complete system/audit source.  A Run receives
    only the compact public catalog and Markdown files that are explicitly
    Judge Valid; when ``judge_model`` is set, the verdict must also come from
    that model (used for the GPT-5.5 trusted NatureBench view).

    ``exclude_task_id`` and ``only_task_id`` are the two mutually exclusive
    task-level filters.  The default (exclude) is the cross-task arm: the Run
    must not see its own history, or it is no longer an independent search.
    ``only_task_id`` inverts it for the same-task self-experience A/B — the Run
    sees its own previous rounds and nothing else.  Passing both is a
    programming error, not a degenerate case, so it raises.

    ``empty`` seeds a well-formed but entry-less snapshot.  This is the control
    arm of the cross-task ExpBank A/B: the directory and README still exist so
    the Run takes the same code path as the treatment arm, and only the catalog
    is empty.  Removing the directory instead would change which branch the
    orchestrator and the Idea prompt take, which is a second variable.

    Both arms also get a seed manifest (see ``_write_seed_manifest``) so the
    delivered dose is on record before the Run starts, not reconstructed from
    trajectories afterwards.
    """

    if exclude_task_id and only_task_id:
        raise ValueError(
            "--exclude-task-id 与 --only-task-id 互斥："
            f"同时收到 {exclude_task_id!r} 和 {only_task_id!r}"
        )
    source = Path(bank_root).expanduser().resolve()
    target = run_dir / "shared_experience_pool" / "cross_task_expbank"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    if empty:
        target.mkdir(parents=True)
        readme = source / "README.md"
        if readme.is_file():
            shutil.copy2(readme, target / "README.md")
        (target / "index.jsonl").write_text("", encoding="utf-8")
        _write_seed_manifest(
            run_dir,
            source=source,
            kept=[],
            exclude_task_id=exclude_task_id,
            only_task_id=only_task_id,
            judge_model=judge_model,
            empty=True,
        )
        return {"published": 0, "empty": 1}
    shutil.copytree(source, target)

    system_path = source.parent / f".{source.name}.system.jsonl"
    system_records = {}
    if system_path.is_file():
        for line in system_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("summary_path"):
                system_records[str(record["summary_path"])] = record

    index_path = target / "index.jsonl"
    kept: list[dict[str, object]] = []
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                public_record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(public_record, dict):
                continue
            system_record = _record_judge_metadata(
                dict(system_records.get(str(public_record.get("summary_path")), {}))
            )
            if str(system_record.get("judge_verdict") or "").lower() != "valid":
                continue
            # 内容闸门，与合规闸门正交。``evolution_markdown`` 只有复盘 Agent
            # 真写完才有值；兜底总结是「方法标题 + 分数」的机器罗列，离线补写
            # 的虽有该字段但同样没有 When to use / When not to use。两者对读它
            # 的 Agent 都是负价值。这一条必须与 CrossTaskExpBank.is_agent_visible
            # 保持一致——库的写入、重建、分发是三个独立关口，漏一处就白改。
            if not str(system_record.get("evolution_markdown") or "").strip():
                continue
            if system_record.get("offline_generated"):
                continue
            if judge_model and str(system_record.get("judge_model") or "") != judge_model:
                continue
            if exclude_task_id and str(system_record.get("task_id") or "") == exclude_task_id:
                continue
            if only_task_id and str(system_record.get("task_id") or "") != only_task_id:
                continue
            kept.append(public_record)
    index_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in kept),
        encoding="utf-8",
    )

    kept_paths = {str(item.get("summary_path")) for item in kept}
    for markdown in target.glob("*/**/*.md"):
        relative = markdown.relative_to(target).as_posix()
        if relative not in kept_paths:
            markdown.unlink()
    _assert_task_excluded(target, exclude_task_id)
    _assert_only_task_included(target, only_task_id)
    _write_seed_manifest(
        run_dir,
        source=source,
        kept=kept,
        exclude_task_id=exclude_task_id,
        only_task_id=only_task_id,
        judge_model=judge_model,
        empty=False,
    )
    return {"published": len(kept)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help=(
            "只 seed，不合并 outbox。合并要遍历全部 run 并对每条记录抢一次库锁，"
            "是批次级维护动作，不该挂在每次提交上——40 个并发提交会在 NFS 锁上"
            "排成车队（实测 39 个进程卡在 nfs4_retry_setlk，零 IO 进展）。"
        ),
    )
    parser.add_argument(
        "--seed-bank-root",
        type=Path,
        help=(
            "Seed the Run snapshot from this bank instead of --bank-root. "
            "Outbox merging always targets --bank-root, so a frozen snapshot "
            "passed here stays byte-stable while the project bank keeps "
            "accumulating. Required for A/B batches: without it, arms launched "
            "at different times read different banks."
        ),
    )
    parser.add_argument("--seed-run", type=Path)
    parser.add_argument("--exclude-task-id")
    parser.add_argument(
        "--only-task-id",
        help=(
            "Inverse of --exclude-task-id: keep ONLY this task's own history in "
            "the Run snapshot (same-task self-experience A/B treatment arm). "
            "Mutually exclusive with --exclude-task-id."
        ),
    )
    parser.add_argument(
        "--empty-seed",
        action="store_true",
        help="Seed an entry-less snapshot (cross-task ExpBank control arm).",
    )
    parser.add_argument(
        "--judge-model",
        help="Only expose Valid verdicts produced by this model in the Run snapshot.",
    )
    args = parser.parse_args(argv)
    if args.exclude_task_id and args.only_task_id:
        parser.error("--exclude-task-id 与 --only-task-id 互斥")
    merged = None
    if not args.skip_merge:
        if args.runs_root is None:
            parser.error("合并 outbox 需要 --runs-root（或改用 --skip-merge）")
        merged = merge_outboxes(args.runs_root.expanduser().resolve(), args.bank_root)
    seeded = None
    seed_bank_root = args.seed_bank_root or args.bank_root
    if args.seed_run is not None:
        seeded = seed_run(
            seed_bank_root,
            args.seed_run.expanduser().resolve(),
            exclude_task_id=args.exclude_task_id,
            only_task_id=args.only_task_id,
            judge_model=args.judge_model,
            empty=args.empty_seed,
        )
    print(
        json.dumps(
            {
                "merged": merged,
                "seeded": seeded,
                "bank_root": str(args.bank_root),
                "seed_bank_root": str(seed_bank_root),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
