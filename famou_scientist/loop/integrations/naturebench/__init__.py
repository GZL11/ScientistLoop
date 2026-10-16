"""NatureBench 公开任务、可信 evaluator、轨迹投影与 Judge 适配。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .plugin import NatureBenchBenchmarkAdapter, NatureBenchEvaluatorAdapter

if TYPE_CHECKING:
    from .judge_adapter import NatureBenchJudgeAdapter
    from .trajectory_adapter import NatureBenchTrajectoryAdapter

__all__ = [
    "NatureBenchBenchmarkAdapter",
    "NatureBenchEvaluatorAdapter",
    "NatureBenchJudgeAdapter",
    "NatureBenchTrajectoryAdapter",
]


def __getattr__(name: str) -> Any:
    """按需加载仅存在于可信 Evaluator 快照中的 Judge 与轨迹适配器。"""
    if name == "NatureBenchJudgeAdapter":
        from .judge_adapter import NatureBenchJudgeAdapter

        return NatureBenchJudgeAdapter
    if name == "NatureBenchTrajectoryAdapter":
        from .trajectory_adapter import NatureBenchTrajectoryAdapter

        return NatureBenchTrajectoryAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
