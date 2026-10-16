"""`--no-idea-generation`：resume 重跑指定 Idea 时关掉新方案产出。

resume 一个已按墙钟结束的 Run 时，队列里被重排回来的 Idea 是本次要测量的对象。
若 IdeaAgent 继续按水位产新方案，它们会抢 implement 槽位、并让"只跑这几条"的
比较失去意义。

两条边界：

1. **默认必须不变**。这个开关只服务 resume 实验，生产批次一律走默认路径。
2. **不能用 `--iterations N` 代替**。`harness/runtime.py` 会把它同时写进
   `max_benchmark_attempts` 和 `max_evaluator_submissions`，把评测预算一起掐死——
   一次工程失败就再无重试机会，而 resume 批次恰恰只有一次机会。
"""
from __future__ import annotations

import argparse

import pytest

from famou_scientist.loop.harness.cli import _build_parser
from famou_scientist.loop.harness.runtime import HarnessConfig
from famou_scientist.loop.runtime.orchestrator import Orchestrator, OrchestratorConfig


BASE = [
    "run",
    "--task-id",
    "t",
    "--run-dir",
    "/tmp/x",
    "--evaluator-channel",
    "/tmp/ch",
]


# --- CLI ------------------------------------------------------------------


def test_idea_generation_defaults_to_on():
    args = _build_parser().parse_args(BASE)
    assert args.idea_generation is True


def test_no_idea_generation_flag_turns_it_off():
    args = _build_parser().parse_args([*BASE, "--no-idea-generation"])
    assert args.idea_generation is False


def test_explicit_positive_flag_is_accepted():
    args = _build_parser().parse_args([*BASE, "--idea-generation"])
    assert args.idea_generation is True


def test_flag_uses_the_same_shape_as_pairwise_improve_search():
    """两个开关服务同一批实验，必须能一起 --no- 掉。"""

    args = _build_parser().parse_args(
        [*BASE, "--no-idea-generation", "--no-pairwise-improve-search"]
    )
    assert args.idea_generation is False
    assert args.pairwise_improve_search is False


# --- 配置贯通 -------------------------------------------------------------


def test_harness_config_defaults_to_on():
    config = HarnessConfig(
        task_id="t",
        run_dir="/tmp/x",
        problem_dir="/tmp/x/problem",
        workspace_dir="/tmp/x/workspace",
        agent_runtime="claude",
    )
    assert config.idea_generation is True


def test_orchestrator_config_defaults_to_on():
    assert OrchestratorConfig().idea_generation_enabled is True


def test_harness_passes_the_flag_to_the_orchestrator():
    """漏接一层就会静默恢复产 Idea，而实验要跑完 2 小时才看得出来。"""

    import inspect

    source = inspect.getsource(
        __import__(
            "famou_scientist.loop.harness.runtime", fromlist=["BenchmarkHarness"]
        )
    )
    assert "idea_generation_enabled=self.config.idea_generation" in source

    cli_source = inspect.getsource(
        __import__("famou_scientist.loop.harness.cli", fromlist=["_build_parser"])
    )
    assert "idea_generation=args.idea_generation" in cli_source


# --- 行为 -----------------------------------------------------------------


class _Queue:
    def __init__(self, size: int = 0):
        self._size = size

    def size(self, status=None):
        del status
        return self._size

    def list(self, status=None):
        del status
        return []


class _Queues:
    def __init__(self):
        self.benchmark_attempt = _Queue()
        self.ideaspark = _Queue()


def _orchestrator(enabled: bool):
    """只装配本用例需要的字段，避免拉起真实 workspace。"""

    obj = Orchestrator.__new__(Orchestrator)
    obj.config = OrchestratorConfig(idea_generation_enabled=enabled)
    obj.queues = _Queues()
    obj.goal_doc = {"constraints": {}}
    return obj


def test_disabled_short_circuits_before_touching_the_queue():
    """关掉后连队列都不该读——它必须是最外层的判据。"""

    obj = _orchestrator(False)

    class _Exploding:
        def size(self, status=None):
            raise AssertionError("关闭 idea 生成后不应再读队列")

    obj.queues.benchmark_attempt = _Exploding()

    assert obj._prepare_benchmark_idea_request({}) is None


def test_enabled_still_reaches_the_queue():
    obj = _orchestrator(True)
    seen = []

    class _Counting(_Queue):
        def size(self, status=None):
            seen.append(1)
            return super().size(status)

    obj.queues.benchmark_attempt = _Counting()
    obj._benchmark_attempt_limit = lambda state: 0  # 立刻返回，不需要完整 goal
    obj._prepare_benchmark_idea_request({})

    assert seen, "开启时必须走到既有的水位/上限判据"


@pytest.mark.parametrize("enabled", [True, False])
def test_flag_does_not_change_the_attempt_limit(enabled):
    """它只挡 Idea 产出，不得影响评测预算——这正是不用 --iterations 的原因。"""

    obj = _orchestrator(enabled)
    obj.goal_doc = {"constraints": {"max_evaluator_submissions": 7}}
    state = {"research_state": {"evaluator_budget": {"max_submissions": 7}}}

    assert obj._benchmark_attempt_limit(state) == 7


# --- 开放科研路径同样受控 -------------------------------------------------


def test_research_workflow_path_checks_the_same_flag():
    """benchmark 与开放科研两条产出路径必须同口径，漏一处就等于没关。"""

    import inspect

    source = inspect.getsource(Orchestrator)
    idx = source.find("not self.benchmark_managed\n            and run_ideas")
    assert idx > 0, "开放科研的 Idea 产出判据结构变了，测试需要同步"
    window = source[idx : idx + 400]
    assert "self.config.idea_generation_enabled" in window
