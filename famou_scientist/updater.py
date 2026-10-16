# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""自更新：`famou-scientist update` —— 一键拉取最新代码（像 `claude update`）。

实际用法：用户首次 `git clone` 仓库 + `pip install -e .`（editable 安装）装好；
此后**不想每次手动 git pull**，于是用 `famou-scientist update` 一条命令代劳。

editable 安装下，`famou-scientist` 命令指向的就是这个 clone 出来的源码目录，
所以 `git pull` 更新完代码、命令下次运行**即时生效**，连重装都不用。

默认流程（先查再问）：
  1. 定位包所在的 git 仓库；
  2. `git fetch` 后比对本地 vs origin/<分支>，看落后几个提交（只查不动）；
  3. 已最新 → 直说；落后 → 交互确认后 `git pull --ff-only`（非 TTY / -y 直接拉）。

设计原则：
- **fail-safe 不毁改动**：用 `git pull --ff-only`（只快进）。本地有未提交改动 /
  分叉冲突时 git 自己会拒绝，我们如实报错让用户处理，**绝不 reset/覆盖**用户的改动。
- **不碰凭证**：代理 / git 凭证走环境与 git 配置（子进程自然继承），代码里绝不
  硬编码任何代理凭证 / token。
- **非 git 安装回退**：若包不在 git 仓库里（将来真有 pip 发布版），提示用
  `pip install -U`，不报错。
- **联网仅在显式 update 时**：不在启动体检里自动查更新。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = [
    "main",
    "current_version",
    "repo_root",
    "do_update",
]

# 非 git 安装时的回退提示用包名 / 源。
_PKG = "famou-scientist"
_PIP_INDEX = "<内部 pip 源>"


def current_version() -> str:
    """当前包版本（__version__）。"""
    from . import __version__
    return __version__


def _pkg_dir() -> Path:
    """famou_scientist 包所在目录。"""
    from . import __file__ as init_file
    return Path(init_file).resolve().parent


def _git(*git_args: str, cwd: Path, capture: bool, timeout: int | None = None):
    """跑 `git -C <cwd> ...`。capture=True 捕获输出（查状态用），False 直连终端（pull 用）。"""
    cmd = ["git", "-C", str(cwd), *git_args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return subprocess.run(cmd)


def repo_root() -> Path | None:
    """包所在的 git 仓库根目录；不在 git 仓库（如纯 pip 安装）则返回 None。"""
    pkg = _pkg_dir()
    try:
        r = _git("rev-parse", "--show-toplevel", cwd=pkg, capture=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    top = (r.stdout or "").strip()
    return Path(top) if top else None


def _current_branch(root: Path) -> str:
    """当前分支名（detached 等异常时回退 'master'）。"""
    try:
        r = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root, capture=True, timeout=10)
        b = (r.stdout or "").strip()
        if b and b != "HEAD":
            return b
    except (OSError, subprocess.SubprocessError):
        pass
    return "master"


def _behind_count(root: Path, branch: str) -> int | None:
    """本地落后 origin/<branch> 多少个提交。无法判定返回 None。

    先 fetch 拿到最新远端引用，再数 HEAD..origin/<branch>。
    """
    try:
        f = _git("fetch", "origin", branch, cwd=root, capture=True, timeout=60)
        if f.returncode != 0:
            return None
        r = _git(
            "rev-list", "--count", f"HEAD..origin/{branch}",
            cwd=root, capture=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        return int((r.stdout or "0").strip() or "0")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _has_local_changes(root: Path) -> bool:
    """工作区是否有未提交改动（脏树）。出错时保守按 True（让 pull 自己把关）。"""
    try:
        r = _git("status", "--porcelain", cwd=root, capture=True, timeout=15)
        return bool((r.stdout or "").strip())
    except (OSError, subprocess.SubprocessError):
        return True


def do_update(root: Path, branch: str) -> int:
    """执行 `git pull --ff-only origin <branch>`。输出直连终端。返回 git 退出码。"""
    print(f"→ git -C {root} pull --ff-only origin {branch}\n", flush=True)
    r = _git("pull", "--ff-only", "origin", branch, cwd=root, capture=False)
    return r.returncode


def _usage() -> None:
    print(
        "用法：famou-scientist update [--check|-n] [--yes|-y]\n"
        "  （无参数）检查远端是否有新提交，有则确认后 git pull\n"
        "  --check / -n  只检查不拉取（落后时返回非 0，便于脚本判断）\n"
        "  --yes   / -y  跳过确认直接拉取（CI / 全自动）",
    )


def main(args=None) -> int:
    """`famou-scientist update` 子命令入口。"""
    args = list(args or [])
    if any(a in ("-h", "--help") for a in args):
        _usage()
        return 0
    check_only = any(a in ("--check", "-n") for a in args)
    assume_yes = any(a in ("--yes", "-y") for a in args)
    unknown = [a for a in args if a not in ("--check", "-n", "--yes", "-y")]
    if unknown:
        print(f"未知参数：{' '.join(unknown)}\n", file=sys.stderr)
        _usage()
        return 2

    cur = current_version()
    print(f"famou-scientist 当前版本：{cur}")

    root = repo_root()
    if root is None:
        # 非 git 安装（如纯 pip 发布版）：给手动升级命令，不报错。
        print(
            "! 当前不是从 git 仓库安装的，无法用 git 更新。\n"
            f"  请手动升级：pip install -U -i {_PIP_INDEX} {_PKG}",
            file=sys.stderr,
        )
        return 0

    branch = _current_branch(root)
    print(f"检查更新（仓库：{root}，分支：{branch}）……")

    behind = _behind_count(root, branch)
    if behind is None:
        print(
            "! 无法获取远端更新（检查网络 / 代理 ALL_PROXY，或 git 远端是否可达）。\n"
            f"  可手动更新：cd {root} && git pull",
            file=sys.stderr,
        )
        return 0

    if behind == 0:
        print("✅ 已是最新（与远端一致）。")
        return 0

    print(f"发现 {behind} 个新提交可更新。")
    if check_only:
        print("（--check：只检查不拉取。去掉 --check 即可更新。）")
        return 1  # 非 0 便于脚本判断"有可用更新"

    # 脏树预警：pull --ff-only 遇到冲突的改动会失败，提前告知更友好。
    if _has_local_changes(root):
        print(
            "⚠ 工作区有未提交改动；若与更新冲突，git pull 会中止（不会覆盖你的改动）。\n"
            "  如需保留改动，建议先 git stash 或 git commit。",
        )

    if not assume_yes and sys.stdin.isatty():
        try:
            ans = input(f"拉取最新代码（{behind} 个提交）? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 0
        if ans not in ("", "y", "yes"):
            print("已取消。")
            return 0

    rc = do_update(root, branch)
    if rc == 0:
        print(
            "\n✅ 已更新到最新代码。"
            "（editable 安装下重开 famou-scientist 即生效；若改了依赖请重跑 pip install -e .）",
        )
    else:
        print(
            f"\n✗ 更新失败（git 退出码 {rc}）。常见原因：本地改动冲突 / 网络。\n"
            f"  可手动处理：cd {root} && git status && git pull",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
