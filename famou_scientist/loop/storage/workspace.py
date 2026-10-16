"""端到端运行工作空间的创建与发现逻辑。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

from ..domain.status import LoopStatus
from ..utils import atomic_write_json, now_ms, read_json, safe_name


DEFAULT_ROOT = Path(".famou/loop")


class WorkspacePathError(ValueError):
    """工作空间路径不合法。"""


class WorkspaceBusyError(RuntimeError):
    """工作空间已被其他进程占用。"""


class WorkspaceRunLock:
    """工作空间运行锁。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)
        self.lock_path = self.workspace / "control" / "orchestrator.lock"
        self._handle = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:  # pragma: no cover - platform dependent
                handle.close()
                raise WorkspaceBusyError(f"workspace is busy: {self.workspace}") from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "WorkspaceRunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class AgentWorkspace:
    """智能体分支工作空间。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)


def loop_root(base: str | Path | None = None) -> Path:
    """返回 Loop 根目录。"""

    root = Path(base).expanduser() if base is not None else DEFAULT_ROOT
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def goal_workspace(goal_id: str, base: str | Path | None = None) -> Path:
    """返回目标对应的 workspace 目录。"""

    normalized = safe_name(goal_id)
    if not goal_id or normalized != goal_id:
        raise WorkspacePathError(f"非法 goal_id: {goal_id!r}")
    return loop_root(base) / normalized


def init_workspace(goal_doc: dict, *, base: str | Path | None = None, source_goal_file: str | Path | None = None) -> Path:
    """初始化目标工作空间。"""

    goal_id = goal_doc["goal_id"]
    root = goal_workspace(goal_id, base)
    root.mkdir(parents=True, exist_ok=True)
    for rel in (
        "control",
        "logs",
        "artifacts",
        "branches",
        "analysis",
        "expbank",
        "shared_experience_pool",
        "problem",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / "goal_doc.json", goal_doc)
    if source_goal_file:
        dst = root / "goal.yaml"
        if not dst.exists():
            shutil.copyfile(Path(source_goal_file), dst)
    for name in [
        "external_baselines.jsonl",
        "literature_methods.jsonl",
        "attempted_ideas.jsonl",
        "failure_cases.jsonl",
        "reusable_artifacts.jsonl",
    ]:
        (root / "shared_experience_pool" / name).touch(exist_ok=True)
    return root


def fresh_workspace(goal_doc: dict, *, base: str | Path | None = None, source_goal_file: str | Path | None = None) -> Path:
    """重建目标工作空间。"""

    root = goal_workspace(goal_doc["goal_id"], base)
    if root.exists():
        lock = WorkspaceRunLock(root)
        lock.acquire()
        try:
            shutil.rmtree(root)
        finally:
            lock.release()
    return init_workspace(goal_doc, base=base, source_goal_file=source_goal_file)


def _resume_state(source_state: dict, goal_doc: dict, resume_root: Path) -> dict:
    """把旧 state 转换为可继续运行的新 state。"""

    state = dict(source_state) if isinstance(source_state, dict) else {}
    rs = state.get("research_state")
    rs = dict(rs) if isinstance(rs, dict) else {}
    goal = rs.get("goal")
    goal = dict(goal) if isinstance(goal, dict) else {}
    lineage = rs.get("lineage")
    lineage = dict(lineage) if isinstance(lineage, dict) else {}
    prior_loop_dirs = [
        str(resume_root),
        *[p for p in (lineage.get("prior_loop_dirs") or []) if p != str(resume_root)],
    ]
    lineage["prior_loop_dirs"] = prior_loop_dirs
    lineage.setdefault("resume_from", str(resume_root))
    goal_doc_goal = goal_doc.get("goal") if isinstance(goal_doc.get("goal"), dict) else {}
    goal.update(
        {
            "id": goal_doc.get("goal_id"),
            "name": goal_doc_goal.get("name") or goal.get("name"),
            "objective_brief": goal_doc.get("objective_brief") if isinstance(goal_doc.get("objective_brief"), dict) else goal.get("objective_brief", {}),
            "constraints": goal_doc.get("constraints") if isinstance(goal_doc.get("constraints"), dict) else goal.get("constraints", {}),
            "workflow": goal_doc.get("workflow") if isinstance(goal_doc.get("workflow"), dict) else goal.get("workflow", {"type": "research"}),
            "infra": goal_doc.get("infra") if isinstance(goal_doc.get("infra"), dict) else goal.get("infra", {}),
        }
    )
    now = now_ms()
    rs.update(
        {
            "goal_id": goal_doc.get("goal_id"),
            "status": LoopStatus.Research.RUNNING,
            "lifecycle": "active",
            "current_phase": "initializing",
            "last_heartbeat_at": now,
            "created_at": now,
            "updated_at": now,
            "termination_reason": None,
            "goal": goal,
            "lineage": lineage,
        }
    )
    for key in ("pending_goal_change", "shutdown", "last_goal_patch_error"):
        rs.pop(key, None)
    state["research_state"] = rs
    return state


def resume_workspace(goal_doc: dict, *, base: str | Path | None = None, source_goal_file: str | Path | None = None, resume_from: str | Path) -> Path:
    """创建新的工作空间，并从旧工作空间继承可见历史。"""

    root = goal_workspace(goal_doc["goal_id"], base)
    source = Path(resume_from).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"resume source workspace not found: {source}")
    if root.exists():
        lock = WorkspaceRunLock(root)
        lock.acquire()
        try:
            shutil.rmtree(root)
        finally:
            lock.release()
    new_root = init_workspace(goal_doc, base=base, source_goal_file=source_goal_file)
    for rel in (
        "expbank",
        "artifacts",
        "analysis",
        "workspace/handoff.json",
        "workspace/handoff.md",
        "workspace/status_summary.md",
    ):
        src = source / rel
        dst = new_root / rel
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    # init_workspace already created the shared pool files. Copy their contents
    # one by one so source and target cannot alias the same path in-place.
    source_pool = source / "shared_experience_pool"
    target_pool = new_root / "shared_experience_pool"
    if source_pool.is_dir():
        for src_file in source_pool.iterdir():
            if src_file.is_file():
                shutil.copy2(src_file, target_pool / src_file.name)
    source_state = source / "research_state.yaml"
    if source_state.exists():
        loaded = read_json(source_state)
        if isinstance(loaded, dict):
            atomic_write_json(new_root / "research_state.yaml", _resume_state(loaded, goal_doc, source))
    return new_root


def find_workspace(goal_id: str, *, base: str | Path | None = None) -> Path:
    """查找已有目标工作空间。"""

    root = goal_workspace(goal_id, base)
    if not root.exists():
        raise FileNotFoundError(f"未找到 loop goal workspace: {root}")
    return root
