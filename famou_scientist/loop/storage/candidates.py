"""保存进入实验与评测阶段的不可变候选版本。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..utils import atomic_write_json, new_id, now_ms, read_json, safe_name, sha256_file
from ..domain.status import LoopStatus


_SNAPSHOT_EXCLUDES = {
    ".git",
    ".famou",
    "__pycache__",
    "benchmark_task",
    "famou_agent_result.json",
    "famou_idea_result.json",
    "output",
    "outputs",
    "logs",
}


class CandidateStore:
    """管理一次提交对应的冻结代码、独立输出和证据目录。"""

    def __init__(self, workspace: str | Path):
        """初始化候选版本根目录。"""
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = self.workspace / "candidates"
        self.root.mkdir(parents=True, exist_ok=True)

    def _candidate_dir(self, candidate_id: str) -> Path:
        """返回经过路径校验的候选版本目录。"""
        value = str(candidate_id or "")
        if not value or value != safe_name(value):
            raise ValueError(f"非法 candidate_id: {candidate_id!r}")
        return self.root / value

    @staticmethod
    def _copy_code(source: Path, destination: Path) -> None:
        """复制代码并排除运行产物、公开数据链接和管理目录。"""

        def ignore(directory: str, names: list[str]) -> set[str]:
            """返回当前层不应进入冻结快照的文件名。"""
            return {
                name
                for name in names
                if name in _SNAPSHOT_EXCLUDES
                or name.startswith(".git")
                or name.endswith(".pyc")
                or (Path(directory) / name).is_symlink()
            }

        shutil.copytree(source, destination, symlinks=False, ignore=ignore)
        # ignore 已排除源码中的链接；这里再拒绝复制阶段可能残留的链接，保证
        # Candidate 不会引用工作区外的可变内容。
        links = [path for path in destination.rglob("*") if path.is_symlink()]
        if links:
            shutil.rmtree(destination)
            raise ValueError(f"候选代码包含符号链接: {links[0]}")

    @staticmethod
    def _relative_entrypoint(
        branch: Mapping[str, Any],
        source: Path,
    ) -> str | None:
        """从分支或方法清单恢复入口，并转换为源码目录内的相对路径。"""
        raw = branch.get("entrypoint")
        if not raw:
            manifest_path = source / "method_manifest.json"
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeError) as exc:
                    raise ValueError(f"方法清单无法解析: {manifest_path}: {exc}") from exc
                if not isinstance(manifest, dict):
                    raise ValueError(f"方法清单必须是 JSON 对象: {manifest_path}")
                raw = manifest.get("entrypoint")
        if not raw:
            return None
        entrypoint = Path(str(raw)).expanduser()
        if not entrypoint.is_absolute():
            relative = entrypoint
        else:
            try:
                relative = entrypoint.resolve().relative_to(source)
            except ValueError as exc:
                raise ValueError(f"实现入口不在 worktree 中: {entrypoint}") from exc
        if ".." in relative.parts:
            raise ValueError(f"实现入口包含越界路径: {relative}")
        return relative.as_posix()

    def create(
        self,
        branch: Mapping[str, Any],
        *,
        revision: int = 1,
        parent_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        """冻结一个分支版本并返回供 Runner 消费的候选描述。"""
        source_value = branch.get("worktree") or branch.get("method_dir")
        if not source_value:
            raise ValueError("实现结果缺少 worktree/method_dir，无法冻结候选代码")
        source = Path(str(source_value)).expanduser().resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"候选源码目录不存在: {source}")

        candidate_id = new_id("candidate")
        candidate_dir = self._candidate_dir(candidate_id)
        code_dir = candidate_dir / "code"
        output_dir = candidate_dir / "output"
        evidence_dir = candidate_dir / "evidence"
        candidate_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._copy_code(source, code_dir)
            output_dir.mkdir()
            evidence_dir.mkdir()
            relative_entrypoint = self._relative_entrypoint(branch, source)
            frozen_entrypoint = (
                code_dir / relative_entrypoint if relative_entrypoint else None
            )
            if frozen_entrypoint is not None and not frozen_entrypoint.is_file():
                raise FileNotFoundError(f"候选快照缺少入口文件: {frozen_entrypoint}")
            files = [
                {
                    "path": path.relative_to(code_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in sorted(code_dir.rglob("*"))
                if path.is_file()
            ]
            manifest = {
                "candidate_id": candidate_id,
                "branch_id": branch.get("branch_id") or branch.get("id"),
                "actor_id": branch.get("actor_id"),
                "lineage_id": branch.get("lineage_id") or branch.get("idea_id"),
                "idea_id": branch.get("idea_id"),
                "revision": max(1, int(revision)),
                "parent_candidate_id": parent_candidate_id,
                "expbank_attempt_id": branch.get("expbank_attempt_id"),
                "status": LoopStatus.Candidate.QUEUED,
                "entrypoint": relative_entrypoint,
                "code_snapshot": {"path": str(code_dir), "files": files},
                "paths": {
                    "code": str(code_dir),
                    "output": str(output_dir),
                    "evidence": str(evidence_dir),
                },
                "created_at": now_ms(),
                "updated_at": now_ms(),
            }
            atomic_write_json(candidate_dir / "manifest.json", manifest)
        except Exception:
            shutil.rmtree(candidate_dir, ignore_errors=True)
            raise

        # Runner 只接收冻结路径。保留其余公开元数据，兼容现有自定义 runner。
        candidate = dict(branch)
        candidate.update(
            {
                "candidate_id": candidate_id,
                "candidate_dir": str(candidate_dir),
                "candidate_output_dir": str(output_dir),
                "candidate_evidence_dir": str(evidence_dir),
                "revision": manifest["revision"],
                "parent_candidate_id": parent_candidate_id,
                "artifact": str(code_dir / "method_manifest.json"),
                "method_dir": str(code_dir),
                "workdir": str(code_dir),
                "entrypoint": str(frozen_entrypoint) if frozen_entrypoint else None,
                "source_worktree": str(source),
            }
        )
        if not Path(candidate["artifact"]).is_file():
            # 通用 Candidate 可以是任意语言的源码包，不强制存在单一入口。
            candidate["artifact"] = (
                str(frozen_entrypoint) if frozen_entrypoint else str(code_dir)
            )
        return candidate

    def read(self, candidate_id: str) -> dict[str, Any]:
        """读取候选版本清单。"""
        manifest = read_json(self._candidate_dir(candidate_id) / "manifest.json")
        if not isinstance(manifest, dict):
            raise FileNotFoundError(f"Candidate 不存在: {candidate_id}")
        return manifest

    def update(self, candidate_id: str, **changes: Any) -> dict[str, Any]:
        """更新候选调度状态和证据指针，不修改冻结代码。"""
        manifest = self.read(candidate_id)
        manifest.update(changes)
        manifest["updated_at"] = now_ms()
        atomic_write_json(self._candidate_dir(candidate_id) / "manifest.json", manifest)
        return manifest

    def list(self) -> list[dict[str, Any]]:
        """列出全部 Candidate 清单，供任务级恢复和终止使用。"""

        manifests: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*/manifest.json")):
            value = read_json(path)
            if isinstance(value, dict):
                manifests.append(value)
        return manifests

    def cancel_unfinished(self, *, reason: str) -> list[dict[str, Any]]:
        """把仍在评测流水线中的 Candidate 标记为不可恢复终态。"""

        cancelled: list[dict[str, Any]] = []
        active = {
            LoopStatus.Candidate.QUEUED,
            LoopStatus.Candidate.WAITING_RESOURCES,
            LoopStatus.Candidate.RUNNING,
        }
        for candidate in self.list():
            if candidate.get("status") not in active:
                continue
            cancelled.append(
                self.update(
                    str(candidate["candidate_id"]),
                    status=LoopStatus.Candidate.CANCELLED,
                    cancel_reason=reason,
                )
            )
        return cancelled

    def write_evidence(
        self,
        candidate_id: str,
        name: str,
        payload: Mapping[str, Any],
    ) -> Path:
        """在候选版本目录写入结构化运行或评测证据。"""
        path = self._candidate_dir(candidate_id) / "evidence" / f"{safe_name(name)}.json"
        atomic_write_json(path, dict(payload))
        return path


__all__ = ["CandidateStore"]
