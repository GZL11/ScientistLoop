"""NatureBench Benchmark 与 Evaluator 插件入口。"""
from __future__ import annotations

from typing import Any

from ...utils import atomic_write_json
from ...plugins import AdapterContext, FinalizationRequest, FinalizationResult
from .benchmark import NatureBenchBenchmarkFacility, NatureBenchExperimentRunner
from .evaluation import NatureBenchEvaluationFacility


class NatureBenchBenchmarkAdapter:
    """把 NatureBench 公开 task package 装配成 Benchmark Facility。"""

    name = "naturebench"

    def create(self, context: AdapterContext) -> NatureBenchBenchmarkFacility:
        """创建 NatureBench 候选执行和 Artifact 生成设施。"""

        timeout_sec = float(context.options.get("experiment_timeout_sec") or 3600)
        benchmark_name = str(
            context.options.get("benchmark_name") or f"naturebench/{context.task_id}"
        )
        runner = NatureBenchExperimentRunner(
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
        return NatureBenchBenchmarkFacility(
            runner,
            run_dir=context.run_dir,
            benchmark_name=benchmark_name,
            task_id=context.task_id,
        )


class NatureBenchEvaluatorAdapter:
    """把 NatureBench 官方 evaluator 与 Judge 装配成可信评分设施。"""

    name = "naturebench"

    def create(
        self,
        context: AdapterContext,
        transport: Any,
    ) -> NatureBenchEvaluationFacility:
        """创建通过签名 transport 调用可信 Evaluator 的评分设施。"""

        benchmark_name = str(
            context.options.get("benchmark_name") or f"naturebench/{context.task_id}"
        )
        return NatureBenchEvaluationFacility(
            transport,
            run_dir=context.run_dir,
            workspace_dir=context.workspace_dir,
            benchmark_name=benchmark_name,
        )

    def finalize(
        self,
        context: AdapterContext,
        facility: NatureBenchEvaluationFacility,
        request: FinalizationRequest,
    ) -> FinalizationResult | None:
        """按配置对最佳冻结 attempt 调用 NatureBench 官方 Validity Judge。"""

        if not bool(context.options.get("finalize_evaluation")):
            return None
        raw = facility.request_operation(
            operation="validity_judge",
            attempt_id=request.best_attempt_id,
        )
        verdict = raw.get("judge")
        if not isinstance(verdict, dict):
            raise ValueError("trusted response contains no NatureBench judge verdict")
        is_valid = verdict.get("is_valid")
        reason = verdict.get("reason")
        if is_valid is not None and type(is_valid) is not bool:
            raise ValueError("NatureBench judge is_valid must be bool or null")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("NatureBench judge reason must be a non-empty string")
        result = FinalizationResult(
            valid=is_valid,
            reason=reason.strip(),
            invalidate_primary_score=is_valid is False,
            extra={
                **verdict,
                "adapter": self.name,
                "operation": "validity_judge",
                "expbank_attempt_id": request.best_attempt_id,
                "transport_request_id": raw.get("request_id"),
            },
        )
        # 这是 NatureBench 的官方兼容文件名，由具体插件而不是 Harness Core 负责。
        atomic_write_json(
            context.run_dir / "controller" / "judge_verdict.json",
            result.to_dict(),
        )
        return result


__all__ = ["NatureBenchBenchmarkAdapter", "NatureBenchEvaluatorAdapter"]
