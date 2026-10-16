"""SciModelingBench Benchmark and Evaluator plugin entry points."""
from __future__ import annotations

from typing import Any

from ...plugins import AdapterContext, FinalizationRequest, FinalizationResult
from .benchmark import (
    SciModelingBenchBenchmarkFacility,
    SciModelingBenchSubmissionRunner,
)
from .evaluation import SciModelingBenchEvaluationFacility


class SciModelingBenchBenchmarkAdapter:
    """Create the public SciModelingBench Benchmark Facility."""

    name = "scimodelingbench"

    def create(self, context: AdapterContext) -> SciModelingBenchBenchmarkFacility:
        """Create a public-only candidate submission runner."""

        timeout_sec = float(context.options.get("experiment_timeout_sec") or 900)
        benchmark_name = str(
            context.options.get("benchmark_name") or f"scimodelingbench/{context.task_id}"
        )
        runner = SciModelingBenchSubmissionRunner(
            context.run_dir,
            context.problem_dir,
            task_id=context.task_id,
            timeout_sec=timeout_sec,
            memory_limit_bytes=(
                int(context.options["experiment_memory_limit_bytes"])
                if context.options.get("experiment_memory_limit_bytes") is not None
                else None
            ),
            agent_uid=(
                int(context.options["agent_uid"])
                if context.options.get("agent_uid") is not None
                else None
            ),
            agent_gid=(
                int(context.options["agent_gid"])
                if context.options.get("agent_gid") is not None
                else None
            ),
        )
        return SciModelingBenchBenchmarkFacility(
            runner,
            run_dir=context.run_dir,
            benchmark_name=benchmark_name,
        )


class SciModelingBenchEvaluatorAdapter:
    """Create the trusted SciModelingBench Evaluation Facility."""

    name = "scimodelingbench"

    def create(
        self,
        context: AdapterContext,
        transport: Any,
    ) -> SciModelingBenchEvaluationFacility:
        """Create an evaluator proxy backed by a trusted transport."""

        benchmark_name = str(
            context.options.get("benchmark_name") or f"scimodelingbench/{context.task_id}"
        )
        return SciModelingBenchEvaluationFacility(
            transport,
            run_dir=context.run_dir,
            workspace_dir=context.workspace_dir,
            benchmark_name=benchmark_name,
        )

    def finalize(
        self,
        context: AdapterContext,
        facility: SciModelingBenchEvaluationFacility,
        request: FinalizationRequest,
    ) -> FinalizationResult | None:
        """SciModelingBench has no post-hoc LLM judge phase."""

        del context, facility, request
        return None


__all__ = [
    "SciModelingBenchBenchmarkAdapter",
    "SciModelingBenchEvaluatorAdapter",
]
