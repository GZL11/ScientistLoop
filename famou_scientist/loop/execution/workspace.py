"""实现智能体专用的分支工作空间。"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..utils import atomic_write_json, atomic_write_text, now_ms, safe_name
from ..domain.status import LoopStatus


class WorkspacePathError(ValueError):
    """表示智能体产物路径越界错误。"""


_FORBIDDEN_SOURCE_NAMES = {
    ".git",
    ".famou",
    "__pycache__",
    "control",
    "evaluator",
    "evaluators",
    "hidden",
    "private",
    "benchmark_task",
}


def _strict_branch_id(value: str) -> str:
    """校验分支标识是否合法。"""
    branch_id = str(value or "")
    if not branch_id or branch_id != safe_name(branch_id):
        raise WorkspacePathError(f"非法 branch_id: {value!r}")
    return branch_id


def _relative_parts(value: str | Path) -> list[str]:
    """解析安全的相对路径片段。"""
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute():
        raise WorkspacePathError(f"workspace path must be relative: {value!r}")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts or ".." in parts:
        raise WorkspacePathError(f"workspace path contains traversal: {value!r}")
    if any(part in _FORBIDDEN_SOURCE_NAMES for part in parts):
        raise WorkspacePathError(f"workspace path is reserved: {value!r}")
    return parts


def _inside(root: Path, candidate: Path) -> bool:
    """判断路径是否位于根目录内。"""
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _copy_source_contents(source: Path, destination: Path) -> None:
    """复制源码快照并排除控制和评测目录。"""

    def ignore(directory: str, names: list[str]) -> set[str]:
        """完成当前处理流程。"""
        del directory
        return {
            name
            for name in names
            if name in _FORBIDDEN_SOURCE_NAMES or name.startswith(".git")
        }

    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in _FORBIDDEN_SOURCE_NAMES or item.name.startswith(".git"):
            continue
        target = destination / item.name
        if item.is_symlink():
            # 不把源码快照中的符号链接带入智能体工作空间。
            continue
        if item.is_dir():
            shutil.copytree(item, target, ignore=ignore)
        else:
            shutil.copy2(item, target)


@dataclass(frozen=True)
class AgentWorkspace:
    """管理单个实现分支的私有工作空间。"""

    goal_workspace: Path
    branch_id: str
    root: Path
    worktree: Path
    public: Path
    outputs: Path
    logs: Path
    manifest_path: Path

    @classmethod
    def create(
        cls,
        goal_workspace: str | Path,
        branch_id: str,
        *,
        source_dir: str | Path | None = None,
        public_payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "AgentWorkspace":
        """创建新的分支工作空间。"""
        goal_root = Path(goal_workspace).expanduser().resolve()
        branch = _strict_branch_id(branch_id)
        root = goal_root / "branches" / branch
        # branch_id 对应一次独立实现版本；已有目录一律拒绝复用，避免新 Agent
        # 覆盖上一版本的代码、日志和输出。
        if root.exists():
            raise FileExistsError(f"agent branch workspace already exists: {root}")

        worktree = root / "worktree"
        public = root / "public"
        outputs = root / "outputs"
        logs = root / "logs"
        for directory in (worktree, public, outputs, logs):
            directory.mkdir(parents=True, exist_ok=True)

        if source_dir is not None:
            # 从上一最佳分支派生时复制真实文件，并排除控制目录、隐藏目录与符号链接。
            # 新分支后续修改不会反向影响 parent。
            source = Path(source_dir).expanduser().resolve()
            if not source.is_dir():
                raise FileNotFoundError(f"agent source_dir is not a directory: {source}")
            _copy_source_contents(source, worktree)

        workspace = cls(
            goal_workspace=goal_root,
            branch_id=branch,
            root=root,
            worktree=worktree,
            public=public,
            outputs=outputs,
            logs=logs,
            manifest_path=root / "manifest.json",
        )
        manifest = {
            "branch_id": branch,
            "goal_workspace": str(goal_root),
            "root": str(root),
            "worktree": str(worktree),
            "public": str(public),
            "outputs": str(outputs),
            "logs": str(logs),
            "isolation": "directory",
            "status": LoopStatus.Workspace.CREATED,
            "created_at": now_ms(),
            "metadata": dict(metadata or {}),
        }
        workspace.write_manifest(manifest)
        if public_payload is not None:
            # context.json 只承载经过上层筛选的公开上下文；Agent 不直接读取调度器
            # 内存对象或可信 evaluator 配置。
            workspace.write_public_json("context.json", dict(public_payload))
        return workspace

    @classmethod
    def open(cls, goal_workspace: str | Path, branch_id: str) -> "AgentWorkspace":
        """打开已有分支工作空间。"""
        goal_root = Path(goal_workspace).expanduser().resolve()
        branch = _strict_branch_id(branch_id)
        root = goal_root / "branches" / branch
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"agent workspace manifest not found: {manifest_path}")

        workspace = cls(
            goal_workspace=goal_root,
            branch_id=branch,
            root=root,
            worktree=root / "worktree",
            public=root / "public",
            outputs=root / "outputs",
            logs=root / "logs",
            manifest_path=manifest_path,
        )
        for path in (workspace.worktree, workspace.public, workspace.outputs, workspace.logs):
            # 恢复已有分支时重新验证布局，不能盲目信任磁盘上的 manifest 路径。
            if not _inside(workspace.root, path) or not path.is_dir():
                raise WorkspacePathError(f"invalid agent workspace layout: {path}")
        return workspace

    def resolve_worktree_path(self, relative_path: str | Path) -> Path:
        """解析并校验工作区内路径。"""

        parts = _relative_parts(relative_path)
        candidate = self.worktree.joinpath(*parts)
        # 字面路径和解析后路径都必须位于 worktree，防止 ../ 与绝对路径越界。
        if not _inside(self.worktree, candidate):
            raise WorkspacePathError(f"path leaves agent worktree: {relative_path!r}")
        # 即使字面路径安全，已有符号链接仍可能指向外部；读写前必须拒绝。
        current = self.worktree
        for part in parts:
            current = current / part
            if current.is_symlink() and not _inside(self.worktree, current):
                raise WorkspacePathError(f"symlink leaves agent worktree: {relative_path!r}")
        return candidate

    def resolve_public_path(self, relative_path: str | Path) -> Path:
        """解析并校验公开目录内路径。"""
        parts = _relative_parts(relative_path)
        candidate = self.public.joinpath(*parts)
        if not _inside(self.public, candidate):
            raise WorkspacePathError(f"path leaves public workspace: {relative_path!r}")
        return candidate

    def resolve_output_path(self, relative_path: str | Path) -> Path:
        """解析并校验输出目录内路径。"""
        parts = _relative_parts(relative_path)
        candidate = self.outputs.joinpath(*parts)
        if not _inside(self.outputs, candidate):
            raise WorkspacePathError(f"path leaves output workspace: {relative_path!r}")
        return candidate

    def write_worktree_text(self, relative_path: str | Path, text: str) -> Path:
        """向工作区写入文本文件。"""
        path = self.resolve_worktree_path(relative_path)
        atomic_write_text(path, text)
        return path

    def write_public_json(self, relative_path: str | Path, value: Mapping[str, Any] | list[Any]) -> Path:
        """向公开目录写入结构化数据。"""
        path = self.resolve_public_path(relative_path)
        atomic_write_json(path, value)
        return path

    def write_output_json(self, relative_path: str | Path, value: Mapping[str, Any]) -> Path:
        """向输出目录写入结构化数据。"""
        path = self.resolve_output_path(relative_path)
        atomic_write_json(path, value)
        return path

    def write_manifest(self, value: Mapping[str, Any]) -> None:
        """写入分支清单文件。"""
        atomic_write_json(self.manifest_path, dict(value))

    def update_manifest(self, **changes: Any) -> dict[str, Any]:
        """更新分支清单文件。"""
        current: dict[str, Any] = {}
        if self.manifest_path.exists():
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                current = raw
        current.update(changes)
        current["updated_at"] = now_ms()
        # manifest 是分支生命周期的轻量索引，详细科研结果仍进入 ArtifactStore/ExpBank。
        self.write_manifest(current)
        return current

    def mark_status(self, status: str, **metadata: Any) -> dict[str, Any]:
        """更新分支状态。"""
        return self.update_manifest(status=str(status), **metadata)
