"""研究状态的读写辅助逻辑。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import atomic_write_json, now_ms, read_json
from ..domain.status import LoopStatus


class ResearchState:
    """读写端到端研究状态。"""
    def __init__(self, workspace: str | Path):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)
        self.path = self.workspace / "research_state.yaml"

    def init(self, goal_doc: dict[str, Any]) -> dict[str, Any]:
        """初始化研究状态文件。"""
        # ResearchState 只保存调度检查点和摘要指针，不嵌入大段代码、日志或评测
        # 原始结果；这些内容分别由 branch workspace、ArtifactStore 和 ExpBank 管理。
        constraints = goal_doc.get("constraints", {})
        if not isinstance(constraints, dict):
            constraints = {}
        infra = goal_doc.get("infra", {})
        if not isinstance(infra, dict):
            infra = {}
        concurrency = infra.get("concurrency", {})
        if not isinstance(concurrency, dict):
            concurrency = {}
        state = {
                "research_state": {
                    "goal_id": goal_doc["goal_id"],
                    "status": LoopStatus.Research.RUNNING,
                    "lifecycle": "active",
                    "goal_revision": int(goal_doc.get("goal_revision", 1) or 1),
                    "current_phase": "initializing",
                    "last_heartbeat_at": now_ms(),
                    "created_at": now_ms(),
                "updated_at": now_ms(),
                "goal": {
                    "name": goal_doc.get("goal", {}).get("name"),
                    "objective_brief": goal_doc.get("objective_brief", {}),
                    "constraints": constraints,
                    "workflow": goal_doc.get("workflow", {"type": "research"}),
                    "infra": infra,
                },
                "lineage": goal_doc.get("lineage", {}),
                "pending_goal_change": None,
                "benchmark_contract": {
                    # contract 记录“哪些指标由哪个 adapter 提供”和隐藏数据策略，
                    # 供审计使用，不把 evaluator 命令或 GT 路径暴露给 Agent。
                    "adapters": goal_doc.get("benchmarks", []),
                    "official_metrics": [b.get("official_metric") for b in goal_doc.get("benchmarks", []) if isinstance(b, dict)],
                    "hidden_eval_policy": goal_doc.get("constraints", {}).get("hidden_test_access", "forbidden"),
                    "prohibited_actions": ["hidden_test_access", "hidden_label_inspection"],
                },
                "queues": {},
                "branches": [],
                "evaluator_budget": {
                    # used_submissions 只在正式 evaluator 被实际调用后增加；本地运行失败
                    # 和公开格式检查失败不占用该预算。缺省/null 表示不限制；显式 0
                    # 表示禁用正式评测，正整数才表示调用上限。
                    "max_submissions": (
                        int(constraints["max_evaluator_submissions"])
                        if constraints.get("max_evaluator_submissions") is not None
                        else None
                    ),
                    "used_submissions": 0,
                },
                "runtime_limits": {
                    "max_wall_time_hours": constraints.get("max_wall_time_hours"),
                    "max_parallel_ideas": concurrency.get(
                        "ideas",
                        constraints.get("max_parallel_ideas", 1),
                    ),
                    "max_parallel_implementations": concurrency.get(
                        "implementations",
                        constraints.get(
                            "max_parallel_implementations",
                            constraints.get("max_parallel_evaluations", 1),
                        ),
                    ),
                    "max_parallel_evaluations": concurrency.get(
                        "evaluations",
                        constraints.get("max_parallel_evaluations", 1),
                    ),
                    "max_experiment_retries": constraints.get("max_experiment_retries", 0),
                    "max_implement_lifetime_sec": constraints.get(
                        "max_implement_lifetime_sec", 14_400
                    ),
                    "max_implement_turns_per_actor": constraints.get(
                        "max_implement_turns_per_actor", 1
                    ),
                    "max_run_attempts_per_actor": constraints.get(
                        "max_run_attempts_per_actor"
                    ),
                    "max_official_evaluations_per_actor": constraints.get(
                        "max_official_evaluations_per_actor"
                    ),
                    "idea_queue_high_watermark": constraints.get(
                        "idea_queue_high_watermark"
                    ),
                    "evaluation_queue_capacity": constraints.get(
                        "evaluation_queue_capacity"
                    ),
                },
                "leaderboard": {
                    # Leaderboard 只保存当前最佳指针，完整的每次实验结果留在 ExpBank。
                    "metric": None,
                    "direction": None,
                    "best_value": None,
                    "branch_id": None,
                    "expbank_attempt_id": None,
                    "artifact_ref": None,
                    "evaluator_artifact_ref": None,
                },
                "validity_verifier": {
                    # 只记录公开 verdict 摘要和证据指针；VerifierAgent session
                    # 由注入的 verifier 自己管理，默认关闭。
                    "enabled": bool(constraints.get("validity_verifier_enabled", False)),
                    "last_status": None,
                    "last_reasons": [],
                    "last_evidence_refs": [],
                    "last_verdict_ref": None,
                    "history": [],
                },
                "artifact_index_ref": "artifacts/artifact_index.jsonl",
                "decision_log_ref": "artifacts/decision_log.jsonl",
                "audit": {
                    # audit 保存安全与终止相关计数，便于判断是否发生隐藏测试访问尝试
                    # 或缺失证据，而不是让 LLM 自己声明流程合规。
                    "evaluator_calls": [],
                    "hidden_test_access_attempts": 0,
                    "artifact_writes": 0,
                    "missing_evidence_warnings": [],
                },
            }
        }
        self.save(state)
        return state

    def load(self) -> dict[str, Any]:
        """加载研究状态文件。"""
        data = read_json(self.path)
        if data is None:
            raise FileNotFoundError(f"ResearchState 不存在: {self.path}")
        return data

    def save(self, state: dict[str, Any]) -> None:
        """保存研究状态文件。"""
        state.setdefault("research_state", {})["updated_at"] = now_ms()
        # 虽然扩展名保留为 yaml 兼容既有路径，内容使用 JSON 子集并原子写入。
        atomic_write_json(self.path, state)

    def update_queues(self, state: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
        """更新研究状态中的队列摘要。"""
        state.setdefault("research_state", {})["queues"] = summary
        self.save(state)
        return state
