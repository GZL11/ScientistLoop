"""保存尚未实现的 Idea、演化关系和 Gate 评审证据。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None

from ..domain.status import LoopStatus
from ..utils import (
    atomic_write_json,
    atomic_write_text,
    new_id,
    now_ms,
    read_json,
    safe_name,
)


def _cell(value: Any) -> str:
    """把任意值转换为适合 Markdown 表格的单行文本。"""

    text = "" if value is None else str(value)
    return " ".join(text.replace("|", "\\|").split())


class IdeaGraphStore:
    """在 ExpBank 内以浅目录维护可恢复的 Idea 图谱。"""

    def __init__(self, workspace: str | Path):
        """初始化 Idea 目录、索引和跨进程文件锁。"""

        self.workspace = Path(workspace).expanduser().resolve()
        self.expbank_root = self.workspace / "expbank"
        self.root = self.expbank_root / "ideas"
        self.index_path = self.expbank_root / "IDEAS.md"
        self.lock_path = self.expbank_root / ".ideas.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """串行化 Idea、Review 和索引更新。"""

        self.expbank_root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, idea_id: str) -> Path:
        """返回经过路径校验的 Idea 记录文件。"""

        value = str(idea_id or "")
        if not value or value != safe_name(value):
            raise ValueError(f"非法 idea_id: {idea_id!r}")
        return self.root / f"{value}.json"

    def _records(self) -> list[dict[str, Any]]:
        """按创建时间读取全部 Idea 记录。"""

        records = [
            value
            for path in sorted(self.root.glob("*.json"))
            if isinstance((value := read_json(path)), dict)
        ]
        return sorted(
            records,
            key=lambda item: (
                int(item.get("created_at") or 0),
                str(item.get("idea_id") or ""),
            ),
        )

    def _write_index(self) -> None:
        """从结构化记录重建供 Agent 浏览的紧凑索引。"""

        lines = [
            "# Idea Graph",
            "",
            "这里保存所有已提交 Idea，包括待评审、需修改、被拒绝和已进入实现的方案。详细机制、版本关系和 Gate 诊断位于 `ideas/<idea_id>.json`。",
            "",
            "| Idea | 标题 | 状态 | 关系 | Parent | Gate 摘要 |",
            "|---|---|---|---|---|---|",
        ]
        records = self._records()
        if not records:
            lines.append("| - | 暂无 Idea | - | - | - | - |")
        for record in records:
            idea = record.get("idea") if isinstance(record.get("idea"), Mapping) else {}
            reviews = (
                record.get("reviews")
                if isinstance(record.get("reviews"), list)
                else []
            )
            latest = reviews[-1] if reviews and isinstance(reviews[-1], Mapping) else {}
            diagnosis = latest.get("reasons") or latest.get("actionable_revision") or []
            if isinstance(diagnosis, list):
                diagnosis = "; ".join(str(item) for item in diagnosis[:2])
            idea_id = str(record.get("idea_id") or "")
            # 无 Gate 准入（benchmark 工作流全程如此，开放科研在 gate 关闭时亦然）
            # 不会再有 Review，标成"待评审"是错的——Agent 会以为还有一道关没过。
            admission = record.get("admission")
            if not diagnosis and isinstance(admission, Mapping):
                if admission.get("mode") == "gate_disabled":
                    diagnosis = "未经 Gate"
            lines.append(
                "| [{idea_id}](./ideas/{idea_id}.json) | {title} | {status} "
                "| {relation} | {parent} | {diagnosis} |".format(
                    idea_id=_cell(idea_id),
                    title=_cell(idea.get("title") or "未命名 Idea"),
                    status=_cell(record.get("status") or "unknown"),
                    relation=_cell(record.get("relation") or "-"),
                    parent=_cell(record.get("parent_idea_id") or "-"),
                    diagnosis=_cell(diagnosis or "待评审"),
                )
            )
        lines.append("")
        atomic_write_text(self.index_path, "\n".join(lines))

    def submit(
        self,
        idea: Mapping[str, Any],
        *,
        actor_id: str | None = None,
        artifact_refs: list[str] | None = None,
        goal_contract_version: str | None = None,
    ) -> dict[str, Any]:
        """在调用 Gate 前持久化一个原始 Idea。"""

        payload = dict(idea)
        idea_id = str(payload.get("id") or new_id("idea"))
        payload["id"] = idea_id
        path = self._path(idea_id)
        with self._lock():
            if path.exists():
                raise FileExistsError(f"Idea 已存在，不能覆盖原始提案: {idea_id}")
            created_at = int(payload.get("created_at") or now_ms())
            record = {
                "idea_id": idea_id,
                "actor_id": actor_id or payload.get("idea_actor_id"),
                "parent_idea_id": payload.get("parent_idea_id"),
                "relation": payload.get("relation"),
                "status": LoopStatus.Idea.SUBMITTED,
                "goal_contract_version": goal_contract_version,
                "idea": payload,
                "reviews": [],
                "artifact_refs": list(artifact_refs or []),
                "created_at": created_at,
                "updated_at": created_at,
            }
            atomic_write_json(path, record)
            self._write_index()
            return record

    def begin_review(self, idea_id: str) -> dict[str, Any]:
        """把已提交 Idea 标记为正在同步评审。"""

        return self._update(idea_id, status=LoopStatus.Idea.UNDER_REVIEW)

    def admit_without_review(
        self,
        idea_id: str,
        *,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """在 Gate 关闭时直接准入 Idea，并明确记录未经过 Judge。"""

        with self._lock():
            record = self.read(idea_id)
            refs = list(record.get("artifact_refs") or [])
            for ref in artifact_refs or []:
                if ref not in refs:
                    refs.append(ref)
            record.update(
                {
                    "status": LoopStatus.Idea.ACCEPTED,
                    "admission": {
                        "mode": "gate_disabled",
                        "decision": "enqueue_without_gate",
                        "created_at": now_ms(),
                    },
                    "artifact_refs": refs,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def record_review(
        self,
        idea_id: str,
        review: Mapping[str, Any],
        *,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """追加 Gate 结果，并将 verdict 映射到稳定 Idea 状态。"""

        verdict = str(review.get("verdict") or "reject")
        status_by_verdict = {
            "pass": LoopStatus.Idea.ACCEPTED,
            "revise": LoopStatus.Idea.REVISION_REQUESTED,
            "reject": LoopStatus.Idea.REJECTED,
            "needs_evidence": LoopStatus.Idea.NEEDS_EVIDENCE,
        }
        with self._lock():
            record = self.read(idea_id)
            reviews = list(record.get("reviews") or [])
            reviews.append(dict(review))
            refs = list(record.get("artifact_refs") or [])
            for ref in artifact_refs or []:
                if ref not in refs:
                    refs.append(ref)
            record.update(
                {
                    "status": status_by_verdict.get(verdict, LoopStatus.Idea.REJECTED),
                    "reviews": reviews,
                    "artifact_refs": refs,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def read(self, idea_id: str) -> dict[str, Any]:
        """读取指定 Idea 的完整图谱记录。"""

        value = read_json(self._path(idea_id))
        if not isinstance(value, dict):
            raise FileNotFoundError(f"Idea 图谱记录不存在: {idea_id}")
        return value

    def latest_review(self, *, actor_id: str | None = None) -> dict[str, Any] | None:
        """返回指定 IdeaActor 最近一次 Gate 反馈。"""

        records = self._records()
        if actor_id:
            records = [item for item in records if item.get("actor_id") == actor_id]
        reviewed = [item for item in records if item.get("reviews")]
        if not reviewed:
            return None
        record = max(reviewed, key=lambda item: int(item.get("updated_at") or 0))
        return {
            "idea_id": record.get("idea_id"),
            "status": record.get("status"),
            "review": dict(record["reviews"][-1]),
        }

    def link_attempt(self, idea_id: str, attempt_id: str) -> dict[str, Any]:
        """把通过 Gate 的 Idea 与开始实现的 ExpBank attempt 关联。"""

        with self._lock():
            record = self.read(idea_id)
            attempts = list(record.get("attempt_ids") or [])
            if attempt_id not in attempts:
                attempts.append(attempt_id)
            record.update(
                {
                    "status": LoopStatus.Idea.IMPLEMENTING,
                    "attempt_ids": attempts,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def record_implementation(
        self,
        idea_id: str,
        *,
        succeeded: bool,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        """根据实现结果更新 Idea 节点，但不把工程失败解释为科研失败。"""

        with self._lock():
            record = self.read(idea_id)
            attempts = list(record.get("attempt_ids") or [])
            if attempt_id and attempt_id not in attempts:
                attempts.append(attempt_id)
            record.update(
                {
                    "status": (
                        LoopStatus.Idea.IMPLEMENTED
                        if succeeded
                        else LoopStatus.Idea.IMPLEMENTATION_FAILED
                    ),
                    "attempt_ids": attempts,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def _update(self, idea_id: str, **changes: Any) -> dict[str, Any]:
        """原子更新一个 Idea 记录并同步索引。"""

        with self._lock():
            record = self.read(idea_id)
            record.update(changes)
            record["updated_at"] = now_ms()
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record


__all__ = ["IdeaGraphStore"]
