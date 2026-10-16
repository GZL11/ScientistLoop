"""Terminal-Bench 单任务 Agent DAG。

这里仅包含状态转移，不执行 CLI、测试或官方 evaluator；这些能力通过
GraphExecutor 的 node runner 注入，从而与 SOTA search graph 解耦。
"""
from __future__ import annotations

from dataclasses import replace
import time
from typing import Any, Callable, Mapping, Sequence

from ...domain.graph import (
    AgentGraph,
    GraphContext,
    GraphOutput,
    GraphState,
    NodeInvocation,
    NodeResult,
)
from .contracts import TerminalTaskConfig, output_map


# 候选轮次校验来源。
#   proxy         VerifierAgent 生成 Proxy verifier，每轮 Proxy 反馈。
#   gt_primary    每轮都调用官方 GT 作为反馈（GT 次数不限）。
#   gt_final_only 运行期间不做任何候选评测，只在 FinalAudit 调用一次官方 GT。
#   gt_budget     Solver 可在运行期间主动申请官方 GT，总次数受 official_gt_budget
#                 限制；FinalAudit 单独执行，不占用预算。
#   dual_shadow   Proxy 为主，同时影子运行官方 GT 用于对比。
CANDIDATE_VERIFIER_MODES = frozenset(
    {"proxy", "gt_primary", "gt_final_only", "gt_budget", "dual_shadow"}
)
# 这些模式不启动 VerifierAgent，也没有 Proxy verifier。
GT_ONLY_MODES = frozenset({"gt_primary", "gt_final_only", "gt_budget"})


class TerminalTaskGraph(AgentGraph):
    """Solve/SurrogateVerify/Refine/FinalAudit 的可恢复状态机。"""

    name = "terminal_task"
    version = "1"

    def __init__(
        self,
        config: TerminalTaskConfig | None = None,
        *,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.config = (config or TerminalTaskConfig()).normalized()
        if self.config.candidate_verifier_mode not in CANDIDATE_VERIFIER_MODES:
            raise ValueError(
                "candidate_verifier_mode 必须是 proxy、gt_primary、gt_final_only、"
                "gt_budget 或 dual_shadow"
            )
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    def initialize(self, context: GraphContext) -> GraphState:
        return GraphState(
            graph_name=self.name,
            graph_version=self.version,
            phase="planning_and_solving",
            data={
                "run_id": context.run_id,
                "task_id": context.task_id,
                "started_at_ms": self._now_ms(),
                # Solver 的 benchmark 预算只累计 Solver turn 的实际运行时长。
                # Verifier、环境准备和 Controller 收尾均不计入该字段。
                "solver_elapsed_ms": 0,
                "refine_round": 0,
                "max_agent_wall_time_sec": self.config.max_agent_wall_time_sec,
                "max_proxy_refine_rounds": self.config.max_proxy_refine_rounds,
                "candidate_verifier_mode": self.config.candidate_verifier_mode,
                # 官方 GT 候选级评测预算（仅 gt_budget 模式使用）。FinalAudit
                # 不计入 official_gt_used。
                "official_gt_budget": self._official_gt_budget(),
                "official_gt_used": 0,
                "official_gt_requests": [],
                "last_gt_request": None,
                "solver_session_ref": None,
                "verifier_session_ref": None,
                "verifier_plan_ref": None,
                "verifier_bundle_ref": None,
                "verifier_bundle_hash": None,
                "verifier_compile_status": None,
                "verifier_self_test_status": None,
                "verifier_compile_attempts": [],
                "verifier_compile_repair_count": 0,
                "last_surrogate_report_ref": None,
                "current_candidate_artifact_ref": None,
                "last_valid_candidate_artifact_ref": None,
                # Compatibility alias for existing summaries/checkpoints.
                "last_surrogate_artifact_ref": None,
                "final_workspace_ref": None,
                "final_audit_ref": None,
            },
        )

    def ready(self, state: GraphState) -> Sequence[NodeInvocation]:
        data = state.data
        if state.terminal:
            return ()
        if state.phase == "planning_and_solving":
            invocations = [
                self._invocation(
                    "solver_turn_0",
                    "agent_turn",
                    {
                        "phase": "solve",
                        "round": 0,
                        "session_key": "terminal_solver",
                        "turn_timeout_sec": self._remaining_agent_time_sec(data),
                        **self._solver_evaluation_policy_payload(data),
                    },
                )
            ]
            if self.config.candidate_verifier_mode not in GT_ONLY_MODES:
                invocations.append(
                    self._invocation(
                        "verifier_plan_0",
                        "verifier_plan",
                        {"phase": "compile_plan", "session_key": "terminal_verifier"},
                    )
                )
            return tuple(invocations)
        if state.phase == "surrogate_verifying":
            round_no = int(data.get("refine_round", 0))
            request = data.get("last_gt_request")
            request = dict(request) if isinstance(request, Mapping) else {}
            return (
                self._invocation(
                    f"surrogate_verify_{round_no}",
                    "surrogate_verify",
                    {
                        "round": round_no,
                        "plan_ref": data.get("verifier_plan_ref"),
                        "solver_session_ref": data.get("solver_session_ref"),
                        # gt_budget: Solver 是否在刚结束的 turn 中申请了官方 GT，
                        # 以及还剩多少次额度。Runner 据此决定只导出还是导出后评测。
                        "gt_requested": bool(request.get("requested")),
                        "gt_request": request or None,
                        "official_gt_remaining": self._official_gt_remaining(data),
                    },
                ),
            )
        if state.phase == "refining":
            round_no = int(data.get("refine_round", 0))
            return (
                self._invocation(
                    f"solver_turn_{round_no}",
                    "agent_turn",
                    {
                        "phase": "refine",
                        "round": round_no,
                        "session_key": "terminal_solver",
                        "report_ref": data.get("last_surrogate_report_ref"),
                        "solver_error": data.get("last_solver_error"),
                        "turn_timeout_sec": self._remaining_agent_time_sec(data),
                        **self._solver_evaluation_policy_payload(data),
                    },
                ),
            )
        if state.phase == "freezing":
            return (
                self._invocation(
                    "freeze_workspace_0",
                    "freeze_workspace",
                    {"last_report_ref": data.get("last_surrogate_report_ref")},
                ),
            )
        if state.phase == "awaiting_final_audit":
            return (
                self._invocation(
                    "final_audit_0",
                    "final_audit",
                    {
                        "workspace_ref": data.get("final_workspace_ref"),
                        "candidate_artifact_ref": data.get(
                            "last_valid_candidate_artifact_ref"
                        )
                        or data.get("last_surrogate_artifact_ref"),
                        "proxy_report_ref": data.get("last_surrogate_report_ref"),
                        "candidate_verifier_mode": data.get("candidate_verifier_mode"),
                    },
                ),
            )
        raise RuntimeError(f"TerminalTaskGraph 未知 phase: {state.phase}")

    def apply(self, state: GraphState, result: NodeResult) -> GraphState:
        data = dict(state.data)
        # Solver 的非零退出是可修复的候选状态：保留错误上下文并恢复同一
        # session。Verifier 编译失败仍是控制器错误，不能把半成品送去审计。
        if result.status != "succeeded" and result.kind == "agent_turn":
            output = output_map(result.output)
            session_ref = output.get("session_ref")
            if session_ref:
                data["solver_session_ref"] = session_ref
            telemetry = output.get("telemetry")
            duration_ms = telemetry.get("duration_ms") if isinstance(telemetry, Mapping) else None
            if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
                data["last_solver_duration_ms"] = int(duration_ms)
                data["solver_elapsed_ms"] = int(data.get("solver_elapsed_ms") or 0) + int(duration_ms)
            data["last_solver_turn_status"] = "failed"
            data["last_solver_error"] = str(result.error or output.get("error") or "agent command failed")
            if output.get("termination_reason"):
                data["last_solver_termination_reason"] = output["termination_reason"]
            data["solver_turn_status"] = "failed"
            data["last_gt_request"] = self._gt_request_from_output(output)
            if output.get("termination_reason") == "infrastructure_error":
                data["failure"] = data["last_solver_error"]
                return state.with_updates(phase="failed", status="failed", data=data)
            return self._after_initial_parallel(state.with_updates(data=data), data)

        if result.status != "succeeded":
            output = output_map(result.output)
            if result.kind == "verifier_plan":
                data["verifier_session_ref"] = output.get("session_ref")
                data["verifier_compile_attempts"] = output.get(
                    "compile_attempts"
                ) or []
                data["verifier_compile_repair_count"] = max(
                    0, len(data["verifier_compile_attempts"]) - 1
                )
            return state.with_updates(
                phase="failed",
                status="failed",
                data={**data, "failure": result.error or "node failed"},
            )

        output = output_map(result.output)
        if result.kind == "agent_turn":
            session_ref = output.get("session_ref")
            if session_ref:
                data["solver_session_ref"] = session_ref
            telemetry = output.get("telemetry")
            if isinstance(telemetry, Mapping):
                duration_ms = telemetry.get("duration_ms")
                if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
                    data["last_solver_duration_ms"] = int(duration_ms)
                    data["solver_elapsed_ms"] = int(
                        data.get("solver_elapsed_ms") or 0
                    ) + int(duration_ms)
            # A minimal/test runner may omit telemetry. A timed-out Solver turn
            # is nevertheless known to have consumed the remaining budget.
            if output.get("turn_status") == "timed_out" and not isinstance(
                telemetry, Mapping
            ):
                data["solver_elapsed_ms"] = self.config.max_agent_wall_time_sec * 1000
            data["last_solver_turn_status"] = output.get("turn_status") or "completed"
            if output.get("termination_reason"):
                data["last_solver_termination_reason"] = output["termination_reason"]
            if output.get("phase") in {"solve", "refine"}:
                data["solver_turn_status"] = "succeeded"
            data["last_gt_request"] = self._gt_request_from_output(output)
            return self._after_initial_parallel(state.with_updates(data=data), data)

        if result.kind == "verifier_plan":
            if output.get("plan_ref"):
                data["verifier_plan_ref"] = output.get("plan_ref")
            if output.get("bundle_ref"):
                data["verifier_bundle_ref"] = output.get("bundle_ref")
                manifest = output.get("bundle_manifest")
                if isinstance(manifest, Mapping):
                    data["verifier_bundle_hash"] = manifest.get("verifier_bundle_hash")
                    static_check = manifest.get("static_check")
                    if isinstance(static_check, Mapping):
                        data["verifier_compile_status"] = static_check.get("status")
                    self_test = manifest.get("self_test")
                    if isinstance(self_test, Mapping):
                        data["verifier_self_test_status"] = self_test.get("status")
            data["verifier_session_ref"] = output.get("session_ref")
            data["verifier_compile_attempts"] = output.get("compile_attempts") or []
            data["verifier_compile_repair_count"] = int(
                output.get("compile_repair_count") or 0
            )
            data["verifier_plan_status"] = "succeeded"
            return self._after_initial_parallel(state.with_updates(data=data), data)

        if result.kind == "surrogate_verify":
            data["last_surrogate_report_ref"] = output.get("report_ref")
            data["last_surrogate_status"] = output.get("status")
            current_artifact = output.get("artifact_ref")
            data["current_candidate_artifact_ref"] = current_artifact
            if isinstance(current_artifact, Mapping):
                data["last_valid_candidate_artifact_ref"] = current_artifact
                # Keep the old field populated for old readers.
                data["last_surrogate_artifact_ref"] = current_artifact
            self._record_gt_request_outcome(data, output)
            status = output.get("status")
            if status == "verifier_error":
                data["failure"] = str(
                    output.get("error")
                    or f"surrogate verifier 执行失败，详见 {output.get('report_ref')}"
                )
                return state.with_updates(phase="failed", status="failed", data=data)
            if status == "exported":
                # 只导出候选快照、没有做任何候选级评测（gt_final_only，或
                # gt_budget 下 Solver 未申请/额度已用完）。Solver 已自然结束，
                # 直接冻结并进入唯一一次 FinalAudit。
                return state.with_updates(phase="freezing", data=data)
            if self._agent_budget_exhausted(data) or status == "passed":
                return state.with_updates(phase="freezing", data=data)
            if status == "repair_required":
                next_round = int(data.get("refine_round", 0)) + 1
                if self._can_proxy_refine(data, next_round):
                    data["refine_round"] = next_round
                    return state.with_updates(phase="refining", data=data)
                return state.with_updates(phase="freezing", data=data)
            return state.with_updates(
                phase="failed",
                status="failed",
                data={**data, "failure": f"unknown surrogate status: {status}"},
            )

        if result.kind == "freeze_workspace":
            data["final_workspace_ref"] = output.get("workspace_ref")
            return state.with_updates(phase="awaiting_final_audit", data=data)

        if result.kind == "final_audit":
            data["final_audit_ref"] = output.get("result_ref")
            status = "completed" if output.get("status") in {"passed", "completed"} else "failed"
            return state.with_updates(phase="completed" if status == "completed" else "failed", status=status, data=data)

        return state.with_updates(
            phase="failed",
            status="failed",
            data={**data, "failure": f"unknown node kind: {result.kind}"},
        )

    def output(self, state: GraphState) -> GraphOutput:
        return GraphOutput(
            status=state.status,
            payload=dict(state.data),
            error=state.data.get("failure"),
        )

    def _after_initial_parallel(self, state: GraphState, data: Mapping[str, Any]) -> GraphState:
        mode = self.config.candidate_verifier_mode
        if mode == "gt_final_only":
            # No candidate-level evaluation. The candidate is still exported
            # through SurrogateVerify (export only) so FinalAudit consumes the
            # container artifact snapshot instead of the host worktree, which
            # never contains the Solver's /app output.
            if data.get("solver_turn_status") in {"succeeded", "failed"}:
                return state.with_updates(phase="surrogate_verifying", data=dict(data))
            return state
        if mode in {"gt_primary", "gt_budget"}:
            request = data.get("last_gt_request")
            gt_requested = bool(
                isinstance(request, Mapping) and request.get("requested")
            )
            # A turn that died abnormally (SIGKILL / non-zero exit) after
            # writing a valid GT request must still have that evaluation
            # honored while budget remains: route to SurrogateVerify
            # (export + official GT) instead of diverting to a refine turn
            # that never reads the request file and silently drops the
            # request. Only when there is no honorable request do we refine.
            honor_request = gt_requested and self._official_gt_remaining(data) > 0
            if data.get("solver_turn_status") == "failed" and not honor_request:
                next_round = int(data.get("refine_round") or 0) + 1
                if self._can_proxy_refine(data, next_round):
                    updated = dict(data)
                    updated["refine_round"] = next_round
                    return state.with_updates(phase="refining", data=updated)
            if data.get("solver_turn_status") in {"succeeded", "failed"}:
                return state.with_updates(phase="surrogate_verifying", data=dict(data))
            return state
        if data.get("verifier_plan_status") != "succeeded":
            return state
        if data.get("solver_turn_status") == "failed":
            next_round = int(data.get("refine_round") or 0) + 1
            if self._can_proxy_refine(data, next_round):
                updated = dict(data)
                updated["refine_round"] = next_round
                return state.with_updates(phase="refining", data=updated)
            # A timeout/non-zero exit may still have exported declared
            # artifacts from FMJob. Give SurrogateVerify one chance to inspect
            # that candidate before freezing; do not silently discard it.
            if data.get("verifier_plan_status") == "succeeded":
                return state.with_updates(phase="surrogate_verifying", data=dict(data))
            return state.with_updates(phase="freezing", data=dict(data))
        if data.get("solver_turn_status") != "succeeded":
            return state
        return state.with_updates(phase="surrogate_verifying", data=dict(data))

    def _agent_budget_exhausted(self, data: Mapping[str, Any]) -> bool:
        elapsed_sec = max(0, float(data.get("solver_elapsed_ms") or 0) / 1000)
        return elapsed_sec >= self.config.max_agent_wall_time_sec

    def _can_proxy_refine(self, data: Mapping[str, Any], next_round: int) -> bool:
        """Check both the task wall-clock budget and the Proxy refine cap."""

        return (
            int(next_round) <= self.config.max_proxy_refine_rounds
            and not self._agent_budget_exhausted(data)
        )

    def _remaining_agent_time_sec(self, data: Mapping[str, Any]) -> float:
        elapsed_sec = max(0.0, float(data.get("solver_elapsed_ms") or 0) / 1000)
        return max(0.1, self.config.max_agent_wall_time_sec - elapsed_sec)

    # ------------------------------------------------------------------
    # 官方 GT 预算
    # ------------------------------------------------------------------

    def _official_gt_budget(self) -> int:
        if self.config.candidate_verifier_mode == "gt_budget":
            return int(self.config.official_gt_budget)
        return 0

    def _official_gt_remaining(self, data: Mapping[str, Any]) -> int:
        budget = int(data.get("official_gt_budget") or 0)
        used = int(data.get("official_gt_used") or 0)
        return max(0, budget - used)

    @staticmethod
    def _gt_request_from_output(output: Mapping[str, Any]) -> dict[str, Any] | None:
        """Solver turn 结束时是否申请官方 GT（由 SolverTurnRunner 从结果 JSON 提取）。"""

        request = output.get("gt_request")
        if not isinstance(request, Mapping) or not request.get("requested"):
            return None
        return {
            "requested": True,
            "reason": str(request.get("reason") or ""),
        }

    @staticmethod
    def _record_gt_request_outcome(data: dict[str, Any], output: Mapping[str, Any]) -> None:
        """记录本轮是否消耗了一次官方 GT 额度，并把申请日志写进状态。"""

        request = data.get("last_gt_request")
        consumed = bool(output.get("gt_consumed"))
        if consumed:
            data["official_gt_used"] = int(data.get("official_gt_used") or 0) + 1
        if isinstance(request, Mapping) or consumed:
            log = list(data.get("official_gt_requests") or [])
            log.append(
                {
                    "round": int(data.get("refine_round") or 0),
                    "requested": bool(isinstance(request, Mapping) and request.get("requested")),
                    "reason": str((request or {}).get("reason") or "") if isinstance(request, Mapping) else "",
                    "granted": consumed,
                    "status": output.get("status"),
                    "report_ref": output.get("report_ref"),
                }
            )
            data["official_gt_requests"] = log
        data["last_gt_request"] = None

    def _solver_evaluation_policy_payload(self, data: Mapping[str, Any]) -> dict[str, Any]:
        mode = self.config.candidate_verifier_mode
        total_sec = int(self.config.max_agent_wall_time_sec)
        remaining_sec = int(self._remaining_agent_time_sec(data))
        time_note = (
            f"时间预算：本任务给你的 Solver 总时长为 {total_sec} 秒"
            f"（约 {total_sec // 3600} 小时），本轮开始时预计剩余约 {remaining_sec} 秒；"
            "到点后当前 turn 会被系统终止。请注意：官方 GT 评测与最终 FinalAudit 的"
            "运行时间都不计入该预算，申请 GT 不会挤占你的解题时间。"
        )
        if mode == "gt_final_only":
            return {
                "gt_evaluation_policy": "final_only_once",
                "official_gt_evaluations_allowed": 1,
                "evaluation_policy_note": (
                    time_note + "\n"
                    "本实验只允许一次官方 GT 评测：仅在 Solver 结束后的 FinalAudit 调用；"
                    "运行期间不会提供 GT 分数或 GT 失败反馈。请在最终提交前自行完成公开检查，"
                    "不要假设可以请求或重试官方评测。"
                ),
            }
        if mode == "gt_budget":
            budget = int(data.get("official_gt_budget") or 0)
            used = int(data.get("official_gt_used") or 0)
            remaining = max(0, budget - used)
            return {
                "gt_evaluation_policy": "on_request_budget",
                "official_gt_evaluations_allowed": budget,
                "official_gt_evaluations_used": used,
                "official_gt_evaluations_remaining": remaining,
                "evaluation_policy_note": (
                    time_note + "\n"
                    f"本实验允许你在运行期间主动申请官方 GT 评测：总额度 {budget} 次，"
                    f"已用 {used} 次，剩余 {remaining} 次。运行期间没有 Proxy 反馈，"
                    "官方 GT 是唯一的外部评测信号，请慎重选择申请时机。"
                    "Solver 结束后系统还会单独执行一次 FinalAudit 官方 GT，它不占用该额度，"
                    "结果也不会反馈给你。官方 GT 只能由系统在你的 turn 结束后执行，"
                    "你不得寻找或调用官方隐藏 evaluator。申请方式：先把任务声明的产物"
                    "完整写到规定的绝对路径，再在公开上下文 `gt_request_file` 指向的文件中"
                    '写入 JSON {"request_official_gt": true, "reason": "<为什么现在需要官方评测>"}'
                    "（只写这两个字段，不要加 status 等其他字段），然后自然退出本 turn；系统会对当前产物快照运行一次官方 GT，并在下一轮把"
                    "完整 stdout/stderr/CTRF 反馈给你。不申请则直接退出，系统会冻结当前产物"
                    "并进入 FinalAudit。剩余额度为 0 时的申请会被忽略并直接进入 FinalAudit。"
                ),
            }
        return {}

    @staticmethod
    def _invocation(invocation_id: str, kind: str, payload: Mapping[str, Any]) -> NodeInvocation:
        return NodeInvocation(
            invocation_id=invocation_id,
            kind=kind,
            payload=dict(payload),
            idempotency_key=invocation_id,
        )


__all__ = ["CANDIDATE_VERIFIER_MODES", "GT_ONLY_MODES", "TerminalTaskGraph"]
