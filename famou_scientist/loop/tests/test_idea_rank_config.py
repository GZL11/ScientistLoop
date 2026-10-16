"""冲刺期 Idea 排序的触发门槛、超时预算与 Judge 配置继承。

实测 121 次 Judge 调用中 21% 因 600 秒上限被 SIGTERM，另有 31% 因待排 Idea
不足而空转、34% 因调用失败静默退回 FIFO——真正生效的只有 35%。这里覆盖三处
针对性修正。
"""
from __future__ import annotations

from typing import Any

from famou_scientist.loop.agents.workers import PromptWorkerSet
from famou_scientist.loop.runtime.orchestrator import OrchestratorConfig


def _workers_goal(idea_rank: dict[str, Any] | None) -> dict[str, Any]:
    workers: dict[str, Any] = {
        "idea": {
            "type": "agent",
            "runtime": "claude",
            "model": "claude-opus-5",
            "base_url": "https://gateway.example/v1",
            "api_key_env": "IDEA_KEY",
        }
    }
    if idea_rank is not None:
        workers["idea_rank"] = idea_rank
    return {"workers": workers}


def _worker_set(goal: dict[str, Any], tmp_path) -> PromptWorkerSet:
    """走真实构造路径，只把 Agent 适配器的创建换成记录调用。

    idea/idea_rank 都保持 type=agent，才能触发被测的继承分支；适配器本身
    被替换掉，避免测试真的去拉起 CLI。
    """
    import famou_scientist.loop.agents.workers as mod

    original = mod._create_agent_adapter
    mod._create_agent_adapter = lambda config, **kwargs: object()
    try:
        return PromptWorkerSet(goal, tmp_path)
    finally:
        mod._create_agent_adapter = original


def test_timeout_budget_raised_to_thirty_minutes():
    """默认超时从 10 分钟提到 30 分钟。"""

    config = OrchestratorConfig()
    assert config.idea_rank_judge_timeout_sec == 1_800


def test_min_items_defaults_to_three():
    """默认要求至少三条待实现 Idea 才触发排序。"""

    config = OrchestratorConfig()
    assert config.idea_rank_min_items == 3


def test_min_items_floor_is_two():
    """配置低于 2 时上抬——一条 Idea 不存在排序问题。"""

    assert OrchestratorConfig(idea_rank_min_items=1).idea_rank_min_items == 2
    assert OrchestratorConfig(idea_rank_min_items=0).idea_rank_min_items == 2


def test_min_items_accepts_override():
    """显式配置可覆盖默认门槛。"""

    assert OrchestratorConfig(idea_rank_min_items=5).idea_rank_min_items == 5


def test_invalid_config_falls_back_to_defaults():
    """非法值回退到默认，不让排序配置阻断整个 Run。"""

    config = OrchestratorConfig(
        idea_rank_judge_timeout_sec="oops",  # type: ignore[arg-type]
        idea_rank_min_items="oops",  # type: ignore[arg-type]
    )
    assert config.idea_rank_judge_timeout_sec == 1_800
    assert config.idea_rank_min_items == 3


def test_judge_inherits_idea_agent_endpoint(tmp_path):
    """Judge 只声明 type 时，运行时/模型/端点全部继承 Idea Agent。

    回归点：缺任一项都会让 Judge 调用失败，而失败是静默退回 FIFO 的。
    """

    workers = _worker_set(_workers_goal({"type": "agent"}), tmp_path)

    assert workers.idea_rank_config["runtime"] == "claude"
    assert workers.idea_rank_config["model"] == "claude-opus-5"
    assert workers.idea_rank_config["base_url"] == "https://gateway.example/v1"
    assert workers.idea_rank_config["api_key_env"] == "IDEA_KEY"


def test_judge_explicit_config_wins(tmp_path):
    """Judge 显式声明的字段不被 Idea 配置覆盖。"""

    workers = _worker_set(
        _workers_goal(
            {
                "type": "agent",
                "model": "gpt-5.5",
                "base_url": "https://judge.example/v1",
            }
        ),
        tmp_path,
    )

    assert workers.idea_rank_config["model"] == "gpt-5.5"
    assert workers.idea_rank_config["base_url"] == "https://judge.example/v1"
    # 未声明的仍然继承。
    assert workers.idea_rank_config["runtime"] == "claude"
    assert workers.idea_rank_config["api_key_env"] == "IDEA_KEY"


def test_judge_inherits_when_section_absent(tmp_path):
    """完全没有 idea_rank 段时也能拿到 Idea 的端点配置。"""

    workers = _worker_set(_workers_goal(None), tmp_path)

    assert workers.idea_rank_config["runtime"] == "claude"
    assert workers.idea_rank_config["model"] == "claude-opus-5"


def test_empty_string_treated_as_missing(tmp_path):
    """空串视同未声明，避免继承出一个不可用的端点。"""

    workers = _worker_set(
        _workers_goal({"type": "agent", "model": "", "base_url": ""}),
        tmp_path,
    )

    assert workers.idea_rank_config["model"] == "claude-opus-5"
    assert workers.idea_rank_config["base_url"] == "https://gateway.example/v1"


def test_min_remaining_is_independent_of_timeout():
    """剩余时间门槛不跟随超时上限，否则排序窗口会被压到很窄。

    回归点：门槛曾是 judge_timeout_sec + 5。把超时提到 30 分钟后，
    该式要求剩余 > 30 分钟，而触发窗口本身是"剩余 <= 60 分钟"——
    可用区间只剩 30~60 分钟这一段，错过即永不排序。
    """

    config = OrchestratorConfig()
    assert config.idea_rank_min_remaining_sec == 900
    assert config.idea_rank_judge_timeout_sec == 1_800
    # 触发窗口 3600 秒内，绝大部分时间都应允许排序。
    assert config.idea_rank_min_remaining_sec < config.idea_rank_trigger_remaining_sec / 2


def test_min_remaining_has_floor():
    """过小的值上抬，避免在最后一分钟启动跨截止线的调用。"""

    assert OrchestratorConfig(idea_rank_min_remaining_sec=5).idea_rank_min_remaining_sec == 60
