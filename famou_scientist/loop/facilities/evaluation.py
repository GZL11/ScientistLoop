"""隐藏 Evaluation Facility 接口及通用 Adapter 适配实现。"""
from __future__ import annotations

from typing import Any, Protocol

from ..utils import new_id
from .contracts import EvaluationRequest, EvaluationResult


class EvaluationFacility(Protocol):
    """定义只接收受控 ArtifactRef 的隐藏或官方评分边界。"""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """对 Controller 选定的 Artifact 执行一次正式评分。"""

        ...

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """生成可安全回传给 Agent 的正式结果视图。"""

        ...

    def close(self) -> None:
        """释放 evaluator 客户端资源。"""

        ...


class AdapterEvaluationFacility:
    """把通用 BenchmarkAdapter 的正式评分能力包装成 Evaluation Facility。"""

    def __init__(self, adapter: Any):
        """保存正式评分 Adapter；该包装层不会执行公开评测。"""

        self.adapter = adapter

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """验证 Artifact 未变化后调用正式 evaluator。"""

        request.artifact_ref.verify()
        raw = self.adapter.run_official_eval(request.artifact_ref.storage_path)
        if not isinstance(raw, dict):
            raise TypeError(
                f"official evaluator returned {type(raw).__name__}, expected dict"
            )
        metrics = raw.get("official_metrics")
        if not isinstance(metrics, dict):
            metrics = (
                raw.get("metrics")
                if isinstance(raw.get("metrics"), dict)
                else {}
            )
        known = {
            "request_id",
            "attempt_id",
            "valid",
            "official_metrics",
            "metrics",
            "stdout",
            "stderr",
            "extra",
            "diagnostics_public",
            "error",
        }
        metadata = {key: value for key, value in raw.items() if key not in known}
        metadata.setdefault("artifact", request.artifact_ref.storage_path)
        metadata.setdefault("benchmark", raw.get("benchmark"))
        return EvaluationResult(
            request_id=str(raw.get("request_id") or new_id("evaluation")),
            attempt_id=str(raw.get("attempt_id") or request.attempt_id),
            valid=raw.get("valid") is True,
            metrics=metrics,
            stdout=str(raw.get("stdout") or ""),
            stderr=str(raw.get("stderr") or ""),
            extra=dict(raw.get("extra") or {}),
            diagnostics_public=dict(raw.get("diagnostics_public") or {}),
            error=str(raw["error"]) if raw.get("error") else None,
            metadata=metadata,
        )

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """复用 Adapter 的正式结果脱敏规则。"""

        return self.adapter.agent_view(result, source=source)

    def close(self) -> None:
        """关闭 Adapter（若其提供 close）。"""

        close = getattr(self.adapter, "close", None)
        if callable(close):
            close()


__all__ = ["AdapterEvaluationFacility", "EvaluationFacility"]
