"""长生命周期 ImplementActor 的持久化状态与反馈邮箱。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None

from ..utils import append_jsonl, atomic_write_json, new_id, now_ms, read_json, read_jsonl, safe_name
from ..domain.status import LoopStatus


class ImplementActorStore:
    """以浅目录保存 actor 状态、预算和 evaluator 反馈。"""

    def __init__(self, workspace: str | Path):
        """初始化 actor 根目录。"""
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = self.workspace / "actors"
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, actor_id: str) -> Path:
        """返回经过校验的 actor 目录。"""
        value = str(actor_id or "")
        if not value or value != safe_name(value):
            raise ValueError(f"非法 actor_id: {actor_id!r}")
        return self.root / value

    @contextmanager
    def _lock(self, actor_id: str) -> Iterator[None]:
        """串行化同一 actor 的线程和进程更新。"""
        directory = self._dir(actor_id)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def create(
        self,
        idea: Mapping[str, Any],
        *,
        max_lifetime_sec: float,
        max_turns: int,
        max_run_attempts: int,
        max_official_evaluations: int | None,
        max_repairs_per_revision: int,
        max_debug_attempts: int | None = None,
    ) -> dict[str, Any]:
        """为一个 Idea 创建稳定 lineage、branch 和多维预算。"""
        actor_id = new_id("implement_actor")
        actor_dir = self._dir(actor_id)
        actor_dir.mkdir(parents=True, exist_ok=False)
        created_at = now_ms()
        record = {
            "actor_id": actor_id,
            "lineage_id": str(idea.get("lineage_id") or idea.get("id") or actor_id),
            "idea_id": idea.get("id"),
            "branch_id": new_id("actor_branch"),
            "status": LoopStatus.Actor.READY,
            "session_id": None,
            "session_runtime": None,
            "session_started": False,
            "session_state_path": None,
            "session_resume_count": 0,
            "created_at": created_at,
            "updated_at": created_at,
            "deadline_at": created_at + max(1, int(max_lifetime_sec * 1000)),
            "budget": {
                "max_turns": max(1, int(max_turns)),
                "used_turns": 0,
                "max_run_attempts": max(1, int(max_run_attempts)),
                "used_run_attempts": 0,
                # None 表示没有独立的正式评测次数限制。Actor 仍受生命周期、
                # 研究回合和 canonical run 次数约束。
                "max_official_evaluations": (
                    max(0, int(max_official_evaluations))
                    if max_official_evaluations is not None
                    else None
                ),
                "used_official_evaluations": 0,
                "max_repairs_per_revision": max(0, int(max_repairs_per_revision)),
                # 「这个方案一共 debug 了几次」。None = 不设独立上限（历史行为，
                # 那时只受 max_run_attempts 和墙钟约束）。0 是合法值，与 None 不同。
                #
                # 和 max_repairs_per_revision 不是一回事：那个每次 register_candidate
                # 都清零（:210），限的是单次提交里连修几回，从来不限总数。
                "max_debug_attempts": (
                    max(0, int(max_debug_attempts))
                    if max_debug_attempts is not None
                    else None
                ),
                "used_debug_attempts": 0,
            },
            "revision": 0,
            "repair_count": 0,
            "pending_candidates": [],
            "completed_candidates": 0,
            "last_candidate_id": None,
            "last_attempt_id": None,
            "last_feedback_id": None,
            "mailbox": str(actor_dir / "mailbox.jsonl"),
            "base_idea": dict(idea),
        }
        atomic_write_json(actor_dir / "state.json", record)
        (actor_dir / "mailbox.jsonl").touch()
        return record

    def read(self, actor_id: str) -> dict[str, Any]:
        """读取一个 actor 的完整状态。"""
        value = read_json(self._dir(actor_id) / "state.json")
        if not isinstance(value, dict):
            raise FileNotFoundError(f"ImplementActor 不存在: {actor_id}")
        return value

    def update(self, actor_id: str, **changes: Any) -> dict[str, Any]:
        """原子更新 actor 状态。"""
        with self._lock(actor_id):
            record = self.read(actor_id)
            record.update(changes)
            record["updated_at"] = now_ms()
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return record

    def can_start_turn(
        self,
        actor_id: str,
        *,
        repair: bool = False,
    ) -> tuple[bool, str | None]:
        """检查墙钟、研究回合和运行预算是否仍允许唤醒 actor。"""
        record = self.read(actor_id)
        budget = record.get("budget") or {}
        if now_ms() >= int(record.get("deadline_at") or 0):
            return False, "actor_lifetime_exhausted"
        # 工程修复不应消耗“有效研究/提交回合”预算，但仍受 Actor 生命周期、
        # canonical run 次数和单 revision 修复次数约束。
        if not repair and int(budget.get("used_turns") or 0) >= int(
            budget.get("max_turns") or 0
        ):
            return False, "actor_turn_budget_exhausted"
        # debug 总次数是独立一轴：单 revision 的修复次数每次提交都会清零，拦不住
        # 「一个方案反复修一整天」。max_debug_attempts 为 None 时保持历史行为。
        max_debug = budget.get("max_debug_attempts")
        if (
            repair
            and max_debug is not None
            and int(budget.get("used_debug_attempts") or 0) >= int(max_debug)
        ):
            return False, "actor_debug_budget_exhausted"
        reserved_runs = len(record.get("pending_candidates") or [])
        if int(budget.get("used_run_attempts") or 0) + reserved_runs >= int(
            budget.get("max_run_attempts") or 0
        ):
            return False, "actor_run_budget_exhausted"
        return True, None

    def begin_turn(
        self,
        actor_id: str,
        *,
        repair: bool = False,
    ) -> dict[str, Any]:
        """占用一次 Agent 激活，并在非修复场景扣研究回合预算。"""
        with self._lock(actor_id):
            record = self.read(actor_id)
            budget = dict(record.get("budget") or {})
            allowed, reason = self.can_start_turn(actor_id, repair=repair)
            if not allowed:
                record["status"] = LoopStatus.Actor.EXHAUSTED
                record["termination_reason"] = reason
                record["updated_at"] = now_ms()
                atomic_write_json(self._dir(actor_id) / "state.json", record)
                raise RuntimeError(str(reason))
            if not repair:
                budget["used_turns"] = int(budget.get("used_turns") or 0) + 1
            else:
                # 扣在这里而不是 add_feedback：一次失败反馈不等于一次 debug，
                # 真正被消耗的是 agent 被再唤醒一次。
                budget["used_debug_attempts"] = int(
                    budget.get("used_debug_attempts") or 0
                ) + 1
            record["budget"] = budget
            record["revision"] = int(record.get("revision") or 0) + 1
            record["status"] = LoopStatus.Actor.RUNNING
            record["activation_kind"] = "repair" if repair else "research"
            record["updated_at"] = now_ms()
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return record

    def update_session(
        self,
        actor_id: str,
        session: Mapping[str, Any],
    ) -> dict[str, Any]:
        """同步 CLI Agent 的持久会话信息，供调度恢复和审计。"""
        changes = {
            "session_id": session.get("session_id"),
            "session_runtime": session.get("runtime"),
            "session_started": bool(session.get("started")),
            "session_state_path": session.get("state_path"),
            "session_resume_count": int(session.get("resume_count") or 0),
        }
        return self.update(actor_id, **changes)

    def register_candidate(
        self,
        actor_id: str,
        candidate_id: str,
        *,
        attempt_id: str | None,
    ) -> dict[str, Any]:
        """记录 actor 唯一的在途 Candidate，并进入等待评测状态。"""
        with self._lock(actor_id):
            record = self.read(actor_id)
            pending = list(record.get("pending_candidates") or [])
            if pending and candidate_id not in pending:
                raise RuntimeError(
                    f"actor {actor_id} 已有在途 Candidate: {pending[0]}"
                )
            if candidate_id not in pending:
                pending.append(candidate_id)
            record.update(
                {
                    "pending_candidates": pending,
                    "last_candidate_id": candidate_id,
                    "last_attempt_id": attempt_id,
                    "status": LoopStatus.Actor.WAITING_EVALUATION,
                    "repair_count": 0,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return record

    def record_run(self, actor_id: str) -> dict[str, Any]:
        """在 canonical run 完成后扣减 actor 的运行次数。"""
        with self._lock(actor_id):
            record = self.read(actor_id)
            budget = dict(record.get("budget") or {})
            budget["used_run_attempts"] = int(budget.get("used_run_attempts") or 0) + 1
            record["budget"] = budget
            record["updated_at"] = now_ms()
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return record

    def complete_candidate(
        self,
        actor_id: str,
        candidate_id: str,
        *,
        official_evaluated: bool,
    ) -> dict[str, Any]:
        """移除已结束 Candidate，并按实际调用扣正式评测次数。"""
        with self._lock(actor_id):
            record = self.read(actor_id)
            pending = list(record.get("pending_candidates") or [])
            was_pending = candidate_id in pending
            record["pending_candidates"] = [
                value
                for value in pending
                if value != candidate_id
            ]
            if was_pending:
                record["completed_candidates"] = int(
                    record.get("completed_candidates") or 0
                ) + 1
            budget = dict(record.get("budget") or {})
            if official_evaluated and was_pending:
                budget["used_official_evaluations"] = int(
                    budget.get("used_official_evaluations") or 0
                ) + 1
            record["budget"] = budget
            record["status"] = LoopStatus.Actor.READY
            record["updated_at"] = now_ms()
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return record

    def add_feedback(
        self,
        actor_id: str,
        *,
        candidate_id: str | None,
        kind: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """向 actor mailbox 追加脱敏反馈并返回消息。"""
        with self._lock(actor_id):
            message = {
                "id": new_id("feedback"),
                "actor_id": actor_id,
                "candidate_id": candidate_id,
                "kind": kind,
                "payload": dict(payload),
                "created_at": now_ms(),
            }
            append_jsonl(self._dir(actor_id) / "mailbox.jsonl", message)
            record = self.read(actor_id)
            record["last_feedback_id"] = message["id"]
            record["last_feedback_kind"] = kind
            if kind in {
                "implementation_failed",
                "preflight_failed",
                "run_failed",
                "validation_failed",
                "public_eval_failed",
                "evaluation_failed",
            }:
                record["repair_count"] = int(record.get("repair_count") or 0) + 1
                record["status"] = LoopStatus.Actor.REPAIR_READY
            elif kind == "evaluated":
                record["status"] = LoopStatus.Actor.REFINE_READY
            record["updated_at"] = now_ms()
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return message

    def mailbox(self, actor_id: str) -> list[dict[str, Any]]:
        """返回 actor 可读取的完整脱敏反馈历史。"""
        return read_jsonl(self._dir(actor_id) / "mailbox.jsonl")

    def record_search_decision(
        self,
        actor_id: str,
        decision: Mapping[str, Any],
        *,
        offered_idea: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """记录 Improve 选择，并在 switch/fuse 后更新下一回合基础 Idea。"""

        with self._lock(actor_id):
            record = self.read(actor_id)
            value = {
                **dict(decision),
                "actor_id": actor_id,
                "recorded_at": now_ms(),
            }
            append_jsonl(self._dir(actor_id) / "search_decisions.jsonl", value)
            record["last_search_decision"] = value
            record["search_decision_count"] = int(
                record.get("search_decision_count") or 0
            ) + 1
            action = str(decision.get("action") or "")
            if action == "switch" and isinstance(offered_idea, Mapping):
                previous = dict(record.get("base_idea") or {})
                adopted = dict(offered_idea)
                # **不写 parent_idea_id / parents。** switch 的语义是「放弃 previous，
                # 改做 offered」——offered 不是从 previous 派生出来的，它早就有自己的
                # 节点和自己的 operator/parents。在这里给它安一个父，就是凭空造一条
                # 假边（正是 20260915 那批 alternative_to 44%/63% 的来源：三个
                # relation 取值全部由代码路径写入，没有一个是 agent 的判断）。
                #
                # 真正无处可查的只有一件事：换之前在做哪个方案——record["idea_id"]
                # 下一行就被覆盖了，search_decisions.jsonl 里也只有 offered 那一侧。
                # 所以只记这一个字段，并且用一个不会被误读成图上父指针的名字。
                adopted["switched_from_idea_id"] = previous.get("id")
                record["base_idea"] = adopted
                record["idea_id"] = adopted.get("id")
            elif action == "fuse" and isinstance(offered_idea, Mapping):
                base = dict(record.get("base_idea") or {})
                fused = list(base.get("fused_ideas") or [])
                offered_id = offered_idea.get("id")
                if offered_id and all(
                    value.get("id") != offered_id
                    for value in fused
                    if isinstance(value, dict)
                ):
                    fused.append(dict(offered_idea))
                base["fused_ideas"] = fused
                # 同理不写 relation="combines"：「融合过」这件事由 fused_ideas 非空
                # 直接表达，再加一个自报的标签只会多一个没人校验的证据来源。
                record["base_idea"] = base
            record["updated_at"] = now_ms()
            atomic_write_json(self._dir(actor_id) / "state.json", record)
            return record

    def list(self) -> list[dict[str, Any]]:
        """列出全部 actor 状态，供调度器执行轻量准入判断。"""
        records: list[dict[str, Any]] = []
        for state_path in sorted(self.root.glob("*/state.json")):
            value = read_json(state_path)
            if isinstance(value, dict):
                records.append(value)
        return records

    def cancel_unfinished(self, *, reason: str) -> list[dict[str, Any]]:
        """终结仍可能被调度的 Actor，并保留 session、mailbox 和 lineage。"""

        terminal = {
            LoopStatus.Actor.EXHAUSTED,
            LoopStatus.Actor.COMPLETED,
            LoopStatus.Actor.FAILED,
            LoopStatus.Actor.CANCELLED,
        }
        cancelled: list[dict[str, Any]] = []
        for actor in self.list():
            if actor.get("status") in terminal:
                continue
            cancelled.append(
                self.update(
                    str(actor["actor_id"]),
                    status=LoopStatus.Actor.CANCELLED,
                    termination_reason=reason,
                    pending_candidates=[],
                )
            )
        return cancelled


__all__ = ["ImplementActorStore"]
