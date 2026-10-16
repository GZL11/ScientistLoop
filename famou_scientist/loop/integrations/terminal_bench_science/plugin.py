"""正式 Terminal-Bench-Science plugin entry point。"""

from ..terminal_bench.plugin import (
    HarborBenchmarkScienceAdapter,
    HarborBenchmarkScienceEvaluatorAdapter,
)

__all__ = [
    "HarborBenchmarkScienceAdapter",
    "HarborBenchmarkScienceEvaluatorAdapter",
]
