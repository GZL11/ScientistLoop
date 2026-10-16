"""进程被信号终止时的归因证据。

此前 SIGKILL 与 SIGTERM 合并为单一 `agent_process_killed`，且唯一的内存证据是
`observed_memory_bytes` —— 它只采样 Agent 自身进程组的 RSS，而 Agent 只驱动 CLI，
重负载在 evaluator 的独立进程里。实测 28 例全部落在 0.3 GiB 左右而限额是 48 GiB，
对判断"是否容器级 OOM"毫无帮助，导致这些 attempt 事后无法归因。

本组覆盖两处修正：
1. cgroup v2 的 `memory.events.oom_kill` 是内核 OOM killer 的直接计数，落盘到
   `failure.signal_evidence`
2. SIGKILL / SIGTERM 分开归类 —— 内核 OOM killer 只发 SIGKILL
"""
from __future__ import annotations

from pathlib import Path

import pytest

from famou_scientist.loop.execution import cli_agent_wrapper as wrapper


def _failure(returncode: int, **kwargs):
    base = dict(
        returncode=returncode,
        timed_out=False,
        submitted=False,
        cancelled_by_controller=False,
        result_valid=False,
        result_error=None,
        stdout="",
        stderr="",
    )
    base.update(kwargs)
    return wrapper._failure_details(**base)


# --- cgroup 证据采集 -------------------------------------------------


def test_reads_oom_kill_counter_from_this_container():
    """在真实环境上验证采集可用 —— 否则修正等于没做。"""

    evidence = wrapper._read_cgroup_memory_evidence()
    if not evidence.get("available"):
        pytest.skip("该环境不暴露 cgroup v2 memory.events")
    assert "memory_events" in evidence or "memory_events_local" in evidence
    assert wrapper._cgroup_oom_kills(evidence) is not None


def test_parses_counters(tmp_path, monkeypatch):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "memory.events").write_text(
        "low 0\nhigh 3\nmax 1\noom 2\noom_kill 7\n", encoding="utf-8"
    )
    (root / "memory.peak").write_text("12345\n", encoding="utf-8")
    (root / "memory.max").write_text("max\n", encoding="utf-8")
    monkeypatch.setattr(wrapper, "_cgroup_v2_root", lambda: root)

    evidence = wrapper._read_cgroup_memory_evidence()
    assert evidence["memory_events"]["oom_kill"] == 7
    assert evidence["memory_peak"] == 12345
    # "max" 表示无上限，不能当成字符串塞进数值字段。
    assert evidence["memory_max"] is None
    assert wrapper._cgroup_oom_kills(evidence) == 7


def test_local_counter_takes_precedence(tmp_path, monkeypatch):
    """memory.events 含子 cgroup 的累计；本层事件应优先。"""

    root = tmp_path / "cg"
    root.mkdir()
    (root / "memory.events").write_text("oom_kill 9\n", encoding="utf-8")
    (root / "memory.events.local").write_text("oom_kill 1\n", encoding="utf-8")
    monkeypatch.setattr(wrapper, "_cgroup_v2_root", lambda: root)

    assert wrapper._cgroup_oom_kills(wrapper._read_cgroup_memory_evidence()) == 1


def test_unavailable_cgroup_does_not_guess(monkeypatch):
    """读不到证据时必须返回不可用，而不是默认"不是 OOM"。"""

    monkeypatch.setattr(wrapper, "_cgroup_v2_root", lambda: None)
    evidence = wrapper._read_cgroup_memory_evidence()
    assert evidence["available"] is False
    assert wrapper._cgroup_oom_kills(evidence) is None


def test_malformed_counters_are_skipped(tmp_path, monkeypatch):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "memory.events").write_text(
        "garbage\noom_kill notanumber\nhigh 4\n", encoding="utf-8"
    )
    monkeypatch.setattr(wrapper, "_cgroup_v2_root", lambda: root)

    evidence = wrapper._read_cgroup_memory_evidence()
    assert evidence["memory_events"] == {"high": 4}
    assert wrapper._cgroup_oom_kills(evidence) is None


# --- SIGKILL / SIGTERM 分开归类 --------------------------------------


def test_sigkill_with_oom_evidence(monkeypatch):
    monkeypatch.setattr(
        wrapper,
        "_read_cgroup_memory_evidence",
        lambda: {"available": True, "memory_events_local": {"oom_kill": 3}},
    )
    failure = _failure(-9)
    assert failure["error_code"] == "agent_killed_by_cgroup_oom"
    assert failure["signal"] == "SIGKILL"
    assert failure["signal_evidence"]["cgroup_oom_kills"] == 3
    # 建议必须指向容器级并发，而不是让 Agent 优化单进程内存。
    assert "并发" in failure["suggested_action"]


def test_sigkill_without_oom_evidence(monkeypatch):
    monkeypatch.setattr(
        wrapper,
        "_read_cgroup_memory_evidence",
        lambda: {"available": True, "memory_events_local": {"oom_kill": 0}},
    )
    failure = _failure(-9)
    assert failure["error_code"] == "agent_killed_sigkill"
    assert failure["signal_evidence"]["cgroup_oom_kills"] == 0
    assert "排除容器级内存不足" in failure["message"]


def test_sigkill_with_unreadable_cgroup(monkeypatch):
    """证据不可读时不得断言"排除 OOM"。"""

    monkeypatch.setattr(
        wrapper, "_read_cgroup_memory_evidence", lambda: {"available": False}
    )
    failure = _failure(-9)
    assert failure["error_code"] == "agent_killed_sigkill"
    assert failure["signal_evidence"]["cgroup_oom_kills"] is None
    assert "无法判断" in failure["message"]


def test_sigterm_is_classified_separately(monkeypatch):
    """回归点：SIGTERM 曾与 SIGKILL 合并，掩盖了两类不同故障。"""

    monkeypatch.setattr(
        wrapper,
        "_read_cgroup_memory_evidence",
        lambda: {"available": True, "memory_events_local": {"oom_kill": 5}},
    )
    failure = _failure(143)
    assert failure["signal"] == "SIGTERM"
    assert failure["error_code"] == "agent_terminated_by_signal"
    # 即便 cgroup 有 OOM 记录，SIGTERM 也不能归因为内核 OOM killer。
    assert "不是内核 OOM killer" in failure["message"]


@pytest.mark.parametrize("returncode", [-9, 143, -15])
def test_signal_evidence_always_attached(returncode, monkeypatch):
    monkeypatch.setattr(
        wrapper,
        "_read_cgroup_memory_evidence",
        lambda: {"available": True, "memory_events": {"oom_kill": 1}},
    )
    assert _failure(returncode)["signal_evidence"] is not None


def test_no_signal_evidence_for_non_signal_failures():
    """非信号类失败不应携带该字段，避免误读。"""

    failure = _failure(0, require_submit=True)
    assert failure["error_code"] == "missing_explicit_submit"
    assert failure["signal_evidence"] is None


def test_earlier_branches_still_win(monkeypatch):
    """超时、内存超限、控制器取消的判定优先于信号归类。"""

    monkeypatch.setattr(
        wrapper,
        "_read_cgroup_memory_evidence",
        lambda: {"available": True, "memory_events": {"oom_kill": 1}},
    )
    assert _failure(-9, timed_out=True)["error_code"] == "agent_timeout_before_submit"
    assert (
        _failure(-9, cancelled_by_controller=True)["error_code"]
        == "agent_cancelled_by_research_deadline"
    )
    assert (
        _failure(-9, memory_limit_exceeded=True)["error_code"]
        == "agent_memory_limit_exceeded"
    )
