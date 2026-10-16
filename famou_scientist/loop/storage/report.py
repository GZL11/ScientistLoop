"""端到端运行的证据包和报告导出逻辑。"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from ..runtime.master_bridge import MasterBridge
from ..domain.status import LoopStatus
from ..storage.queues import QueueSet
from ..storage.state import ResearchState
from ..utils import atomic_write_json, now_ms, read_jsonl, sha256_file
from ..observability import ObservabilityStore


def _read_json_file(path: Path) -> dict[str, Any] | None:
    """安全读取结构化数据文件。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def artifact_index(workspace: str | Path) -> list[dict[str, Any]]:
    """读取证据索引记录。"""
    ws = Path(workspace)
    return read_jsonl(ws / "artifacts" / "artifact_index.jsonl")


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    """按指定字段统计记录数量。"""
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _recent_decisions(workspace: Path, *, limit: int = 8) -> list[dict[str, Any]]:
    """读取最近的决策记录。"""
    rows = read_jsonl(workspace / "artifacts" / "decision_log.jsonl")
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        out.append(
            {
                "id": row.get("id"),
                "decision": row.get("decision"),
                "branch_id": row.get("branch_id"),
                "idea_id": row.get("idea_id"),
                "reasons": row.get("reasons") or [],
                "created_at": row.get("created_at"),
            }
        )
    return out


def generate_status_overview(workspace: str | Path) -> dict[str, Any]:
    """生成面向用户和主控的状态概览。"""

    ws = Path(workspace)
    state = ResearchState(ws).load()
    rs = state.get("research_state", {})
    queues = QueueSet(ws).summary()
    artifacts = artifact_index(ws)
    branches = rs.get("branches") if isinstance(rs.get("branches"), list) else []
    budget = rs.get("evaluator_budget") if isinstance(rs.get("evaluator_budget"), dict) else {}
    leaderboard = rs.get("leaderboard") if isinstance(rs.get("leaderboard"), dict) else {}
    runtime_limits = rs.get("runtime_limits") if isinstance(rs.get("runtime_limits"), dict) else {}

    queued_total = sum(
        int(summary.get(LoopStatus.Queue.QUEUED.value, 0) or 0)
        for summary in queues.values()
    )
    running_total = sum(
        int(summary.get(LoopStatus.Queue.RUNNING.value, 0) or 0)
        for summary in queues.values()
    )
    failed_total = sum(
        int(summary.get(LoopStatus.Queue.FAILED.value, 0) or 0)
        for summary in queues.values()
    )
    finished_total = sum(
        int(summary.get(LoopStatus.Queue.FINISHED.value, 0) or 0)
        for summary in queues.values()
    )

    return {
        "workspace": str(ws),
        "goal_id": rs.get("goal_id"),
        "status": rs.get("status"),
        "termination_reason": rs.get("termination_reason"),
        "current_phase": rs.get("current_phase"),
        "last_heartbeat_at": rs.get("last_heartbeat_at"),
        "goal": rs.get("goal") or {},
        "runtime_limits": runtime_limits,
        "evaluator_submissions": {
            "used": budget.get("used_submissions", 0),
            "max": budget.get("max_submissions", 0),
        },
        "leaderboard": leaderboard,
        "queues": queues,
        "queue_totals": {
            LoopStatus.Queue.QUEUED.value: queued_total,
            LoopStatus.Queue.RUNNING.value: running_total,
            LoopStatus.Queue.FINISHED.value: finished_total,
            LoopStatus.Queue.FAILED.value: failed_total,
        },
        "branches": {
            "total": len(branches),
            "by_status": _count_by(branches, "status"),
            "items": branches,
        },
        "artifacts": {
            "total": len(artifacts),
            "by_type": _count_by(artifacts, "type"),
            "index": "artifacts/artifact_index.jsonl",
            "decision_log": "artifacts/decision_log.jsonl",
        },
        "recent_decisions": _recent_decisions(ws),
    }


def render_status_overview(overview: dict[str, Any]) -> str:
    """将状态概览渲染为简洁文本。"""

    submissions = overview.get("evaluator_submissions") or {}
    leaderboard = overview.get("leaderboard") or {}
    queue_totals = overview.get("queue_totals") or {}
    branches = overview.get("branches") or {}
    lines = [
        f"goal_id: {overview.get('goal_id')}",
        f"status: {overview.get('status')}",
        f"phase: {overview.get('current_phase')}",
        f"workspace: {overview.get('workspace')}",
        f"last_heartbeat_at: {overview.get('last_heartbeat_at')}",
        f"evaluator_submissions: {submissions.get('used', 0)}/{submissions.get('max', 0)}",
        (
            "best: "
            f"{leaderboard.get('metric')}={leaderboard.get('best_value')} "
            f"branch={leaderboard.get('branch_id')} source={leaderboard.get('source', '')}"
        ),
        f"runtime_limits: {overview.get('runtime_limits') or {}}",
        (
            "queue_totals: "
            f"queued={queue_totals.get('queued', 0)} "
            f"running={queue_totals.get('running', 0)} "
            f"finished={queue_totals.get('finished', 0)} "
            f"failed={queue_totals.get('failed', 0)}"
        ),
        "queues:",
    ]
    for name, summary in (overview.get("queues") or {}).items():
        lines.append(f"  {name}: {summary}")
    lines.append(
        f"branches: total={branches.get('total', 0)} by_status={branches.get('by_status', {})}"
    )
    artifacts = overview.get("artifacts") or {}
    lines.append(
        f"artifacts: total={artifacts.get('total', 0)} by_type={artifacts.get('by_type', {})}"
    )
    recent = overview.get("recent_decisions") or []
    if recent:
        lines.append("recent_decisions:")
        for decision in recent:
            subject = decision.get("branch_id") or decision.get("idea_id") or ""
            reasons = decision.get("reasons") or []
            reason = reasons[0] if reasons else ""
            lines.append(f"  - {decision.get('decision')} {subject}: {reason}")
    return "\n".join(lines) + "\n"


def generate_claim_evidence_map(workspace: str | Path) -> dict[str, Any]:
    """根据分析产物生成主张与证据映射。"""
    ws = Path(workspace)
    claims: list[dict[str, Any]] = []
    idx = artifact_index(ws)
    counter = 1
    for rec in idx:
        if rec.get("type") != "deep_analysis":
            continue
        path = ws / str(rec.get("path", ""))
        data = _read_json_file(path) or {}
        limitations = data.get("limitations") if isinstance(data.get("limitations"), list) else []
        for claim in data.get("claims") or []:
            claims.append({
                "claim_id": f"C{counter}",
                "claim": str(claim),
                "source_artifact": rec.get("id"),
                "evidence_refs": list(dict.fromkeys((rec.get("input_refs") or []) + [rec.get("id")])) ,
                "limitations": limitations,
            })
            counter += 1
    return {"generated_at": now_ms(), "claims": claims}


def generate_final_report(workspace: str | Path, *, claim_map: dict[str, Any] | None = None) -> str:
    """生成最终研究报告。"""
    ws = Path(workspace)
    state = ResearchState(ws).load()
    rs = state.get("research_state", {})
    goal = rs.get("goal", {})
    queue_summary = QueueSet(ws).summary()
    claim_map = claim_map or generate_claim_evidence_map(ws)
    budget = rs.get("evaluator_budget", {})
    leaderboard = rs.get("leaderboard", {})
    lines = [
        f"# Loop Final Report: {rs.get('goal_id', 'unknown')}",
        "",
        "## Summary",
        f"- Status: `{rs.get('status', 'unknown')}`",
        f"- Termination reason: `{rs.get('termination_reason', '')}`",
        f"- Current phase: `{rs.get('current_phase', '')}`",
        f"- Last heartbeat: `{rs.get('last_heartbeat_at', '')}`",
        f"- Goal: {goal.get('name', '')}",
        f"- Domain: {goal.get('domain', '')}",
        f"- Evaluator submissions: {budget.get('used_submissions', 0)}/{budget.get('max_submissions', 0)}",
        f"- Runtime limits: {rs.get('runtime_limits', {})}",
        f"- Best score: {leaderboard.get('metric')}={leaderboard.get('best_value')} "
        f"(branch={leaderboard.get('branch_id')}, source={leaderboard.get('source', '')})",
        "",
        "## Objective Brief",
        str(goal.get("objective_brief", {}).get("primary_goal", "")),
        "",
        "## Queue Summary",
    ]
    for name, summary in queue_summary.items():
        lines.append(f"- {name}: {summary}")
    lines.extend(["", "## Branches"])
    branches = rs.get("branches") or []
    if not branches:
        lines.append("- No branches recorded.")
    else:
        for branch in branches:
            lines.append(f"- `{branch.get('branch_id')}`: status={branch.get('status')} idea={branch.get('idea_id')}")
    lines.extend(["", "## Claims and Evidence"])
    if not claim_map.get("claims"):
        lines.append("- No paper-level claims generated yet.")
    else:
        for claim in claim_map["claims"]:
            lines.append(f"- **{claim['claim_id']}**: {claim['claim']}")
            lines.append(f"  - evidence_refs: {claim.get('evidence_refs', [])}")
            if claim.get("limitations"):
                lines.append(f"  - limitations: {claim['limitations']}")
    lines.extend([
        "",
        "## Reproducibility Notes",
        "- See `manifest.json` for exported evidence files and checksums.",
        "- See `artifact_index.jsonl` and `decision_log.jsonl` for the full evidence trail.",
    ])
    return "\n".join(lines) + "\n"


def export_evidence_bundle(workspace: str | Path, *, output: str | Path | None = None, max_file_bytes: int = 5_000_000) -> Path:
    """导出证据包。"""
    ws = Path(workspace)
    bundle_dir = Path(output) if output else ws / "artifacts" / "evidence_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    state = ResearchState(ws).load()
    queue_summary = QueueSet(ws).summary()
    status_summary = MasterBridge(ws).render_status_summary(state, queue_summary)
    claim_map = generate_claim_evidence_map(ws)
    final_report = generate_final_report(ws, claim_map=claim_map)

    files: list[dict[str, Any]] = []

    def copy_rel(rel: str, *, required: bool = False) -> None:
        """完成当前处理流程。"""
        src = ws / rel
        if not src.exists():
            if required:
                files.append({"source": rel, "missing": True})
            return
        dst = bundle_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file() and src.stat().st_size <= max_file_bytes:
            shutil.copyfile(src, dst)
            files.append({"source": rel, "path": str(dst.relative_to(bundle_dir)), "sha256": sha256_file(dst), "bytes": dst.stat().st_size})
        else:
            files.append({"source": rel, "skipped": True, "reason": "too_large_or_not_file"})

    # 核心状态与日志。
    observability = ObservabilityStore(ws)
    if observability.usage_path.is_file():
        observability.write_summary()
    copy_rel("research_state.yaml", required=True)
    copy_rel("status_summary.md")
    copy_rel("queues/queue_events.jsonl")
    copy_rel("artifacts/artifact_index.jsonl")
    copy_rel("artifacts/decision_log.jsonl")
    copy_rel("artifacts/agent_usage.jsonl")
    copy_rel("artifacts/agent_trajectory.jsonl")
    copy_rel("controller/agent_usage_summary.json")

    # 复制索引引用的证据产物，并按第一版大小上限进行约束。
    for rec in artifact_index(ws):
        rel = rec.get("path")
        if isinstance(rel, str):
            copy_rel(rel)

    atomic_write_json(bundle_dir / "queue_summary.json", queue_summary)
    (bundle_dir / "status_summary.md").write_text(status_summary, encoding="utf-8")
    atomic_write_json(bundle_dir / "claim_evidence_map.json", claim_map)
    (bundle_dir / "final_report.md").write_text(final_report, encoding="utf-8")

    for rel in ["queue_summary.json", "claim_evidence_map.json", "final_report.md", "status_summary.md"]:
        path = bundle_dir / rel
        files.append({"source": f"generated:{rel}", "path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size})

    manifest = {
        "generated_at": now_ms(),
        "goal_id": state.get("research_state", {}).get("goal_id"),
        "workspace": str(ws),
        "files": files,
    }
    atomic_write_json(bundle_dir / "manifest.json", manifest)

    # 清单写入后再创建归档，保证证据包自包含。
    zip_path = bundle_dir / "evidence_bundle.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in bundle_dir.rglob("*"):
            if path == zip_path or not path.is_file():
                continue
            zf.write(path, path.relative_to(bundle_dir))
    return bundle_dir
