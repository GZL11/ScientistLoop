#!/usr/bin/env python3
"""Prepare an isolated SciModelingBench fm-job run directory."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from famou_scientist.loop.integrations.scimodelingbench.prepare_problem import (
    prepare_task_problem,
)
from famou_scientist.loop.integrations.scimodelingbench.task_catalog import (
    DEFAULT_HF_REVISION,
)

_ALLOWED_CLAUDE_ENV_NAMES = {"API_TIMEOUT_MS"}
_ALLOWED_CLAUDE_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_")


def _set_tree_mode(root: Path, *, directory_mode: int, file_mode: int) -> None:
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError(f"permission tree root must be a real directory: {root}")
    root.chmod(directory_mode)
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"permission tree contains symlink: {path}")
        path.chmod(directory_mode if path.is_dir() else file_mode)


def _filtered_claude_settings_env(source: Path) -> dict[str, str]:
    """Keep only Claude CLI credentials and runtime settings needed by the Agent."""
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"Claude settings not found: {source}")
    raw = json.loads(source.read_text(encoding="utf-8"))
    source_env = raw.get("env") if isinstance(raw, dict) else None
    if not isinstance(source_env, dict):
        raise ValueError(f"Claude settings contains no env mapping: {source}")
    allowed_env = {
        str(key): str(value)
        for key, value in source_env.items()
        if isinstance(key, str)
        and isinstance(value, str)
        and (
            key in _ALLOWED_CLAUDE_ENV_NAMES
            or key.startswith(_ALLOWED_CLAUDE_ENV_PREFIXES)
        )
    }
    if not allowed_env:
        raise ValueError(f"Claude settings contains no supported credentials: {source}")
    return allowed_env


def _write_claude_settings(destination: Path, allowed_env: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"env": allowed_env}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    destination.chmod(0o600)


def _stage_claude_settings(source: Path, run_dir: Path) -> None:
    """Persist a filtered copy for resume and stage the initial Agent HOME copy."""
    allowed_env = _filtered_claude_settings_env(source)
    _write_claude_settings(run_dir / "trusted" / "claude_settings.json", allowed_env)
    _write_claude_settings(
        run_dir / "agent_home" / ".claude" / "settings.json", allowed_env
    )


def _chown_tree(root: Path, *, uid: int, gid: int) -> None:
    if hasattr(os, "chown"):
        os.chown(root, uid, gid)
        for path in root.rglob("*"):
            if not path.is_symlink():
                os.chown(path, uid, gid)


@contextmanager
def _online_hf_env(cache_dir: Path):
    """Use the submitted proxy/cache during trusted dataset preparation."""

    previous = {
        "HF_HOME": os.environ.get("HF_HOME"),
        "HF_DATASETS_CACHE": os.environ.get("HF_DATASETS_CACHE"),
        "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
        "HF_DATASETS_OFFLINE": os.environ.get("HF_DATASETS_OFFLINE"),
        "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
    }
    os.environ["HF_HOME"] = str(cache_dir)
    os.environ["HF_DATASETS_CACHE"] = str(cache_dir / "datasets")
    for key in ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _seed_cache(cache_dir: Path, seed_dir: Path | None) -> None:
    if seed_dir is None or not seed_dir.is_dir():
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    for item in seed_dir.iterdir():
        target = cache_dir / item.name
        if target.exists():
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target)


def prepare_run(
    *,
    task_id: str,
    famou_source: Path,
    run_dir: Path,
    cache_dir: Path,
    revision: str,
    agent_uid: int,
    agent_gid: int,
    claude_settings: Path | None = None,
    cache_seed_dir: Path | None = None,
    overwrite_problem: bool = False,
) -> dict[str, Any]:
    """Prepare public, trusted, and channel directories for one fm-job."""

    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    trusted_dir = run_dir / "trusted"
    channel_dir = run_dir / "controller" / "evaluator_channel"
    problem_dir = run_dir / "problem"
    agent_home = run_dir / "agent_home"
    for directory in (
        run_dir,
        run_dir / "workspace",
        run_dir / "results",
        run_dir / "controller",
        channel_dir / "requests",
        channel_dir / "responses",
        trusted_dir / "logs",
        agent_home,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    _seed_cache(cache_dir, cache_seed_dir)

    with _online_hf_env(cache_dir):
        prepare_report = prepare_task_problem(
            task_id=task_id,
            problem_dir=problem_dir,
            revision=revision,
            cache_dir=cache_dir,
            overwrite=overwrite_problem,
        )
    if claude_settings is not None:
        _stage_claude_settings(claude_settings, run_dir)

    _set_tree_mode(problem_dir, directory_mode=0o555, file_mode=0o444)
    _chown_tree(agent_home, uid=agent_uid, gid=agent_gid)
    _set_tree_mode(agent_home, directory_mode=0o700, file_mode=0o600)
    trusted_dir.chmod(0o700)
    (trusted_dir / "logs").chmod(0o700)
    channel_dir.chmod(0o755)

    staging = {
        "schema_version": 1,
        "benchmark": "scimodelingbench",
        "task_id": task_id,
        "run_dir": str(run_dir),
        "problem_dir": str(problem_dir),
        "workspace_dir": str(run_dir / "workspace"),
        "channel_dir": str(channel_dir),
        "trusted_dir": str(trusted_dir),
        "trusted_cache_dir": str(cache_dir),
        "revision": revision,
        "agent_uid": agent_uid,
        "agent_gid": agent_gid,
        "prepare_report": prepare_report,
    }
    (run_dir / "controller" / "staging.json").write_text(
        json.dumps(staging, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return staging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--famou-source", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--cache-seed-dir")
    parser.add_argument("--revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--agent-uid", type=int, default=10001)
    parser.add_argument("--agent-gid", type=int, default=10001)
    parser.add_argument("--claude-settings")
    parser.add_argument("--overwrite-problem", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    staging = prepare_run(
        task_id=args.task_id,
        famou_source=Path(args.famou_source).expanduser().resolve(),
        run_dir=Path(args.run_dir).expanduser().resolve(),
        cache_dir=Path(args.cache_dir).expanduser().resolve(),
        cache_seed_dir=(
            Path(args.cache_seed_dir).expanduser().resolve()
            if args.cache_seed_dir
            else (
                Path(seed).expanduser().resolve()
                if (seed := os.environ.get("SCIMODELINGBENCH_CACHE_SEED_DIR"))
                else None
            )
        ),
        revision=args.revision,
        agent_uid=args.agent_uid,
        agent_gid=args.agent_gid,
        claude_settings=(
            Path(args.claude_settings).expanduser().resolve()
            if args.claude_settings
            else None
        ),
        overwrite_problem=args.overwrite_problem,
    )
    print(json.dumps(staging, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
