"""Harbor/Terminal-Bench plugin entry points."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Mapping

from ...plugins import AdapterContext, FinalizationRequest, FinalizationResult
from .harbor import HarborBenchmarkFacility, HarborEvaluationFacility, HarborTrialLayout


def _load_backend(spec: str, *, layout: HarborTrialLayout, options: Mapping[str, Any]) -> Any:
    module_name, separator, attribute = str(spec).partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("--harbor-backend 必须是 module:Class")
    provider = getattr(importlib.import_module(module_name), attribute)
    if isinstance(provider, type):
        try:
            return provider(layout=layout, options=dict(options))
        except TypeError:
            return provider()
    if callable(provider):
        return provider(layout=layout, options=dict(options))
    return provider


def _layout(context: AdapterContext) -> HarborTrialLayout:
    options = context.options
    trial_dir = Path(str(options.get("harbor_trial_dir") or context.run_dir))
    artifact_root = options.get("harbor_artifact_root")
    if artifact_root is None:
        raise ValueError(
            "terminal_bench_science/harbor 需要 --harbor-artifact-root；"
            "该路径必须由 Harbor launcher 提供，不能猜测私有目录"
        )
    return HarborTrialLayout.from_paths(
        trial_dir=trial_dir,
        task_dir=context.problem_dir,
        artifact_root=Path(str(artifact_root)),
        famou_dir=options.get("harbor_famou_dir"),
        agent_task_view=options.get("harbor_agent_task_view"),
    )


class HarborBenchmarkScienceAdapter:
    """创建 Terminal-Bench-Science 使用的公开 Harbor facility。"""

    name = "terminal_bench_science"

    def create(self, context: AdapterContext) -> HarborBenchmarkFacility:
        layout = _layout(context)
        backend_spec = context.options.get("harbor_backend")
        if not backend_spec:
            raise ValueError("terminal_bench_science adapter 需要 --harbor-backend module:Class")
        backend = _load_backend(str(backend_spec), layout=layout, options=context.options)
        return HarborBenchmarkFacility(
            layout=layout,
            backend=backend,
            task_id=context.task_id,
        )


class HarborBenchmarkScienceEvaluatorAdapter:
    """Terminal-Bench-Science 只在 FinalAudit 调用 Harbor official verifier。"""

    name = "terminal_bench_science"

    def create(self, context: AdapterContext, transport: Any) -> HarborEvaluationFacility:
        del transport
        layout = _layout(context)
        backend_spec = context.options.get("harbor_backend")
        if not backend_spec:
            raise ValueError("terminal_bench_science evaluator 需要 --harbor-backend module:Class")
        backend = _load_backend(str(backend_spec), layout=layout, options=context.options)
        return HarborEvaluationFacility(backend=backend, layout=layout)

    def finalize(
        self,
        context: AdapterContext,
        facility: HarborEvaluationFacility,
        request: FinalizationRequest,
    ) -> FinalizationResult | None:
        del context, facility, request
        # TerminalTaskGraph 的 FinalAudit 已经直接调用 EvaluationFacility.evaluate；
        # 不再通过旧 SOTA Harness 的 post-hoc finalize 重复执行 Harbor verifier。
        return None


# 兼容之前实验命令的旧类名；正式注册名使用 terminal_bench_science。
HarborBenchmarkAdapter = HarborBenchmarkScienceAdapter
HarborEvaluatorAdapter = HarborBenchmarkScienceEvaluatorAdapter

__all__ = [
    "HarborBenchmarkAdapter",
    "HarborBenchmarkScienceAdapter",
    "HarborEvaluatorAdapter",
    "HarborBenchmarkScienceEvaluatorAdapter",
]
