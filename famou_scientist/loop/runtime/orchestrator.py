"""端到端科研循环的基础调度器。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..agents.workers import DummyWorkerSet
from ..utils import append_jsonl, atomic_write_json, new_id, now_ms, read_json
from .master_bridge import MasterBridge
from ..domain.goal import goal_query, idea_gate_enabled, workflow_type
from ..domain.resources import ResourceBroker, ResourceEnvelope, ResourceRequest
from ..domain.status import LoopStatus
from ..evaluation.evaluator import BenchmarkAdapter
from ..evaluation.experiment import ExperimentRunner, runner_from_goal
from ..execution.resources import current_gpu_free_memory_gib
from ..facilities import (
    AdapterEvaluationFacility,
    AgentFacility,
    ArtifactRef,
    BenchmarkFacility,
    CandidateRef,
    EvaluationFacility,
    EvaluationRequest,
    EvaluationResult,
    RunResult,
    RunnerBenchmarkFacility,
    ValidityVerifier,
    WorkerAgentFacility,
    validate_validity_verdict,
)
from ..search import SearchPolicy, search_policy_from_mapping
from ..storage.artifacts import ArtifactStore
from ..storage.candidates import CandidateStore
from ..storage.cross_task_expbank import (
    CrossTaskExpBank,
    achievement_level,
    experience_bank_root,
    public_task_summary,
    resolve_experience_domain,
)
from ..storage.expbank import (
    ExpBank,
    extract_per_instance_improvement,
    worst_instance_summary,
)
from ..storage.experience import ExperienceStore
from ..storage.evolution_graph import (
    DEFAULT_GRAPH_VERSION,
    GRAPH_VERSIONS,
    MULTI_PARENT_OPERATORS,
    OPERATOR_EXPLOIT,
    ROOT_ID,
    EvolutionGraphStore,
    make_idea_graph,
    read_parents,
    validate_operator,
)
from ..storage.queues import JsonlQueue, QueueSet
from ..storage.state import ResearchState
from ..storage.workspace import WorkspaceRunLock
from .control import ControlEventStore
from .implement_actor import ImplementActorStore

#: Idea 的 `operator`/`parents` 非法时，带着原因退回让 Agent 重提的最多次数。
#: 到上限仍非法就丢弃这条提案——宿主不替 agent 改算子（理由见
#: `docs/design/AGENT_VIEW_CN.md` §3.3）。取 3 而不是 1：改一个填错的父节点编号
#: 对 Agent 是件容易事，多给两次机会的代价只是几个回合，比丢掉一条真实提案便宜。
OPERATOR_RETRY_LIMIT = 3


@dataclass
class OrchestratorConfig:
    """保存调度器运行配置。"""
    min_ideas: int = 1
    max_ticks: int = 5
    interval_sec: float = 0.1
    async_pipeline: bool = False
    max_parallel_ideas: int = 1
    max_parallel_implementations: int | None = None
    max_parallel_evaluations: int = 1
    max_experiment_retries: int = 0
    max_wall_time_hours: float | None = None
    max_implement_lifetime_sec: float = 14_400
    max_implement_turns_per_actor: int = 1
    max_run_attempts_per_actor: int | None = None
    max_official_evaluations_per_actor: int | None = None
    max_repairs_per_revision: int = 1
    # 评测出分之后，还让不让同一个 ImplementActor 自己接着改（refine）。
    #
    # 这是基础版的"下一步做什么"策略：不回 IdeaAgent、不看图，actor 就地续跑。
    # 演化图 v2 的全部立论是**由 agent 看着分数选 operator + parents**，所以 v2
    # 下要关掉它——关掉之后出分即终结 actor，改进必须作为一个新的 exploit 节点
    # 重新走 IdeaAgent，才会进主读数（exploit 节点的 Δ 配对）。
    #
    # 与 `pairwise_improve_search` 是两条独立的路：那个管"队列递第二个方案过来
    # 二选一"，这个管"actor 自己接着改"。两者都关，Improve 回合才真正没有。
    # 默认 True＝保持历史行为，`submit_one_click.sh` 是所有批次共用的脚本。
    refine_after_evaluation: bool = True
    # 单个方案（actor）允许被 debug 的总次数；None = 不设独立上限，沿用历史行为
    # （那时实际只受 max_run_attempts_per_actor 和墙钟约束）。
    #
    # 注意它和 max_repairs_per_revision 是两个轴，不是重复：后者限的是"同一次
    # 提交里连续修几回"，且每次 register_candidate 都会把计数清零，所以它**从来
    # 不限制总次数**。"这个方案一共 debug 了几次"以前没有任何字段答得上来。
    max_debug_attempts_per_actor: int | None = None
    idea_queue_high_watermark: int | None = None
    evaluation_queue_capacity: int | None = None
    # 关闭后完全不再调用 IdeaAgent 产出新方案，只消费队列里已有的条目。
    # 用于 resume 已结束的 Run 重跑指定 Idea：不关掉的话 IdeaAgent 会按水位
    # 继续产新方案，抢 implement 槽位并污染"只跑这几条"的比较。
    #
    # 不要用 ``--iterations N``（即 max_benchmark_attempts）代替：
    # harness 会把它同时写进 max_evaluator_submissions，把评测预算一起掐死，
    # 一次工程失败就再无重试机会。
    idea_generation_enabled: bool = True
    # Idea 图（IDEAS.md + ideas/*.json 的 idea→idea 派生边）在 benchmark 工作流里
    # 是否生效。开放科研路径一直启用，与该开关无关；benchmark 路径历史上被显式
    # 排除，故默认保持关闭，避免静默改变既有批次的行为。见 _idea_graph_active。
    idea_graph_enabled: bool = False
    # Idea 图的 schema 版本。v1 = `IDEAS.md` + `ideas/*.json`（上一批 A/B 的对照臂
    # 配置，必须能一键回去）；v2 = `GRAPH.md` + `graph/*.json` 的方案演化 DAG，带
    # 分数、唯一身份和多父。**默认必须是 v1**：submit_one_click.sh 是所有历史批次
    # 共用的提交脚本，默认开 v2 会静默改变后续一切 run 的行为。
    # 设计文档：docs/design/EVOLUTION_GRAPH_V2_CN.md
    idea_graph_version: str = DEFAULT_GRAPH_VERSION
    time_aware_idea_ranking_enabled: bool = False
    idea_rank_trigger_remaining_sec: float = 3_600
    # 冲刺阶段只做一次排序。实测 Judge 中位耗时 270 秒、p90 顶到旧的 600 秒
    # 上限并被 SIGTERM（121 次调用中 21% 超时），故放宽到 30 分钟。
    idea_rank_judge_timeout_sec: float = 1_800
    # 少于该条数不触发排序：两条之间的先后取舍不值得一次 Judge 调用。
    idea_rank_min_items: int = 3
    # 剩余时间低于该值不再启动排序。按典型完成时间（中位 270s、p90 570s）加
    # 余量设定，而非按超时上限——否则排序窗口会被压缩到很窄的一段。
    idea_rank_min_remaining_sec: float = 900
    # Idea Judge 辩论环节。与冲刺期排序对称：那个是"剩余 ≤1h 才开"，
    # 这个是"已跑 ≥1h 才开"。默认关闭，由 goal 显式打开。
    idea_debate_enabled: bool = False
    # respond：Judge 只给反馈，由 Idea Agent 自己回应（保留作者权，防同质化）。
    # rewrite：Judge 直接给出改写后的 Idea。
    idea_debate_mode: str = "respond"
    idea_debate_max_rounds: int = 1
    # 兜底闸门：至少跑满这么久。实测每个 Run 中位产 11 条 Idea，其中 8 条落在
    # 头 1 小时，所以这个闸门本身会挡掉约 66% 的 Idea。
    idea_debate_min_elapsed_sec: float = 3_600
    # 主闸门：至少有这么多条 in-task 评测结果，否则 Judge 无据可批。实测开跑
    # 45 分钟时 65/79 个 Run 一条结果都没有，60 分钟时仍有 54/79 为零，
    # 所以纯时间闸门不够，必须同时看证据。
    idea_debate_min_evaluated_attempts: int = 1
    # 打开后允许在 in-task 证据出现前就启动，此时 Judge 只能引用跨任务经验。
    idea_debate_allow_cross_task_only: bool = False
    # 辩论过的 Idea 相对普通新 Idea 的优先级加成。0 表示不插队（配合
    # queue_ordering=equal 可以把"插队"这一项单独关掉做对照）。
    idea_debate_priority_bonus: int = 1
    # 配对模式：内容真被改过时，原版与改写版都入队，构成同 Run 内的配对样本。
    # 两条同优先级、相邻消费，用于直接测量"辩论让 Idea 变好了吗"。
    idea_debate_emit_pair: bool = False
    # 待实现队列消费顺序：weighted = 按 priority 降序、同级 FIFO；equal = 纯 FIFO。
    queue_ordering: str = "weighted"
    # Candidate validity checking is opt-in; the default SOTA loop remains unchanged.
    validity_verifier_enabled: bool = False

    def __post_init__(self) -> None:
        # 非正数并发度会导致执行器运行时失败；这里回退到安全的串行设置。
        """在初始化后校验并归一化配置。"""
        for attr in (
            "max_parallel_ideas",
            "max_parallel_evaluations",
        ):
            try:
                setattr(self, attr, max(1, int(getattr(self, attr) or 1)))
            except (TypeError, ValueError):
                setattr(self, attr, 1)
        if self.max_parallel_implementations is None:
            self.max_parallel_implementations = self.max_parallel_evaluations
        else:
            try:
                self.max_parallel_implementations = max(
                    1,
                    int(self.max_parallel_implementations or 1),
                )
            except (TypeError, ValueError):
                self.max_parallel_implementations = self.max_parallel_evaluations
        try:
            self.max_experiment_retries = max(0, int(self.max_experiment_retries or 0))
        except (TypeError, ValueError):
            self.max_experiment_retries = 0
        if self.max_wall_time_hours is not None:
            try:
                self.max_wall_time_hours = max(0.0, float(self.max_wall_time_hours))
            except (TypeError, ValueError):
                self.max_wall_time_hours = None
        try:
            self.max_implement_lifetime_sec = max(
                1.0, float(self.max_implement_lifetime_sec or 1)
            )
        except (TypeError, ValueError):
            self.max_implement_lifetime_sec = 14_400
        for attr, minimum in (
            ("max_implement_turns_per_actor", 1),
            ("max_repairs_per_revision", 0),
        ):
            try:
                setattr(self, attr, max(minimum, int(getattr(self, attr) or 0)))
            except (TypeError, ValueError):
                setattr(self, attr, minimum)
        if self.max_run_attempts_per_actor is None:
            self.max_run_attempts_per_actor = self.max_implement_turns_per_actor
        else:
            self.max_run_attempts_per_actor = max(
                1, int(self.max_run_attempts_per_actor)
            )
        if self.max_official_evaluations_per_actor is not None:
            self.max_official_evaluations_per_actor = max(
                0, int(self.max_official_evaluations_per_actor)
            )
        if self.max_debug_attempts_per_actor is not None:
            # 0 是合法取值，意思是「一次 debug 都不给」，与 None（不设上限）不同。
            try:
                self.max_debug_attempts_per_actor = max(
                    0, int(self.max_debug_attempts_per_actor)
                )
            except (TypeError, ValueError):
                self.max_debug_attempts_per_actor = None
        self.refine_after_evaluation = bool(self.refine_after_evaluation)
        if self.idea_queue_high_watermark is None:
            self.idea_queue_high_watermark = self.max_parallel_ideas
        else:
            self.idea_queue_high_watermark = max(1, int(self.idea_queue_high_watermark))
        if self.evaluation_queue_capacity is None:
            self.evaluation_queue_capacity = self.max_parallel_evaluations
        else:
            self.evaluation_queue_capacity = max(
                1,
                int(self.evaluation_queue_capacity),
            )
        self.time_aware_idea_ranking_enabled = bool(
            self.time_aware_idea_ranking_enabled
        )
        try:
            self.idea_rank_trigger_remaining_sec = max(
                1.0,
                float(self.idea_rank_trigger_remaining_sec),
            )
        except (TypeError, ValueError):
            self.idea_rank_trigger_remaining_sec = 3_600
        try:
            self.idea_rank_judge_timeout_sec = max(
                1.0,
                float(self.idea_rank_judge_timeout_sec),
            )
        except (TypeError, ValueError):
            self.idea_rank_judge_timeout_sec = 1_800
        try:
            self.idea_rank_min_items = max(2, int(self.idea_rank_min_items))
        except (TypeError, ValueError):
            self.idea_rank_min_items = 3
        try:
            self.idea_rank_min_remaining_sec = max(
                60.0,
                float(self.idea_rank_min_remaining_sec),
            )
        except (TypeError, ValueError):
            self.idea_rank_min_remaining_sec = 900
        self.idea_debate_enabled = bool(self.idea_debate_enabled)
        mode = str(self.idea_debate_mode or "").strip().lower()
        # 未知模式一律回落到 respond：让 Judge 直接改写 Idea 的影响更大，
        # 不能因为配置写错而被静默启用。
        self.idea_debate_mode = mode if mode in {"respond", "rewrite"} else "respond"
        try:
            self.idea_debate_max_rounds = max(1, int(self.idea_debate_max_rounds))
        except (TypeError, ValueError):
            self.idea_debate_max_rounds = 1
        try:
            self.idea_debate_min_elapsed_sec = max(
                0.0,
                float(self.idea_debate_min_elapsed_sec),
            )
        except (TypeError, ValueError):
            self.idea_debate_min_elapsed_sec = 3_600
        try:
            self.idea_debate_min_evaluated_attempts = max(
                0,
                int(self.idea_debate_min_evaluated_attempts),
            )
        except (TypeError, ValueError):
            self.idea_debate_min_evaluated_attempts = 1
        self.idea_debate_allow_cross_task_only = bool(
            self.idea_debate_allow_cross_task_only
        )
        self.idea_debate_emit_pair = bool(self.idea_debate_emit_pair)
        try:
            self.idea_debate_priority_bonus = max(
                0, int(self.idea_debate_priority_bonus)
            )
        except (TypeError, ValueError):
            self.idea_debate_priority_bonus = 1
        ordering = str(self.queue_ordering or "").strip().lower()
        # 未知取值回落到既有行为，不因配置写错而静默改变消费顺序。
        self.queue_ordering = ordering if ordering in {"weighted", "equal"} else "weighted"
        version = str(self.idea_graph_version or "").strip().lower()
        # 同上：宿主层（HarnessConfig）对非法版本抛错，orchestrator 层钳到默认。
        # 图是上下文层，不该因为版本串写错而让一个 4 小时的作业起不来。
        self.idea_graph_version = (
            version if version in GRAPH_VERSIONS else DEFAULT_GRAPH_VERSION
        )


class Orchestrator:
    """协调想法、实现、实验、评测和分析阶段。"""
    def __init__(
        self,
        workspace: str | Path,
        goal_doc: dict[str, Any],
        *,
        evaluator: BenchmarkAdapter | None = None,
        workers=None,
        experiment_runner: ExperimentRunner | None = None,
        agent_facility: AgentFacility | None = None,
        benchmark_facility: BenchmarkFacility | None = None,
        evaluation_facility: EvaluationFacility | None = None,
        validity_verifier: ValidityVerifier | None = None,
        search_policy: SearchPolicy | None = None,
        config: OrchestratorConfig | None = None,
    ) -> None:
        """初始化调度器，并把旧组件归一化为三类 Facility。"""
        self.workspace = Path(workspace)
        self.goal_doc = goal_doc
        legacy_workers = workers or DummyWorkerSet()
        legacy_runner = experiment_runner
        if legacy_runner is None and benchmark_facility is None:
            legacy_runner = runner_from_goal(goal_doc, self.workspace)
        if benchmark_facility is None and evaluator is None:
            raise ValueError("必须提供 benchmark_facility，或提供兼容 evaluator")
        if evaluation_facility is None and evaluator is None:
            raise ValueError("必须提供 evaluation_facility，或提供兼容 evaluator")
        task = goal_doc.get("benchmark_task")
        task_id = (
            str(task.get("task_id") or task.get("id") or "task")
            if isinstance(task, dict)
            else "task"
        )
        self._legacy_agent_binding = agent_facility is None
        self._legacy_benchmark_binding = benchmark_facility is None
        self._legacy_evaluation_binding = evaluation_facility is None
        self.agent_facility = agent_facility or WorkerAgentFacility(legacy_workers)
        self.benchmark_facility = benchmark_facility or RunnerBenchmarkFacility(
            legacy_runner,
            evaluator,
            task_id=task_id,
        )
        self.evaluation_facility = evaluation_facility or AdapterEvaluationFacility(
            evaluator
        )
        self.validity_verifier = validity_verifier
        # 旧属性只为外部调用方的兼容读取保留；Core 后续不再通过它们执行工作。
        self._workers = legacy_workers
        self._experiment_runner = legacy_runner
        self._evaluator = evaluator
        self.config = config or OrchestratorConfig()
        if self.config.validity_verifier_enabled and self.validity_verifier is None:
            raise ValueError(
                "validity_verifier_enabled=True 时必须注入 validity_verifier"
            )
        self.workflow_type = workflow_type(goal_doc)
        self.benchmark_managed = self.workflow_type == "benchmark_managed"
        infra = goal_doc.get("infra") if isinstance(goal_doc.get("infra"), dict) else {}
        scheduling = (
            infra.get("scheduling")
            if isinstance(infra.get("scheduling"), dict)
            else {}
        )
        search_config = (
            scheduling.get("search_policy")
            if isinstance(scheduling.get("search_policy"), dict)
            else {}
        )
        # Search Policy 通过协议注入。Controller 不理解 refine/switch/fuse 的
        # 具体选择规则，只在派发和结果收口两个稳定接缝调用它。
        self.search_policy = search_policy or search_policy_from_mapping(
            search_config
        )
        resources = (
            infra.get("resources")
            if isinstance(infra.get("resources"), dict)
            else {}
        )
        self.resource_declarations_required = bool(
            resources.get("resource_declarations_required", False)
        )
        resource_envelope = ResourceEnvelope.from_mapping(resources)
        self.resource_broker = ResourceBroker(
            resource_envelope,
            gpu_free_memory_provider=(
                current_gpu_free_memory_gib
                if resource_envelope.gpu_devices
                and bool(resources.get("dynamic_gpu_memory_admission", False))
                else None
            ),
        )
        # Gate 属于 research 图中的可选节点。默认信任 IdeaAgent 的 instruction，
        # 只有 Goal Contract 显式开启时才增加同步 LLM Judge。
        self.idea_gate_enabled = (
            not self.benchmark_managed and idea_gate_enabled(goal_doc)
        )
        self.state_store = ResearchState(self.workspace)
        self.queues = QueueSet(self.workspace, ordering=self.config.queue_ordering)
        self.artifacts = ArtifactStore(self.workspace)
        self.candidates = CandidateStore(self.workspace)
        self.actors = ImplementActorStore(self.workspace)
        self.expbank = ExpBank(self.workspace)
        self.idea_graph = make_idea_graph(
            self.workspace, version=self.config.idea_graph_version
        )
        lineage = goal_doc.get("lineage") if isinstance(goal_doc.get("lineage"), dict) else {}
        experience_sources = lineage.get("experience_sources")
        self.experience = ExperienceStore(
            self.workspace,
            source_roots=experience_sources if isinstance(experience_sources, list) else None,
        )
        # 控制总线在两种工作流中都存在；benchmark-managed 不启用 Master Agent，
        # 但仍允许外部运维通过同一总线 pause/stop/resume。
        self.control_events = ControlEventStore(self.workspace)
        self.master_bridge = (
            None
            if self.benchmark_managed
            else MasterBridge(self.workspace, control_events=self.control_events)
        )
        self.log_path = self.workspace / "logs" / "orchestrator.log"

    @staticmethod
    def _experience_text(value: Any) -> str:
        """从 Idea 或结论对象中提取适合摘要展示的文本。"""

        if isinstance(value, dict):
            for key in ("summary", "title", "claim", "mechanism", "description"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value or "").strip()

    @staticmethod
    def _finite_attempt_score(record: dict[str, Any]) -> float | None:
        """读取可信完整 ExpBank 分数，拒绝无效或不完整候选。"""

        evaluation = record.get("evaluation")
        if not isinstance(evaluation, dict) or evaluation.get("valid") is not True:
            return None
        extra = evaluation.get("extra")
        if isinstance(extra, dict):
            failures = extra.get("primary_instance_failures")
            if isinstance(failures, list) and failures:
                return None
            if Orchestrator._contains_nonempty_error(extra.get("raw_scores")):
                return None

        value = record.get("score")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        score = float(value)
        return score if math.isfinite(score) else None

    @staticmethod
    def _contains_nonempty_error(value: Any) -> bool:
        """识别旧 evaluator 只返回 aggregate、但实例块含错误的记录。"""

        if isinstance(value, dict):
            return any(
                (str(key).lower() == "error" and item not in (None, "", [], {}))
                or Orchestrator._contains_nonempty_error(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(Orchestrator._contains_nonempty_error(item) for item in value)
        return False

    @staticmethod
    def _achievement_level(best_score: float | None) -> str:
        """把最佳分数映射成 NatureBench 公开成绩档位。

        实现在 ``storage.cross_task_expbank.achievement_level``——目录投影侧要用
        同一个口径把旧记录的 ``result`` 派生出来，两处各写一份必然会漂。
        阈值同时与 ``benchmark.py`` 的 ``score_interpretation`` 同源，那是下发给
        Idea Agent 的公开口径。
        """

        return achievement_level(best_score)

    def _experience_summary_context(
        self,
        state: dict[str, Any],
        attempts: list[dict[str, Any]],
        domain: str,
    ) -> dict[str, Any]:
        """构造只含公开 ExpBank 证据的收尾总结上下文。

        这里给的是**目录和路径，不是内容**。复盘节点是带文件工具的 CLI Agent，
        ``expbank/`` 是 world-readable 的 Agent 可见区（``trusted/`` 是
        ``drwx------ root``，Agent 以非 root 身份跑，读不到），所以直接给绝对
        路径让它按需取证即可——与 Idea Agent 拿 ``expbank_dir`` 的方式一致。

        此前这里返回全量 ``attempts``，被 wrapper 原样内联进提示词正文，实测
        286 KB ~ 1.16 MB，且同一份数据在 ``public/context.json`` 里已经有一份。
        它在 2026-08 造成 24 次 ``Prompt is too long``——而且是按 attempt 数
        选择性触发，跑得越多、经验越厚的 Run 越复盘不出来。
        """

        research = state.get("research_state")
        research = research if isinstance(research, dict) else {}
        goal = self.goal_doc.get("goal")
        goal = goal if isinstance(goal, dict) else {}
        expbank_dir = self.workspace / "expbank"
        return {
            "goal_name": str(goal.get("name") or self.goal_doc.get("name") or ""),
            "domain": domain,
            "workflow_type": self.workflow_type,
            "research_state": {
                "status": research.get("status"),
                "counters": research.get("counters") or {},
                "leaderboard": research.get("leaderboard") or {},
                "shutdown": research.get("shutdown") or {},
            },
            # 只给 Agent 可见区的路径，不给 trusted 目录。
            "expbank_dir": str(expbank_dir),
            "expbank_index": str(expbank_dir / "INDEX.md"),
            "attempt_index": self._attempt_index(attempts),
            "evidence_policy": {
                "allowed": "公开 Goal、ExpBank、公开 evaluator 结果",
                "forbidden": "hidden test、GT、私有 evaluator、凭据和 endpoint",
            },
        }

    def _attempt_index(self, attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把 attempt 压成一行一条的目录，完整记录留在文件里按需读。"""

        expbank_dir = self.workspace / "expbank"
        index: list[dict[str, Any]] = []
        for record in attempts:
            attempt_id = record.get("attempt_id")
            if not attempt_id:
                continue
            idea = record.get("idea")
            idea = idea if isinstance(idea, dict) else {}
            index.append(
                {
                    "attempt_id": attempt_id,
                    "status": record.get("status"),
                    "score": self._finite_attempt_score(record),
                    "idea_title": str(idea.get("title") or ""),
                    "parent_attempt_id": record.get("parent_attempt_id"),
                    "record_path": str(expbank_dir / str(attempt_id) / "record.json"),
                    "summary_path": str(expbank_dir / str(attempt_id) / "SUMMARY.md"),
                }
            )
        return index

    def _idea_experience(self, *, top_k: int) -> list[dict[str, Any]]:
        """只给当前任务的经验。跨任务经验走目录，不进载荷。

        以前这里还会把「同领域最多 20 条」跨任务经验塞进载荷（``search()``
        选、``read_summary()`` 读）。删掉的理由：

        1. **那 20 条是自己发明的窗口，而且正是出错的地方。** 按写入时间排序取
           前 20，导致同一任务的多次重跑连成一片；2026-09-06 那批 A/B 里
           cellular_omics 有 33 条同领域条目、其中有内容的 3 条，按时间排的前
           20 条里一条都没有——那 4 个任务的处理臂等价于对照臂。
        2. **筛选本来就是 Agent 的活。** Idea Agent 是带 Read/Grep/Glob 的 CLI
           Agent，库就在它工作区里：外层 ``index.jsonl`` + 六个领域目录，每个
           目录下一篇篇演化总结。按自己的 domain grep 一下索引（当前最大领域
           17.8 KB）就能挑，不需要调度器代它决定看哪 20 条。
        3. **唯一不能交给 Agent 的是自任务屏蔽，而那件事不在这里做。**
           ``seed_run`` 拷快照时会把本任务的条目从索引删掉、**并物理删除对应
           的 .md**，所以 Agent 绕过索引直接 ``ls`` 也读不到自己的历史解法。

        Agent 拿到的是目录路径（``cross_task_expbank_dir``），提示词 v5 说明结构。
        """

        return self.experience.search(goal_query(self.goal_doc), top_k=top_k)

    def _cross_task_expbank(self) -> CrossTaskExpBank:
        """Resolve the shared bank, honoring a harness-provided persistent snapshot."""

        infra = self.goal_doc.get("infra")
        infra = infra if isinstance(infra, dict) else {}
        shared = infra.get("shared_experience")
        shared = shared if isinstance(shared, dict) else {}
        configured = shared.get("cross_task_expbank_root")
        if configured:
            return CrossTaskExpBank(str(configured))
        return CrossTaskExpBank(experience_bank_root(self.workspace))

    def _public_task_summary(self) -> str | None:
        """从公开题面提取一句话任务说明，供别的任务在经验目录里做相关性判断。

        解析实现在 ``storage.cross_task_expbank.public_task_summary``——存量记录
        的回填脚本要用同一套解析，两处各写一份必然会漂。
        """

        task = self.goal_doc.get("benchmark_task")
        task = task if isinstance(task, dict) else {}
        return public_task_summary(task.get("public_dir"))

    def _base_experience_summary(
        self,
        state: dict[str, Any],
        attempts: list[dict[str, Any]],
        domain: str,
    ) -> dict[str, Any]:
        """从 ExpBank 构造不依赖 LLM 的可追溯基础总结。"""

        scored = [
            (score, record)
            for record in attempts
            if (score := self._finite_attempt_score(record)) is not None
        ]
        best_score, best = max(scored, key=lambda item: item[0]) if scored else (None, {})
        successful: list[str] = []
        failed: list[str] = []
        refinements: list[str] = []
        for record in attempts:
            attempt_id = str(record.get("attempt_id") or "unknown")
            idea_text = self._experience_text(record.get("idea")) or "未命名方案"
            score = self._finite_attempt_score(record)
            if score is not None:
                successful.append(f"{attempt_id}: {idea_text}; score={score:.6g}")
            error = record.get("error") or record.get("failure")
            if error:
                failed.append(
                    f"{attempt_id}: {idea_text}; {self._experience_text(error)}"
                )
            parent = record.get("parent_attempt_id")
            if parent:
                refinements.append(f"{attempt_id} 基于 {parent}: {idea_text}")

        task = self.goal_doc.get("benchmark_task")
        task = task if isinstance(task, dict) else {}
        goal = self.goal_doc.get("goal")
        goal = goal if isinstance(goal, dict) else {}
        best_idea = self._experience_text(best.get("idea")) if best else ""
        conclusion = self._experience_text(best.get("conclusion")) if best else ""
        method_summary = conclusion or best_idea or "尚未形成具有有限正式分数的候选。"
        research = state.get("research_state")
        research = research if isinstance(research, dict) else {}
        return {
            "task_id": str(task.get("task_id") or goal.get("id") or ""),
            "goal_id": str(self.goal_doc.get("goal_id") or goal.get("id") or ""),
            "run_id": self.workspace.name,
            # 系统审计字段：保留完整 Run 和任务产物目录，不进入 Agent-facing projection。
            "source_run_dir": str(self.workspace.resolve()),
            "task_output_dir": str((self.workspace / "workspace" / "output").resolve()),
            "domain": domain,
            "task_summary": self._public_task_summary(),
            "result": self._achievement_level(best_score),
            # Loop 自身的生命周期状态与「这个 Run 打到了什么水平」是两件事，
            # 分开存：前者只做审计，后者才进 Agent-facing 目录。
            "run_status": str(research.get("status") or "unknown"),
            "attempt_count": len(attempts),
            "best_attempt_id": best.get("attempt_id") if best else None,
            "best_score": best_score,
            "method_summary": method_summary,
            "successful_ideas": successful,
            "failed_ideas": failed,
            "refine_summary": refinements,
            "evidence_refs": [
                f"expbank/{record.get('attempt_id')}/record.json"
                for record in attempts
                if record.get("attempt_id")
            ],
            "created_at": now_ms(),
        }

    @staticmethod
    def _merge_experience_summary(
        base: dict[str, Any],
        agent_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """只接受总结 schema 中的公开字段，保留调度器确定的标识和分数。"""

        merged = dict(base)
        scalar_fields = ("method_summary", "evolution_markdown", "evolution_summary")
        list_fields = (
            "successful_ideas",
            "failed_ideas",
            "refine_summary",
            "engineering_failures",
            "evaluator_observations",
        )
        for key in scalar_fields:
            value = agent_summary.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
        for key in list_fields:
            value = agent_summary.get(key)
            if isinstance(value, list):
                merged[key] = value
        merged["agent_summary"] = bool(agent_summary)
        return merged

    def _finalize_cross_task_experience(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """执行跨任务经验收尾，调用方负责隔离非预期存储异常。"""

        research = state.get("research_state")
        research = research if isinstance(research, dict) else {}
        if research.get("status") not in {
            LoopStatus.Research.COMPLETED,
            LoopStatus.Research.STOPPED,
            LoopStatus.Research.FAILED,
        }:
            return None
        marker_path = self.workspace / "controller" / "cross_task_experience.json"
        marker = read_json(marker_path, default={})
        if isinstance(marker, dict) and marker.get("status") == "written":
            return marker

        attempts = self.expbank.all_attempts()
        domain = resolve_experience_domain(self.goal_doc)
        if not attempts or domain is None:
            marker = {
                "status": "skipped",
                "reason": "empty_expbank" if not attempts else "unresolved_domain",
                "attempt_count": len(attempts),
                "updated_at": now_ms(),
            }
            atomic_write_json(marker_path, marker)
            return marker

        base = self._base_experience_summary(state, attempts, domain)
        context = self._experience_summary_context(state, attempts, domain)
        agent_summary: dict[str, Any] = {}
        agent_error: str | None = None
        summarize = getattr(self.agent_facility, "summarize_experience", None)
        if callable(summarize):
            try:
                value = summarize(context)
                if isinstance(value, dict):
                    agent_summary = value
                else:
                    agent_error = f"unexpected summary type: {type(value).__name__}"
            except Exception as exc:  # noqa: BLE001 - 总结失败不能破坏正式结果
                agent_error = f"{type(exc).__name__}: {exc}"
                self.log(f"cross-task experience summary failed: {agent_error}")

        summary = self._merge_experience_summary(base, agent_summary)
        # Markdown is the default Agent-facing format; legacy structured workers
        # can still return the original JSON fields through the compatibility path.
        if isinstance(agent_summary.get("evolution_markdown"), str):
            summary["evolution_markdown"] = agent_summary["evolution_markdown"].strip()
        if agent_error:
            summary["summary_agent_error"] = agent_error
        # Persist a run-local outbox before publishing. Cluster jobs commonly mount
        # only the Run directory, so a later host-side sync can still publish this
        # record even when the project-level bank is outside the job mount.
        outbox_path = self.workspace / "controller" / "cross_task_experience_record.json"
        atomic_write_json(outbox_path, summary)
        try:
            record = self._cross_task_expbank().upsert_summary(summary)
            marker = {
                "status": "written",
                "experience_id": record["experience_id"],
                "domain": record["domain"],
                "summary_path": record["summary_path"],
                "record_path": str(outbox_path),
                "agent_visible": bool(record.get("agent_visible")),
                "agent_summary": bool(agent_summary),
                "agent_error": agent_error,
                "updated_at": now_ms(),
            }
            atomic_write_json(marker_path, marker)
            self.log(
                "cross-task experience written "
                f"domain={record['domain']} id={record['experience_id']}"
            )
            return marker
        except Exception as exc:  # noqa: BLE001 - 经验库故障不改变任务退出码
            marker = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "updated_at": now_ms(),
            }
            atomic_write_json(marker_path, marker)
            self.log(f"cross-task experience write failed: {marker['error']}")
            return marker

    def finalize_cross_task_experience(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """安全写入跨任务经验；任何失败都不改变主 Loop 结果。"""

        try:
            return self._finalize_cross_task_experience(state)
        except Exception as exc:  # noqa: BLE001 - 收尾异常不得改变 benchmark 结果
            marker = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "updated_at": now_ms(),
            }
            try:
                atomic_write_json(
                    self.workspace / "controller" / "cross_task_experience.json",
                    marker,
                )
            except Exception:  # noqa: BLE001 - 审计盘故障同样不能覆盖主任务结果
                pass
            self.log(f"cross-task experience finalize failed: {marker['error']}")
            return marker

    def _research_deadline_path(self) -> Path:
        """返回非特权 Agent 可观察、但不可写入的研究截止信号路径。"""

        signal_dir = self.workspace / "agent_control"
        signal_dir.mkdir(parents=True, exist_ok=True)
        signal_dir.chmod(0o755)
        return signal_dir / "research_deadline_reached.json"

    def _research_stop_path(self) -> Path:
        """返回任务级 stop 取消信号路径。"""

        signal_dir = self.workspace / "agent_control"
        signal_dir.mkdir(parents=True, exist_ok=True)
        signal_dir.chmod(0o755)
        return signal_dir / "research_stop_requested.json"

    def _signal_user_stop(self, *, reason: str) -> None:
        """通知 Agent、Candidate runner 和 Evaluator 终止当前任务。"""

        payload = {"reason": reason, "created_at": now_ms()}
        atomic_write_json(self._research_stop_path(), payload)
        # 现有 Agent 配置使用该公共路径观察研究级取消；保留文件名兼容性，
        # payload.reason 用于区分 wall-time 截止和控制面 stop。
        atomic_write_json(self._research_deadline_path(), payload)

    def _normalize_resource_request(
        self,
        value: Any,
        *,
        require_explicit: bool | None = None,
    ) -> dict[str, Any]:
        """校验并规范化 Idea 或 Candidate 的资源声明。"""

        request = ResourceRequest.from_mapping(
            value if isinstance(value, dict) else None,
            require_explicit=(
                self.resource_declarations_required
                if require_explicit is None
                else bool(require_explicit)
            ),
        )
        self.resource_broker.require_can_ever_fit(request)
        return request.to_dict()

    @property
    def workers(self) -> Any:
        """返回兼容的旧 WorkerSet。"""

        return self._workers

    @workers.setter
    def workers(self, value: Any) -> None:
        """替换旧 WorkerSet，并同步由它包装出的 Agent Facility。"""

        self._workers = value
        if getattr(self, "_legacy_agent_binding", False):
            self.agent_facility = WorkerAgentFacility(value)

    @property
    def experiment_runner(self) -> ExperimentRunner | None:
        """返回兼容的旧 ExperimentRunner。"""

        return self._experiment_runner

    @experiment_runner.setter
    def experiment_runner(self, value: ExperimentRunner) -> None:
        """替换旧 Runner，并同步兼容 Bench Facility。"""

        self._experiment_runner = value
        if getattr(self, "_legacy_benchmark_binding", False):
            self.benchmark_facility.runner = value

    @property
    def evaluator(self) -> BenchmarkAdapter | None:
        """返回兼容的旧 BenchmarkAdapter。"""

        return self._evaluator

    @evaluator.setter
    def evaluator(self, value: BenchmarkAdapter) -> None:
        """替换旧 Adapter，并同步公开与正式两个兼容 Facility。"""

        self._evaluator = value
        if getattr(self, "_legacy_benchmark_binding", False):
            self.benchmark_facility.public_adapter = value
        if getattr(self, "_legacy_evaluation_binding", False):
            self.evaluation_facility.adapter = value

    def _last_run_evidence(self, actor: dict[str, Any]) -> dict[str, Any] | None:
        """汇总上一个候选的实测运行证据，并给出可自行查看的产物目录。

        选择 refine/switch/fuse 时，Agent 需要知道自己这版究竟跑成什么样：
        是分数不够，还是根本没跑完（OOM/超时/报错）。这些事实此前散落在
        mailbox、candidate manifest 和 evidence/run.json 里，需要 Agent 自己
        拼；这里直接汇总到决策位置，并保留目录路径供深入查看。
        """

        candidate_id = str(actor.get("last_candidate_id") or "")
        if not candidate_id:
            return None
        try:
            candidate = self.candidates.read(candidate_id)
        except (OSError, ValueError, KeyError):
            return None

        evidence: dict[str, Any] = {
            "candidate_id": candidate_id,
            "status": candidate.get("status"),
        }
        if candidate.get("error"):
            evidence["error"] = candidate["error"]
        paths = candidate.get("paths")
        if isinstance(paths, Mapping):
            # 目录按 ExpBank 同构组织：code/ 是提交的实现，output/ 是本次产物，
            # evidence/run.json 是完整执行记录（含 stdout/stderr 全文）。
            evidence["paths"] = {
                key: str(value)
                for key, value in paths.items()
                if key in {"code", "output", "evidence"} and value
            }

        run = None
        evidence_dir = (candidate.get("paths") or {}).get("evidence")
        if evidence_dir:
            run_path = Path(str(evidence_dir)) / "run.json"
            if run_path.is_file():
                try:
                    run = json.loads(run_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    run = None
        if isinstance(run, Mapping):
            for key in (
                "returncode",
                "timed_out",
                "duration_ms",
                "observed_memory_bytes",
                "memory_limit_bytes",
                "memory_limit_exceeded",
                "memory_over_request",
                "cuda_out_of_memory",
                "termination_reason",
                "expected_runtime_sec",
                "error_code",
            ):
                if run.get(key) is not None:
                    evidence[key] = run[key]
        return evidence or None

    def _refine_diagnostics(
        self,
        state: dict[str, Any],
        actor: dict[str, Any],
    ) -> dict[str, Any] | None:
        """汇总本轮 refine 的量化处境，供 Agent 选择 refine/switch/fuse。

        Search Policy 只把两条 Idea 的文字描述交给 Agent，缺少"我现在多少分、
        距目标还差多少、全场最好的是哪个"这类判据。历史数据显示 refine 达标率
        随差距断崖下降（差距 ≤0.05 时 73%，>0.2 时仅 5%），但 Agent 的选择几乎
        不随差距变化。这里只给出直接观测量，不做二次加工。
        """

        metric_name, direction = self._primary_metric_spec()
        if not metric_name:
            return None
        attempts = [
            item
            for item in self.expbank.all_attempts()
            if isinstance(item.get("score"), (int, float))
        ]
        if not attempts:
            return None
        attempts.sort(key=lambda item: str(item.get("attempt_id") or ""))

        parent_id = str(actor.get("last_attempt_id") or "")
        current = next(
            (
                float(item["score"])
                for item in attempts
                if str(item.get("attempt_id") or "") == parent_id
            ),
            None,
        )
        if current is None:
            return None

        higher_is_better = direction != "lower_is_better"
        scores = [float(item["score"]) for item in attempts]
        run_best = max(scores) if higher_is_better else min(scores)
        best_attempt = next(
            (
                str(item.get("attempt_id") or "")
                for item in attempts
                if float(item["score"]) == run_best
            ),
            None,
        )

        target, target_level = self._match_target_value(state)
        diagnostics: dict[str, Any] = {
            "schema_version": 1,
            "metric": metric_name,
            "direction": direction,
            "current_score": current,
            "run_best_score": run_best,
            "run_best_attempt_id": best_attempt,
            "current_is_run_best": best_attempt == parent_id,
            "evaluated_attempts": len(attempts),
        }
        level = self._current_level(state, current)
        if level:
            diagnostics["current_level"] = level
        if target is not None:
            diagnostics["target_level"] = target_level
            diagnostics["target_score"] = target
        worst = self._worst_submetric(state, parent_id)
        if worst:
            diagnostics["worst_submetric"] = worst
        evidence = self._last_run_evidence(actor)
        if evidence:
            diagnostics["last_run"] = evidence
        return diagnostics

    def _score_levels(self, state: dict[str, Any]) -> dict[str, Any] | None:
        """定位公开评分等级定义。

        NatureBench 把它放在运行时契约里（``benchmark_contract.adapters[*]``），
        而不是 goal 文档的 ``benchmarks`` 段——两处都要找。
        """

        contract = (state.get("research_state") or {}).get("benchmark_contract")
        if isinstance(contract, dict):
            for adapter in contract.get("adapters") or []:
                if isinstance(adapter, dict) and isinstance(
                    adapter.get("score_interpretation"), dict
                ):
                    return adapter["score_interpretation"]
        task = self.goal_doc.get("benchmark_task")
        if isinstance(task, dict):
            for holder in (task, task.get("contract")):
                if isinstance(holder, dict) and isinstance(
                    holder.get("score_interpretation"), dict
                ):
                    return holder["score_interpretation"]
        for benchmark in self.goal_doc.get("benchmarks") or []:
            if isinstance(benchmark, dict) and isinstance(
                benchmark.get("score_interpretation"), dict
            ):
                return benchmark["score_interpretation"]
        return None

    @staticmethod
    def _level_lower_bound(condition: str) -> float | None:
        """从 ``0 <= value <= 0.1`` 这类条件里取下界。"""

        number = r"([-+]?\d+(?:\.\d+)?)"
        match = re.search(number + r"\s*<=?\s*value", condition)
        if match:
            return float(match.group(1))
        match = re.search(r"value\s*>=?\s*" + number, condition)
        if match:
            return float(match.group(1))
        return None

    def _match_target_value(self, state: dict[str, Any]) -> tuple[float | None, str | None]:
        """返回 (当前首要目标的分数线, 该等级名)。

        阈值取自契约声明的等级条件，不做推断；``primary_target`` 的首项即当前
        应当先达成的等级。
        """

        criteria = self._score_levels(state)
        if not criteria:
            return None, None
        levels = [item for item in criteria.get("levels") or [] if isinstance(item, dict)]
        if not levels:
            return None, None
        primary = [str(name) for name in criteria.get("primary_target") or []]
        target_name = primary[0] if primary else None
        for level in levels:
            if target_name and str(level.get("name")) != target_name:
                continue
            bound = self._level_lower_bound(str(level.get("condition") or ""))
            if bound is not None:
                return bound, str(level.get("name"))
        return None, None

    def _current_level(self, state: dict[str, Any], score: float) -> str | None:
        """按契约的等级条件判定当前分数所处等级。"""

        criteria = self._score_levels(state)
        if not criteria:
            return None
        best_name: str | None = None
        best_bound = float("-inf")
        for level in criteria.get("levels") or []:
            if not isinstance(level, dict):
                continue
            bound = self._level_lower_bound(str(level.get("condition") or ""))
            if bound is None:
                # 形如 "value < 0" 的兜底等级没有下界，作为最低档保留。
                if best_name is None:
                    best_name = str(level.get("name"))
                continue
            if score >= bound and bound >= best_bound:
                best_bound = bound
                best_name = str(level.get("name"))
        return best_name

    def _worst_submetric(
        self,
        state: dict[str, Any],
        attempt_id: str,
    ) -> dict[str, Any] | None:
        """定位当前候选最差的实例/子指标。

        主指标是各实例的算术平均，最差实例主导全局，因此它是提升杠杆最大的
        目标；但平均之后这个信息在标量分数里就看不见了。

        提取与归纳逻辑与 ExpBank 摘要共用，两处口径不允许漂移。
        """

        if not attempt_id:
            return None
        try:
            record = self.expbank.read_attempt(attempt_id)
        except (OSError, ValueError):
            return None
        per_instance = extract_per_instance_improvement(record.get("evaluation"))
        return worst_instance_summary(per_instance)

    def _implementation_queue(self) -> JsonlQueue:
        """返回当前工作流使用的实现任务队列。"""
        # benchmark 任务不需要 novelty gate，因此 Idea 直接进入专用 attempt 队列；
        # 开放科研则只有通过创新性判决的 Idea 才会出现在 IdeaSpark。
        if self.benchmark_managed:
            return self.queues.benchmark_attempt
        return self.queues.ideaspark

    def _claim_implementation_item(self) -> dict[str, Any] | None:
        """领取实现任务，并让独立 Search Policy 准备 Improve 配对。"""

        queue = self._implementation_queue()
        item = queue.pop()
        if item is None:
            return None
        return self.search_policy.prepare_dispatch(item, queue)

    #: 占用 IdeaSpark 名额的条目类型。actor_continuation 不在其中。
    NEW_IDEA_ITEM_TYPES = frozenset({"idea", "benchmark_attempt"})

    @classmethod
    def _idea_backlog(cls, queue: JsonlQueue) -> int:
        """统计尚未完成的 New Idea，租用期间仍占 IdeaSpark 容量。

        只数新 Idea。``actor_continuation`` 是 ImplementActor 的续跑请求：它不
        经过 IdeaAgent（``generate_ideas`` 与该路径无交集），对应的是一条已经拿到
        分数、正在迭代的线路，push 时本就带更高 priority（repair 3 / refine 2）。
        此前把两类混在一起数，续跑一旦堆积就会把新 Idea 生产整体卡死——实测有
        run 在 70 分钟后再未产出任何新 Idea，后续 push 全是续跑。

        被 SearchPolicy 租用（LEASED）的新 Idea 仍然计入：它尚未实现，只是被暂
        时预留给某个续跑回合作为 ``offered_idea``。
        """

        return sum(
            1
            for status in (LoopStatus.Queue.QUEUED, LoopStatus.Queue.LEASED)
            for item in queue.list(status)
            if item.get("type") in cls.NEW_IDEA_ITEM_TYPES
        )

    @staticmethod
    def _candidate_ref(branch: dict[str, Any]) -> CandidateRef:
        """把内部队列分支转换为不携带 evaluator 信息的 CandidateRef。"""

        return CandidateRef.from_payload(branch)

    @staticmethod
    def _has_candidate_source(branch: dict[str, Any]) -> bool:
        """判断 Agent 工作区是否真的包含需要冻结的候选源码。"""

        source_value = branch.get("worktree") or branch.get("method_dir")
        if not source_value:
            return False
        source = Path(str(source_value)).expanduser()
        return source.is_dir() and any(path.is_file() for path in source.rglob("*"))

    @staticmethod
    def _artifact_ref(
        run_result: dict[str, Any],
        branch: dict[str, Any],
    ) -> ArtifactRef | None:
        """从规范结果恢复 ArtifactRef，并兼容迁移前的纯路径结果。"""

        raw_ref = run_result.get("artifact_ref")
        if isinstance(raw_ref, ArtifactRef):
            return raw_ref
        if isinstance(raw_ref, dict):
            return ArtifactRef.from_dict(raw_ref)
        artifact = str(run_result.get("artifact") or branch.get("artifact") or "")
        if not artifact:
            return None
        return ArtifactRef.from_path(
            artifact,
            artifact_id=str(run_result.get("id") or new_id("artifact")),
            kind=str(run_result.get("artifact_kind") or "submission_bundle"),
            producer=str(run_result.get("source") or "benchmark_facility"),
            metadata={
                "candidate_id": branch.get("candidate_id"),
                "branch_id": branch.get("branch_id") or branch.get("id"),
            },
        )

    def _evaluation_request(
        self,
        branch: dict[str, Any],
        artifact_ref: ArtifactRef,
    ) -> EvaluationRequest:
        """构造正式评分请求，确保 evaluator 只收到受控 ArtifactRef。"""

        task = self.goal_doc.get("benchmark_task")
        task_id = (
            str(task.get("task_id") or task.get("id") or "task")
            if isinstance(task, dict)
            else "task"
        )
        attempt_id = str(
            branch.get("candidate_id")
            or branch.get("branch_id")
            or branch.get("id")
            or artifact_ref.artifact_id
        )
        return EvaluationRequest(
            task_id=task_id,
            attempt_id=attempt_id,
            artifact_ref=artifact_ref,
            metadata={
                "branch_id": branch.get("branch_id") or branch.get("id"),
                "actor_id": branch.get("actor_id"),
                "revision": branch.get("revision"),
            },
        )

    def _render_status(self, state: dict[str, Any]) -> None:
        """仅在开放式科研工作流中渲染主控摘要。"""
        if self.master_bridge is not None:
            self.master_bridge.render_status_summary(state, self.queues.summary())

    def log(self, msg: str) -> None:
        """完成当前处理流程。"""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{now_ms()}] {msg}\n")

    def _idea_graph_active(self) -> bool:
        """Idea 图对当前工作流是否生效。

        开放科研路径一直启用。benchmark 路径此前在读（_research_idea_context）与写
        （submit / link_attempt / record_implementation）四处都被 ``not
        self.benchmark_managed`` 显式排除，于是 idea→idea 的派生边整层是空的；现在
        改由 ``--idea-graph`` 控制，默认仍排除，以免改变既有批次的行为。

        四处判据共用本函数，不要在调用点各写一遍布尔表达式——跨任务经验库那次
        "三个关口靠手抄副本保持同步"的教训就是漏改一处等于整条链路半通。
        """

        return not self.benchmark_managed or self.config.idea_graph_enabled

    def _evolution_graph(self) -> EvolutionGraphStore | None:
        """v2 才有的能力（分数、唯一身份、多父、权重）统一走这一个入口。

        与 `_idea_graph_active()` 同样的纪律：判据只有一处。不要在调用点写
        ``isinstance(self.idea_graph, EvolutionGraphStore)`` 或手抄一份版本比较——
        图的写入全都裹在 ``except Exception`` 里，漏改一处不会报错，只会安静地
        少写数据，事后极难发现。

        返回 None 表示当前是 v1 臂（或图整体关闭），调用方跳过即可。
        """

        if not self._idea_graph_active():
            return None
        store = getattr(self, "idea_graph", None)
        return store if isinstance(store, EvolutionGraphStore) else None

    def _idea_runtime_payload(self) -> dict[str, Any]:
        """Idea Agent 读取图所需的同步反馈载荷。"""

        return {
            "actor_id": "idea_agent_main",
            "goal_contract_version": self._goal_contract_version(),
            "idea_graph_dir": str(self.idea_graph.expbank_root),
            "idea_graph_index": str(self.idea_graph.index_path),
            # Gate 在上一回合已经同步完成。恢复同一 CLI Session 时再次显式提供
            # 结构化反馈，避免只依赖某一具体 Agent 产品的会话恢复语义。
            # benchmark 工作流不经过 Judge，record_review 从不被调用，因此这一项
            # 在那条路径上恒为 None；保留字段是为了两条路径的 schema 一致。
            "last_review": self.idea_graph.latest_review(actor_id="idea_agent_main"),
        }

    def _research_idea_context(self) -> dict[str, Any]:
        """构造长生命周期 IdeaActor 每个回合可见的同步反馈上下文。"""

        context = dict(self.goal_doc)
        context["idea_runtime"] = self._idea_runtime_payload()
        return context

    def _goal_contract_version(self) -> str:
        """以内容摘要标识当前 Goal Contract，避免修改后仍标成初始版本。"""

        serialized = json.dumps(
            self.goal_doc,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(serialized).hexdigest()[:16]}"

    @staticmethod
    def _normalize_idea_review(
        idea: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        """把旧 Gate 和插件输出归一化为统一的四态 verdict。"""

        value = dict(review)
        verdict = str(value.get("verdict") or "").strip().lower()
        if verdict not in {"pass", "revise", "reject", "needs_evidence"}:
            verdict = "pass" if bool(value.get("accept")) else "reject"
        decision_by_verdict = {
            "pass": "accept_to_ideaspark",
            "revise": "revise_idea",
            "reject": "reject",
            "needs_evidence": "needs_evidence",
        }
        value.update(
            {
                "idea_id": idea.get("id"),
                "verdict": verdict,
                "accept": verdict == "pass",
                "decision": decision_by_verdict[verdict],
            }
        )
        for key in (
            "reasons",
            "risks",
            "similar_prior_work",
            "criterion_results",
            "actionable_revision",
            "reusable_lessons",
        ):
            if not isinstance(value.get(key), list):
                value[key] = []
        value.setdefault("confidence", "medium")
        value.setdefault("created_at", now_ms())
        return value

    def _unique_idea(self, idea: dict[str, Any]) -> dict[str, Any]:
        """避免 Agent 重复使用旧 ID 覆盖已经留存的科研证据。"""

        value = dict(idea)
        idea_id = str(value.get("id") or new_id("idea"))
        try:
            self.idea_graph.read(idea_id)
        except FileNotFoundError:
            value["id"] = idea_id
            return value
        value["proposed_id"] = idea_id
        value["id"] = new_id("idea")
        return value

    def _record_idea_gate_experience(
        self,
        idea: dict[str, Any],
        review: dict[str, Any],
        *,
        refs: list[str],
    ) -> None:
        """将未通过 Gate 的细粒度诊断写入共享经验池。"""

        self.experience.upsert(
            {
                "type": "attempted_idea",
                "summary": idea.get("title"),
                "idea_id": idea.get("id"),
                # v8 的 idea 载荷只有 `parents` 数组，直接读 `parent_idea_id`
                # 会把整条父链记成 null。`read_parents` 两种载荷都认。
                "parents": read_parents(idea),
                "outcome": {
                    "status": review.get("verdict"),
                    "reasons": list(review.get("reasons") or []),
                    "criterion_results": list(
                        review.get("criterion_results") or []
                    ),
                    "actionable_revision": list(
                        review.get("actionable_revision") or []
                    ),
                    "reusable_lessons": list(
                        review.get("reusable_lessons") or []
                    ),
                    "confidence": review.get("confidence"),
                },
                "artifact_refs": refs,
            }
        )

    def _enqueue_idea_without_gate(
        self,
        idea: dict[str, Any],
        idea_ref: str,
        *,
        inherited_refs: list[str] | None = None,
    ) -> list[str]:
        """跳过可选 Judge，将已留存的 Idea 直接送入 IdeaSpark。"""

        refs = list(inherited_refs or [])
        if idea_ref not in refs:
            refs.append(idea_ref)
        # 这里记录的是确定性的调度策略，不伪造一条 verdict=pass 的 LLM Review。
        decision_ref = self.artifacts.record_decision(
            {
                "decision": "enqueue_without_gate",
                "idea_id": idea.get("id"),
                "reason": "idea_gate_disabled",
            },
            refs=refs,
        )
        refs.append(decision_ref)
        self.idea_graph.admit_without_review(
            str(idea["id"]),
            artifact_refs=[decision_ref],
        )
        self.queues.ideaspark.push(
            idea,
            item_type="idea",
            priority=1,
            evidence_refs=refs,
        )
        return refs

    def _write_user_handoff(
        self,
        state: dict[str, Any],
        *,
        reason: str,
        next_goal: dict[str, Any] | None = None,
    ) -> None:
        """在用户终止当前 Loop 时保存后续 Loop 可读的交接记录。"""
        bridge = self.master_bridge or MasterBridge(
            self.workspace,
            control_events=self.control_events,
        )
        bridge.write_handoff(
            state,
            self.queues.summary(),
            reason=reason,
            next_goal=next_goal,
        )

    def _cancel_unfinished_after_user_stop(
        self,
        state: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        """取消全部未完成任务，但不删除队列内容和任务证据。"""
        archived = self.queues.cancel_unfinished(reason=reason)
        cancelled_candidates = self.candidates.cancel_unfinished(reason=reason)
        cancelled_actors = self.actors.cancel_unfinished(reason=reason)
        for items in archived.values():
            for item in items:
                payload = item.get("payload") or {}
                if isinstance(payload, dict) and payload.get("branch_id"):
                    self._upsert_branch_state(
                        state,
                        payload,
                        LoopStatus.Branch.CANCELLED,
                    )
        audit = state.setdefault("research_state", {}).setdefault("audit", {})
        audit.setdefault("user_stop_cancelled_items", []).append(
            {
                "ts": now_ms(),
                "reason": reason,
                "items": {
                    name: [item.get("id") for item in items]
                    for name, items in archived.items()
                    if items
                },
                "candidate_ids": [
                    item.get("candidate_id") for item in cancelled_candidates
                ],
                "actor_ids": [item.get("actor_id") for item in cancelled_actors],
            }
        )

    def _apply_control_command(
        self,
        state: dict[str, Any],
        command: dict[str, Any],
    ) -> dict[str, Any]:
        """在调度器主线程中应用一条已校验的外部命令。"""
        command_type = str(command.get("type") or "")
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        rs = state.setdefault("research_state", {})
        if command.get("goal_id") and command.get("goal_id") != rs.get("goal_id"):
            raise ValueError(
                f"命令 goal_id 与当前 Loop 不一致: {command.get('goal_id')!r}"
            )

        if command_type == "message":
            # 原始人类消息已经完整保存在 commands.jsonl；ResearchState 只保留
            # 最近一条摘要，避免状态文件无限膨胀。
            rs["last_human_message"] = payload.get("text")
            return {"action": "message_recorded"}

        if command_type == "pause":
            (self.workspace / "control" / "pause").write_text("1\n", encoding="utf-8")
            rs["status"] = LoopStatus.Research.PAUSED
            rs["termination_reason"] = payload.get("reason", "paused_by_user")
            return {"action": "pause_requested"}

        if command_type == "resume":
            if (
                rs.get("status") == LoopStatus.Research.STOPPED
                and rs.get("termination_reason") != "wall_time_budget_exhausted"
            ):
                raise ValueError("用户主动停止的 Loop 不能原地 resume")
            (self.workspace / "control" / "pause").unlink(missing_ok=True)
            (self.workspace / "control" / "stop").unlink(missing_ok=True)
            if rs.get("termination_reason") == "wall_time_budget_exhausted":
                self.resume_task(state)
                return {"action": "task_resume_requested"}
            rs["status"] = LoopStatus.Research.RUNNING
            rs["lifecycle"] = "active"
            rs.pop("termination_reason", None)
            return {"action": "resume_requested"}

        if command_type == "stop":
            reason = str(payload.get("reason") or "stopped_by_user")
            (self.workspace / "control" / "stop").write_text("1\n", encoding="utf-8")
            self._signal_user_stop(reason=reason)
            rs["status"] = LoopStatus.Research.STOPPED
            rs["lifecycle"] = "stopped_by_user"
            rs["termination_reason"] = reason
            self._cancel_unfinished_after_user_stop(state, reason=reason)
            self._write_user_handoff(state, reason=reason)
            return {"action": "stop_requested", "reason": reason}

        if command_type == "goal_change":
            if self.benchmark_managed:
                raise ValueError("benchmark_managed Loop 不接受开放式 goal_change")
            decision = str(payload.get("decision") or "")
            pending = {
                "command_id": command.get("command_id"),
                "decision": decision,
                "reason": payload.get("reason") or "human_goal_change",
                "instruction": payload.get("instruction"),
                "goal_patch": payload.get("goal_patch"),
                "next_goal": payload.get("next_goal"),
                "created_at": command.get("created_at", now_ms()),
            }
            rs["pending_goal_change"] = pending
            if decision == "continue_current":
                return {
                    "action": "defer_goal_change",
                    "message": "当前 Loop 继续运行，目标变更留给下一 Loop",
                }
            if decision == "stop_current":
                reason = "superseded_by_user_goal_change"
                (self.workspace / "control" / "stop").write_text(
                    "1\n",
                    encoding="utf-8",
                )
                self._signal_user_stop(reason=reason)
                rs["status"] = LoopStatus.Research.STOPPED
                rs["lifecycle"] = "superseded_by_user"
                rs["termination_reason"] = reason
                self._cancel_unfinished_after_user_stop(state, reason=reason)
                self._write_user_handoff(
                    state,
                    reason=reason,
                    next_goal=pending,
                )
                return {
                    "action": "stop_and_fork_requested",
                    "message": "当前 Loop 已停止接收新任务，后续 Loop 可读取 handoff.md",
                }
            raise ValueError(f"未知的 goal_change decision: {decision!r}")

        if command_type == "clarification_response":
            rs["last_clarification_response"] = {
                "request_id": payload.get("request_id"),
                "answer": payload.get("answer"),
                "created_at": command.get("created_at", now_ms()),
            }
            return {"action": "clarification_response_recorded"}

        raise ValueError(f"未知的控制命令: {command_type!r}")

    def _consume_control_commands(self, state: dict[str, Any]) -> bool:
        """消费外部命令，并把每条命令的结果写入事件回执。"""
        pending = self.control_events.pending_commands()
        if not pending:
            return False
        changed = False
        for command in pending:
            line_number = command.get("_line_number")
            try:
                result = self._apply_control_command(state, command)
                self.control_events.acknowledge(
                    command,
                    accepted=True,
                    payload=result,
                    goal_id=state.get("research_state", {}).get("goal_id"),
                )
                changed = True
                self.log(
                    f"control command applied type={command.get('type')} "
                    f"id={command.get('command_id')}"
                )
            except Exception as exc:  # noqa: BLE001 - 单条命令不能拖垮 Loop
                self.control_events.acknowledge(
                    command,
                    accepted=False,
                    error=repr(exc),
                    goal_id=state.get("research_state", {}).get("goal_id"),
                )
                state.setdefault("research_state", {}).setdefault("audit", {}).setdefault(
                    "control_command_errors", []
                ).append(
                    {
                        "command_id": command.get("command_id"),
                        "type": command.get("type"),
                        "error": repr(exc),
                        "ts": now_ms(),
                    }
                )
                # 即使命令本身被拒绝，错误审计也必须落盘；否则外部只能看到
                # command_rejected 回执，却无法从 ResearchState 还原拒绝原因。
                changed = True
            finally:
                if isinstance(line_number, int):
                    self.control_events.advance(line_number)
        if changed:
            self.state_store.save(state)
            self._render_status(state)
        return changed

    def _control_status(self) -> str | None:
        """读取当前控制状态。"""
        control = self.workspace / "control"
        if (control / "stop").exists():
            return LoopStatus.Research.STOPPED
        if (control / "pause").exists():
            return LoopStatus.Research.PAUSED
        return None

    def _preserve_external_control(self, state: dict[str, Any]) -> None:
        """避免覆盖外部并发写入的控制状态。"""
        requested = self._control_status()
        latest = None
        if requested is None:
            try:
                latest = self.state_store.load().get("research_state", {})
            except FileNotFoundError:
                latest = None
            if (
                isinstance(latest, dict)
                and latest.get("status") in LoopStatus.RESEARCH_EXTERNAL_CONTROL
            ):
                requested = latest.get("status")
        if requested not in LoopStatus.RESEARCH_EXTERNAL_CONTROL:
            return
        rs = state.setdefault("research_state", {})
        rs["status"] = requested
        if isinstance(latest, dict) and latest.get("termination_reason"):
            rs["termination_reason"] = latest["termination_reason"]

    def _upsert_branch_state(
        self,
        state: dict[str, Any],
        branch: dict[str, Any],
        status: str,
        *,
        evidence_refs: list[str] | None = None,
    ) -> None:
        """同步面向用户的分支状态台账。"""
        rs = state.setdefault("research_state", {})
        branch_id = branch.get("branch_id") or branch.get("id")
        if not branch_id:
            return
        branches = rs.setdefault("branches", [])
        entry = next((item for item in branches if item.get("branch_id") == branch_id), None)
        if entry is None:
            entry = {
                "branch_id": branch_id,
                "idea_id": branch.get("idea_id"),
                "status": status,
                "code_ref": branch.get("artifact"),
                "evidence_refs": [],
            }
            branches.append(entry)
        entry["status"] = status
        if branch.get("idea_id") is not None:
            entry["idea_id"] = branch.get("idea_id")
        if branch.get("artifact"):
            entry["code_ref"] = branch.get("artifact")
        if evidence_refs:
            entry["evidence_refs"] = list(
                dict.fromkeys((entry.get("evidence_refs") or []) + evidence_refs)
            )

    def _apply_runtime_constraint_patch(self, state: dict[str, Any]) -> None:
        """应用主控更新的运行约束。"""
        rs = state.setdefault("research_state", {})
        constraints = rs.get("goal", {}).get("constraints")
        if not isinstance(constraints, dict):
            return
        if "max_evaluator_submissions" in constraints:
            try:
                budget = rs.setdefault(
                    "evaluator_budget", {"max_submissions": None, "used_submissions": 0}
                )
                configured = constraints.get("max_evaluator_submissions")
                budget["max_submissions"] = (
                    max(0, int(configured)) if configured is not None else None
                )
            except (TypeError, ValueError):
                pass
        if "max_parallel_evaluations" in constraints:
            try:
                self.config.max_parallel_evaluations = max(
                    1, int(constraints.get("max_parallel_evaluations") or 1)
                )
            except (TypeError, ValueError):
                pass
        if "max_parallel_ideas" in constraints:
            try:
                self.config.max_parallel_ideas = max(
                    1, int(constraints.get("max_parallel_ideas") or 1)
                )
            except (TypeError, ValueError):
                pass
        if "max_parallel_implementations" in constraints:
            try:
                self.config.max_parallel_implementations = max(
                    1, int(constraints.get("max_parallel_implementations") or 1)
                )
            except (TypeError, ValueError):
                pass
        if "max_experiment_retries" in constraints:
            try:
                self.config.max_experiment_retries = max(
                    0, int(constraints.get("max_experiment_retries") or 0)
                )
            except (TypeError, ValueError):
                pass
        if "max_wall_time_hours" in constraints:
            try:
                self.config.max_wall_time_hours = max(
                    0.0, float(constraints.get("max_wall_time_hours") or 0)
                )
            except (TypeError, ValueError):
                pass
        limits = rs.setdefault("runtime_limits", {})
        limits["max_parallel_ideas"] = self.config.max_parallel_ideas
        limits["max_parallel_implementations"] = self.config.max_parallel_implementations
        limits["max_parallel_evaluations"] = self.config.max_parallel_evaluations
        limits["max_experiment_retries"] = self.config.max_experiment_retries
        limits["max_wall_time_hours"] = self.config.max_wall_time_hours

    def _sync_goal_doc_from_state(self, state: dict[str, Any]) -> None:
        """将持久化目标补丁同步到内存目标。"""
        state_goal = state.get("research_state", {}).get("goal")
        if not isinstance(state_goal, dict):
            return
        goal = self.goal_doc.setdefault("goal", {})
        if not isinstance(goal, dict):
            goal = {}
            self.goal_doc["goal"] = goal
        for key in ("name",):
            if key in state_goal:
                goal[key] = state_goal[key]
        for key in ("objective_brief", "constraints"):
            if key in state_goal:
                self.goal_doc[key] = state_goal[key]

    def _wall_time_exhausted(self, state: dict[str, Any]) -> bool:
        """判断从研究启动起连续计算的墙钟预算是否耗尽。"""
        limit = self.config.max_wall_time_hours
        if limit is None or limit <= 0:
            return False
        research = state.get("research_state", {})
        created_at = research.get("active_run_started_at") or research.get(
            "created_at"
        )
        try:
            elapsed_hours = max(0, now_ms() - int(created_at)) / 3_600_000
        except (TypeError, ValueError):
            return False
        return elapsed_hours >= limit

    def _has_resumable_work(self) -> bool:
        """判断持久化任务图中是否仍有可以继续消费的工作。"""
        active_statuses = (
            LoopStatus.Queue.QUEUED,
            LoopStatus.Queue.LEASED,
            LoopStatus.Queue.WAITING_RESOURCES,
            LoopStatus.Queue.RUNNING,
        )
        return any(
            queue.size(status) > 0
            for queue in (
                self.queues.ideaspark,
                self.queues.benchmark_attempt,
                self.queues.evaluation,
                self.queues.analyze,
            )
            for status in active_statuses
        ) or any(
            actor.get("status")
            in {
                LoopStatus.Actor.REPAIR_READY,
                LoopStatus.Actor.REFINE_READY,
            }
            for actor in self.actors.list()
        )

    def resume_task(self, state: dict[str, Any] | None = None) -> bool:
        """重新打开同一 run_dir，并恢复整个任务级工作图。"""
        state = state if state is not None else self.state_store.load()
        research = state.setdefault("research_state", {})
        status = research.get("status")
        reason = str(research.get("termination_reason") or "")
        deadline_resume = reason == "wall_time_budget_exhausted"
        inconsistent_terminal = (
            status == LoopStatus.Research.COMPLETED and self._has_resumable_work()
        )
        if not deadline_resume and not inconsistent_terminal:
            return False

        resumed = self.queues.requeue_for_resume(
            reason_prefix="research_wall_time_budget_exhausted"
        )
        resumed_items = [item for items in resumed.values() for item in items]
        for actor in self.actors.list():
            actor_reason = str(actor.get("termination_reason") or "")
            if actor_reason.startswith("research_runtime_") or actor_reason == (
                "research_wall_time_budget_exhausted"
            ):
                self.actors.update(
                    str(actor["actor_id"]),
                    status=LoopStatus.Actor.READY,
                    termination_reason=None,
                )

        audit = research.setdefault("audit", {})
        audit.setdefault("resume_events", []).append(
            {
                "ts": now_ms(),
                "reason": reason or "terminal_state_with_resumable_work",
                "requeued_item_ids": [str(item.get("id")) for item in resumed_items],
            }
        )
        research.pop("shutdown", None)
        research["status"] = LoopStatus.Research.RUNNING
        research["lifecycle"] = "active"
        research["termination_reason"] = None
        research["current_phase"] = "resuming"
        research["active_run_started_at"] = now_ms()
        self._research_deadline_path().unlink(missing_ok=True)
        self.state_store.update_queues(state, self.queues.summary())
        self.log(
            "task resume reopened durable work graph; "
            f"requeued={len(resumed_items)}"
        )
        return True

    def _remaining_wall_time_sec(
        self,
        state: dict[str, Any],
    ) -> float | None:
        """计算 Agent 研究阶段还剩多少墙钟秒数。"""

        limit = self.config.max_wall_time_hours
        if limit is None or limit <= 0:
            return None
        research = state.get("research_state", {})
        created_at = research.get("active_run_started_at") or research.get(
            "created_at"
        )
        try:
            elapsed_sec = max(0.0, (now_ms() - int(created_at)) / 1_000)
        except (TypeError, ValueError):
            return None
        return max(0.0, float(limit) * 3_600 - elapsed_sec)

    @staticmethod
    def _rankable_idea_items(queue: JsonlQueue) -> list[dict[str, Any]]:
        """返回尚未实现的普通 Idea，不把 repair/refine continuation 混入排名。"""

        return [
            item
            for item in queue.list(LoopStatus.Queue.QUEUED)
            if item.get("type") in {"idea", "benchmark_attempt"}
            and not (item.get("payload") or {}).get("continuation_reason")
        ]

    def _idea_ranking_fingerprint(
        self,
        state: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> str:
        """摘要待实现集合和最新评测事实，用于避免每个 tick 重复调用 Judge。"""

        research = state.get("research_state", {})
        leaderboard = (
            research.get("leaderboard")
            if isinstance(research.get("leaderboard"), dict)
            else {}
        )
        payload = {
            "queue_item_ids": sorted(str(item.get("id")) for item in items),
            "evaluation_finished": self.queues.evaluation.size(
                LoopStatus.Queue.FINISHED
            ),
            "evaluation_failed": self.queues.evaluation.size(
                LoopStatus.Queue.FAILED
            ),
            "leaderboard_updated_at": leaderboard.get("updated_at"),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _normalize_rank_entries(
        items: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """校验 Judge 输出覆盖全部队列项，并返回严格的全序排名。"""

        raw_entries = result.get("ranking")
        if not isinstance(raw_entries, list):
            raise ValueError("Idea Rank Judge 输出缺少 ranking 数组")
        expected = {str(item.get("id")): item for item in items}
        entries: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        seen_ranks: set[int] = set()
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValueError("Idea Rank Judge 的 ranking 条目必须是 object")
            item_id = str(raw_entry.get("queue_item_id") or "")
            if item_id not in expected or item_id in seen_items:
                raise ValueError(
                    f"Idea Rank Judge 返回未知或重复 queue_item_id: {item_id!r}"
                )
            try:
                rank = int(raw_entry.get("rank"))
            except (TypeError, ValueError):
                raise ValueError("Idea Rank Judge 的 rank 必须是正整数") from None
            if rank < 1 or rank in seen_ranks:
                raise ValueError("Idea Rank Judge 的 rank 必须从 1 开始且不得并列")
            scores = raw_entry.get("scores")
            if not isinstance(scores, dict):
                scores = {}
            normalized_scores: dict[str, int] = {}
            for name, raw_score in scores.items():
                try:
                    score = int(raw_score)
                except (TypeError, ValueError):
                    continue
                if 1 <= score <= 5:
                    normalized_scores[str(name)] = score
            entries.append(
                {
                    **raw_entry,
                    "queue_item_id": item_id,
                    "idea_id": (expected[item_id].get("payload") or {}).get("id"),
                    "rank": rank,
                    "scores": normalized_scores,
                }
            )
            seen_items.add(item_id)
            seen_ranks.add(rank)
        if seen_items != set(expected):
            missing = sorted(set(expected) - seen_items)
            raise ValueError(f"Idea Rank Judge 未覆盖队列项: {missing}")
        if seen_ranks != set(range(1, len(items) + 1)):
            raise ValueError("Idea Rank Judge 的 rank 必须形成从 1 开始的连续全序")
        entries.sort(key=lambda entry: int(entry["rank"]))
        return entries

    def _elapsed_wall_time_sec(self, state: dict[str, Any]) -> float | None:
        """计算 Agent 研究阶段已经跑了多少墙钟秒数。"""

        research = state.get("research_state", {})
        created_at = research.get("active_run_started_at") or research.get(
            "created_at"
        )
        try:
            return max(0.0, (now_ms() - int(created_at)) / 1_000)
        except (TypeError, ValueError):
            return None

    def _evaluated_attempt_count(self) -> int:
        """本 Run 已经拿到有限分数的 attempt 条数。"""

        count = 0
        for record in self.expbank.all_attempts():
            if self._finite_attempt_score(record) is not None:
                count += 1
        return count

    def _attempt_priority(self, attempt: Mapping[str, Any]) -> int:
        """计算新 Idea 入队优先级。

        只有"内容真被改过"的方案才插队。判无意见的 Idea 同样带 idea_debate
        元数据，但内容与未评审时一模一样，给它加速既无因果意义，也会稀释
        "插队是否有用"的测量。

        配对模式（``arm`` 存在）下两条臂必须同优先级：给改写版插队会让
        "原版 vs 改写版"的比较失去意义——改写版会更早被实现、更可能赶在
        研究截止前拿到分数。
        """

        debate = attempt.get("idea_debate")
        debated = (
            isinstance(debate, Mapping)
            and debate.get("outcome") in {"author_revised", "judge_rewrote"}
            and not debate.get("arm")
        )
        return 1 + (self.config.idea_debate_priority_bonus if debated else 0)

    def _idea_debate_directive(self, state: dict[str, Any]) -> dict[str, Any] | None:
        """决定本次 Idea 生产是否附带 Judge 辩论环节。

        与冲刺期排序对称但不同：排序是一次性的时间门控，辩论一旦开启就常驻，
        因此这里只记录首次开启时刻，不写一次性锁。
        """

        if not self.config.idea_debate_enabled:
            return None
        elapsed_sec = self._elapsed_wall_time_sec(state)
        evaluated = self._evaluated_attempt_count()
        # 时间是证据的糟糕代理：同样跑满 1 小时，多数 Run 一条评测结果都没有。
        # 所以证据闸门与时间闸门必须同时满足，缺一不可。
        time_ready = (
            elapsed_sec is not None
            and elapsed_sec >= self.config.idea_debate_min_elapsed_sec
        )
        evidence_ready = evaluated >= self.config.idea_debate_min_evaluated_attempts
        if evidence_ready:
            gate_mode = "in_task"
        elif self.config.idea_debate_allow_cross_task_only:
            # 没有 in-task 证据时也可以开，但 Judge 只准引用跨任务经验；
            # 提示词据此禁止它编造本 Run 的事实。
            gate_mode = "cross_task_only"
        else:
            gate_mode = None
        if not time_ready or gate_mode is None:
            return None

        research = state.setdefault("research_state", {})
        scheduler = research.setdefault("scheduler", {}).setdefault(
            "idea_debate",
            {},
        )
        if not scheduler.get("activated_at"):
            scheduler.update(
                {
                    "status": "active",
                    "activated_at": now_ms(),
                    "activated_elapsed_sec": elapsed_sec,
                    "activated_evaluated_attempts": evaluated,
                    "gate_mode": gate_mode,
                    "mode": self.config.idea_debate_mode,
                }
            )
            self.artifacts.record_decision(
                {
                    "decision": "activate_idea_debate",
                    "elapsed_sec": elapsed_sec,
                    "evaluated_attempts": evaluated,
                    "gate_mode": gate_mode,
                    "mode": self.config.idea_debate_mode,
                    "min_elapsed_sec": self.config.idea_debate_min_elapsed_sec,
                    "min_evaluated_attempts": (
                        self.config.idea_debate_min_evaluated_attempts
                    ),
                }
            )
        scheduler["last_dispatched_at"] = now_ms()
        return {
            "enabled": True,
            "mode": self.config.idea_debate_mode,
            "max_rounds": self.config.idea_debate_max_rounds,
            "emit_pair": self.config.idea_debate_emit_pair,
            "gate": {
                "mode": gate_mode,
                "elapsed_sec": elapsed_sec,
                "evaluated_attempts": evaluated,
            },
        }

    def _maybe_rank_queued_ideas(self, state: dict[str, Any]) -> bool:
        """进入冲刺窗口后，同步调用 Judge 并重排尚未实现的 Idea。"""

        if not self.config.time_aware_idea_ranking_enabled:
            return False
        remaining_sec = self._remaining_wall_time_sec(state)
        if (
            remaining_sec is None
            or remaining_sec > self.config.idea_rank_trigger_remaining_sec
        ):
            return False

        research = state.setdefault("research_state", {})
        scheduler = research.setdefault("scheduler", {}).setdefault(
            "time_aware_idea_ranking",
            {},
        )
        if not scheduler.get("activated_at"):
            scheduler.update(
                {
                    "status": "active",
                    "activated_at": now_ms(),
                    "trigger_remaining_sec": (
                        self.config.idea_rank_trigger_remaining_sec
                    ),
                }
            )
            self.artifacts.record_decision(
                {
                    "decision": "activate_time_aware_idea_ranking",
                    "remaining_sec": remaining_sec,
                    "trigger_remaining_sec": (
                        self.config.idea_rank_trigger_remaining_sec
                    ),
                }
            )

        queue = self._implementation_queue()
        items = self._rankable_idea_items(queue)
        # 时间门控只触发一次。不要因为新的评测结果改变 fingerprint 就再次
        # 启动 Judge；冲刺阶段应该把剩余时间留给 Implement 和 Evaluator。
        # 失败也不自动重试，保持 FIFO，避免一次超时演变成持续的 Judge 消耗。
        if scheduler.get("ranking_attempted_at") or scheduler.get(
            "last_attempted_at"
        ):
            self.state_store.save(state)
            return False
        fingerprint = self._idea_ranking_fingerprint(state, items)
        scheduler["ranking_attempted_at"] = now_ms()
        scheduler["last_fingerprint"] = fingerprint
        scheduler["last_attempted_at"] = now_ms()
        scheduler["remaining_sec_at_last_attempt"] = remaining_sec

        # 少于三条待实现 Idea 时不值得为排序花一次 Judge 调用：两条之间的
        # 先后取舍决策空间太小，而一次冲刺期 Judge 调用的实测中位耗时约
        # 270 秒、并会占用本该留给 Implement 和 Evaluator 的时间。
        if len(items) < self.config.idea_rank_min_items:
            scheduler.update(
                {
                    "last_ranked_at": now_ms(),
                    "ranked_item_ids": [str(item.get("id")) for item in items],
                    "last_result": "deterministic_noop",
                    "min_items": self.config.idea_rank_min_items,
                }
            )
            self.state_store.save(state)
            return False
        if remaining_sec <= self.config.idea_rank_min_remaining_sec:
            # 不在最后几分钟再启动可能跨过研究截止的 LLM 调用；保持原有
            # 排序或原 FIFO，给 Implement/canonical run 留出最后可用时间。
            #
            # 门槛按"典型完成时间 + 余量"设定，而不是按超时上限：超时是防挂死
            # 的兜底（30 分钟），实测中位 270 秒、p90 570 秒。若按上限预留，
            # 排序窗口会被压缩到剩余 30~60 分钟这一小段，错过即永不触发。
            scheduler.update(
                {
                    "last_result": "skipped_insufficient_time_for_judge",
                    "judge_timeout_sec": self.config.idea_rank_judge_timeout_sec,
                    "min_remaining_sec": self.config.idea_rank_min_remaining_sec,
                }
            )
            self.state_store.save(state)
            return False

        leaderboard = (
            research.get("leaderboard")
            if isinstance(research.get("leaderboard"), dict)
            else {}
        )
        infra = self.goal_doc.get("infra")
        infra = dict(infra) if isinstance(infra, dict) else {}
        ranking_inputs = [
            {
                "queue_item_id": str(item.get("id")),
                "idea_id": (item.get("payload") or {}).get("id"),
                "idea": dict(item.get("payload") or {}),
                "created_at": item.get("created_at"),
            }
            for item in items
        ]
        runtime_context = {
            "remaining_wall_time_sec": remaining_sec,
            "ranking_trigger_remaining_sec": (
                self.config.idea_rank_trigger_remaining_sec
            ),
            "leaderboard": dict(leaderboard),
            "resources": (
                dict(infra.get("resources"))
                if isinstance(infra.get("resources"), dict)
                else {}
            ),
            "pipeline": {
                "max_parallel_implementations": (
                    self.config.max_parallel_implementations
                ),
                "max_parallel_evaluations": self.config.max_parallel_evaluations,
                "evaluation_queue_capacity": self.config.evaluation_queue_capacity,
                "evaluation_queued": self.queues.evaluation.size(
                    LoopStatus.Queue.QUEUED
                ),
                "evaluation_running": self.queues.evaluation.size(
                    LoopStatus.Queue.RUNNING
                ),
            },
            "expbank_dir": str(self.expbank.root),
            "expbank_index": str(self.expbank.index_path),
            "rubric_version": "time_resource_aware_v1",
        }
        try:
            result = self.agent_facility.rank_ideas(
                self.goal_doc,
                ranking_inputs,
                runtime_context,
            )
            if not isinstance(result, dict):
                raise TypeError("Idea Rank Judge 必须返回 JSON object")
            entries = self._normalize_rank_entries(items, result)
        except Exception as exc:  # noqa: BLE001 - 排序失败必须回退原有队列策略
            failure_ref = self.artifacts.save_json(
                "idea_ranking_failure",
                {
                    "fingerprint": fingerprint,
                    "remaining_sec": remaining_sec,
                    "queue_item_ids": [str(item.get("id")) for item in items],
                    "error": f"{type(exc).__name__}: {exc}",
                    "created_at": now_ms(),
                },
            )
            scheduler.update(
                {
                    "last_result": "judge_failed_fifo_preserved",
                    "last_failure_ref": failure_ref,
                }
            )
            self.artifacts.record_decision(
                {
                    "decision": "preserve_idea_queue_after_rank_failure",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                refs=[failure_ref],
            )
            self.state_store.save(state)
            return False

        ranking_ref = self.artifacts.save_json(
            "idea_ranking",
            {
                "fingerprint": fingerprint,
                "remaining_sec": remaining_sec,
                "rubric_version": runtime_context["rubric_version"],
                "ranking": entries,
                "judge_summary": result.get("summary"),
                "created_at": now_ms(),
            },
        )
        decision_ref = self.artifacts.record_decision(
            {
                "decision": "apply_time_aware_idea_ranking",
                "remaining_sec": remaining_sec,
                "ordered_queue_item_ids": [
                    entry["queue_item_id"] for entry in entries
                ],
            },
            refs=[ranking_ref],
        )
        items_by_id = {str(item.get("id")): item for item in items}
        for entry in entries:
            item = items_by_id[entry["queue_item_id"]]
            # 普通 Idea 的默认优先级是 1。排名依次使用 1、0、-1...，因此
            # Actor repair/refine 的 3/2 优先级保持不变，同类 Idea 内按 Judge 排序。
            item["priority"] = 2 - int(entry["rank"])
            item["time_aware_rank"] = {
                **entry,
                "ranking_ref": ranking_ref,
                "ranked_at": now_ms(),
            }
            queue.update(
                item,
                evidence_refs=[ranking_ref, decision_ref],
            )
        scheduler.update(
            {
                "last_result": "ranked",
                "last_ranked_at": now_ms(),
                "last_ranking_ref": ranking_ref,
                "ranked_item_ids": [entry["queue_item_id"] for entry in entries],
            }
        )
        self.state_store.save(state)
        self.log(
            "time-aware idea ranking applied; "
            f"items={len(entries)} remaining_sec={remaining_sec:.1f}"
        )
        return True

    def _record_runtime_limits(self, state: dict[str, Any]) -> None:
        """记录当前运行限制。"""
        state.setdefault("research_state", {}).setdefault("runtime_limits", {}).update(
            {
                "max_parallel_evaluations": self.config.max_parallel_evaluations,
                "max_parallel_ideas": self.config.max_parallel_ideas,
                "max_parallel_implementations": self.config.max_parallel_implementations,
                "max_experiment_retries": self.config.max_experiment_retries,
                "max_wall_time_hours": self.config.max_wall_time_hours,
                "max_implement_lifetime_sec": self.config.max_implement_lifetime_sec,
                "max_implement_turns_per_actor": self.config.max_implement_turns_per_actor,
                "max_run_attempts_per_actor": self.config.max_run_attempts_per_actor,
                "max_official_evaluations_per_actor": self.config.max_official_evaluations_per_actor,
                "idea_queue_high_watermark": self.config.idea_queue_high_watermark,
                "evaluation_queue_capacity": self.config.evaluation_queue_capacity,
                "idea_gate_enabled": self.idea_gate_enabled,
                "time_aware_idea_ranking_enabled": (
                    self.config.time_aware_idea_ranking_enabled
                ),
                "pairwise_improve_search_enabled": bool(
                    getattr(self.search_policy, "enabled", False)
                ),
                "idea_rank_trigger_remaining_sec": (
                    self.config.idea_rank_trigger_remaining_sec
                ),
                "idea_rank_judge_timeout_sec": (
                    self.config.idea_rank_judge_timeout_sec
                ),
            }
        )

    def _checkpoint(self, state: dict[str, Any], phase: str) -> None:
        """保存状态检查点。"""
        rs = state.setdefault("research_state", {})
        rs["current_phase"] = phase
        rs["last_heartbeat_at"] = now_ms()
        self.state_store.update_queues(state, self.queues.summary())
        self._render_status(state)

    def _stop_for_wall_time(self, state: dict[str, Any]) -> None:
        """因墙钟时间耗尽而停止运行。"""
        rs = state.setdefault("research_state", {})
        rs["status"] = LoopStatus.Research.STOPPED
        rs["termination_reason"] = "wall_time_budget_exhausted"
        rs.setdefault("audit", {}).setdefault("termination_events", []).append(
            {
                "ts": now_ms(),
                "reason": "wall_time_budget_exhausted",
                "max_wall_time_hours": self.config.max_wall_time_hours,
            }
        )
        self.state_store.save(state)
        self._render_status(state)
        self.log(
            "wall-time budget exhausted; "
            f"limit_hours={self.config.max_wall_time_hours}"
        )

    def _recover_interrupted_items(self) -> None:
        """恢复上次中断遗留的运行中条目。"""
        state = self.state_store.load()
        # WorkspaceRunLock 已在 run() 外层持有，此时旧 running 条目不可能仍被另一
        # 调度器合法执行，可以安全重新排队。
        recovered = self.queues.recover_running()
        total = sum(len(items) for items in recovered.values())
        if not total:
            return
        for item in recovered["benchmark_attempt_queue"]:
            self._upsert_branch_state(
                state,
                item.get("payload") or {},
                LoopStatus.Branch.BENCHMARK_ATTEMPT_QUEUED,
            )
        for item in recovered["evaluation_queue"]:
            self._upsert_branch_state(
                state,
                item.get("payload") or {},
                LoopStatus.Branch.EVALUATION_QUEUED,
            )
        for item in recovered["analyze_spark"]:
            self._upsert_branch_state(
                state,
                item.get("payload") or {},
                LoopStatus.Branch.ANALYSIS_QUEUED,
            )
        state.setdefault("research_state", {}).setdefault("audit", {}).setdefault(
            "recovery_events", []
        ).append(
            {
                "ts": now_ms(),
                "recovered": {
                    name: [item.get("id") for item in items]
                    for name, items in recovered.items()
                    if items
                },
            }
        )
        self.state_store.update_queues(state, self.queues.summary())
        self.log(f"recovered interrupted queue items={total}")

    def _long_lived_actors_enabled(self) -> bool:
        """判断当前目标是否启用多回合 ImplementActor。

        Actor 存在的理由是"还要再唤醒一次"，而续跑有两种：refine 和 debug。
        历史上只有 refine 这一种，所以判据就是 `turns > 1`。

        演化图 v2 要的是"**不 refine，但仍能 debug**"——这时 turns 会被设成 1，
        可 actor 必须照样活着，否则 resume debug 跟着一起没了，代码有 bug 的方案
        直接判死。所以多出下面那个分支。

        默认（`refine_after_evaluation=True`）时这个函数与改动前逐字等价。
        """

        if self.config.max_implement_turns_per_actor > 1:
            return True
        return (
            not self.config.refine_after_evaluation
            and self.config.max_debug_attempts_per_actor != 0
        )

    def _prepare_actor_turn(
        self,
        idea: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """创建或恢复 actor，并把稳定工作区与 mailbox 注入本回合。"""
        if not self._long_lived_actors_enabled():
            return idea, None
        actor_id = str(idea.get("actor_id") or "")
        if actor_id:
            actor = self.actors.read(actor_id)
        else:
            actor = self.actors.create(
                idea,
                max_lifetime_sec=self.config.max_implement_lifetime_sec,
                max_turns=self.config.max_implement_turns_per_actor,
                max_run_attempts=self.config.max_run_attempts_per_actor,
                max_official_evaluations=self.config.max_official_evaluations_per_actor,
                max_repairs_per_revision=self.config.max_repairs_per_revision,
                max_debug_attempts=self.config.max_debug_attempts_per_actor,
            )
            actor_id = str(actor["actor_id"])
        repair_reasons = {
            "implementation_failed",
            "preflight_failed",
            "run_failed",
            "validation_failed",
            "public_eval_failed",
            "evaluation_failed",
            "validity_failed",
        }
        actor = self.actors.begin_turn(
            actor_id,
            repair=str(idea.get("continuation_reason") or "") in repair_reasons,
        )
        budget = dict(actor.get("budget") or {})
        official_limit = budget.get("max_official_evaluations")
        actor_limits = {
            "deadline_at": actor.get("deadline_at"),
            "remaining_lifetime_sec": max(
                0,
                (int(actor.get("deadline_at") or 0) - now_ms()) // 1000,
            ),
            "remaining_research_turns": max(
                0,
                int(budget.get("max_turns") or 0)
                - int(budget.get("used_turns") or 0),
            ),
            "remaining_run_attempts": max(
                0,
                int(budget.get("max_run_attempts") or 0)
                - int(budget.get("used_run_attempts") or 0)
                - len(actor.get("pending_candidates") or []),
            ),
            "remaining_official_evaluations": (
                None
                if official_limit is None
                else max(
                    0,
                    int(official_limit)
                    - int(budget.get("used_official_evaluations") or 0),
                )
            ),
        }
        # 对 Agent 使用更直接的“可提交候选”术语；当前 V1 中一次通过 preflight
        # 的提交会占用一次 canonical run，因此两者共享同一硬预算。
        actor_limits["remaining_candidate_submissions"] = actor_limits[
            "remaining_run_attempts"
        ]
        prepared = dict(idea)
        prepared.update(
            {
                "actor_id": actor_id,
                "actor_branch_id": actor["branch_id"],
                "lineage_id": actor["lineage_id"],
                "revision": actor["revision"],
                "parent_attempt_id": actor.get("last_attempt_id"),
                "parent_candidate_id": actor.get("last_candidate_id"),
                "feedback_mailbox": actor["mailbox"],
                # instruction 会向 Agent 展示该只读预算快照；真正的限制仍由
                # ImplementActorStore 和调度器执行，不能依赖模型自觉遵守。
                "actor_limits": actor_limits,
            }
        )
        return prepared, actor

    def _actor_has_active_turn(self, actor_id: str) -> bool:
        """检查同一 actor 是否已有排队或运行中的实现回合。"""
        if not actor_id:
            return False
        queue = self._implementation_queue()
        return any(
            str((item.get("payload") or {}).get("actor_id") or "") == actor_id
            for status in (LoopStatus.Queue.QUEUED, LoopStatus.Queue.RUNNING)
            for item in queue.list(status)
        )

    def _schedule_actor_continuation(
        self,
        state: dict[str, Any],
        branch: dict[str, Any],
        *,
        reason: str,
    ) -> bool:
        """在预算和背压允许时为现有 actor 排入下一实现回合。"""
        actor_id = str(branch.get("actor_id") or "")
        if not self._long_lived_actors_enabled() or not actor_id:
            return False
        if reason == "evaluated" and not self.config.refine_after_evaluation:
            # 出分即收工。改进不在 actor 内部发生，必须回 IdeaAgent 看图、选
            # operator + parents，作为一条新的 exploit 边挂上去——这样它才进得了
            # 主读数。就地 refine 只会给同一个节点多加一条 attempt，图上看不出
            # 「往哪走了」。
            #
            # 状态用 COMPLETED 而不是 EXHAUSTED：这是正常收尾，不是预算耗尽。
            # termination_reason 必须能把两者分开，否则事后审计会把"设计如此"
            # 读成"预算不够"。
            self.actors.update(
                actor_id,
                status=LoopStatus.Actor.COMPLETED,
                termination_reason="refine_after_evaluation_disabled",
            )
            return False
        runtime_status = state.get("research_state", {}).get("status")
        if runtime_status in LoopStatus.RESEARCH_TERMINAL:
            # 截止后返回的 evaluator 结果仍需完整落盘，但不能再由反馈派生新的
            # Implement 回合。Actor 终止和 Candidate 结果是两条独立证据。
            self.actors.update(
                actor_id,
                status=LoopStatus.Actor.EXHAUSTED,
                termination_reason=f"research_runtime_{runtime_status}",
            )
            return False
        if self._actor_has_active_turn(actor_id):
            return False
        implementation_queue = self._implementation_queue()
        # Idea high watermark 是整个待实现队列的硬容量，不区分新 Idea 与 Actor
        # continuation。反馈续跑虽有更高优先级，但不能绕过容量无限堆积。
        if (
            self._idea_backlog(implementation_queue)
            >= self.config.idea_queue_high_watermark
        ):
            return False
        actor = self.actors.read(actor_id)
        repair_reasons = {
            "implementation_failed",
            "preflight_failed",
            "run_failed",
            "validation_failed",
            "public_eval_failed",
            "evaluation_failed",
            "validity_failed",
        }
        is_repair = reason in repair_reasons
        actor_budget = actor.get("budget") or {}
        if (
            reason == "evaluated"
            and int(actor_budget.get("max_official_evaluations") or 0) > 0
            and int(actor_budget.get("used_official_evaluations") or 0)
            >= int(actor_budget["max_official_evaluations"])
        ):
            self.actors.update(
                actor_id,
                status=LoopStatus.Actor.COMPLETED,
                termination_reason="actor_valid_evaluation_budget_exhausted",
            )
            return False
        allowed, termination_reason = self.actors.can_start_turn(
            actor_id,
            repair=is_repair,
        )
        if not allowed:
            self.actors.update(
                actor_id,
                status=(
                    LoopStatus.Actor.COMPLETED
                    if reason == "evaluated"
                    and termination_reason == "actor_turn_budget_exhausted"
                    else LoopStatus.Actor.EXHAUSTED
                ),
                termination_reason=termination_reason,
            )
            return False
        budget = actor.get("budget") or {}
        if (
            is_repair
            and int(actor.get("repair_count") or 0)
            > int(budget.get("max_repairs_per_revision") or 0)
        ):
            self.actors.update(
                actor_id,
                status=LoopStatus.Actor.EXHAUSTED,
                termination_reason="actor_repair_budget_exhausted",
            )
            return False
        pending = list(actor.get("pending_candidates") or [])
        # pending 同时覆盖排队、运行和等待正式评分的 Candidate。达到单 Actor
        # 上限后只等待 Evaluation Pool 返回反馈，不再叠加 speculative/policy-lag。
        if pending:
            return False
        eval_backlog = self.queues.evaluation.size(
            LoopStatus.Queue.QUEUED
        ) + self.queues.evaluation.size(
            LoopStatus.Queue.WAITING_RESOURCES
        ) + self.queues.evaluation.size(LoopStatus.Queue.RUNNING)
        if eval_backlog >= self.config.evaluation_queue_capacity:
            return False
        queue = implementation_queue
        continuation = dict(actor.get("base_idea") or {})
        continuation.update(
            {
                "actor_id": actor_id,
                "actor_branch_id": actor["branch_id"],
                "lineage_id": actor["lineage_id"],
                "parent_attempt_id": actor.get("last_attempt_id"),
                "parent_candidate_id": actor.get("last_candidate_id"),
                "feedback_mailbox": actor["mailbox"],
                "continuation_reason": reason,
                "attempt_number": queue.size() + 1,
            }
        )
        if not is_repair:
            diagnostics = self._refine_diagnostics(state, actor)
            if diagnostics:
                continuation["refine_diagnostics"] = diagnostics
        continuation_ref = self.artifacts.save_json(
            "actor_continuation",
            continuation,
        )
        queue.push(
            continuation,
            item_type="actor_continuation",
            # 修复反馈优先于普通 refine 和新 Idea，但不会抢占已经在运行的 Agent。
            priority=(
                3
                if is_repair
                else 2
            ),
            evidence_refs=[continuation_ref],
        )
        self.actors.update(actor_id, status=LoopStatus.Actor.READY)
        self.artifacts.record_decision(
            {
                "decision": "schedule_actor_continuation",
                "actor_id": actor_id,
                "reason": reason,
                "parent_candidate_id": actor.get("last_candidate_id"),
            },
            refs=[continuation_ref],
        )
        return True

    def _schedule_ready_actors(self, state: dict[str, Any]) -> int:
        """重新派发此前因并发槽或背压不足而暂存的 Actor。"""
        ready = [
            actor
            for actor in self.actors.list()
            if actor.get("status")
            in {LoopStatus.Actor.REPAIR_READY, LoopStatus.Actor.REFINE_READY}
        ]
        # 工程修复优先恢复；同一优先级按更新时间处理，保证等待较久的 Actor 先走。
        ready.sort(
            key=lambda actor: (
                0
                if actor.get("status") == LoopStatus.Actor.REPAIR_READY
                else 1,
                int(actor.get("updated_at") or 0),
            )
        )
        scheduled = 0
        for actor in ready:
            reason = str(
                actor.get("last_feedback_kind")
                or (
                    "run_failed"
                    if actor.get("status") == LoopStatus.Actor.REPAIR_READY
                    else "evaluated"
                )
            )
            if self._schedule_actor_continuation(state, actor, reason=reason):
                scheduled += 1
        return scheduled

    def _actor_official_budget_available(self, branch: dict[str, Any]) -> bool:
        """检查 actor 级正式评测预算；非 actor 分支始终返回允许。"""
        actor_id = str(branch.get("actor_id") or "")
        if not actor_id:
            return True
        actor = self.actors.read(actor_id)
        budget = actor.get("budget") or {}
        limit = budget.get("max_official_evaluations")
        return limit is None or int(
            budget.get("used_official_evaluations") or 0
        ) < int(limit)

    def _finish_actor_candidate(
        self,
        state: dict[str, Any],
        branch: dict[str, Any],
        *,
        kind: str,
        feedback: dict[str, Any],
        official_evaluated: bool = False,
    ) -> None:
        """结束 Candidate、投递脱敏反馈并尝试唤醒 actor。"""
        actor_id = str(branch.get("actor_id") or "")
        candidate_id = str(branch.get("candidate_id") or "")
        if not actor_id:
            return
        if candidate_id:
            self.actors.complete_candidate(
                actor_id,
                candidate_id,
                official_evaluated=official_evaluated,
            )
        # complete_candidate 会先释放单 Actor 的唯一在途名额；随后 add_feedback
        # 把 Actor 切到 repair_ready/refine_ready，调度器才能安全恢复原 Session。
        self.actors.add_feedback(
            actor_id,
            candidate_id=candidate_id or None,
            kind=kind,
            payload=feedback,
        )
        self._schedule_actor_continuation(state, branch, reason=kind)

    def _run_implementation_item(self, idea_item: dict[str, Any]) -> dict[str, Any]:
        """运行单个实现任务并捕获异常。"""

        idea = dict(idea_item.get("payload") or {})
        idea_id = str(idea.get("id") or idea_item.get("id") or "unknown")
        lineage = (
            self.goal_doc.get("lineage")
            if isinstance(self.goal_doc.get("lineage"), dict)
            else {}
        )
        # 父 Loop 目录是只读输入，不复制到当前 workspace；把路径放入 Idea
        # payload 后，普通 Implement Agent、Actor continuation 和恢复回合都能
        # 使用同一份历史上下文。
        idea.setdefault(
            "prior_loop_dirs",
            list(lineage.get("prior_loop_dirs") or []),
        )
        idea.setdefault(
            "experience_sources",
            list(lineage.get("experience_sources") or []),
        )
        try:
            idea, _actor = self._prepare_actor_turn(idea)
        except Exception as exc:  # noqa: BLE001 - actor 预算耗尽按普通失败持久化
            branch_id = str(idea.get("actor_branch_id") or new_id("branch_failed"))
            return {
                "id": branch_id,
                "branch_id": branch_id,
                "idea_id": idea_id,
                "actor_id": idea.get("actor_id"),
                "status": LoopStatus.Implementation.FAILED,
                "valid": False,
                "error": repr(exc),
                "implementation_type": "actor_admission",
                "lineage_id": str(idea.get("lineage_id") or idea_id),
                "created_at": now_ms(),
            }
        attempt_id = str(idea.get("expbank_attempt_id") or "")
        if not attempt_id:
            # 一旦进入实现阶段就先分配 ExpBank 编号。即使 Agent 随后报错，
            # 该版本仍有稳定位置保存 Idea、错误和后续修复线索。
            attempt_id = self.expbank.create_attempt(
                idea=idea,
                lineage_id=str(idea.get("lineage_id") or idea_id),
                parent_attempt_id=idea.get("parent_attempt_id"),
                metadata={"queue_item_id": idea_item.get("id")},
                # v2 才写：attempt 从此显式回指方案节点，INDEX.md 也多出「节点」列。
                # v1 臂不传，record.json 与 INDEX.md 的渲染都保持原样。
                idea_id=idea_id if self._evolution_graph() else None,
            )
        if self._idea_graph_active():
            try:
                self.idea_graph.link_attempt(idea_id, attempt_id)
            except FileNotFoundError:
                # 迁移前的旧 Ideaspark 条目没有 Idea Graph 节点；实现证据仍由
                # ExpBank attempt 完整保存，不能因此中断恢复中的 Loop。
                pass
        idea["expbank_attempt_id"] = attempt_id
        idea["expbank_dir"] = str(self.expbank.root)

        try:
            branch = self.agent_facility.implement(idea, self.workspace)
            if not isinstance(branch, dict):
                raise TypeError(
                    f"implement worker returned {type(branch).__name__}, expected dict"
                )
            branch = dict(branch)
            branch["expbank_attempt_id"] = attempt_id
            branch["lineage_id"] = str(idea.get("lineage_id") or idea_id)
            branch["actor_id"] = idea.get("actor_id")
            # Idea 的声明是默认运行契约；Implement 可以在结构化提交中给出更准确
            # 的修正，但必须重新通过任务总资源校验。
            try:
                branch["resource_request"] = self._normalize_resource_request(
                    branch.get("resource_request") or idea.get("resource_request")
                )
            except ValueError as exc:
                # submit_candidate 已对标准 CLI Agent 前置校验；这里仍保留防御性
                # 校验，覆盖自定义 Agent Adapter 和旧 Candidate。
                branch.update(
                    {
                        "status": LoopStatus.Implementation.FAILED,
                        "valid": False,
                        "failure_kind": "implement_resource_override_rejected",
                        "error": str(exc),
                        "failure": {
                            "failure_stage": "resource_admission",
                            "error_code": "implement_resource_override_rejected",
                            "return_code": None,
                            "signal": None,
                            "timed_out": False,
                            "submitted": bool(branch.get("submission_id")),
                            "retryable": True,
                            "message": str(exc),
                            "suggested_action": (
                                "把 Candidate 资源声明调整到请求中的脱敏资源信封内后重提。"
                            ),
                            "evidence_refs": [],
                        },
                    }
                )
                return branch
            if self._research_deadline_path().is_file():
                # Agent 返回和截止信号可能并发发生。截止后不再做 Candidate 冻结或
                # Bench preflight；异步收集器会把本次 attempt 归档为 not_executed。
                branch["cancelled_by_research_deadline"] = True
                return branch
            if (
                branch.get("status", LoopStatus.Implementation.IMPLEMENTED)
                == LoopStatus.Implementation.IMPLEMENTED
                and (branch.get("worktree") or branch.get("method_dir"))
                and self._has_candidate_source(branch)
            ):
                # Agent 只产生可变工作区。Controller 先冻结通用 CandidateRef，再把
                # 它交给 Bench Facility；入口文件等任务约定由具体 Bench 校验。
                branch = self.candidates.create(
                    branch,
                    revision=int(idea.get("revision") or 1),
                    parent_candidate_id=idea.get("parent_candidate_id"),
                )
                candidate_ref = self._candidate_ref(branch)
                branch["candidate_ref"] = candidate_ref.to_dict()
                preflight = self.benchmark_facility.preflight(
                    candidate_ref,
                    context=branch,
                )
                branch["preflight"] = preflight
                if not isinstance(preflight, dict) or preflight.get("valid") is not True:
                    branch.update(
                        {
                            "status": LoopStatus.Implementation.FAILED,
                            "valid": False,
                            "failure_kind": "preflight_failed",
                            "error": str(
                                preflight.get("error")
                                if isinstance(preflight, dict)
                                else "preflight did not return an object"
                            ),
                        }
                    )
                    return branch
            return branch
        except Exception as exc:  # noqa: BLE001 - isolate a failed idea
            branch_id = str(idea.get("actor_branch_id") or new_id("branch_failed"))
            return {
                "id": branch_id,
                "branch_id": branch_id,
                "idea_id": idea_id,
                "status": LoopStatus.Implementation.FAILED,
                "valid": False,
                "error": repr(exc),
                "implementation_type": "worker_exception",
                "expbank_attempt_id": attempt_id,
                "lineage_id": str(idea.get("lineage_id") or idea_id),
                "actor_id": idea.get("actor_id"),
                "created_at": now_ms(),
            }

    def _process_implementation_result(
        self,
        state: dict[str, Any],
        idea_item: dict[str, Any],
        branch: dict[str, Any],
    ) -> None:
        """持久化实现结果或归档失败分支。"""

        # 自定义 Agent Adapter 可能没有实现显式选择协议。策略会将缺失或非法
        # 决策安全归一化为 refine，确保临时 New Idea 不会被误消费。
        # settlement 必须读取 Agent 的原始返回，不能读取下方写回 branch 的归一化
        # 结果，否则 controller_fallback 会在二次归一化时被误记为 Agent 选择。
        raw_policy_result = branch
        search_decision = self.search_policy.normalize_decision(idea_item, branch)
        if search_decision is not None:
            branch = dict(branch)
            branch["search_decision"] = search_decision
            branch["lineage_idea_ids"] = list(
                search_decision.get("lineage_idea_ids") or []
            )

        branch_ref = self.artifacts.save_json(
            "branch",
            branch,
            refs=idea_item.get("evidence_refs", []),
        )
        settlement = self.search_policy.settle(
            idea_item,
            raw_policy_result,
            self._implementation_queue(),
            evidence_refs=[branch_ref],
        )
        if settlement.decision is not None:
            settlement_payload = {
                **settlement.decision,
                "decision": "settle_improve_search_opportunity",
                "implementation_queue_item_id": idea_item.get("id"),
                "replayed": settlement.replayed,
                "consumed": settlement.consumed,
                "ignored": settlement.ignored,
            }
            settlement_ref = self.artifacts.save_json(
                "search_policy_decision",
                settlement_payload,
                refs=[branch_ref],
            )
            self.artifacts.record_decision(
                settlement_payload,
                refs=[branch_ref, settlement_ref],
            )
            actor_id = str(branch.get("actor_id") or "")
            opportunity = (idea_item.get("payload") or {}).get(
                "search_opportunity"
            )
            offered_idea = (
                opportunity.get("offered_idea")
                if isinstance(opportunity, dict)
                else None
            )
            if actor_id:
                self.actors.record_search_decision(
                    actor_id,
                    settlement.decision,
                    offered_idea=(
                        offered_idea if isinstance(offered_idea, dict) else None
                    ),
                )
        self._implementation_queue().update(
            idea_item,
            status=LoopStatus.Queue.FINISHED,
            output_refs=[branch_ref],
            evidence_refs=[branch_ref],
        )
        expbank_attempt_id = str(branch.get("expbank_attempt_id") or "")
        source_idea = idea_item.get("payload") or {}
        idea_id = str(
            branch.get("idea_id")
            or (source_idea.get("id") if isinstance(source_idea, dict) else "")
            or ""
        )
        actor_id = str(branch.get("actor_id") or "")
        if actor_id and isinstance(branch.get("agent_session"), dict):
            self.actors.update_session(actor_id, branch["agent_session"])
        if (
            branch.get("status", LoopStatus.Implementation.IMPLEMENTED)
            != LoopStatus.Implementation.IMPLEMENTED
        ):
            failure = (
                dict(branch.get("failure"))
                if isinstance(branch.get("failure"), dict)
                else {}
            )
            failure_kind = str(
                branch.get("failure_kind")
                or failure.get("error_code")
                or "implementation_failed"
            )
            if not failure:
                failure = {
                    "failure_stage": "implementation",
                    "error_code": failure_kind,
                    "return_code": None,
                    "signal": None,
                    "timed_out": False,
                    "submitted": bool(branch.get("submission_id")),
                    "retryable": True,
                    "message": str(branch.get("error") or "implementation failed"),
                    "suggested_action": "读取实现日志后修复当前版本。",
                    "evidence_refs": [branch_ref],
                }
            if self._idea_graph_active():
                try:
                    self.idea_graph.record_implementation(
                        idea_id,
                        succeeded=False,
                        attempt_id=expbank_attempt_id or None,
                    )
                except (FileNotFoundError, ValueError):
                    pass
            if expbank_attempt_id:
                if isinstance(branch.get("preflight"), dict):
                    self.expbank.write_evidence_json(
                        expbank_attempt_id,
                        "preflight",
                        branch["preflight"],
                    )
                self.expbank.update_attempt(
                    expbank_attempt_id,
                    status=LoopStatus.ExpBank.ENGINEERING_FAILED,
                    branch_id=branch.get("branch_id"),
                    implementation=branch,
                    search_decision=branch.get("search_decision"),
                    failure=failure,
                    error=str(branch.get("error") or "implementation failed"),
                    conclusion="当前版本存在工程问题，尚不能形成方法有效性结论。",
                    next_step="读取错误信息并创建修复版本。",
                    evidence_refs=[branch_ref],
                )
            self._upsert_branch_state(
                state,
                branch,
                LoopStatus.Branch.ENGINEERING_FAILED,
                evidence_refs=[branch_ref],
            )
            self.artifacts.record_decision(
                {
                    "decision": "request_actor_repair" if actor_id else "archive",
                    "branch_id": branch.get("branch_id"),
                    "reasons": [str(branch.get("error") or "implementation failed")],
                },
                refs=[branch_ref],
            )
            # 实现失败只结束当前版本，不代表 Idea/lineage 本身无效。错误和修复建议
            # 已写入 ExpBank，后续 Idea/Implement 可以据此派生修复版本。
            if actor_id:
                feedback_payload = {
                    **failure,
                    "error": str(branch.get("error") or "implementation failed"),
                    "preflight": branch.get("preflight"),
                    "expbank_attempt_id": expbank_attempt_id or None,
                }
                self.actors.add_feedback(
                    actor_id,
                    candidate_id=None,
                    # 路由依据是失败阶段，细粒度 error_code 保留在 payload。
                    # 这样 API、协议、超时或内存错误都会恢复原 Actor 修复，且不会
                    # 被误计为新的科研 Improve 回合。
                    kind="implementation_failed",
                    payload=feedback_payload,
                )
                self._schedule_actor_continuation(
                    state,
                    branch,
                    reason="implementation_failed",
                )
            return

        if self._idea_graph_active():
            try:
                self.idea_graph.record_implementation(
                    idea_id,
                    succeeded=True,
                    attempt_id=expbank_attempt_id or None,
                )
            except (FileNotFoundError, ValueError):
                pass
        if expbank_attempt_id:
            if isinstance(branch.get("preflight"), dict):
                self.expbank.write_evidence_json(
                    expbank_attempt_id,
                    "preflight",
                    branch["preflight"],
                )
            self.expbank.update_attempt(
                expbank_attempt_id,
                status=LoopStatus.ExpBank.IMPLEMENTED,
                branch_id=branch.get("branch_id"),
                implementation=branch,
                search_decision=branch.get("search_decision"),
                evidence_refs=[branch_ref],
            )
            worktree = branch.get("method_dir") or branch.get("worktree")
            # 实验与评测永远对应这个冻结快照。Implement Agent 后续即使继续修改
            # 自己的工作区，也不能改变已经进入 evaluation_queue 的版本证据。
            if worktree and not (self.expbank.root / expbank_attempt_id / "code").exists():
                self.expbank.freeze_code(expbank_attempt_id, str(worktree))
        candidate_id = str(branch.get("candidate_id") or "")
        if candidate_id:
            terminal_status = self._control_status() or state.get("research_state", {}).get("status")
            candidate_status = (
                LoopStatus.Candidate.CANCELLED
                if terminal_status == LoopStatus.Research.STOPPED
                and state.get("research_state", {}).get("termination_reason")
                != "wall_time_budget_exhausted"
                else LoopStatus.Candidate.QUEUED
            )
            self.candidates.update(candidate_id, status=candidate_status)
            actor_id = str(branch.get("actor_id") or "")
            if actor_id:
                self.actors.register_candidate(
                    actor_id,
                    candidate_id,
                    attempt_id=expbank_attempt_id or None,
                )

        terminal_status = self._control_status() or state.get("research_state", {}).get("status")
        if terminal_status in LoopStatus.RESEARCH_TERMINAL:
            # 后台 Agent 可能在 stop/pause 之后才返回。保留其代码证据，但不再接收
            # 新实验，避免用户停止后继续消耗计算或正式评测预算。
            self._upsert_branch_state(
                state,
                branch,
                LoopStatus.Branch.ARCHIVED,
                evidence_refs=[branch_ref],
            )
            self.artifacts.record_decision(
                {
                    "decision": "archive",
                    "branch_id": branch.get("branch_id"),
                    "reasons": [
                        "implementation finished after runtime stopped accepting new evaluations",
                        f"runtime_status={terminal_status}",
                    ],
                },
                refs=[branch_ref],
            )
            return

        self.queues.evaluation.push(
            branch,
            item_type="branch",
            priority=idea_item.get("priority", 0),
            evidence_refs=[branch_ref],
        )
        self.artifacts.record_decision(
            {
                "decision": "implemented_to_evaluation_queue",
                "branch_id": branch.get("branch_id"),
                "reasons": ["implementation completed"],
            },
            refs=[branch_ref],
        )
        self._upsert_branch_state(
            state,
            branch,
            LoopStatus.Branch.EVALUATION_QUEUED,
            evidence_refs=[branch_ref],
        )
        # Candidate 提交后 Actor 进入 waiting_evaluation 并释放 Implement 并发槽。
        # 同一 Actor 不做无反馈续投；调度器可以在该槽位运行其他 Idea 的 Actor。

    def _run_experiment_item(self, exp_item: dict[str, Any]) -> dict[str, Any]:
        """通过 Bench Facility 运行单个 Candidate，并捕获异常。"""
        branch = exp_item.get("payload") or {}
        branch_id = str(branch.get("branch_id") or branch.get("id") or exp_item.get("id") or "unknown")
        candidate_id = str(branch.get("candidate_id") or "")
        try:
            if candidate_id:
                self.candidates.update(candidate_id, status=LoopStatus.Candidate.RUNNING)
            candidate_ref = self._candidate_ref(branch)
            result = self.benchmark_facility.run(candidate_ref, context=branch)
            if not isinstance(result, RunResult):
                raise TypeError(
                    "benchmark facility returned "
                    f"{type(result).__name__}, expected RunResult"
                )
            return result.to_dict()
        except Exception as exc:  # noqa: BLE001 - isolate a failed branch
            return {
                "id": new_id("failed_run"),
                "branch_id": branch_id,
                "source": "orchestrator_experiment_runner",
                "valid": False,
                "returncode": -1,
                "error": repr(exc),
                "exception_type": type(exc).__name__,
                "created_at": now_ms(),
            }

    def _run_experiment_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """运行一批相互独立的实验任务。"""
        if not items:
            return []
        max_workers = min(self.config.max_parallel_evaluations, len(items))
        if max_workers <= 1:
            return [self._run_experiment_item(item) for item in items]

        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="loop-experiment"
        ) as executor:
            futures = [executor.submit(self._run_experiment_item, item) for item in items]
            # 等所有实验执行器完成后，再进入串行评测阶段。
            return [future.result() for future in futures]

    def _run_evaluator_item(
        self,
        exp_item: dict[str, Any],
        run_result: dict[str, Any],
        *,
        allow_official: bool,
    ) -> dict[str, Any]:
        """执行公开检查与正式评分，持久化和预算由主线程完成。"""
        branch = exp_item.get("payload") or {}
        if self._research_stop_path().is_file():
            raise RuntimeError("evaluation cancelled by task stop")
        artifact_ref = self._artifact_ref(run_result, branch)
        artifact = artifact_ref.storage_path if artifact_ref else ""
        try:
            if artifact_ref is None:
                raise ValueError("benchmark run 未返回 ArtifactRef")
            validation = self.benchmark_facility.validate_artifact(artifact_ref)
            if not isinstance(validation, dict):
                raise TypeError(
                    "artifact validator returned "
                    f"{type(validation).__name__}, expected dict"
                )
            public = None
            official = None
            official_called = False
            if validation.get("valid") is True:
                if self._research_stop_path().is_file():
                    raise RuntimeError("evaluation cancelled by task stop")
                public = self.benchmark_facility.run_public_evaluation(artifact_ref)
                if not isinstance(public, dict):
                    public = {
                        "valid": False,
                        "source": "public_eval",
                        "artifact": artifact,
                        "error": (
                            "public evaluator returned "
                            f"{type(public).__name__}, expected dict"
                        ),
                    }
                if public.get("valid") is True and allow_official:
                    if self._research_stop_path().is_file():
                        raise RuntimeError("evaluation cancelled by task stop")
                    official_called = True
                    official_value = self.evaluation_facility.evaluate(
                        self._evaluation_request(branch, artifact_ref)
                    )
                    if not isinstance(official_value, EvaluationResult):
                        official = {
                            "valid": False,
                            "source": "official_evaluator",
                            "artifact": artifact,
                            "error": (
                                "evaluation facility returned "
                                f"{type(official_value).__name__}, "
                                "expected EvaluationResult"
                            ),
                        }
                    else:
                        official = official_value.to_dict()
            return {
                "valid": True,
                "artifact": artifact,
                "artifact_ref": artifact_ref.to_dict(),
                "validation": validation,
                "public": public,
                "official": official,
                "official_allowed": allow_official,
                "official_called": official_called,
            }
        except Exception as exc:  # noqa: BLE001 - 主线程会统一归档错误证据
            return {
                "valid": False,
                "artifact": artifact,
                "official_allowed": allow_official,
                "official_called": False,
                "error": repr(exc),
                "exception_type": type(exc).__name__,
            }

    def _archive_failed_experiment(
        self,
        exp_item: dict[str, Any],
        branch: dict[str, Any],
        run_result: dict[str, Any],
        refs: list[str],
        *,
        reason: str,
    ) -> None:
        """保存实验失败信息且不中断其他分支。"""
        self.queues.evaluation.update(
            exp_item,
            status=LoopStatus.Queue.FAILED,
            output_refs=refs,
            evidence_refs=refs,
        )
        self.artifacts.record_decision(
            {
                "decision": "record_engineering_failure",
                "branch_id": branch.get("branch_id"),
                "reasons": [reason],
                "run_result": {"valid": run_result.get("valid"), "error": run_result.get("error")},
            },
            refs=refs,
        )

    def _record_expbank_failure(
        self,
        branch: dict[str, Any],
        refs: list[str],
        *,
        reason: str,
        next_step: str,
        evaluation: dict[str, Any] | None = None,
        failure: dict[str, Any] | None = None,
    ) -> None:
        """把执行或评测失败同步到对应的 ExpBank 版本。"""
        attempt_id = str(branch.get("expbank_attempt_id") or "")
        if not attempt_id:
            return
        if evaluation is not None:
            self.expbank.write_evidence_json(attempt_id, "evaluation", evaluation)
        self.expbank.update_attempt(
            attempt_id,
            status=LoopStatus.ExpBank.ENGINEERING_FAILED,
            branch_id=branch.get("branch_id"),
            error=reason,
            evaluation=evaluation or {},
            failure=dict(failure or {}),
            conclusion="当前候选存在工程问题，尚不能形成方法有效性结论。",
            next_step=next_step,
            evidence_refs=refs,
        )

    def _retry_experiment(
        self,
        exp_item: dict[str, Any],
        branch: dict[str, Any],
        run_result: dict[str, Any],
        refs: list[str],
        *,
        reason: str,
    ) -> bool:
        """在重试预算允许时重新排队实验任务。"""
        retry_count = int(exp_item.get("retry_count") or 0)
        if retry_count >= self.config.max_experiment_retries:
            return False
        # 这里重试的是本地 ExperimentRunner，不是正式 evaluator。只有通过本地执行
        # 与公开预检后才会扣 max_evaluator_submissions。
        exp_item["retry_count"] = retry_count + 1
        self.queues.evaluation.update(
            exp_item,
            status=LoopStatus.Queue.QUEUED,
            output_refs=refs,
            evidence_refs=refs,
        )
        self.artifacts.record_decision(
            {
                "decision": "retry_experiment",
                "branch_id": branch.get("branch_id"),
                "reasons": [reason],
                "retry_count": exp_item["retry_count"],
                "max_retries": self.config.max_experiment_retries,
                "run_result": {"valid": run_result.get("valid"), "error": run_result.get("error")},
            },
            refs=refs,
        )
        return True

    def _primary_metric_spec(self) -> tuple[str | None, str]:
        """读取主指标配置。"""
        benchmarks = self.goal_doc.get("benchmarks") or []
        benchmark = benchmarks[0] if benchmarks and isinstance(benchmarks[0], dict) else {}
        metric = benchmark.get("official_metric")
        if not isinstance(metric, dict):
            metric = {}
        name = metric.get("name")
        direction = str(metric.get("direction") or "higher_is_better")
        if direction not in {"higher_is_better", "lower_is_better"}:
            direction = "higher_is_better"
        return (str(name) if name else None), direction

    @staticmethod
    def _result_metric_snapshot(
        public_result: dict[str, Any],
        official_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """提取结果中的指标快照。"""
        snapshot: dict[str, Any] = {}
        public_metrics = public_result.get("metrics")
        if isinstance(public_metrics, dict):
            snapshot["public"] = public_metrics
        if isinstance(official_result, dict):
            official_metrics = official_result.get("official_metrics")
            if not isinstance(official_metrics, dict):
                official_metrics = official_result.get("metrics")
            if isinstance(official_metrics, dict):
                snapshot["official"] = official_metrics
        return snapshot

    def _update_leaderboard(
        self,
        state: dict[str, Any],
        branch: dict[str, Any],
        public_result: dict[str, Any],
        official_result: dict[str, Any] | None,
        *,
        evaluator_refs: list[str],
        commit: bool = True,
    ) -> bool:
        """根据有效主指标更新排行榜。"""
        metric_name, direction = self._primary_metric_spec()
        candidates: list[tuple[str, dict[str, Any]]] = []
        # official 放在 public 前面；同一分支同时有两类指标时，排行榜必须以正式
        # evaluator 为权威，公开分数只在没有有效 official 时回退使用。
        if isinstance(official_result, dict) and official_result.get("valid") is True:
            candidates.append(
                (
                    "official",
                    official_result.get("official_metrics")
                    if isinstance(official_result.get("official_metrics"), dict)
                    else official_result,
                )
            )
        if isinstance(public_result, dict) and public_result.get("valid") is True:
            candidates.append(
                (
                    "public",
                    public_result.get("metrics")
                    if isinstance(public_result.get("metrics"), dict)
                    else public_result,
                )
            )
        if not candidates:
            return False

        if metric_name is None:
            for _, metrics in candidates:
                numeric_keys = [
                    key
                    for key, value in metrics.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
                if numeric_keys:
                    metric_name = numeric_keys[0]
                    break
        if not metric_name:
            return False

        selected_value = None
        selected_source = None
        for source, metrics in candidates:
            raw_value = metrics.get(metric_name)
            if isinstance(raw_value, bool):
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if value != value or value in {float("inf"), float("-inf")}:
                continue
            selected_value = value
            selected_source = source
            break
        if selected_value is None:
            return False

        rs = state.setdefault("research_state", {})
        leaderboard = rs.setdefault("leaderboard", {})
        current = leaderboard.get("best_value")
        try:
            current_value = float(current) if current is not None else None
        except (TypeError, ValueError):
            current_value = None
        better = current_value is None or (
            direction == "higher_is_better" and selected_value > current_value
        ) or (
            direction == "lower_is_better" and selected_value < current_value
        )
        if not better:
            # 非最佳版本仍完整写入 ExpBank，只是不改变最终提升指针。
            return False

        # validity verifier 在提交前调用同一函数的 dry-run，确保不可信候选不会
        # 先短暂写入 leaderboard 再回滚。
        if not commit:
            return True

        leaderboard.update(
            {
                "metric": metric_name,
                "direction": direction,
                "best_value": selected_value,
                "branch_id": branch.get("branch_id"),
                "expbank_attempt_id": branch.get("expbank_attempt_id"),
                "artifact_ref": branch.get("artifact"),
                "evaluator_artifact_ref": evaluator_refs[-1] if evaluator_refs else None,
                "source": selected_source,
                "updated_at": now_ms(),
            }
        )
        self.artifacts.record_decision(
            {
                "decision": "new_best",
                "branch_id": branch.get("branch_id"),
                "metric": metric_name,
                "value": selected_value,
                "direction": direction,
                "source": selected_source,
            },
            refs=evaluator_refs,
        )
        return True

    def _run_validity_verifier(
        self,
        state: dict[str, Any],
        branch: dict[str, Any],
        *,
        public_result: dict[str, Any],
        official_result: dict[str, Any] | None,
        evaluator_refs: list[str],
    ) -> dict[str, Any]:
        """在候选晋升前运行可选 VerifierAgent，并持久化脱敏 verdict。"""

        if not self.config.validity_verifier_enabled:
            return {"status": "valid", "reasons": [], "evidence_refs": [], "violations": []}
        verifier = self.validity_verifier
        if verifier is None:  # 防御性分支；构造函数已提前校验。
            raise RuntimeError("validity verifier is enabled but not configured")

        research = state.setdefault("research_state", {})
        verifier_state = research.setdefault("validity_verifier", {})
        previous_session = verifier_state.get("session_ref")
        task = self.goal_doc.get("benchmark_task")
        task = dict(task) if isinstance(task, dict) else {}
        for private_key in (
            "private_dir",
            "evaluator_dir",
            "ground_truth_dir",
            "official_eval_cmd",
        ):
            task.pop(private_key, None)
        public_constraints = self.goal_doc.get("constraints")
        public_constraints = (
            dict(public_constraints)
            if isinstance(public_constraints, dict)
            else {}
        )
        for private_key in (
            "private_dir",
            "evaluator_dir",
            "ground_truth_dir",
            "official_eval_cmd",
            "evaluator_url",
            "evaluator_public_key",
        ):
            public_constraints.pop(private_key, None)
        context = {
            "run_id": str(research.get("goal_id") or self.workspace.name),
            "task_id": task.get("task_id"),
            "task": task,
            "public_constraints": public_constraints,
            "candidate": {
                "candidate_id": branch.get("candidate_id"),
                "branch_id": branch.get("branch_id"),
                "method_dir": branch.get("method_dir"),
                "candidate_dir": branch.get("candidate_dir"),
                "artifact": branch.get("artifact"),
            },
            "evaluation": {
                "public": public_result,
                "official": official_result,
            },
            "evaluator_refs": list(evaluator_refs),
            "trigger": "new_best_solution",
        }
        raw = verifier.verify_candidate(
            branch,
            context=context,
            session_key="validity_verifier",
            resume=bool(previous_session),
        )
        verdict = validate_validity_verdict(raw)
        session_ref = raw.get("session_ref") if isinstance(raw, dict) else None
        if session_ref:
            verifier_state["session_ref"] = str(session_ref)
        verdict_ref = self.artifacts.save_json(
            "validity_verdict",
            verdict,
            refs=evaluator_refs + list(verdict.get("evidence_refs") or []),
        )
        verifier_state.update(
            {
                "enabled": True,
                "last_status": verdict["status"],
                "last_reasons": list(verdict.get("reasons") or []),
                "last_evidence_refs": list(verdict.get("evidence_refs") or []),
                "last_verdict_ref": str(verdict_ref),
                "updated_at": now_ms(),
            }
        )
        verifier_state.setdefault("history", []).append(
            {
                "branch_id": branch.get("branch_id"),
                "candidate_id": branch.get("candidate_id"),
                "status": verdict["status"],
                "verdict_ref": str(verdict_ref),
                "evidence_refs": list(verdict.get("evidence_refs") or []),
                "updated_at": verifier_state["updated_at"],
            }
        )
        if branch.get("candidate_id"):
            candidate_verdict_ref = self.candidates.write_evidence(
                str(branch["candidate_id"]),
                "validity_verdict",
                verdict,
            )
            verifier_state["last_candidate_verdict_ref"] = str(candidate_verdict_ref)
        attempt_id = str(branch.get("expbank_attempt_id") or "")
        if attempt_id:
            expbank_ref = self.expbank.write_evidence_json(
                attempt_id,
                "validity_verdict",
                verdict,
            )
            verifier_state["last_expbank_verdict_ref"] = str(expbank_ref)
        return verdict

    def _benchmark_attempt_limit(self, state: dict[str, Any]) -> int | None:
        """返回 benchmark 尝试上限；未显式配置时不限制。"""
        constraints = self.goal_doc.get("constraints")
        if not isinstance(constraints, dict):
            constraints = {}
        configured = constraints.get("max_benchmark_attempts")
        if configured is None:
            # 只有显式正式提交上限时才沿用。两者都缺省表示由墙钟预算和背压
            # 控制循环，不能拿调度 tick 数冒充科研尝试上限。
            budget = state.get("research_state", {}).get("evaluator_budget", {})
            configured = budget.get("max_submissions")
        if configured is None:
            return None
        try:
            value = int(configured)
        except (TypeError, ValueError):
            return None
        return max(1, value)

    def _prepare_benchmark_idea_request(
        self,
        state: dict[str, Any],
        *,
        reserved: int = 0,
    ) -> dict[str, Any] | None:
        """为一次 benchmark Idea 调用构造不含私有评测信息的快照。"""

        if not self.config.idea_generation_enabled:
            return None
        queue = self.queues.benchmark_attempt
        created = queue.size()
        limit = self._benchmark_attempt_limit(state)
        if limit is not None and created + reserved >= limit:
            return None
        # Idea 和 Implement 使用不同并发槽。实现正在运行时允许生产下一条 Idea，
        # 但 queued + 后台生成中的 Idea 不超过高水位，避免无限预取旧方案。
        # Actor 的反馈续跑使用更高队列优先级，因此不会被预取的新 Idea 阻塞。
        queued_backlog = self._idea_backlog(queue)
        if queued_backlog + reserved >= self.config.idea_queue_high_watermark:
            return None

        rs = state.setdefault("research_state", {})
        leaderboard = rs.get("leaderboard") if isinstance(rs.get("leaderboard"), dict) else {}
        benchmarks = self.goal_doc.get("benchmarks") or []
        benchmark = benchmarks[0] if benchmarks and isinstance(benchmarks[0], dict) else {}
        task = self.goal_doc.get("benchmark_task")
        safe_task = dict(task) if isinstance(task, dict) else {}
        for private_key in (
            "private_dir",
            "evaluator_dir",
            "ground_truth_dir",
            "official_eval_cmd",
        ):
            safe_task.pop(private_key, None)

        previous_best = {
            "metric": leaderboard.get("metric"),
            "value": leaderboard.get("best_value"),
            "branch_id": leaderboard.get("branch_id"),
            "expbank_attempt_id": leaderboard.get("expbank_attempt_id"),
            "source": leaderboard.get("source"),
        }
        verifier_state = rs.get("validity_verifier")
        verifier_state = verifier_state if isinstance(verifier_state, dict) else {}
        verifier_feedback = {
            "enabled": bool(self.config.validity_verifier_enabled),
            "last_status": verifier_state.get("last_status"),
            "last_reasons": list(verifier_state.get("last_reasons") or [])[-5:],
            "last_evidence_refs": list(
                verifier_state.get("last_evidence_refs") or []
            )[-10:],
        }
        # Idea Agent 使用提交时刻的排行榜快照。即使它与上一条 Implement 并发，
        # 最终 attempt 仍能准确说明生成时看到了哪个 best，而不是事后改写 lineage。
        idea_context = dict(self.goal_doc)
        idea_context["benchmark_runtime"] = {
            "expbank_dir": str(self.expbank.root),
            "remaining_attempts": (
                limit - created - reserved if limit is not None else None
            ),
            "available_slots": 1,
            "previous_best": previous_best,
            # IdeaAgent 只看到脱敏的 Verifier 诊断，不能看到 verifier 私有 session
            # 或 evaluator raw evidence；这些原因用于避免重复提出同类方案。
            "validity_verifier": verifier_feedback,
        }
        debate = self._idea_debate_directive(state)
        if debate is not None:
            idea_context["benchmark_runtime"]["idea_debate"] = debate
        # attempt 层（expbank/INDEX.md）一直是通的；这里补的是 idea→idea 的派生边，
        # 让本回合能看见此前提过哪些 Idea、彼此是什么关系。提示词里「如果请求包含
        # idea_runtime.idea_graph_dir，先读 IDEAS.md」这一支在关闭时仍不成立。
        if self._idea_graph_active():
            idea_context["idea_runtime"] = self._idea_runtime_payload()
        return {
            "idea_context": idea_context,
            "experience": self._idea_experience(top_k=5),
            "benchmark": dict(benchmark),
            "benchmark_task": safe_task,
            "previous_best": previous_best,
        }

    def _check_operators(
        self,
        ideas: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """校验本回合 Idea 自报的 `operator` + `parents`。

        返回「合法的 Idea」和「违规说明」两份。只在 v2 臂上生效（v1 的 facade
        `known_ids()` 返回空集合，整条短路）。校验实现是共用的那一份
        `validate_operator`，这里只负责把图的当前状态（已存在的节点 id、成环
        探针）喂给它。

        说明为空表示全部合法。
        """

        graph = self._evolution_graph()
        passthrough = [dict(idea) for idea in ideas if isinstance(idea, Mapping)]
        if graph is None:
            return passthrough, []
        try:
            known = graph.known_ids()
        except Exception as exc:  # noqa: BLE001 - 图是上下文层，不是关键路径
            self.log(f"evolution_graph: 读取已知节点失败，跳过算子校验 err={exc!r}")
            return passthrough, []
        legal: list[dict[str, Any]] = []
        notes: list[str] = []
        for idea in ideas:
            if not isinstance(idea, Mapping):
                continue
            # 索引上显示的是方案编号 `NNNN`，磁盘主键是长 node_id，两种写法
            # 都是真地址。**先统一解析再校验**——否则 Agent 照着索引抄下来的
            # 合法编号会被判成「父节点不存在」，而它从报错里看不出自己错在哪。
            candidate = dict(idea)
            graph.resolve_parents_in_place(candidate)
            check = validate_operator(
                candidate,
                known,
                node_id=str(candidate.get("id") or "") or None,
                cycle_probe=graph.would_cycle,
            )
            if check.ok:
                legal.append(candidate)
                continue
            label = idea.get("title") or idea.get("id") or "未命名 Idea"
            notes.append(f"{label}：{check.reason}")
        return legal, notes

    def _run_benchmark_idea_request(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """调用一次 Idea Agent；该方法可以在独立线程中执行。"""

        idea_context = dict(request.get("idea_context") or {})
        experience = list(request.get("experience") or [])
        ideas = self._collect_benchmark_ideas(idea_context, experience)

        # 算子非法就把原因回给 Agent 重提，最多 OPERATOR_RETRY_LIMIT 次。**不替它
        # 改**：宿主把算子填成"最近的合法形态"等于替 agent 做了一个它没做的决定，
        # 它永远不知道自己错了，下次照错；图上还会多出一条它没打算建立的边。
        # 重提到上限仍非法的整条丢弃——丢一条提案，好过在图里留一条假边。
        for _ in range(OPERATOR_RETRY_LIMIT):
            legal, violations = self._check_operators(ideas)
            if not violations:
                return {**request, "ideas": legal}
            self.log("evolution_graph: 算子非法，重提 — " + "；".join(violations))
            retry_context = copy.deepcopy(idea_context)
            runtime = retry_context.setdefault("benchmark_runtime", {})
            if isinstance(runtime, dict):
                runtime["operator_violation"] = {
                    "reasons": violations,
                    "instruction": (
                        "上一条 Idea 的 operator/parents 不合法。请重新提交一条："
                        "operator 必填且只能是 innovate / exploit / cross / ensemble；"
                        "innovate 的 parents 必须恰好 [\"ROOT\"]，"
                        "exploit 恰好 1 个 GRAPH.md 里已存在的方案，"
                        "cross 与 ensemble 各至少 2 个已存在方案。"
                        "parents 里写 GRAPH.md 行首那个四位编号即可。"
                    ),
                }
            retried = self._collect_benchmark_ideas(retry_context, experience)
            # 重提返回空说明 Agent 这一轮不再产出，继续要下去只是空转。
            if not retried:
                break
            ideas = retried

        legal, violations = self._check_operators(ideas)
        if violations:
            self.log(
                f"evolution_graph: 重提 {OPERATOR_RETRY_LIMIT} 次仍非法，"
                f"丢弃 {len(violations)} 条 — " + "；".join(violations)
            )
        return {**request, "ideas": legal}

    def _collect_benchmark_ideas(
        self,
        idea_context: Mapping[str, Any],
        experience: Sequence[Any],
    ) -> list[dict[str, Any]]:
        """调用一次 Idea Agent 并按配对模式截断。"""

        raw_ideas = self.agent_facility.generate_ideas(
            dict(idea_context),
            list(experience),
        )
        # 通常一次调用只发布一条 Idea。辩论的配对模式是唯一例外：它同时返回
        # origin 与 debated 两条，必须都入队才能构成配对样本，因此不能在这里截断。
        ideas = [idea for idea in raw_ideas if isinstance(idea, dict)]
        if not self._idea_pair_enabled():
            ideas = ideas[:1]
        return ideas

    def _idea_pair_enabled(self) -> bool:
        """辩论配对模式是否开启。"""

        return bool(
            self.config.idea_debate_enabled and self.config.idea_debate_emit_pair
        )

    def _enqueue_benchmark_idea_result(
        self,
        state: dict[str, Any],
        result: dict[str, Any],
    ) -> int:
        """由调度主线程编号并持久化后台 Idea Agent 的结果。"""

        queue = self.queues.benchmark_attempt
        limit = self._benchmark_attempt_limit(state)
        ideas = [idea for idea in result.get("ideas", []) if isinstance(idea, dict)]
        if not self._idea_pair_enabled():
            ideas = ideas[:1]
        if not ideas:
            return 0

        benchmark = result.get("benchmark")
        benchmark = dict(benchmark) if isinstance(benchmark, dict) else {}
        safe_task = result.get("benchmark_task")
        safe_task = dict(safe_task) if isinstance(safe_task, dict) else {}
        previous_best = result.get("previous_best")
        previous_best = (
            dict(previous_best) if isinstance(previous_best, dict) else {}
        )
        scheduled = 0
        for idea in ideas:
            created = queue.size()
            if limit is not None and created >= limit:
                break
            if self._schedule_one_benchmark_idea(
                queue,
                idea,
                attempt_number=created + 1,
                benchmark=benchmark,
                safe_task=safe_task,
                previous_best=previous_best,
            ):
                scheduled += 1
        return scheduled

    def _record_benchmark_idea_node(self, attempt: dict[str, Any]) -> None:
        """把一条 benchmark Idea 落成 Idea 图节点，并就地敲定它的最终 id。

        必须在 attempt 被序列化进 artifact / 队列**之前**调用：撞车时这里会改写
        ``attempt["id"]``，晚调用会让 artifact 里的 id 与图节点对不上。

        benchmark 工作流没有 Gate，因此走 admit_without_review 并显式记一条
        "未经 Judge" 的 decision，而不是伪造一条 verdict=pass 的 Review——与
        _enqueue_idea_without_gate 同一条纪律。
        """

        if not self._idea_graph_active():
            return
        try:
            decision_ref = self.artifacts.record_decision(
                {
                    "decision": "enqueue_without_gate",
                    "idea_id": attempt.get("id"),
                    "reason": "benchmark_workflow_has_no_idea_gate",
                },
                refs=[],
            )
            try:
                self.idea_graph.submit(
                    attempt,
                    actor_id="idea_agent_main",
                    artifact_refs=[decision_ref],
                    goal_contract_version=self._goal_contract_version(),
                )
            except FileExistsError:
                # Idea 的 id 由 Agent 自带。图一旦可见，Agent 就可能照抄一个已存在
                # 的 id；此时换号重发，绝不能因为图写不进去就把这次 attempt 丢掉。
                stale = attempt.get("id")
                attempt["id"] = new_id("benchmark_idea")
                self.log(
                    f"idea graph: duplicate idea id {stale}; "
                    f"reissued as {attempt['id']}"
                )
                self.idea_graph.submit(
                    attempt,
                    actor_id="idea_agent_main",
                    artifact_refs=[decision_ref],
                    goal_contract_version=self._goal_contract_version(),
                )
            self.idea_graph.admit_without_review(
                str(attempt["id"]),
                artifact_refs=[decision_ref],
            )
        except Exception as exc:  # noqa: BLE001
            # 图是上下文层，不是关键路径：写失败只记日志，attempt 照常排程。
            self.log(f"idea graph: failed to record node for benchmark idea: {exc}")

    def _parent_artifacts(
        self, parents: Iterable[Any]
    ) -> list[dict[str, Any]]:
        """列出多父算子的每个父节点已经留在盘上的产物目录。

        `ensemble` 要直接加载父节点训好的权重，光给一串节点 id 是用不了的——
        Agent 拿到 id 也找不到 ckpt 在哪。父的 `attempts[].paths` 本来就记着
        `code` 和 `output` 的绝对路径，这里只是把它搬到 Idea 上。

        只对多父算子填，且**只列真实存在的目录**：路径是宿主实测，不是自报。
        父节点读不到就跳过——图是上下文层，不能因为它让排程失败。
        """

        artifacts: list[dict[str, Any]] = []
        for raw in parents or []:
            node_id = str(raw or "").strip()
            if not node_id or node_id == ROOT_ID:
                continue
            try:
                record = self.idea_graph.read(node_id)
            except Exception:  # noqa: BLE001 - 读不到就当这个父没有产物
                continue
            if not isinstance(record, Mapping):
                continue
            attempts = [
                item
                for item in (record.get("attempts") or [])
                if isinstance(item, Mapping) and isinstance(item.get("paths"), Mapping)
            ]
            if not attempts:
                continue
            # 优先 status=="best"；没有就取分数最高的那次。
            best = next(
                (item for item in attempts if item.get("status") == "best"),
                None,
            )
            if best is None:
                scored = [
                    item for item in attempts if item.get("score") is not None
                ]
                if not scored:
                    continue
                best = max(scored, key=lambda item: float(item["score"]))
            paths = best.get("paths") or {}
            entry: dict[str, Any] = {
                "node_id": node_id,
                "title": (record.get("idea") or {}).get("title"),
                "best_score": record.get("best_score"),
                "attempt_id": best.get("attempt_id"),
            }
            for key in ("code", "output"):
                value = str(paths.get(key) or "")
                if value and Path(value).exists():
                    entry[key] = value
            # 权重按约定放在 output 的同级 `weights/`（见 implement 提示词）。
            output = str(paths.get("output") or "")
            if output:
                weights = Path(output).parent / "weights"
                if weights.is_dir() and any(weights.iterdir()):
                    entry["weights"] = str(weights)
            artifacts.append(entry)
        return artifacts

    def _schedule_one_benchmark_idea(
        self,
        queue: JsonlQueue,
        idea: Mapping[str, Any],
        *,
        attempt_number: int,
        benchmark: dict[str, Any],
        safe_task: dict[str, Any],
        previous_best: dict[str, Any],
    ) -> bool:
        """把一条 Idea 编号、校验资源申报并推入待实现队列。"""

        attempt = dict(idea)
        attempt.setdefault("id", new_id("benchmark_idea"))
        try:
            attempt["resource_request"] = self._normalize_resource_request(
                attempt.get("resource_request")
            )
        except ValueError as exc:
            rejected_ref = self.artifacts.save_json(
                "benchmark_attempt_rejected",
                {
                    **attempt,
                    "attempt_number": attempt_number,
                    "status": "resource_request_rejected",
                    "error": str(exc),
                    "created_at": now_ms(),
                },
            )
            self.artifacts.record_decision(
                {
                    "decision": "reject_resource_request",
                    "attempt_id": attempt.get("id"),
                    "reasons": [str(exc)],
                },
                refs=[rejected_ref],
            )
            return False
        attempt.update(
            {
                "attempt_number": attempt_number,
                "benchmark": {
                    "name": benchmark.get("name"),
                    "official_metric": benchmark.get("official_metric"),
                    "hidden_test_access": benchmark.get(
                        "hidden_test_access",
                        "forbidden",
                    ),
                },
                "benchmark_task": safe_task,
                "previous_best": previous_best,
                "source_branch_id": previous_best.get("branch_id"),
                "parent_attempt_id": previous_best.get("expbank_attempt_id"),
            }
        )
        # 多父算子要的是父的**产物**，不是父的 id。单父的 exploit 走
        # `previous_best`/`parent_attempt_id` 那条老路，不重复给一份。
        if str(attempt.get("operator") or "") in MULTI_PARENT_OPERATORS:
            parent_artifacts = self._parent_artifacts(attempt.get("parents"))
            if parent_artifacts:
                attempt["parent_artifacts"] = parent_artifacts
        attempt.setdefault(
            "validation_plan",
            ["运行 benchmark runner", "调用可信 evaluator"],
        )
        attempt.setdefault("created_at", now_ms())
        # 先落图节点再序列化：撞车改号发生在这一步，之后 attempt["id"] 不再变动。
        self._record_benchmark_idea_node(attempt)
        # benchmark_attempt artifact 保存 Idea 本身，queue item 保存调度状态；
        # 两者通过 evidence_refs 关联。
        attempt_ref = self.artifacts.save_json("benchmark_attempt", attempt)
        # 只有"内容真的被改过"的方案才插队。判无意见的 Idea 同样带 idea_debate
        # 元数据，但内容与未评审时一模一样，给它加速既无因果意义，也会稀释
        # "插队是否有用"的测量——实测 v3 批次 22 次辩论里 18 次判无意见，
        # 若一并加速，队列里 priority=2 的绝大多数都是没改过的方案。
        queue.push(
            attempt,
            item_type="benchmark_attempt",
            priority=self._attempt_priority(attempt),
            evidence_refs=[attempt_ref],
        )
        self.artifacts.record_decision(
            {
                "decision": "schedule_benchmark_attempt",
                "attempt_id": attempt["id"],
                "attempt_number": attempt_number,
                "source_branch_id": attempt.get("source_branch_id"),
                "reasons": ["benchmark attempt budget remains"],
                "debate_arm": (attempt.get("idea_debate") or {}).get("arm"),
                "debate_pair_id": (attempt.get("idea_debate") or {}).get("pair_id"),
            },
            refs=[attempt_ref],
        )
        return True

    def _enqueue_benchmark_attempts(self, state: dict[str, Any]) -> int:
        """同步调用一次 Idea Agent，并把候选路线放入 benchmark 实现队列。"""

        request = self._prepare_benchmark_idea_request(state)
        if request is None:
            return 0
        result = self._run_benchmark_idea_request(request)
        return self._enqueue_benchmark_idea_result(state, result)

    def _complete_benchmark_if_done(self, state: dict[str, Any]) -> bool:
        """在尝试预算耗尽且流水线清空后结束 benchmark 工作流。"""
        if not self.benchmark_managed:
            return False
        queue = self.queues.benchmark_attempt
        limit = self._benchmark_attempt_limit(state)
        if limit is None or queue.size() < limit:
            return False
        # 仅“创建够了 attempt”不能结束；必须等 Implement 与 Experiment 的 queued/
        # running 条目全部排空，确保在途结果已经进入 Evaluator 和 ExpBank。
        active = (
            queue.size(LoopStatus.Queue.QUEUED)
            + queue.size(LoopStatus.Queue.RUNNING)
            + self.queues.evaluation.size(LoopStatus.Queue.QUEUED)
            + self.queues.evaluation.size(LoopStatus.Queue.WAITING_RESOURCES)
            + self.queues.evaluation.size(LoopStatus.Queue.RUNNING)
        )
        if active:
            return False
        rs = state.setdefault("research_state", {})
        if rs.get("status") not in {
            LoopStatus.Research.PAUSED,
            LoopStatus.Research.STOPPED,
            LoopStatus.Research.FAILED,
        }:
            rs["status"] = LoopStatus.Research.COMPLETED
            rs["termination_reason"] = "benchmark_attempt_budget_exhausted"
            self.log("benchmark attempt budget exhausted; workflow completed")
            return True
        return False

    def _record_benchmark_result(
        self,
        state: dict[str, Any],
        exp_item: dict[str, Any],
        branch: dict[str, Any],
        public_result: dict[str, Any],
        official_result: dict[str, Any] | None,
        refs: list[str],
    ) -> None:
        """直接记录 benchmark 指标，不调用额外智能体裁判。"""
        self.queues.evaluation.update(
            exp_item,
            status=LoopStatus.Queue.FINISHED,
            output_refs=refs,
            evidence_refs=refs,
        )
        metrics = self._result_metric_snapshot(public_result, official_result)
        # benchmark 自带 evaluator 已经给出唯一正式判断，因此这里只做事实记录，
        # 不再调用 LLM Result Analyst 重新解释分数。
        validity_invalid = bool(branch.get("validity_invalid"))
        validity_error = branch.get("validity_verifier_error")
        branch_status = (
            LoopStatus.Branch.FAILED
            if validity_invalid or validity_error
            else LoopStatus.Branch.EVALUATED
        )
        outcome_status = (
            LoopStatus.Outcome.FAILED
            if validity_invalid or validity_error
            else LoopStatus.Outcome.EVALUATED
        )
        self._upsert_branch_state(
            state,
            branch,
            branch_status,
            evidence_refs=refs,
        )
        self.experience.upsert(
            {
                "type": "benchmark_attempt",
                "benchmark": public_result.get("benchmark"),
                "summary": f"branch {branch.get('branch_id')} benchmark result",
                "outcome": {
                    "status": outcome_status,
                    "metrics": metrics,
                    "leaderboard": state.get("research_state", {}).get("leaderboard", {}),
                },
                "artifact_refs": refs,
            }
        )
        self.artifacts.record_decision(
            {
                "decision": "record_benchmark_result",
                "branch_id": branch.get("branch_id"),
                "reasons": ["benchmark evaluator is the sole result authority"],
                "metrics": metrics,
            },
            refs=refs,
        )
        self._complete_benchmark_if_done(state)

    def _process_evaluation_result(
        self,
        state: dict[str, Any],
        exp_item: dict[str, Any],
        run_result: dict[str, Any],
        evaluation_bundle: dict[str, Any] | None = None,
    ) -> None:
        """串行提交实验与 evaluator 结果到状态、预算和证据存储。"""
        rs = state.setdefault("research_state", {})
        branch = exp_item.get("payload") or {}
        # Runner 的 stdout/stderr 和提交路径先作为执行证据落盘；执行无效时不会
        # 消耗正式 evaluator 提交预算。
        run_ref = self.artifacts.save_json(
            "experiment_run",
            run_result,
            refs=exp_item.get("evidence_refs", []),
        )
        refs = [run_ref]
        expbank_attempt_id = str(branch.get("expbank_attempt_id") or "")
        candidate_id = str(branch.get("candidate_id") or "")
        actor_id = str(branch.get("actor_id") or "")
        if actor_id:
            self.actors.record_run(actor_id)
        if candidate_id:
            self.candidates.write_evidence(candidate_id, "run", run_result)
        if expbank_attempt_id:
            self.expbank.write_evidence_json(expbank_attempt_id, "run", run_result)
            self.expbank.write_evidence_text(
                expbank_attempt_id,
                "stdout",
                str(run_result.get("stdout") or ""),
            )
            self.expbank.write_evidence_text(
                expbank_attempt_id,
                "stderr",
                str(run_result.get("stderr") or ""),
            )

        if run_result.get("artifact"):
            branch["artifact"] = run_result["artifact"]
        artifact = str(branch.get("artifact") or "")
        if not run_result.get("valid") or not artifact:
            reason = str(run_result.get("error") or "experiment runner failed")
            if self._retry_experiment(exp_item, branch, run_result, refs, reason=reason):
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.EVALUATION_QUEUED,
                    evidence_refs=refs,
                )
                return
            self._archive_failed_experiment(exp_item, branch, run_result, refs, reason=reason)
            self._upsert_branch_state(
                state,
                branch,
                LoopStatus.Branch.ENGINEERING_FAILED,
                evidence_refs=refs,
            )
            self._record_expbank_failure(
                branch,
                refs,
                reason=reason,
                next_step="根据 run.json、stdout.log 和 stderr.log 修复代码。",
                failure={
                    "failure_stage": str(
                        run_result.get("stage") or "canonical_run"
                    ),
                    "error_code": str(
                        run_result.get("error_code") or "canonical_run_failed"
                    ),
                    "return_code": run_result.get("returncode"),
                    "signal": run_result.get("signal"),
                    "timed_out": bool(run_result.get("timed_out")),
                    "submitted": True,
                    "retryable": bool(run_result.get("retryable", True)),
                    "message": reason,
                    "suggested_action": (
                        "根据 run.json、stdout.log 和 stderr.log 修复代码。"
                    ),
                    "evidence_refs": refs,
                    "diagnostics": {
                        key: run_result.get(key)
                        for key in (
                            "timeout_sec",
                            "expected_runtime_sec",
                            "duration_ms",
                            "termination_reason",
                            "memory_limit_bytes",
                            "memory_limit_exceeded",
                            "resource_request",
                            "resource_lease",
                            "resource_admission",
                            "command",
                            "entrypoint",
                        )
                        if run_result.get(key) is not None
                    },
                },
            )
            if candidate_id:
                self.candidates.update(
                    candidate_id,
                    status=LoopStatus.Candidate.RUN_FAILED,
                    error=reason,
                    artifact=artifact or None,
                )
            self._finish_actor_candidate(
                state,
                branch,
                kind=str(run_result.get("failure_kind") or "run_failed"),
                feedback={
                    "stage": run_result.get("stage") or "canonical_run",
                    "error_code": run_result.get("error_code") or "canonical_run_failed",
                    "error": reason,
                    "retryable": run_result.get("retryable", True),
                    "returncode": run_result.get("returncode"),
                    "timed_out": run_result.get("timed_out"),
                    "timeout_sec": run_result.get("timeout_sec"),
                    "expected_runtime_sec": run_result.get("expected_runtime_sec"),
                    "termination_reason": run_result.get("termination_reason"),
                    "memory_limit_bytes": run_result.get("memory_limit_bytes"),
                    "memory_limit_exceeded": run_result.get(
                        "memory_limit_exceeded"
                    ),
                    "resource_request": run_result.get("resource_request"),
                    "resource_lease": run_result.get("resource_lease"),
                    "resource_admission": run_result.get("resource_admission"),
                    "process_group_isolated": run_result.get(
                        "process_group_isolated"
                    ),
                    "duration_ms": run_result.get("duration_ms"),
                    "command": run_result.get("command"),
                    "candidate_id": candidate_id or None,
                    "candidate_dir": run_result.get("candidate_dir"),
                    "method_dir": run_result.get("method_dir"),
                    "entrypoint": run_result.get("entrypoint"),
                    "run_evidence_ref": run_ref,
                    "stdout": str(run_result.get("stdout") or "")[-3000:],
                    "stderr": str(run_result.get("stderr") or "")[-3000:],
                    "expbank_attempt_id": expbank_attempt_id or None,
                },
            )
            return

        try:
            # 评测调用、正式提交预算更新和结果分析故意保留在主线程路径。
            # Harness 使用单一 canonical output，且正式适配器默认不支持并发调用。
            artifact_ref = self._artifact_ref(run_result, branch)
            if artifact_ref is None:
                raise ValueError("benchmark run 未返回 ArtifactRef")
            if evaluation_bundle is not None and not evaluation_bundle.get("valid"):
                raise RuntimeError(
                    str(evaluation_bundle.get("error") or "evaluator worker failed")
                )
            validation_result = (
                evaluation_bundle.get("validation")
                if evaluation_bundle is not None
                else self.benchmark_facility.validate_artifact(artifact_ref)
            )
            if not isinstance(validation_result, dict):
                raise TypeError(
                    f"artifact validator returned {type(validation_result).__name__}, expected dict"
                )
            validation_ref = self.artifacts.save_json(
                "artifact_validation",
                validation_result,
                refs=[run_ref],
            )
            refs.append(validation_ref)
            if validation_result.get("valid") is not True:
                reason = str(
                    validation_result.get("error")
                    or validation_result.get("reason")
                    or "artifact validation failed"
                )
                if self._retry_experiment(exp_item, branch, run_result, refs, reason=reason):
                    self._upsert_branch_state(
                        state,
                        branch,
                        LoopStatus.Branch.EVALUATION_QUEUED,
                        evidence_refs=refs,
                    )
                    return
                self._archive_failed_experiment(
                    exp_item,
                    branch,
                    run_result,
                    refs,
                    reason=reason,
                )
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.ENGINEERING_FAILED,
                    evidence_refs=refs,
                )
                validation_agent_view = self.benchmark_facility.agent_view(
                    validation_result,
                    source="artifact_validation",
                )
                self._record_expbank_failure(
                    branch,
                    refs,
                    reason=reason,
                    next_step="修复提交格式或缺失文件后，在同一 lineage 创建新版本。",
                    evaluation=validation_agent_view,
                    failure={
                        "failure_stage": "artifact_validation",
                        "error_code": str(
                            validation_agent_view.get("error_code")
                            or "artifact_validation_failed"
                        ),
                        "return_code": validation_agent_view.get("returncode"),
                        "signal": validation_agent_view.get("signal"),
                        "timed_out": bool(validation_agent_view.get("timed_out")),
                        "submitted": True,
                        "retryable": bool(
                            validation_agent_view.get("retryable", True)
                        ),
                        "message": reason,
                        "suggested_action": (
                            "修复提交格式或缺失文件后，在同一 lineage 创建新版本。"
                        ),
                        "evidence_refs": refs,
                        "diagnostics": validation_agent_view,
                    },
                )
                if candidate_id:
                    self.candidates.write_evidence(
                        candidate_id,
                        "validation",
                        validation_result,
                    )
                    self.candidates.update(
                        candidate_id,
                        status=LoopStatus.Candidate.VALIDATION_FAILED,
                        error=reason,
                        artifact=artifact,
                    )
                self._finish_actor_candidate(
                    state,
                    branch,
                    kind="validation_failed",
                    feedback=validation_agent_view,
                )
                return
            public_result = (
                evaluation_bundle.get("public")
                if evaluation_bundle is not None
                else self.benchmark_facility.run_public_evaluation(artifact_ref)
            )
            if not isinstance(public_result, dict):
                public_result = {
                    "valid": False,
                    "source": "public_eval",
                    "artifact": artifact,
                    "error": (
                        "public evaluator returned "
                        f"{type(public_result).__name__}, expected dict"
                    ),
                }
            public_ref = self.artifacts.save_json("public_eval", public_result, refs=[run_ref])
            refs.append(public_ref)
            if public_result.get("valid") is not True:
                reason = str(
                    public_result.get("error")
                    or public_result.get("reason")
                    or "public evaluator returned invalid result"
                )
                self._archive_failed_experiment(
                    exp_item,
                    branch,
                    public_result,
                    refs,
                    reason=reason,
                )
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.ENGINEERING_FAILED,
                    evidence_refs=refs,
                )
                public_agent_result = self.benchmark_facility.agent_view(
                    public_result,
                    source="public_eval",
                )
                self._record_expbank_failure(
                    branch,
                    refs,
                    reason=reason,
                    next_step="读取公开 evaluator 的安全诊断并修复当前方法。",
                    evaluation=public_agent_result,
                    failure={
                        "failure_stage": "public_evaluation",
                        "error_code": str(
                            public_agent_result.get("error_code")
                            or "public_evaluation_failed"
                        ),
                        "return_code": public_agent_result.get("returncode"),
                        "signal": public_agent_result.get("signal"),
                        "timed_out": bool(public_agent_result.get("timed_out")),
                        "submitted": True,
                        "retryable": bool(
                            public_agent_result.get("retryable", True)
                        ),
                        "message": reason,
                        "suggested_action": (
                            "读取公开 evaluator 的安全诊断并修复当前方法。"
                        ),
                        "evidence_refs": refs,
                        "diagnostics": public_agent_result,
                    },
                )
                if candidate_id:
                    self.candidates.write_evidence(
                        candidate_id,
                        "evaluation",
                        public_result,
                    )
                    self.candidates.update(
                        candidate_id,
                        status=LoopStatus.Candidate.EVALUATION_FAILED,
                        error=reason,
                        artifact=artifact,
                    )
                self._finish_actor_candidate(
                    state,
                    branch,
                    kind="public_eval_failed",
                    feedback=public_agent_result,
                )
                return
            public_agent_result = self.benchmark_facility.agent_view(
                public_result,
                source="public_eval",
            )
            public_view_ref = self.artifacts.save_json(
                "evaluator_agent_view",
                public_agent_result,
                refs=[public_ref],
            )
            refs.append(public_view_ref)
            official_result = None
            official_ref = None
            official_agent_result = None
            budget = rs.setdefault(
                "evaluator_budget", {"max_submissions": None, "used_submissions": 0}
            )
            max_sub = budget.get("max_submissions")
            used = int(budget.get("used_submissions") or 0)
            actor_official_allowed = self._actor_official_budget_available(branch)
            official_called = False
            if evaluation_bundle is not None:
                official_called = bool(evaluation_bundle.get("official_called"))
                official_result = evaluation_bundle.get("official")
            elif (
                (max_sub is None or used < int(max_sub))
                and actor_official_allowed
            ):
                # 只有本地执行和公开预检都通过后才扣正式提交预算。EvaluatorAdapter
                # 会在此调用内发布指定快照，避免评错并发分支的输出。
                official_called = True
                official_value = self.evaluation_facility.evaluate(
                    self._evaluation_request(branch, artifact_ref)
                )
                if not isinstance(official_value, EvaluationResult):
                    official_result = {
                        "valid": False,
                        "source": "official_evaluator",
                        "artifact": artifact,
                        "error": (
                            "evaluation facility returned "
                            f"{type(official_value).__name__}, "
                            "expected EvaluationResult"
                        ),
                    }
                else:
                    official_result = official_value.to_dict()
            if official_called:
                official_ref = self.artifacts.save_json(
                    "official_eval",
                    official_result,
                    refs=[public_ref],
                )
                refs.append(official_ref)
                # 异步路径在提交 Future 时只做内存预留；只有主线程确认 evaluator
                # 确实被调用后，才把正式预算和审计记录持久化。
                budget["used_submissions"] = used + 1
                rs.setdefault("audit", {}).setdefault("evaluator_calls", []).append(
                    {
                        "ts": now_ms(),
                        "branch_id": branch.get("branch_id"),
                        "artifact_ref": official_ref,
                    }
                )
                if official_result.get("valid") is not True:
                    reason = str(
                        official_result.get("error")
                        or official_result.get("reason")
                        or "official evaluator returned invalid result"
                    )
                    # 正式评测失败通常表示 Candidate 输出缺失、格式错误或运行超时。
                    # 先生成脱敏视图再确定性路由回原 Actor，不能退回公开格式检查并
                    # 把该候选误记成一条正常科研结论。
                    official_agent_result = self.evaluation_facility.agent_view(
                        official_result,
                        source="official_evaluator",
                    )
                    official_view_ref = self.artifacts.save_json(
                        "evaluator_agent_view",
                        official_agent_result,
                        refs=[official_ref],
                    )
                    refs.append(official_view_ref)
                    self.artifacts.record_decision(
                        {
                            "decision": "official_eval_invalid",
                            "branch_id": branch.get("branch_id"),
                            "reasons": [reason],
                        },
                        refs=[public_ref, official_ref, official_view_ref],
                    )
                    self._archive_failed_experiment(
                        exp_item,
                        branch,
                        official_result,
                        refs,
                        reason=reason,
                    )
                    self._upsert_branch_state(
                        state,
                        branch,
                        LoopStatus.Branch.ENGINEERING_FAILED,
                        evidence_refs=refs,
                    )
                    self._record_expbank_failure(
                        branch,
                        refs,
                        reason=reason,
                        next_step=(
                            "读取正式 evaluator 的公开诊断，修复当前 Candidate 后重新提交。"
                        ),
                        evaluation=official_agent_result,
                        failure={
                            "failure_stage": "official_evaluation",
                            "error_code": str(
                                official_agent_result.get("error_code")
                                or "official_evaluation_failed"
                            ),
                            "return_code": official_agent_result.get("returncode"),
                            "signal": official_agent_result.get("signal"),
                            "timed_out": bool(
                                official_agent_result.get("timed_out")
                                or (
                                    official_agent_result.get("diagnostics_public")
                                    or {}
                                ).get("timed_out")
                            ),
                            "submitted": True,
                            "retryable": bool(
                                official_agent_result.get("retryable", True)
                            ),
                            "message": reason,
                            "suggested_action": (
                                "读取正式 evaluator 的公开诊断，修复当前 Candidate 后重新提交。"
                            ),
                            "evidence_refs": refs,
                            "diagnostics": official_agent_result,
                        },
                    )
                    if candidate_id:
                        self.candidates.write_evidence(
                            candidate_id,
                            "evaluation",
                            {
                                "public": public_agent_result,
                                "official": official_agent_result,
                            },
                        )
                        self.candidates.update(
                            candidate_id,
                            status=LoopStatus.Candidate.EVALUATION_FAILED,
                            error=reason,
                            artifact=artifact,
                            official_evaluated=True,
                            evidence_refs=refs,
                        )
                    self._finish_actor_candidate(
                        state,
                        branch,
                        kind="evaluation_failed",
                        feedback=official_agent_result,
                        official_evaluated=True,
                    )
                    return
                else:
                    # 原始正式响应保存在 official_eval artifact；后续 Agent 和 ExpBank
                    # 只能接收经过字段白名单过滤的 agent_view。
                    official_agent_result = self.evaluation_facility.agent_view(
                        official_result,
                        source="official_evaluator",
                    )
                    official_view_ref = self.artifacts.save_json(
                        "evaluator_agent_view",
                        official_agent_result,
                        refs=[official_ref],
                    )
                    refs.append(official_view_ref)
            elif evaluation_bundle is not None:
                self.artifacts.record_decision(
                    {
                        "decision": "skip_official_eval",
                        "branch_id": branch.get("branch_id"),
                        "actor_id": actor_id or None,
                        "reasons": ["official evaluator slot was not admitted"],
                    },
                    refs=[public_ref],
                )
            elif max_sub > 0 and used >= max_sub:
                self.artifacts.record_decision(
                    {
                        "decision": "skip_official_eval",
                        "branch_id": branch.get("branch_id"),
                        "reasons": ["evaluator submission budget exhausted"],
                    },
                    refs=[public_ref],
                )
            elif max_sub > 0 and not actor_official_allowed:
                self.artifacts.record_decision(
                    {
                        "decision": "skip_official_eval",
                        "branch_id": branch.get("branch_id"),
                        "actor_id": actor_id or None,
                        "reasons": ["actor official evaluator budget exhausted"],
                    },
                    refs=[public_ref],
                )
            evaluator_refs = [public_ref]
            if official_ref:
                evaluator_refs.append(official_ref)
            would_promote = self._update_leaderboard(
                state,
                branch,
                public_result,
                official_result,
                evaluator_refs=evaluator_refs,
                commit=False,
            )
            validity_verdict: dict[str, Any] | None = None
            validity_error: str | None = None
            if would_promote and self.config.validity_verifier_enabled:
                try:
                    validity_verdict = self._run_validity_verifier(
                        state,
                        branch,
                        public_result=public_agent_result,
                        official_result=official_agent_result,
                        evaluator_refs=evaluator_refs,
                    )
                    verdict_ref = (
                        state.get("research_state", {})
                        .get("validity_verifier", {})
                        .get("last_verdict_ref")
                    )
                    if verdict_ref:
                        refs.append(str(verdict_ref))
                except Exception as exc:  # noqa: BLE001 - verifier is an optional worker
                    validity_error = f"{type(exc).__name__}: {exc}"
                    branch["validity_verifier_error"] = validity_error
                    error_ref = self.artifacts.save_json(
                        "validity_verifier_error",
                        {
                            "status": "verifier_error",
                            "error": validity_error,
                            "branch_id": branch.get("branch_id"),
                            "candidate_id": branch.get("candidate_id"),
                        },
                        refs=evaluator_refs,
                    )
                    state.setdefault("research_state", {}).setdefault(
                        "validity_verifier", {}
                    ).update(
                        {
                            "enabled": True,
                            "last_status": "verifier_error",
                            "last_error": validity_error,
                            "last_verdict_ref": str(error_ref),
                            "updated_at": now_ms(),
                        }
                    )
                if validity_verdict is not None and validity_verdict["status"] == "invalid":
                    branch["validity_invalid"] = True
            promoted = False
            if not validity_error and not branch.get("validity_invalid"):
                promoted = self._update_leaderboard(
                    state,
                    branch,
                    public_result,
                    official_result,
                    evaluator_refs=evaluator_refs,
                    commit=True,
                )
            if expbank_attempt_id:
                # ExpBank 是 Agent 可直接读取的经验池，因此这里只写脱敏结果，
                # 不写 evaluator 的 raw stdout、隐藏诊断或逐样本明细。
                selected_evaluation = official_agent_result or public_agent_result
                self.expbank.write_evidence_json(
                    expbank_attempt_id,
                    "evaluation",
                    selected_evaluation,
                )
                # 每条 attempt 记录自己的成绩：分数取本次评测指标，与排行榜无关。
                # `promoted` 来自 _update_leaderboard 的返回值，即"本次是否刷新最佳"；
                # 不能用 branch_id 比对排行榜——同一 lineage 的所有 attempt 共用
                # branch_id，一旦该 branch 夺冠，其后每次 attempt（哪怕更差）都会被
                # 误判为最佳并被写上排行榜分数，污染 Agent 读取的经验池。
                leaderboard = state.get("research_state", {}).get("leaderboard", {})
                metrics = (
                    selected_evaluation.get("official_metrics")
                    or selected_evaluation.get("metrics")
                    or {}
                )
                score = None
                metric_name = leaderboard.get("metric") or self._primary_metric_spec()[0]
                value = metrics.get(metric_name) if metric_name else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    score = float(value)
                attempt_record = self.expbank.read_attempt(expbank_attempt_id)
                paths = dict(attempt_record.get("paths") or {})
                paths["output"] = artifact
                attempt_status = (
                    LoopStatus.ExpBank.FAILED
                    if branch.get("validity_invalid")
                    else LoopStatus.ExpBank.BEST
                    if promoted
                    else LoopStatus.ExpBank.EVALUATED
                )
                attempt_conclusion = (
                    "Validity Verifier 判定 invalid，候选标记为 buggy_solution，等待 refine。"
                    if branch.get("validity_invalid")
                    else "正式评测有效，当前候选成为新的最佳方法。"
                    if promoted
                    else "评测有效，但未超过当前最佳方法。"
                )
                self.expbank.update_attempt(
                    expbank_attempt_id,
                    status=attempt_status,
                    branch_id=branch.get("branch_id"),
                    evaluation=selected_evaluation,
                    score=score,
                    promoted=promoted,
                    conclusion=attempt_conclusion,
                    paths=paths,
                    validity_verdict=validity_verdict
                    if validity_verdict is not None
                    else ({"status": "verifier_error", "error": validity_error} if validity_error else None),
                    evidence_refs=refs,
                )
                # 给图装上海拔。分数只有评测完才存在，所以回填必须挂在这里，
                # 不能挂在 link_attempt——那时 attempt 刚建壳，一分都还没有。
                # 上一批 README §七.5 把这个时序列为未决，答案就是"拿不到"。
                #
                # 同一 attempt_id 是 upsert：重试挂回同一个方案节点，不新建节点。
                graph = self._evolution_graph()
                node_id = str(attempt_record.get("idea_id") or "")
                if graph is not None and node_id:
                    try:
                        graph.record_attempt_result(
                            node_id,
                            expbank_attempt_id,
                            status=attempt_status,
                            score=score,
                            conclusion=attempt_conclusion,
                            paths=paths,
                            evidence_refs=refs,
                        )
                    except Exception as exc:  # noqa: BLE001 - 图是上下文层，不是关键路径
                        self.log(
                            f"evolution_graph: 回填分数失败 node={node_id} "
                            f"attempt={expbank_attempt_id} err={exc!r}"
                        )
            if candidate_id:
                # Candidate 目录位于 Agent 可见 run 内，因此这里只能写白名单视图。
                # 可信 evaluator 的原始 response 由 evaluator worker 写入 run 外的
                # trusted evidence store，不通过 Candidate/ArtifactStore 回流。
                candidate_evaluation = {
                    "public": public_agent_result,
                    "official": official_agent_result,
                }
                self.candidates.write_evidence(
                    candidate_id,
                    "evaluation",
                    candidate_evaluation,
                )
                self.candidates.update(
                    candidate_id,
                    status=(
                        LoopStatus.Candidate.BUGGY
                        if branch.get("validity_invalid")
                        else LoopStatus.Candidate.VERIFIER_FAILED
                        if validity_error
                        else LoopStatus.Candidate.EVALUATED
                    ),
                    artifact=artifact,
                    official_evaluated=official_agent_result is not None,
                    evidence_refs=refs,
                )
            self._finish_actor_candidate(
                state,
                branch,
                kind="validity_failed" if branch.get("validity_invalid") else "evaluated",
                feedback={
                    "public": public_agent_result,
                    "official": official_agent_result,
                    "validity_verifier": validity_verdict
                    if validity_verdict is not None
                    else ({"status": "verifier_error", "error": validity_error} if validity_error else None),
                    "leaderboard": state.get("research_state", {}).get(
                        "leaderboard", {}
                    ),
                },
                official_evaluated=official_agent_result is not None,
            )
            if self.benchmark_managed:
                self._record_benchmark_result(
                    state,
                    exp_item,
                    branch,
                    public_result,
                    official_result,
                    refs,
                )
                return
            analysis = self.agent_facility.analyze_result(
                branch,
                {
                    "public": public_agent_result,
                    "official": official_agent_result,
                },
            )
            if not isinstance(analysis, dict):
                raise TypeError(f"result analyst returned {type(analysis).__name__}, expected dict")
            if analysis.get("need_user_preference"):
                assert self.master_bridge is not None
                self.master_bridge.request_clarification(
                    {
                        "type": "preference_request",
                        "branch_id": branch.get("branch_id"),
                        "question": analysis.get("question")
                        or "Need user preference to resolve research trade-off.",
                        "options": analysis.get("options") or [],
                    }
                )
            analysis_ref = self.artifacts.save_json("analysis_report", analysis, refs=refs)
            refs.append(analysis_ref)
            self.queues.evaluation.update(
                exp_item,
                status=LoopStatus.Queue.FINISHED,
                output_refs=refs,
                evidence_refs=refs,
            )
            if analysis.get("promote"):
                self.queues.analyze.push(
                    branch,
                    item_type="analysis_task",
                    priority=1,
                    evidence_refs=refs,
                )
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.ANALYSIS_QUEUED,
                    evidence_refs=refs,
                )
                self.experience.upsert(
                    {
                        "type": "reusable_artifact",
                        "benchmark": (
                            (self.goal_doc.get("benchmarks") or [{}])[0].get("name")
                            if isinstance((self.goal_doc.get("benchmarks") or [{}])[0], dict)
                            else None
                        ),
                        "summary": f"branch {branch.get('branch_id')} promoted for deep analysis",
                        "outcome": {
                            "status": LoopStatus.Outcome.PROMOTED,
                            "metrics": self._result_metric_snapshot(
                                public_result,
                                official_result,
                            ),
                            "leaderboard": state.get("research_state", {}).get("leaderboard", {}),
                        },
                        "artifact_refs": refs,
                    }
                )
                decision = "promote_to_analyze_spark"
            elif analysis.get("retry"):
                revised_idea = analysis.get("revised_idea")
                if (
                    not isinstance(revised_idea, dict)
                    or not revised_idea.get("title")
                    or not revised_idea.get("mechanism")
                ):
                    self._upsert_branch_state(
                        state,
                        branch,
                        LoopStatus.Branch.ARCHIVED,
                        evidence_refs=refs,
                    )
                    self.experience.upsert(
                        {
                            "type": "failure_case",
                            "summary": f"branch {branch.get('branch_id')} retry idea invalid",
                            "outcome": {
                                "status": LoopStatus.Outcome.FAILED,
                                "reason": "result analyst requested retry without a valid revised_idea",
                            },
                            "artifact_refs": refs,
                        }
                    )
                    decision = "archive"
                else:
                    revised_idea = dict(revised_idea)
                    revised_idea.setdefault("id", new_id("idea"))
                    # 这个载荷两行之后就进 `idea_graph.submit()`，而 v1/v2 读的是
                    # 两套字段名，所以两套都写——v1 读 parent_idea_id/relation
                    # （`storage/idea_graph.py:151-152`，并渲染进 IDEAS.md 的
                    # 「关系」「Parent」两列），v2 读 operator/parents。
                    # 这不是「为兼容而兼容」的镜像：两边都有真实的运行时消费者，
                    # 少写哪一套，对应那条臂的父指针就是空的。
                    #
                    # 算子是 exploit：这是宿主替 analyst 造的「基于原方案重试」，
                    # 恰好一个已存在的父，语义与 v8 定义的 exploit 逐字吻合。
                    revised_idea.setdefault("operator", OPERATOR_EXPLOIT)
                    revised_idea.setdefault("parents", [branch.get("idea_id")])
                    revised_idea.setdefault("parent_idea_id", branch.get("idea_id"))
                    revised_idea.setdefault("relation", "derived_from")
                    revised_idea.setdefault("idea_actor_id", "idea_agent_main")
                    revised_idea["parent_branch_id"] = branch.get("branch_id")
                    revised_idea = self._unique_idea(revised_idea)
                    idea_ref = self.artifacts.save_json("idea", revised_idea, refs=[analysis_ref])
                    self.idea_graph.submit(
                        revised_idea,
                        actor_id="idea_agent_main",
                        artifact_refs=[idea_ref],
                        goal_contract_version=self._goal_contract_version(),
                    )
                    if not self.idea_gate_enabled:
                        retry_refs = self._enqueue_idea_without_gate(
                            revised_idea,
                            idea_ref,
                            inherited_refs=refs,
                        )
                        self._upsert_branch_state(
                            state,
                            branch,
                            LoopStatus.Branch.RETRY_QUEUED,
                            evidence_refs=retry_refs,
                        )
                        decision = "retry_idea"
                    else:
                        self.idea_graph.begin_review(str(revised_idea["id"]))
                        retry_exp = self.experience.search(
                            goal_query(self.goal_doc),
                            top_k=5,
                        )
                        retry_review = self._normalize_idea_review(
                            revised_idea,
                            self.agent_facility.idea_gate(
                                self.goal_doc,
                                revised_idea,
                                retry_exp,
                            ),
                        )
                        review_ref = self.artifacts.save_json(
                            "idea_review",
                            retry_review,
                            refs=[idea_ref],
                        )
                        self.idea_graph.record_review(
                            str(revised_idea["id"]),
                            retry_review,
                            artifact_refs=[review_ref],
                        )
                        retry_refs = refs + [idea_ref, review_ref]
                        if retry_review.get("accept"):
                            self.queues.ideaspark.push(
                                revised_idea,
                                item_type="idea",
                                priority=1,
                                evidence_refs=retry_refs,
                            )
                            self._upsert_branch_state(
                                state,
                                branch,
                                LoopStatus.Branch.RETRY_QUEUED,
                                evidence_refs=retry_refs,
                            )
                            decision = "retry_idea"
                        else:
                            self._record_idea_gate_experience(
                                revised_idea,
                                retry_review,
                                refs=retry_refs,
                            )
                            self._upsert_branch_state(
                                state,
                                branch,
                                LoopStatus.Branch.ARCHIVED,
                                evidence_refs=retry_refs,
                            )
                            decision = "reject_retry_idea"
            else:
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.ARCHIVED,
                    evidence_refs=refs,
                )
                self.experience.upsert(
                    {
                        "type": "failure_case",
                        "summary": f"branch {branch.get('branch_id')} archived",
                        "outcome": {
                            "status": LoopStatus.Outcome.FAILED,
                            "reason": "; ".join(analysis.get("reasons", [])),
                            "metrics": self._result_metric_snapshot(
                                public_result,
                                official_result,
                            ),
                        },
                        "artifact_refs": refs,
                    }
                )
                decision = "archive"
            self.artifacts.record_decision(
                {
                    "decision": decision,
                    "branch_id": branch.get("branch_id"),
                    "reasons": analysis.get("reasons", []),
                },
                refs=refs,
            )
        except Exception as exc:  # noqa: BLE001 - isolate evaluator/analysis failures
            error = {
                "id": new_id("evaluation_error"),
                "branch_id": branch.get("branch_id"),
                "source": "orchestrator_evaluation",
                "valid": False,
                "error": repr(exc),
                "exception_type": type(exc).__name__,
                "created_at": now_ms(),
            }
            error_ref = self.artifacts.save_json("evaluation_error", error, refs=refs)
            refs.append(error_ref)
            self._archive_failed_experiment(
                exp_item,
                branch,
                error,
                refs,
                reason=f"evaluator/analysis failed: {exc}",
            )
            self._upsert_branch_state(
                state,
                branch,
                LoopStatus.Branch.ENGINEERING_FAILED,
                evidence_refs=refs,
            )
            self._record_expbank_failure(
                branch,
                refs,
                reason=f"evaluator/analysis failed: {exc}",
                next_step="检查 evaluation_error 证据后重试评测链路。",
                failure={
                    "failure_stage": "evaluation_infrastructure",
                    "error_code": "evaluation_infrastructure_failed",
                    "return_code": None,
                    "signal": None,
                    "timed_out": False,
                    "submitted": True,
                    "retryable": True,
                    "message": f"evaluator/analysis failed: {exc}",
                    "suggested_action": "检查 evaluation_error 证据后重试评测链路。",
                    "evidence_refs": refs,
                    "diagnostics": error,
                },
            )
            if candidate_id:
                self.candidates.write_evidence(candidate_id, "evaluation_error", error)
                self.candidates.update(
                    candidate_id,
                    status=LoopStatus.Candidate.EVALUATION_FAILED,
                    error=repr(exc),
                    evidence_refs=refs,
                )
            self._finish_actor_candidate(
                state,
                branch,
                kind="evaluation_failed",
                feedback={"error": repr(exc), "source": "orchestrator_evaluation"},
            )

    def tick(
        self,
        *,
        run_ideas: bool = True,
        run_implementations: bool = True,
        run_evaluations: bool = True,
    ) -> bool:
        """执行一个调度周期。"""
        state = self.state_store.load()
        rs = state.setdefault("research_state", {})
        self._sync_goal_doc_from_state(state)
        self._record_runtime_limits(state)
        control_changed = self._consume_control_commands(state)
        forced = self._control_status()
        if forced:
            rs["status"] = forced
            self.state_store.save(state)
            self.log(f"control status={forced}; skip tick")
            return control_changed
        if rs.get("status") in LoopStatus.RESEARCH_TERMINAL:
            self._render_status(state)
            self.log(f"state status={rs.get('status')}; skip tick")
            return False
        if self._wall_time_exhausted(state):
            self._stop_for_wall_time(state)
            return False

        self._checkpoint(state, "tick")
        patched = False
        if self.master_bridge is not None:
            patched = self.master_bridge.apply_goal_patch(state)
        if patched:
            self._apply_runtime_constraint_patch(state)
            self._sync_goal_doc_from_state(state)
            self.state_store.save(state)
            self.log("applied goal_patch")

        progressed = control_changed or bool(patched)

        # feedback 已经持久化但此前没有可用槽位的 Actor 必须在每个 tick 重试派发。
        # repair continuation 具有更高队列优先级；这里只入队，不会 kill 当前 Agent。
        resumed = self._schedule_ready_actors(state)
        progressed = progressed or resumed > 0

        # 完整 benchmark 的任务已经明确：调用 Idea Agent 产生路线后直接进入实现队列，
        # 不经过 Master、novelty gate、Result Analyst 或 AnalyzeSpark。
        if self.benchmark_managed and run_ideas:
            scheduled = self._enqueue_benchmark_attempts(state)
            progressed = progressed or scheduled > 0

        # 开放式科研中，IdeaActor 每回合只提交一个 Idea。默认直接准入；若 Goal
        # 显式开启 Gate，则在同一调度线程等待 Review，并在下一回合恢复 Session 时注入。
        elif (
            not self.benchmark_managed
            and run_ideas
            and self.config.idea_generation_enabled
            and self.config.min_ideas > 0
            and self._idea_backlog(self.queues.ideaspark)
            < self.config.idea_queue_high_watermark
        ):
            exp = self._idea_experience(top_k=5)
            raw_ideas = self.agent_facility.generate_ideas(
                self._research_idea_context(),
                exp,
            )
            for raw_idea in raw_ideas:
                idea = self._unique_idea(raw_idea)
                idea_ref = self.artifacts.save_json("idea", idea)
                try:
                    self.idea_graph.submit(
                        idea,
                        actor_id=str(idea.get("idea_actor_id") or "idea_agent_main"),
                        artifact_refs=[idea_ref],
                        goal_contract_version=self._goal_contract_version(),
                    )
                except ValueError as exc:
                    # 登记不进图的方案后面没人能引用它，跳过好过让 tick 整个断掉。
                    self.log(f"idea graph: 丢弃非法提案 {idea.get('id')} — {exc}")
                    continue
                if not self.idea_gate_enabled:
                    self._enqueue_idea_without_gate(idea, idea_ref)
                    continue
                self.idea_graph.begin_review(str(idea["id"]))
                review = self._normalize_idea_review(
                    idea,
                    self.agent_facility.idea_gate(self.goal_doc, idea, exp),
                )
                review_ref = self.artifacts.save_json(
                    "idea_review",
                    review,
                    refs=[idea_ref],
                )
                self.idea_graph.record_review(
                    str(idea["id"]),
                    review,
                    artifact_refs=[review_ref],
                )
                if review.get("accept"):
                    self.queues.ideaspark.push(idea, item_type="idea", priority=1, evidence_refs=[idea_ref, review_ref])
                    self.artifacts.record_decision({"decision": "accept_to_ideaspark", "idea_id": idea.get("id"), "reasons": review.get("reasons", [])}, refs=[idea_ref, review_ref])
                else:
                    self._record_idea_gate_experience(
                        idea,
                        review,
                        refs=[idea_ref, review_ref],
                    )
                    self.artifacts.record_decision(
                        {
                            "decision": (
                                "reject_idea"
                                if review.get("verdict") == "reject"
                                else review.get("decision")
                            ),
                            "idea_id": idea.get("id"),
                            "verdict": review.get("verdict"),
                            "reasons": review.get("reasons", []),
                            "actionable_revision": review.get(
                                "actionable_revision", []
                            ),
                        },
                        refs=[idea_ref, review_ref],
                    )
            progressed = True

        # 二、同步 Orchestrator 从想法池填充实验槽位；AsyncOrchestrator 会把
        # run_implementations 设为 False，并由独立 Implement 线程池消费这些条目。
        if run_implementations:
            ranked = self._maybe_rank_queued_ideas(state)
            progressed = progressed or ranked
            # Judge 本身消耗研究墙钟；若调用期间跨过截止点，不再领取新实现。
            if self._wall_time_exhausted(state):
                self._stop_for_wall_time(state)
                return progressed
            evaluation_backlog = (
                self.queues.evaluation.size(LoopStatus.Queue.QUEUED)
                + self.queues.evaluation.size(
                    LoopStatus.Queue.WAITING_RESOURCES
                )
                + self.queues.evaluation.size(LoopStatus.Queue.RUNNING)
            )
            implementation_slots = min(
                self.config.max_parallel_implementations,
                max(
                    0,
                    self.config.evaluation_queue_capacity - evaluation_backlog,
                ),
            )
            implementation_queue = self._implementation_queue()
            for _ in range(implementation_slots):
                item = self._claim_implementation_item()
                if not item:
                    break
                branch = self._run_implementation_item(item)
                self._process_implementation_result(state, item, branch)
                progressed = True

        if run_evaluations:
            # 三、同步模式按 Evaluation 容量领取 Candidate。每个 Candidate 仍严格
            # 按 run.py、产物校验、正式评分的顺序执行。
            exp_items = []
            for _ in range(self.config.max_parallel_evaluations):
                item = self.queues.evaluation.pop()
                if not item:
                    break
                exp_items.append(item)
                self._upsert_branch_state(
                    state,
                    item.get("payload") or {},
                    LoopStatus.Branch.EVALUATION_RUNNING,
                )
            if exp_items:
                self._checkpoint(state, "experiment_runner")
                self.log(
                    f"running experiment batch size={len(exp_items)} "
                    f"max_parallel={self.config.max_parallel_evaluations}"
                )
                run_results = self._run_experiment_batch(exp_items)
                self._checkpoint(state, "evaluator")
                for exp_item, run_result in zip(exp_items, run_results):
                    self._process_evaluation_result(state, exp_item, run_result)
                progressed = True

        # 完整 benchmark 不需要论文候选或额外分析裁判。
        an_item = None if self.benchmark_managed else self.queues.analyze.pop()
        if an_item:
            self._checkpoint(state, "deep_analysis")
            branch = an_item["payload"]
            report = self.agent_facility.analyze_deep(branch)
            report_ref = self.artifacts.save_json("deep_analysis", report, refs=an_item.get("evidence_refs", []))
            self.queues.analyze.update(
                an_item,
                status=LoopStatus.Queue.FINISHED,
                output_refs=[report_ref],
                evidence_refs=[report_ref],
            )
            if report.get("paper_candidate"):
                self.artifacts.record_decision({"decision": "mark_paper_candidate", "branch_id": branch.get("branch_id"), "reasons": report.get("claims", [])}, refs=[report_ref])
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.PAPER_CANDIDATE,
                    evidence_refs=[report_ref],
                )
                rs["status"] = LoopStatus.Research.COMPLETED
            else:
                self._upsert_branch_state(
                    state,
                    branch,
                    LoopStatus.Branch.ANALYZED,
                    evidence_refs=[report_ref],
                )
            progressed = True

        if self._complete_benchmark_if_done(state):
            progressed = True

        self._preserve_external_control(state)
        self._checkpoint(
            state,
            (
                "completed"
                if state.get("research_state", {}).get("status")
                == LoopStatus.Research.COMPLETED
                else "idle"
            ),
        )
        append_jsonl(self.workspace / "logs" / "ticks.jsonl", {"ts": now_ms(), "progressed": progressed, "queues": self.queues.summary()})
        self.log(f"tick progressed={progressed}")
        return progressed

    def _run_unlocked(self) -> dict[str, Any]:
        """在已持有锁的情况下运行调度循环。"""
        ticks = 0
        # 聊天控制器使用 max_ticks=-1 表示持续接收新任务；真正的终止条件由
        # 墙钟预算、用户 stop 或工作流完成状态决定。0 仍保留“只初始化”语义。
        while self.config.max_ticks < 0 or ticks < self.config.max_ticks:
            ticks += 1
            progressed = self.tick()
            if not progressed:
                break
            state = self.state_store.load()
            if (
                state.get("research_state", {}).get("status")
                in LoopStatus.RESEARCH_TERMINAL
            ):
                break
            time.sleep(self.config.interval_sec)
        return self.state_store.load()

    def run(self) -> dict[str, Any]:
        """执行当前组件的运行流程。"""
        with WorkspaceRunLock(self.workspace):
            self.resume_task()
            self._recover_interrupted_items()
            state = self._run_unlocked()
            self.finalize_cross_task_experience(state)
            return self.state_store.load()
