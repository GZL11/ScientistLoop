"""三类设施之间传递的稳定值对象。"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


def _resolved_path(value: str | Path, *, field_name: str) -> Path:
    """解析必须存在且不能是符号链接的受控路径。"""

    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError(f"{field_name} 不能是符号链接: {path}")
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{field_name} 不存在: {resolved}")
    return resolved


def artifact_sha256(path: str | Path) -> str:
    """计算文件或目录的确定性哈希，并拒绝目录中的符号链接。"""

    root = _resolved_path(path, field_name="artifact")
    digest = hashlib.sha256()
    if root.is_file():
        digest.update(b"file\0")
        with root.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if not root.is_dir():
        raise ValueError(f"artifact 必须是普通文件或目录: {root}")

    digest.update(b"directory\0")
    for child in sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        if child.is_symlink():
            raise ValueError(f"artifact 目录不能包含符号链接: {child}")
        relative = child.relative_to(root).as_posix().encode("utf-8")
        if child.is_dir():
            digest.update(b"d\0" + relative + b"\0")
            continue
        if not child.is_file():
            raise ValueError(f"artifact 目录包含不支持的文件类型: {child}")
        digest.update(b"f\0" + relative + b"\0")
        with child.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class TaskView:
    """允许 Agent 读取的公开任务视图，不包含 evaluator 私有信息。"""

    task_id: str
    public_path: str | None = None
    instructions: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化字典。"""

        return asdict(self)


@dataclass(frozen=True)
class CandidateRef:
    """引用 Agent 已冻结的候选源码，而不规定语言和执行入口。"""

    candidate_id: str
    code_path: str
    output_path: str | None = None
    evidence_path: str | None = None
    entrypoint: str | None = None
    producer: str = "agent"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CandidateRef":
        """从现有队列 payload 构造设施边界对象。"""

        candidate_id = str(
            payload.get("candidate_id")
            or payload.get("branch_id")
            or payload.get("id")
            or "candidate"
        )
        code_value = payload.get("method_dir") or payload.get("worktree")
        if not code_value:
            artifact = Path(str(payload.get("artifact") or "")).expanduser()
            code_value = artifact.parent if artifact.name else artifact
        code_path = _resolved_path(code_value, field_name="candidate code")
        entrypoint_value = payload.get("entrypoint")
        entrypoint = None
        if entrypoint_value:
            entrypoint_path = Path(str(entrypoint_value)).expanduser()
            if not entrypoint_path.is_absolute():
                entrypoint_path = code_path / entrypoint_path
            entrypoint = str(entrypoint_path.resolve())
        return cls(
            candidate_id=candidate_id,
            code_path=str(code_path),
            output_path=(
                str(Path(str(payload["candidate_output_dir"])).expanduser().resolve())
                if payload.get("candidate_output_dir")
                else None
            ),
            evidence_path=(
                str(Path(str(payload["candidate_evidence_dir"])).expanduser().resolve())
                if payload.get("candidate_evidence_dir")
                else None
            ),
            entrypoint=entrypoint,
            producer=str(payload.get("implementation_type") or "agent"),
            metadata={
                "branch_id": payload.get("branch_id") or payload.get("id"),
                "idea_id": payload.get("idea_id"),
                "actor_id": payload.get("actor_id"),
                "revision": payload.get("revision"),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化字典。"""

        return asdict(self)


@dataclass(frozen=True)
class ArtifactRef:
    """引用 Bench 产生的不可变评测产物。"""

    artifact_id: str
    kind: str
    storage_path: str
    sha256: str
    producer: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        artifact_id: str,
        kind: str = "submission_bundle",
        producer: str = "benchmark",
        metadata: Mapping[str, Any] | None = None,
    ) -> "ArtifactRef":
        """校验一个受控路径并创建带内容哈希的引用。"""

        resolved = _resolved_path(path, field_name="artifact")
        return cls(
            artifact_id=str(artifact_id),
            kind=str(kind),
            storage_path=str(resolved),
            sha256=artifact_sha256(resolved),
            producer=str(producer),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRef":
        """从持久化字典恢复引用。"""

        return cls(
            artifact_id=str(value.get("artifact_id") or value.get("id") or "artifact"),
            kind=str(value.get("kind") or "submission_bundle"),
            storage_path=str(value.get("storage_path") or value.get("path") or ""),
            sha256=str(value.get("sha256") or ""),
            producer=str(value.get("producer") or "benchmark"),
            metadata=dict(value.get("metadata") or {}),
        )

    def verify(self) -> None:
        """确认当前内容仍与引用创建时完全一致。"""

        actual = artifact_sha256(self.storage_path)
        if actual != self.sha256:
            raise ValueError(
                f"artifact 内容已变化: expected={self.sha256}, actual={actual}"
            )

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化字典。"""

        return asdict(self)


@dataclass(frozen=True)
class RunResult:
    """Bench 执行 Candidate 后返回的规范化结果。"""

    run_id: str
    candidate_id: str
    valid: bool
    artifact_ref: ArtifactRef | None = None
    returncode: int | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    duration_ms: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回兼容现有证据链的字典。"""

        result = asdict(self)
        result.update(self.extra)
        result["id"] = self.run_id
        result["artifact"] = (
            self.artifact_ref.storage_path if self.artifact_ref else ""
        )
        return result


@dataclass(frozen=True)
class EvaluationRequest:
    """Controller 发给隐藏评测设施的唯一正式请求。"""

    task_id: str
    attempt_id: str
    artifact_ref: ArtifactRef
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回可审计字典。"""

        return asdict(self)


@dataclass(frozen=True)
class EvaluationResult:
    """隐藏或官方 evaluator 返回的规范化结果。"""

    request_id: str
    attempt_id: str
    valid: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    diagnostics_public: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回兼容正式评分证据格式的字典。"""

        result = asdict(self)
        result.update(self.metadata)
        result["source"] = "official_evaluator"
        result["official_metrics"] = dict(self.metrics)
        return result


__all__ = [
    "ArtifactRef",
    "CandidateRef",
    "EvaluationRequest",
    "EvaluationResult",
    "RunResult",
    "TaskView",
    "artifact_sha256",
]
