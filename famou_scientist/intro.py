# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""Famou-Scientist 的「初始界面」——拉起 opencode 前的一层 famou 自有薄壳。

为什么要这层壳：opencode 的 TUI 全屏接管、画自己的 logo home，且名字编译进二进制、
无配置开关可改。我们不侵入第三方二进制，而是在 **exec opencode 之前**先呈现一个
**纯 famou 品牌**的交互菜单，让"第一眼"是 Famou-Scientist。

交互：**方向键 ↑/↓ 轮转**选择（也支持 j/k、数字快选），回车确认，q/ESC 退出——
不是敲数字。四个选项竖直排布。选「继续历史会话」会列出 opencode 会话库里的**历史会话**
（按最近更新，可选），选中后带 ``--session <id>`` 直接进该会话的聊天视图，
从而跳过 opencode 那个带 logo 的 home 屏。

设计约束：
- **纯 stdlib、零依赖**：方向键用 termios/tty raw 模式读，会话列表复用 ``vis.trace``。
- **只在交互式 TTY 显示**：管道 / headless / RCB / 带参数一律跳过。``--no-intro`` /
  ``FAMOU_NO_INTRO=1`` 可强制关闭。
- 永远是 Famou-Scientist 品牌，绝不出现 opencode 字样（身份一致性）。
- 选择器核心 ``select()`` 把"读键"与"读会话"做成可注入参数，便于离线单测（不碰真终端）。

返回给 cmdline 的是动作三元：``("tui", extra)`` / ``("web", [])`` / ``("quit", [])``。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import os
import sys

__all__ = ["strip_flags", "strip_flags_ext", "should_show", "banner", "select", "run_menu"]


def _supports_color() -> bool:
    """是否上色：尊重 NO_COLOR；非 TTY 不上色。"""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def strip_flags(args: list[str]) -> tuple[list[str], bool]:
    """从参数里摘出 famou 自有标志，返回（透传给 opencode 的干净参数, 是否 --no-intro）。"""
    clean, no_intro, _bs = strip_flags_ext(args)
    return clean, no_intro


def strip_flags_ext(args: list[str]) -> tuple[list[str], bool, bool]:
    """``strip_flags`` 的扩展版：额外摘出 ``--bs``（返回 (干净参数, --no-intro, --bs)）。

    ``--bs`` 是消融实验专用标志（见 ``bs_toggle`` 模块），单独拆出这个 ext 版本而不是
    直接改 ``strip_flags`` 的返回签名，避免动到已有调用点/测试的元组解包形状。
    """
    no_intro = False
    bs = False
    clean: list[str] = []
    for a in args:
        if a == "--no-intro":
            no_intro = True
        elif a == "--bs":
            bs = True
        else:
            clean.append(a)
    return clean, no_intro, bs


def should_show(clean_args: list[str], no_intro: bool) -> bool:
    """是否呈现初始菜单。

    仅当：交互式 TTY（stdin+stdout 都是终端）、未 --no-intro、未设 FAMOU_NO_INTRO、
    且**无任何透传参数**（裸 ``famou-scientist``）。带 --model / prompt / 路径等显式调用，
    视为"老手/脚本直达"，跳过菜单。
    """
    if no_intro or os.environ.get("FAMOU_NO_INTRO"):
        return False
    if clean_args:  # 带参数 = 明确意图，直达
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def banner() -> str:
    """纯文本品牌横幅（不含 ANSI），便于单测断言内容。"""
    try:
        from . import __version__ as ver
    except Exception:
        ver = ""
    v = f"  v{ver}" if ver else ""
    return (
        "\n"
        "  ▌\n"
        "  ▌  Famou-Scientist" + v + "\n"
        "  ▌  你的科研搭子 · 自主科研 Agent\n"
        "  ▌  文献调研 → 实验 → 论文，一条龙\n"
        "  ▌\n"
    )


# ── 键盘：raw 模式读一个按键，规范化为 token ─────────────────────
def _decode_key(b: bytes) -> str:
    """把读到的原始字节解码成 token：up/down/left/right/enter/quit，或原字符。

    方向键是 3 字节 ESC[A/B/C/D；裸 ESC 视为 quit；Ctrl-C 抛 KeyboardInterrupt。
    """
    if not b:
        return "quit"
    if b == b"\x03":  # Ctrl-C（raw 模式下不再触发 SIGINT，自己处理）
        raise KeyboardInterrupt
    if b in (b"\r", b"\n"):
        return "enter"
    if b[:1] == b"\x1b":  # 转义序列
        return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}.get(b[1:], "quit")
    ch = b.decode("utf-8", "ignore")
    if ch in ("q", "Q"):
        return "quit"
    return ch or "quit"


def _read_key() -> str:
    """读一个按键并规范化。仅在真 TTY 用。

    用 ``os.read``（绕过 Python 行缓冲！）一次读最多 3 字节——方向键的 ``\\x1b[A``
    一次到齐；若只读到裸 ESC，再用 select 补读后续字节（应对 SSH 下字节被拆开）。
    """
    import select as _sel
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd, termios.TCSANOW)  # TCSANOW：立即生效但**不丢弃**已输入字节（保留快速连按/方向键序列）
        b = os.read(fd, 3)
        if b == b"\x1b" and _sel.select([fd], [], [], 0.05)[0]:
            b += os.read(fd, 2)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return _decode_key(b)


def _render_select(header: str, options: list[str], idx: int, write) -> None:
    color = _supports_color()
    parts = []
    try:
        if sys.stdout.isatty():
            parts.append("\033[2J\033[3J\033[H")  # 清屏+清回滚+归位
    except Exception:
        pass
    if header:
        parts.append(header)
    for i, opt in enumerate(options):
        if i == idx:
            parts.append(f"   \033[36m\033[1m▸ {opt}\033[0m" if color else f"   ▸ {opt}")
        else:
            parts.append(f"     {opt}")
    hint = "   ↑/↓ 选择 · 回车 确认 · q 退出"
    parts.append("\n" + (f"\033[2m{hint}\033[0m" if color else hint))
    write("\n".join(parts) + "\n")


def select(options: list[str], *, header: str = "", read_key=None, write=None) -> int | None:
    """竖排单选，方向键 ↑/↓ 轮转（含 j/k、数字快选）。返回选中下标，q/ESC/Ctrl-C 返回 None。"""
    if not options:
        return None
    read_key = read_key or _read_key
    if write is None:
        def write(s):
            sys.stdout.write(s)
            sys.stdout.flush()
    n = len(options)
    idx = 0
    while True:
        _render_select(header, options, idx, write)
        try:
            key = read_key()
        except KeyboardInterrupt:
            return None
        if key in ("up", "k"):
            idx = (idx - 1) % n          # 轮转
        elif key in ("down", "j"):
            idx = (idx + 1) % n
        elif key == "enter":
            return idx
        elif key == "quit":
            return None
        elif isinstance(key, str) and key.isdigit():
            d = int(key)
            if 1 <= d <= n:
                return d - 1


# ── 历史会话：复用 vis.trace，按 build_env 解析 DB（与 opencode 一致）──
def _recent_sessions(limit: int = 8) -> list[dict]:
    """列最近的主会话（过滤子会话）；拿不到库就返回空，绝不报错打断菜单。"""
    try:
        from . import launcher, web
        from .vis import trace

        env = launcher.build_env()
        db = web._opencode_data_dir(env) / "opencode.db"
        if not db.exists():
            return []
        con = trace._connect(db)
        try:
            rows = trace.list_sessions(con, limit=limit * 3)
        finally:
            con.close()
        rows = [r for r in rows if not r.get("parent_id")]  # 只列主会话
        return rows[:limit]
    except Exception:
        return []


def _session_label(s: dict) -> str:
    title = (s.get("title") or "").strip() or "(无标题)"
    if len(title) > 36:
        title = title[:35] + "…"
    updated = (s.get("updated") or "").replace("T", " ")
    return f"{title}    {updated}  · {s.get('messages', 0)} 条"


def run_menu(read_key=None, list_sessions_fn=None) -> tuple[str, list[str]]:
    """呈现菜单并读取选择，返回动作三元。

    Args:
        read_key: 读一个按键的函数（默认 termios；测试注入）。
        list_sessions_fn: 列历史会话的函数（默认 ``_recent_sessions``；测试注入）。

    Returns:
        ("tui", []) 新研究 | ("tui", ["--session", sid]) 续某会话 | ("web", []) | ("quit", [])
    """
    list_sessions_fn = list_sessions_fn or _recent_sessions
    main_opts = ["开始新研究", "继续历史会话", "Web 研究台", "退出"]
    header = banner() + "\n"
    while True:
        i = select(main_opts, header=header, read_key=read_key)
        if i is None or i == 3:
            return ("quit", [])
        if i == 0:
            return ("tui", [])
        if i == 2:
            return ("web", [])
        # i == 1：继续历史会话 → 二级列表
        sessions = list_sessions_fn()
        sub_header = banner() + "\n  选择要继续的历史会话：\n"
        if not sessions:
            select(["（暂无历史会话）", "← 返回"], header=sub_header, read_key=read_key)
            continue  # 无论选哪，回主菜单
        labels = [_session_label(s) for s in sessions] + ["← 返回"]
        j = select(labels, header=sub_header, read_key=read_key)
        if j is None or j == len(sessions):
            continue  # 返回主菜单
        return ("tui", ["--session", sessions[j]["id"]])
