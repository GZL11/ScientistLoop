"""Agent、Benchmark 与 Evaluator 插件之间的稳定装配契约。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class AdapterContext:
    """向 Adapter 提供受控运行上下文，不包含其他设施的实现细节。"""

    task_id: str
    run_dir: Path
    problem_dir: Path
    workspace_dir: Path
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalizationRequest:
    """描述一次任务结束后的可信评测收尾请求。"""

    task_id: str
    best_attempt_id: str
    best_score: float | None
    run_dir: Path
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalizationResult:
    """表示后验合法性检查或其他最终评测阶段的统一结果。"""

    valid: bool | None
    reason: str
    invalidate_primary_score: bool = False
    metrics: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可持久化的评测收尾结果。"""

        value = asdict(self)
        details = dict(self.extra)
        for key, item in details.items():
            value.setdefault(key, item)
        # 兼容已有 Judge 消费方，同时保留通用 valid 字段。
        value["is_valid"] = self.valid
        return value


class AgentAdapter(Protocol):
    """把统一 Agent 配置转换为可执行的 Idea/Implement Agent。

    Adapter 应在标准结果的 ``telemetry`` 中返回本次激活的增量 usage、费用、
    Session 和轨迹引用。缺失字段必须保持为空，不能由 Adapter 猜测价格。
    """

    name: str

    def create(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: str | Path | None = None,
    ) -> Any:
        """创建一个遵守 Famou Agent Runtime 契约的实例。"""

        ...


class BenchmarkAdapter(Protocol):
    """把外部公开任务转换为 Famou Benchmark Facility。"""

    name: str

    def create(self, context: AdapterContext) -> Any:
        """创建只接触公开题面和候选产物的 Benchmark Facility。"""

        ...


class EvaluatorAdapter(Protocol):
    """把外部可信评分设施转换为 Famou Evaluation Facility。"""

    name: str

    def create(self, context: AdapterContext, transport: Any) -> Any:
        """创建只接收受控 ArtifactRef 的 Evaluation Facility。"""

        ...

    def finalize(
        self,
        context: AdapterContext,
        facility: Any,
        request: FinalizationRequest,
    ) -> FinalizationResult | None:
        """执行可选的任务级后验评测；不需要时返回空值。"""

        ...


__all__ = [
    "AdapterContext",
    "AgentAdapter",
    "BenchmarkAdapter",
    "EvaluatorAdapter",
    "FinalizationRequest",
    "FinalizationResult",
]
