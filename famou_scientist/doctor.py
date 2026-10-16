# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""启动前体检：确认 OpenCode、python3 就绪，软提示模型配置。

设计原则：**只检测、不代办**。模型凭证由用户自己 ``opencode auth`` 配置，
本工具不碰 key、不写 provider（开源/内部分发，凭证绝不进文件）。

体检分两级：
- **硬性**（缺则无法启动，返回非 0）：opencode 不在 PATH。
- **软性**（仅警告，不阻断）：python3 版本偏低、未发现模型 provider 配置。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

__all__ = [
    "check",
]

# OpenCode 全局配置位置（用于软性判断用户有没有配 provider）。
_GLOBAL_CONFIG_CANDIDATES = (
    Path.home() / ".config" / "opencode" / "opencode.json",
    Path.home() / ".config" / "opencode" / "opencode.jsonc",
    Path.home() / ".config" / "opencode" / "config.json",
)


def _check_opencode() -> tuple[bool, str]:
    """硬性：opencode 是否在 PATH。"""
    path = shutil.which("opencode")
    if path:
        version = ""
        try:
            r = subprocess.run(
                ["opencode", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            version = (r.stdout or r.stderr or "").strip().splitlines()[0] if r.stdout or r.stderr else ""
        except (OSError, subprocess.SubprocessError):
            pass
        return True, f"opencode 就绪（{path}{'，' + version if version else ''}）"
    return False, (
        "未找到 opencode。请先安装：\n"
        "    npm i -g opencode-ai\n"
        "  安装后用 `opencode auth login` 配置一个模型 provider。"
    )


def _check_python() -> tuple[bool, str]:
    """软性：python3 版本（跑实验/内核脚本用）。建议 >= 3.10。"""
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 10)
    msg = f"python3 {major}.{minor}（{sys.executable}）"
    if not ok:
        msg += " —— 版本偏低，部分内核脚本可能不兼容，建议 >= 3.10"
    return ok, msg


def _check_provider() -> tuple[bool, str]:
    """软性：用户是否配过模型 provider（只看全局配置是否存在且含 provider/model）。

    顺带提示自定义 provider 是否漏了 limit.context（缺它 auto-compact 不触发、
    长会话会撑爆）——但仅提示；真正的回填由 launcher 启动时的 config_heal 顺手做。
    """
    for cfg in _GLOBAL_CONFIG_CANDIDATES:
        if cfg.exists():
            try:
                text = cfg.read_text(encoding="utf-8")
            except OSError:
                continue
            if '"provider"' in text or '"model"' in text:
                missing = _missing_limit_models(cfg)
                if missing:
                    return True, (
                        f"检测到模型配置（{cfg}），但自定义 provider 模型缺 limit.context："
                        f"{', '.join(missing)} —— 启动时会自动回填默认值（防长会话上下文撑爆）"
                    )
                return True, f"检测到模型配置（{cfg}）"
            return True, f"找到 {cfg.name}，但未见 provider/model 字段——若启动后无可用模型，运行 `opencode auth login`"
    return False, (
        "未检测到 OpenCode 模型配置。启动后若提示无可用模型，请运行：\n"
        "    opencode auth login\n"
        "  （本工具不管理任何 API key —— 凭证由你自己配置、不写入任何文件）"
    )


def _missing_limit_models(cfg_path: Path) -> list[str]:
    """复用 config_heal 的检测：返回该配置里缺 limit.context 的自定义 provider 模型 id。"""
    try:
        from . import config_heal
        import json

        cfg = json.loads(config_heal._strip_jsonc(cfg_path.read_text(encoding="utf-8")))
        return config_heal._models_needing_limit(cfg)
    except Exception:  # noqa: BLE001 — 体检软项，出错就当没缺
        return []


def check(verbose: bool = True) -> bool:
    """运行全部体检项。

    Args:
        verbose: 是否打印体检结果。

    Returns:
        硬性检查是否全部通过（决定能否继续启动）。软性失败不影响返回值。
    """
    # (label, ok, message, hard)
    opencode_ok, opencode_msg = _check_opencode()
    python_ok, python_msg = _check_python()
    provider_ok, provider_msg = _check_provider()

    items = [
        ("OpenCode", opencode_ok, opencode_msg, True),
        ("Python", python_ok, python_msg, False),
        ("模型配置", provider_ok, provider_msg, False),
    ]

    if verbose:
        print("famou-scientist 启动体检：")
        for label, ok, msg, hard in items:
            if ok:
                mark = "✓"
            else:
                mark = "✗" if hard else "!"
            print(f"  [{mark}] {label}：{msg}")
        print()

    # 只有硬性项失败才阻断启动。
    return all(ok for _, ok, _, hard in items if hard)
