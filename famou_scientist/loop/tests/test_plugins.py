"""Agent、Benchmark 与 Evaluator 插件装配测试。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from famou_scientist.loop.agents.workers import PromptWorkerSet
from famou_scientist.loop.facilities import TaskView
from famou_scientist.loop.harness.runtime import BenchmarkHarness, HarnessConfig
from famou_scientist.loop.plugins import (
    AdapterContext,
    FinalizationRequest,
    FinalizationResult,
    available_adapters,
    load_adapter,
    register_adapter,
)


class _AgentInstance:
    """记录测试 Agent Adapter 收到的配置。"""

    def __init__(self, config: Mapping[str, Any]):
        """保存不可变配置副本。"""

        self.config = dict(config)


class _AgentAdapter:
    """用于验证角色节点不依赖内置 CLI Agent 的测试 Adapter。"""

    name = "test-agent-adapter"

    def create(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: str | Path | None = None,
    ) -> _AgentInstance:
        """创建只记录配置的测试 Agent。"""

        del config_dir
        return _AgentInstance(config)


class _BenchmarkFacility:
    """提供最小公开 TaskView 的测试 Benchmark Facility。"""

    def __init__(self, context: AdapterContext):
        """保存插件装配上下文。"""

        self.context = context

    def task_view(self) -> TaskView:
        """返回不包含任何 NatureBench 字段的公开任务。"""

        return TaskView(
            task_id=self.context.task_id,
            public_path=str(self.context.problem_dir),
            metadata={
                "entrypoint": "solve.sh",
                "primary_metric": "best_k_mean",
            },
        )


class _BenchmarkAdapter:
    """用于验证 Harness Benchmark 插件装配的测试 Adapter。"""

    name = "test-benchmark-adapter"

    def create(self, context: AdapterContext) -> _BenchmarkFacility:
        """创建测试 Benchmark Facility。"""

        return _BenchmarkFacility(context)


class _EvaluationFacility:
    """保存测试 evaluator transport，不执行正式评分。"""

    def __init__(self, transport: Any):
        """保存 transport 引用。"""

        self.transport = transport


class _EvaluatorAdapter:
    """用于验证 Harness Evaluator 插件装配的测试 Adapter。"""

    name = "test-evaluator-adapter"

    def create(
        self,
        context: AdapterContext,
        transport: Any,
    ) -> _EvaluationFacility:
        """创建不依赖 Benchmark 实现的测试评分设施。"""

        del context
        return _EvaluationFacility(transport)

    def finalize(
        self,
        context: AdapterContext,
        facility: _EvaluationFacility,
        request: FinalizationRequest,
    ) -> FinalizationResult | None:
        """测试 Adapter 不提供后验评测。"""

        del context, facility, request
        return None


class _Transport:
    """提供 Harness 构造阶段所需的占位可信 transport。"""

    def close(self) -> None:
        """结束占位 transport。"""


def test_builtin_adapter_registry_exposes_three_facility_types() -> None:
    """内置注册表应独立发现 Agent、Benchmark 和 Evaluator Adapter。"""

    assert "cli" in available_adapters("agent")
    assert "naturebench" in available_adapters("benchmark")
    assert "naturebench" in available_adapters("evaluator")
    assert load_adapter("agent", "cli").name == "cli"


def test_prompt_workers_create_agent_through_registered_adapter(tmp_path: Path) -> None:
    """Idea/Implement 角色应通过 Agent Adapter 创建而非写死 CLI 类。"""

    register_adapter("agent", "test-agent-adapter", _AgentAdapter())
    goal = {
        "workflow": {"type": "benchmark_managed"},
        "workers": {
            "idea": {
                "type": "agent",
                "adapter": "test-agent-adapter",
            },
            "implement": {"type": "single_call"},
        },
    }
    workers = PromptWorkerSet(goal, tmp_path, llm=object())

    assert isinstance(workers.idea_agent, _AgentInstance)
    assert workers.idea_agent.config["role"] == "idea"


def test_harness_assembles_non_naturebench_plugins(tmp_path: Path) -> None:
    """Harness 应能正交装配任意 Benchmark 与 Evaluator Adapter。"""

    register_adapter("benchmark", "test-benchmark-adapter", _BenchmarkAdapter())
    register_adapter("evaluator", "test-evaluator-adapter", _EvaluatorAdapter())
    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    transport = _Transport()
    harness = BenchmarkHarness(
        HarnessConfig(
            task_id="custom-task",
            run_dir=tmp_path / "run",
            problem_dir=problem,
            workspace_dir=tmp_path / "run" / "workspace",
            agent_runtime="custom-runtime",
            benchmark_adapter="test-benchmark-adapter",
            evaluator_adapter="test-evaluator-adapter",
        ),
        transport,
    )

    assert isinstance(harness.benchmark_facility, _BenchmarkFacility)
    assert isinstance(harness.evaluation_facility, _EvaluationFacility)
    assert harness.evaluation_facility.transport is transport
    assert harness._goal_doc()["benchmark_task"]["contract"] == {
        "entrypoint": "solve.sh",
        "primary_metric": "best_k_mean",
    }
    assert harness._goal_doc()["benchmarks"][0]["official_metric"] == {
        "name": "best_k_mean",
        "direction": "higher_is_better",
    }


def test_finalization_result_preserves_normalized_and_adapter_fields() -> None:
    """通用收尾结果应同时保存稳定字段和 Adapter 原始证据。"""

    value = FinalizationResult(
        valid=False,
        reason="invalid shortcut",
        invalidate_primary_score=True,
        extra={"model": "judge-model"},
    ).to_dict()

    assert value["valid"] is False
    assert value["is_valid"] is False
    assert value["invalidate_primary_score"] is True
    assert value["model"] == "judge-model"
