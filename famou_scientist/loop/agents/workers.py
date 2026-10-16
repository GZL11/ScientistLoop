"""端到端科研循环中的工作节点实现。"""
from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ..utils import (
    atomic_write_json,
    new_id,
    now_ms,
    safe_name,
    sha256_file,
)
from ..execution.agent_runtime import ImplementRequest
from ..execution.sandbox import sandbox_from_config
from ..execution.workspace import AgentWorkspace
from ..domain.goal import workflow_type
from ..domain.status import LoopStatus
from ..plugins import load_adapter
from ..observability import ObservabilityStore


def _create_agent_adapter(
    config: dict[str, Any],
    *,
    config_dir: str | Path | None,
) -> Any:
    """通过插件注册表创建 Idea 或 Implement Agent。"""

    adapter_name = str(config.get("adapter") or "cli")
    adapter = load_adapter("agent", adapter_name)
    create = getattr(adapter, "create", None)
    if not callable(create):
        raise TypeError(f"Agent Adapter 缺少 create(): {adapter_name}")
    return create(config, config_dir=config_dir)


def _sandbox_config(
    worker_config: dict[str, Any],
    goal_doc: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a worker sandbox, falling back to the goal-level sandbox."""

    configured = worker_config.get("sandbox")
    if isinstance(configured, dict):
        return dict(configured)
    infra = goal_doc.get("infra") if isinstance(goal_doc, dict) else None
    fallback = infra.get("sandbox") if isinstance(infra, dict) else None
    return dict(fallback) if isinstance(fallback, dict) else {}


class DummyWorkerSet:
    """提供确定性的测试用工作节点集合。"""
    def generate_ideas(self, goal: dict[str, Any], experience: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """生成候选研究想法。"""
        return [
            {
                "id": new_id("idea"),
                "title": "Prototype Routing Classifier (dummy)",
                "mechanism": "Use class prototypes plus a shallow routing rule for interpretable prediction.",
                "expected_gain": ["interpretability", "latency"],
                "created_at": now_ms(),
                "experience_refs": [r.get("id") for r in experience[:3]],
            },
            {
                "id": new_id("idea"),
                "title": "Pure HPO baseline tweak (dummy reject)",
                "mechanism": "Only tune hyperparameters.",
                "created_at": now_ms(),
            },
        ]

    def idea_gate(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        experience: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """判断研究想法是否具备足够新颖性。"""
        del goal
        title = str(idea.get("title", "")).lower()
        accept = "hpo" not in title and "tune" not in str(idea.get("mechanism", "")).lower()
        return {
            "id": new_id("review"),
            "idea_id": idea.get("id"),
            "accept": accept,
            "decision": "accept_to_ideaspark" if accept else "reject",
            "reasons": ["has a concrete mechanism"] if accept else ["low novelty: HPO-only idea"],
            "created_at": now_ms(),
        }

    def rank_ideas(
        self,
        goal: dict[str, Any],
        ideas: list[dict[str, Any]],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        """以确定性顺序返回测试用 Idea 排名。"""

        del goal, runtime_context
        return {
            "ranking": [
                {
                    "queue_item_id": idea.get("queue_item_id"),
                    "idea_id": idea.get("idea_id"),
                    "rank": index,
                    "reason": "dummy judge preserves input order",
                    "scores": {
                        "feasibility": 3,
                        "score_potential": 3,
                        "time_fit": 3,
                        "resource_fit": 3,
                    },
                }
                for index, idea in enumerate(ideas, start=1)
            ]
        }

    def implement(self, idea: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
        """实现候选研究想法并返回结果。"""
        branch_id = str(idea.get("actor_branch_id") or new_id("branch"))
        agent_workspace = AgentWorkspace.create(workspace, branch_id)
        artifact = agent_workspace.write_output_json(
            "submission.json",
            {"branch_id": branch_id, "idea": idea, "dummy_model": True},
        )
        agent_workspace.mark_status(
            LoopStatus.Implementation.IMPLEMENTED,
            implementation_type="dummy",
        )
        return {
            "id": branch_id,
            "branch_id": branch_id,
            "idea_id": idea.get("id"),
            "artifact": str(artifact),
            "agent_workspace": str(agent_workspace.root),
            "worktree": str(agent_workspace.worktree),
            "public_dir": str(agent_workspace.public),
            "outputs_dir": str(agent_workspace.outputs),
            "isolation": "directory",
            "status": LoopStatus.Implementation.IMPLEMENTED,
            "created_at": now_ms(),
        }

    def analyze_result(self, branch: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
        """分析评测结果并给出后续决策。"""
        public = results.get("public") or {}
        metrics = public.get("metrics") or {}
        acc = float(metrics.get("accuracy", 0.0) or 0.0)
        promote = acc >= 0.75
        return {
            "id": new_id("analysis"),
            "branch_id": branch.get("branch_id") or branch.get("id"),
            "promote": promote,
            "retry": False,
            "decision": "promote_to_analyze_spark" if promote else "archive",
            "reasons": [f"public accuracy={acc} >= 0.75"] if promote else [f"public accuracy={acc} < 0.75"],
            "created_at": now_ms(),
        }

    def analyze_deep(self, branch: dict[str, Any]) -> dict[str, Any]:
        """进行更深入的论文候选分析。"""
        return {
            "id": new_id("deep"),
            "branch_id": branch.get("branch_id") or branch.get("id"),
            "paper_candidate": True,
            "claims": ["Dummy branch has a traceable mechanism and complete smoke-test evidence."],
            "created_at": now_ms(),
        }

    def summarize_experience(self, context: dict[str, Any]) -> dict[str, Any]:
        """测试节点不调用模型，由调度器保留确定性的基础总结。"""

        del context
        return {}


# ---- 基于提示词和大模型的工作节点 ---------------------------------------------

from ..storage.artifacts import ArtifactStore  # noqa: E402
from .llm import llm_from_goal  # noqa: E402


def _as_list(value) -> list:
    """将输入值转换为列表。"""
    return value if isinstance(value, list) else []


def _agent_call_metadata(result: Any, *, call_id: str, role: str) -> dict[str, Any] | None:
    """读取 Agent Adapter 的调用证据，并兼容独立 telemetry 返回字段。"""

    output = result.output if isinstance(getattr(result, "output", None), dict) else {}
    raw = output.get("__agent_call__")
    call = dict(raw) if isinstance(raw, dict) else {}
    telemetry = getattr(result, "telemetry", None)
    if isinstance(telemetry, dict) and telemetry:
        call.setdefault("telemetry", dict(telemetry))
    if not call:
        return None
    call.setdefault("id", call_id)
    call.setdefault("role", role)
    return call


def _observability_role(task: str) -> str:
    """把 single-LLM 节点名映射到与 CLI Agent 一致的角色。"""

    return {
        "idea_generator": "idea",
        "idea_rank_judge": "idea_rank",
        "method_designer": "implement",
        "experience_summarizer": "experience_summary",
    }.get(task, task)


def _implementation_goal_view(goal_doc: dict[str, Any]) -> dict[str, Any]:
    """构建不包含评测私有信息的目标视图。"""

    raw_goal = goal_doc.get("goal") if isinstance(goal_doc.get("goal"), dict) else {}
    goal = {"name": raw_goal["name"]} if "name" in raw_goal else {}
    benchmarks: list[dict[str, Any]] = []
    for benchmark in goal_doc.get("benchmarks") or []:
        if not isinstance(benchmark, dict):
            continue
        item = {
            key: benchmark[key]
            for key in (
                "name",
                "official_metric",
                "hidden_test_access",
                "score_interpretation",
            )
            if key in benchmark
        }
        benchmarks.append(item)
    constraints = goal_doc.get("constraints")
    safe_constraints = {}
    if isinstance(constraints, dict):
        for key in ("hidden_test_access", "external_data_policy"):
            if key in constraints:
                safe_constraints[key] = constraints[key]
    infra = goal_doc.get("infra") if isinstance(goal_doc.get("infra"), dict) else {}
    raw_resources = (
        infra.get("resources") if isinstance(infra.get("resources"), dict) else {}
    )
    public_resources: dict[str, Any] = {}
    if raw_resources:
        # 只提供总容量，不暴露物理 GPU UUID、调度租约或运行时利用率。
        from ..domain.resources import ResourceEnvelope

        public_resources = ResourceEnvelope.from_mapping(
            raw_resources
        ).to_public_dict()
        public_resources["resource_declarations_required"] = bool(
            raw_resources.get("resource_declarations_required", False)
        )
    return {
        "goal": goal,
        "objective_brief": goal_doc.get("objective_brief") or {},
        "baselines": goal_doc.get("baselines") or [],
        "benchmarks": benchmarks,
        "constraints": safe_constraints,
        "benchmark_task": _public_benchmark_task(goal_doc),
        "infra": {"resources": public_resources} if public_resources else {},
        # 新 Loop 通过 lineage 只读访问旧 Loop；不把旧产物复制到当前工作区。
        "lineage": goal_doc.get("lineage") or {},
    }


def _public_benchmark_task(goal_doc: dict[str, Any]) -> dict[str, Any]:
    """返回可以暴露给实现智能体的 benchmark 任务配置。"""
    task = goal_doc.get("benchmark_task")
    if not isinstance(task, dict):
        return {}
    blocked = {
        "private_dir",
        "task_dir",
        "evaluator_dir",
        "ground_truth_dir",
        "official_eval_cmd",
    }
    return {key: value for key, value in task.items() if key not in blocked}


def _implementation_contract(goal_doc: dict[str, Any]) -> dict[str, Any]:
    """根据普通科研或 benchmark 任务生成实现入口契约。"""
    task = _public_benchmark_task(goal_doc)
    if task:
        task_contract = (
            task.get("contract") if isinstance(task.get("contract"), dict) else {}
        )
        # Harness 把 BenchmarkFacility.task_view().metadata 放在 contract 下。
        # 入口要求必须从该设施契约传到 Agent wrapper，不能要求每个 benchmark
        # 再把相同字段复制到 benchmark_task 顶层。
        entrypoint = (
            task.get("entrypoint")
            or task_contract.get("entrypoint")
            or task_contract.get("required_entrypoint")
        )
        entrypoint_interface = (
            task.get("entrypoint_interface")
            or task_contract.get("entrypoint_interface")
        )
        contract: dict[str, Any] = {
            "entrypoint_must_be_executable": bool(entrypoint),
            "files_must_be_relative": True,
            "public_task_dir": "benchmark_task",
            "evaluator_and_hidden_data_are_unavailable": True,
        }
        if entrypoint:
            contract["entrypoint"] = str(entrypoint)
        if entrypoint_interface:
            contract["entrypoint_interface"] = str(entrypoint_interface)
        elif task_contract.get("input_environment") or task_contract.get(
            "output_environment"
        ):
            input_env = str(task_contract.get("input_environment") or "benchmark input")
            output_env = str(
                task_contract.get("output_environment") or "benchmark output"
            )
            contract["entrypoint_interface"] = f"{input_env} -> {output_env}"
        execution_limits = (
            task.get("execution_limits")
            if isinstance(task.get("execution_limits"), dict)
            else {}
        )
        canonical_timeout = task_contract.get(
            "canonical_timeout_sec",
            execution_limits.get("canonical_timeout_sec"),
        )
        if canonical_timeout is not None:
            contract["canonical_timeout_sec"] = float(
                canonical_timeout
            )
        return contract
    return {
        "entrypoint_must_be_executable": True,
        "entrypoint_interface": "python <entrypoint> --output <path>",
        "files_must_be_relative": True,
        "evaluator_and_hidden_data_are_unavailable": True,
    }


def _source_worktree(
    workspace: str | Path,
    idea: dict[str, Any],
) -> Path | None:
    """解析受信任的上一轮分支源码目录。"""
    branch_id = str(idea.get("source_branch_id") or "")
    if not branch_id:
        return None
    if branch_id != safe_name(branch_id):
        return None
    root = Path(workspace).resolve()
    candidate = (root / "branches" / branch_id / "worktree").resolve()
    try:
        candidate.relative_to(root / "branches")
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None
def _stage_public_benchmark_task(
    agent_workspace: AgentWorkspace,
    goal_doc: dict[str, Any],
) -> None:
    """把 benchmark 公开说明和数据入口放入分支工作区。"""
    task = _public_benchmark_task(goal_doc)
    source_value = task.get("public_dir")
    if not source_value:
        return
    source = Path(str(source_value)).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"benchmark public_dir 不存在: {source}")
    if source.name.lower() in {"evaluation", "evaluator", "ground_truth", "hidden", "private"}:
        raise ValueError(f"benchmark public_dir 不能指向私有评测目录: {source}")

    target = agent_workspace.worktree / "benchmark_task"
    target.mkdir(parents=True, exist_ok=True)
    blocked_names = {"evaluation", "evaluator", "ground_truth", "hidden", "private"}
    for item in source.iterdir():
        if item.name.lower() in blocked_names or item.name.startswith(".git"):
            continue
        destination = target / item.name
        if destination.exists() or destination.is_symlink():
            continue
        if item.is_dir():
            destination.symlink_to(item, target_is_directory=True)
        elif item.is_file():
            shutil.copy2(item, destination)


def _score_interpretation(goal_doc: dict[str, Any]) -> dict[str, Any] | None:
    """读取 Benchmark Facility 暴露的公开评分等级定义。"""

    task = goal_doc.get("benchmark_task")
    if isinstance(task, dict):
        direct = task.get("score_interpretation")
        if isinstance(direct, dict):
            return direct
        contract = task.get("contract")
        if isinstance(contract, dict) and isinstance(
            contract.get("score_interpretation"), dict
        ):
            return contract["score_interpretation"]
    for benchmark in goal_doc.get("benchmarks") or []:
        if isinstance(benchmark, dict) and isinstance(
            benchmark.get("score_interpretation"), dict
        ):
            return benchmark["score_interpretation"]
    return None


def _normalize_expected_return(
    value: Any,
    goal_doc: dict[str, Any],
) -> dict[str, Any] | None:
    """校验 Idea 的收益预测；该预测不得被当作正式 evaluator 指标。"""

    if not isinstance(value, dict):
        return None
    criteria = _score_interpretation(goal_doc) or {}
    levels = {
        str(item.get("name"))
        for item in criteria.get("levels") or []
        if isinstance(item, dict) and item.get("name")
    }
    target_level = str(value.get("target_level") or "")
    if target_level not in levels | {"uncertain"}:
        return None

    expected_metric = value.get("expected_metric")
    if not isinstance(expected_metric, dict):
        return None
    metric_name = str(expected_metric.get("name") or "")
    public_metric = str(criteria.get("metric") or "")
    if not metric_name or (public_metric and metric_name != public_metric):
        return None

    metric_range = expected_metric.get("range")
    normalized_range = None
    if metric_range is not None:
        if not isinstance(metric_range, dict):
            return None
        lower = metric_range.get("lower")
        upper = metric_range.get("upper")
        if any(
            isinstance(bound, bool)
            or not isinstance(bound, (int, float))
            or not math.isfinite(float(bound))
            for bound in (lower, upper)
        ):
            return None
        if float(lower) > float(upper):
            return None
        normalized_range = {"lower": float(lower), "upper": float(upper)}

    confidence = str(value.get("confidence") or "")
    if confidence not in {"low", "medium", "high"}:
        return None
    basis_value = value.get("basis")
    if not isinstance(basis_value, list):
        return None
    basis = [
        item.strip()
        for item in basis_value
        if isinstance(item, str) and item.strip()
    ]
    assumptions_value = value.get("assumptions")
    if not basis or not isinstance(assumptions_value, list):
        return None
    assumptions = [
        item.strip()
        for item in assumptions_value
        if isinstance(item, str) and item.strip()
    ]
    return {
        "target_level": target_level,
        "expected_metric": {
            "name": metric_name,
            "range": normalized_range,
        },
        "confidence": confidence,
        "basis": basis,
        "assumptions": assumptions,
    }


def _valid_idea(obj: dict[str, Any], goal_doc: dict[str, Any]) -> bool:
    """校验候选想法和公开目标要求的收益预测。"""

    if not isinstance(obj, dict) or not obj.get("title") or not obj.get("mechanism"):
        return False
    criteria = _score_interpretation(goal_doc)
    if criteria is not None or "expected_return" in obj:
        return (
            _normalize_expected_return(obj.get("expected_return"), goal_doc)
            is not None
        )
    return True


_MAX_METHOD_FILES = 64
_FORBIDDEN_METHOD_PARTS = {
    ".git",
    ".famou",
    "__pycache__",
    "control",
    "evaluator",
    "evaluators",
    "hidden",
    "test",
    "tests",
    "benchmark_task",
}


def _safe_method_path(value: Any) -> str:
    """规范化方法文件路径并拒绝越界。"""

    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute():
        raise ValueError(f"method file path must be relative: {value!r}")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts or ".." in parts:
        raise ValueError(f"method file path contains traversal: {value!r}")
    if any(part in _FORBIDDEN_METHOD_PARTS for part in parts):
        raise ValueError(f"method file path is reserved: {value!r}")
    normalized = "/".join(parts)
    if len(normalized) > 240:
        raise ValueError("method file path is too long")
    return normalized


def _method_files_from_output(output: dict[str, Any]) -> list[dict[str, str]]:
    """读取模型返回的显式代码文件列表。"""

    raw_files = output.get("files")
    if isinstance(raw_files, dict):
        raw_files = [
            {"path": path, "content": content}
            for path, content in raw_files.items()
        ]
    if not isinstance(raw_files, list) and isinstance(output.get("code"), str):
        raw_files = [
            {
                "path": output.get("entrypoint") or "method.py",
                "content": output["code"],
            }
        ]
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("method_designer must return a non-empty files list")
    if len(raw_files) > _MAX_METHOD_FILES:
        raise ValueError(f"method_designer returned too many files: {len(raw_files)}")

    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise ValueError(f"method_designer.files[{index}] must be an object")
        path = _safe_method_path(item.get("path"))
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError(f"method_designer.files[{index}].content must be a string")
        if path in seen:
            raise ValueError(f"method_designer returned duplicate file: {path}")
        seen.add(path)
        files.append({"path": path, "content": content})
    return files


def _method_spec_from_output(
    output: dict[str, Any],
    *,
    idea: dict[str, Any],
    branch_id: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """根据单次调用输出构建方法规格。"""
    if not isinstance(output, dict):
        raise ValueError("method_designer output must be an object")
    files = _method_files_from_output(output)
    raw_entrypoint = output.get("entrypoint")
    entrypoint = _safe_method_path(raw_entrypoint) if raw_entrypoint else ""
    file_paths = {item["path"] for item in files}
    if not entrypoint:
        py_files = [item["path"] for item in files if item["path"].endswith(".py")]
        entrypoint = py_files[0] if py_files else ""
    if not entrypoint or entrypoint not in file_paths:
        raise ValueError(
            "method_designer.entrypoint must point to one of the generated files"
        )
    if not entrypoint.endswith(".py"):
        raise ValueError("method_designer.entrypoint must be a Python file")
    spec = {
        "id": str(output.get("id") or new_id("method")),
        "branch_id": branch_id,
        "idea_id": idea.get("id"),
        "title": str(output.get("title") or idea.get("title") or "generated_method"),
        "summary": str(
            output.get("method_summary")
            or output.get("summary")
            or idea.get("mechanism")
            or ""
        ),
        "entrypoint": entrypoint,
        "files": [
            {
                "path": item["path"],
                "bytes": len(item["content"].encode("utf-8")),
            }
            for item in files
        ],
        "experiment_plan": _as_list(output.get("experiment_plan")),
        "limitations": _as_list(output.get("limitations")),
        "created_at": now_ms(),
    }
    return spec, files


def _implementation_resource_request(
    idea: dict[str, Any],
    output: dict[str, Any],
    search_decision: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """确定实现版本的资源声明，并处理 Switch 后的默认继承关系。"""

    override = output.get("resource_request")
    if isinstance(override, dict):
        return override
    opportunity = idea.get("search_opportunity")
    offered = (
        opportunity.get("offered_idea")
        if isinstance(opportunity, dict)
        else None
    )
    offered_id = str(offered.get("id") or "") if isinstance(offered, dict) else ""
    action = (
        str(search_decision.get("action") or "")
        if isinstance(search_decision, dict)
        else ""
    )
    reason = (
        str(search_decision.get("reason") or "").strip()
        if isinstance(search_decision, dict)
        else ""
    )
    declared_offered_id = (
        str(search_decision.get("offered_idea_id") or "")
        if isinstance(search_decision, dict)
        else ""
    )
    # 只有完整、归因一致的 Switch 才采用 offered Idea 的资源声明。非法决策
    # 会由 Search Policy 回退为 Refine，因此这里也必须继续沿用当前 Idea。
    valid_switch = (
        action == "switch"
        and bool(reason)
        and bool(offered_id)
        and (not declared_offered_id or declared_offered_id == offered_id)
    )
    if valid_switch and isinstance(offered, dict):
        offered_request = offered.get("resource_request")
        if isinstance(offered_request, dict):
            return offered_request
    current_request = idea.get("resource_request")
    return current_request if isinstance(current_request, dict) else None


def _method_spec_from_agent_workspace(
    agent_workspace: AgentWorkspace,
    output: dict[str, Any],
    *,
    idea: dict[str, Any],
    branch_id: str,
    source_root: Path | None = None,
    entrypoint_required: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """根据智能体工作空间产物构建方法规格，可选强制单一入口。"""

    if not isinstance(output, dict):
        raise ValueError("implement agent output must be an object")

    method_root = (source_root or agent_workspace.worktree).resolve()
    manifest_path = method_root / "method_manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw_manifest, dict):
                manifest = raw_manifest
        except json.JSONDecodeError as exc:
            raise ValueError(f"agent method_manifest.json is invalid: {exc}") from exc

    raw_files = output.get("files")
    if raw_files is None:
        raw_files = manifest.get("files")
    if isinstance(raw_files, dict):
        raw_files = [{"path": path} for path in raw_files]
    if not isinstance(raw_files, list):
        raw_files = []

    requested_paths: list[str] = []
    for index, item in enumerate(raw_files):
        if isinstance(item, str):
            raw_path = item
        elif isinstance(item, dict):
            raw_path = item.get("path")
        else:
            raise ValueError(f"implement agent files[{index}] must be a path or object")
        requested_paths.append(_safe_method_path(raw_path))

    raw_entrypoint = output.get("entrypoint") or manifest.get("entrypoint")
    entrypoint = _safe_method_path(raw_entrypoint) if raw_entrypoint else ""
    if entrypoint_required and not entrypoint and requested_paths:
        py_files = [path for path in requested_paths if path.endswith(".py")]
        entrypoint = py_files[0] if py_files else ""
    if entrypoint_required and not entrypoint:
        py_files = sorted(
            path.relative_to(method_root).as_posix()
            for path in method_root.rglob("*.py")
            if path.is_file() and not path.is_symlink()
        )
        if py_files:
            entrypoint = _safe_method_path(py_files[0])
            requested_paths.append(entrypoint)
    if entrypoint_required and not entrypoint:
        raise ValueError("implement agent must create or report a Python entrypoint")
    if entrypoint and entrypoint not in requested_paths:
        requested_paths.append(entrypoint)
    if not requested_paths:
        # 无单一入口的源码包仍需形成证据清单。显式提交快照已经排除公开数据
        # 链接和运行产物，这里只枚举其中的普通文件。
        requested_paths = sorted(
            path.relative_to(method_root).as_posix()
            for path in method_root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.name != "method_manifest.json"
        )
    if not requested_paths:
        raise ValueError("implement agent must create or report at least one source file")

    # 保持智能体返回顺序的同时去重。
    requested_paths = list(dict.fromkeys(requested_paths))
    if len(requested_paths) > _MAX_METHOD_FILES:
        raise ValueError(f"implement agent created/reported too many files: {len(requested_paths)}")

    written_files: list[dict[str, Any]] = []
    for relative_path in requested_paths:
        target = (method_root / relative_path).resolve()
        try:
            target.relative_to(method_root)
        except ValueError as exc:
            raise ValueError(
                f"implement agent file escapes submitted worktree: {relative_path}"
            ) from exc
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"implement agent file does not exist or is a symlink: {relative_path}")
        file_bytes = target.stat().st_size
        written_files.append(
            {
                "path": relative_path,
                "absolute_path": str(target),
                "bytes": file_bytes,
                "sha256": sha256_file(target),
            }
        )

    spec = {
        "id": str(output.get("id") or manifest.get("id") or new_id("method")),
        "branch_id": branch_id,
        "idea_id": idea.get("id"),
        "title": str(
            output.get("title")
            or manifest.get("title")
            or idea.get("title")
            or "agent_generated_method"
        ),
        "summary": str(
            output.get("method_summary")
            or output.get("summary")
            or manifest.get("method_summary")
            or manifest.get("summary")
            or idea.get("mechanism")
            or ""
        ),
        "entrypoint": entrypoint or None,
        "files": [
            {"path": item["path"], "bytes": item["bytes"]}
            for item in written_files
        ],
        "experiment_plan": _as_list(
            output.get("experiment_plan") or manifest.get("experiment_plan")
        ),
        "limitations": _as_list(
            output.get("limitations") or manifest.get("limitations")
        ),
        "created_at": now_ms(),
    }
    return spec, written_files


class PromptWorkerSet:
    """使用提示词和大模型驱动工作节点集合。"""

    def __init__(
        self,
        goal_doc: dict[str, Any],
        workspace: str | Path,
        *,
        llm=None,
        prompt_dir: str | Path | None = None,
        config_dir: str | Path | None = None,
    ):
        """初始化对象并保存必要配置。"""
        self.goal_doc = goal_doc
        self.workspace = Path(workspace)
        self.workflow_type = workflow_type(goal_doc)
        self.llm = llm or llm_from_goal(goal_doc, workspace)
        self.artifacts = ArtifactStore(workspace)
        self.observability = ObservabilityStore(workspace)
        workers_config = goal_doc.get("workers") if isinstance(goal_doc.get("workers"), dict) else {}
        idea_config = (
            workers_config.get("idea")
            if isinstance(workers_config.get("idea"), dict)
            else {}
        )
        self.idea_mode = str(
            idea_config.get("type")
            or workers_config.get("idea_mode")
            or "single_call"
        ).lower()
        self.idea_config = dict(idea_config)
        self.idea_config.setdefault(
            "cancel_file",
            str(self.workspace / "agent_control" / "research_deadline_reached.json"),
        )
        self.idea_agent = None
        if self.idea_mode in {"agent", "command_agent"}:
            self.idea_config["role"] = "idea"
            self.idea_agent = _create_agent_adapter(
                self.idea_config,
                config_dir=config_dir,
            )
        elif self.idea_mode not in {"single_call", "llm", "single"}:
            raise ValueError(
                "workers.idea.type must be one of single_call or agent"
            )
        idea_rank_config = (
            workers_config.get("idea_rank")
            if isinstance(workers_config.get("idea_rank"), dict)
            else {}
        )
        self.idea_rank_mode = str(
            idea_rank_config.get("type") or "single_call"
        ).lower()
        self.idea_rank_config = dict(idea_rank_config)
        # Judge 未显式声明运行时/模型/端点时继承 Idea Agent 的配置：Judge 只是
        # 换了提示词的同一类调用，缺一项就整体失败（历史上因此静默退回 FIFO）
        # 比沿用 Idea 侧已验证可用的凭据更糟。
        for key in (
            "runtime",
            "model",
            "binary",
            "base_url",
            "api_key",
            "api_key_env",
            "settings",
            "config",
            "env",
        ):
            if self.idea_rank_config.get(key) in (None, "") and self.idea_config.get(key) not in (
                None,
                "",
            ):
                self.idea_rank_config[key] = self.idea_config[key]
        self.idea_rank_config.setdefault(
            "cancel_file",
            str(self.workspace / "agent_control" / "research_deadline_reached.json"),
        )
        self.idea_rank_agent = None
        if self.idea_rank_mode in {"agent", "command_agent"}:
            self.idea_rank_config["role"] = "idea_rank"
            self.idea_rank_agent = _create_agent_adapter(
                self.idea_rank_config,
                config_dir=config_dir,
            )
        elif self.idea_rank_mode not in {"single_call", "llm", "single"}:
            raise ValueError(
                "workers.idea_rank.type must be one of single_call or agent"
            )
        idea_judge_config = (
            workers_config.get("idea_judge")
            if isinstance(workers_config.get("idea_judge"), dict)
            else {}
        )
        self.idea_judge_mode = str(
            idea_judge_config.get("type") or "single_call"
        ).lower()
        self.idea_judge_config = dict(idea_judge_config)
        # 与 idea_rank 同样的继承规则：Judge 只是换了提示词的同一类调用，
        # 缺一项凭据就整体失败，比沿用 Idea 侧已验证可用的配置更糟。
        for key in (
            "runtime",
            "model",
            "binary",
            "base_url",
            "api_key",
            "api_key_env",
            "settings",
            "config",
            "env",
        ):
            if self.idea_judge_config.get(key) in (None, "") and self.idea_config.get(
                key
            ) not in (None, ""):
                self.idea_judge_config[key] = self.idea_config[key]
        self.idea_judge_config.setdefault(
            "cancel_file",
            str(self.workspace / "agent_control" / "research_deadline_reached.json"),
        )
        self.idea_judge_agent = None
        if self.idea_judge_mode in {"agent", "command_agent"}:
            self.idea_judge_config["role"] = "idea_judge"
            self.idea_judge_agent = _create_agent_adapter(
                self.idea_judge_config,
                config_dir=config_dir,
            )
        elif self.idea_judge_mode not in {"single_call", "llm", "single"}:
            raise ValueError(
                "workers.idea_judge.type must be one of single_call or agent"
            )
        experience_summary_config = (
            workers_config.get("experience_summary")
            if isinstance(workers_config.get("experience_summary"), dict)
            else {}
        )
        self.experience_summary_mode = str(
            experience_summary_config.get("type") or "single_call"
        ).lower()
        self.experience_summary_config = dict(experience_summary_config)
        self.experience_summary_config.setdefault("format", "markdown")
        self.experience_summary_agent = None
        if self.experience_summary_mode in {"agent", "command_agent"}:
            self.experience_summary_config["role"] = "experience_summary"
            self.experience_summary_agent = _create_agent_adapter(
                self.experience_summary_config,
                config_dir=config_dir,
            )
        elif self.experience_summary_mode not in {"single_call", "llm", "single"}:
            raise ValueError(
                "workers.experience_summary.type must be one of single_call or agent"
            )
        implement_config = (
            workers_config.get("implement")
            if isinstance(workers_config.get("implement"), dict)
            else {}
        )
        self.implementation_mode = str(
            implement_config.get("type")
            or workers_config.get("implement_mode")
            or "single_call"
        ).lower()
        self.implementation_config = dict(implement_config)
        self.implementation_config_dir = (
            Path(config_dir).expanduser().resolve() if config_dir else None
        )
        # 所有外部 Agent 都观察同一个任务级取消信号。benchmark-managed
        # Harness 会在配置中提供相同路径；开放科研模式也必须能被 Master stop
        # 及时终止，而不是等当前 Agent timeout 自然耗尽。
        self.implementation_config.setdefault(
            "cancel_file",
            str(self.workspace / "agent_control" / "research_deadline_reached.json"),
        )
        self.implement_agent = None
        if self.implementation_mode in {"agent", "command_agent"}:
            if workflow_type(goal_doc) == "benchmark_managed":
                # 明确 benchmark 的 Candidate 必须由 Agent 主动提交；普通开放科研
                # 暂时保留旧 command agent 兼容路径。
                self.implementation_config.setdefault(
                    "require_submit_candidate",
                    True,
                )
                self.implementation_config.setdefault("submission_grace_sec", 20)
            self.implement_agent = _create_agent_adapter(
                self.implementation_config,
                config_dir=self.implementation_config_dir,
            )
        elif self.implementation_mode not in {"single_call", "llm", "single"}:
            raise ValueError(
                "workers.implement.type must be one of "
                "single_call or agent"
            )
        validity_config = (
            workers_config.get("validity_verifier")
            if isinstance(workers_config.get("validity_verifier"), dict)
            else {}
        )
        self.validity_verifier_config = dict(validity_config)
        self.validity_verifier_mode = str(
            validity_config.get("type") or "disabled"
        ).lower()
        self.validity_verifier_agent = None
        if self.validity_verifier_mode in {"agent", "command_agent"}:
            self.validity_verifier_config["role"] = "terminal_verifier"
            self.validity_verifier_config.setdefault("session_key", "validity_verifier")
            self.validity_verifier_agent = _create_agent_adapter(
                self.validity_verifier_config,
                config_dir=self.implementation_config_dir,
            )
        elif self.validity_verifier_mode not in {"disabled", "none", "off"}:
            raise ValueError(
                "workers.validity_verifier.type must be one of disabled or agent"
            )
        prompt_root = Path(__file__).resolve().parents[1] / "prompts"
        self.allow_prompt_fallback = prompt_dir is None
        if prompt_dir:
            self.prompt_dir = Path(prompt_dir)
        elif workflow_type(goal_doc) == "benchmark_managed":
            self.prompt_dir = prompt_root / "benchmark_managed"
        else:
            self.prompt_dir = prompt_root / "research"
        self.fallback_prompt_dir = prompt_root / "research"

    def _prompt(self, name: str) -> str:
        """读取指定任务的提示模板。"""
        prompt_name = (
            "idea_agent"
            if name == "idea_generator" and self.prompt_dir.name == "benchmark_managed"
            else name
        )
        if self.prompt_dir.name == "benchmark_managed":
            if prompt_name == "idea_agent":
                version = os.environ.get(
                    "FAMOU_IDEA_PROMPT_VERSION", "v1"
                ).strip().lower()
            elif prompt_name == "implement_agent":
                version = os.environ.get(
                    "FAMOU_IMPLEMENT_PROMPT_VERSION", "v1"
                ).strip().lower()
            else:
                version = "v1"
            if version in {"v8", "8", "operator-v8"}:
                prompt_name += "_v8"
            elif version in {"v7", "7", "rules-v7"}:
                prompt_name += "_v7"
            elif version in {"v6", "6", "selftask-v6"}:
                prompt_name += "_v6"
            elif version in {"v5", "5", "expbank-v5"}:
                prompt_name += "_v5"
            elif version in {"v4", "4", "debate-v4"}:
                prompt_name += "_v4"
            elif version in {"v3", "3", "validity-v3"}:
                prompt_name += "_v3"
            elif version in {"v2", "2", "expbank-v2", "algorithm-v2"}:
                prompt_name += "_v2"
        path = self.prompt_dir / f"{prompt_name}.md"
        if (
            not path.is_file()
            and self.allow_prompt_fallback
            and self.prompt_dir != self.fallback_prompt_dir
        ):
            path = self.fallback_prompt_dir / f"{name}.md"
        if not path.is_file():
            raise FileNotFoundError(f"worker Prompt 文件不存在: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _call(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        """调用模型工作节点并保存证据。"""
        prompt = self._prompt(task)
        try:
            out = self.llm.complete_json(task, prompt, context)
            meta = out.get("__worker_call__") if isinstance(out, dict) else None
            if isinstance(meta, dict):
                self.artifacts.save_json("worker_call", {"id": meta.get("id"), "task": task, "valid": True, "meta": meta})
                self.observability.record_agent_call(
                    meta,
                    task=task,
                    role=_observability_role(task),
                    valid=True,
                )
            return out
        except Exception as exc:  # noqa: BLE001 - fail closed by caller
            call_meta = getattr(exc, "call_meta", None)
            self.artifacts.save_json(
                "worker_call",
                {
                    "id": call_meta.get("id") if isinstance(call_meta, dict) else None,
                    "task": task,
                    "valid": False,
                    "error": repr(exc),
                    "meta": call_meta if isinstance(call_meta, dict) else {},
                    "created_at": now_ms(),
                },
            )
            if isinstance(call_meta, dict):
                self.observability.record_agent_call(
                    call_meta,
                    task=task,
                    role=_observability_role(task),
                    valid=False,
                )
            raise

    def generate_ideas(self, goal: dict[str, Any], experience: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """生成候选研究想法。"""
        try:
            # ExpBank 路径直接交给 Idea Agent。Agent 可先读 INDEX.md，再按需查看
            # 历史代码与证据；这里不截断成“最近若干条”的摘要。
            #
            # ``expbank_dir`` 是**本任务**的 ExpBank（``<run>/expbank``，含
            # INDEX.md 和逐 attempt 记录）；``cross_task_expbank_dir`` 是**别的
            # 任务**的经验快照（含 ``index.jsonl`` 和逐 run Markdown）。两者以前
            # 只下发前者，而提示词却把 ``expbank_dir`` 描述成跨任务快照、让 Agent
            # 去读 ``<expbank_dir>/INDEX.md`` 筛 domain——实测 20 个 run 没有一个
            # 打开过跨任务目录，只能盲开载荷里给的 20 条 summary_path。
            context = {
                "goal": goal,
                "experience": experience,
                "expbank_dir": str(self.workspace / "expbank"),
                "cross_task_expbank_dir": self._cross_task_expbank_dir(goal),
                "lineage": goal.get("lineage") if isinstance(goal, dict) else {},
            }
            if self.idea_agent is None:
                out = self._call("idea_generator", context)
            else:
                # 开放科研中的 IdeaAgent 是长生命周期的逻辑 Actor：每个回合只提交
                # 一条 Idea，Gate 同步返回后立即恢复同一 CLI Session。完整 benchmark
                # 仍保留独立调用，避免并发生产者共享一个 Session。
                call_id = new_id("idea_agent")
                continuous = self.workflow_type != "benchmark_managed"
                actor_id = "idea_agent_main" if continuous else call_id
                idea_workspace_root = self.workspace / "idea_agent_workspaces"
                actor_root = idea_workspace_root / "branches" / actor_id
                if continuous and actor_root.exists():
                    agent_workspace = AgentWorkspace.open(idea_workspace_root, actor_id)
                    agent_workspace.write_public_json("context.json", context)
                else:
                    agent_workspace = AgentWorkspace.create(
                        idea_workspace_root,
                        actor_id,
                        public_payload=context,
                        metadata={
                            "role": "idea",
                            "continuous": continuous,
                        },
                    )
                sandbox = sandbox_from_config(
                    self.idea_config.get("sandbox"),
                    agent_workspace.root,
                )
                try:
                    result = self.idea_agent.implement(
                        ImplementRequest(
                            goal=_implementation_goal_view(goal),
                            idea={"id": f"{call_id}-seed"},
                            workspace=agent_workspace,
                            sandbox=sandbox,
                            instruction=self._prompt("idea_generator"),
                            metadata=context,
                        )
                    )
                finally:
                    sandbox.close()
                self.artifacts.save_json(
                    "worker_call",
                    {
                        "id": call_id,
                        "task": "idea_generator",
                        "implementation_mode": "command_agent",
                        "idea_actor_id": actor_id,
                        "valid": result.status == LoopStatus.Implementation.IMPLEMENTED,
                        "result": result.to_dict(),
                    },
                )
                agent_call = _agent_call_metadata(
                    result,
                    call_id=call_id,
                    role="idea",
                )
                if isinstance(agent_call, dict):
                    self.observability.record_agent_call(
                        agent_call,
                        task="idea_generator",
                        role="idea",
                        valid=(
                            result.status
                            == LoopStatus.Implementation.IMPLEMENTED
                        ),
                        metadata={"idea_actor_id": actor_id},
                    )
                if result.status != LoopStatus.Implementation.IMPLEMENTED:
                    return []
                out = {
                    key: value
                    for key, value in result.output.items()
                    if key != "__agent_call__"
                }
                out.setdefault("idea_actor_id", actor_id)
            ideas = _as_list(out.get("ideas"))
            if not ideas and isinstance(out, dict) and out.get("title"):
                ideas = [out]
            # 长生命周期 IdeaActor 每个回合只发布一条可审计 Idea。若启用 Gate，
            # 后续方案在同步反馈后生成；关闭时也不一次预取 3-5 条旧策略方案。
            if self.idea_agent is not None and self.workflow_type != "benchmark_managed":
                ideas = ideas[:1]
        except Exception:  # noqa: BLE001
            return []
        valid = []
        for idea in ideas:
            if isinstance(idea, dict) and not idea.get("mechanism") and idea.get("method"):
                idea = {**idea, "mechanism": idea["method"]}
            if not _valid_idea(idea, goal):
                continue
            item = dict(idea)
            expected_return = _normalize_expected_return(
                item.get("expected_return"),
                goal,
            )
            if expected_return is not None:
                item["expected_return"] = expected_return
            item.setdefault("id", new_id("idea"))
            item.setdefault("created_at", now_ms())
            item.setdefault("expected_gain", [])
            item.setdefault("risks", [])
            item.setdefault("validation_plan", [])
            if out.get("idea_actor_id"):
                item.setdefault("idea_actor_id", out["idea_actor_id"])
            valid.append(item)
        directive = self._debate_directive(goal)
        if directive is None or not valid:
            return valid
        emitted: list[dict[str, Any]] = []
        for item in valid:
            emitted.extend(
                self._run_idea_debate(
                    goal,
                    item,
                    directive,
                    respond=lambda current, feedback, round_index, _item=item: (
                        self._author_response(
                            goal,
                            current,
                            feedback,
                            round_index,
                            context=context,
                            actor_id=str(_item.get("idea_actor_id") or ""),
                        )
                    ),
                )
            )
        return emitted

    def _author_response(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        feedback: dict[str, Any],
        round_index: int,
        *,
        context: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any] | None:
        """唤醒同一个 Idea Agent 分支来回应 Judge 的反馈。

        分支的 CLI Session 状态存放在 branch 的 logs 目录里，因此在同一个
        AgentWorkspace 上再次 implement 会自动 resume，作者能看到自己刚写的
        方案与判官的反馈，并有权拒绝修改。
        """

        if self.idea_agent is None or not actor_id:
            return None
        workspace_root = self.workspace / "idea_agent_workspaces"
        if not (workspace_root / "branches" / actor_id / "manifest.json").is_file():
            return None
        respond_context = {
            **context,
            "idea_debate": {
                "role": "author_response",
                "round": round_index,
                "max_rounds": feedback.get("max_rounds"),
                "current_idea": idea,
                "objections": feedback.get("objections") or [],
                "feedback_markdown": feedback.get("feedback_markdown"),
                # 作者有权拒绝：判官不得以"应向当前最优靠拢"为由要求修改，
                # 独立路线本身就是价值。
                "may_decline": True,
            },
        }
        try:
            agent_workspace = AgentWorkspace.open(workspace_root, actor_id)
            agent_workspace.write_public_json("context.json", respond_context)
        except Exception:  # noqa: BLE001 - 回应失败不得阻断 Idea 生产
            return None
        sandbox = sandbox_from_config(
            self.idea_config.get("sandbox"),
            agent_workspace.root,
        )
        call_id = new_id("idea_agent_response")
        try:
            result = self.idea_agent.implement(
                ImplementRequest(
                    goal=_implementation_goal_view(goal),
                    idea={"id": f"{call_id}-seed"},
                    workspace=agent_workspace,
                    sandbox=sandbox,
                    instruction=self._prompt("idea_generator"),
                    metadata=respond_context,
                )
            )
        except Exception:  # noqa: BLE001 - 回应失败不得阻断 Idea 生产
            return None
        finally:
            sandbox.close()
        self.artifacts.save_json(
            "worker_call",
            {
                "id": call_id,
                "task": "idea_author_response",
                "implementation_mode": "command_agent",
                "idea_actor_id": actor_id,
                "round": round_index,
                "valid": result.status == LoopStatus.Implementation.IMPLEMENTED,
                "result": result.to_dict(),
            },
        )
        if result.status != LoopStatus.Implementation.IMPLEMENTED:
            return None
        out = {
            key: value
            for key, value in result.output.items()
            if key != "__agent_call__"
        }
        answered = _as_list(out.get("ideas"))
        candidate = answered[0] if answered else (out if out.get("title") else None)
        if not isinstance(candidate, dict):
            return None
        if not candidate.get("mechanism") and candidate.get("method"):
            candidate = {**candidate, "mechanism": candidate["method"]}
        expected_return = _normalize_expected_return(
            candidate.get("expected_return"),
            goal,
        )
        if expected_return is not None:
            candidate = {**candidate, "expected_return": expected_return}
        return candidate

    def _run_idea_debate(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        directive: dict[str, Any],
        *,
        respond: "Callable[[dict[str, Any], dict[str, Any], int], dict[str, Any] | None]",
    ) -> list[dict[str, Any]]:
        """驱动 Judge 与 Idea 作者的辩论，返回要入队的 Idea 列表。

        默认返回一条（最终采用的版本）。开启 ``emit_pair`` 且内容真被改过时
        返回两条：原版与改写版各自独立实现、独立评测，构成同 Run 内的配对样本。
        这是唯一能把"辩论让 Idea 变好了吗"从任务难度、时段、集群波动里剥离出来
        的设计——run 级对照只有个位数配对点，idea 级一个 Run 就有十几对。

        任何一步失败都退回上一版可用的 Idea：辩论是增益环节，不能成为
        Idea 生产的新故障点。
        """

        mode = str(directive.get("mode") or "respond").lower()
        try:
            max_rounds = max(1, int(directive.get("max_rounds") or 1))
        except (TypeError, ValueError):
            max_rounds = 1
        current = dict(idea)
        rounds: list[dict[str, Any]] = []
        outcome = "no_objection"
        for round_index in range(1, max_rounds + 1):
            verdict = self._critique_idea(goal, current, directive, round_index)
            if not isinstance(verdict, dict):
                outcome = "judge_failed_idea_preserved"
                break
            objections = self._material_objections(verdict)
            entry = {
                "round": round_index,
                "max_rounds": max_rounds,
                "has_material_objection": bool(objections),
                "objections": objections,
                "feedback_markdown": verdict.get("feedback_markdown"),
                "summary": verdict.get("summary"),
            }
            # Judge 声称有意见但没有一条绑得上证据时，按契约视为没有意见。
            if not objections:
                rounds.append({**entry, "action": "keep"})
                outcome = "no_objection"
                break
            if mode == "rewrite":
                revised = verdict.get("revised_idea")
                if _valid_idea(revised, goal):
                    current = dict(revised)
                    current["id"] = idea.get("id")
                    rounds.append({**entry, "action": "judge_rewrote"})
                    outcome = "judge_rewrote"
                else:
                    rounds.append({**entry, "action": "rewrite_rejected"})
                    outcome = "rewrite_rejected_idea_preserved"
                    break
                continue
            answered = respond(current, entry, round_index)
            if not _valid_idea(answered, goal):
                rounds.append({**entry, "action": "author_failed"})
                outcome = "author_failed_idea_preserved"
                break
            revised = dict(answered)
            revised["id"] = idea.get("id")
            changed = revised != current
            current = revised
            rounds.append(
                {**entry, "action": "author_revised" if changed else "author_kept"}
            )
            outcome = "author_revised" if changed else "author_kept"
            if not changed:
                # 作者行使了拒绝权。多轮配置下不再纠缠，防止无意义的来回。
                break
        feedback_path = self._record_debate(idea, rounds, outcome)
        meta = {
            "mode": mode,
            "outcome": outcome,
            "rounds": len(rounds),
            "gate": directive.get("gate") or {},
            "feedback_path": feedback_path,
        }
        changed = outcome in {"author_revised", "judge_rewrote"}
        if not (directive.get("emit_pair") and changed):
            current["idea_debate"] = dict(meta)
            return [current]
        # 配对模式：原版与改写版都入队。两条共享 pair_id，各自独立 id；
        # 优先级必须相同（见 _schedule_benchmark_attempt 对 arm 的处理），
        # 否则改写版插队会让比较失去意义。origin 先入队，debated 紧随其后：
        # 同优先级按 seq 严格 FIFO，两条会被相邻消费。
        pair_id = new_id("idea_pair")
        origin = dict(idea)
        origin["idea_debate"] = {**meta, "arm": "origin", "pair_id": pair_id}
        debated = dict(current)
        debated["id"] = new_id("idea")
        debated["idea_debate"] = {
            **meta,
            "arm": "debated",
            "pair_id": pair_id,
            "origin_idea_id": idea.get("id"),
        }
        return [origin, debated]

    # ---- Idea Judge 辩论环节 ------------------------------------------

    @staticmethod
    def _debate_directive(goal: dict[str, Any]) -> dict[str, Any] | None:
        """读取 Controller 下发的辩论指令。

        闸门由 Orchestrator 判定（已跑时长 + in-task 证据条数），worker 层只执行。
        """

        runtime = goal.get("benchmark_runtime") if isinstance(goal, dict) else None
        directive = (
            runtime.get("idea_debate") if isinstance(runtime, dict) else None
        )
        if not isinstance(directive, dict) or directive.get("enabled") is not True:
            return None
        return directive

    def _cross_task_expbank_dir(self, goal: dict[str, Any]) -> str | None:
        """定位 Agent 侧只读的跨任务经验快照目录。"""

        infra = goal.get("infra") if isinstance(goal, dict) else None
        shared = infra.get("shared_experience") if isinstance(infra, dict) else None
        root = (
            shared.get("cross_task_expbank_root") if isinstance(shared, dict) else None
        )
        return str(root) if root else None

    def _critique_idea(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        directive: dict[str, Any],
        round_index: int,
    ) -> dict[str, Any] | None:
        """调用 Idea Judge，产出可核查的反对意见与反馈正文。"""

        context = {
            "goal": _implementation_goal_view(goal),
            "idea": idea,
            "mode": directive.get("mode"),
            "round": round_index,
            "max_rounds": directive.get("max_rounds"),
            "gate": directive.get("gate") or {},
            "expbank_dir": str(self.workspace / "expbank"),
            "expbank_index": str(self.workspace / "expbank" / "INDEX.md"),
            "cross_task_expbank_dir": self._cross_task_expbank_dir(goal),
        }
        if self.idea_judge_agent is None:
            try:
                return self._call("idea_judge", context)
            except Exception:  # noqa: BLE001 - 辩论失败不得阻断 Idea 生产
                return None
        call_id = new_id("idea_judge")
        agent_workspace = AgentWorkspace.create(
            self.workspace / "idea_judge_workspaces",
            call_id,
            public_payload=context,
            metadata={"role": "idea_judge", "continuous": False},
        )
        sandbox = sandbox_from_config(
            self.idea_judge_config.get("sandbox"),
            agent_workspace.root,
        )
        try:
            result = self.idea_judge_agent.implement(
                ImplementRequest(
                    goal=_implementation_goal_view(goal),
                    idea={"id": call_id, "under_review": idea},
                    workspace=agent_workspace,
                    sandbox=sandbox,
                    instruction=self._prompt("idea_judge"),
                    metadata=context,
                )
            )
        except Exception:  # noqa: BLE001 - 辩论失败不得阻断 Idea 生产
            return None
        finally:
            sandbox.close()
        self.artifacts.save_json(
            "worker_call",
            {
                "id": call_id,
                "task": "idea_judge",
                "implementation_mode": "command_agent",
                "idea_id": idea.get("id"),
                "round": round_index,
                "valid": result.status == LoopStatus.Implementation.IMPLEMENTED,
                "result": result.to_dict(),
            },
        )
        agent_call = _agent_call_metadata(result, call_id=call_id, role="idea_judge")
        if isinstance(agent_call, dict):
            self.observability.record_agent_call(
                agent_call,
                task="idea_judge",
                role="idea_judge",
                valid=result.status == LoopStatus.Implementation.IMPLEMENTED,
                metadata={"idea_id": idea.get("id"), "round": round_index},
            )
        if result.status != LoopStatus.Implementation.IMPLEMENTED:
            return None
        return {
            key: value
            for key, value in result.output.items()
            if key != "__agent_call__"
        }

    @staticmethod
    def _material_objections(verdict: dict[str, Any]) -> list[dict[str, Any]]:
        """只保留绑定了可核查对象的反对意见。

        提示词要求每条意见带 evidence_refs；没有依据的意见按契约丢弃，避免
        Judge 为了交差硬挑毛病而制造无意义的改写。
        """

        objections: list[dict[str, Any]] = []
        for item in _as_list(verdict.get("objections")):
            if not isinstance(item, dict):
                continue
            refs = [
                str(ref)
                for ref in _as_list(item.get("evidence_refs"))
                if str(ref).strip()
            ]
            statement = str(item.get("statement") or "").strip()
            if not refs or not statement:
                continue
            objections.append({**item, "evidence_refs": refs, "statement": statement})
        return objections

    def _record_debate(
        self,
        idea: dict[str, Any],
        rounds: list[dict[str, Any]],
        outcome: str,
    ) -> str | None:
        """把反馈正文与逐轮结论落盘，供事后复核。"""

        lines = [
            "# Idea Debate",
            "",
            f"- Idea: `{idea.get('id')}`",
            f"- 结果: `{outcome}`",
            "",
        ]
        for entry in rounds:
            lines.append(f"## Round {entry.get('round')}")
            lines.append("")
            lines.append(str(entry.get("feedback_markdown") or "(无反馈正文)"))
            lines.append("")
        try:
            path = self.artifacts.save_text("idea_debate", "\n".join(lines))
        except Exception:  # noqa: BLE001 - 落盘失败不得阻断 Idea 生产
            path = None
        self.artifacts.save_json(
            "idea_debate",
            {
                "idea_id": idea.get("id"),
                "outcome": outcome,
                "rounds": rounds,
                "feedback_path": path,
                "created_at": now_ms(),
            },
        )
        return path

    def idea_gate(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        experience: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """根据目标 Rubric 判断 Idea 是否应进入实现阶段。"""
        try:
            out = self._call(
                "idea_gate",
                {"goal": goal, "idea": idea, "experience": experience},
            )
        except Exception:  # noqa: BLE001
            return {
                "id": new_id("review"),
                "idea_id": idea.get("id"),
                "accept": False,
                "verdict": "reject",
                "decision": "reject",
                "reasons": ["Idea Gate 调用失败；按 fail-closed 拒绝进入实现"],
                "criterion_results": [],
                "actionable_revision": [],
                "reusable_lessons": [],
                "confidence": "high",
                "created_at": now_ms(),
            }
        raw_verdict = str(out.get("verdict") or "").strip().lower()
        if raw_verdict not in {"pass", "revise", "reject", "needs_evidence"}:
            raw_decision = str(out.get("decision") or "").strip().lower()
            if bool(out.get("accept")) or raw_decision == "accept_to_ideaspark":
                raw_verdict = "pass"
            else:
                raw_verdict = "reject"
        accept = raw_verdict == "pass"
        decision_by_verdict = {
            "pass": "accept_to_ideaspark",
            "revise": "revise_idea",
            "reject": "reject",
            "needs_evidence": "needs_evidence",
        }
        decision = decision_by_verdict[raw_verdict]
        return {
            "id": str(out.get("id") or new_id("review")),
            "idea_id": idea.get("id"),
            "accept": accept,
            "verdict": raw_verdict,
            "decision": decision,
            "reasons": _as_list(out.get("reasons"))
            or (["Idea Gate 通过"] if accept else ["Idea Gate 未通过"]),
            "risks": _as_list(out.get("risks")),
            "similar_prior_work": _as_list(out.get("similar_prior_work")),
            "criterion_results": [
                dict(item)
                for item in _as_list(out.get("criterion_results"))
                if isinstance(item, dict)
            ],
            "actionable_revision": _as_list(out.get("actionable_revision")),
            "reusable_lessons": _as_list(out.get("reusable_lessons")),
            "confidence": str(out.get("confidence") or "medium"),
            "created_at": now_ms(),
        }

    def rank_ideas(
        self,
        goal: dict[str, Any],
        ideas: list[dict[str, Any]],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        """调用独立 Judge，按剩余时间和资源对待实现 Idea 排序。"""

        context = {
            "goal": goal,
            "ideas": ideas,
            "runtime_context": runtime_context,
            "expbank_dir": str(self.workspace / "expbank"),
            "expbank_index": str(self.workspace / "expbank" / "INDEX.md"),
        }
        if self.idea_rank_agent is None:
            return self._call("idea_rank_judge", context)

        call_id = new_id("idea_rank_judge")
        workspace_root = self.workspace / "idea_rank_workspaces"
        agent_workspace = AgentWorkspace.create(
            workspace_root,
            call_id,
            public_payload=context,
            metadata={"role": "idea_rank", "continuous": False},
        )
        sandbox = sandbox_from_config(
            self.idea_rank_config.get("sandbox"),
            agent_workspace.root,
        )
        try:
            result = self.idea_rank_agent.implement(
                ImplementRequest(
                    goal=_implementation_goal_view(goal),
                    idea={"id": call_id, "candidates": ideas},
                    workspace=agent_workspace,
                    sandbox=sandbox,
                    instruction=self._prompt("idea_rank_judge"),
                    metadata=context,
                )
            )
        finally:
            sandbox.close()
        self.artifacts.save_json(
            "worker_call",
            {
                "id": call_id,
                "task": "idea_rank_judge",
                "implementation_mode": "command_agent",
                "valid": result.status == LoopStatus.Implementation.IMPLEMENTED,
                "result": result.to_dict(),
            },
        )
        agent_call = _agent_call_metadata(
            result,
            call_id=call_id,
            role="idea_rank",
        )
        if isinstance(agent_call, dict):
            self.observability.record_agent_call(
                agent_call,
                task="idea_rank_judge",
                role="idea_rank",
                valid=result.status == LoopStatus.Implementation.IMPLEMENTED,
            )
        if result.status != LoopStatus.Implementation.IMPLEMENTED:
            raise RuntimeError(result.error or "Idea Rank Judge 调用失败")
        return {
            key: value
            for key, value in result.output.items()
            if key != "__agent_call__"
        }

    def verify_candidate(
        self,
        candidate: dict[str, Any],
        *,
        context: dict[str, Any],
        session_key: str,
        resume: bool,
    ) -> dict[str, Any]:
        """唤醒可配置 Validity Verifier，并返回其结构化 verdict。"""

        if self.validity_verifier_agent is None:
            raise RuntimeError("validity verifier agent is disabled")
        call_id = new_id("validity_verifier")
        workspace_root = self.workspace / "validity_verifier_workspace"
        branch_id = "validity_verifier"
        if (workspace_root / "branches" / branch_id / "manifest.json").is_file():
            verifier_workspace = AgentWorkspace.open(workspace_root, branch_id)
        else:
            verifier_workspace = AgentWorkspace.create(
                workspace_root,
                branch_id,
                public_payload=context,
                metadata={"role": "validity_verifier"},
            )
        snapshot = verifier_workspace.public / "candidate_snapshot"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        source = Path(str(candidate.get("method_dir") or "")).expanduser().resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"validity verifier candidate directory not found: {source}")
        shutil.copytree(source, snapshot, symlinks=False)
        verifier_workspace.write_public_json(
            "validity_context.json",
            {**context, "candidate_snapshot": str(snapshot), "resume": bool(resume)},
        )
        sandbox = sandbox_from_config(
            _sandbox_config(self.validity_verifier_config, self.goal_doc),
            verifier_workspace.root,
        )
        try:
            result = self.validity_verifier_agent.implement(
                ImplementRequest(
                    goal=_implementation_goal_view(self.goal_doc),
                    idea={"id": call_id, "title": "validity_verifier"},
                    workspace=verifier_workspace,
                    sandbox=sandbox,
                    instruction=self._prompt("validity_verifier"),
                    metadata={
                        "validity_context": context,
                        "session_key": session_key,
                        "resume": bool(resume),
                    },
                )
            )
        finally:
            sandbox.close()
        self.artifacts.save_json(
            "worker_call",
            {
                "id": call_id,
                "task": "validity_verifier",
                "implementation_mode": "command_agent",
                "valid": result.status == LoopStatus.Implementation.IMPLEMENTED,
                "result": result.to_dict(),
            },
        )
        if result.status != LoopStatus.Implementation.IMPLEMENTED:
            raise RuntimeError(result.error or "Validity Verifier 调用失败")
        output = {
            key: value
            for key, value in result.output.items()
            if key != "__agent_call__"
        }
        call = result.output.get("__agent_call__")
        if isinstance(call, dict):
            session = call.get("session")
            if isinstance(session, dict) and session.get("state_path"):
                output["session_ref"] = str(session["state_path"])
        return output

    def summarize_experience(self, context: dict[str, Any]) -> dict[str, Any]:
        """在 Loop 收尾后总结演化轨迹和可迁移经验。"""

        if self.experience_summary_agent is None:
            return self._call("experience_summarizer", context)

        call_id = new_id("experience_summary")
        workspace_root = self.workspace / "experience_summary_workspaces"
        agent_workspace = AgentWorkspace.create(
            workspace_root,
            call_id,
            public_payload=context,
            metadata={"role": "experience_summary", "continuous": False},
        )
        sandbox = sandbox_from_config(
            _sandbox_config(self.experience_summary_config, self.goal_doc),
            agent_workspace.root,
        )
        try:
            result = self.experience_summary_agent.implement(
                ImplementRequest(
                    goal=_implementation_goal_view(self.goal_doc),
                    idea={"id": call_id, "task": "experience_summary"},
                    workspace=agent_workspace,
                    sandbox=sandbox,
                    instruction=self._prompt("experience_summarizer"),
                    metadata=context,
                )
            )
        finally:
            sandbox.close()

        self.artifacts.save_json(
            "worker_call",
            {
                "id": call_id,
                "task": "experience_summarizer",
                "implementation_mode": "command_agent",
                "valid": result.status == LoopStatus.Implementation.IMPLEMENTED,
                "result": result.to_dict(),
            },
        )
        agent_call = _agent_call_metadata(
            result,
            call_id=call_id,
            role="experience_summary",
        )
        if isinstance(agent_call, dict):
            self.observability.record_agent_call(
                agent_call,
                task="experience_summarizer",
                role="experience_summary",
                valid=result.status == LoopStatus.Implementation.IMPLEMENTED,
            )
        if result.status != LoopStatus.Implementation.IMPLEMENTED:
            raise RuntimeError(result.error or "跨任务经验总结 Agent 调用失败")
        return {
            key: value
            for key, value in result.output.items()
            if key != "__agent_call__"
        }

    def implement(self, idea: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
        """实现候选研究想法并返回结果。"""
        # 同一个逻辑 ImplementActor 始终拥有同一 branch/worktree。CandidateStore
        # 会在每次提交时冻结快照，因此复用工作区不会覆盖已经进入评测的代码。
        branch_id = str(idea.get("actor_branch_id") or new_id("branch"))
        agent_workspace: AgentWorkspace | None = None
        agent_session: dict[str, Any] | None = None
        search_decision: dict[str, Any] | None = None
        submitted_worktree: Path | None = None
        failure_details: dict[str, Any] = {}
        agent_call_ref: str | None = None
        try:
            implementation_contract = _implementation_contract(self.goal_doc)
            # source_worktree 仅允许指向调度器记录的上一最佳分支。新版本由该快照
            # 派生，同时仍写入全新的 branch workspace，避免原地覆盖历史代码。
            branch_root = Path(workspace).expanduser().resolve() / "branches" / branch_id
            public_payload = {
                "idea": idea,
                "implementation_contract": implementation_contract,
                "actor": {
                    "actor_id": idea.get("actor_id"),
                    "revision": idea.get("revision"),
                    "feedback_mailbox": idea.get("feedback_mailbox"),
                    "continuation_reason": idea.get("continuation_reason"),
                    "limits": idea.get("actor_limits"),
                },
            }
            if idea.get("actor_id") and branch_root.exists():
                # 长生命周期 Actor 的后续回合继续修改同一个 worktree；每次提交由
                # CandidateStore 冻结，因此复用工作区不会改写已评版本。
                agent_workspace = AgentWorkspace.open(workspace, branch_id)
                agent_workspace.write_public_json("context.json", public_payload)
            else:
                agent_workspace = AgentWorkspace.create(
                    workspace,
                    branch_id,
                    source_dir=_source_worktree(workspace, idea),
                    public_payload=public_payload,
                    metadata={
                        "implementation_mode": self.implementation_mode,
                        "actor_id": idea.get("actor_id"),
                    },
                )
            # 只把公开题面和公开数据入口放入分支；evaluation、GT、private 等目录
            # 会在 staging 时被显式排除。
            _stage_public_benchmark_task(agent_workspace, self.goal_doc)
            implementation_goal = _implementation_goal_view(self.goal_doc)
            if self.implement_agent is not None:
                request = ImplementRequest(
                    goal=implementation_goal,
                    idea=idea,
                    workspace=agent_workspace,
                    sandbox=sandbox_from_config(
                        self.implementation_config.get("sandbox"),
                        agent_workspace.root,
                    ),
                    instruction=self._prompt("implement_agent"),
                    metadata={
                        "implementation_contract": implementation_contract,
                        "actor_id": idea.get("actor_id"),
                        "revision": idea.get("revision"),
                        "feedback_mailbox": idea.get("feedback_mailbox"),
                        "expbank_dir": idea.get("expbank_dir"),
                        "prior_loop_dirs": idea.get("prior_loop_dirs"),
                        "actor_limits": idea.get("actor_limits"),
                    },
                )
                agent_result = self.implement_agent.implement(request)
                agent_output = dict(agent_result.output or {})
                if isinstance(agent_output.get("search_decision"), dict):
                    search_decision = dict(agent_output["search_decision"])
                agent_call = _agent_call_metadata(
                    agent_result,
                    call_id=new_id("implement_agent_call"),
                    role="implement",
                )
                if isinstance(agent_call, dict):
                    if isinstance(agent_call.get("session"), dict):
                        agent_session = dict(agent_call["session"])
                    agent_call_ref = self.artifacts.save_json(
                        "worker_call",
                        {
                            "id": agent_call.get("id") or new_id("implement_agent_call"),
                            "task": "implement_agent",
                            "implementation_mode": self.implementation_mode,
                            "valid": (
                                agent_result.status
                                == LoopStatus.Implementation.IMPLEMENTED
                            ),
                            "meta": agent_call,
                        },
                        meta={
                            "branch_id": branch_id,
                            "idea_id": idea.get("id"),
                            "implementation_mode": self.implementation_mode,
                        },
                    )
                    self.observability.record_agent_call(
                        agent_call,
                        task="implement_agent",
                        role="implement",
                        valid=(
                            agent_result.status
                            == LoopStatus.Implementation.IMPLEMENTED
                        ),
                        metadata={
                            "branch_id": branch_id,
                            "idea_id": idea.get("id"),
                            "actor_id": idea.get("actor_id"),
                            "revision": idea.get("revision"),
                        },
                    )
                if agent_result.status != LoopStatus.Implementation.IMPLEMENTED:
                    failure_details = dict(agent_result.failure or {})
                    raise RuntimeError(agent_result.error or "implement agent failed")
                submitted_worktree_value = agent_output.get("submitted_worktree")
                if submitted_worktree_value:
                    submitted_worktree = Path(str(submitted_worktree_value)).resolve()
                    try:
                        submitted_worktree.relative_to(agent_workspace.outputs.resolve())
                    except ValueError as exc:
                        raise ValueError(
                            "submitted worktree must be below branch outputs"
                        ) from exc
                    if not submitted_worktree.is_dir():
                        raise FileNotFoundError(
                            f"submitted worktree does not exist: {submitted_worktree}"
                        )
                # 不能只相信 Agent 返回的 status。这里重新从 branch worktree 枚举并
                # 校验入口和文件路径，越界路径、缺失入口或符号链接都会失败关闭。
                method_spec, written_files = _method_spec_from_agent_workspace(
                    agent_workspace,
                    agent_output,
                    idea=idea,
                    branch_id=branch_id,
                    source_root=submitted_worktree,
                    entrypoint_required=bool(
                        implementation_contract.get(
                            "entrypoint_must_be_executable",
                            False,
                        )
                    ),
                )
                implementation_type = "command_agent"
            else:
                output = self._call(
                    "method_designer",
                    {
                        "goal": implementation_goal,
                        "idea": idea,
                        "implementation_contract": implementation_contract,
                        "workspace": {
                            "root": str(agent_workspace.root),
                            "worktree": str(agent_workspace.worktree),
                            "public_dir": str(agent_workspace.public),
                            "outputs_dir": str(agent_workspace.outputs),
                        },
                        "actor": public_payload["actor"],
                        "expbank_dir": idea.get("expbank_dir"),
                        "prior_loop_dirs": idea.get("prior_loop_dirs"),
                    },
                )
                # 内部工作节点调用元数据可作为证据保留，但不应进入生成的方法规格。
                output = {
                    key: value
                    for key, value in output.items()
                    if key != "__worker_call__"
                }
                if isinstance(output.get("search_decision"), dict):
                    search_decision = dict(output["search_decision"])
                method_spec, files = _method_spec_from_output(
                    output,
                    idea=idea,
                    branch_id=branch_id,
                )
                written_files = []
                for item in files:
                    target = agent_workspace.write_worktree_text(
                        item["path"],
                        item["content"],
                    )
                    written_files.append(
                        {
                            "path": item["path"],
                            "absolute_path": str(target),
                            "bytes": len(item["content"].encode("utf-8")),
                            "sha256": sha256_file(target),
                        }
                    )
                implementation_type = "llm_method_designer"
            expected_entrypoint = implementation_contract.get("entrypoint")
            if expected_entrypoint and method_spec.get("entrypoint") != expected_entrypoint:
                # benchmark 可以固定 run.py 等入口名称，Agent 不能自行改成 evaluator
                # 不会调用的脚本。
                raise ValueError(
                    "benchmark implement agent entrypoint must be "
                    f"{expected_entrypoint!r}, got {method_spec.get('entrypoint')!r}"
                )
            manifest_path = agent_workspace.worktree / "method_manifest.json"
            # method_manifest 是 Runner 与证据系统之间的稳定接口：记录入口、代码文件、
            # 实验计划及 Agent 调用证据，但不包含 evaluator 结果。
            manifest = dict(method_spec)
            manifest["workspace"] = str(agent_workspace.root)
            manifest["worktree"] = str(agent_workspace.worktree)
            manifest["outputs"] = str(agent_workspace.outputs)
            manifest["files"] = written_files
            manifest["implementation_type"] = implementation_type
            if agent_call_ref:
                manifest["agent_call_ref"] = agent_call_ref
            atomic_write_json(manifest_path, manifest)
            method_root = (
                submitted_worktree
                if self.implement_agent is not None and submitted_worktree is not None
                else agent_workspace.worktree
            )
            if method_root != agent_workspace.worktree:
                # 这是 Controller 在提交时代码快照上补充的审计清单，不改变 Agent
                # 已提交的源码字节；CandidateStore 随后会整体冻结该目录。
                atomic_write_json(method_root / "method_manifest.json", manifest)
            agent_workspace.mark_status(
                LoopStatus.Implementation.IMPLEMENTED,
                implementation_type=implementation_type,
                method_manifest=str(manifest_path),
            )

            method_spec_ref = self.artifacts.save_json(
                "method_spec",
                manifest,
                meta={"branch_id": branch_id, "idea_id": idea.get("id")},
            )
            code_patch_refs = [
                # 每个实际代码文件单独进入 ArtifactStore，并通过 method_spec_ref 形成
                # 可追踪的“方法规格 -> 代码文件”关系。
                self.artifacts.save_file(
                    "code_patch",
                    agent_workspace.worktree / item["path"],
                    refs=[method_spec_ref],
                    meta={
                        "branch_id": branch_id,
                        "idea_id": idea.get("id"),
                        "relative_path": item["path"],
                    },
                )
                for item in written_files
            ]
            entrypoint_path = (
                method_root / str(method_spec["entrypoint"])
                if method_spec.get("entrypoint")
                else None
            )
            return {
                "id": branch_id,
                "branch_id": branch_id,
                "idea_id": idea.get("id"),
                "actor_id": idea.get("actor_id"),
                "revision": idea.get("revision"),
                "submission_id": (
                    agent_output.get("submission_id")
                    if self.implement_agent is not None
                    else None
                ),
                "artifact": str(manifest_path),
                "agent_workspace": str(agent_workspace.root),
                "worktree": str(method_root),
                "public_dir": str(agent_workspace.public),
                "outputs_dir": str(agent_workspace.outputs),
                "method_dir": str(method_root),
                "workdir": str(method_root),
                "actor_worktree": str(agent_workspace.worktree),
                "entrypoint": str(entrypoint_path) if entrypoint_path else None,
                "method_spec_ref": method_spec_ref,
                "code_patch_refs": code_patch_refs,
                "method_summary": method_spec["summary"],
                "experiment_plan": method_spec["experiment_plan"],
                "resource_request": _implementation_resource_request(
                    idea,
                    agent_output if self.implement_agent is not None else output,
                    search_decision,
                ),
                "status": LoopStatus.Implementation.IMPLEMENTED,
                "implementation_type": implementation_type,
                "agent_session": agent_session,
                "search_decision": search_decision,
                "isolation": "directory",
                "created_at": now_ms(),
            }
        except Exception as exc:  # noqa: BLE001 - fail closed, never write outside branch
            if agent_workspace is not None:
                # 失败也更新分支 manifest；上层随后会创建/更新对应 ExpBank 失败记录。
                agent_workspace.mark_status(
                    LoopStatus.Implementation.FAILED,
                    error=repr(exc),
                    failure=failure_details or None,
                )
            failed = {
                "id": branch_id,
                "branch_id": branch_id,
                "idea_id": idea.get("id"),
                "actor_id": idea.get("actor_id"),
                "agent_session": agent_session,
                "search_decision": search_decision,
                "agent_workspace": (
                    str(agent_workspace.root) if agent_workspace is not None else None
                ),
                "status": LoopStatus.Implementation.FAILED,
                "valid": False,
                "error": repr(exc),
                "implementation_type": self.implementation_mode,
                "created_at": now_ms(),
            }
            if agent_call_ref:
                failed["agent_call_ref"] = agent_call_ref
            if failure_details:
                failed["failure"] = failure_details
                failed["failure_stage"] = failure_details.get("failure_stage")
                failed["error_code"] = failure_details.get("error_code")
            return failed

    def analyze_result(self, branch: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
        """分析评测结果并给出后续决策。"""
        try:
            out = self._call("result_analyst", {"goal": self.goal_doc, "branch": branch, "results": results})
        except Exception:  # noqa: BLE001
            return {"id": new_id("analysis"), "branch_id": branch.get("branch_id") or branch.get("id"), "promote": False, "retry": False, "decision": "archive", "reasons": ["result_analyst worker failed; fail closed"], "created_at": now_ms()}
        promote = bool(out.get("promote"))
        retry = bool(out.get("retry"))
        if promote and retry:
            retry = False
        return {
            "id": str(out.get("id") or new_id("analysis")),
            "branch_id": branch.get("branch_id") or branch.get("id"),
            "promote": promote,
            "retry": retry,
            "decision": str(out.get("decision") or ("promote_to_analyze_spark" if promote else "retry" if retry else "archive")),
            "reasons": _as_list(out.get("reasons")) or ["no reasons provided"],
            "revised_idea": out.get("revised_idea"),
            "created_at": now_ms(),
        }

    def analyze_deep(self, branch: dict[str, Any]) -> dict[str, Any]:
        """进行更深入的论文候选分析。"""
        try:
            out = self._call("deep_analyzer", {"goal": self.goal_doc, "branch": branch})
        except Exception:  # noqa: BLE001
            return {"id": new_id("deep"), "branch_id": branch.get("branch_id") or branch.get("id"), "paper_candidate": False, "claims": [], "limitations": ["deep_analyzer worker failed; fail closed"], "created_at": now_ms()}
        return {
            "id": str(out.get("id") or new_id("deep")),
            "branch_id": branch.get("branch_id") or branch.get("id"),
            "paper_candidate": bool(out.get("paper_candidate")),
            "claims": _as_list(out.get("claims")),
            "limitations": _as_list(out.get("limitations")),
            "created_at": now_ms(),
        }


def workers_from_goal(goal_doc: dict[str, Any], workspace: str | Path, *, cwd: str | Path | None = None):
    """根据目标配置创建工作节点集合。"""
    workers = goal_doc.get("workers") if isinstance(goal_doc.get("workers"), dict) else {}
    if (
        workers.get("type") == "prompt"
        or isinstance(workers.get("idea"), dict)
        or isinstance(workers.get("implement"), dict)
    ):
        idea = workers.get("idea") if isinstance(workers.get("idea"), dict) else {}
        implement = (
            workers.get("implement")
            if isinstance(workers.get("implement"), dict)
            else {}
        )
        all_benchmark_nodes_are_agents = (
            workflow_type(goal_doc) == "benchmark_managed"
            and idea.get("type") in {"agent", "command_agent"}
            and implement.get("type") in {"agent", "command_agent"}
        )
        llm = (
            object()
            if all_benchmark_nodes_are_agents
            else llm_from_goal(goal_doc, workspace, cwd=cwd)
        )
        return PromptWorkerSet(goal_doc, workspace, llm=llm, config_dir=cwd)
    return DummyWorkerSet()
