"""聊天触发自主科研 Loop 的提议、确认和后台启动控制器。

聊天层的职责是把 Master Agent 的判断转换成可审计的 ``GoalProposal``，
而不是直接拼接一条 shell 命令。用户确认后，本模块再生成标准 ``goal.yaml``，
并通过现有 ``famou_scientist loop run`` 启动统一调度器。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Iterator

from ..domain.goal import GoalError, load_goal
from ..utils import (
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    new_id,
    now_ms,
    read_json,
    safe_name,
)
from .master_bridge import MasterBridge

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None


class ChatGoalError(ValueError):
    """表示聊天 Goal 控制请求不符合协议。"""


class ProposalStatus:
    """定义 GoalProposal 的生命周期状态。"""

    PENDING = "pending"
    NEEDS_CLARIFICATION = "needs_clarification"
    CHAT_ONLY = "chat_only"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"

    @classmethod
    def values(cls) -> set[str]:
        """返回全部受支持的提议状态。"""
        return {
            cls.PENDING,
            cls.NEEDS_CLARIFICATION,
            cls.CHAT_ONLY,
            cls.CONFIRMED,
            cls.REJECTED,
            cls.STARTING,
            cls.RUNNING,
            cls.STOPPED,
            cls.COMPLETED,
            cls.FAILED,
            cls.SUPERSEDED,
        }


class HumanPolicy:
    """定义聊天控制面的人类授权策略。"""

    CONFIRM = "confirm"
    AUTO = "auto"

    @classmethod
    def values(cls) -> set[str]:
        """返回可用的人类授权策略。"""
        return {cls.CONFIRM, cls.AUTO}


class MasterDecision:
    """定义 Master 对当前用户消息的 Loop 进入判定。"""

    ENTER_LOOP = "enter_loop"
    STAY_IN_CHAT = "stay_in_chat"
    NEEDS_CLARIFICATION = "needs_clarification"

    @classmethod
    def values(cls) -> set[str]:
        """返回可用的 Master 决策。"""
        return {
            cls.ENTER_LOOP,
            cls.STAY_IN_CHAT,
            cls.NEEDS_CLARIFICATION,
        }


@dataclass
class GoalProposal:
    """保存一次聊天消息对应的、等待用户确认的标准化目标提议。"""

    proposal_id: str
    conversation_id: str
    raw_user_message: str
    status: str
    human_policy: str
    master_decision: str
    decision_reason: str
    confidence: Any
    assumptions: list[str]
    missing_information: list[str]
    goal_document: dict[str, Any]
    created_at: int
    updated_at: int
    source: str = "opencode-master"
    goal_id: str | None = None
    goal_file: str | None = None
    started_at: int | None = None
    finished_at: int | None = None
    process: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_mapping(
        cls,
        value: dict[str, Any],
        *,
        conversation_id: str,
        default_policy: str = HumanPolicy.CONFIRM,
        source: str = "opencode-master",
        proposal_id: str | None = None,
    ) -> "GoalProposal":
        """将 Master 输出的 object 归一化为 GoalProposal。"""
        if not isinstance(value, dict):
            raise ChatGoalError("GoalProposal 顶层必须是 object")
        if not str(conversation_id or "").strip():
            raise ChatGoalError("conversation_id 不能为空")

        raw_message = str(
            value.get("raw_user_message")
            or value.get("raw_instruction")
            or value.get("instruction")
            or ""
        ).strip()
        if not raw_message:
            raise ChatGoalError("GoalProposal 必须保留 raw_user_message")

        decision = str(
            value.get("master_decision")
            or value.get("decision")
            or MasterDecision.ENTER_LOOP
        ).strip()
        if decision not in MasterDecision.values():
            raise ChatGoalError(
                "master_decision 必须是 enter_loop、stay_in_chat 或 needs_clarification"
            )

        policy_value = value.get("human_policy", default_policy)
        if isinstance(policy_value, dict):
            policy_value = policy_value.get("mode")
        policy = str(policy_value or default_policy).strip()
        if policy not in HumanPolicy.values():
            raise ChatGoalError("human_policy.mode 必须是 confirm 或 auto")

        actual_proposal_id = proposal_id or new_id("proposal")
        goal_document = _goal_document_from_proposal(value, raw_message)
        goal = goal_document["goal"]
        goal_id = str(goal["id"])
        timestamp = now_ms()
        if decision == MasterDecision.STAY_IN_CHAT:
            status = ProposalStatus.CHAT_ONLY
        elif decision == MasterDecision.NEEDS_CLARIFICATION:
            status = ProposalStatus.NEEDS_CLARIFICATION
        else:
            status = ProposalStatus.PENDING

        assumptions = _string_list(value.get("assumptions"))
        missing = _string_list(value.get("missing_information"))
        if goal_document.get("constraints", {}).get("max_wall_time_hours") is None:
            goal_document["constraints"]["max_wall_time_hours"] = 4.0
            assumptions.append("未指定墙钟预算，暂按 4 小时生成提议；用户可在确认前修改。")
        goal_document.setdefault("provenance", {})
        goal_document["provenance"].update(
            {
                "proposal_id": actual_proposal_id,
                "conversation_id": conversation_id,
                "raw_user_message": raw_message,
                "master_decision": decision,
                "decision_reason": str(value.get("decision_reason") or "").strip(),
                "source": source,
            }
        )
        return cls(
            proposal_id=actual_proposal_id,
            conversation_id=str(conversation_id),
            raw_user_message=raw_message,
            status=status,
            human_policy=policy,
            master_decision=decision,
            decision_reason=str(value.get("decision_reason") or "").strip(),
            confidence=value.get("confidence"),
            assumptions=_unique(assumptions),
            missing_information=missing,
            goal_document=goal_document,
            created_at=timestamp,
            updated_at=timestamp,
            source=str(source or "unknown"),
            goal_id=goal_id,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoalProposal":
        """从持久化 JSON 恢复 GoalProposal。"""
        if not isinstance(value, dict):
            raise ChatGoalError("持久化的 GoalProposal 必须是 object")
        required = {
            "proposal_id",
            "conversation_id",
            "raw_user_message",
            "status",
            "human_policy",
            "master_decision",
            "goal_document",
        }
        missing = sorted(key for key in required if key not in value)
        if missing:
            raise ChatGoalError(f"GoalProposal 缺少字段: {missing}")
        proposal = cls(
            proposal_id=str(value["proposal_id"]),
            conversation_id=str(value["conversation_id"]),
            raw_user_message=str(value["raw_user_message"]),
            status=str(value["status"]),
            human_policy=str(value["human_policy"]),
            master_decision=str(value["master_decision"]),
            decision_reason=str(value.get("decision_reason") or ""),
            confidence=value.get("confidence"),
            assumptions=_string_list(value.get("assumptions")),
            missing_information=_string_list(value.get("missing_information")),
            goal_document=dict(value["goal_document"]),
            created_at=int(value.get("created_at") or now_ms()),
            updated_at=int(value.get("updated_at") or now_ms()),
            source=str(value.get("source") or "unknown"),
            goal_id=str(value.get("goal_id")) if value.get("goal_id") else None,
            goal_file=str(value.get("goal_file")) if value.get("goal_file") else None,
            started_at=int(value["started_at"]) if value.get("started_at") else None,
            finished_at=int(value["finished_at"]) if value.get("finished_at") else None,
            process=dict(value["process"]) if isinstance(value.get("process"), dict) else None,
            error=str(value.get("error")) if value.get("error") else None,
        )
        proposal.validate()
        return proposal

    def validate(self) -> None:
        """校验提议的状态和目标字段。"""
        if not self.proposal_id or safe_name(self.proposal_id) != self.proposal_id:
            raise ChatGoalError(f"非法 proposal_id: {self.proposal_id!r}")
        if self.status not in ProposalStatus.values():
            raise ChatGoalError(f"未知 GoalProposal status: {self.status!r}")
        if self.human_policy not in HumanPolicy.values():
            raise ChatGoalError(f"未知 human_policy: {self.human_policy!r}")
        if self.master_decision not in MasterDecision.values():
            raise ChatGoalError(f"未知 master_decision: {self.master_decision!r}")
        if not isinstance(self.goal_document, dict):
            raise ChatGoalError("goal_document 必须是 object")

    def to_dict(self) -> dict[str, Any]:
        """返回用于审计和 JSON 序列化的完整提议。"""
        self.validate()
        return {
            "schema_version": 1,
            "proposal_id": self.proposal_id,
            "conversation_id": self.conversation_id,
            "raw_user_message": self.raw_user_message,
            "status": self.status,
            "human_policy": self.human_policy,
            "master_decision": self.master_decision,
            "decision_reason": self.decision_reason,
            "confidence": self.confidence,
            "assumptions": self.assumptions,
            "missing_information": self.missing_information,
            "goal_id": self.goal_id,
            "goal_file": self.goal_file,
            "goal_document": self.goal_document,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "process": self.process,
            "error": self.error,
            "source": self.source,
        }


class ChatGoalController:
    """管理聊天会话的 GoalProposal，并启动已有 Loop 调度器。"""

    DEFAULT_WALL_TIME_HOURS = 4.0

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        project_root: str | Path | None = None,
        process_launcher: Callable[..., Any] | None = None,
    ) -> None:
        """初始化控制器目录、事件日志和可选的进程启动器。"""
        self.loop_root = (
            Path(root).expanduser().resolve()
            if root is not None
            else (Path.cwd() / ".famou" / "loop").resolve()
        )
        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else Path.cwd().resolve()
        )
        self.control_root = self.loop_root.parent / "goal-controller"
        self.proposals_dir = self.control_root / "proposals"
        self.goals_dir = self.control_root / "goals"
        self.logs_dir = self.control_root / "logs"
        self.sessions_dir = self.control_root / "sessions"
        self.policies_dir = self.control_root / "policies"
        self.events_path = self.control_root / "events.jsonl"
        self.lock_path = self.control_root / "controller.lock"
        self._process_launcher = process_launcher or subprocess.Popen
        for directory in (
            self.proposals_dir,
            self.goals_dir,
            self.logs_dir,
            self.sessions_dir,
            self.policies_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """串行化聊天入口对 proposal/session 文件的更新。"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _session_key(self, conversation_id: str) -> str:
        """将会话标识转换为不可越界的稳定文件名。"""
        return hashlib.sha256(str(conversation_id).encode("utf-8")).hexdigest()[:32]

    def _session_path(self, conversation_id: str) -> Path:
        """返回一个聊天会话的当前 Loop 记录路径。"""
        return self.sessions_dir / f"{self._session_key(conversation_id)}.json"

    def _proposal_path(self, proposal_id: str) -> Path:
        """返回一个提议的持久化路径。"""
        if safe_name(proposal_id) != proposal_id:
            raise ChatGoalError(f"非法 proposal_id: {proposal_id!r}")
        return self.proposals_dir / f"{proposal_id}.json"

    def _policy_path(self, conversation_id: str) -> Path:
        """返回一个会话授权策略的持久化路径。"""
        return self.policies_dir / f"{self._session_key(conversation_id)}.json"

    def _write_proposal(self, proposal: GoalProposal) -> None:
        """原子写入完整 GoalProposal。"""
        proposal.updated_at = now_ms()
        atomic_write_json(self._proposal_path(proposal.proposal_id), proposal.to_dict())

    def _read_proposal(self, proposal_id: str) -> GoalProposal:
        """读取并校验一条 GoalProposal。"""
        value = read_json(self._proposal_path(proposal_id))
        if not isinstance(value, dict):
            raise ChatGoalError(f"未找到 GoalProposal: {proposal_id}")
        return GoalProposal.from_dict(value)

    def _write_session(self, conversation_id: str, value: dict[str, Any]) -> None:
        """原子写入会话当前 Loop 摘要。"""
        value = dict(value)
        value["conversation_id"] = conversation_id
        value["updated_at"] = now_ms()
        atomic_write_json(self._session_path(conversation_id), value)

    def _read_session(self, conversation_id: str) -> dict[str, Any]:
        """读取会话摘要，不存在时返回空 object。"""
        value = read_json(self._session_path(conversation_id), {})
        return dict(value) if isinstance(value, dict) else {}

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        """追加一条聊天控制面的审计事件。"""
        append_jsonl(
            self.events_path,
            {
                "schema_version": 1,
                "event_id": new_id("chat_event"),
                "type": event_type,
                "created_at": now_ms(),
                "payload": payload,
            },
        )

    def set_policy(
        self,
        conversation_id: str,
        mode: str,
        *,
        actor: str = "human",
        source: str = "chat",
        authorization_text: str | None = None,
    ) -> dict[str, Any]:
        """设置会话级 confirm/auto 策略，并保留授权证据。"""
        mode = str(mode or "").strip()
        if mode not in HumanPolicy.values():
            raise ChatGoalError("策略必须是 confirm 或 auto")
        authorization = str(authorization_text or "").strip()
        if mode == HumanPolicy.AUTO and not authorization:
            raise ChatGoalError(
                "启用全自动策略必须保留用户明确授权的原始文本，不能由 Master 自行推断。"
            )
        record = {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "mode": mode,
            "actor": actor,
            "source": source,
            "authorization_text": authorization,
            "created_at": now_ms(),
        }
        with self._lock():
            atomic_write_json(self._policy_path(conversation_id), record)
            self._event("policy_changed", record)
        return record

    def policy(self, conversation_id: str) -> dict[str, Any]:
        """读取会话级授权策略；默认必须确认。"""
        value = read_json(self._policy_path(conversation_id))
        if isinstance(value, dict) and value.get("mode") in HumanPolicy.values():
            return value
        return {
            "conversation_id": conversation_id,
            "mode": HumanPolicy.CONFIRM,
            "source": "default",
        }

    def propose(
        self,
        value: dict[str, Any],
        *,
        conversation_id: str,
        mode: str | None = None,
        auto_authorized: bool = False,
        authorization_text: str | None = None,
        source: str = "opencode-master",
    ) -> dict[str, Any]:
        """记录 Master 提议，并按授权策略决定是否立即启动。"""
        policy = self.policy(conversation_id)
        requested_mode = mode or value.get("human_policy") or policy.get("mode")
        if isinstance(requested_mode, dict):
            requested_mode = requested_mode.get("mode")
        requested_mode = str(requested_mode or HumanPolicy.CONFIRM)
        authorization = str(authorization_text or "").strip()
        if requested_mode == HumanPolicy.AUTO and policy.get("mode") != HumanPolicy.AUTO:
            if not auto_authorized or not authorization:
                raise ChatGoalError(
                    "当前会话没有全自动授权；一次性 auto 必须保留用户明确授权的原始文本。"
                )
            raw_message = str(
                value.get("raw_user_message")
                or value.get("raw_instruction")
                or value.get("instruction")
                or ""
            ).strip()
            if authorization != raw_message:
                raise ChatGoalError(
                    "一次性 auto 的 authorization_text 必须与 raw_user_message 完全一致。"
                )
        proposal = GoalProposal.from_mapping(
            value,
            conversation_id=conversation_id,
            default_policy=requested_mode,
            source=source,
        )
        proposal.human_policy = requested_mode
        if authorization:
            proposal.goal_document.setdefault("provenance", {})[
                "auto_authorization_text"
            ] = authorization
        with self._lock():
            current = self._refresh_session_locked(conversation_id)
            if current.get("status") == ProposalStatus.RUNNING:
                raise ChatGoalError(
                    f"当前会话已有运行中的 Loop: {current.get('goal_id')}; "
                    "请先暂停/停止，或把新消息作为当前 Loop 的 message。"
                )
            # 用户修改待确认目标时，新 Proposal 成为唯一当前版本；旧版本仍完整
            # 留存，但显式标记 superseded，避免后续 confirm 误启动过期目标。
            previous_id = str(current.get("proposal_id") or "")
            if previous_id:
                try:
                    previous = self._read_proposal(previous_id)
                    if previous.status in {
                        ProposalStatus.PENDING,
                        ProposalStatus.NEEDS_CLARIFICATION,
                    }:
                        previous.status = ProposalStatus.SUPERSEDED
                        previous.error = f"superseded_by:{proposal.proposal_id}"
                        self._write_proposal(previous)
                        self._event(
                            "proposal_superseded",
                            {
                                "proposal_id": previous.proposal_id,
                                "superseded_by": proposal.proposal_id,
                                "conversation_id": conversation_id,
                            },
                        )
                except ChatGoalError:
                    pass
            self._write_proposal(proposal)
            self._write_session(
                conversation_id,
                {
                    "status": proposal.status,
                    "proposal_id": proposal.proposal_id,
                    "goal_id": proposal.goal_id,
                },
            )
            self._event("proposal_created", proposal.to_dict())
        if proposal.human_policy == HumanPolicy.AUTO and proposal.master_decision == MasterDecision.ENTER_LOOP:
            return self.start(proposal.proposal_id, conversation_id=conversation_id, auto_approved=True)
        return proposal.to_dict()

    def confirm(
        self,
        *,
        conversation_id: str,
        proposal_id: str | None = None,
        source: str = "chat",
    ) -> dict[str, Any]:
        """确认当前会话的提议，并启动后台 Loop。"""
        with self._lock():
            proposal = self._latest_proposal_locked(conversation_id, proposal_id)
            if proposal.status not in {ProposalStatus.PENDING, ProposalStatus.NEEDS_CLARIFICATION}:
                raise ChatGoalError(f"当前提议不能确认，状态为 {proposal.status}")
            if proposal.master_decision != MasterDecision.ENTER_LOOP:
                raise ChatGoalError("Master 判定当前消息不应进入 Loop，不能直接确认")
            proposal.status = ProposalStatus.CONFIRMED
            proposal.updated_at = now_ms()
            self._write_proposal(proposal)
            self._event(
                "proposal_confirmed",
                {"proposal_id": proposal.proposal_id, "conversation_id": conversation_id, "source": source},
            )
        return self.start(proposal.proposal_id, conversation_id=conversation_id, auto_approved=False)

    def reject(
        self,
        *,
        conversation_id: str,
        proposal_id: str | None = None,
        reason: str = "rejected_by_user",
    ) -> dict[str, Any]:
        """拒绝当前提议，并保留原始内容。"""
        with self._lock():
            proposal = self._latest_proposal_locked(conversation_id, proposal_id)
            if proposal.status not in {ProposalStatus.PENDING, ProposalStatus.NEEDS_CLARIFICATION}:
                raise ChatGoalError(f"当前提议不能拒绝，状态为 {proposal.status}")
            proposal.status = ProposalStatus.REJECTED
            proposal.error = reason
            self._write_proposal(proposal)
            self._write_session(
                conversation_id,
                {"status": ProposalStatus.REJECTED, "proposal_id": proposal.proposal_id, "goal_id": proposal.goal_id},
            )
            self._event(
                "proposal_rejected",
                {"proposal_id": proposal.proposal_id, "conversation_id": conversation_id, "reason": reason},
            )
        return proposal.to_dict()

    def start(
        self,
        proposal_id: str,
        *,
        conversation_id: str,
        auto_approved: bool,
    ) -> dict[str, Any]:
        """把已确认提议转换为 goal.yaml，并以独立进程启动 Loop。"""
        with self._lock():
            proposal = self._read_proposal(proposal_id)
            if proposal.conversation_id != conversation_id:
                raise ChatGoalError("proposal 不属于当前聊天会话")
            if proposal.status == ProposalStatus.RUNNING:
                return proposal.to_dict()
            if proposal.status not in {ProposalStatus.CONFIRMED, ProposalStatus.PENDING}:
                raise ChatGoalError(f"当前提议不能启动，状态为 {proposal.status}")
            if proposal.master_decision != MasterDecision.ENTER_LOOP:
                raise ChatGoalError("Master 没有判定进入 Loop")
            current = self._refresh_session_locked(conversation_id)
            if current.get("status") == ProposalStatus.RUNNING:
                raise ChatGoalError(f"当前会话已有运行中的 Loop: {current.get('goal_id')}")

            goal_document = dict(proposal.goal_document)
            workflow = goal_document.get("workflow")
            workflow_type = workflow.get("type") if isinstance(workflow, dict) else "research"
            if workflow_type == "benchmark_managed":
                raise ChatGoalError(
                    "benchmark_managed 需要外部 Harness 提供 task/evaluator 通道，"
                    "请使用 famou-scientist agent run；聊天层先保留该 Proposal，不直接伪造通道。"
                )
            goal_file = self.goals_dir / f"{proposal.goal_id}.yaml"
            goal_document.setdefault("provenance", {})["proposal_id"] = proposal.proposal_id
            _write_goal_document(goal_file, goal_document)
            try:
                loaded_goal = load_goal(goal_file)
                _validate_research_launch(loaded_goal)
            except GoalError as exc:
                proposal.status = ProposalStatus.FAILED
                proposal.error = str(exc)
                self._write_proposal(proposal)
                self._event("loop_start_rejected", {"proposal_id": proposal.proposal_id, "error": str(exc)})
                raise ChatGoalError(f"生成的 goal.yaml 未通过校验: {exc}") from exc
            except ChatGoalError as exc:
                proposal.status = ProposalStatus.NEEDS_CLARIFICATION
                proposal.error = str(exc)
                self._write_proposal(proposal)
                self._write_session(
                    conversation_id,
                    {
                        "status": ProposalStatus.NEEDS_CLARIFICATION,
                        "proposal_id": proposal.proposal_id,
                        "goal_id": proposal.goal_id,
                    },
                )
                self._event(
                    "loop_start_rejected",
                    {"proposal_id": proposal.proposal_id, "error": str(exc)},
                )
                raise

            proposal.status = ProposalStatus.STARTING
            proposal.goal_file = str(goal_file)
            proposal.started_at = now_ms()
            proposal.process = {"status": ProposalStatus.STARTING}
            self._write_proposal(proposal)
            out_path = self.logs_dir / f"{proposal.goal_id}.stdout.log"
            err_path = self.logs_dir / f"{proposal.goal_id}.stderr.log"
            command = [
                sys.executable,
                "-m",
                "famou_scientist",
                "loop",
                "run",
                "--goal-file",
                str(goal_file),
                "--root",
                str(self.loop_root),
                "--async-pipeline",
                "--max-ticks",
                "-1",
            ]
            env = os.environ.copy()
            env.setdefault("FAMOU_CHAT_SESSION_ID", conversation_id)
            try:
                stdout = out_path.open("a", encoding="utf-8")
                stderr = err_path.open("a", encoding="utf-8")
                process = self._process_launcher(
                    command,
                    cwd=str(self.project_root),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
            except Exception as exc:  # noqa: BLE001 - 启动失败需要落盘
                proposal.status = ProposalStatus.FAILED
                proposal.error = repr(exc)
                self._write_proposal(proposal)
                self._event("loop_start_failed", {"proposal_id": proposal.proposal_id, "error": repr(exc)})
                raise ChatGoalError(f"后台 Loop 启动失败: {exc}") from exc
            finally:
                for handle in locals().get("stdout"), locals().get("stderr"):
                    if handle is not None:
                        handle.close()

            pid = int(getattr(process, "pid", 0) or 0)
            proposal.status = ProposalStatus.RUNNING
            proposal.process = {
                "status": ProposalStatus.RUNNING,
                "pid": pid,
                "command": command,
                "stdout_log": str(out_path),
                "stderr_log": str(err_path),
                "auto_approved": bool(auto_approved),
            }
            self._write_proposal(proposal)
            self._write_session(
                conversation_id,
                {
                    "status": ProposalStatus.RUNNING,
                    "proposal_id": proposal.proposal_id,
                    "goal_id": proposal.goal_id,
                    "pid": pid,
                    "goal_file": str(goal_file),
                    "workspace": str(self.loop_root / str(proposal.goal_id)),
                },
            )
            self._event(
                "loop_started",
                {
                    "proposal_id": proposal.proposal_id,
                    "conversation_id": conversation_id,
                    "goal_id": proposal.goal_id,
                    "pid": pid,
                    "command": command,
                    "auto_approved": bool(auto_approved),
                },
            )
            return proposal.to_dict()

    def status(self, conversation_id: str) -> dict[str, Any]:
        """返回聊天会话的提议、授权策略和当前 Loop 状态。"""
        with self._lock():
            session = self._refresh_session_locked(conversation_id)
            proposal_id = session.get("proposal_id")
            proposal = None
            if proposal_id:
                try:
                    proposal = self._read_proposal(str(proposal_id)).to_dict()
                except ChatGoalError:
                    proposal = None
            return {
                "conversation_id": conversation_id,
                "policy": self.policy(conversation_id),
                "session": session,
                "proposal": proposal,
            }

    def control(
        self,
        conversation_id: str,
        action: str,
        *,
        reason: str = "chat_goal_control",
    ) -> dict[str, Any]:
        """向当前会话的活动 Loop 提交 pause、resume 或 stop。"""
        action = str(action or "").strip()
        if action not in {"pause", "resume", "stop"}:
            raise ChatGoalError("控制动作必须是 pause、resume 或 stop")
        with self._lock():
            session, goal_id, bridge = self._active_bridge_locked(conversation_id)
            record = bridge.request_control(
                action,
                reason=reason,
                actor="human",
                source="chat-goal-controller",
                goal_id=goal_id,
            )
            workspace = self.loop_root / goal_id
            control = workspace / "control"
            control.mkdir(parents=True, exist_ok=True)
            if action in {"pause", "stop"}:
                (control / action).write_text("1\n", encoding="utf-8")
            else:
                (control / "pause").unlink(missing_ok=True)
                (control / "stop").unlink(missing_ok=True)
            session["last_control"] = {
                "action": action,
                "reason": reason,
                "command_id": record["command_id"],
                "created_at": now_ms(),
            }
            self._write_session(conversation_id, session)
            self._event(
                "loop_control_queued",
                {
                    "conversation_id": conversation_id,
                    "goal_id": goal_id,
                    "action": action,
                    "command_id": record["command_id"],
                },
            )
            return {
                "conversation_id": conversation_id,
                "goal_id": goal_id,
                "action": action,
                "command": record,
            }

    def submit_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        """把用户对当前研究的补充意见追加到 Loop 入站总线。"""
        message = str(text or "").strip()
        if not message:
            raise ChatGoalError("message 文本不能为空")
        with self._lock():
            _, goal_id, bridge = self._active_bridge_locked(conversation_id)
            record = bridge.submit_message(
                message,
                actor="human",
                source="chat-goal-controller",
                goal_id=goal_id,
            )
            self._event(
                "loop_message_queued",
                {
                    "conversation_id": conversation_id,
                    "goal_id": goal_id,
                    "command_id": record["command_id"],
                },
            )
            return {
                "conversation_id": conversation_id,
                "goal_id": goal_id,
                "action": "message",
                "command": record,
            }

    def answer_clarification(
        self,
        conversation_id: str,
        request_id: str,
        text: str,
    ) -> dict[str, Any]:
        """把用户对 Loop 澄清请求的回答写入同一控制总线。"""
        request = str(request_id or "").strip()
        answer = str(text or "").strip()
        if not request or not answer:
            raise ChatGoalError("clarification answer 需要 request_id 和非空文本")
        with self._lock():
            _, goal_id, bridge = self._active_bridge_locked(conversation_id)
            record = bridge.answer_clarification(
                request,
                answer,
                actor="human",
                source="chat-goal-controller",
                goal_id=goal_id,
            )
            self._event(
                "clarification_answer_queued",
                {
                    "conversation_id": conversation_id,
                    "goal_id": goal_id,
                    "request_id": request,
                    "command_id": record["command_id"],
                },
            )
            return {
                "conversation_id": conversation_id,
                "goal_id": goal_id,
                "action": "answer",
                "command": record,
            }

    def request_goal_change(
        self,
        conversation_id: str,
        *,
        decision: str,
        instruction: str,
        goal_patch: dict[str, Any] | None = None,
        next_goal: dict[str, Any] | None = None,
        reason: str = "human_goal_change",
    ) -> dict[str, Any]:
        """按用户选择提交继续当前 Loop 或停止后换目标的请求。"""
        decision = str(decision or "").strip()
        instruction = str(instruction or "").strip()
        if decision not in {"continue_current", "stop_current"}:
            raise ChatGoalError("goal change decision 必须是 continue_current 或 stop_current")
        if not instruction:
            raise ChatGoalError("goal change 必须保留用户的新指令")
        with self._lock():
            _, goal_id, bridge = self._active_bridge_locked(conversation_id)
            record = bridge.request_goal_change(
                decision=decision,
                instruction=instruction,
                goal_patch=goal_patch,
                next_goal=next_goal,
                reason=str(reason or "human_goal_change"),
                actor="human",
                source="chat-goal-controller",
                goal_id=goal_id,
            )
            self._event(
                "loop_goal_change_queued",
                {
                    "conversation_id": conversation_id,
                    "goal_id": goal_id,
                    "decision": decision,
                    "command_id": record["command_id"],
                },
            )
            return {
                "conversation_id": conversation_id,
                "goal_id": goal_id,
                "action": "goal_change",
                "decision": decision,
                "command": record,
            }

    def _active_bridge_locked(
        self,
        conversation_id: str,
    ) -> tuple[dict[str, Any], str, MasterBridge]:
        """在已持锁时解析当前活动 Loop 及其 MasterBridge。"""
        session = self._refresh_session_locked(conversation_id)
        if session.get("status") != ProposalStatus.RUNNING:
            raise ChatGoalError("当前会话没有运行中或暂停中的 Loop")
        goal_id = str(session.get("goal_id") or "")
        if not goal_id:
            raise ChatGoalError("当前会话缺少活动 Loop 的 goal_id")
        return session, goal_id, MasterBridge(self.loop_root / goal_id)

    def _latest_proposal_locked(
        self,
        conversation_id: str,
        proposal_id: str | None,
    ) -> GoalProposal:
        """在已持有控制器锁时读取指定或最新提议。"""
        if proposal_id:
            proposal = self._read_proposal(proposal_id)
        else:
            candidates: list[GoalProposal] = []
            for path in self.proposals_dir.glob("proposal_*.json"):
                try:
                    candidate = GoalProposal.from_dict(read_json(path, {}))
                except (ChatGoalError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if candidate.conversation_id == conversation_id:
                    candidates.append(candidate)
            if not candidates:
                raise ChatGoalError("当前会话没有 GoalProposal")
            proposal = max(candidates, key=lambda item: item.updated_at)
        if proposal.conversation_id != conversation_id:
            raise ChatGoalError("proposal 不属于当前聊天会话")
        return proposal

    def _refresh_session_locked(self, conversation_id: str) -> dict[str, Any]:
        """根据 Loop ResearchState 刷新会话摘要。"""
        session = self._read_session(conversation_id)
        if session.get("status") != ProposalStatus.RUNNING:
            return session
        goal_id = session.get("goal_id")
        if not goal_id:
            return session
        state_path = self.loop_root / str(goal_id) / "research_state.yaml"
        state = read_json(state_path, {})
        research_state = state.get("research_state") if isinstance(state, dict) else None
        runtime_status = research_state.get("status") if isinstance(research_state, dict) else None
        if runtime_status == "paused":
            session["loop_status"] = "paused"
            self._write_session(conversation_id, session)
            return session
        terminal = {"completed", "stopped", "failed"}
        if runtime_status in terminal:
            session["status"] = runtime_status
            session["loop_status"] = runtime_status
            session["finished_at"] = now_ms()
            self._write_session(conversation_id, session)
            proposal_id = session.get("proposal_id")
            if proposal_id:
                try:
                    proposal = self._read_proposal(str(proposal_id))
                    proposal.status = (
                        ProposalStatus.COMPLETED
                        if runtime_status == "completed"
                        else ProposalStatus.FAILED
                        if runtime_status == "failed"
                        else ProposalStatus.STOPPED
                        if runtime_status == "stopped"
                        else ProposalStatus.RUNNING
                    )
                    proposal.finished_at = session["finished_at"]
                    self._write_proposal(proposal)
                except ChatGoalError:
                    pass
            return session

        pid = session.get("pid")
        if pid and not _pid_alive(pid):
            session["status"] = ProposalStatus.FAILED
            session["loop_status"] = runtime_status or "process_exited"
            session["finished_at"] = now_ms()
            session["error"] = "background_loop_process_exited"
            self._write_session(conversation_id, session)
            proposal_id = session.get("proposal_id")
            if proposal_id:
                try:
                    proposal = self._read_proposal(str(proposal_id))
                    proposal.status = ProposalStatus.FAILED
                    proposal.finished_at = session["finished_at"]
                    proposal.error = session["error"]
                    self._write_proposal(proposal)
                except ChatGoalError:
                    pass
        return session


def _goal_document_from_proposal(value: dict[str, Any], raw_message: str) -> dict[str, Any]:
    """从 Master 提议提取 loop run 所需的 goal 文档。"""
    document = value.get("goal_document")
    if isinstance(document, dict):
        document = dict(document)
    else:
        ignored = {
            "proposal_id",
            "conversation_id",
            "raw_user_message",
            "raw_instruction",
            "instruction",
            "master_decision",
            "decision",
            "decision_reason",
            "confidence",
            "assumptions",
            "missing_information",
            "human_policy",
            "status",
            "source",
        }
        document = {key: value[key] for key in value if key not in ignored}
    goal = document.get("goal") if isinstance(document.get("goal"), dict) else {}
    goal = dict(goal)
    name = str(goal.get("name") or document.get("name") or raw_message[:60]).strip()
    name = name or "chat_research_goal"
    goal_id = str(goal.get("id") or document.get("goal_id") or "").strip()
    if not goal_id:
        goal_id = f"{safe_name(name)[:48]}-{new_id('g').split('_', 1)[-1]}"
    goal["id"] = goal_id
    goal["name"] = name
    document["goal"] = goal
    document["goal_id"] = goal_id
    workflow = document.get("workflow")
    if not isinstance(workflow, dict):
        workflow = {"type": "research"}
    workflow = dict(workflow)
    workflow["type"] = str(workflow.get("type") or "research")
    document["workflow"] = workflow
    objective = document.get("objective_brief")
    if not isinstance(objective, dict):
        objective = {}
    objective = dict(objective)
    objective.setdefault("primary_goal", raw_message)
    document["objective_brief"] = objective
    benchmarks = document.get("benchmarks")
    document["benchmarks"] = list(benchmarks) if isinstance(benchmarks, list) else []
    constraints = document.get("constraints")
    document["constraints"] = dict(constraints) if isinstance(constraints, dict) else {}
    document.setdefault("baselines", [])
    document.setdefault("outputs", {})
    infra = document.get("infra")
    if not isinstance(infra, dict):
        infra = {}
    infra = dict(infra)
    infra.setdefault("pipeline", "async")
    concurrency = infra.get("concurrency")
    if not isinstance(concurrency, dict):
        concurrency = {}
    concurrency = dict(concurrency)
    concurrency.setdefault("ideas", 1)
    concurrency.setdefault("implementations", 1)
    concurrency.setdefault("evaluations", 1)
    infra["concurrency"] = concurrency
    document["infra"] = infra
    return document


def _write_goal_document(path: Path, document: dict[str, Any]) -> None:
    """以 YAML（无 PyYAML 时退化为 JSON）原子写入 goal 文档。"""
    try:
        import yaml  # type: ignore

        text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    except Exception:  # pragma: no cover - PyYAML 是项目运行依赖
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)


def _validate_research_launch(goal_document: dict[str, Any]) -> None:
    """确认聊天生成的开放科研目标具备当前运行时所需 evaluator。"""
    workflow = goal_document.get("workflow")
    workflow_type = workflow.get("type") if isinstance(workflow, dict) else "research"
    if workflow_type != "research":
        return
    benchmarks = goal_document.get("benchmarks")
    if not isinstance(benchmarks, list) or not benchmarks:
        raise ChatGoalError(
            "开放科研 Loop 还缺少 benchmark/evaluator；请先和用户确认数据、指标和评测方式。"
        )
    first = benchmarks[0] if isinstance(benchmarks[0], dict) else {}
    adapter = first.get("adapter") if isinstance(first.get("adapter"), dict) else {}
    if adapter.get("type") not in {"command", "dummy"}:
        raise ChatGoalError(
            "当前 research Loop 需要 command 或已注册的 evaluator adapter；"
            "不能由 Master 自己估计正式分数。"
        )


def _pid_alive(value: Any) -> bool:
    """判断后台进程是否仍存在，不向进程发送终止信号。"""
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _string_list(value: Any) -> list[str]:
    """将 Master 的列表字段规范化为非空字符串列表。"""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique(values: list[str]) -> list[str]:
    """按原顺序去除重复说明。"""
    return list(dict.fromkeys(values))


__all__ = [
    "ChatGoalController",
    "ChatGoalError",
    "GoalProposal",
    "HumanPolicy",
    "MasterDecision",
    "ProposalStatus",
]
