"""Loop 人机交互使用的轻量文件事件总线。"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None

from ..domain.goal import GoalError, validate_goal_patch
from ..utils import atomic_write_json, new_id, now_ms


class ControlEventError(ValueError):
    """表示控制事件不符合 Loop 控制协议。"""


class ControlEventStore:
    """提供进程之间共享的追加式命令和事件存储。"""

    COMMAND_TYPES = frozenset(
        {
            "message",
            "pause",
            "resume",
            "stop",
            "goal_change",
            "clarification_response",
        }
    )
    GOAL_CHANGE_DECISIONS = frozenset(
        {"continue_current", "stop_current"}
    )

    def __init__(self, workspace: str | Path):
        """初始化控制目录和事件文件。"""
        self.workspace = Path(workspace)
        self.control = self.workspace / "control"
        self.control.mkdir(parents=True, exist_ok=True)
        self.commands_path = self.control / "commands.jsonl"
        self.events_path = self.control / "events.jsonl"
        self.cursor_path = self.control / "command_cursor.json"
        self.lock_path = self.control / "events.lock"
        self.commands_path.touch(exist_ok=True)
        self.events_path.touch(exist_ok=True)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """串行化多个入口对 JSONL 文件的追加。"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _validate_type(event_type: str, *, command: bool) -> str:
        """校验事件类型并返回规范化字符串。"""
        value = str(event_type or "").strip()
        if command and value not in ControlEventStore.COMMAND_TYPES:
            raise ControlEventError(f"不支持的 Loop 控制命令: {value!r}")
        if not value:
            raise ControlEventError("控制事件 type 不能为空")
        return value

    @staticmethod
    def _validate_goal_change(payload: dict[str, Any]) -> dict[str, Any]:
        """校验目标变更请求，不在这里修改当前目标。"""
        if not isinstance(payload, dict):
            raise ControlEventError("goal_change payload 必须是 object")
        decision = str(payload.get("decision") or "").strip()
        if decision not in ControlEventStore.GOAL_CHANGE_DECISIONS:
            raise ControlEventError(
                "goal_change.decision 必须是 continue_current 或 stop_current"
            )
        instruction = payload.get("instruction")
        if instruction is not None and not isinstance(instruction, str):
            raise ControlEventError("goal_change.instruction 必须是字符串")
        patch = payload.get("goal_patch")
        if patch is not None:
            try:
                patch = validate_goal_patch(patch)
            except GoalError as exc:
                raise ControlEventError(str(exc)) from exc
        next_goal = payload.get("next_goal")
        if next_goal is not None and not isinstance(next_goal, dict):
            raise ControlEventError("goal_change.next_goal 必须是 object")
        if not instruction and patch is None and next_goal is None:
            raise ControlEventError(
                "goal_change 至少需要 instruction、goal_patch 或 next_goal"
            )
        normalized = dict(payload)
        normalized["decision"] = decision
        if patch is not None:
            normalized["goal_patch"] = patch
        return normalized

    def _append_locked(self, path: Path, record: dict[str, Any]) -> dict[str, Any]:
        """在已持锁的情况下追加一条 JSONL 记录。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def submit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "human",
        source: str = "unknown",
        goal_id: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """提交一条待 Loop 消费的控制命令。"""
        event_type = self._validate_type(event_type, command=True)
        body = dict(payload or {})
        if event_type == "goal_change":
            body = self._validate_goal_change(body)
        elif event_type == "message":
            if not isinstance(body.get("text"), str) or not body["text"].strip():
                raise ControlEventError("message.text 不能为空")
        elif event_type == "clarification_response":
            if not body.get("request_id"):
                raise ControlEventError("clarification_response.request_id 不能为空")
            if not isinstance(body.get("answer"), str) or not body["answer"].strip():
                raise ControlEventError("clarification_response.answer 不能为空")

        record = {
            "schema_version": 1,
            "command_id": new_id("cmd"),
            "goal_id": goal_id,
            "type": event_type,
            "actor": str(actor or "unknown"),
            "source": str(source or "unknown"),
            "reply_to": reply_to,
            "created_at": now_ms(),
            "status": "queued",
            "payload": body,
        }
        with self._lock():
            return self._append_locked(self.commands_path, record)

    def append_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "loop",
        source: str = "orchestrator",
        goal_id: str | None = None,
        command_id: str | None = None,
        status: str = "recorded",
    ) -> dict[str, Any]:
        """追加一条面向 Master 和用户的回执事件。"""
        event_type = self._validate_type(event_type, command=False)
        record = {
            "schema_version": 1,
            "event_id": new_id("event"),
            "command_id": command_id,
            "goal_id": goal_id,
            "type": event_type,
            "actor": str(actor or "loop"),
            "source": str(source or "orchestrator"),
            "created_at": now_ms(),
            "status": str(status or "recorded"),
            "payload": dict(payload or {}),
        }
        with self._lock():
            return self._append_locked(self.events_path, record)

    def pending_commands(self) -> list[dict[str, Any]]:
        """读取上次游标之后的待处理命令。"""
        try:
            cursor_data = json.loads(self.cursor_path.read_text(encoding="utf-8"))
            start = max(0, int(cursor_data.get("line", 0)))
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            start = 0

        pending: list[dict[str, Any]] = []
        try:
            lines = self.commands_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return pending
        for line_number, line in enumerate(lines[start:], start=start):
            text = line.strip()
            if not text:
                continue
            try:
                command = json.loads(text)
            except json.JSONDecodeError:
                command = {
                    "command_id": f"invalid-line-{line_number}",
                    "type": "invalid",
                    "payload": {"raw": text},
                }
            if isinstance(command, dict):
                command["_line_number"] = line_number
                pending.append(command)
        return pending

    def advance(self, line_number: int) -> None:
        """把消费游标推进到指定行之后。"""
        atomic_write_json(self.cursor_path, {"line": int(line_number) + 1})

    def acknowledge(
        self,
        command: dict[str, Any],
        *,
        accepted: bool,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        """为已消费命令写入 accepted 或 rejected 回执。"""
        result = dict(payload or {})
        if error:
            result["error"] = error
        return self.append_event(
            "command_applied" if accepted else "command_rejected",
            result,
            goal_id=goal_id or command.get("goal_id"),
            command_id=command.get("command_id"),
            status="accepted" if accepted else "rejected",
        )

    def read_events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """读取回执事件，末尾不完整记录会被忽略。"""
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        rows: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        if limit == 0:
            return []
        if limit is not None and limit > 0:
            return rows[-limit:]
        return rows


__all__ = ["ControlEventError", "ControlEventStore"]
