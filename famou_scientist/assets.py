# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""Asset registry CLI for prompts, skills, tools, plugins, and future MCP entries.

The CLI inspects the local asset registry and validates version metadata. The
private admin UI can publish versions by copying a version snapshot to its
target file; runtime loading remains controlled by files under ``assets/opencode``.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

from . import launcher

__all__ = ["main", "registry_path", "load_registry"]

CATEGORIES = ("prompts", "skills", "tools", "plugins", "runtime_patches", "mcp")
PATH_KEYS = (
    "target",
    "active",
    "baseline",
    "manifest",
    "changelog",
    "path",
    "runtime_path",
    "versions_dir",
    "files_dir",
    "release_log",
)


def registry_path() -> Path:
    """Return the bundled asset registry path."""
    return launcher.opencode_config_dir() / "registry" / "registry.json"


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load registry JSON."""
    p = path or registry_path()
    return json.loads(p.read_text(encoding="utf-8"))


def _root(registry: dict[str, Any]) -> Path:
    raw = registry.get("root") or ".."
    return (registry_path().parent / str(raw)).resolve()


def _entries(registry: dict[str, Any], category: str) -> list[dict[str, Any]]:
    if category not in CATEGORIES:
        raise KeyError(f"unknown category: {category}")
    return list(registry.get(category) or [])


def _find(registry: dict[str, Any], ref: str) -> tuple[str, dict[str, Any]]:
    if "/" in ref:
        category, item_id = ref.split("/", 1)
        for item in _entries(registry, category):
            if item.get("id") == item_id:
                return category, item
        raise KeyError(f"asset not found: {ref}")

    matches: list[tuple[str, dict[str, Any]]] = []
    for category in CATEGORIES:
        for item in _entries(registry, category):
            if item.get("id") == ref:
                matches.append((category, item))
    if not matches:
        raise KeyError(f"asset not found: {ref}")
    if len(matches) > 1:
        cats = ", ".join(f"{c}/{i.get('id')}" for c, i in matches)
        raise KeyError(f"ambiguous asset id {ref!r}; use one of: {cats}")
    return matches[0]


def _resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else root / p


def _version_entries(root: Path, item: dict[str, Any]) -> list[dict[str, Any]]:
    versions_dir = _resolve(root, item.get("versions_dir"))
    if not versions_dir or not versions_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(versions_dir.glob("*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _version_by_id(root: Path, item: dict[str, Any], version: str | None) -> dict[str, Any] | None:
    if not version:
        return None
    for v in _version_entries(root, item):
        if v.get("version") == version:
            return v
    return None


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry()
    cats = [args.category] if args.category else CATEGORIES
    for category in cats:
        entries = _entries(registry, category)
        print(f"[{category}] {len(entries)}")
        for item in entries:
            status = "enabled" if item.get("enabled", True) else "disabled"
            path = item.get("target") or item.get("path") or ""
            version = item.get("online_version")
            version_text = f" online={version}" if version else ""
            print(f"  - {item.get('id')} ({status}) {path}{version_text}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    registry = load_registry()
    category, item = _find(registry, args.asset)
    root = _root(registry)
    data = {"category": category, **item}
    for key in PATH_KEYS:
        if key in data:
            resolved = _resolve(root, data.get(key))
            data[key + "_abs"] = str(resolved) if resolved else None
    if item.get("online_version"):
        data["versions"] = _version_entries(root, item)
    _print_json(data)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    registry = load_registry()
    root = _root(registry)
    errors: list[str] = []
    warnings: list[str] = []

    for category in CATEGORIES:
        for item in _entries(registry, category):
            item_id = item.get("id", "<missing-id>")
            for key in PATH_KEYS:
                if key not in item:
                    continue
                p = _resolve(root, item.get(key))
                if p and not p.exists():
                    errors.append(f"{category}/{item_id}: missing {key}: {p}")
            online = item.get("online_version")
            if online:
                version = _version_by_id(root, item, online)
                if not version:
                    errors.append(f"{category}/{item_id}: missing online_version metadata: {online}")
                else:
                    src = _resolve(root, version.get("source_file"))
                    if not src or not src.exists():
                        errors.append(f"{category}/{item_id}: missing online version source_file: {version.get('source_file')}")
            for test in item.get("tests") or []:
                p = _resolve(root, test)
                if p and not p.exists():
                    errors.append(f"{category}/{item_id}: missing test: {p}")
            runtime = item.get("runtime_path")
            if runtime and item.get("enabled", True):
                p = _resolve(root, runtime)
                if not p or not p.exists():
                    errors.append(f"{category}/{item_id}: enabled but runtime missing: {runtime}")
            glob_pat = item.get("glob")
            if glob_pat:
                matches = list(root.glob(glob_pat))
                if not matches:
                    errors.append(f"{category}/{item_id}: glob matched nothing: {glob_pat}")
                else:
                    warnings.append(f"{category}/{item_id}: glob matched {len(matches)} files")

    if warnings and args.verbose:
        for w in warnings:
            print(f"WARN {w}")
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 1
    print("asset registry check passed")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    registry = load_registry()
    _, item = _find(registry, args.asset)
    root = _root(registry)
    online_version = _version_by_id(root, item, item.get("online_version"))
    online_source = online_version.get("source_file") if online_version else None
    left = _resolve(root, args.left or item.get("baseline") or online_source)
    right = _resolve(root, args.right or item.get("target") or item.get("active"))
    if left is None or right is None:
        print("diff needs --left/--right or registry baseline/target", file=sys.stderr)
        return 2
    if not left.exists() or not right.exists():
        print(f"diff file missing: {left} or {right}", file=sys.stderr)
        return 1

    left_lines = left.read_text(encoding="utf-8").splitlines(keepends=True)
    right_lines = right.read_text(encoding="utf-8").splitlines(keepends=True)
    for line in difflib.unified_diff(left_lines, right_lines, fromfile=str(left), tofile=str(right)):
        print(line, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="famou-scientist assets",
        description="Inspect the Famou prompt/skill/tool/plugin asset registry.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List registered assets")
    p_list.add_argument("category", nargs="?", choices=CATEGORIES)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one asset by id or category/id")
    p_show.add_argument("asset")
    p_show.set_defaults(func=cmd_show)

    p_check = sub.add_parser("check", help="Validate registry paths")
    p_check.add_argument("-v", "--verbose", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_diff = sub.add_parser("diff", help="Unified diff for a registered asset")
    p_diff.add_argument("asset")
    p_diff.add_argument("--left", help="Left file path relative to assets/opencode")
    p_diff.add_argument("--right", help="Right file path relative to assets/opencode")
    p_diff.set_defaults(func=cmd_diff)

    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyError as exc:
        print(str(exc).strip("'"), file=sys.stderr)
        return 2
