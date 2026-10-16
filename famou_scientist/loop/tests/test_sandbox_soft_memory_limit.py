"""内存软限额：超申报值只记录，超资源池余量才终止。

历史 OOM 多为超出自己申报值 1%~9%（如申报 32 GiB、实际 32.2 GiB）而被杀，
但容器仍有余量。软限额把终止阈值从"自己申报的额度"改为"资源池余量"，
超报事实由 ``memory_over_request`` 记录，供后续校准申报值。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from famou_scientist.loop.execution.sandbox import LocalSandbox, SandboxError


def _alloc_script(mib: int) -> list[str]:
    """分配约 mib MiB 常驻内存并短暂持有。"""
    return [
        sys.executable,
        "-c",
        (
            "import time\n"
            f"buf = bytearray({mib} * 1024 * 1024)\n"
            "for i in range(0, len(buf), 4096):\n"
            "    buf[i] = 1\n"
            "time.sleep(1.5)\n"
        ),
    ]


def test_hard_limit_defaults_to_request(tmp_path: Path):
    """未给出硬阈值时退回申报值，保持原有行为。"""

    sandbox = LocalSandbox(tmp_path, memory_limit_bytes=64 * 2**20)
    assert sandbox.memory_hard_limit_bytes == 64 * 2**20


def test_hard_limit_never_below_request(tmp_path: Path):
    """硬阈值低于申报值时上抬，避免软限额反而更严格。"""

    sandbox = LocalSandbox(
        tmp_path,
        memory_limit_bytes=128 * 2**20,
        memory_hard_limit_bytes=32 * 2**20,
    )
    assert sandbox.memory_hard_limit_bytes == 128 * 2**20


def test_rejects_nonpositive_hard_limit(tmp_path: Path):
    """硬阈值必须为正数。"""

    with pytest.raises(SandboxError):
        LocalSandbox(tmp_path, memory_hard_limit_bytes=0)


@pytest.mark.skipif(sys.platform != "linux", reason="RSS 监控依赖 /proc")
def test_over_request_within_pool_survives(tmp_path: Path):
    """超出申报值但仍在余量内：跑完，并标记 over_request。"""

    sandbox = LocalSandbox(
        tmp_path,
        memory_limit_bytes=48 * 2**20,        # 申报 48 MiB
        memory_hard_limit_bytes=512 * 2**20,  # 池内余量 512 MiB
        memory_limit_strategy="rss",
        memory_monitor_interval_sec=0.02,
    )
    result = sandbox.run(_alloc_script(128), timeout_sec=60)

    assert result.returncode == 0
    assert not result.memory_limit_exceeded
    assert result.termination_reason == "completed"
    # 回归点：旧实现会在越过 48 MiB 时立即 SIGTERM。
    assert result.memory_over_request is True
    assert result.observed_memory_bytes > 48 * 2**20


@pytest.mark.skipif(sys.platform != "linux", reason="RSS 监控依赖 /proc")
def test_exceeding_pool_is_terminated(tmp_path: Path):
    """越过资源池余量：仍然终止，防止拖垮整个容器。"""

    sandbox = LocalSandbox(
        tmp_path,
        memory_limit_bytes=16 * 2**20,
        memory_hard_limit_bytes=64 * 2**20,
        memory_limit_strategy="rss",
        memory_monitor_interval_sec=0.02,
    )
    result = sandbox.run(_alloc_script(256), timeout_sec=60)

    assert result.memory_limit_exceeded is True
    assert result.termination_reason == "memory_limit_exceeded"
    assert result.memory_over_request is True


@pytest.mark.skipif(sys.platform != "linux", reason="RSS 监控依赖 /proc")
def test_within_request_not_flagged(tmp_path: Path):
    """未超申报值时不应误标 over_request。"""

    sandbox = LocalSandbox(
        tmp_path,
        memory_limit_bytes=512 * 2**20,
        memory_hard_limit_bytes=1024 * 2**20,
        memory_limit_strategy="rss",
        memory_monitor_interval_sec=0.02,
    )
    result = sandbox.run(_alloc_script(32), timeout_sec=60)

    assert result.returncode == 0
    assert result.memory_over_request is False
    assert not result.memory_limit_exceeded


def test_address_space_uses_hard_limit(tmp_path: Path):
    """非 GPU 任务的 RLIMIT_AS 取硬阈值，而非申报值。"""

    sandbox = LocalSandbox(
        tmp_path,
        memory_limit_bytes=64 * 2**20,
        memory_hard_limit_bytes=512 * 2**20,
        memory_limit_strategy="address_space",
    )
    argv = sandbox._execution_argv(("echo", "hi"))
    assert any(f"--as={512 * 2**20}" == part for part in argv)
    assert not any(f"--as={64 * 2**20}" == part for part in argv)


def test_result_dict_exposes_new_fields(tmp_path: Path):
    """新字段进入可持久化结果，供后续校准申报值。"""

    sandbox = LocalSandbox(tmp_path, memory_limit_bytes=32 * 2**20)
    payload = sandbox.run([sys.executable, "-c", "pass"], timeout_sec=30).to_dict()
    assert "memory_hard_limit_bytes" in payload
    assert "memory_over_request" in payload
