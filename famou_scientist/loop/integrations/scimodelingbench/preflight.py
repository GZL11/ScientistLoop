"""Trusted SciModelingBench dataset preflight for worker containers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .evaluator_worker import _load_task
from .task_catalog import DEFAULT_HF_REVISION


def preflight_task(
    *,
    task_id: str,
    revision: str,
    cache_dir: str | Path,
) -> dict[str, Any]:
    """Load the task and materialize its input in the evaluator environment."""

    task = _load_task(
        task_id,
        revision=revision,
        loader=None,
        cache_dir=cache_dir,
    )
    bundle = task.build_input()
    manifest = getattr(bundle, "manifest", None)
    views = getattr(manifest, "views", ()) if manifest is not None else ()
    return {
        "task_id": task_id,
        "revision": revision,
        "cache_dir": str(Path(cache_dir).expanduser().resolve()),
        "loaded_task": type(task).__name__,
        "view_count": len(tuple(views)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--cache-dir", required=True)
    args = parser.parse_args(argv)
    result = preflight_task(
        task_id=args.task_id,
        revision=args.revision,
        cache_dir=args.cache_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
