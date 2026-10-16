"""Bench Facility 接口及通用 Runner 适配实现。"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from ..utils import new_id
from .contracts import ArtifactRef, CandidateRef, RunResult, TaskView


class BenchmarkFacility(Protocol):
    """定义公开任务、候选执行、产物校验和公开评测边界。"""

    def task_view(self) -> TaskView:
        """返回可以暴露给 Agent 的公开任务视图。"""

        ...

    def preflight(
        self,
        candidate: CandidateRef,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行不接触隐藏数据的提交前检查。"""

        ...

    def run(
        self,
        candidate: CandidateRef,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> RunResult:
        """执行候选并产生正式评测所需 Artifact。"""

        ...

    def validate_artifact(self, artifact: ArtifactRef) -> dict[str, Any]:
        """校验 Artifact 是否符合该 benchmark 的公开提交约定。"""

        ...

    def run_public_evaluation(self, artifact: ArtifactRef) -> dict[str, Any]:
        """运行无需隐藏数据的公开检查或公开评分。"""

        ...

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """把公开结果转换为可回传 Agent 的安全视图。"""

        ...


class RunnerBenchmarkFacility:
    """把通用 Runner 与公开检查器包装成 Bench Facility。"""

    def __init__(
        self,
        runner: Any,
        public_adapter: Any,
        *,
        task_id: str = "task",
    ) -> None:
        """保存公开侧组件；正式评分不会由此包装层触发。"""

        self.runner = runner
        self.public_adapter = public_adapter
        self.task_id = str(task_id)

    def task_view(self) -> TaskView:
        """为通用 Runner 返回最小公开任务视图。"""

        return TaskView(task_id=self.task_id)

    @staticmethod
    def _payload(
        candidate: CandidateRef,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """把 CandidateRef 补入 Runner 需要的字典上下文。"""

        payload = dict(context or {})
        payload.setdefault("candidate_id", candidate.candidate_id)
        payload["method_dir"] = candidate.code_path
        payload["worktree"] = candidate.code_path
        if candidate.output_path:
            payload["candidate_output_dir"] = candidate.output_path
        if candidate.evidence_path:
            payload["candidate_evidence_dir"] = candidate.evidence_path
        if candidate.entrypoint:
            payload["entrypoint"] = candidate.entrypoint
        else:
            payload.pop("entrypoint", None)
        return payload

    def preflight(
        self,
        candidate: CandidateRef,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 Runner 的公开 preflight。"""

        return self.runner.preflight(self._payload(candidate, context))

    def run(
        self,
        candidate: CandidateRef,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> RunResult:
        """调用 Runner，并把路径结果升级成带哈希的 ArtifactRef。"""

        raw = self.runner.run(self._payload(candidate, context))
        if not isinstance(raw, dict):
            raise TypeError(
                f"experiment runner returned {type(raw).__name__}, expected dict"
            )
        artifact_ref = None
        artifact_path = raw.get("artifact") or raw.get("output_artifact")
        if raw.get("valid") is True and artifact_path:
            artifact_ref = ArtifactRef.from_path(
                str(artifact_path),
                artifact_id=str(raw.get("id") or new_id("artifact")),
                kind=str(raw.get("artifact_kind") or "submission_bundle"),
                producer=str(raw.get("source") or "experiment_runner"),
                metadata={"candidate_id": candidate.candidate_id},
            )
        known = {
            "id",
            "candidate_id",
            "valid",
            "artifact",
            "output_artifact",
            "returncode",
            "timed_out",
            "stdout",
            "stderr",
            "error",
            "duration_ms",
        }
        return RunResult(
            run_id=str(raw.get("id") or new_id("run")),
            candidate_id=candidate.candidate_id,
            valid=raw.get("valid") is True,
            artifact_ref=artifact_ref,
            returncode=raw.get("returncode"),
            timed_out=bool(raw.get("timed_out")),
            stdout=str(raw.get("stdout") or ""),
            stderr=str(raw.get("stderr") or ""),
            error=str(raw["error"]) if raw.get("error") else None,
            duration_ms=raw.get("duration_ms"),
            extra={key: value for key, value in raw.items() if key not in known},
        )

    def validate_artifact(self, artifact: ArtifactRef) -> dict[str, Any]:
        """先验证内容哈希，再调用公开检查器的格式校验。"""

        artifact.verify()
        return self.public_adapter.validate_artifact(artifact.storage_path)

    def run_public_evaluation(self, artifact: ArtifactRef) -> dict[str, Any]:
        """调用公开检查器的评测方法。"""

        artifact.verify()
        return self.public_adapter.run_public_eval(artifact.storage_path)

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """复用公开检查器的字段脱敏规则。"""

        return self.public_adapter.agent_view(result, source=source)


__all__ = ["BenchmarkFacility", "RunnerBenchmarkFacility"]
