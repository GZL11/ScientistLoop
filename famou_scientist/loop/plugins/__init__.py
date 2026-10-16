"""Famou 可插拔 Agent、Benchmark 与 Evaluator 装配接口。"""
from .contracts import (
    AdapterContext,
    AgentAdapter,
    BenchmarkAdapter,
    EvaluatorAdapter,
    FinalizationRequest,
    FinalizationResult,
)
from .registry import available_adapters, load_adapter, register_adapter

__all__ = [
    "AdapterContext",
    "AgentAdapter",
    "BenchmarkAdapter",
    "EvaluatorAdapter",
    "FinalizationRequest",
    "FinalizationResult",
    "available_adapters",
    "load_adapter",
    "register_adapter",
]
