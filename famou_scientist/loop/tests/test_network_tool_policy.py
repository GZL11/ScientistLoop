"""联网工具的授予边界。

回归点：`allowed_tools` 曾把 WebSearch/WebFetch 硬编码进 claude 的
`--allowedTools`，对所有 benchmark 一律生效。NatureBench 明确禁止联网，
一旦 Agent 能检索到论文原文或官方结果，成绩即不可采信——而这种泄漏在
事后判定里很难识别。默认关闭，需要联网的 benchmark 显式开启。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from famou_scientist.loop.execution.cli_agent_wrapper import build_cli_argv, parse_args


def _args(role: str = "implement", allow_network: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        runtime="claude",
        binary="claude",
        extra_arg=[],
        worktree=Path("/tmp/worktree"),
        title="t",
        model="claude-opus-5",
        agent=None,
        auto_approve=True,
        role=role,
        profile=None,
        allow_network_tools=allow_network,
    )


def _allowed_tools(argv: list[str]) -> str:
    for item in argv:
        if item.startswith("--allowedTools="):
            return item.split("=", 1)[1]
    raise AssertionError(f"--allowedTools not found in {argv}")


@pytest.mark.parametrize(
    "role", ["idea", "idea_rank", "experience_summary", "implement"]
)
def test_network_tools_off_by_default(role):
    """默认不授予联网工具——这是 NatureBench 的合规底线。"""

    tools = _allowed_tools(build_cli_argv(_args(role), "p", Path("/tmp/l")))
    assert "WebSearch" not in tools
    assert "WebFetch" not in tools


def test_idea_roles_stay_read_only():
    """Idea 侧不得获得执行权限：只产出方案，不跑训练。"""

    for role in ("idea", "idea_rank", "experience_summary"):
        tools = _allowed_tools(build_cli_argv(_args(role), "p", Path("/tmp/l")))
        assert tools == "Read,Edit"


def test_implement_keeps_execution_tools():
    tools = _allowed_tools(build_cli_argv(_args("implement"), "p", Path("/tmp/l")))
    assert tools == "Read,Write,Edit,Bash"


@pytest.mark.parametrize("role", ["idea", "implement"])
def test_network_tools_granted_when_enabled(role):
    """允许联网的 benchmark 显式开启后才拿到 WebSearch/WebFetch。"""

    tools = _allowed_tools(
        build_cli_argv(_args(role, allow_network=True), "p", Path("/tmp/l"))
    )
    assert "WebSearch" in tools
    assert "WebFetch" in tools
    # 开启联网不应顺带放宽执行权限边界。
    assert ("Bash" in tools) is (role == "implement")


def test_flag_defaults_to_false_when_absent():
    """命令行未传该开关时解析为 False，不依赖调用方显式传 --no-*。"""

    parsed = parse_args(
        [
            "--runtime",
            "claude",
            "--binary",
            "claude",
            "--input",
            "/tmp/in.json",
            "--output",
            "/tmp/out.json",
            "--instruction",
            "/tmp/i.md",
            "--worktree",
            "/tmp/wt",
            "--logs-dir",
            "/tmp/logs",
            "--outputs-dir",
            "/tmp/outputs",
            "--title",
            "t",
            "--role",
            "idea",
        ]
    )
    assert parsed.allow_network_tools is False


def test_missing_attribute_defaults_to_no_network():
    """构造 Namespace 时漏掉该字段，也必须落在"不联网"这一侧。

    默认值决定合规性，不能依赖每个调用方都记得设置。
    """

    import argparse

    ns = argparse.Namespace(
        runtime="claude",
        binary="claude",
        extra_arg=[],
        worktree=Path("/tmp/worktree"),
        title="t",
        model="m",
        agent=None,
        auto_approve=True,
        role="implement",
        profile=None,
    )  # 故意不设 allow_network_tools
    tools = _allowed_tools(build_cli_argv(ns, "p", Path("/tmp/l")))
    assert "WebSearch" not in tools and "WebFetch" not in tools
