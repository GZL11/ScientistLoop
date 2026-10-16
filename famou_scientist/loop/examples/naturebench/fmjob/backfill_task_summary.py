"""给存量跨任务经验补 ``task_summary``，并按需重建 Agent 目录。

``task_summary`` 是目录里唯一能让 Idea Agent 判断「这条经验和我的任务像不像」
的字段。Loop 侧直到 2026-09-09 才开始写它，此前 232 条系统记录全部为空——实测
Agent 拿到的同领域 20 条因此完全无法区分，只能盲开 Markdown（20 个 run 打开
148 篇，其中有内容的 12 篇）。

新写入的 run 由 ``Orchestrator._base_experience_summary`` 负责；本脚本只处理存量：
从系统记录的 ``source_run_dir`` 找到该 run 的公开题面，用与 Loop 侧同一个解析函数
（``storage.cross_task_expbank.public_task_summary``）算出摘要写回系统层，再重建
Agent 目录。

只读公开题面（``problem/README.md``）。隐藏测试、GT 与私有 evaluator 一律不碰。

    python -m famou_scientist.loop.examples.naturebench.fmjob.backfill_task_summary \
        --bank-root .famou/cross_task_expbank [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from famou_scientist.loop.storage.cross_task_expbank import (
    CrossTaskExpBank,
    public_task_summary,
)


def _public_dir(record: dict[str, object]) -> Path | None:
    """定位该 run 的公开题面目录。

    ``source_run_dir`` 是宿主机上的 run 根目录，题面固定 stage 在 ``problem/``。
    run 目录可能已被归档/删除，这时只能跳过。
    """

    source = record.get("source_run_dir")
    if not isinstance(source, str) or not source.strip():
        return None
    problem = Path(source) / "problem"
    return problem if problem.is_dir() else None


def backfill(bank_root: Path, *, dry_run: bool = False) -> dict[str, int]:
    bank = CrossTaskExpBank(bank_root)
    records = bank.records()
    stats = {
        "records": len(records),
        "already_present": 0,
        "filled": 0,
        "no_run_dir": 0,
        "no_summary": 0,
    }
    updated: list[dict[str, object]] = []
    for record in records:
        if str(record.get("task_summary") or "").strip():
            stats["already_present"] += 1
            updated.append(record)
            continue
        public_dir = _public_dir(record)
        if public_dir is None:
            stats["no_run_dir"] += 1
            updated.append(record)
            continue
        summary = public_task_summary(public_dir)
        if not summary:
            stats["no_summary"] += 1
            updated.append(record)
            continue
        record = {**record, "task_summary": summary}
        stats["filled"] += 1
        updated.append(record)

    if dry_run:
        return stats

    bank.system_index_path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in updated
        ),
        encoding="utf-8",
    )
    stats["catalog_entries"] = bank.rebuild_catalog()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    stats = backfill(args.bank_root.expanduser().resolve(), dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
