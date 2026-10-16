"""SciModelingBench integration for benchmark-managed Famou loops."""

from .plugin import (
    SciModelingBenchBenchmarkAdapter,
    SciModelingBenchEvaluatorAdapter,
)

__all__ = [
    "SciModelingBenchBenchmarkAdapter",
    "SciModelingBenchEvaluatorAdapter",
]
