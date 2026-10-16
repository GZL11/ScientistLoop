"""主控桥接所需的状态与指令文件。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import append_jsonl, atomic_write_json, atomic_write_text, new_id, now_ms, read_json
from ..domain.goal import GoalError, validate_goal_patch
from .control import ControlEventStore


class MasterBridge:
    """连接用户、主控与自主循环的桥接组件。"""
    def __init__(
        self,
        workspace: str | Path,
        *,
        control_events: ControlEventStore | None = None,
    ):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)
        self.control = self.workspace / "control"
        self.control.mkdir(parents=True, exist_ok=True)
        self.control_events = control_events or ControlEventStore(self.workspace)
        self.goal_patch_path = self.control / "goal_patch.json"
        self.applied_patch_log = self.control / "applied_goal_patches.jsonl"
        self.rejected_patch_log = self.control / "rejected_goal_patches.jsonl"
        self.clarification_path = self.control / "clarification_request.jsonl"
        self.status_summary_path = self.workspace / "status_summary.md"

    def submit_message(
        self,
        text: str,
        *,
        actor: str = "human",
        source: str = "master",
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        """提交一条不直接改变 Loop 状态的人类消息。"""
        return self.control_events.submit(
            "message",
            {"text": str(text)},
            actor=actor,
            source=source,
            goal_id=goal_id,
        )

    def request_control(
        self,
        action: str,
        *,
        reason: str = "external_control",
        actor: str = "human",
        source: str = "master",
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        """提交 pause、resume 或 stop 控制命令。"""
        if action not in {"pause", "resume", "stop"}:
            raise ValueError(f"不支持的控制动作: {action!r}")
        return self.control_events.submit(
            action,
            {"reason": reason},
            actor=actor,
            source=source,
            goal_id=goal_id,
        )

    def request_goal_change(
        self,
        *,
        decision: str,
        instruction: str | None = None,
        goal_patch: dict[str, Any] | None = None,
        next_goal: dict[str, Any] | None = None,
        reason: str = "human_goal_change",
        actor: str = "master",
        source: str = "master",
        goal_id: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """提交目标变更请求，由用户决定当前 Loop 的处置方式。"""
        payload: dict[str, Any] = {
            "decision": decision,
            "reason": reason,
        }
        if instruction:
            payload["instruction"] = instruction
        if goal_patch is not None:
            payload["goal_patch"] = goal_patch
        if next_goal is not None:
            payload["next_goal"] = next_goal
        return self.control_events.submit(
            "goal_change",
            payload,
            actor=actor,
            source=source,
            goal_id=goal_id,
            reply_to=reply_to,
        )

    def answer_clarification(
        self,
        request_id: str,
        answer: str,
        *,
        actor: str = "human",
        source: str = "master",
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        """提交对 Loop 澄清请求的回答。"""
        return self.control_events.submit(
            "clarification_response",
            {"request_id": request_id, "answer": answer},
            actor=actor,
            source=source,
            goal_id=goal_id,
        )

    def write_goal_patch(self, patch: dict[str, Any]) -> None:
        """写入目标补丁文件。"""
        payload = dict(patch)
        payload.setdefault("created_at", now_ms())
        atomic_write_json(self.goal_patch_path, validate_goal_patch(payload))

    def load_goal_patch(self) -> dict[str, Any] | None:
        """读取目标补丁文件。"""
        patch = read_json(self.goal_patch_path)
        return patch if isinstance(patch, dict) else None

    def clear_goal_patch(self) -> None:
        """删除已应用的目标补丁文件。"""
        self.goal_patch_path.unlink(missing_ok=True)

    def apply_goal_patch(self, state: dict[str, Any]) -> bool:
        """将目标补丁合并到当前目标。"""
        patch = self.load_goal_patch()
        if not patch:
            return False
        try:
            patch = validate_goal_patch(patch)
        except GoalError as exc:
            rejection = {
                "ts": now_ms(),
                "patch": patch,
                "error": str(exc),
            }
            append_jsonl(self.rejected_patch_log, rejection)
            rs = state.setdefault("research_state", {})
            audit = rs.setdefault("audit", {})
            audit.setdefault("goal_patch_rejections", []).append(rejection)
            rs["last_goal_patch_error"] = str(exc)
            self.clear_goal_patch()
            return False
        rs = state.setdefault("research_state", {})
        goal = rs.setdefault("goal", {})
        changes = patch["changes"]

        # 第一版只支持小而明确的目标补丁范围：目标描述与约束。
        if isinstance(changes.get("objective_brief"), dict):
            brief = goal.setdefault("objective_brief", {})
            _deep_merge(brief, changes["objective_brief"])
        if isinstance(changes.get("constraints"), dict):
            constraints = goal.setdefault("constraints", {})
            _deep_merge(constraints, changes["constraints"])

        rs.setdefault("goal_patch_history", []).append({
            "ts": now_ms(),
            "reason": patch.get("reason", "unspecified"),
            "changes": changes,
        })
        append_jsonl(self.applied_patch_log, {"ts": now_ms(), "patch": patch})
        self.clear_goal_patch()
        return True

    def request_clarification(self, request: dict[str, Any]) -> None:
        """记录需要用户澄清的问题。"""
        payload = dict(request)
        payload.setdefault("request_id", new_id("clarification"))
        payload.setdefault("created_at", now_ms())
        payload.setdefault("status", "open")
        append_jsonl(self.clarification_path, payload)
        self.control_events.append_event(
            "clarification_request",
            payload,
            goal_id=payload.get("goal_id"),
        )

    def write_handoff(
        self,
        state: dict[str, Any],
        queue_summary: dict[str, Any],
        *,
        reason: str,
        next_goal: dict[str, Any] | None = None,
    ) -> Path:
        """生成供后续 Loop 和 Agent 阅读的紧凑交接记录。"""
        rs = state.get("research_state", {})
        handoff = {
            "schema_version": 1,
            "created_at": now_ms(),
            "goal_id": rs.get("goal_id"),
            "status": rs.get("status"),
            "termination_reason": reason,
            "goal": rs.get("goal", {}),
            "goal_revision": rs.get("goal_revision", 1),
            "lineage": rs.get("lineage", {}),
            "leaderboard": rs.get("leaderboard", {}),
            "queues": queue_summary,
            "artifact_index": rs.get("artifact_index_ref"),
            "decision_log": rs.get("decision_log_ref"),
            "expbank_dir": str(self.workspace / "expbank"),
            "shared_experience_pool": str(self.workspace / "shared_experience_pool"),
            "next_goal": next_goal,
            "read_first": [
                "handoff.md",
                "expbank/INDEX.md",
                "status_summary.md",
                "research_state.yaml",
                "artifacts/artifact_index.jsonl",
                "artifacts/decision_log.jsonl",
            ],
        }
        json_path = self.workspace / "handoff.json"
        markdown_path = self.workspace / "handoff.md"
        atomic_write_json(json_path, handoff)
        lines = [
            f"# Loop Handoff: {handoff.get('goal_id', 'unknown')}",
            "",
            f"- 状态：`{handoff.get('status', '')}`",
            f"- 结束原因：`{reason}`",
            f"- 目标版本：`{handoff.get('goal_revision', 1)}`",
            f"- ExpBank：`{handoff.get('expbank_dir')}`",
            f"- 共享经验池：`{handoff.get('shared_experience_pool')}`",
            "",
            "## 后续 Agent 建议阅读",
            "",
        ]
        lines.extend(f"- `{item}`" for item in handoff["read_first"])
        lineage = handoff.get("lineage") or {}
        prior_loop_dirs = lineage.get("prior_loop_dirs") or []
        if prior_loop_dirs:
            lines.extend(["", "## 可读取的历史 Loop", ""])
            lines.extend(f"- `{item}`（只读）" for item in prior_loop_dirs)
        lines.extend(["", "## 队列快照", "", "```json", json.dumps(queue_summary, ensure_ascii=False, indent=2), "```", ""])
        if next_goal:
            lines.extend(["## 下一目标请求", "", "```json", json.dumps(next_goal, ensure_ascii=False, indent=2), "```", ""])
        atomic_write_text(markdown_path, "\n".join(lines))
        return markdown_path

    def render_status_summary(self, state: dict[str, Any], queue_summary: dict[str, Any]) -> str:
        """渲染主控可读的状态摘要。"""
        rs = state.get("research_state", {})
        budget = rs.get("evaluator_budget", {})
        leaderboard = rs.get("leaderboard", {})
        goal = rs.get("goal", {})
        lines = [
            f"# Loop Status Summary: {rs.get('goal_id', 'unknown')}",
            "",
            f"- Status: `{rs.get('status', 'unknown')}`",
            f"- Termination reason: `{rs.get('termination_reason', '')}`",
            f"- Current phase: `{rs.get('current_phase', '')}`",
            f"- Lifecycle: `{rs.get('lifecycle', 'active')}`",
            f"- Goal revision: `{rs.get('goal_revision', 1)}`",
            f"- Last heartbeat: `{rs.get('last_heartbeat_at', '')}`",
            f"- Goal: {goal.get('name', '')}",
            f"- Domain: {goal.get('domain', '')}",
            f"- Updated: {rs.get('updated_at', '')}",
            f"- Evaluator submissions: {budget.get('used_submissions', 0)}/{budget.get('max_submissions', 0)}",
            "",
            "## Runtime Limits",
            f"- {rs.get('runtime_limits', {})}",
            "",
            "## Best Score",
            f"- {leaderboard.get('metric')}: {leaderboard.get('best_value')} "
            f"(branch={leaderboard.get('branch_id')}, source={leaderboard.get('source', '')})",
            "",
            "## Queues",
        ]
        for name, summary in queue_summary.items():
            lines.append(f"- {name}: {summary}")
        lines.extend(["", "## Branches"])
        branches = rs.get("branches") or []
        if not branches:
            lines.append("- No branches yet.")
        else:
            for b in branches[-10:]:
                lines.append(f"- {b.get('branch_id')}: {b.get('status')} idea={b.get('idea_id')}")
        history = rs.get("goal_patch_history") or []
        if history:
            lines.extend(["", "## Recent Goal Patches"])
            for h in history[-5:]:
                lines.append(f"- {h.get('ts')}: {h.get('reason')}")
        pending = rs.get("pending_goal_change")
        if pending:
            lines.extend(["", "## Pending Goal Change", f"- decision: `{pending.get('decision', '')}`", f"- reason: {pending.get('reason', '')}"])
        text = "\n".join(lines) + "\n"
        self.status_summary_path.write_text(text, encoding="utf-8")
        return text


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个字典。"""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value
    return dst
