"""目标文件加载、校验与归一化逻辑。"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..utils import new_id, safe_name


class GoalError(ValueError):
    """表示目标文件加载或校验错误。"""
    pass


_NUMERIC_CONSTRAINTS = {
    "max_benchmark_attempts": (1, int),
    "max_evaluator_submissions": (0, int),
    "max_parallel_ideas": (1, int),
    "max_parallel_implementations": (1, int),
    "max_parallel_evaluations": (1, int),
    "max_experiment_retries": (0, int),
    "max_wall_time_hours": (0, float),
    "max_implement_lifetime_sec": (1, float),
    "max_implement_turns_per_actor": (1, int),
    "max_run_attempts_per_actor": (1, int),
    "max_official_evaluations_per_actor": (0, int),
    "max_repairs_per_revision": (0, int),
    "idea_queue_high_watermark": (1, int),
    "evaluation_queue_capacity": (1, int),
}

_WORKFLOW_TYPES = {"research", "benchmark_managed"}
_PIPELINE_TYPES = {"sync", "async"}


def idea_gate_enabled(goal_doc: dict[str, Any]) -> bool:
    """返回开放科研工作流是否显式启用了 Idea Gate。"""

    workflow = goal_doc.get("workflow")
    if not isinstance(workflow, dict):
        return False
    gate = workflow.get("idea_gate")
    if not isinstance(gate, dict):
        return False
    # Idea Agent 的 instruction 已包含基本约束，因此 V1 默认信任 Agent；
    # 只有目标明确开启时，才增加一次同步 LLM Judge。
    return gate.get("enabled") is True


def _validate_constraints(constraints: dict[str, Any], *, prefix: str = "constraints") -> None:
    """校验目标中的约束字段。"""
    if not isinstance(constraints, dict):
        raise GoalError(f"{prefix} 必须是 object")
    for name, (minimum, converter) in _NUMERIC_CONSTRAINTS.items():
        if name not in constraints or constraints[name] is None:
            continue
        raw_value = constraints[name]
        if isinstance(raw_value, bool):
            raise GoalError(f"{prefix}.{name} 必须是数字")
        try:
            value = converter(raw_value)
        except (TypeError, ValueError):
            raise GoalError(f"{prefix}.{name} 必须是数字") from None
        if value < minimum:
            raise GoalError(f"{prefix}.{name} 不能小于 {minimum}")


def _validate_infra(infra: dict[str, Any]) -> None:
    """校验流水线模式和并发配置。"""
    if not isinstance(infra, dict):
        raise GoalError("infra 必须是 object")
    pipeline = str(infra.get("pipeline") or "sync")
    if pipeline not in _PIPELINE_TYPES:
        raise GoalError("infra.pipeline 必须是 sync 或 async")
    concurrency = infra.get("concurrency") or {}
    if not isinstance(concurrency, dict):
        raise GoalError("infra.concurrency 必须是 object")
    for name in ("ideas", "implementations", "evaluations"):
        if name not in concurrency:
            continue
        value = concurrency[name]
        if isinstance(value, bool):
            raise GoalError(f"infra.concurrency.{name} 必须是正整数")
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise GoalError(f"infra.concurrency.{name} 必须是正整数") from None
        if parsed < 1:
            raise GoalError(f"infra.concurrency.{name} 必须是正整数")
    scheduling = infra.get("scheduling") or {}
    if not isinstance(scheduling, dict):
        raise GoalError("infra.scheduling 必须是 object")
    observability = infra.get("observability") or {}
    if not isinstance(observability, dict):
        raise GoalError("infra.observability 必须是 object")
    pricing = observability.get("pricing")
    if pricing is not None:
        if not isinstance(pricing, dict):
            raise GoalError("infra.observability.pricing 必须是 object")
        currency = str(pricing.get("currency") or "").strip()
        if not currency:
            raise GoalError("infra.observability.pricing.currency 不能为空")
        rates = pricing.get("per_million_tokens")
        if not isinstance(rates, dict):
            raise GoalError(
                "infra.observability.pricing.per_million_tokens 必须是 object"
            )
        for name in ("input", "cache_creation", "cache_read", "output"):
            value = rates.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise GoalError(
                    "infra.observability.pricing.per_million_tokens."
                    f"{name} 必须是非负数字"
                )
            if not math.isfinite(float(value)) or value < 0:
                raise GoalError(
                    "infra.observability.pricing.per_million_tokens."
                    f"{name} 必须是非负数字"
                )
    search_policy = scheduling.get("search_policy")
    if search_policy is not None:
        if not isinstance(search_policy, dict):
            raise GoalError("infra.scheduling.search_policy 必须是 object")
        if "enabled" in search_policy and not isinstance(
            search_policy["enabled"], bool
        ):
            raise GoalError(
                "infra.scheduling.search_policy.enabled 必须是 boolean"
            )
        policy_type = str(search_policy.get("type") or "pairwise_improve")
        if policy_type != "pairwise_improve":
            raise GoalError(
                "infra.scheduling.search_policy.type 当前只支持 pairwise_improve"
            )
    ranking = scheduling.get("time_aware_idea_ranking")
    if ranking is not None:
        if not isinstance(ranking, dict):
            raise GoalError(
                "infra.scheduling.time_aware_idea_ranking 必须是 object"
            )
        if "enabled" in ranking and not isinstance(ranking["enabled"], bool):
            raise GoalError(
                "infra.scheduling.time_aware_idea_ranking.enabled 必须是 boolean"
            )
        trigger = ranking.get("trigger_remaining_sec")
        if trigger is not None:
            if isinstance(trigger, bool):
                raise GoalError(
                    "infra.scheduling.time_aware_idea_ranking."
                    "trigger_remaining_sec 必须是正数"
                )
            try:
                trigger_value = float(trigger)
            except (TypeError, ValueError):
                raise GoalError(
                    "infra.scheduling.time_aware_idea_ranking."
                    "trigger_remaining_sec 必须是正数"
                ) from None
            if trigger_value <= 0:
                raise GoalError(
                    "infra.scheduling.time_aware_idea_ranking."
                    "trigger_remaining_sec 必须是正数"
                )
        timeout = ranking.get("judge_timeout_sec")
        if timeout is not None:
            if isinstance(timeout, bool):
                raise GoalError(
                    "infra.scheduling.time_aware_idea_ranking."
                    "judge_timeout_sec 必须是正数"
                )
            try:
                timeout_value = float(timeout)
            except (TypeError, ValueError):
                raise GoalError(
                    "infra.scheduling.time_aware_idea_ranking."
                    "judge_timeout_sec 必须是正数"
                ) from None
            if timeout_value <= 0:
                raise GoalError(
                    "infra.scheduling.time_aware_idea_ranking."
                    "judge_timeout_sec 必须是正数"
                )


def _apply_builtin_benchmark_defaults(data: dict[str, Any]) -> None:
    """为内置 benchmark adapter 补齐可从任务类型推导的配置。"""
    task = data.get("benchmark_task")
    if not isinstance(task, dict) or task.get("type") != "naturebench":
        return
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise GoalError("NatureBench 任务必须提供 benchmark_task.task_id")
    data.setdefault("workflow", {"type": "benchmark_managed"})
    if not data.get("benchmarks"):
        data["benchmarks"] = [
            {
                "name": f"NatureBench/{task_id}",
                "adapter": {"type": "naturebench"},
                "official_metric": {
                    "name": "aggregate_improvement",
                    "direction": "higher_is_better",
                },
                "hidden_test_access": "forbidden",
            }
        ]
    constraints = data.setdefault("constraints", {})
    if isinstance(constraints, dict):
        attempts = constraints.get("max_benchmark_attempts")
        if attempts is not None:
            constraints.setdefault("max_evaluator_submissions", attempts)


def _validate_goal_doc(data: dict[str, Any]) -> None:
    """校验目标文件的整体结构。"""
    goal = data.get("goal") or {}
    goal_id = str(goal.get("id") or data.get("goal_id") or "")
    if not goal_id:
        raise GoalError("goal.id 不能为空")
    if goal_id != safe_name(goal_id):
        raise GoalError(
            f"goal.id 只能包含字母、数字、点、下划线和连字符，禁止路径字符: {goal_id!r}"
        )

    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        raise GoalError("workflow 必须是 object")
    workflow_type = str(workflow.get("type") or "research")
    if workflow_type not in _WORKFLOW_TYPES:
        raise GoalError(
            f"workflow.type 必须是 research 或 benchmark_managed: {workflow_type!r}"
        )
    idea_gate = workflow.get("idea_gate")
    if idea_gate is not None:
        if not isinstance(idea_gate, dict):
            raise GoalError("workflow.idea_gate 必须是 object")
        if "enabled" in idea_gate and not isinstance(idea_gate["enabled"], bool):
            raise GoalError("workflow.idea_gate.enabled 必须是 boolean")

    benchmarks = data.get("benchmarks")
    if not isinstance(benchmarks, list):
        raise GoalError("benchmarks 必须是 list")
    for index, benchmark in enumerate(benchmarks):
        if not isinstance(benchmark, dict):
            raise GoalError(f"benchmarks[{index}] 必须是 object")
        metric = benchmark.get("official_metric")
        if metric is not None:
            if not isinstance(metric, dict) or not metric.get("name"):
                raise GoalError(f"benchmarks[{index}].official_metric 必须包含 name")
            direction = metric.get("direction", "higher_is_better")
            if direction not in {"higher_is_better", "lower_is_better"}:
                raise GoalError(
                    f"benchmarks[{index}].official_metric.direction 无效: {direction!r}"
                )
        adapter = benchmark.get("adapter")
        if adapter is not None and not isinstance(adapter, dict):
            raise GoalError(f"benchmarks[{index}].adapter 必须是 object")

    _validate_constraints(data.get("constraints"), prefix="constraints")
    _validate_infra(data.get("infra") or {})


def validate_goal_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化目标补丁。"""
    if not isinstance(patch, dict):
        raise GoalError("goal patch 顶层必须是 object")

    metadata_keys = {"reason", "created_at"}
    allowed_change_keys = {"objective_brief", "constraints"}
    if "changes" in patch:
        unexpected = set(patch) - metadata_keys - {"changes"}
        if unexpected:
            raise GoalError(
                f"goal patch 不能同时使用 changes 和直接字段: {sorted(unexpected)!r}"
            )
        changes = patch.get("changes")
        if not isinstance(changes, dict):
            raise GoalError("goal patch.changes 必须是 object")
    else:
        unexpected = set(patch) - metadata_keys - allowed_change_keys
        if unexpected:
            raise GoalError(f"goal patch 包含不支持的字段: {sorted(unexpected)!r}")
        changes = {
            key: patch[key]
            for key in allowed_change_keys
            if key in patch
        }

    unexpected_changes = set(changes) - allowed_change_keys
    if unexpected_changes:
        raise GoalError(
            f"goal patch.changes 包含不支持的字段: {sorted(unexpected_changes)!r}"
        )
    if "objective_brief" in changes and not isinstance(changes["objective_brief"], dict):
        raise GoalError("goal patch.objective_brief 必须是 object")
    if "constraints" in changes:
        _validate_constraints(changes["constraints"], prefix="goal patch.constraints")
    if not changes:
        raise GoalError("goal patch 至少需要 objective_brief 或 constraints")

    normalized = {
        key: value
        for key, value in patch.items()
        if key not in allowed_change_keys
    }
    normalized["changes"] = dict(changes)
    return normalized


def _load_structured_text(path: Path) -> dict[str, Any]:
    """加载结构化文本配置。"""
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise GoalError(
                f"无法解析 {path}: 当前环境没有 PyYAML；V1 支持 JSON 或安装 PyYAML 后读取 YAML。"
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise GoalError(f"goal file 顶层必须是 object/dict: {path}")
    return data


def load_goal(path: str | Path) -> dict[str, Any]:
    """加载并校验目标文件。"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise GoalError(f"goal file 不存在: {p}")

    data = _load_structured_text(p)
    goal = data.get("goal")
    if not isinstance(goal, dict):
        raise GoalError("goal file 必须包含 goal: {...}")

    name = str(goal.get("name") or p.stem)
    goal_id = str(goal.get("id") or data.get("goal_id") or new_id(safe_name(name)))
    goal["id"] = goal_id
    goal.setdefault("name", name)
    data["goal"] = goal
    data["goal_id"] = goal_id
    data["goal_file"] = str(p)
    data.setdefault("benchmarks", [])
    data.setdefault("baselines", [])
    data.setdefault("objective_brief", {})
    data.setdefault("constraints", {})
    data.setdefault("outputs", {})
    _apply_builtin_benchmark_defaults(data)
    workflow = data.setdefault("workflow", {"type": "research"})
    if isinstance(workflow, dict):
        workflow.setdefault("type", "research")
    _validate_goal_doc(data)
    return data


def workflow_type(goal_doc: dict[str, Any]) -> str:
    """返回目标使用的运行工作流类型。"""
    workflow = goal_doc.get("workflow")
    if not isinstance(workflow, dict):
        return "research"
    value = str(workflow.get("type") or "research")
    return value if value in _WORKFLOW_TYPES else "research"


def goal_query(goal_doc: dict[str, Any]) -> str:
    """提取用于检索的目标文本。"""
    goal = goal_doc.get("goal") or {}
    brief = goal_doc.get("objective_brief") or {}
    task = goal_doc.get("benchmark_task") or {}
    benchmarks = goal_doc.get("benchmarks") or []
    parts = [
        str(goal.get("name", "")),
        str(task.get("type", "")) if isinstance(task, dict) else "",
        str(task.get("task_id", "")) if isinstance(task, dict) else "",
        *[
            str(benchmark.get("name", ""))
            for benchmark in benchmarks
            if isinstance(benchmark, dict)
        ],
        str(brief.get("primary_goal", "")),
        str(brief.get("preference_description", "")),
    ]
    return "\n".join(p for p in parts if p)
