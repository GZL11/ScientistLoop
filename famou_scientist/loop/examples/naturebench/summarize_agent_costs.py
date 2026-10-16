"""汇总 NatureBench 每个 case 的 Agent 调用、时长和 token 花费。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from famou_scientist.loop.observability import TokenPricingPolicy


CASE_ID_PATTERN = re.compile(r"s\d{5}-\d{3}-\d{5}-[0-9a-z]")
REPORTED_COST_PATTERN = re.compile(
    r'"(?:total_cost_usd|cost_usd)"\s*:\s*(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
)
ROLES = ("idea", "implement", "idea_rank", "idea_judge", "other")
TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
CALCULATED_COST_COLUMNS = (
    "calculated_input_cost_usd",
    "calculated_cache_creation_cost_usd",
    "calculated_cache_read_cost_usd",
    "calculated_output_cost_usd",
    "calculated_cost_usd",
)


@dataclass
class TokenStats:
    """保存 CLI 轨迹中真实上报的 token 用量。"""

    turns: int = 0
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    def add_usage(self, usage: dict[str, Any]) -> None:
        """累加一条去重后的模型 usage 记录。"""
        self.turns += 1
        for field_name in TOKEN_FIELDS:
            value = usage.get(field_name, 0)
            if isinstance(value, (int, float)):
                setattr(self, field_name, getattr(self, field_name) + int(value))

    def merge(self, other: "TokenStats") -> None:
        """合并另一份 token 统计。"""
        self.turns += other.turns
        for field_name in TOKEN_FIELDS:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))

    @property
    def reported_total_tokens(self) -> int:
        """返回输入、缓存和输出字段之和，不推断供应商账单口径。"""
        return sum(getattr(self, field_name) for field_name in TOKEN_FIELDS)

    def to_usage(self) -> dict[str, int]:
        """转换为通用价格策略可消费的 usage 字段。"""

        return {field_name: getattr(self, field_name) for field_name in TOKEN_FIELDS}


@dataclass
class RoleStats:
    """保存某类 Agent 的激活次数、活跃时长和 token。"""

    activations: int = 0
    duration_ms: int = 0
    tokens: TokenStats = field(default_factory=TokenStats)

    def merge(self, other: "RoleStats") -> None:
        """合并同角色统计。"""
        self.activations += other.activations
        self.duration_ms += other.duration_ms
        self.tokens.merge(other.tokens)


@dataclass
class RunStats:
    """保存一个实际 Run 的 Agent 花费快照。"""

    case_id: str
    run_id: str
    run_path: str
    status: str = "unknown"
    roles: dict[str, RoleStats] = field(
        default_factory=lambda: {role: RoleStats() for role in ROLES}
    )
    models: set[str] = field(default_factory=set)
    session_count: int = 0
    sessions_with_usage: int = 0
    judge_runs: int = 0
    reported_cost_usd: float = 0.0
    cost_covered_activations: int = 0

    def merge(self, other: "RunStats") -> None:
        """把另一个 Run 的统计并入当前对象。"""
        for role in ROLES:
            self.roles[role].merge(other.roles[role])
        self.models.update(other.models)
        self.session_count += other.session_count
        self.sessions_with_usage += other.sessions_with_usage
        self.judge_runs += other.judge_runs
        self.reported_cost_usd += other.reported_cost_usd
        self.cost_covered_activations += other.cost_covered_activations


def _case_id(path: Path) -> str | None:
    """从目录路径中提取 NatureBench case id。"""
    match = CASE_ID_PATTERN.search(str(path))
    return match.group(0) if match else None


def _safe_json(path: Path) -> dict[str, Any] | None:
    """读取 JSON 对象；运行中尚未完整落盘时返回空值。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _run_quality(run_dir: Path) -> tuple[int, int, int]:
    """给重复 staging 目录评分，优先保留证据更完整的一份。"""
    worker_count = len(_wrapper_meta_paths(run_dir))
    if not worker_count:
        worker_count = len(list((run_dir / "artifacts" / "worker_calls").glob("*.json")))
    session_count = 1 if _consolidated_trajectory(run_dir) else 0
    state = run_dir / "research_state.yaml"
    try:
        state_mtime = state.stat().st_mtime_ns
    except OSError:
        state_mtime = 0
    return worker_count, session_count, state_mtime


def discover_run_dirs(runs_root: Path) -> list[Path]:
    """发现顶层 Run 和其 reruns，并消除同名 staging 副本。"""
    candidates: list[Path] = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        if _case_id(run_dir):
            candidates.append(run_dir)
        reruns_dir = run_dir / "reruns"
        if reruns_dir.is_dir():
            candidates.extend(
                path for path in sorted(reruns_dir.iterdir()) if path.is_dir() and _case_id(path)
            )

    selected: dict[tuple[str, str], Path] = {}
    for run_dir in candidates:
        case_id = _case_id(run_dir)
        if not case_id:
            continue
        key = case_id, run_dir.name
        current = selected.get(key)
        if current is None or _run_quality(run_dir) > _run_quality(current):
            selected[key] = run_dir
    return sorted(selected.values(), key=lambda path: (_case_id(path) or "", path.name))


def _session_paths(run_dir: Path) -> list[Path]:
    """只扫描 Agent workspace，避免递归进入 benchmark 大数据目录。"""
    patterns = [
        "branches/*/logs/claude_home/.claude/projects/*/*.jsonl",
        "*workspaces/branches/*/logs/claude_home/.claude/projects/*/*.jsonl",
    ]
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(run_dir.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def _consolidated_trajectory(run_dir: Path) -> Path | None:
    """返回 Judge 输入中最新且最完整的合并轨迹。"""
    case_id = _case_id(run_dir)
    if not case_id:
        return None
    root = run_dir / "controller" / "naturebench_judge"
    candidates = list(root.glob(f"*/{case_id}/famou.jsonl")) if root.is_dir() else []
    if not candidates:
        return None

    def quality(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except OSError:
            return 0, 0
        return stat.st_size, stat.st_mtime_ns

    return max(candidates, key=quality)


def _wrapper_meta_paths(run_dir: Path) -> list[Path]:
    """发现轻量 wrapper 元数据，避免为统计时长读取大型 worker-call JSON。"""
    patterns = [
        "branches/*/logs/*.claude_wrapper_meta.json",
        "*workspaces/branches/*/logs/*.claude_wrapper_meta.json",
    ]
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(run_dir.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def _role_from_path(path: Path) -> str:
    """根据隔离 workspace 路径识别 Agent 角色。"""
    text = str(path)
    if "idea_judge" in text:
        return "idea_judge"
    if "idea_rank" in text or "ranking" in text:
        return "idea_rank"
    if "idea_agent_workspaces" in text:
        return "idea"
    if "/branches/actor_branch_" in text:
        return "implement"
    return "other"


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """递归遍历 JSON 中的对象，用于兼容不同版本 worker-call 结构。"""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _model_from_command(command: Any) -> str | None:
    """从 CLI 参数中读取模型名。"""
    if not isinstance(command, list):
        return None
    for index, item in enumerate(command[:-1]):
        if item == "--model" and isinstance(command[index + 1], str):
            return command[index + 1]
    return None


def _reported_cost(value: Any) -> float | None:
    """提取供应商明确上报的美元成本；没有字段时不估算。"""
    for item in _walk_dicts(value):
        for key in ("total_cost_usd", "cost_usd"):
            cost = item.get(key)
            if isinstance(cost, (int, float)):
                return float(cost)
    return None


def _stdout_reported_cost(call: dict[str, Any]) -> float | None:
    """从旧 wrapper stdout 回填每次 CLI 激活明确上报的费用。"""

    value = call.get("stdout_path")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    values = [float(match) for match in REPORTED_COST_PATTERN.findall(text)]
    return sum(values) if values else None


def _stdout_path_for_wrapper_meta(path: Path) -> Path:
    """从稳定文件布局直接定位 stdout，避免为费用回填读取 meta JSON。"""

    name = path.name.replace(
        ".claude_wrapper_meta.json",
        ".claude_stdout.txt",
    )
    return path.parent.parent / "outputs" / name


def _reported_cost_from_stdout_path(path: Path) -> float | None:
    """以正则读取供应商顶层费用字段；modelUsage 内不含同名字段。"""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    values = [float(match) for match in REPORTED_COST_PATTERN.findall(text)]
    return sum(values) if values else None


def _agent_call(document: dict[str, Any]) -> dict[str, Any] | None:
    """定位 worker-call 中真正执行 CLI Agent 的元数据。"""
    candidates: list[dict[str, Any]] = []
    meta = document.get("meta")
    if isinstance(meta, dict):
        candidates.append(meta)
    output = document.get("result", {}).get("output", {}) if isinstance(document.get("result"), dict) else {}
    if isinstance(output, dict) and isinstance(output.get("__agent_call__"), dict):
        candidates.append(output["__agent_call__"])
    for item in _walk_dicts(document):
        run = item.get("run")
        if (
            isinstance(run, dict)
            and isinstance(run.get("duration_ms"), (int, float))
            and isinstance(item.get("id"), str)
        ):
            candidates.append(item)
    return next(
        (
            item
            for item in candidates
            if isinstance(item.get("run"), dict)
            and isinstance(item["run"].get("duration_ms"), (int, float))
        ),
        None,
    )


def _normalize_role(role: Any, task: Any) -> str:
    """把历史命名映射到稳定角色集合。"""
    text = str(role or task or "").lower()
    if "judge" in text and "idea" in text:
        return "idea_judge"
    if "rank" in text:
        return "idea_rank"
    if "idea" in text:
        return "idea"
    if "implement" in text or "method" in text:
        return "implement"
    return "other"


def _collect_activations(
    run_dir: Path,
    run_stats: RunStats,
    seen_call_ids: set[str],
) -> None:
    """从 worker-call 证据统计 Agent 激活与进程活跃时长。"""
    wrapper_paths = _wrapper_meta_paths(run_dir)
    if wrapper_paths:
        for path in wrapper_paths:
            call = _safe_json(path)
            if not call or not isinstance(call.get("duration_ms"), (int, float)):
                continue
            call_id = path.name.split(".result.claude_wrapper_meta.json", 1)[0]
            if call_id in seen_call_ids:
                continue
            seen_call_ids.add(call_id)
            role = _role_from_path(path)
            run_stats.roles[role].activations += 1
            run_stats.roles[role].duration_ms += max(int(call["duration_ms"]), 0)
            model = _model_from_command(call.get("command"))
            if model:
                run_stats.models.add(model)
            cost = _reported_cost(call)
            if cost is None:
                cost = _stdout_reported_cost(call)
            if cost is not None:
                run_stats.reported_cost_usd += cost
                run_stats.cost_covered_activations += 1
        return

    # 极早期 Run 还没有 wrapper metadata，才回退到体积更大的 worker-call 证据。
    worker_dir = run_dir / "artifacts" / "worker_calls"
    for path in sorted(worker_dir.glob("*.json")):
        document = _safe_json(path)
        if not document:
            continue
        call = _agent_call(document)
        if not call:
            continue
        call_id = str(call.get("id") or document.get("id") or path.stem)
        if call_id in seen_call_ids:
            continue
        seen_call_ids.add(call_id)
        role = _normalize_role(call.get("role"), document.get("task"))
        duration_ms = int(call["run"].get("duration_ms", 0))
        run_stats.roles[role].activations += 1
        run_stats.roles[role].duration_ms += max(duration_ms, 0)
        model = _model_from_command(call.get("command")) or _model_from_command(
            call.get("run", {}).get("command")
        )
        if model:
            run_stats.models.add(model)
        cost = _reported_cost(call)
        if cost is None:
            cost = _stdout_reported_cost(call)
        if cost is not None:
            run_stats.reported_cost_usd += cost
            run_stats.cost_covered_activations += 1


def _event_role(event: dict[str, Any], default_role: str) -> str:
    """从合并轨迹事件的 cwd 还原 Idea/Implement/Ranking 角色。"""
    text = str(event.get("cwd") or "")
    if "idea_judge" in text:
        return "idea_judge"
    if "idea_rank" in text or "ranking" in text:
        return "idea_rank"
    if "idea_agent_workspaces" in text:
        return "idea"
    if "/branches/actor_branch_" in text:
        return "implement"
    return default_role


def _parse_session_usage(
    path: Path,
    case_id: str,
) -> tuple[set[str], list[tuple[tuple[Any, ...], str, dict[str, Any], str | None]]]:
    """解析单个 session；由线程池并发执行 CFS 读取。"""
    role = _role_from_path(path)
    session_key = path.stem
    sessions: set[str] = set()
    records: list[tuple[tuple[Any, ...], str, dict[str, Any], str | None]] = []
    local_seen: set[tuple[Any, ...]] = set()
    try:
        lines = path.open("r", encoding="utf-8")
    except OSError:
        return sessions, records
    with lines:
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            actual_session = str(event.get("sessionId") or session_key)
            # 同一响应的 thinking/tool 内容块会重复 usage；相同 usage 只计一次。
            usage_key = (
                case_id,
                actual_session,
                message.get("id") or event.get("uuid"),
                message.get("model"),
                *(int(usage.get(field_name, 0) or 0) for field_name in TOKEN_FIELDS),
            )
            if usage_key in local_seen:
                continue
            local_seen.add(usage_key)
            model = message.get("model")
            sessions.add(actual_session)
            records.append(
                (
                    usage_key,
                    _event_role(event, role),
                    usage,
                    model if isinstance(model, str) else None,
                )
            )
    return sessions, records


def _collect_tokens(
    run_dir: Path,
    run_stats: RunStats,
    seen_usage_records: set[tuple[Any, ...]],
    seen_session_paths: set[tuple[str, str]],
) -> None:
    """从 Claude CLI 原生 session 轨迹并发统计逐轮 token usage。"""
    consolidated = _consolidated_trajectory(run_dir)
    pending_paths = [consolidated] if consolidated else _session_paths(run_dir)
    if not pending_paths:
        return
    workers = min(12, len(pending_paths))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        parsed_sessions = executor.map(
            lambda path: _parse_session_usage(path, run_stats.case_id), pending_paths
        )
        for sessions, records in parsed_sessions:
            new_sessions = {
                session
                for session in sessions
                if (run_stats.case_id, session) not in seen_session_paths
            }
            seen_session_paths.update((run_stats.case_id, session) for session in new_sessions)
            run_stats.session_count += len(new_sessions)
            sessions_with_new_usage: set[str] = set()
            for usage_key, role, usage, model in records:
                if usage_key in seen_usage_records:
                    continue
                seen_usage_records.add(usage_key)
                run_stats.roles[role].tokens.add_usage(usage)
                sessions_with_new_usage.add(str(usage_key[1]))
                if model and model != "<synthetic>":
                    run_stats.models.add(model)
            run_stats.sessions_with_usage += len(sessions_with_new_usage)


def _read_status(run_dir: Path) -> str:
    """读取运行状态；ResearchState 当前以 JSON 语法写入 yaml 文件。"""
    state = _safe_json(run_dir / "research_state.yaml")
    if not state:
        return "unknown"
    research_state = state.get("research_state")
    if isinstance(research_state, dict) and isinstance(research_state.get("status"), str):
        return research_state["status"]
    return "unknown"


def _count_judge_runs(run_dir: Path) -> int:
    """统计实际留下 verdict 的 Validity Judge 调用目录。"""
    root = run_dir / "controller" / "naturebench_judge"
    if not root.is_dir():
        return 0
    return sum(1 for path in root.glob("*/judge_verdict.json") if path.is_file())


def collect_run_stats(runs_root: Path) -> list[RunStats]:
    """并发扫描规范化后的 Run，并在各 Run 内去重调用和 usage。"""
    def collect_one(run_dir: Path) -> RunStats | None:
        case_id = _case_id(run_dir)
        if not case_id:
            return None
        stats = RunStats(
            case_id=case_id,
            run_id=run_dir.name,
            run_path=str(run_dir.resolve()),
            status=_read_status(run_dir),
            judge_runs=_count_judge_runs(run_dir),
        )
        _collect_activations(run_dir, stats, set())
        _collect_tokens(run_dir, stats, set(), set())
        if (
            sum(item.activations for item in stats.roles.values())
            or stats.session_count
            or stats.judge_runs
        ):
            return stats
        return None

    run_dirs = discover_run_dirs(runs_root)
    with ThreadPoolExecutor(max_workers=min(12, len(run_dirs) or 1)) as executor:
        collected = executor.map(collect_one, run_dirs)
        results = [stats for stats in collected if stats is not None]
    return sorted(results, key=lambda stats: (stats.case_id, stats.run_id))


def _official_results(path: Path | None) -> dict[str, dict[str, str]]:
    """读取官方提交 CSV，用于补齐 90 个 case 和当前成绩。"""
    if path is None:
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def _aggregate_cases(
    run_stats: list[RunStats],
    official: dict[str, dict[str, str]],
) -> dict[str, RunStats]:
    """把多个历史 Run 合并为每个 case 的累计实际花费。"""
    cases: dict[str, RunStats] = {}
    for case_id in sorted(set(official) | {item.case_id for item in run_stats}):
        cases[case_id] = RunStats(case_id=case_id, run_id="ALL", run_path="")
    for stats in run_stats:
        cases[stats.case_id].merge(stats)
    return cases


def _role_totals(stats: RunStats) -> tuple[int, int, TokenStats]:
    """返回全部角色的调用数、活跃时长和 token 汇总。"""
    activations = sum(item.activations for item in stats.roles.values())
    duration_ms = sum(item.duration_ms for item in stats.roles.values())
    tokens = TokenStats()
    for item in stats.roles.values():
        tokens.merge(item.tokens)
    return activations, duration_ms, tokens


def _calculated_cost_columns(
    tokens: TokenStats,
    pricing: TokenPricingPolicy | None,
) -> dict[str, str]:
    """生成配置价格的美元分项；没有策略时保留空列。"""

    columns = {name: "" for name in CALCULATED_COST_COLUMNS}
    if pricing is None:
        return columns
    if pricing.currency != "USD":
        raise ValueError("NatureBench 历史费用表当前只支持 USD 价格策略")
    calculated = pricing.calculate(tokens.to_usage())
    breakdown = calculated["breakdown"]
    columns.update(
        {
            "calculated_input_cost_usd": f"{breakdown['input']:.6f}",
            "calculated_cache_creation_cost_usd": (
                f"{breakdown['cache_creation']:.6f}"
            ),
            "calculated_cache_read_cost_usd": f"{breakdown['cache_read']:.6f}",
            "calculated_output_cost_usd": f"{breakdown['output']:.6f}",
            "calculated_cost_usd": f"{calculated['amount']:.6f}",
        }
    )
    return columns


def _base_row(
    stats: RunStats,
    pricing: TokenPricingPolicy | None = None,
) -> dict[str, Any]:
    """生成 case/run 两张表共用的统计列。"""
    activations, duration_ms, tokens = _role_totals(stats)
    row: dict[str, Any] = {
        "agent_activations": activations,
        "idea_activations": stats.roles["idea"].activations,
        "implement_activations": stats.roles["implement"].activations,
        "idea_rank_activations": stats.roles["idea_rank"].activations,
        "idea_judge_activations": stats.roles["idea_judge"].activations,
        "other_activations": stats.roles["other"].activations,
        "agent_active_hours": f"{duration_ms / 3_600_000:.4f}",
        "idea_active_hours": f"{stats.roles['idea'].duration_ms / 3_600_000:.4f}",
        "implement_active_hours": f"{stats.roles['implement'].duration_ms / 3_600_000:.4f}",
        "idea_rank_active_hours": f"{stats.roles['idea_rank'].duration_ms / 3_600_000:.4f}",
        "llm_turns": tokens.turns,
        "input_tokens": tokens.input_tokens,
        "cache_creation_input_tokens": tokens.cache_creation_input_tokens,
        "cache_read_input_tokens": tokens.cache_read_input_tokens,
        "output_tokens": tokens.output_tokens,
        "reported_total_tokens": tokens.reported_total_tokens,
        **_calculated_cost_columns(tokens, pricing),
        "reported_cost_usd": (
            f"{stats.reported_cost_usd:.6f}" if stats.cost_covered_activations else ""
        ),
        "cost_covered_activations": stats.cost_covered_activations,
        "session_count": stats.session_count,
        "sessions_with_usage": stats.sessions_with_usage,
        "validity_judge_runs": stats.judge_runs,
        "models": ";".join(sorted(stats.models)),
    }
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """以稳定列顺序写出 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("没有可写出的统计记录")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_reports(
    runs_root: Path,
    official_results: Path | None,
    case_output: Path,
    run_output: Path,
    summary_output: Path,
    pricing: TokenPricingPolicy | None = None,
) -> dict[str, Any]:
    """生成 case 汇总、Run 明细和机器可读总览。"""
    run_stats = collect_run_stats(runs_root)
    official = _official_results(official_results)
    cases = _aggregate_cases(run_stats, official)
    run_count_by_case: dict[str, int] = defaultdict(int)
    running_by_case: dict[str, bool] = defaultdict(bool)
    for stats in run_stats:
        run_count_by_case[stats.case_id] += 1
        running_by_case[stats.case_id] |= stats.status in {"running", "active"}

    case_rows: list[dict[str, Any]] = []
    for case_id, stats in sorted(cases.items()):
        official_row = official.get(case_id, {})
        row = {
            "case_id": case_id,
            "final_status": official_row.get("final_status", ""),
            "best_score": official_row.get("best_score", ""),
            "judge_verdict": official_row.get("judge_verdict", ""),
            "tracked_run_count": run_count_by_case[case_id],
            "has_running_run": str(running_by_case[case_id]).lower(),
            **_base_row(stats, pricing),
        }
        case_rows.append(row)

    run_rows = [
        {
            "case_id": stats.case_id,
            "run_id": stats.run_id,
            "run_status": stats.status,
            "run_path": stats.run_path,
            **_base_row(stats, pricing),
        }
        for stats in run_stats
    ]
    _write_csv(case_output, case_rows)
    _write_csv(run_output, run_rows)

    total = RunStats(case_id="TOTAL", run_id="ALL", run_path="")
    for stats in cases.values():
        total.merge(stats)
    activations, duration_ms, tokens = _role_totals(total)
    calculated = pricing.calculate(tokens.to_usage()) if pricing else None
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "all deduplicated NatureBench runs present under runs_root",
        "case_count": len(case_rows),
        "run_count": len(run_rows),
        "agent_activations": activations,
        "agent_active_hours": duration_ms / 3_600_000,
        "llm_turns": tokens.turns,
        "input_tokens": tokens.input_tokens,
        "cache_creation_input_tokens": tokens.cache_creation_input_tokens,
        "cache_read_input_tokens": tokens.cache_read_input_tokens,
        "output_tokens": tokens.output_tokens,
        "reported_total_tokens": tokens.reported_total_tokens,
        "calculated_cost_usd": calculated["amount"] if calculated else None,
        "calculated_cost_breakdown_usd": (
            calculated["breakdown"] if calculated else None
        ),
        "pricing_policy": pricing.to_dict() if pricing else None,
        "pricing_source": pricing.source if pricing else None,
        "pricing_effective_at": pricing.effective_at if pricing else None,
        "reported_cost_usd": (
            total.reported_cost_usd if total.cost_covered_activations else None
        ),
        "cost_covered_activations": total.cost_covered_activations,
        "validity_judge_runs": total.judge_runs,
        "methodology": {
            "duration": "sum of CLI Agent activation duration_ms; concurrent durations overlap",
            "tokens": "deduplicated native Claude CLI assistant usage records",
            "usage_dedup": "case + session + message id + model + exact usage tuple",
            "cost": (
                "CLI-reported total_cost_usd; compatible backends may use a "
                "canonical-model USD equivalent; missing values are not estimated"
            ),
            "calculated_cost": (
                "four token fields multiplied independently by the explicitly "
                "configured per-million-token prices; this does not overwrite "
                "CLI-reported cost"
                if pricing
                else "not calculated because no explicit pricing policy was supplied"
            ),
            "judge": "Judge invocation count only; Judge token/cost is not present in current artifacts",
        },
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def backfill_reported_costs(
    case_output: Path,
    run_output: Path,
    summary_output: Path,
) -> dict[str, Any]:
    """不重扫大型 Session，仅从 wrapper stdout 回填旧报告费用。"""

    with run_output.open("r", encoding="utf-8", newline="") as handle:
        run_rows = list(csv.DictReader(handle))
    with case_output.open("r", encoding="utf-8", newline="") as handle:
        case_rows = list(csv.DictReader(handle))

    wrapper_jobs: list[tuple[int, Path]] = []
    for index, row in enumerate(run_rows):
        wrapper_jobs.extend(
            (index, _stdout_path_for_wrapper_meta(path))
            for path in _wrapper_meta_paths(Path(row["run_path"]))
        )
    costs = [(0.0, 0) for _ in run_rows]
    with ThreadPoolExecutor(max_workers=min(64, len(wrapper_jobs) or 1)) as executor:
        values = executor.map(
            _reported_cost_from_stdout_path,
            (path for _, path in wrapper_jobs),
        )
        mutable = [[0.0, 0] for _ in run_rows]
        for (index, _), cost in zip(wrapper_jobs, values):
            if cost is not None:
                mutable[index][0] += cost
                mutable[index][1] += 1
    costs = [(float(cost), int(covered)) for cost, covered in mutable]
    case_costs: dict[str, float] = defaultdict(float)
    case_coverage: dict[str, int] = defaultdict(int)
    for row, (cost, covered) in zip(run_rows, costs):
        row["reported_cost_usd"] = f"{cost:.6f}" if covered else ""
        row["cost_covered_activations"] = str(covered)
        row["models"] = ";".join(
            model for model in row.get("models", "").split(";") if model != "<synthetic>"
        )
        case_costs[row["case_id"]] += cost
        case_coverage[row["case_id"]] += covered
    for row in case_rows:
        case_id = row["case_id"]
        covered = case_coverage[case_id]
        row["reported_cost_usd"] = (
            f"{case_costs[case_id]:.6f}" if covered else ""
        )
        row["cost_covered_activations"] = str(covered)
        row["models"] = ";".join(
            model for model in row.get("models", "").split(";") if model != "<synthetic>"
        )
    _write_csv(case_output, case_rows)
    _write_csv(run_output, run_rows)

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    total_cost = sum(cost for cost, _ in costs)
    total_coverage = sum(covered for _, covered in costs)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["reported_cost_usd"] = total_cost if total_coverage else None
    summary["cost_covered_activations"] = total_coverage
    summary.setdefault("methodology", {})["cost"] = (
        "CLI-reported total_cost_usd from each wrapper stdout; compatible backends "
        "may use a canonical-model USD equivalent; missing values are not estimated"
    )
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _token_stats_from_row(row: dict[str, str]) -> TokenStats:
    """从已有 CSV 恢复四类 Token，供价格变更后快速重算。"""

    return TokenStats(
        **{
            field_name: int(row.get(field_name) or 0)
            for field_name in TOKEN_FIELDS
        }
    )


def reprice_reports(
    case_output: Path,
    run_output: Path,
    summary_output: Path,
    pricing: TokenPricingPolicy,
) -> dict[str, Any]:
    """复用已有 Token 表按新价格重算，不重新扫描大型 Session。"""

    with run_output.open("r", encoding="utf-8", newline="") as handle:
        run_rows = list(csv.DictReader(handle))
    with case_output.open("r", encoding="utf-8", newline="") as handle:
        case_rows = list(csv.DictReader(handle))
    def replace_columns(row: dict[str, str]) -> dict[str, str]:
        """把重算列稳定插入 Token 列后，避免多次重算改变 CSV schema。"""

        calculated = _calculated_cost_columns(_token_stats_from_row(row), pricing)
        updated: dict[str, str] = {}
        for name, value in row.items():
            if name in CALCULATED_COST_COLUMNS:
                continue
            updated[name] = value
            if name == "reported_total_tokens":
                updated.update(calculated)
        return updated

    case_rows = [replace_columns(row) for row in case_rows]
    run_rows = [replace_columns(row) for row in run_rows]
    _write_csv(case_output, case_rows)
    _write_csv(run_output, run_rows)

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    total_tokens = TokenStats(
        **{
            field_name: int(summary.get(field_name) or 0)
            for field_name in TOKEN_FIELDS
        }
    )
    calculated = pricing.calculate(total_tokens.to_usage())
    summary.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calculated_cost_usd": calculated["amount"],
            "calculated_cost_breakdown_usd": calculated["breakdown"],
            "pricing_policy": pricing.to_dict(),
            "pricing_source": pricing.source,
            "pricing_effective_at": pricing.effective_at,
        }
    )
    summary.setdefault("methodology", {})["calculated_cost"] = (
        "four token fields multiplied independently by the explicitly configured "
        "per-million-token prices; this does not overwrite CLI-reported cost"
    )
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _pricing_from_args(args: argparse.Namespace) -> TokenPricingPolicy | None:
    """把可选 CLI 单价转换为统一价格策略，并拒绝不完整配置。"""

    values = (
        args.input_price_per_million,
        args.cache_creation_price_per_million,
        args.cache_read_price_per_million,
        args.output_price_per_million,
    )
    if not any(value is not None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("必须同时提供 input/cache creation/cache read/output 四类价格")
    return TokenPricingPolicy.from_mapping(
        {
            "currency": args.pricing_currency,
            "per_million_tokens": {
                "input": args.input_price_per_million,
                "cache_creation": args.cache_creation_price_per_million,
                "cache_read": args.cache_read_price_per_million,
                "output": args.output_price_per_million,
            },
            "source": args.pricing_source,
            "effective_at": args.pricing_effective_at,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True, help="NatureBench Run 根目录")
    parser.add_argument("--official-results", type=Path, help="官方提交 results.csv")
    parser.add_argument("--case-output", type=Path, required=True, help="按 case 汇总 CSV")
    parser.add_argument("--run-output", type=Path, required=True, help="按 Run 明细 CSV")
    parser.add_argument("--summary-output", type=Path, required=True, help="总览 JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--cost-only",
        action="store_true",
        help="复用现有 Token 报告，仅从 wrapper stdout 回填供应商费用",
    )
    mode.add_argument(
        "--reprice-only",
        action="store_true",
        help="复用现有 Token 报告，仅按显式价格重算费用",
    )
    parser.add_argument("--pricing-currency", default="USD")
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--cache-creation-price-per-million", type=float)
    parser.add_argument("--cache-read-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--pricing-source")
    parser.add_argument("--pricing-effective-at")
    return parser


def main() -> int:
    """执行 Agent 花费统计。"""
    args = build_parser().parse_args()
    pricing = _pricing_from_args(args)
    if args.reprice_only:
        if pricing is None:
            raise ValueError("--reprice-only 必须提供完整价格策略")
        summary = reprice_reports(
            args.case_output,
            args.run_output,
            args.summary_output,
            pricing,
        )
    elif args.cost_only:
        summary = backfill_reported_costs(
            args.case_output,
            args.run_output,
            args.summary_output,
        )
    else:
        summary = build_reports(
            args.runs_root,
            args.official_results,
            args.case_output,
            args.run_output,
            args.summary_output,
            pricing,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
