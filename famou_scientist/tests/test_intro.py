# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""intro 薄壳初始菜单的单元测试：参数摘取、显示门控、菜单选择映射、品牌一致性。

均离线、不起 opencode、不触真 TTY（用 monkeypatch 注入 isatty / input）。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import pytest

from famou_scientist import intro


def test_strip_flags_extracts_no_intro():
    clean, no_intro = intro.strip_flags(["--no-intro", "--model", "x"])
    assert clean == ["--model", "x"]
    assert no_intro is True


def test_strip_flags_default():
    clean, no_intro = intro.strip_flags([])
    assert clean == [] and no_intro is False


def test_should_show_false_when_not_tty(monkeypatch):
    monkeypatch.delenv("FAMOU_NO_INTRO", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert intro.should_show([], False) is False


def test_should_show_false_with_no_intro(monkeypatch):
    monkeypatch.delenv("FAMOU_NO_INTRO", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert intro.should_show([], True) is False


def test_should_show_false_with_args(monkeypatch):
    monkeypatch.delenv("FAMOU_NO_INTRO", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    # 带透传参数 = 明确意图，跳过菜单
    assert intro.should_show(["--model", "x"], False) is False


def test_should_show_false_with_env(monkeypatch):
    monkeypatch.setenv("FAMOU_NO_INTRO", "1")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert intro.should_show([], False) is False


def test_should_show_true_interactive(monkeypatch):
    monkeypatch.delenv("FAMOU_NO_INTRO", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert intro.should_show([], False) is True


def _keys(seq):
    """把按键序列做成可注入的 read_key（每调用返回下一个 token）。"""
    it = iter(seq)
    return lambda: next(it)


# ── _decode_key：方向键/回车/退出 字节解码（守护"按方向键即退出"那个 bug）──
def test_decode_arrow_keys():
    assert intro._decode_key(b"\x1b[A") == "up"
    assert intro._decode_key(b"\x1b[B") == "down"
    assert intro._decode_key(b"\x1b[C") == "right"
    assert intro._decode_key(b"\x1b[D") == "left"


def test_decode_enter_and_quit():
    assert intro._decode_key(b"\r") == "enter"
    assert intro._decode_key(b"\n") == "enter"
    assert intro._decode_key(b"q") == "quit"
    assert intro._decode_key(b"\x1b") == "quit"   # 裸 ESC
    assert intro._decode_key(b"") == "quit"        # 无字节


def test_decode_plain_chars():
    assert intro._decode_key(b"2") == "2"
    assert intro._decode_key(b"j") == "j"
    assert intro._decode_key(b"k") == "k"


def test_decode_ctrl_c_raises():
    with pytest.raises(KeyboardInterrupt):
        intro._decode_key(b"\x03")


# ── select：方向键轮转 ─────────────────────────────────────────
def test_select_down_then_enter():
    assert intro.select(["a", "b", "c"], read_key=_keys(["down", "enter"]), write=lambda s: None) == 1


def test_select_up_wraps_to_last():
    # 起点 0，↑ 轮转到最后一项
    assert intro.select(["a", "b", "c"], read_key=_keys(["up", "enter"]), write=lambda s: None) == 2


def test_select_jk_and_quit():
    assert intro.select(["a", "b"], read_key=_keys(["j", "k", "quit"]), write=lambda s: None) is None


def test_select_digit_quick_pick():
    assert intro.select(["a", "b", "c"], read_key=_keys(["2"]), write=lambda s: None) == 1


# ── run_menu：四项 + 历史会话二级列表 ─────────────────────────
def test_run_menu_new_research():
    # 主菜单停在第 0 项，回车 → 新研究
    act = intro.run_menu(read_key=_keys(["enter"]), list_sessions_fn=lambda: [])
    assert act == ("tui", [])


def test_run_menu_web():
    # ↓↓ 到第 2 项（Web），回车
    act = intro.run_menu(read_key=_keys(["down", "down", "enter"]), list_sessions_fn=lambda: [])
    assert act == ("web", [])


def test_run_menu_quit_via_last_item():
    act = intro.run_menu(read_key=_keys(["down", "down", "down", "enter"]), list_sessions_fn=lambda: [])
    assert act == ("quit", [])


def test_run_menu_continue_picks_session():
    sessions = [{"id": "ses_aaa", "title": "玻色采样", "updated": "2026-06-20T10:00:00", "messages": 12},
                {"id": "ses_bbb", "title": "HEP", "updated": "2026-06-19T09:00:00", "messages": 3}]
    # 主菜单 ↓ 到「继续历史会话」(idx1)→回车；二级列表 ↓ 到第二个会话→回车
    act = intro.run_menu(read_key=_keys(["down", "enter", "down", "enter"]),
                         list_sessions_fn=lambda: sessions)
    assert act == ("tui", ["--session", "ses_bbb"])


def test_run_menu_continue_empty_returns_to_main_then_new():
    # 无历史会话：进二级列表选任意项回主菜单，再回车 = 新研究
    act = intro.run_menu(read_key=_keys(["down", "enter", "enter", "enter"]),
                         list_sessions_fn=lambda: [])
    assert act == ("tui", [])


def test_run_menu_continue_back_returns_to_main():
    sessions = [{"id": "ses_aaa", "title": "x", "updated": "2026-06-20T10:00:00", "messages": 1}]
    # 进二级列表，↓ 到「← 返回」(idx==len)→回车 回主菜单；再 ↓↓ 到 Web
    act = intro.run_menu(read_key=_keys(["down", "enter", "down", "enter", "down", "down", "enter"]),
                         list_sessions_fn=lambda: sessions)
    assert act == ("web", [])


def test_banner_is_famou_branded_not_opencode():
    b = intro.banner()
    assert "Famou-Scientist" in b
    assert "opencode" not in b.lower()  # 身份一致性：绝不出现 opencode
