"""
runners/ui/server.py — Trace Viewer & Experiment Dashboard

轻量级只读 server，扫描 results/ 目录，提供：
  - 实验列表（含评分摘要）
  - 实验对比（score matrix + token/turn 统计）
  - Trace 查看（统一 schema，turn-by-turn）

启动：
    python -m runners.ui.server
    # 打开 http://localhost:8765
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..bench_config import RESULTS_DIR
from ..defaults import RUNNER_CHOICES, MODEL_ALIASES

# ── 路径 ─────────────────────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"
_RUNNERS_DIR = Path(__file__).parent.parent

# ── app ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Famou Bench Viewer")

from .chat_api import router as chat_router
app.include_router(chat_router)

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/api/options")
async def get_options():
    """返回前端下拉框选项：runners / prompt_variants / skill_sets / models。"""
    variants_dir = _RUNNERS_DIR / "prompt_variants"
    skills_dir = _RUNNERS_DIR / "skill_sets"

    variants = sorted(d.name for d in variants_dir.iterdir() if d.is_dir()) if variants_dir.exists() else ["default"]
    skills = sorted(d.name for d in skills_dir.iterdir() if d.is_dir()) if skills_dir.exists() else ["default"]
    if "none" not in skills:
        skills.append("none")
    models = list(MODEL_ALIASES.keys())

    return {
        "runners": RUNNER_CHOICES,
        "prompt_variants": variants,
        "skill_sets": skills,
        "models": models,
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = _STATIC_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    html_path = _STATIC_DIR / "chat.html"
    if not html_path.exists():
        return HTMLResponse("<h1>chat.html not found</h1>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ── /api/experiments — 实验列表 ──────────────────────────────────────────────

@app.get("/api/experiments")
async def list_experiments():
    """扫描 results/ 下所有 batch 目录，返回实验列表（含评分摘要）。"""
    if not RESULTS_DIR.exists():
        return []

    experiments = []
    for batch_dir in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if not batch_dir.is_dir() or batch_dir.name.startswith("."):
            continue

        meta = _load_meta(batch_dir)

        # 轻量扫描：只读目录名，不读 result.json（避免大量文件 I/O）
        cases = [
            d.name for d in batch_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

        experiments.append({
            "id": batch_dir.name,
            "runner": meta.get("runner", "?"),
            "prompt_variant": meta.get("prompt_variant", "?"),
            "skill_set": meta.get("skill_set", "default"),
            "submitted_at": meta.get("submitted_at", ""),
            "status": meta.get("status", "unknown"),
            "case_count": len(cases),
            "avg_score": None,  # 点击展开时通过 /results 接口加载
            "cases": cases,
        })

    return experiments


# ── /api/experiments/{id}/results — 单个实验的全部 case 结果 ─────────────────

@app.get("/api/experiments/{experiment_id}/results")
async def get_experiment_results(experiment_id: str):
    batch_dir = RESULTS_DIR / experiment_id
    if not batch_dir.exists():
        raise HTTPException(404, f"Experiment not found: {experiment_id}")

    results = _collect_case_results(batch_dir)
    meta = _load_meta(batch_dir)

    # 加载每个 case 的 trace 统计
    for r in results:
        workspace = Path(r["workspace"])
        trace_stats = _collect_trace_stats(workspace)
        r["trace_stats"] = trace_stats

    return {"meta": meta, "results": results}


# ── /api/experiments/{id}/{case}/trace — Trace 数据 ──────────────────────────

@app.get("/api/experiments/{experiment_id}/{case}/trace")
async def get_trace(experiment_id: str, case: str, run_idx: int = 0):
    batch_dir = RESULTS_DIR / experiment_id
    case_dir = batch_dir / case
    if not case_dir.exists():
        raise HTTPException(404, f"Case not found: {case}")

    workspace = case_dir / f"run_{run_idx:02d}" if run_idx > 0 else case_dir
    trace_dir = workspace / ".eval" / "trace"
    if not trace_dir.exists():
        raise HTTPException(404, f"Trace not found: {trace_dir}")

    sessions = []
    for f in sorted(trace_dir.glob("*.json")):
        try:
            sessions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue

    # root session 在前
    sessions.sort(key=lambda s: (
        s.get("session", {}).get("parent_id") is not None,
        s.get("session", {}).get("started_at") or "",
    ))

    return {"sessions": sessions}


# ── /api/compare — 多实验对比 ────────────────────────────────────────────────

@app.get("/api/compare")
async def compare(ids: str):
    """对比多个实验，返回 score matrix + token/turn 统计。"""
    id_list = [r.strip() for r in ids.split(",") if r.strip()]
    if not id_list:
        raise HTTPException(400, "ids is required")

    all_cases: set[str] = set()
    run_metas: list[dict] = []
    run_scores: dict[str, dict[str, float | None]] = {}
    run_stats: dict[str, dict[str, dict]] = {}  # id → case → stats

    for exp_id in id_list:
        batch_dir = RESULTS_DIR / exp_id
        meta = _load_meta(batch_dir)
        run_metas.append({
            "id": exp_id,
            "runner": meta.get("runner", "?"),
            "variant": meta.get("prompt_variant", "?"),
            "skill_set": meta.get("skill_set", "default"),
        })

        scores: dict[str, float | None] = {}
        stats: dict[str, dict] = {}
        if batch_dir.exists():
            for case_dir in sorted(batch_dir.iterdir()):
                if not case_dir.is_dir() or case_dir.name.startswith("."):
                    continue
                case_name = case_dir.name

                # Score
                result_path = case_dir / ".eval" / "result.json"
                if result_path.exists():
                    try:
                        r = json.loads(result_path.read_text(encoding="utf-8"))
                        scores[case_name] = r.get("overall_score")
                        all_cases.add(case_name)
                    except Exception:
                        pass

                # Trace stats
                trace_stats = _collect_trace_stats(case_dir)
                if trace_stats:
                    stats[case_name] = trace_stats

        run_scores[exp_id] = scores
        run_stats[exp_id] = stats

    cases = sorted(all_cases)
    matrix = {
        c: [
            {
                "score": run_scores[eid].get(c),
                "stats": run_stats[eid].get(c),
            }
            for eid in id_list
        ]
        for c in cases
    }

    return {"cases": cases, "runs": run_metas, "matrix": matrix}


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_meta(batch_dir: Path) -> dict:
    meta_path = batch_dir / ".meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _collect_case_results(batch_dir: Path) -> list[dict]:
    results = []
    for case_dir in sorted(batch_dir.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("."):
            continue
        run_dirs = sorted(case_dir.glob("run_*")) or [case_dir]
        for rd in run_dirs:
            result_path = rd / ".eval" / "result.json"
            if result_path.exists():
                try:
                    r = json.loads(result_path.read_text(encoding="utf-8"))
                    r["case"] = case_dir.name
                    r["run_idx"] = _run_idx(rd)
                    r["workspace"] = str(rd)
                    results.append(r)
                except Exception:
                    pass
            else:
                results.append({
                    "case": case_dir.name,
                    "run_idx": _run_idx(rd),
                    "workspace": str(rd),
                    "status": "pending",
                })
    return results


def _collect_trace_stats(workspace: Path) -> dict | None:
    """从 workspace/.eval/trace/*.json 汇总 token/turn 统计。"""
    trace_dir = workspace / ".eval" / "trace"
    if not trace_dir.exists():
        return None

    total_tokens = {"input": 0, "output": 0, "total": 0, "cache_read": 0, "cache_write": 0}
    total_turns = 0
    total_tool_usage: dict[str, int] = {}
    session_count = 0

    for f in trace_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        session_count += 1
        stats = data.get("stats", {})
        total_turns += stats.get("turn_count", 0)

        tok = stats.get("tokens", {})
        for k in total_tokens:
            total_tokens[k] += tok.get(k, 0)

        for tool, count in stats.get("tool_usage", {}).items():
            total_tool_usage[tool] = total_tool_usage.get(tool, 0) + count

    if session_count == 0:
        return None

    return {
        "session_count": session_count,
        "turn_count": total_turns,
        "tokens": total_tokens,
        "tool_usage": total_tool_usage,
    }


def _run_idx(path: Path) -> int:
    name = path.name
    if name.startswith("run_"):
        try:
            return int(name[4:])
        except ValueError:
            pass
    return 0


# ── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
