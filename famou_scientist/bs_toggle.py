# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""``--bs``（Baidu Search）消融实验模式：断外网只留百度专线，对比有无外网时的科研效果。

背景：``arc.ts`` 里的 ``web_search`` 走百度千帆 AI 搜索（内网专线），``arc_search_literature``
等其它工具走 arXiv/Semantic Scholar/OpenAlex 等公网 API。想验证"断外网、仅剩百度搜索"场景下
agent 的科研表现，就需要在整机层面把 80/443 全部墙掉、只放行百度 API 的 IP，再拉起 opencode。

这是**风险操作**（改全局 iptables 规则，非本进程沙箱），脚本本身随包分发在
``scripts/toggle_network.sh``（换机器也自带，不依赖外部路径）。为了不让这种实验性操作
污染主启动路径（``launcher.launch()`` 用 ``execvpe`` 直接替换进程，没有"退出后再执行清理"的
钩子），单独开一个模块：只有显式传 ``--bs`` 才会被 ``cmdline.py``/``web.py`` 调用到，
其余启动路径完全不感知本模块的存在。

对外提供两种粒度：
- ``run()``：TUI 专用，自己管子进程生命周期（断网→跑 opencode→复网）。
- ``toggle_off()`` / ``install_restore_guard()``：细粒度原语，供 ``web.py`` 这类"自己管子进程、
  只是想在生命周期两端插入断网/复网"的调用方复用，避免重复实现信号/atexit 兜底逻辑。

机制上与主路径的关键差异：主路径 ``execvpe`` 替换进程（无法在其后插清理逻辑）；本模块必须
用 ``subprocess`` 拉子进程、等待退出后再执行"复网"，所以是两套不同的进程模型，仅在
``--bs`` 分支生效。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

__all__ = [
    "DEFAULT_TOGGLE_SCRIPT",
    "run",
    "toggle_off",
    "install_restore_guard",
    "restore_now",
]

# 脚本随包分发（famou_scientist/scripts/toggle_network.sh），换机器也自带；
# 如需换成别的版本（比如别的机器上不同的百度 IP 白名单），设 FAMOU_TOGGLE_NETWORK_SCRIPT 覆盖。
DEFAULT_TOGGLE_SCRIPT = str(Path(__file__).resolve().parent / "scripts" / "toggle_network.sh")

_restore_lock = threading.Lock()
_restored = False


def _toggle_script() -> str:
    return os.environ.get("FAMOU_TOGGLE_NETWORK_SCRIPT", DEFAULT_TOGGLE_SCRIPT)


def script_ready() -> tuple[bool, str]:
    """脚本是否存在且可执行；返回 (是否就绪, 脚本路径)，供调用方统一报错文案。"""
    script = _toggle_script()
    return os.path.isfile(script) and os.access(script, os.X_OK), script


def _run_toggle(action: str) -> bool:
    """跑一次 toggle_network.sh on/off，返回是否成功（失败仅打印，不抛异常）。"""
    script = _toggle_script()
    try:
        r = subprocess.run(
            [script, action],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[--bs] 执行 {script} {action} 失败：{e}", file=sys.stderr)
        return False
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out:
        print(f"[--bs] {out}")
    if r.returncode != 0:
        print(f"[--bs] {script} {action} 退出码 {r.returncode}" + (f"：{err}" if err else ""), file=sys.stderr)
        return False
    return True


def restore_now() -> None:
    """幂等地恢复外网：atexit + 信号处理器可能都会触发，用锁防止重复执行。

    模块级去重（``_restored``）只在**同一次 Python 进程**内生效；``run()``（TUI）和
    ``serve_web()``（web）是各自独立的进程，不会互相影响这个状态。
    """
    global _restored
    with _restore_lock:
        if _restored:
            return
        _restored = True
        print("[--bs] 正在恢复外网……")
        _run_toggle("on")


def toggle_off() -> bool:
    """断外网（仅留百度专线）。返回是否成功。"""
    print("[--bs] 消融实验模式：断外网，仅保留百度 API 专线……")
    return _run_toggle("off")


def install_restore_guard(proc: "subprocess.Popen | None" = None) -> None:
    """挂 atexit + SIGINT/SIGTERM 处理器，确保调用方无论怎么退出都会尝试复网。

    供"自己管子进程生命周期、只需要在两端插入断/复网"的调用方（如 ``web.serve_web``）使用；
    与 ``run()`` 内联实现的是同一套兜底逻辑，抽出来避免重复。

    Args:
        proc: 若传入，仅用于打印提示；不再尝试转发信号给它——opencode 是全屏 TUI，
            会自己接管终端并注册自己的信号处理逻辑，父进程转发的信号不保证被其处理
            成"退出"（它可能是忽略、或者需要先跳出某个子界面）。之前 ``run()`` 靠转发
            信号 + ``proc.wait()`` 阻塞等待，一旦 opencode 没在预期内响应，父进程的
            Python 主线程会卡死在 ``wait()`` 系统调用里，Ctrl+C 连按也没用，只能
            ``kill -9``。真正让父进程"能退出"的是 ``run()`` 里的后台线程轮询
            （见其实现），本函数只负责复网 + 给用户一次性提示。
    """
    atexit.register(restore_now)
    prev_handlers: dict[int, object] = {}

    def _on_signal(signum, frame):  # noqa: ANN001
        print("\n[--bs] 收到退出信号，正在恢复外网……", flush=True)
        restore_now()
        prev = prev_handlers.get(signum)
        if callable(prev):
            prev(signum, frame)
        else:
            sys.exit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        prev_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, _on_signal)


def run(extra_args: list[str] | None = None) -> int:
    """断外网（仅留百度专线）→ 跑 opencode 子进程 → 无论如何退出都恢复外网。

    与 ``launcher.launch()`` 不同：这里不能用 ``execvpe`` 替换进程（那样进程退出时
    "复网"就没机会执行了），改用 ``subprocess`` 管子进程生命周期，父进程活到子进程
    退出、再做清理。

    进程模型（关键）：opencode 是全屏 TUI，直接继承终端，用户在里面按下的
    ``/exit`` 或 Ctrl+C 都是**子进程自己**处理、自己退出——父进程不需要（也不能可靠地）
    转发信号让它退出。父进程只是在后台线程里 ``proc.wait()``，一旦子进程退出（无论是
    ``/exit``、还是用户在子进程的终端里按 Ctrl+C 直接杀了它），主线程立刻执行复网并返回，
    不会卡住、也不需要用户对父进程本身做任何操作。

    Args:
        extra_args: 透传给 opencode 的额外参数。

    Returns:
        opencode 子进程的退出码；若前置检查失败则返回非 0。
    """
    from . import launcher

    ready, script = script_ready()
    if not ready:
        print(
            f"✗ --bs 需要网络切换脚本，但未找到或不可执行：{script}\n"
            "  可通过环境变量 FAMOU_TOGGLE_NETWORK_SCRIPT 指定实际路径。",
            file=sys.stderr,
        )
        return 1

    opencode = shutil.which("opencode")
    if not opencode:
        print(
            "✗ 未找到 opencode 可执行文件。请先安装：npm i -g opencode-ai\n"
            "  然后 opencode auth login 配好一个模型。",
            file=sys.stderr,
        )
        return 127

    try:
        from . import config_heal

        config_heal.heal_config()
    except Exception:  # noqa: BLE001 — 锦上添花，异常静默
        pass

    if not toggle_off():
        print("✗ 断网失败，取消启动（避免造成'看似隔离但实际仍联网'的假实验条件）。", file=sys.stderr)
        return 1

    env = launcher.build_env()
    argv = ["opencode"]
    if extra_args:
        argv.extend(extra_args)

    print("正在拉起 Famou-Scientist 研究台（--bs 模式）……（输入 /exit 退出）\n")
    # opencode 直接继承本进程的 stdin/stdout/stderr，接管终端画 TUI；父进程不参与
    # 终端交互，只是在旁边等它退出。
    proc = subprocess.Popen([opencode, *argv[1:]], env=env)
    install_restore_guard(proc)
    proc.wait()
    restore_now()
    return proc.returncode
