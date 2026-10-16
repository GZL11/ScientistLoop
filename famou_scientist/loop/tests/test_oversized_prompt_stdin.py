"""超长提示词的 stdin 交付。

回归点：提示词随 mailbox 与 ExpBank 证据累积增长，作为单个 argv 元素传给 CLI
时会越过 Linux 的 MAX_ARG_STRLEN（32 页 = 128 KiB），execve 直接以 E2BIG 失败。
现象是 CLI 瞬间 rc=1、零 token、零花费、stdout/stderr 皆空，而 wrapper 只报
`agent result invalid: missing agent result JSON`——真实原因被完全掩盖。
实测该故障已导致 opus5-v1 批次 4 次 attempt 报废。
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from famou_scientist.loop.execution.cli_agent_wrapper import (
    MAX_SINGLE_ARG_BYTES,
    PROMPT_ARG_SAFE_BYTES,
    STDIN_PROMPT_RUNTIMES,
    _spawn_stdin_writer,
    build_cli_argv,
    prompt_needs_stdin,
)


def _args(runtime: str = "claude") -> argparse.Namespace:
    return argparse.Namespace(
        runtime=runtime,
        binary=runtime,
        extra_arg=[],
        worktree=Path("/tmp/worktree"),
        title="t",
        model="claude-opus-5",
        agent=None,
        auto_approve=True,
        role="implement",
        profile=None,
    )


def test_kernel_limit_is_reproducible():
    """先确认被防御的内核限制真实存在，否则本组测试没有意义。"""

    with pytest.raises(OSError) as excinfo:
        subprocess.run(["/bin/echo", "x" * MAX_SINGLE_ARG_BYTES], capture_output=True)
    assert excinfo.value.errno == 7  # E2BIG


def test_safe_threshold_actually_passes_exec():
    """阈值本身必须仍能通过 execve，否则等于把可用提示词也挡掉了。"""

    done = subprocess.run(
        ["/bin/true", "x" * PROMPT_ARG_SAFE_BYTES],
        capture_output=True,
    )
    assert done.returncode == 0


def test_threshold_leaves_margin_under_kernel_limit():
    assert PROMPT_ARG_SAFE_BYTES < MAX_SINGLE_ARG_BYTES
    assert MAX_SINGLE_ARG_BYTES - PROMPT_ARG_SAFE_BYTES >= 4096


def test_normal_prompt_keeps_argv_delivery():
    """未超限时行为完全不变——不为罕见故障改动主路径。"""

    prompt = "x" * 1000
    assert prompt_needs_stdin("claude", prompt) is False
    argv = build_cli_argv(_args(), prompt, Path("/tmp/last"))
    assert argv[-1] == prompt


def test_prompt_at_threshold_still_uses_argv():
    prompt = "x" * PROMPT_ARG_SAFE_BYTES
    assert prompt_needs_stdin("claude", prompt) is False


def test_oversized_prompt_switches_to_stdin():
    prompt = "x" * (PROMPT_ARG_SAFE_BYTES + 1)
    assert prompt_needs_stdin("claude", prompt) is True
    argv = build_cli_argv(_args(), prompt, Path("/tmp/last"), prompt_via_stdin=True)
    assert prompt not in argv


def test_multibyte_prompt_measured_in_bytes():
    """按字节而非字符计量：中文提示词的字节数是字符数的三倍。"""

    prompt = "中" * (PROMPT_ARG_SAFE_BYTES // 3 + 1)
    assert len(prompt) < PROMPT_ARG_SAFE_BYTES
    assert prompt_needs_stdin("claude", prompt) is True


def test_unsupported_runtime_raises_actionable_error():
    """不支持 stdin 的运行时超限时显式报错，而不是让 execve 抛出晦涩的 E2BIG。"""

    prompt = "x" * (PROMPT_ARG_SAFE_BYTES + 1)
    for runtime in ("codex", "opencode", "kimi-code", "z-code"):
        assert runtime not in STDIN_PROMPT_RUNTIMES
        with pytest.raises(ValueError, match="stdin"):
            prompt_needs_stdin(runtime, prompt)


def test_unsupported_runtime_unaffected_below_threshold():
    """超限之外的路径对其他运行时保持原样。"""

    assert prompt_needs_stdin("codex", "x" * 1000) is False


def test_stdin_writer_delivers_full_payload(tmp_path):
    """后台写入必须交付完整内容——截断会让 Agent 拿到残缺指令。"""

    payload = "y" * (PROMPT_ARG_SAFE_BYTES + 5000)
    proc = subprocess.Popen(
        ["/bin/cat"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    _spawn_stdin_writer(proc.stdin, payload)
    out, _ = proc.communicate(timeout=60)
    assert out == payload


def test_stdin_writer_survives_dead_child():
    """子进程先退出时写入线程不得抛出，否则会掩盖真正的退出码。"""

    proc = subprocess.Popen(["/bin/true"], stdin=subprocess.PIPE, text=True)
    proc.wait()
    thread = _spawn_stdin_writer(proc.stdin, "z" * 200000)
    thread.join(timeout=30)
    assert not thread.is_alive()
