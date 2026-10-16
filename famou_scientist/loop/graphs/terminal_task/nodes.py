"""TerminalTaskGraph 的可注入节点 runner。"""
from __future__ import annotations

from dataclasses import dataclass, replace
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import re
import shlex
from typing import Any, Callable, Mapping, Protocol, Sequence

from ...domain.graph import GraphContext, NodeInvocation, NodeResult
from ...execution.agent_turn import AgentTurnRequest, CommandAgentTurn
from ...execution.sandbox import ExecutionSandbox
from ...execution.workspace import AgentWorkspace
from ...facilities.benchmark import BenchmarkFacility
from ...facilities.contracts import ArtifactRef, CandidateRef, EvaluationRequest
from ...facilities.evaluation import EvaluationFacility
from ...utils import atomic_write_json, read_json
from .verifier import VerifierBundleStore, VerifierPlanStore, validate_verifier_source


class RubricExecutor(Protocol):
    """在公开隔离环境中执行冻结 rubric 的扩展点。"""

    def execute(
        self,
        plan: Mapping[str, Any],
        artifact: ArtifactRef,
        *,
        round_no: int,
    ) -> Mapping[str, Any]: ...


class NoopRubricExecutor:
    """只依赖 BenchmarkFacility 公开检查的默认实现。"""

    def execute(self, plan, artifact, *, round_no):
        del plan, artifact, round_no
        return {"valid": True, "checks": []}


class DeterministicRubricExecutor:
    """执行不会启动任意命令的安全 rubric 子集。"""

    def execute(self, plan, artifact, *, round_no):
        del round_no
        root = Path(artifact.storage_path).resolve()
        checks: list[dict[str, Any]] = []
        deterministic_failed = False
        for rubric in plan.get("rubrics", []):
            if not isinstance(rubric, Mapping):
                continue
            rubric_id = str(rubric.get("id") or "")
            checker = rubric.get("checker")
            checker = checker if isinstance(checker, Mapping) else {}
            kind = str(checker.get("kind") or "")
            if kind == "file":
                value = checker.get("path") or checker.get("spec")
                try:
                    target = _safe_artifact_path(root, str(value or ""))
                    passed = target.exists() and not target.is_symlink()
                    details = {"path": str(target.relative_to(root)), "exists": passed}
                except ValueError as exc:
                    passed = False
                    details = {"error": str(exc)}
                deterministic_failed = deterministic_failed or not passed
                checks.append(
                    {
                        "rubric_id": rubric_id,
                        "status": "passed" if passed else "failed",
                        "details": details,
                    }
                )
            else:
                # Agent 生成的 command 不能直接在宿主机执行。Terminal-Bench
                # Adapter 可通过公开 BenchmarkFacility 执行可信命令；其余项交给
                # read-only VerifierAgent 基于证据判断。
                checks.append(
                    {
                        "rubric_id": rubric_id,
                        "status": "unknown",
                        "details": {"checker_kind": kind, "reason": "requires_verifier_diagnosis"},
                    }
                )
        return {"valid": not deterministic_failed, "checks": checks}


@dataclass
class SolverTurnRunner:
    adapter: CommandAgentTurn
    workspace: AgentWorkspace
    sandbox: ExecutionSandbox
    instruction: str
    resource_limits: Mapping[str, Any] | None = None

    def __call__(self, invocation: NodeInvocation, context: GraphContext) -> NodeResult:
        phase = str(invocation.payload.get("phase") or "solve")
        report_ref = invocation.payload.get("report_ref")
        public_context: dict[str, Any] = {
            "run_id": context.run_id,
            "task_id": context.task_id,
            "round": int(invocation.payload.get("round") or 0),
        }
        if invocation.payload.get("gt_evaluation_policy"):
            public_context["evaluation_policy"] = invocation.payload[
                "gt_evaluation_policy"
            ]
            public_context["official_gt_evaluations_allowed"] = int(
                invocation.payload.get("official_gt_evaluations_allowed") or 0
            )
            public_context["evaluation_policy_note"] = str(
                invocation.payload.get("evaluation_policy_note") or ""
            )
            if invocation.payload["gt_evaluation_policy"] == "on_request_budget":
                # gt_budget: 告诉 Solver 剩余额度以及申请文件的位置。该文件就是
                # CLI wrapper 在 natural_exit 模式下回收的结构化结果 JSON。
                public_context["official_gt_evaluations_used"] = int(
                    invocation.payload.get("official_gt_evaluations_used") or 0
                )
                public_context["official_gt_evaluations_remaining"] = int(
                    invocation.payload.get("official_gt_evaluations_remaining") or 0
                )
                public_context["gt_request_file"] = str(
                    self.workspace.worktree / GT_REQUEST_RESULT_FILENAME
                )
        if self.resource_limits:
            public_context["resource_limits"] = dict(self.resource_limits)
        if report_ref:
            report = read_json(_resolve_run_ref(context.run_dir, str(report_ref)))
            if isinstance(report, dict):
                public_context["surrogate_report"] = report
                public_context["surrogate_report_path"] = report.get(
                    "agent_workspace_path"
                )
        solver_error = invocation.payload.get("solver_error")
        if solver_error:
            public_context["solver_error"] = str(solver_error)
        result = self.adapter.run(
            AgentTurnRequest(
                role="terminal_solver",
                phase=phase,
                session_key=str(invocation.payload.get("session_key") or "terminal_solver"),
                instruction=self.instruction,
                workspace=self.workspace,
                sandbox=self.sandbox,
                context=public_context,
                completion_mode="natural_exit",
                timeout_sec=float(invocation.payload["turn_timeout_sec"])
                if invocation.payload.get("turn_timeout_sec") is not None
                else None,
            )
        )
        returncode = (
            result.failure.get("returncode")
            or result.failure.get("return_code")
            or result.telemetry.get("returncode")
            or result.output.get("returncode")
        )
        duration_ms = result.telemetry.get("duration_ms")
        timeout_sec = float(invocation.payload.get("turn_timeout_sec") or 0)
        timed_out = (
            result.status != "succeeded"
            and (
                result.failure.get("timed_out") is True
                or result.failure.get("error_code") in {"timeout", "timed_out"}
                or (
                    returncode in {-15, 143}
                    and isinstance(duration_ms, (int, float))
                    and timeout_sec > 0
                    and float(duration_ms) >= timeout_sec * 1000 * 0.9
                )
            )
        )
        return NodeResult(
            invocation_id=invocation.invocation_id,
            kind=invocation.kind,
            # Terminal Solver 的 DDL 表示本轮受控结束。已有 workspace 仍需经过
            # SurrogateVerify、冻结和 FinalAudit；其他运行时错误才终止 Graph。
            status="succeeded" if timed_out else result.status,
            output={
                "phase": phase,
                "session_ref": result.session_ref,
                "turn_status": "timed_out" if timed_out else "completed",
                "termination_reason": (
                    str(result.failure.get("error_code") or "agent_timeout")
                    if timed_out
                    else str(result.failure.get("error_code") or "") or None
                ),
                "telemetry": dict(result.telemetry),
                # gt_budget: Solver 在结果 JSON 中声明 request_official_gt 即视为
                # 申请一次官方 GT；Graph 负责核对剩余额度。
                "gt_request": _gt_request_from_solver_output(result.output),
            },
            error=None if timed_out else result.error,
        )


# Solver 在 worktree 中写入的结构化结果文件名；与 cli_agent_wrapper 的
# terminal_solver result_filename 保持一致。
GT_REQUEST_RESULT_FILENAME = "famou_terminal_solver_result.json"


def _gt_request_from_solver_output(output: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(output, Mapping):
        return None
    flag = output.get("request_official_gt")
    if isinstance(flag, str):
        requested = flag.strip().lower() in {"true", "yes", "1"}
    else:
        requested = bool(flag)
    if not requested:
        return None
    return {"requested": True, "reason": str(output.get("reason") or "")}

@dataclass
class VerifierPlanRunner:
    adapter: CommandAgentTurn
    workspace: AgentWorkspace
    sandbox: ExecutionSandbox
    instruction: str
    task_input_hash: str
    # Public task package used for the Controller-runtime probe before freeze.
    task_root: Path | None = None
    # VerifierAgent bundle 编译/静态检查的独立修复上限；默认最多五次。
    max_compile_repairs: int = 5

    def __call__(self, invocation: NodeInvocation, context: GraphContext) -> NodeResult:
        session_key = str(invocation.payload.get("session_key") or "terminal_verifier")
        compile_errors: list[str] = []
        attempts: list[dict[str, Any]] = []
        result = None
        source_root = self.workspace.worktree
        bundle_store = VerifierBundleStore(context.run_dir)
        bundle_ref = None
        bundle_manifest = None
        for attempt_no in range(self.max_compile_repairs + 1):
            phase = "compile_plan" if attempt_no == 0 else "repair_compile"
            turn_context: dict[str, Any] = {
                "run_id": context.run_id,
                "task_id": context.task_id,
                "task_input_hash": self.task_input_hash,
                "compile_attempt": attempt_no + 1,
            }
            if compile_errors:
                turn_context["compile_errors"] = list(compile_errors)
            result = self.adapter.run(
                AgentTurnRequest(
                    role="terminal_verifier",
                    phase=phase,
                    session_key=session_key,
                    instruction=self.instruction,
                    workspace=self.workspace,
                    sandbox=self.sandbox,
                    context=turn_context,
                    # Compiler Agent 的主要产物是 worktree 中的源码和测试；自然退出时
                    # 不要求它额外拼接一个大 JSON。旧 plan JSON 仍作为过渡回退。
                    completion_mode="natural_exit",
                )
            )
            compile_errors = []
            if (source_root / "verifier.py").is_file():
                try:
                    source_report = validate_verifier_source(source_root)
                    if source_report["status"] != "passed":
                        compile_errors.append(
                            "VerifierAgent verifier 静态检查失败: "
                            + "; ".join(source_report["errors"])
                        )
                    self_test_status = str(
                        source_report.get("self_test", {}).get("status") or ""
                    )
                    if (
                        source_report["status"] == "passed"
                        and self_test_status not in {"agent_reported_passed", "partial"}
                    ):
                        compile_errors.append(
                            "VerifierAgent 自测记录无效或未完成: "
                            f"status={self_test_status or 'missing'}"
                        )
                    runtime_check: dict[str, Any] | None = None
                    if not compile_errors:
                        runtime_check = self._controller_runtime_probe(
                            source_root,
                            self.task_root,
                        )
                        if runtime_check["status"] == "failed":
                            compile_errors.append(
                                "Controller runtime 自测失败: "
                                + str(runtime_check.get("error") or "unknown error")
                            )
                    if compile_errors:
                        # Do not freeze a bundle that the actual Controller
                        # runtime cannot import/decode. The next iteration
                        # resumes VerifierAgent with this concrete error.
                        bundle_ref = None
                        bundle_manifest = None
                    else:
                        bundle_ref, bundle_manifest = bundle_store.freeze_source(
                            source_root,
                            task_id=str(context.task_id or "terminal-task"),
                            task_input_hash=self.task_input_hash,
                            verifier_agent_session_ref=result.session_ref,
                            controller_runtime_check=runtime_check,
                        )
                except Exception as exc:  # noqa: BLE001 - preserve validation evidence
                    compile_errors.append(
                        f"VerifierAgent verifier bundle 校验失败: {type(exc).__name__}: {exc}"
                    )
            elif not (isinstance(result.output, Mapping) and "rubrics" in result.output):
                compile_errors.append("VerifierAgent 未生成 verifier.py")
            attempts.append(
                {
                    "attempt": attempt_no + 1,
                    "phase": phase,
                    "session_ref": result.session_ref,
                    "status": "succeeded" if not compile_errors else "failed",
                    "errors": list(compile_errors),
                }
            )
            if not compile_errors:
                break
        assert result is not None
        if compile_errors:
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "failed",
                output={"compile_attempts": attempts, "session_ref": result.session_ref},
                error="; ".join(compile_errors),
            )
        # CLI wrappers may report a non-zero protocol result (for example an
        # empty/legacy result JSON) even though the compiler wrote a complete,
        # statically checked bundle. The bundle is the compiler's authoritative
        # output, so allow that case to proceed to candidate-level verification.
        if result.status != "succeeded" and bundle_ref is None:
            return NodeResult(
                invocation.invocation_id,
                invocation.kind,
                "failed",
                error=result.error or "VerifierAgent 未生成 verifier bundle",
            )
        # 兼容尚未切换 prompt 的调用和已有测试：仅当 Agent 没有源码产物时才
        # 接受旧的 JSON plan，后续每轮仍走原有 rubric executor。
        plan_ref = None
        if bundle_ref is None:
            if not isinstance(result.output, Mapping) or "rubrics" not in result.output:
                return NodeResult(
                    invocation.invocation_id,
                    invocation.kind,
                    "failed",
                    error="VerifierAgent 未生成 verifier.py，也未返回兼容 VerifierPlan",
                )
            plan_path = VerifierPlanStore(context.run_dir).freeze(
                result.output,
                task_input_hash=self.task_input_hash,
            )
            plan_ref = str(plan_path.relative_to(context.run_dir))
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "succeeded",
            {
                "plan_ref": plan_ref,
                "bundle_ref": (
                    str(bundle_ref.relative_to(context.run_dir))
                    if bundle_ref is not None
                    else None
                ),
                "bundle_manifest": bundle_manifest,
                "session_ref": result.session_ref,
                "compile_attempts": attempts,
                "compile_repair_count": max(0, len(attempts) - 1),
            },
        )

    @staticmethod
    def _controller_runtime_probe(
        source_root: Path,
        task_root: Path | None,
    ) -> dict[str, Any]:
        """Exercise generated DICOM helpers in the Controller's Python runtime.

        VerifierAgent self-tests run in its own worker image.  This probe runs
        before freezing, in the process that later executes the frozen bundle,
        so dependency/codec failures cannot be hidden by an environment
        mismatch.  Tasks without a DICOM study are explicitly skipped.
        """

        source_root = Path(source_root).expanduser().resolve()
        if task_root is None:
            return {"status": "skipped", "reason": "task_root_not_configured"}
        public_root = _resolve_verifier_task_root(Path(task_root))
        study_dir = public_root / "study"
        helper_path = source_root / "verifier_study.py"
        if not helper_path.is_file() or not study_dir.is_dir():
            return {
                "status": "skipped",
                "reason": "no verifier_study.py or public study directory",
            }

        old_path = list(sys.path)
        old_helper = sys.modules.pop("verifier_study", None)
        source_module_cache: dict[str, Any] = {}
        for name, loaded in list(sys.modules.items()):
            loaded_file = getattr(loaded, "__file__", None)
            if not loaded_file:
                continue
            try:
                if Path(loaded_file).expanduser().resolve().is_relative_to(
                    source_root
                ):
                    source_module_cache[name] = loaded
                    sys.modules.pop(name, None)
            except (OSError, RuntimeError, TypeError):
                continue
        try:
            # Resolve local imports from the source worktree, then restore the
            # Controller interpreter's import state below. Load the complete
            # verifier because this must match the import path used by Proxy;
            # static checks have already run before reaching this point.
            sys.path.insert(0, str(source_root))
            module_name = f"famou_controller_probe_{abs(hash(str(source_root)))}"
            spec = importlib.util.spec_from_file_location(
                module_name,
                source_root / "verifier.py",
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("无法加载 verifier.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            helper = getattr(module, "vs", None)
            if helper is None:
                helper_spec = importlib.util.spec_from_file_location(
                    f"{module_name}_study",
                    helper_path,
                )
                if helper_spec is None or helper_spec.loader is None:
                    raise RuntimeError("无法加载 verifier_study.py")
                helper = importlib.util.module_from_spec(helper_spec)
                helper_spec.loader.exec_module(helper)
            study_cls = getattr(helper, "Study", None)
            if not callable(study_cls):
                return {"status": "skipped", "reason": "Study helper not exposed"}
            study = study_cls(study_dir)
            series = getattr(study, "diagnostic", None)
            if callable(series):
                series = series()
            series = list(series or [])
            decoded = 0
            for item in series:
                instances = list(getattr(item, "instances", []) or [])
                pixels = getattr(item, "pixels", None)
                if instances and callable(pixels):
                    pixels(instances[0])
                    decoded += 1
            return {
                "status": "passed",
                "study_root": str(study_dir),
                "diagnostic_series": len(series),
                "decoded_instances": decoded,
                "numpy_version": _module_version("numpy"),
                "pydicom_version": _module_version("pydicom"),
            }
        except Exception as exc:  # noqa: BLE001 - report exact runtime failure
            return {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "numpy_version": _module_version("numpy"),
                "pydicom_version": _module_version("pydicom"),
            }
        finally:
            sys.path[:] = old_path
            for name, loaded in list(sys.modules.items()):
                loaded_file = getattr(loaded, "__file__", None)
                if not loaded_file:
                    continue
                try:
                    if Path(loaded_file).expanduser().resolve().is_relative_to(
                        source_root
                    ):
                        sys.modules.pop(name, None)
                except (OSError, RuntimeError, TypeError):
                    continue
            sys.modules.update(source_module_cache)
            if old_helper is not None:
                sys.modules["verifier_study"] = old_helper


@dataclass
class SurrogateVerifyRunner:
    benchmark: BenchmarkFacility
    workspace: AgentWorkspace
    task_root: Path | None = None
    rubric_executor: RubricExecutor = DeterministicRubricExecutor()
    diagnose: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    verifier_mode: str = "proxy"

    def __call__(self, invocation: NodeInvocation, context: GraphContext) -> NodeResult:
        round_no = int(invocation.payload.get("round") or 0)
        mode = str(self.verifier_mode or "proxy").strip().lower()
        candidate = CandidateRef(
            candidate_id=f"{context.run_id}:surrogate:{round_no}",
            code_path=str(self.workspace.worktree),
            output_path=str(self.workspace.outputs),
            evidence_path=str(self.workspace.logs),
            producer="terminal_solver",
            metadata={"round": round_no},
        )
        try:
            preflight = self.benchmark.preflight(
                candidate,
                context={"run_id": context.run_id, "round": round_no, "surrogate": True},
            )
            run = self.benchmark.run(
                candidate,
                context={"run_id": context.run_id, "round": round_no, "surrogate": True},
            )
        except Exception as exc:  # noqa: BLE001
            report = self._report(
                round_no,
                "repair_required",
                [{
                    "id": "artifact_export",
                    "status": "failed",
                    "details": {
                        "error": str(exc),
                        "candidate_output_path": str(self.workspace.outputs),
                        "message": "未能从 Solver 容器导出 task.toml 声明的产物，请按声明的绝对路径写出文件后重试。",
                    },
                }],
                artifact=None,
                repair_instructions=[
                    "检查 task.toml 中声明的每一个绝对产物路径，确保 Solver 容器退出前文件已写入对应位置。",
                    f"当前 Solver worktree 输出目录为 {self.workspace.outputs}；不要只把文件留在其他目录。",
                ],
                verifier_mode=mode,
            )
            if mode == "gt_final_only":
                # 没有候选级反馈的实验：导出失败也不给 Solver 修复机会，直接
                # 冻结并让 FinalAudit 如实报告缺失产物。
                report["status"] = "exported"
            return self._save_report(invocation, context, report)
        if not run.valid or run.artifact_ref is None:
            report = self._report(
                round_no,
                "repair_required",
                [{"id": "benchmark_run", "status": "failed", "details": run.to_dict()}],
                artifact=None,
                verifier_mode=mode,
            )
            if mode == "gt_final_only":
                report["status"] = "exported"
            return self._save_report(invocation, context, report)

        export_check = {
            "id": "artifact_export",
            "status": "passed",
            "details": {"message": "已导出 task.toml 声明的产物快照。"},
        }
        if mode == "gt_final_only":
            # 只导出候选快照供 FinalAudit 使用，不做任何候选级评测。这样
            # FinalAudit 评的是容器内 /app 的真实产物，而不是宿主机 worktree。
            report = self._report(
                round_no,
                "exported",
                [export_check],
                artifact=run.artifact_ref,
                verifier_mode=mode,
            )
            return self._save_report(invocation, context, report)
        if mode == "gt_budget":
            requested = bool(invocation.payload.get("gt_requested"))
            remaining = int(invocation.payload.get("official_gt_remaining") or 0)
            if not requested or remaining <= 0:
                checks = [export_check]
                if requested and remaining <= 0:
                    checks.append(
                        {
                            "id": "official_gt_request",
                            "status": "skipped",
                            "details": {
                                "message": "官方 GT 额度已用完，本次申请被忽略；直接进入 FinalAudit。",
                                "official_gt_remaining": 0,
                            },
                        }
                    )
                report = self._report(
                    round_no,
                    "exported",
                    checks,
                    artifact=run.artifact_ref,
                    verifier_mode=mode,
                )
                return self._save_report(invocation, context, report)
            # 申请有效且仍有额度：与 gt_primary 共用官方 GT 反馈路径。

        if mode in {"gt_primary", "gt_budget"}:
            try:
                gt = self.benchmark.run_gt_evaluation(run.artifact_ref, round_no=round_no)
            except Exception as exc:  # noqa: BLE001
                gt = {"status": "verifier_error", "verifier": "tbs_gt", "error": str(exc)}
            status = str(gt.get("status") or "verifier_error")
            report = self._report(
                round_no,
                status,
                [{"id": "tbs_gt", "status": "passed" if status == "passed" else status, "details": gt}],
                artifact=run.artifact_ref,
                repair_instructions=(
                    []
                    if status == "passed"
                    else [
                        "读取 gt_evaluation 中的完整 stdout、stderr 和 CTRF 失败信息，逐项修正后重新提交。"
                    ]
                ),
                error=gt.get("error") if status == "verifier_error" else None,
                verifier_mode=mode,
                gt_evaluation=gt,
            )
            if mode == "gt_budget":
                # 一次真实执行的官方 GT 才消耗额度；verifier_error 属于系统故障，
                # 不算 Solver 用掉了机会。
                report["official_gt_consumed"] = status != "verifier_error"
                report["official_gt_request"] = invocation.payload.get("gt_request")
            return self._save_report(invocation, context, report)

        gt_shadow = None
        if mode == "dual_shadow":
            try:
                gt_shadow = self.benchmark.run_gt_evaluation(run.artifact_ref, round_no=round_no)
            except Exception as exc:  # noqa: BLE001
                gt_shadow = {"status": "verifier_error", "verifier": "tbs_gt", "error": str(exc)}

        validation = self.benchmark.validate_artifact(run.artifact_ref)
        public_evaluation = self.benchmark.run_public_evaluation(run.artifact_ref)
        public_view = self.benchmark.agent_view(public_evaluation, source="surrogate")
        bundle_root = context.run_dir / "controller" / "verifier" / "bundle"
        if (bundle_root / "verifier.py").is_file():
            generated = self._execute_frozen_verifier(
                bundle_root,
                run.artifact_ref,
                round_no=round_no,
                task_root=_resolve_verifier_task_root(
                    self.task_root or self.workspace.worktree
                ),
                output_dir=context.run_dir / "controller" / "surrogate" / f"round_{round_no}" / "evidence",
            )
            generated_status = _generated_report_status(generated)
            checks = [
                {"id": "preflight", "status": _check_status(preflight), "details": preflight},
                {"id": "artifact_validation", "status": _check_status(validation), "details": validation},
                {"id": "public_evaluation", "status": _check_status(public_view), "details": public_view},
                *[
                    {
                        "id": str(item.get("id") or f"generated_{index}"),
                        "status": _generated_check_status(item),
                        "details": dict(item),
                    }
                    for index, item in enumerate(generated.get("checks", []))
                    if isinstance(item, Mapping)
                ],
            ]
            if generated_status == "verifier_error":
                report_status = "verifier_error"
            else:
                # The generated verifier is authoritative about coverage. An
                # ``unknown`` check is allowed when the verifier itself still
                # reports ``passed`` (for example an explicitly uncovered
                # hidden-GT comparison alongside passing public value proxies).
                # Only concrete failed checks, or failed controller preflight /
                # artifact/public checks, require candidate repair.
                base_checks = checks[:3]
                generated_checks = checks[3:]
                concrete_generated_failure = any(
                    item.get("status") == "failed" for item in generated_checks
                )
                report_status = (
                    "passed"
                    if generated_status == "passed"
                    and all(item.get("status") == "passed" for item in base_checks)
                    and not concrete_generated_failure
                    else "repair_required"
                )
            report = self._report(
                round_no,
                report_status,
                checks,
                artifact=run.artifact_ref,
                error=generated.get("error") if report_status == "verifier_error" else None,
                verifier_mode=mode,
                gt_evaluation=gt_shadow,
            )
            return self._save_report(invocation, context, report)
        plan = VerifierPlanStore(context.run_dir).load()
        rubric_result = dict(
            self.rubric_executor.execute(plan, run.artifact_ref, round_no=round_no)
        )
        public_preflight = self._safe_agent_view(preflight, source="preflight")
        public_validation = self._safe_agent_view(
            validation,
            source="artifact_validation",
        )
        diagnosis_input = {
            "round": round_no,
            "artifact_ref": run.artifact_ref.to_dict(),
            "preflight": public_preflight,
            "validation": public_validation,
            "public_evaluation": public_view,
            "rubric_result": rubric_result,
        }
        diagnosis = dict(self.diagnose(diagnosis_input)) if self.diagnose else {}
        if diagnosis.get("status") == "verifier_error":
            raise RuntimeError(
                str(diagnosis.get("error") or "VerifierAgent diagnose failed")
            )
        diagnosis_checks = self._complete_diagnosis_checks(
            plan,
            diagnosis,
            rubric_result,
        )
        checks = [
            {"id": "preflight", "status": _check_status(preflight), "details": preflight},
            {"id": "artifact_validation", "status": _check_status(validation), "details": validation},
            {"id": "public_evaluation", "status": _check_status(public_view), "details": public_view},
            {"id": "rubric", "status": _check_status(rubric_result), "details": rubric_result},
        ]
        if diagnosis:
            checks.extend(diagnosis_checks)
        diagnosis_passed = not diagnosis or diagnosis.get("status") == "passed"
        passed = diagnosis_passed and all(
            item.get("status") == "passed" for item in checks
        )
        report = self._report(
            round_no,
            "passed" if passed else "repair_required",
            checks,
            artifact=run.artifact_ref,
            repair_instructions=diagnosis.get("repair_instructions") or [],
            verifier_mode=mode,
            gt_evaluation=gt_shadow,
        )
        agent_report = {
            "schema_version": 1,
            "round": round_no,
            "status": report["status"],
            "checks": [
                {"id": "preflight", "status": _check_status(public_preflight), "details": public_preflight},
                {"id": "artifact_validation", "status": _check_status(public_validation), "details": public_validation},
                {"id": "public_evaluation", "status": _check_status(public_view), "details": public_view},
                {"id": "rubric", "status": _check_status(rubric_result), "details": rubric_result},
                *diagnosis_checks,
            ],
            "repair_instructions": diagnosis.get("repair_instructions") or [],
        }
        return self._save_report(invocation, context, report, agent_report=agent_report)

    @staticmethod
    def _execute_frozen_verifier(
        bundle_root: Path,
        artifact: ArtifactRef,
        *,
        round_no: int,
        task_root: Path,
        output_dir: Path,
    ) -> dict[str, Any]:
        """加载并执行已静态检查、已冻结的 verifier.py。"""

        output_dir.mkdir(parents=True, exist_ok=True)
        verifier_path = bundle_root / "verifier.py"
        try:
            # ArtifactRef points at an immutable, hash-addressed snapshot.
            # Importing candidate Python code may create __pycache__, and a
            # generated verifier may write temporary files.  Run against a
            # disposable copy so those side effects cannot invalidate the
            # snapshot that FinalAudit will consume.
            source_root = Path(artifact.storage_path).resolve()
            with tempfile.TemporaryDirectory(prefix="famou-verifier-artifact-") as temp_dir:
                evaluation_root = Path(temp_dir) / "payload"
                if source_root.is_dir():
                    shutil.copytree(source_root, evaluation_root, symlinks=False)
                elif source_root.is_file():
                    shutil.copy2(source_root, evaluation_root)
                else:
                    raise FileNotFoundError(f"artifact 不存在: {source_root}")
                evaluation_artifact = replace(
                    artifact,
                    storage_path=str(evaluation_root),
                )
                # The Solver sees the image's runtime ``/app`` view.  Do not
                # pass the host ``environment/`` source tree as task_root:
                # that tree contains Dockerfile/checksum build metadata which
                # is deliberately absent from the container.  Materialize
                # the public files copied into /app and use that same root
                # for both candidate and task data during Proxy execution.
                runtime_payload = Path(temp_dir) / "runtime-payload"
                runtime_root = runtime_payload / "app"
                _materialize_solver_runtime_view(
                    task_root,
                    runtime_root,
                )
                # The exported candidate is a separate immutable payload. Its
                # declared /app artifacts (normally submission/) are layered
                # onto the freshly materialized public runtime view, just as
                # the Solver image sees them. Never clean the artifact payload
                # in place: that would remove the candidate before checking it.
                candidate_source = _verifier_candidate_root(evaluation_artifact)
                if candidate_source.is_dir():
                    shutil.copytree(
                        candidate_source,
                        runtime_root,
                        symlinks=False,
                        dirs_exist_ok=True,
                    )
                runtime_artifact = replace(
                    artifact,
                    storage_path=str(runtime_payload),
                )
                return SurrogateVerifyRunner._run_frozen_verifier_module(
                    verifier_path,
                    runtime_artifact,
                    round_no=round_no,
                    task_root=runtime_root,
                    output_dir=output_dir,
                )
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "verifier_error",
                "checks": [],
                "error": f"冻结 verifier 执行失败: {exc}",
            }

    @staticmethod
    def _run_frozen_verifier_module(
        verifier_path: Path,
        artifact: ArtifactRef,
        *,
        round_no: int,
        task_root: Path,
        output_dir: Path,
    ) -> dict[str, Any]:
        """在隔离的候选副本上加载 verifier 模块。"""

        module_name = f"famou_frozen_verifier_{round_no}_{abs(hash(str(verifier_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, verifier_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载 verifier.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Generated verifiers must resolve public data through task_root.
        # Bind conventional Path constants for compatibility with older
        # bundles that used container-only /app/data literals.
        public_root = Path(task_root).expanduser().resolve()
        for name in ("DATA_NPZ", "DATA_GEOM", "DATA_JSON", "PUBLIC_DATA"):
            value = getattr(module, name, None)
            if isinstance(value, Path):
                candidate = public_root / value.name
                if candidate.is_file():
                    setattr(module, name, candidate)
        verify = getattr(module, "verify", None)
        if not callable(verify):
            raise RuntimeError("verifier.py 缺少 verify()")
        value = verify(
            _verifier_candidate_root(artifact),
            Path(task_root),
            output_dir,
        )
        if not isinstance(value, Mapping):
            raise RuntimeError("verify() 必须返回对象")
        return dict(value)

    @staticmethod
    def _complete_diagnosis_checks(
        plan: Mapping[str, Any],
        diagnosis: Mapping[str, Any],
        rubric_result: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        raw_checks = diagnosis.get("checks")
        checks = [dict(item) for item in raw_checks or [] if isinstance(item, Mapping)]
        by_rubric = {
            str(item.get("rubric_id")): item
            for item in checks
            if item.get("rubric_id")
        }
        deterministic_coverage = {
            str(item.get("rubric_id"))
            for item in rubric_result.get("checks", [])
            if isinstance(item, Mapping)
            and item.get("rubric_id")
            and item.get("status") in {"passed", "failed"}
        }
        for rubric in plan.get("rubrics", []):
            if not isinstance(rubric, Mapping):
                continue
            rubric_id = str(rubric.get("id") or "")
            if (
                rubric_id
                and rubric_id not in by_rubric
                and rubric_id not in deterministic_coverage
            ):
                checks.append(
                    {
                        "rubric_id": rubric_id,
                        "status": "unknown",
                        "summary": "VerifierAgent 未覆盖该固定 rubric",
                        "evidence_refs": [],
                    }
                )
        return checks

    def _safe_agent_view(
        self,
        value: Mapping[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        try:
            public = self.benchmark.agent_view(dict(value), source=source)
        except Exception:
            # 脱敏器不支持该阶段时宁可少给信息，也不能回退泄露原始结果。
            return {"valid": value.get("valid") is True, "source": source}
        return dict(public) if isinstance(public, Mapping) else {"valid": False, "source": source}

    @staticmethod
    def _report(
        round_no: int,
        status: str,
        checks: list[dict[str, Any]],
        *,
        artifact: ArtifactRef | None,
        repair_instructions: Any = None,
        error: Any = None,
        verifier_mode: str = "proxy",
        gt_evaluation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        report = {
            "schema_version": 1,
            "round": round_no,
            "status": status,
            "checks": checks,
            "repair_instructions": repair_instructions or [],
            "artifact_ref": artifact.to_dict() if artifact else None,
            "verifier_mode": verifier_mode,
        }
        if gt_evaluation is not None:
            report["gt_evaluation"] = dict(gt_evaluation)
        if error:
            report["error"] = str(error)
        return report

    @staticmethod
    def _save_report(
        invocation: NodeInvocation,
        context: GraphContext,
        report: dict[str, Any],
        *,
        agent_report: dict[str, Any] | None = None,
    ) -> NodeResult:
        system_path = (
            context.run_dir / "controller" / "surrogate" / f"round_{report['round']}.json"
        )
        agent_path = (
            context.run_dir / "agent_control" / "surrogate" / f"round_{report['round']}.json"
        )
        visible_ref = f".famou/surrogate/round_{report['round']}.json"
        solver_path = context.workspace_dir / visible_ref
        public_report = dict(agent_report or {
            "schema_version": 1,
            "round": report["round"],
            "status": report["status"],
            "checks": [
                {"id": item.get("id"), "status": item.get("status")}
                for item in report.get("checks", [])
            ],
            "repair_instructions": report.get("repair_instructions") or [],
        })
        public_report["agent_workspace_path"] = visible_ref
        public_report["verifier_mode"] = str(report.get("verifier_mode") or "proxy")
        if (
            public_report["verifier_mode"] in {"gt_primary", "gt_budget"}
            and isinstance(report.get("gt_evaluation"), Mapping)
        ):
            # gt_primary/gt_budget explicitly use the official verifier as
            # iterative feedback. run_gt_evaluation has already removed
            # Controller-only identifiers and paths, so preserve its complete
            # actionable stdout/stderr/CTRF payload for the resumed Solver.
            public_report["gt_evaluation"] = dict(report["gt_evaluation"])
        if public_report["verifier_mode"] == "gt_budget":
            public_report["official_gt_consumed"] = bool(report.get("official_gt_consumed"))
        public_checks: list[dict[str, Any]] = []
        for raw_check in public_report.get("checks", []):
            if not isinstance(raw_check, Mapping):
                continue
            # Verifier 的私有快照路径对 Solver 不可用，也不属于稳定 contract。
            # 每项统一引用 Solver worktree 内的脱敏报告，详细证据仍在对应 details 中。
            public_checks.append({**raw_check, "evidence_refs": [visible_ref]})
        public_report["checks"] = public_checks
        atomic_write_json(system_path, report)
        atomic_write_json(agent_path, public_report)
        atomic_write_json(solver_path, public_report)
        artifact = report.get("artifact_ref")
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "succeeded",
            {
                "status": report["status"],
                "report_ref": str(agent_path.relative_to(context.run_dir)),
                "system_report_ref": str(system_path.relative_to(context.run_dir)),
                "artifact_ref": artifact,
                "error": report.get("error"),
                # gt_budget: 本轮是否真实消耗了一次官方 GT 额度。
                "gt_consumed": bool(report.get("official_gt_consumed")),
            },
        )


# 新设计名称；保留 VerifierPlanRunner 作为旧 graph/checkpoint 的兼容入口。
VerifierCompilerRunner = VerifierPlanRunner


class FreezeWorkspaceRunner:
    """把 Agent worktree 复制成只读、带哈希的最终 Artifact。"""

    # Lean's .lake is a build cache and commonly contains package symlinks;
    # it is never a declared submission artifact and must not block freezing.
    _EXCLUDED = {".git", ".famou", "__pycache__", ".lake"}

    def __init__(self, artifact_paths: Sequence[str] | None = None) -> None:
        self.artifact_paths = tuple(str(path) for path in (artifact_paths or ()))

    def __call__(self, invocation: NodeInvocation, context: GraphContext) -> NodeResult:
        destination = context.run_dir / "artifacts" / "final_workspace"
        if not destination.exists():
            temporary = destination.with_name(destination.name + ".partial")
            if temporary.exists():
                shutil.rmtree(temporary)
            skipped_symlinks: list[str] = []
            self._copy_tree(context.workspace_dir, temporary, skipped_symlinks)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)
            self._make_read_only(destination)
            atomic_write_json(
                context.run_dir / "controller" / "final_workspace_skipped_symlinks.json",
                {"skipped_symlinks": skipped_symlinks},
            )
        skipped_path = context.run_dir / "controller" / "final_workspace_skipped_symlinks.json"
        skipped_symlinks = (
            json.loads(skipped_path.read_text(encoding="utf-8")).get("skipped_symlinks", [])
            if skipped_path.is_file()
            else []
        )
        artifact = ArtifactRef.from_path(
            destination,
            artifact_id=f"{context.run_id}:final_workspace",
            kind="terminal_workspace",
            producer="terminal_task_graph",
            metadata={
                "task_id": context.task_id,
                "artifact_paths": list(self.artifact_paths),
                "skipped_symlinks": list(skipped_symlinks),
            },
        )
        ref_path = context.run_dir / "controller" / "final_workspace_ref.json"
        atomic_write_json(ref_path, artifact.to_dict())
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "succeeded",
            {"workspace_ref": artifact.to_dict(), "workspace_ref_path": str(ref_path)},
        )

    @classmethod
    def _copy_tree(cls, source: Path, destination: Path, skipped_symlinks: list[str] | None = None) -> None:
        destination.mkdir(parents=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            if child.name in cls._EXCLUDED or child.name.startswith(".git"):
                continue
            if child.is_symlink():
                # Solvers leave scratch symlinks (e.g. ``controller_mod.py ->
                # /app/submission/controller.py``) in the worktree. The frozen
                # workspace is an archival snapshot, not the audited artifact
                # (FinalAudit consumes the container export), so a symlink must
                # not abort the run. Never follow it; record and skip.
                if skipped_symlinks is not None:
                    skipped_symlinks.append(str(child))
                continue
            target = destination / child.name
            if child.is_dir():
                cls._copy_tree(child, target, skipped_symlinks)
            elif child.is_file():
                shutil.copy2(child, target)
            else:
                raise ValueError(f"final workspace 包含不支持的文件类型: {child}")

    @staticmethod
    def _make_read_only(root: Path) -> None:
        for path in sorted(root.rglob("*"), reverse=True):
            mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(mode & ~0o222)
        mode = stat.S_IMODE(root.stat().st_mode)
        root.chmod(mode & ~0o222)


@dataclass
class FinalAuditRunner:
    """在 Agent 退出和 workspace 冻结后 exactly-once 调用可信 evaluator。"""

    evaluator: EvaluationFacility

    def __call__(self, invocation: NodeInvocation, context: GraphContext) -> NodeResult:
        root = context.run_dir / "controller" / "final_audit"
        request_path = root / "request.json"
        result_path = root / "result.json"
        existing = read_json(result_path)
        if isinstance(existing, dict):
            # Older/partially resumed runs may have persisted the GT result
            # before the comparison write.  Complete that sidecar on retry so
            # every finished proxy run has an auditable proxy-vs-GT record.
            comparison_path = self._write_proxy_comparison_if_needed(
                context.run_dir, root, invocation, existing
            )
            if comparison_path is not None and existing.get("proxy_gt_comparison_ref") != str(
                comparison_path.relative_to(context.run_dir)
            ):
                existing = dict(existing)
                existing["proxy_gt_comparison_ref"] = str(
                    comparison_path.relative_to(context.run_dir)
                )
                atomic_write_json(result_path, existing)
            return self._node_result(invocation, result_path, existing)

        # Prefer the immutable artifact exported by the latest FMJob round.
        # A frozen worktree is still retained for publication/debugging, but it
        # is not a reliable representation of container-absolute output paths.
        candidate_ref = invocation.payload.get("candidate_artifact_ref")
        raw_ref = (
            candidate_ref
            if isinstance(candidate_ref, Mapping)
            else invocation.payload.get("workspace_ref")
        )
        if not isinstance(raw_ref, Mapping):
            raise ValueError("FinalAudit 缺少结构化 FrozenWorkspaceRef")
        artifact = ArtifactRef.from_dict(raw_ref)
        artifact.verify()
        request = EvaluationRequest(
            task_id=str(context.task_id or "terminal-task"),
            attempt_id=f"{context.run_id}:final",
            artifact_ref=artifact,
            metadata={"graph": "terminal_task", "final_audit": True},
        )
        atomic_write_json(request_path, request.to_dict())
        result = self.evaluator.evaluate(request)
        value = result.to_dict()
        comparison_path = self._write_proxy_comparison_if_needed(
            context.run_dir, root, invocation, value
        )
        if comparison_path is not None:
            value["proxy_gt_comparison_ref"] = str(
                comparison_path.relative_to(context.run_dir)
            )
        atomic_write_json(result_path, value)
        return self._node_result(invocation, result_path, value)

    @staticmethod
    def _write_proxy_comparison_if_needed(
        run_dir: Path,
        root: Path,
        invocation: NodeInvocation,
        gt_result: Mapping[str, Any],
    ) -> Path | None:
        """Persist the proxy/GT sidecar exactly once when proxy mode is used."""

        proxy_report_ref = invocation.payload.get("proxy_report_ref")
        if (
            str(invocation.payload.get("candidate_verifier_mode") or "").lower()
            != "proxy"
            or not proxy_report_ref
        ):
            return None
        comparison_path = root / "proxy_gt_comparison.json"
        if not comparison_path.exists():
            comparison = _compare_proxy_and_gt(
                run_dir,
                str(proxy_report_ref),
                gt_result,
            )
            atomic_write_json(comparison_path, comparison)
        return comparison_path

    @staticmethod
    def _node_result(
        invocation: NodeInvocation,
        result_path: Path,
        value: Mapping[str, Any],
    ) -> NodeResult:
        return NodeResult(
            invocation.invocation_id,
            invocation.kind,
            "succeeded",
            {
                "status": "passed" if value.get("valid") is True else "failed",
                "result_ref": str(result_path),
            },
        )


def _resolve_run_ref(run_dir: Path, value: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (run_dir / path).resolve()
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"run reference 越界: {value}") from exc
    return resolved


def _compare_proxy_and_gt(
    run_dir: Path,
    proxy_report_ref: str,
    gt_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a compact, auditable comparison for every proxy run."""

    proxy_path = _resolve_run_ref(run_dir, proxy_report_ref)
    proxy = read_json(proxy_path)
    if not isinstance(proxy, Mapping):
        raise ValueError(f"Proxy report 不是对象: {proxy_report_ref}")
    proxy_checks = [
        item for item in proxy.get("checks", []) if isinstance(item, Mapping)
    ]
    proxy_passed = sum(item.get("status") == "passed" for item in proxy_checks)
    proxy_failed = sum(item.get("status") not in {"passed", "skipped"} for item in proxy_checks)

    # Pytest stdout counts expanded parameterized cases, while CTRF may count
    # only test functions. Prefer stdout so persisted comparisons use the same
    # denominator as the official FinalAudit report and results document.
    stdout = str(gt_result.get("stdout") or "")
    stdout_passed = re.findall(r"(?<!\w)(\d+)\s+passed\b", stdout)
    stdout_failed = re.findall(r"(?<!\w)(\d+)\s+failed\b", stdout)
    gt_passed = int(stdout_passed[-1]) if stdout_passed else None
    gt_failed = int(stdout_failed[-1]) if stdout_failed else None
    count_source = "pytest_stdout" if gt_passed is not None or gt_failed is not None else None
    if count_source == "pytest_stdout":
        gt_passed = gt_passed or 0
        gt_failed = gt_failed or 0
    else:
        ctrf = gt_result.get("ctrf")
        if isinstance(ctrf, Mapping):
            summary = ((ctrf.get("results") or {}).get("summary") or {})
            if isinstance(summary, Mapping):
                if isinstance(summary.get("passed"), int):
                    gt_passed = summary["passed"]
                if isinstance(summary.get("failed"), int):
                    gt_failed = summary["failed"]
                if gt_passed is not None or gt_failed is not None:
                    count_source = "ctrf"

    gt_valid = gt_result.get("valid") is True
    proxy_status = str(proxy.get("status") or "unknown")
    gt_status = "passed" if gt_valid else "failed"
    return {
        "schema_version": 1,
        "proxy_report_ref": proxy_report_ref,
        "gt_result_ref": "controller/final_audit/result.json",
        "proxy": {
            "status": proxy_status,
            "checks_total": len(proxy_checks),
            "checks_passed": proxy_passed,
            "checks_failed": proxy_failed,
        },
        "gt": {
            "status": gt_status,
            "valid": gt_valid,
            "reward": (gt_result.get("official_metrics") or {}).get("reward"),
            "checks_passed": gt_passed,
            "checks_failed": gt_failed,
            "checks_count_source": count_source,
        },
        "difference": {
            "comparison_basis": "Proxy 检查集合与 GT 测试集合通常不同，数量差异仅作覆盖范围提示，不作为准确率比较",
            "status_diff": proxy_status != gt_status,
            "passed_count_diff": None if gt_passed is None else proxy_passed - gt_passed,
            "failed_count_diff": None if gt_failed is None else proxy_failed - gt_failed,
            "interpretation": (
                "Proxy 与 GT 状态一致"
                if proxy_status == gt_status
                else "Proxy 与 GT 状态不一致；以 GT FinalAudit 为准"
            ),
        },
    }


def _verifier_candidate_root(artifact: ArtifactRef) -> Path:
    """Return the CFS directory corresponding to the verifier's workdir.

    Harbor keeps the leading container path component in its payload (for
    example ``payload/root/results`` for ``/root/results``).  Generated
    verifiers receive the directory that stood for their container workdir and
    then look below it for ``results``.  Select that prefix from the declared
    artifact contract instead of treating the payload directory as the
    workdir itself.
    """

    root = Path(artifact.storage_path).resolve()
    raw_paths = artifact.metadata.get("artifact_paths", [])
    paths = [str(path) for path in raw_paths if str(path).startswith("/")]
    if not paths:
        return root
    prefixes = {Path(path).parts[1] for path in paths if len(Path(path).parts) > 1}
    if len(prefixes) == 1:
        prefix = next(iter(prefixes))
        # /results/... is already relative to the candidate root; /root/...,
        # /app/... and task-specific prefixes need their payload subdirectory.
        if prefix != "results":
            candidate = root / prefix
            if candidate.is_dir():
                return candidate
    return root


_RUNTIME_BUILD_METADATA = {
    "Dockerfile",
    ".dockerignore",
}


def _materialize_solver_runtime_view(task_root: Path, runtime_root: Path) -> Path:
    """Materialize the public files that the Solver image copies into ``/app``.

    ``task_root`` is the host-side task ``environment`` directory, while
    ``runtime_root`` represents the container's ``/app``.  Docker build files
    and checksum manifests are intentionally excluded unless the Dockerfile
    explicitly copies them into ``/app``.  Parsing the task Dockerfile keeps
    this mapping task-defined instead of maintaining per-task path rules.
    """

    source = Path(task_root).expanduser().resolve()
    destination = Path(runtime_root).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"task runtime source 不存在: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    dockerfile = source / "Dockerfile"
    copy_rules: list[tuple[list[str], str]] = []
    if dockerfile.is_file():
        for raw_line in dockerfile.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tokens = shlex.split(line, comments=True, posix=True)
            except ValueError:
                continue
            if not tokens or tokens[0].upper() not in {"COPY", "ADD"}:
                continue
            values = [value for value in tokens[1:] if not value.startswith("--")]
            if len(values) < 2:
                continue
            target = values[-1]
            if not target.startswith("/app"):
                continue
            # A path such as /application must not be treated as /app.
            if len(target) > 4 and target[4] != "/":
                continue
            copy_rules.append((values[:-1], target))

    def copy_source(raw_source: str, target: str, *, multiple: bool) -> None:
        relative = raw_source.lstrip("/")
        if relative in {"", "."}:
            source_path = source
        else:
            source_path = (source / relative).resolve()
            try:
                source_path.relative_to(source)
            except ValueError:
                return
        if not source_path.exists() or source_path.is_symlink():
            return
        target_rel = target[4:].lstrip("/")
        target_path = destination / target_rel
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            for child in source_path.iterdir():
                if source_path == source and child.name in _RUNTIME_BUILD_METADATA:
                    continue
                child_target = target_path / child.name
                if child.is_dir() and not child.is_symlink():
                    shutil.copytree(child, child_target, symlinks=False, dirs_exist_ok=True)
                elif child.is_file() and not child.is_symlink():
                    child_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(child, child_target)
            return
        # Docker treats a multi-source COPY destination as a directory.
        target_file = target_path / source_path.name if multiple or target.endswith("/") else target_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_file)

    for sources, target in copy_rules:
        for raw_source in sources:
            copy_source(raw_source, target, multiple=len(sources) > 1)

    # A malformed or non-standard Dockerfile should not make Proxy unusable.
    # Keep a conservative fallback containing public environment data while
    # excluding files that only belong to image construction.
    if not any(destination.iterdir()):
        for child in source.iterdir():
            if child.name in _RUNTIME_BUILD_METADATA or child.name.endswith(".sha256"):
                continue
            target = destination / child.name
            if child.is_dir() and not child.is_symlink():
                shutil.copytree(child, target, symlinks=False, dirs_exist_ok=True)
            elif child.is_file() and not child.is_symlink():
                shutil.copy2(child, target)
    return destination


def _check_status(value: Mapping[str, Any]) -> str:
    if value.get("valid") is True or value.get("status") in {"passed", "valid", "ok"}:
        return "passed"
    return "failed"


def _generated_report_status(value: Mapping[str, Any]) -> str:
    """Normalize the two result protocols emitted by generated verifiers."""

    status = str(value.get("status") or "").strip().lower()
    if status in {"passed", "valid", "ok"}:
        return "passed"
    if status in {"repair_required", "failed", "invalid"}:
        return "repair_required"
    if status == "verifier_error":
        return "verifier_error"
    if isinstance(value.get("passed"), bool):
        return "passed" if value["passed"] else "repair_required"
    return "verifier_error"


def _generated_check_status(value: Mapping[str, Any]) -> str:
    status = str(value.get("status") or "").strip().lower()
    if status in {"passed", "valid", "ok"}:
        return "passed"
    if status in {"failed", "invalid", "repair_required"}:
        return "failed"
    if isinstance(value.get("passed"), bool):
        return "passed" if value["passed"] else "failed"
    return "unknown"


def _resolve_verifier_task_root(root: Path) -> Path:
    """Return the public task-data root expected by generated verifiers."""

    root = Path(root).expanduser().resolve()
    if (root / "metadata.json").is_file():
        return root
    # Harbor tasks use both ``environment/data`` and a direct ``environment``
    # layout for public inputs. Resolve either before invoking the verifier.
    for data_root in (root / "environment" / "data", root / "environment"):
        if not data_root.is_dir():
            continue
        if (data_root / "metadata.json").is_file() or any(
            (data_root / marker).exists()
            for marker in (
                "study",
                "vocabularies.json",
                "icd10_candidates.tsv",
                # TBS tasks commonly expose their public package under
                # environment/data with api/ and instances/ directories.
                # These are normative task inputs, not verifier-private data.
                "api",
                "instances",
            )
        ):
            return data_root
    return root


def _module_version(name: str) -> str | None:
    """Return a dependency version for runtime audit evidence."""

    module = sys.modules.get(name)
    value = getattr(module, "__version__", None) if module is not None else None
    return str(value) if value is not None else None


def _safe_artifact_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"rubric file path 非法: {relative!r}")
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"rubric file path 越界: {relative!r}") from exc
    return target


__all__ = [
    "FinalAuditRunner",
    "FreezeWorkspaceRunner",
    "DeterministicRubricExecutor",
    "NoopRubricExecutor",
    "RubricExecutor",
    "SolverTurnRunner",
    "SurrogateVerifyRunner",
    "VerifierPlanRunner",
    "VerifierCompilerRunner",
]
