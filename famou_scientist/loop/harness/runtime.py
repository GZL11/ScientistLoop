"""把外部 benchmark Harness 接入统一异步科研调度器。"""
from __future__ import annotations

import shutil
import tomllib
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agents.workers import workers_from_goal
from ..execution.resources import resource_envelope_dict
from ..utils import atomic_write_json, new_id, now_ms, read_json
from ..domain.status import LoopStatus
from ..plugins import (
    AdapterContext,
    FinalizationRequest,
    FinalizationResult,
    load_adapter,
)
from ..observability import ObservabilityStore, TokenPricingPolicy
from ..runtime import AsyncOrchestrator
from ..runtime.orchestrator import OrchestratorConfig
from ..storage.expbank import ExpBank
from ..storage.evolution_graph import GRAPH_VERSIONS
from ..storage.cross_task_expbank import (
    CrossTaskExpBank,
    resolve_experience_domain,
)
from ..storage.queues import QueueSet
from ..storage.state import ResearchState
from ..storage.workspace import WorkspaceRunLock
from .evaluator import EvaluatorClient
from .trajectory import TrajectoryWriter


def _explicit_model(value: str | None) -> bool:
    """判断模型名是否显式可用，拒绝旧脚本使用的默认模型占位符。"""

    return bool(value and str(value).strip() not in {"", "-"})


def _fmjob_prefix(task_id: str, role: str) -> str:
    """Return a stable short prefix that leaves room for FMJob's timestamp."""

    digest = hashlib.sha1(f"{task_id}:{role}".encode("utf-8")).hexdigest()[:8]
    task_slug = "".join(ch if ch.isalnum() else "-" for ch in task_id).strip("-")
    role_slug = "".join(ch if ch.isalnum() else "-" for ch in role).strip("-")
    # FMJob appends a timestamp and Kubernetes caps the complete name at 63
    # characters. Keep the caller-supplied portion comfortably below that cap.
    return f"f-{task_slug[:16]}-{role_slug[:6]}-{digest}"


def _summary_status(research: dict[str, Any]) -> str:
    """Map a drained wall-time stop to a successful benchmark completion."""

    status = research.get("status") or LoopStatus.Research.COMPLETED
    shutdown = research.get("shutdown")
    if (
        status == LoopStatus.Research.STOPPED
        and research.get("termination_reason") == "wall_time_budget_exhausted"
        and isinstance(shutdown, dict)
        and shutdown.get("phase") == "evaluation_drain_completed"
    ):
        return LoopStatus.Research.COMPLETED
    return str(status)


@dataclass(frozen=True)
class HarnessConfig:
    """描述一次由外部 benchmark 托管的 Agent 运行。"""

    task_id: str
    run_dir: Path
    problem_dir: Path
    workspace_dir: Path
    agent_runtime: str
    agent_graph: str = "sota_search"
    idea_runtime: str | None = None
    implement_runtime: str | None = None
    solver_runtime: str | None = None
    verifier_runtime: str | None = None
    agent_adapter: str = "cli"
    benchmark_adapter: str = "naturebench"
    evaluator_adapter: str = "naturebench"
    harbor_trial_dir: Path | None = None
    harbor_artifact_root: Path | None = None
    # Optional root where Harbor compose services export their declared
    # artifacts, e.g. ``<trial>/artifacts/fmjob-service``.
    harbor_service_artifact_root: Path | None = None
    harbor_famou_dir: Path | None = None
    harbor_agent_task_view: Path | None = None
    harbor_backend: str | None = None
    fm_job_bin: str = "fm-job"
    solver_image: str | None = None
    verifier_image: str | None = None
    # Official TBS verifier image; distinct from the VerifierAgent image.
    gt_verifier_image: str | None = None
    candidate_verifier_mode: str = "proxy"
    # gt_budget 模式下 Solver 运行期间可主动申请的官方 GT 次数（FinalAudit 不计入）。
    official_gt_budget: int = 1
    fmjob_cpu: str = "4"
    fmjob_memory: str = "8Gi"
    fmjob_gpu: int = 0
    fmjob_shm_size: str = "8Gi"
    model: str | None = None
    idea_model: str | None = None
    implement_model: str | None = None
    idea_rank_model: str | None = None
    # 未配置时由 workers 层继承 Idea Agent 的运行时与模型。
    idea_judge_model: str | None = None
    solver_model: str | None = None
    verifier_model: str | None = None
    agent_binary: str | None = None
    # Python executable inside an Agent container; defaults to host interpreter
    # for local sandboxes, but FMJob images commonly provide only python3.
    agent_python_binary: str | None = None
    # 兼容旧版 --iterations；None 表示 benchmark 没有声明尝试次数上限。
    iterations: int | None = None
    agent_timeout_sec: float = 3600
    # 单次 Implement 激活的墙钟上限。None 表示跟随 agent_timeout_sec。
    # 单独拆出来是因为 idea/implement 的时间画像完全不同：idea 通常几分钟结束，
    # implement 要写代码 + 跑 smoke。20260920 实测 43/181 次 attempt 是跑满
    # 3600 秒被掐掉的，而心跳送到时它们还没把代码跑通（见
    # .famou/naturebench-submit-batches/20260920-graph-v2-ab-10x2/HEARTBEAT_FINDINGS.md）。
    implement_agent_timeout_sec: float | None = None
    # None 表示跟随 task.toml 的 [agent].timeout_sec；该字段是
    # VerifierAgent 编译预算，不是官方 [verifier].timeout_sec。
    verifier_planning_timeout_sec: float | None = None
    implement_deadline_heartbeat: bool = False
    implement_deadline_heartbeat_after_sec: float = 2400
    experiment_timeout_sec: float = 3600
    max_wall_time_hours: float | None = None
    max_turns: int | None = None
    # Deprecated compatibility field; the terminal-task loop is time-bounded.
    max_refine_rounds: int = 0
    max_parallel_ideas: int = 1
    max_parallel_implementations: int = 1
    max_parallel_evaluations: int = 1
    max_implement_lifetime_sec: float = 14_400
    # 默认允许同一 Idea 在 evaluator 反馈后继续两次；每次提交之间 Actor 都会
    # park 并释放进程槽，不会同步占用 Implement Worker。
    max_implement_turns_per_actor: int = 3
    max_run_attempts_per_actor: int | None = None
    max_official_evaluations_per_actor: int | None = None
    max_repairs_per_revision: int = 1
    # 出分后让不让同一个 actor 自己接着改。关掉＝改进必须回 IdeaAgent 看图，
    # 作为新的 exploit 节点重新入队（演化图 v2 的前提）。默认 True 保持历史行为。
    refine_after_evaluation: bool = True
    # 单个方案允许 debug 的总次数；None = 不设独立上限（历史行为）。
    max_debug_attempts_per_actor: int | None = None
    idea_queue_high_watermark: int | None = None
    evaluation_queue_capacity: int | None = None
    pairwise_improve_search: bool = True
    # 关闭后不再调用 IdeaAgent 产新方案，只消费队列里已有的条目。
    idea_generation: bool = True
    # 在 benchmark 工作流里启用 Idea 图的 idea→idea 派生边。默认关闭。
    idea_graph: bool = False
    # 方案图 schema 版本：v1 = 现状（IDEAS.md，单父无分数），v2 = 方案演化图
    # （GRAPH.md，多父 DAG + 节点带最好分 + 算子校验）。默认 v1——这是所有历史
    # 批次的对照臂配置，默认改 v2 会静默改变后续一切 run 的行为。
    idea_graph_version: str = "v1"
    time_aware_idea_ranking: bool = False
    idea_rank_trigger_remaining_sec: float = 3_600
    idea_rank_max_turns: int | None = 30
    # Idea Ranking 是一次性的冲刺调度调用，给足时间完成 ExpBank 阅读和结构化输出。
    # 旧的 600 秒上限导致 121 次调用中 21% 被 SIGTERM，故放宽到 30 分钟。
    idea_rank_timeout_sec: float = 1_800
    # 待实现 Idea 少于该条数时跳过排序，不为两条之间的取舍花一次 Judge 调用。
    idea_rank_min_items: int = 3
    # Idea Judge 辩论环节。与冲刺期排序对称：那个是"剩余 ≤1h 才开"，这个是
    # "已跑 ≥1h 且已有 in-task 证据才开"。
    idea_debate: bool = False
    idea_debate_mode: str = "respond"
    idea_debate_max_rounds: int = 1
    idea_debate_min_elapsed_sec: float = 3_600
    idea_debate_min_evaluated_attempts: int = 1
    idea_debate_allow_cross_task_only: bool = False
    idea_debate_emit_pair: bool = False
    idea_debate_max_turns: int | None = 30
    idea_debate_timeout_sec: float = 1_800
    available_cpu: float | None = None
    available_gpu: int | None = None
    available_memory_gib: float | None = None
    # None 时从控制面保留内存和最大 Agent 并发自动均分；显式值用于特殊环境覆盖。
    agent_process_memory_limit_gib: float | None = None
    agent_uid: int | None = None
    agent_gid: int | None = None
    finalize_evaluation: bool = False
    pricing: dict[str, Any] | None = None

    @property
    def effective_implement_timeout_sec(self) -> float:
        """单次 Implement 激活的实际墙钟上限；未单独配置时回落到通用值。"""
        if self.implement_agent_timeout_sec is not None:
            return float(self.implement_agent_timeout_sec)
        return float(self.agent_timeout_sec)

    def validate(self) -> None:
        """校验公开目录、运行时和预算参数。"""
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not self.problem_dir.is_dir():
            raise FileNotFoundError(
                f"public problem directory not found: {self.problem_dir}"
            )
        for name in ("agent_adapter", "benchmark_adapter", "evaluator_adapter"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if not self.agent_runtime.strip():
            raise ValueError("agent_runtime must not be empty")
        if self.agent_graph not in {"sota_search", "terminal_task", "scimodeling_budget"}:
            raise ValueError(f"unsupported agent_graph: {self.agent_graph!r}")
        if self.agent_graph == "scimodeling_budget":
            if self.benchmark_adapter != "scimodelingbench" or self.evaluator_adapter != "scimodelingbench":
                raise ValueError("scimodeling_budget requires SciModelingBench adapters")
            if self.iterations is not None:
                raise ValueError("use --official-gt-budget, not --iterations, for limited GT")
            if self.solver_image:
                raise ValueError("scimodeling_budget runs inside the SciModelingBench job, not a nested solver image")
        if self.candidate_verifier_mode not in {
            "proxy",
            "gt_primary",
            "gt_final_only",
            "gt_budget",
            "dual_shadow",
        }:
            raise ValueError(
                "candidate_verifier_mode must be proxy, gt_primary, gt_final_only, "
                "gt_budget, or dual_shadow"
            )
        if int(self.official_gt_budget) < 0:
            raise ValueError("official_gt_budget must be >= 0")
        for name in (
            "idea_runtime",
            "implement_runtime",
            "solver_runtime",
            "verifier_runtime",
        ):
            value = getattr(self, name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must not be empty when configured")
        if self.pricing is not None:
            TokenPricingPolicy.from_mapping(self.pricing)
        if self.implement_agent_timeout_sec is not None and (
            self.implement_agent_timeout_sec <= 0
        ):
            raise ValueError("implement_agent_timeout_sec must be greater than 0")
        if self.implement_deadline_heartbeat:
            if not (
                0
                < self.implement_deadline_heartbeat_after_sec
                < self.effective_implement_timeout_sec
            ):
                raise ValueError(
                    "implement_deadline_heartbeat_after_sec 必须大于 0 且小于 "
                    "implement_agent_timeout_sec（未设置时为 agent_timeout_sec）"
                )
        if self.agent_adapter == "cli" and self.agent_runtime.strip().lower() in {
            "claude",
            "codex",
            "opencode",
        }:
            missing_roles = []
            if self.agent_graph == "scimodeling_budget":
                if not (_explicit_model(self.solver_model) or _explicit_model(self.model)):
                    missing_roles.append("researcher")
            elif self.agent_graph == "terminal_task":
                if not (_explicit_model(self.solver_model) or _explicit_model(self.model)):
                    missing_roles.append("solver")
                if not (_explicit_model(self.verifier_model) or _explicit_model(self.model)):
                    missing_roles.append("verifier")
            else:
                if not (_explicit_model(self.idea_model) or _explicit_model(self.model)):
                    missing_roles.append("idea")
                if not (
                    _explicit_model(self.implement_model)
                    or _explicit_model(self.model)
                ):
                    missing_roles.append("implement")
                if self.time_aware_idea_ranking and not (
                    _explicit_model(self.idea_rank_model)
                    or _explicit_model(self.model)
                ):
                    missing_roles.append("idea_rank")
            if missing_roles:
                raise ValueError(
                    "CLI Agent 必须显式指定模型，缺少角色: "
                    + ", ".join(missing_roles)
                )
        if self.iterations is not None and self.iterations < 1:
            raise ValueError("iterations must be at least 1")
        for name in (
            "max_parallel_ideas",
            "max_parallel_implementations",
            "max_parallel_evaluations",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.max_wall_time_hours is not None and self.max_wall_time_hours <= 0:
            raise ValueError("max_wall_time_hours must be greater than 0")
        if self.max_refine_rounds < 0:
            raise ValueError("max_refine_rounds must not be negative")
        if (
            self.verifier_planning_timeout_sec is not None
            and self.verifier_planning_timeout_sec <= 0
        ):
            raise ValueError("verifier_planning_timeout_sec must be greater than 0")
        if self.max_implement_lifetime_sec <= 0:
            raise ValueError("max_implement_lifetime_sec must be greater than 0")
        if self.max_implement_turns_per_actor < 1:
            raise ValueError("max_implement_turns_per_actor must be at least 1")
        if (
            self.max_debug_attempts_per_actor is not None
            and self.max_debug_attempts_per_actor < 0
        ):
            raise ValueError("max_debug_attempts_per_actor must be non-negative")
        if (
            self.evaluation_queue_capacity is not None
            and self.evaluation_queue_capacity < 1
        ):
            raise ValueError("evaluation_queue_capacity must be at least 1")
        if self.idea_rank_trigger_remaining_sec <= 0:
            raise ValueError("idea_rank_trigger_remaining_sec must be greater than 0")
        if self.idea_rank_max_turns is not None and self.idea_rank_max_turns < 1:
            raise ValueError("idea_rank_max_turns must be at least 1")
        if self.idea_rank_timeout_sec <= 0:
            raise ValueError("idea_rank_timeout_sec must be greater than 0")
        if self.idea_debate_mode not in {"respond", "rewrite"}:
            raise ValueError("idea_debate_mode must be respond or rewrite")
        # 宿主层抛错、orchestrator 层钳到默认，是这里的既有双重校验风格：拼错的
        # 版本号在提交时就该炸，而不是安静地跑成对照臂——那会毁掉整批配对实验。
        if self.idea_graph_version not in GRAPH_VERSIONS:
            raise ValueError(
                "idea_graph_version must be one of " + "/".join(GRAPH_VERSIONS)
            )
        if self.idea_debate_max_rounds < 1:
            raise ValueError("idea_debate_max_rounds must be at least 1")
        if self.idea_debate_min_elapsed_sec < 0:
            raise ValueError("idea_debate_min_elapsed_sec must not be negative")
        if self.idea_debate_min_evaluated_attempts < 0:
            raise ValueError(
                "idea_debate_min_evaluated_attempts must not be negative"
            )
        if self.idea_debate_max_turns is not None and self.idea_debate_max_turns < 1:
            raise ValueError("idea_debate_max_turns must be at least 1")
        if self.idea_debate_timeout_sec <= 0:
            raise ValueError("idea_debate_timeout_sec must be greater than 0")
        for name in ("available_cpu", "available_gpu", "available_memory_gib"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if (
            self.agent_process_memory_limit_gib is not None
            and self.agent_process_memory_limit_gib <= 0
        ):
            raise ValueError("agent_process_memory_limit_gib must be greater than 0")
        if (self.agent_uid is None) != (self.agent_gid is None):
            raise ValueError("agent_uid 和 agent_gid 必须同时配置")
        if self.agent_uid is not None and (
            int(self.agent_uid) <= 0 or int(self.agent_gid or 0) <= 0
        ):
            raise ValueError("agent_uid 和 agent_gid 必须是非 root 正整数")


def _replace_path(source: Path, destination: Path) -> None:
    """用不保留符号链接的真实副本替换目标路径。"""
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False)
    else:
        shutil.copy2(source, destination)


class BenchmarkHarness:
    """把外部 Harness 上下文转换为统一 ``AsyncOrchestrator`` 运行。"""

    def __init__(self, config: HarnessConfig, evaluator: EvaluatorClient):
        """通过插件注册表装配三类设施和兼容摘要路径。"""
        config.validate()
        self.config = config
        self.resource_envelope = resource_envelope_dict(
            available_cpu=config.available_cpu,
            available_memory_gib=config.available_memory_gib,
            available_gpu=config.available_gpu,
        )
        self.run_dir = config.run_dir.expanduser().resolve()
        self.workspace_dir = config.workspace_dir.expanduser().resolve()
        self.controller_dir = self.run_dir / "controller"
        self.agent_control_dir = self.run_dir / "agent_control"
        self.summary_path = self.controller_dir / "run_summary.json"
        self.trajectory = TrajectoryWriter(self.controller_dir / "trajectory.jsonl")
        for directory in (
            self.run_dir,
            self.workspace_dir,
            self.controller_dir,
            self.agent_control_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        # 这里只保存 Controller 发给非特权 Agent 的单向信号。目录可遍历、
        # 文件可读取，但 Agent 无权创建或覆盖信号；可信控制面仍在 controller/。
        self.agent_control_dir.chmod(0o755)
        self.adapter_context = AdapterContext(
            task_id=config.task_id,
            run_dir=self.run_dir,
            problem_dir=config.problem_dir.expanduser().resolve(),
            workspace_dir=self.workspace_dir,
            options={
                "benchmark_name": f"{config.benchmark_adapter}/{config.task_id}",
                "agent_graph": config.agent_graph,
                "terminal_task_persistent": config.agent_graph == "terminal_task",
                "experiment_timeout_sec": config.experiment_timeout_sec,
                # 单条 Candidate 的 prlimit 来自其 ResourceRequest。总并发占用由
                # Resource Broker 装箱，不再按最大并发静态均分主存。
                "experiment_memory_limit_bytes": None,
                "finalize_evaluation": config.finalize_evaluation,
                "agent_runtime": config.agent_runtime,
                "agent_uid": config.agent_uid,
                "agent_gid": config.agent_gid,
                "harbor_trial_dir": config.harbor_trial_dir,
                "harbor_artifact_root": config.harbor_artifact_root,
                "harbor_service_artifact_root": config.harbor_service_artifact_root,
                "harbor_famou_dir": config.harbor_famou_dir,
                "harbor_agent_task_view": config.harbor_agent_task_view,
                "harbor_backend": config.harbor_backend,
                # FMJob-backed Harbor adapters reuse the same execution
                # settings as the Terminal Agent sandboxes.
                "fm_job_bin": config.fm_job_bin,
                "fmjob_cpu": config.fmjob_cpu,
                "fmjob_memory": config.fmjob_memory,
                "fmjob_gpu": config.fmjob_gpu,
                "fmjob_shm_size": config.fmjob_shm_size,
                "solver_image": config.solver_image,
                "verifier_image": config.verifier_image,
                "gt_verifier_image": config.gt_verifier_image,
                # Official GT runtime is benchmark-owned and independent of
                # the VerifierAgent planning budget.  Long replay tasks (for
                # example TAMP) declare this separately in task.toml.
                "verifier_timeout_sec": self._task_verifier_timeout_sec(
                    config.problem_dir
                ),
            },
        )
        self.agent_adapter = load_adapter("agent", config.agent_adapter)
        self.benchmark_adapter = load_adapter(
            "benchmark", config.benchmark_adapter
        )
        self.evaluator_adapter = load_adapter(
            "evaluator", config.evaluator_adapter
        )
        self.benchmark_facility = self.benchmark_adapter.create(
            self.adapter_context
        )
        self.evaluation_facility = self.evaluator_adapter.create(
            self.adapter_context,
            evaluator,
        )

    def _model_for_role(self, role: str) -> str | None:
        """解析角色模型，并把空值和旧占位符视为未配置。"""

        role_models = {
            "idea": self.config.idea_model,
            "implement": self.config.implement_model,
            "idea_rank": self.config.idea_rank_model,
            "idea_judge": self.config.idea_judge_model,
            # 第一版总结 Agent 复用 Idea 模型，减少 benchmark 接入配置项。
            "experience_summary": self.config.idea_model,
            "terminal_solver": self.config.solver_model,
            "scimodeling_researcher": self.config.solver_model,
            "terminal_verifier": self.config.verifier_model,
        }
        role_model = role_models[role]
        selected = role_model if _explicit_model(role_model) else self.config.model
        return str(selected) if _explicit_model(selected) else None

    def _agent_config(
        self,
        *,
        role: str,
        timeout_override_sec: float | None = None,
    ) -> dict[str, Any]:
        """构造 benchmark 各角色的 CLI Agent 配置。"""
        model = self._model_for_role(role)
        runtime = self.config.agent_runtime
        if role in {"idea", "idea_rank", "idea_judge", "experience_summary"}:
            runtime = self.config.idea_runtime or runtime
        elif role == "implement":
            runtime = self.config.implement_runtime or runtime
        elif role in {"terminal_solver", "scimodeling_researcher"}:
            runtime = self.config.solver_runtime or self.config.implement_runtime or runtime
        elif role == "terminal_verifier":
            runtime = self.config.verifier_runtime or self.config.idea_runtime or runtime
        if timeout_override_sec is not None:
            timeout_sec = float(timeout_override_sec)
        elif role == "implement":
            timeout_sec = self.config.effective_implement_timeout_sec
        else:
            timeout_sec = float(self.config.agent_timeout_sec)
        value: dict[str, Any] = {
            "type": "agent",
            "adapter": self.config.agent_adapter,
            "runtime": runtime,
            "role": role,
            "timeout_sec": timeout_sec,
            "title": f"famou-{self.config.task_id}-{role}",
            "auto_approve": True,
            # 研究墙钟截止时由 AsyncOrchestrator 在独立公共信号目录原子创建
            # 该文件。CLI wrapper 无需穿越 root-only controller/ 即可观察截止。
            "cancel_file": str(
                self.agent_control_dir / "research_deadline_reached.json"
            ),
        }
        process_memory_limit = self._agent_process_memory_limit_gib()
        if process_memory_limit is not None:
            value["process_memory_limit_bytes"] = int(
                process_memory_limit * 1024**3
            )
        if role == "implement":
            # benchmark-managed 模式必须由 Agent 主动提交 Candidate。wrapper 在
            # 提交事件出现后 park 当前进程，不能再把“进程自然退出”等同于提交。
            value["require_submit_candidate"] = True
            value["submission_grace_sec"] = 20
            value["deadline_heartbeat"] = {
                "enabled": self.config.implement_deadline_heartbeat,
                "trigger_after_sec": (
                    self.config.implement_deadline_heartbeat_after_sec
                ),
            }
        elif role in {"terminal_solver", "scimodeling_researcher"}:
            value["session_key"] = role
            value["completion_mode"] = "natural_exit"
            value["require_submit_candidate"] = False
        elif role == "terminal_verifier":
            value["session_key"] = "terminal_verifier"
            # VerifierAgent 编译器的权威产物是 worktree 中的 verifier bundle；
            # 不要求 CLI 额外生成结构化诊断 JSON。
            value["completion_mode"] = "natural_exit"
            value["require_submit_candidate"] = False
            verifier_timeout = self.config.verifier_planning_timeout_sec
            if verifier_timeout is not None:
                value["timeout_sec"] = min(
                    float(value["timeout_sec"]), float(verifier_timeout)
                )
        fmjob_image = (
            self.config.solver_image
            if role == "terminal_solver"
            else self.config.verifier_image
            if role == "terminal_verifier"
            else None
        )
        if fmjob_image:
            value["sandbox"] = {
                "type": "fmjob",
                "image": fmjob_image,
                "fm_job_bin": self.config.fm_job_bin,
                # Kubernetes Job names are RFC-1123; role names use
                # underscores internally (e.g. terminal_solver).
                "prefix": _fmjob_prefix(self.config.task_id, role),
                "cpu": self.config.fmjob_cpu,
                "memory": self.config.fmjob_memory,
                "gpu": self.config.fmjob_gpu,
                "shm_size": self.config.fmjob_shm_size,
                "subpath": str(self.config.harbor_trial_dir or self.run_dir),
                # TerminalTask 的 solve/refine 共用任务级 FMJob；SOTA loop
                # 仍使用原有的一次调用一个 Job 语义。
                "persistent": self.config.agent_graph == "terminal_task",
            }
            # The controller's absolute interpreter path is not guaranteed to
            # exist inside an FMJob image. Runtime wrappers are copied/mounted
            # into the trial, so invoke the image's portable python3 instead.
            value.setdefault("python_binary", "python3")
            if role in {"terminal_solver", "terminal_verifier"}:
                # Generic CLI images do not contain the benchmark environment
                # image's /root/data. Stage the task-owned input data below the
                # trial CFS mount and restore it before launching the solver.
                source_data = self.config.problem_dir / "environment" / "data"
                trial_root = self.config.harbor_trial_dir or self.run_dir
                if source_data.is_dir():
                    staged_data = (
                        Path(trial_root).expanduser().resolve()
                        / "fmjob-inputs"
                        / self.config.task_id
                        / "root-data"
                    )
                    if not staged_data.is_dir():
                        shutil.copytree(source_data, staged_data, symlinks=False)
                    value["sandbox"]["input_paths"] = {
                        "/root/data": str(staged_data),
                    }
            if role in {"terminal_solver", "terminal_verifier"} and self.config.harbor_artifact_root:
                task_toml = self.config.problem_dir / "task.toml"
                if task_toml.is_file():
                    from ..integrations.terminal_bench.harbor import (
                        load_harbor_artifact_specs,
                    )

                    value["sandbox"]["artifact_paths"] = list(
                        spec.path
                        for spec in load_harbor_artifact_specs(self.config.problem_dir)
                        if spec.service is None
                    )
                    value["sandbox"]["artifact_export_root"] = str(
                        self.config.harbor_artifact_root / "fmjob-agent"
                    )
        elif self.config.agent_uid is not None and self.config.agent_gid is not None:
            value["sandbox"] = {
                "type": "local",
                "run_as_uid": self.config.agent_uid,
                "run_as_gid": self.config.agent_gid,
                "prepare_root_owner": True,
            }
        if model:
            value["model"] = model
        if self.config.agent_binary:
            value["binary"] = self.config.agent_binary
        if self.config.agent_python_binary:
            value["python_binary"] = self.config.agent_python_binary
        if self.config.max_turns is not None:
            value["max_turns"] = self.config.max_turns
        if role == "idea_rank":
            if self.config.idea_rank_max_turns is not None:
                value["max_turns"] = self.config.idea_rank_max_turns
            value["timeout_sec"] = min(
                self.config.agent_timeout_sec,
                self.config.idea_rank_timeout_sec,
            )
        if role == "idea_judge":
            if self.config.idea_debate_max_turns is not None:
                value["max_turns"] = self.config.idea_debate_max_turns
            value["timeout_sec"] = min(
                self.config.agent_timeout_sec,
                self.config.idea_debate_timeout_sec,
            )
        if role == "experience_summary":
            value["format"] = "markdown"
            value["max_turns"] = 30
            value["timeout_sec"] = min(self.config.agent_timeout_sec, 600.0)
            # 总结发生在研究时限和评测排空之后，不能被研究阶段的截止文件取消。
            value.pop("cancel_file", None)
        return value

    def _agent_process_memory_limit_gib(self) -> float | None:
        """计算单个 CLI Agent 的 RSS 上限，避免探索命令 OOM 整个 Task Pod。"""

        if self.config.agent_process_memory_limit_gib is not None:
            return float(self.config.agent_process_memory_limit_gib)
        if self.config.agent_graph == "scimodeling_budget":
            # One persistent researcher also runs its local surrogate training.
            # It uses the task compute allocation, not a SOTA controller slice.
            memory = self.config.available_memory_gib
            return float(memory) * 0.8 if memory else None
        reserve = self.resource_envelope.get("host_memory_reserve_gib")
        if not isinstance(reserve, (int, float)) or reserve <= 0:
            return None
        # Idea、Implement 与一次冲刺 Ranking 可能重叠。只分配控制面保留内存的
        # 80%，剩余 20% 留给 Controller、CLI wrapper 和文件缓存。
        concurrent_agents = (
            2
            if self.config.agent_graph == "terminal_task"
            else self.config.max_parallel_ideas
            + self.config.max_parallel_implementations
            + int(self.config.time_aware_idea_ranking)
        )
        return max(1.0, float(reserve) * 0.8 / max(1, concurrent_agents))

    def _goal_doc(self) -> dict[str, Any]:
        """生成不重复描述领域信息的 benchmark-managed 目标。"""
        # 外部 benchmark 已经给出题面、数据和 evaluator。这里仅把 Harness 参数
        # 转成统一调度器的运行契约，不额外发明 domain/description 等任务字段。
        task_view = self.benchmark_facility.task_view()
        task_contract = (
            dict(task_view.metadata) if isinstance(task_view.metadata, dict) else {}
        )
        score_interpretation = task_contract.get("score_interpretation")
        official_metric_name = task_contract.get("primary_metric")
        if not official_metric_name and isinstance(score_interpretation, dict):
            official_metric_name = score_interpretation.get("metric")
        official_metric_direction = task_contract.get("direction")
        if not official_metric_direction and isinstance(score_interpretation, dict):
            official_metric_direction = score_interpretation.get("direction")
        target_instruction = (
            score_interpretation.get("target_instruction")
            if isinstance(score_interpretation, dict)
            else None
        )
        goal_doc = {
            "goal_id": f"harness-{self.config.task_id}",
            "goal": {
                "id": f"harness-{self.config.task_id}",
                "name": self.config.task_id,
            },
            "workflow": {"type": "benchmark_managed"},
            "objective_brief": {
                "primary_goal": str(target_instruction)
                if target_instruction
                else "根据公开题面持续改进提交，正式 evaluator 是唯一评分权威。"
            },
            "benchmark_task": {
                "type": self.config.benchmark_adapter,
                "adapter": self.config.benchmark_adapter,
                "task_id": self.config.task_id,
                "public_dir": task_view.public_path,
                "instructions": task_view.instructions,
                "contract": task_contract,
                # 这是 Famou Benchmark Facility 的公开执行限制，不修改第三方
                # Adapter 原始 contract，保证 Benchmark 与 Loop 基础设施正交。
                "execution_limits": {
                    "canonical_timeout_sec": self.config.experiment_timeout_sec,
                },
            },
            "benchmarks": [
                {
                    "name": f"{self.config.benchmark_adapter}/{self.config.task_id}",
                    "adapter": self.config.evaluator_adapter,
                    "official_metric": {
                        "name": (
                            str(official_metric_name)
                            if official_metric_name
                            else "aggregate_improvement"
                        ),
                        "direction": (
                            str(official_metric_direction)
                            if official_metric_direction
                            else "higher_is_better"
                        ),
                    },
                    "hidden_test_access": "forbidden",
                    **(
                        {"score_interpretation": score_interpretation}
                        if isinstance(score_interpretation, dict)
                        else {}
                    ),
                }
            ],
            "workers": {
                "idea": self._agent_config(role="idea"),
                "implement": self._agent_config(role="implement"),
                "experience_summary": self._agent_config(
                    role="experience_summary"
                ),
            },
            "infra": {
                "shared_experience": {
                    "cross_task_expbank_root": str(
                        self.run_dir
                        / "shared_experience_pool"
                        / "cross_task_expbank"
                    ),
                },
                "pipeline": "async",
                "concurrency": {
                    "ideas": self.config.max_parallel_ideas,
                    "implementations": self.config.max_parallel_implementations,
                    "evaluations": self.config.max_parallel_evaluations,
                },
                "resources": {
                    **self.resource_envelope,
                    "agent_process_memory_limit_gib": (
                        self._agent_process_memory_limit_gib()
                    ),
                },
                "scheduling": {
                    "search_policy": {
                        "type": "pairwise_improve",
                        "enabled": self.config.pairwise_improve_search,
                    },
                    "time_aware_idea_ranking": {
                        "enabled": self.config.time_aware_idea_ranking,
                        "trigger_remaining_sec": (
                            self.config.idea_rank_trigger_remaining_sec
                        ),
                        "judge_timeout_sec": self.config.idea_rank_timeout_sec,
                    }
                },
                **(
                    {"observability": {"pricing": dict(self.config.pricing)}}
                    if self.config.pricing is not None
                    else {}
                ),
            },
            "constraints": {
                "max_parallel_ideas": self.config.max_parallel_ideas,
                "max_parallel_implementations": self.config.max_parallel_implementations,
                "max_parallel_evaluations": self.config.max_parallel_evaluations,
                "max_wall_time_hours": self.config.max_wall_time_hours,
                "max_implement_lifetime_sec": self.config.max_implement_lifetime_sec,
                "max_implement_turns_per_actor": self.config.max_implement_turns_per_actor,
                "max_run_attempts_per_actor": self.config.max_run_attempts_per_actor,
                "max_official_evaluations_per_actor": self.config.max_official_evaluations_per_actor,
                "max_repairs_per_revision": self.config.max_repairs_per_revision,
                # 这两项事后从产物里看不出来（没 refine 时队列不留痕迹，正如
                # pairwise_improve_search 关掉时 lease 不发生），必须留档。
                "refine_after_evaluation": self.config.refine_after_evaluation,
                "max_debug_attempts_per_actor": self.config.max_debug_attempts_per_actor,
                "idea_queue_high_watermark": self.config.idea_queue_high_watermark,
                "evaluation_queue_capacity": self.config.evaluation_queue_capacity,
                "hidden_test_access": "forbidden",
            },
            "outputs": {"workspace_dir": str(self.workspace_dir)},
        }
        if self.config.time_aware_idea_ranking:
            goal_doc["workers"]["idea_rank"] = self._agent_config(
                role="idea_rank"
            )
        if self.config.idea_debate:
            goal_doc["workers"]["idea_judge"] = self._agent_config(
                role="idea_judge"
            )
            goal_doc.setdefault("infra", {}).setdefault("scheduling", {})[
                "idea_debate"
            ] = {
                "enabled": True,
                "mode": self.config.idea_debate_mode,
                "max_rounds": self.config.idea_debate_max_rounds,
                "activation": {
                    "min_elapsed_sec": self.config.idea_debate_min_elapsed_sec,
                    "min_evaluated_attempts": (
                        self.config.idea_debate_min_evaluated_attempts
                    ),
                    "allow_cross_task_only": (
                        self.config.idea_debate_allow_cross_task_only
                    ),
                },
                "emit_pair": self.config.idea_debate_emit_pair,
            }
        # 只有 benchmark 或调用方明确传入 --iterations 时才创建次数预算。
        # 默认运行由墙钟预算和队列背压结束，不人为限制正式评分次数。
        if self.config.iterations is not None:
            goal_doc["constraints"].update(
                {
                    "max_benchmark_attempts": self.config.iterations,
                    "max_evaluator_submissions": self.config.iterations,
                }
            )
        return goal_doc

    def _promote_best(self, state: dict[str, Any]) -> tuple[str | None, float | None]:
        """把排行榜最佳代码和提交恢复到 benchmark 最终工作区。"""
        leaderboard = state.get("research_state", {}).get("leaderboard", {})
        branch_id = leaderboard.get("branch_id")
        attempt_id = leaderboard.get("expbank_attempt_id")
        score = leaderboard.get("best_value")
        if not branch_id or not attempt_id:
            return None, None
        record = ExpBank(self.run_dir).read_attempt(str(attempt_id))
        code = self.run_dir / "expbank" / str(attempt_id) / "code"
        output_value = (record.get("paths") or {}).get("output")
        output = Path(str(output_value)).resolve() if output_value else None
        if not code.is_dir() or output is None or not output.exists():
            raise FileNotFoundError("best ExpBank record is missing code or output snapshot")

        # 评测期间 workspace/output 只是 canonical 临时发布区。循环结束后必须从
        # ExpBank 的最佳冻结版本恢复代码和输出，不能把“最后一次评测”当作最佳结果。
        for child in list(self.workspace_dir.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in code.iterdir():
            _replace_path(child, self.workspace_dir / child.name)
        _replace_path(output, self.workspace_dir / "output")
        atomic_write_json(
            self.controller_dir / "promoted_best.json",
            {
                "branch_id": branch_id,
                "expbank_attempt_id": attempt_id,
                "score": score,
                "code": str(code),
                "output": str(output),
                "promoted_at": now_ms(),
            },
        )
        return str(branch_id), float(score) if score is not None else None

    def _cross_task_expbank_dose(self, goal_doc: dict[str, Any]) -> dict[str, Any]:
        """记录本 Run 拿到的跨任务经验剂量。

        「开了跨任务经验库」和「Idea Agent 真能看到同领域经验」是两件事。
        2026-09-06 的 A/B 里，cellular_omics 的 4 个 run 开关是 on、快照 33 条，
        但落到 Idea Agent 手里有内容的是 0 条——而这件事直到实验结束后翻 220 个
        agent trajectory 才发现，开跑前没有任何一处记着剂量。

        这里只记**客观数量**，不记「我们替它选了哪些」：选哪几篇是 Agent 自己
        的活（它按 domain grep 索引、再打开相关的 Markdown）。真正要看的
        「它实际读了几篇」在 trajectory 里，收尾时算不了。
        """

        snapshot = self.run_dir / "shared_experience_pool" / "cross_task_expbank"
        dose: dict[str, Any] = {
            "snapshot": str(snapshot),
            "enabled": snapshot.is_dir(),
        }
        manifest = read_json(
            self.run_dir
            / "shared_experience_pool"
            / "cross_task_expbank_seed_manifest.json"
        )
        if isinstance(manifest, dict):
            dose["seeded"] = {
                key: manifest.get(key)
                for key in (
                    "published",
                    "empty_arm",
                    "by_domain",
                    "excluded_task_id",
                    "included_task_id",
                )
                if key in manifest
            }
        if not snapshot.is_dir():
            return dose
        domain = resolve_experience_domain(goal_doc)
        dose["domain"] = domain
        try:
            counts = CrossTaskExpBank(snapshot).domain_counts()
        except (OSError, ValueError):  # noqa: BLE001 - 观测项不得阻断收尾
            return dose
        dose["entries"] = sum(counts.values())
        dose["by_domain"] = counts
        only_task_id = (
            manifest.get("included_task_id") if isinstance(manifest, dict) else None
        )
        if only_task_id:
            # 同任务自身经验臂：快照里的条目按定义全落在同一个 domain，
            # same_domain 恒等于总数，用它判剂量等于没判。这条臂的剂量就是
            # 本任务自己有几条历史复盘（实测 2-9 条），阈值也得跟着降——
            # 跨任务要三条同领域才算有处理效应，自身经验有两条就已经是
            # 「上几轮我试过什么」的完整信息。
            dose["same_task_entries"] = sum(counts.values())
            dose["low_dose"] = dose["same_task_entries"] < 2
        elif domain is not None:
            same_domain = counts.get(domain, 0)
            dose["same_domain_entries"] = same_domain
            # 三条以下基本等于没有处理效应，A/B 分析时该把这些 run 标出来。
            dose["low_dose"] = same_domain < 3
        return dose

    def _failures(self) -> list[dict[str, Any]]:
        """从 ExpBank 汇总失败版本，保持旧摘要字段兼容。"""
        failures: list[dict[str, Any]] = []
        expbank_root = self.run_dir / "expbank"
        for path in sorted(expbank_root.glob("[0-9][0-9][0-9][0-9]/record.json")):
            record = read_json(path)
            if (
                isinstance(record, dict)
                and record.get("status") == LoopStatus.ExpBank.FAILED
            ):
                failures.append(
                    {
                        "attempt_id": record.get("attempt_id"),
                        "branch_id": record.get("branch_id"),
                        "error": record.get("error"),
                        "created_at": record.get("created_at"),
                    }
                )
        return failures

    def _run_final_evaluation(
        self,
        *,
        best_attempt_id: str | None,
        best_score: float | None,
    ) -> FinalizationResult | None:
        """调用 Evaluator Adapter 的可选收尾，并把设施故障降级为未知。"""

        if not best_attempt_id:
            return None
        try:
            result = self.evaluator_adapter.finalize(
                self.adapter_context,
                self.evaluation_facility,
                FinalizationRequest(
                    task_id=self.config.task_id,
                    best_attempt_id=best_attempt_id,
                    best_score=best_score,
                    run_dir=self.run_dir,
                    metadata={
                        "agent_runtime": self.config.agent_runtime,
                        "benchmark_adapter": self.config.benchmark_adapter,
                    },
                ),
            )
            if result is not None and not isinstance(result, FinalizationResult):
                raise TypeError("Evaluator Adapter finalize() 返回类型错误")
        except Exception as exc:  # noqa: BLE001 - Judge 故障不能抹掉官方数值分数
            result = FinalizationResult(
                valid=None,
                reason=f"finalization_error: {type(exc).__name__}: {exc}",
                extra={"expbank_attempt_id": best_attempt_id},
            )
        if result is None:
            return None
        atomic_write_json(
            self.controller_dir / "final_evaluation.json",
            result.to_dict(),
        )
        self.trajectory.record(
            "final_evaluation_finished",
            expbank_attempt_id=best_attempt_id,
            evaluator_adapter=self.config.evaluator_adapter,
            result=result.to_dict(),
        )
        return result

    def run(self) -> dict[str, Any]:
        """按配置选择相互独立的 Agent Graph。"""

        if self.config.agent_graph == "scimodeling_budget":
            from ..integrations.scimodelingbench.limited_gt import run_limited_gt

            try:
                with WorkspaceRunLock(self.run_dir):
                    return run_limited_gt(self)
            finally:
                self.evaluation_facility.close()
        if self.config.agent_graph == "terminal_task":
            return self._run_terminal_task()
        return self._run_sota_search()

    def _run_terminal_task(self) -> dict[str, Any]:
        """装配 TerminalTaskGraph；不进入 SOTA AsyncOrchestrator。"""

        from .terminal_task import TerminalTaskHarness, TerminalTaskHarnessConfig

        terminal_run_dir = (
            self.config.harbor_famou_dir.expanduser().resolve()
            if self.config.harbor_famou_dir is not None
            else self.run_dir
        )
        terminal_run_dir.mkdir(parents=True, exist_ok=True)
        task_agent_timeout_sec = self._task_agent_timeout_sec(self.config.problem_dir)
        # An explicit --max-wall-time-hours remains the highest-priority
        # harness override. Otherwise honor Terminal-Bench's per-task agent
        # budget, falling back to the generic CLI timeout for non-Harbor tasks.
        max_agent_wall_time_sec = int(
            (self.config.max_wall_time_hours * 60 * 60)
            if self.config.max_wall_time_hours is not None
            else task_agent_timeout_sec or self.config.agent_timeout_sec
        )
        verifier_timeout_sec = (
            self.config.verifier_planning_timeout_sec
            if self.config.verifier_planning_timeout_sec is not None
            else max_agent_wall_time_sec
        )
        solver_agent = self._agent_config(
            role="terminal_solver",
            timeout_override_sec=max_agent_wall_time_sec,
        )
        verifier_agent = self._agent_config(
            role="terminal_verifier",
            timeout_override_sec=verifier_timeout_sec,
        )
        runtime = TerminalTaskHarness(
            TerminalTaskHarnessConfig(
                task_id=self.config.task_id,
                run_dir=terminal_run_dir,
                # Harbor 模式只把 Agent-visible task view 作为初始 CFS snapshot；
                # 不把完整 task package（solution/tests）复制进 Agent workspace。
                problem_dir=self.config.problem_dir.expanduser().resolve(),
                agent_source_dir=(
                    self.config.harbor_agent_task_view.expanduser().resolve()
                    if self.config.harbor_agent_task_view is not None
                    else None
                ),
                final_workspace_dir=self.workspace_dir,
                solver_agent=solver_agent,
                verifier_agent=verifier_agent,
                max_refine_rounds=self.config.max_refine_rounds,
                max_agent_wall_time_sec=max_agent_wall_time_sec,
                candidate_verifier_mode=self.config.candidate_verifier_mode,
                official_gt_budget=int(self.config.official_gt_budget),
            ),
            agent_adapter=self.agent_adapter,
            benchmark_facility=self.benchmark_facility,
            evaluation_facility=self.evaluation_facility,
        )
        try:
            with WorkspaceRunLock(self.run_dir):
                return runtime.run()
        finally:
            self.evaluation_facility.close()

    @staticmethod
    def _task_agent_timeout_sec(problem_dir: Path) -> int | None:
        """读取 Terminal-Bench task.toml 的 [agent].timeout_sec。"""

        path = Path(problem_dir) / "task.toml"
        if not path.is_file():
            return None
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            value = raw.get("agent", {}).get("timeout_sec")
            if isinstance(value, (int, float)) and float(value) > 0:
                return int(float(value))
        except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
            # task.toml 的详细校验由 Harbor 负责；这里不因读取失败猜测一个
            # 更大的预算，回退到 Harness 自身的显式配置。
            return None
        return None

    @staticmethod
    def _task_verifier_timeout_sec(problem_dir: Path) -> float | None:
        """Read Harbor's official ``[verifier].timeout_sec`` contract."""

        path = Path(problem_dir) / "task.toml"
        if not path.is_file():
            return None
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            value = raw.get("verifier", {}).get("timeout_sec")
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)
        except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
            return None
        return None

    def _run_sota_search(self) -> dict[str, Any]:
        """使用统一异步调度器执行完整 benchmark 优化循环。"""
        goal_doc = self._goal_doc()
        state_store = ResearchState(self.run_dir)
        # 已存在状态时直接恢复队列和预算；首次运行才创建 ResearchState。
        if not state_store.path.exists():
            state_store.init(goal_doc)
        # Harness 只提供两个薄适配器。Idea/Implement、队列、并发、预算和 ExpBank
        workers = workers_from_goal(goal_doc, self.run_dir, cwd=self.run_dir)
        orchestrator = AsyncOrchestrator(
            self.run_dir,
            goal_doc,
            workers=workers,
            benchmark_facility=self.benchmark_facility,
            evaluation_facility=self.evaluation_facility,
            validity_verifier=(
                workers
                if bool(
                    (goal_doc.get("constraints") or {}).get(
                        "validity_verifier_enabled", False
                    )
                )
                and getattr(workers, "validity_verifier_agent", None) is not None
                else None
            ),
            config=OrchestratorConfig(
                # 未配置尝试上限时让墙钟预算成为主终止条件。该值只是调度
                # 周期的保险上限，在 4 小时内不会先于墙钟耗尽。
                max_ticks=(
                    max(12, self.config.iterations * 8)
                    if self.config.iterations is not None
                    else 2_147_483_647
                ),
                interval_sec=0.05,
                async_pipeline=True,
                max_parallel_ideas=self.config.max_parallel_ideas,
                max_parallel_implementations=self.config.max_parallel_implementations,
                max_parallel_evaluations=self.config.max_parallel_evaluations,
                max_wall_time_hours=self.config.max_wall_time_hours,
                max_implement_lifetime_sec=self.config.max_implement_lifetime_sec,
                max_implement_turns_per_actor=self.config.max_implement_turns_per_actor,
                max_run_attempts_per_actor=self.config.max_run_attempts_per_actor,
                max_official_evaluations_per_actor=self.config.max_official_evaluations_per_actor,
                max_repairs_per_revision=self.config.max_repairs_per_revision,
                refine_after_evaluation=self.config.refine_after_evaluation,
                max_debug_attempts_per_actor=self.config.max_debug_attempts_per_actor,
                idea_queue_high_watermark=self.config.idea_queue_high_watermark,
                evaluation_queue_capacity=self.config.evaluation_queue_capacity,
                idea_generation_enabled=self.config.idea_generation,
                idea_graph_enabled=self.config.idea_graph,
                idea_graph_version=self.config.idea_graph_version,
                time_aware_idea_ranking_enabled=(
                    self.config.time_aware_idea_ranking
                ),
                idea_rank_trigger_remaining_sec=(
                    self.config.idea_rank_trigger_remaining_sec
                ),
                idea_rank_judge_timeout_sec=self.config.idea_rank_timeout_sec,
                idea_rank_min_items=self.config.idea_rank_min_items,
                idea_debate_enabled=self.config.idea_debate,
                idea_debate_mode=self.config.idea_debate_mode,
                idea_debate_max_rounds=self.config.idea_debate_max_rounds,
                idea_debate_min_elapsed_sec=(
                    self.config.idea_debate_min_elapsed_sec
                ),
                idea_debate_min_evaluated_attempts=(
                    self.config.idea_debate_min_evaluated_attempts
                ),
                idea_debate_allow_cross_task_only=(
                    self.config.idea_debate_allow_cross_task_only
                ),
                idea_debate_emit_pair=self.config.idea_debate_emit_pair,
                validity_verifier_enabled=bool(
                    (goal_doc.get("constraints") or {}).get(
                        "validity_verifier_enabled", False
                    )
                ),
            ),
        )
        self.trajectory.record(
            "harness_started",
            task_id=self.config.task_id,
            scheduler="AsyncOrchestrator",
            max_benchmark_attempts=self.config.iterations,
            adapters={
                "agent": self.config.agent_adapter,
                "benchmark": self.config.benchmark_adapter,
                "evaluator": self.config.evaluator_adapter,
            },
            models={
                "idea": self._model_for_role("idea"),
                "implement": self._model_for_role("implement"),
                "idea_rank": (
                    self._model_for_role("idea_rank")
                    if self.config.time_aware_idea_ranking
                    else None
                ),
            },
        )

        final_evaluation: FinalizationResult | None = None
        best_attempt_id: str | None = None
        finalization_started_at: int | None = None
        finalization_finished_at: int | None = None
        try:
            state = orchestrator.run()
            research_status = state.get("research_state", {}).get("status")
            if research_status != LoopStatus.Research.STOPPED or state.get(
                "research_state", {}
            ).get("termination_reason") == "wall_time_budget_exhausted":
                # 正常完成或墙钟截止 drain 后才发布最佳版本并执行可选 finalization。
                finalization_started_at = now_ms()
                best_branch, best_score = self._promote_best(state)
                leaderboard = state.get("research_state", {}).get("leaderboard", {})
                value = leaderboard.get("expbank_attempt_id")
                best_attempt_id = str(value) if value else None
                final_evaluation = self._run_final_evaluation(
                    best_attempt_id=best_attempt_id,
                    best_score=best_score,
                )
                finalization_finished_at = now_ms()
        finally:
            # 即使调度器或最终提升抛错，也通知文件 evaluator 客户端结束，避免可信
            # worker 一直等待新请求。
            self.evaluation_facility.close()

        queues = QueueSet(self.run_dir).summary()
        # 兼容摘要中的 attempts_completed 统计的是实现队列终态；实验或评测失败详情
        # 通过 failures 和 ExpBank record 查看。
        attempts_completed = (
            queues["benchmark_attempt_queue"][LoopStatus.Queue.FINISHED.value]
            + queues["benchmark_attempt_queue"][LoopStatus.Queue.FAILED.value]
        )
        research = state.get("research_state", {})
        shutdown = (
            research.get("shutdown")
            if isinstance(research.get("shutdown"), dict)
            else {}
        )
        summary_status = _summary_status(research)
        # Agent/Benchmark/Evaluator 三类设施已经收尾后再做一次确定性汇总。
        # 原始 ledger 在运行中持续追加，摘要只是可随时重建的派生产物。
        agent_usage = ObservabilityStore(self.run_dir).write_summary()
        summary = {
            "task_id": self.config.task_id,
            # 找不到有效 Candidate 是 benchmark 结果，不是 Harness 设施故障。
            # Master stop 保持 stopped；墙钟 drain 和自然完成才归为 completed。
            "status": summary_status,
            "outcome": (
                "best_candidate_found" if best_branch else "no_valid_candidate"
            ),
            "scheduler": "AsyncOrchestrator",
            "adapters": {
                "agent": self.config.agent_adapter,
                "benchmark": self.config.benchmark_adapter,
                "evaluator": self.config.evaluator_adapter,
            },
            "models": {
                "idea": self._model_for_role("idea"),
                "implement": self._model_for_role("implement"),
                "idea_rank": (
                    self._model_for_role("idea_rank")
                    if self.config.time_aware_idea_ranking
                    else None
                ),
            },
            "max_benchmark_attempts": self.config.iterations,
            "attempts_completed": attempts_completed,
            "attempts_not_executed": queues["benchmark_attempt_queue"][
                LoopStatus.Queue.NOT_EXECUTED.value
            ],
            "best_score": best_score,
            "effective_score": (
                None
                if final_evaluation is not None
                and final_evaluation.invalidate_primary_score
                else best_score
            ),
            "best_branch": best_branch,
            "best_attempt_id": best_attempt_id,
            "final_evaluation": (
                final_evaluation.to_dict() if final_evaluation is not None else None
            ),
            "workspace": str(self.workspace_dir),
            "expbank": str(self.run_dir / "expbank"),
            "cross_task_expbank": self._cross_task_expbank_dose(goal_doc),
            "trajectory": str(self.trajectory.path),
            "agent_usage": agent_usage,
            "failures": self._failures(),
            "timing": {
                "agent_run_started_at": research.get("created_at"),
                "agent_run_finished_at": (
                    shutdown.get("research_finished_at")
                    or finalization_started_at
                ),
                "agent_wall_time_budget_hours": self.config.max_wall_time_hours,
                "research_wall_time_mode": "continuous",
                "post_deadline_evaluation_drain": True,
                "evaluation_drain_finished_at": shutdown.get(
                    "evaluation_drain_finished_at"
                ),
                "finalization_started_at": finalization_started_at,
                "finalization_finished_at": finalization_finished_at,
                "finalization_outside_agent_budget": bool(
                    self.adapter_context.options.get("finalize_evaluation")
                ),
            },
            "finished_at": now_ms(),
        }
        atomic_write_json(self.summary_path, summary)
        self.trajectory.record("harness_finished", summary=summary)
        return summary


__all__ = [
    "BenchmarkHarness",
    "HarnessConfig",
]
