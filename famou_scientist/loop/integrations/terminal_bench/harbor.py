"""Harbor trial adapter for the independent TerminalTaskGraph.

Harbor owns the task/trial layout and official verifier.  This module only
defines the narrow bridge needed by Famou: public task view, artifact export,
public checks, and one final audit.  The concrete Harbor 0.14/FMJob runner is
injected as ``HarborTaskBackend`` so importing Famou does not require Harbor's
optional dependency environment.
"""
from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import shutil
import tomllib
from typing import Any, Mapping, Protocol, Sequence

from ...facilities.contracts import (
    ArtifactRef,
    CandidateRef,
    EvaluationRequest,
    EvaluationResult,
    RunResult,
    TaskView,
)
from ...utils import new_id


@dataclass(frozen=True)
class HarborArtifactSpec:
    """One Harbor artifact and its producer scope.

    ``service`` is intentionally kept separate from the container path.  A
    service-backed artifact is not an Agent deliverable and must be collected
    from the service export, never guessed from the Solver worktree.
    """

    path: str
    service: str | None = None

    def to_dict(self) -> dict[str, str]:
        value: dict[str, str] = {"source": self.path}
        if self.service is not None:
            value["service"] = self.service
        return value


def load_harbor_artifact_specs(task_dir: str | Path) -> tuple[HarborArtifactSpec, ...]:
    """读取 Harbor task.toml 中的 artifact contract，保留 service 来源。"""

    task_root = Path(task_dir).expanduser().resolve()
    config_path = task_root / "task.toml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Harbor task.toml 不存在: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    values = data.get("artifacts")
    if not isinstance(values, list):
        raise ValueError("Harbor task.toml 必须定义 artifacts = [绝对路径, ...]")
    specs: list[HarborArtifactSpec] = []
    for item in values:
        if isinstance(item, str):
            specs.append(HarborArtifactSpec(path=item))
        elif isinstance(item, Mapping) and isinstance(item.get("source"), str):
            service = item.get("service")
            if service is not None and (
                not isinstance(service, str) or not service.strip()
            ):
                raise ValueError("Harbor artifact service 必须是非空字符串")
            specs.append(
                HarborArtifactSpec(
                    path=str(item["source"]),
                    service=str(service).strip() if service is not None else None,
                )
            )
        else:
            raise ValueError("Harbor task.toml artifacts 必须是绝对路径或带 source 的对象")
    if any(not item.path.startswith("/") for item in specs):
        raise ValueError("Harbor artifacts 必须使用绝对容器路径")
    return tuple(specs)


def load_harbor_artifacts(task_dir: str | Path) -> tuple[str, ...]:
    """读取 artifact 路径；保留旧调用方的兼容 API。"""

    return tuple(spec.path for spec in load_harbor_artifact_specs(task_dir))


def copy_fmjob_artifacts(
    source_root: str | Path,
    *,
    artifact_paths: Sequence[str],
    destination: str | Path,
) -> Path:
    """把 FMJobSandbox 的 round export 复制成 Harbor payload。"""

    source = Path(source_root).expanduser().resolve()
    target_root = Path(destination).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"FMJob artifact export 不存在: {source}")
    target_root.mkdir(parents=True, exist_ok=True)
    for raw_path in artifact_paths:
        path = str(raw_path)
        if not path.startswith("/"):
            raise ValueError(f"artifact path 必须是绝对路径: {path!r}")
        src = (source / path.lstrip("/")).resolve()
        try:
            src.relative_to(source)
        except ValueError as exc:
            raise ValueError(f"artifact source 越界: {path!r}") from exc
        if not src.exists() or src.is_symlink():
            raise FileNotFoundError(f"FMJob artifact 缺失或为符号链接: {src}")
        dst = target_root / path.lstrip("/")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=False)
        elif src.is_file():
            shutil.copy2(src, dst)
        else:
            raise ValueError(f"artifact 类型不支持: {src}")
    return target_root


@dataclass(frozen=True)
class HarborTrialLayout:
    """Harbor trial 的路径入口。

    ``trial_dir`` 是 Harbor 提供的 canonical trial root；Famou 只在
    ``famou_dir`` 下保存控制状态。artifact/snapshot 目录必须由 Harbor
    launcher 传入，避免根据私有目录名称猜测 Harbor 版本实现。
    """

    trial_dir: Path
    task_dir: Path
    artifact_root: Path
    famou_dir: Path
    agent_task_view: Path | None = None

    @classmethod
    def from_paths(
        cls,
        *,
        trial_dir: str | Path,
        task_dir: str | Path,
        artifact_root: str | Path,
        famou_dir: str | Path | None = None,
        agent_task_view: str | Path | None = None,
    ) -> "HarborTrialLayout":
        """从 Harbor launcher 解析的路径创建布局，不复制任务源码。"""

        trial = Path(trial_dir).expanduser().resolve()
        task = Path(task_dir).expanduser().resolve()
        artifacts = Path(artifact_root).expanduser().resolve()
        control = Path(famou_dir or trial / "famou").expanduser().resolve()
        view = (
            Path(agent_task_view).expanduser().resolve()
            if agent_task_view is not None
            else None
        )
        for name, value in (("trial_dir", trial), ("task_dir", task), ("artifact_root", artifacts)):
            if not value.exists():
                raise FileNotFoundError(f"Harbor {name} 不存在: {value}")
        if view is not None and not view.exists():
            raise FileNotFoundError(f"Harbor agent task view 不存在: {view}")
        return cls(trial, task, artifacts, control, view)

    @property
    def controller_dir(self) -> Path:
        return self.famou_dir / "controller"

    @property
    def surrogate_dir(self) -> Path:
        return self.famou_dir / "surrogate"

    def round_artifact_dir(self, round_no: int) -> Path:
        return self.artifact_root / "famou" / "surrogate" / f"round_{int(round_no)}"

    def final_artifact_dir(self) -> Path:
        return self.artifact_root / "famou" / "final"

    def service_artifact_dir(self, service: str, round_no: int) -> Path:
        """Canonical CFS handoff directory for a Harbor service snapshot."""

        name = str(service).strip()
        if not name or "/" in name or name in {".", ".."}:
            raise ValueError(f"非法 Harbor service 名称: {service!r}")
        if int(round_no) < 0:
            raise ValueError(f"非法 artifact round: {round_no!r}")
        return self.artifact_root / "fmjob-service" / name / f"round_{int(round_no)}"


class HarborTaskBackend(Protocol):
    """Harbor 0.14/FMJob launcher 对 Famou 暴露的最小 backend contract。"""

    def export_artifacts(
        self,
        candidate: CandidateRef,
        *,
        artifact_paths: Sequence[str],
        destination: Path,
        artifact_specs: Sequence[HarborArtifactSpec] | None = None,
    ) -> Path:
        """从 Agent container copy-out artifacts 到 immutable CFS 目录。"""

        ...

    def preflight(self, candidate: CandidateRef, *, context: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def validate_artifact(self, artifact: ArtifactRef) -> Mapping[str, Any]:
        ...

    def public_evaluate(self, artifact: ArtifactRef) -> Mapping[str, Any]:
        ...

    def candidate_gt_evaluate(self, request: EvaluationRequest) -> Mapping[str, Any]:
        """在候选轮次运行官方 GT verifier，并返回可用于修复的完整反馈。"""

        ...

    def final_audit(self, request: EvaluationRequest) -> Mapping[str, Any]:
        """调用 Harbor official verifier；不得把结果写回 Agent view。"""

        ...


def _status(value: Mapping[str, Any]) -> str:
    if value.get("valid") is True or value.get("status") in {"passed", "valid", "ok"}:
        return "passed"
    return "failed"


def _agent_view(value: Mapping[str, Any]) -> dict[str, Any]:
    """移除 Harbor/Controller/GT 路径，只保留可公开反馈。"""

    hidden_keys = {
        "artifact",
        "artifact_ref",
        "storage_path",
        "trial_dir",
        "task_dir",
        "source_task_path",
        "ground_truth",
        "gt",
        "private",
    }

    def scrub(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): scrub(raw)
                for key, raw in item.items()
                if str(key).lower() not in hidden_keys
            }
        if isinstance(item, list):
            return [scrub(raw) for raw in item]
        return item

    result = scrub(dict(value))
    return result if isinstance(result, dict) else {}


class HarborBenchmarkFacility:
    """把 Harbor public task/artifact API 接到 TerminalTaskGraph。"""

    def __init__(
        self,
        *,
        layout: HarborTrialLayout,
        backend: HarborTaskBackend,
        task_id: str,
        artifact_paths: Sequence[str] | None = None,
    ) -> None:
        self.layout = layout
        self.backend = backend
        self.task_id = str(task_id)
        if artifact_paths is None:
            self.artifact_specs = load_harbor_artifact_specs(layout.task_dir)
            self.artifact_paths = tuple(spec.path for spec in self.artifact_specs)
        else:
            self.artifact_paths = tuple(str(path) for path in artifact_paths)
            self.artifact_specs = tuple(
                HarborArtifactSpec(path=path) for path in self.artifact_paths
            )

    def task_view(self) -> TaskView:
        view_root = self.layout.agent_task_view or self.layout.task_dir
        instruction_path = view_root / "instruction.md"
        if not instruction_path.is_file():
            raise FileNotFoundError(f"Harbor task view 缺少 instruction.md: {instruction_path}")
        return TaskView(
            task_id=self.task_id,
            public_path=str(view_root),
            instructions=instruction_path.read_text(encoding="utf-8"),
            metadata={"source": "harbor_task_view"},
        )

    def preflight(self, candidate: CandidateRef, *, context=None) -> dict[str, Any]:
        return dict(self.backend.preflight(candidate, context=dict(context or {})))

    def run(self, candidate: CandidateRef, *, context=None) -> RunResult:
        context = dict(context or {})
        round_no = int(context.get("round") or candidate.metadata.get("round") or 0)
        destination = self.layout.round_artifact_dir(round_no)
        destination.mkdir(parents=True, exist_ok=True)
        payload_dir = destination / "payload"
        exporter = self.backend.export_artifacts
        # Third-party backends written against the original contract only
        # accept artifact_paths.  Use signature inspection so a genuine
        # TypeError raised inside an exporter is not silently swallowed.
        if "artifact_specs" in inspect.signature(exporter).parameters:
            artifact_path = exporter(
                candidate,
                artifact_paths=self.artifact_paths,
                artifact_specs=self.artifact_specs,
                destination=payload_dir,
            )
        else:
            artifact_path = exporter(
                candidate,
                artifact_paths=self.artifact_paths,
                destination=payload_dir,
            )
        artifact = ArtifactRef.from_path(
            artifact_path,
            artifact_id=f"{self.task_id}:surrogate:{round_no}",
            kind="harbor_submission_artifacts",
            producer="harbor_fmjob_agent",
            metadata={
                "round": round_no,
                "artifact_paths": list(self.artifact_paths),
                "artifact_specs": [spec.to_dict() for spec in self.artifact_specs],
            },
        )
        manifest = {
            "task_id": self.task_id,
            "round": round_no,
            "artifact": artifact.to_dict(),
            "artifact_paths": list(self.artifact_paths),
            "artifact_specs": [spec.to_dict() for spec in self.artifact_specs],
        }
        destination.joinpath("manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        destination.joinpath("COMPLETE").write_text("\n", encoding="utf-8")
        return RunResult(
            run_id=f"{self.task_id}:surrogate:{round_no}",
            candidate_id=candidate.candidate_id,
            valid=True,
            artifact_ref=artifact,
            extra={"harbor_trial_dir": str(self.layout.trial_dir)},
        )

    def validate_artifact(self, artifact: ArtifactRef) -> dict[str, Any]:
        artifact.verify()
        result = dict(self.backend.validate_artifact(artifact))
        artifact.verify()
        return result

    def run_public_evaluation(self, artifact: ArtifactRef) -> dict[str, Any]:
        artifact.verify()
        result = _agent_view(self.backend.public_evaluate(artifact))
        # A registered artifact is immutable. Catch a backend that writes to
        # its path immediately instead of allowing FinalAudit to fail later
        # with an opaque hash mismatch.
        artifact.verify()
        return result

    def run_gt_evaluation(self, artifact: ArtifactRef, *, round_no: int) -> dict[str, Any]:
        method = getattr(self.backend, "candidate_gt_evaluate", None)
        if not callable(method):
            raise RuntimeError("当前 Harbor backend 未配置官方 GT candidate verifier")
        raw = dict(
            method(
                EvaluationRequest(
                    task_id=self.task_id,
                    attempt_id=f"{self.task_id}:candidate-gt:{int(round_no)}",
                    artifact_ref=artifact,
                    metadata={"candidate_round": int(round_no)},
                )
            )
        )
        artifact.verify()
        reward = (raw.get("official_metrics") or {}).get("reward")
        if raw.get("error") or (reward is None and raw.get("valid") is not True):
            return {
                "status": "verifier_error",
                "verifier": "tbs_gt",
                "error": str(raw.get("error") or "官方 GT verifier 未返回 reward"),
                "official_metrics": dict(raw.get("official_metrics") or {}),
                "stdout": str(raw.get("stdout") or ""),
                "stderr": str(raw.get("stderr") or ""),
                "ctrf": raw.get("ctrf"),
            }
        return {
            "status": "passed" if raw.get("valid") is True else "repair_required",
            "verifier": "tbs_gt",
            "reward": reward,
            "valid": raw.get("valid") is True,
            "official_metrics": dict(raw.get("official_metrics") or {}),
            "stdout": str(raw.get("stdout") or ""),
            "stderr": str(raw.get("stderr") or ""),
            "ctrf": raw.get("ctrf"),
        }

    def agent_view(self, result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
        del source
        return _agent_view(result)

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()


class HarborEvaluationFacility:
    """Harbor official verifier 的唯一 EvaluationFacility 入口。"""

    def __init__(self, *, backend: HarborTaskBackend, layout: HarborTrialLayout):
        self.backend = backend
        self.layout = layout

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        request.artifact_ref.verify()
        raw = dict(self.backend.final_audit(request))
        # FinalAudit is the last consumer of the snapshot.  Verify again
        # after the backend returns so a buggy verifier cannot silently alter
        # the evidence that is later published.
        request.artifact_ref.verify()
        metrics = raw.get("official_metrics") or raw.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        valid = raw.get("valid")
        if type(valid) is not bool:
            raise ValueError("Harbor official verifier 必须返回 bool valid")
        return EvaluationResult(
            request_id=str(raw.get("request_id") or new_id("harbor-evaluation")),
            attempt_id=request.attempt_id,
            valid=valid,
            metrics=metrics,
            stdout=str(raw.get("stdout") or ""),
            stderr=str(raw.get("stderr") or ""),
            diagnostics_public=_agent_view(raw.get("diagnostics_public") or {}),
            metadata={"harbor_trial_dir": str(self.layout.trial_dir)},
        )

    def agent_view(self, result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
        del source
        return _agent_view(result)

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()


__all__ = [
    "HarborArtifactSpec",
    "HarborBenchmarkFacility",
    "HarborEvaluationFacility",
    "HarborTaskBackend",
    "HarborTrialLayout",
    "copy_fmjob_artifacts",
    "load_harbor_artifact_specs",
    "load_harbor_artifacts",
]
