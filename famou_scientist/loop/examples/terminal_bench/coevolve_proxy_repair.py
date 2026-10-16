"""Phase B: offline proxy↔GT co-evolve repair harness (朴素版本).

The in-loop proxy is frozen the moment `verifier_plan` builds it, and the GT
result is never fed back to it (see nodes.py: the bundle store hard-rejects any
rewrite, and the VerifierAgent that builds/diagnoses the proxy sees no GT
fields). So "let the verifier agent fix the proxy using GT" cannot be a loop
mode — it has to be an *offline* harness that re-plays one frozen artifact.

What this does, per run directory:

  1. discover()  — locate the frozen proxy bundle, the public task_root, the
     final candidate artifact, the GT result, and the last proxy round report.
  2. run_proxy_content() — re-execute the frozen `verifier.py` on the SAME
     artifact offline (subprocess) and read its content checks. This is the
     REPAIRABLE surface: the harness-added wrapper checks (preflight /
     artifact_validation / public_evaluation) are NOT part of the proxy — in
     particular public_evaluation is the official public test suite — so the
     agent never touches them and we don't score them here.
  3. verdicts — proxy content PASS iff no content check is "failed"; GT PASS iff
     reward == 1 / valid. BEFORE agreement = (proxy == GT).
  4. repair_bundle() — hand the VerifierAgent the proxy code + its own report +
     the GT pytest output, under two red lines (GT calibrates the proxy's
     reliability, it does NOT score the solution; NO hardcoding of GT answers /
     expected numbers — else the proxy degrades into oracle search), and take
     back a revised verifier.py (+ goal_reference.py).
  5. re-run the revised proxy on the same artifact → AFTER verdict → AFTER
     agreement. Report BEFORE→AFTER per run and aggregated.

KPI = proxy↔GT PASS/FAIL agreement, before vs after repair. Expectation from
the three-class framework: synthesized tasks (reactor/rdkit/traffic/ode) should
gain; blind tasks (guided-wave/ankle/tamp) should NOT — with PASS/FAIL-only and
no hardcoding, a blind proxy can only stay honestly wrong. Those are the
negative controls that keep the harness honest.

Usage:
  # BEFORE-only (no model spend), validate mechanics on pilot data:
  python coevolve_proxy_repair.py --no-repair .famou/tbs-reruns-v51-proxy-v2/*
  # full repair loop:
  python coevolve_proxy_repair.py --out .famou/coevolve_out .famou/tbs-reruns-v84*/*
"""
from __future__ import annotations

import argparse
import ast
import glob as _glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL = os.environ.get("FAMOU_COEVOLVE_MODEL", "claude-opus-5")
PROXY_TIMEOUT = int(os.environ.get("FAMOU_COEVOLVE_PROXY_TIMEOUT", "1200"))
REPAIR_TIMEOUT = int(os.environ.get("FAMOU_COEVOLVE_REPAIR_TIMEOUT", "1800"))

# ---------------------------------------------------------------- discovery

_TASKROOT_MARKERS = (
    "api/schemas.json", "metadata.json", "instances", "study",
    "vocabularies.json", "icd10_candidates.tsv", "environment/data", "environment",
)


def _task_id(run_dir: Path) -> str:
    """`tbs-<task>-tbs-reruns-vNN-...` -> `<task>`."""
    name = run_dir.name
    if name.startswith("tbs-"):
        name = name[4:]
    return name.split("-tbs-reruns")[0]


def _looks_like_task_root(d: Path) -> bool:
    return any((d / m).exists() for m in _TASKROOT_MARKERS)


def _find_task_root(run_dir: Path) -> Path | None:
    """Public task-data root: prefer the captured fmjob-inputs/<task>/root-data,
    fall back to the verifier worktree (what the proxy actually read)."""
    inputs = run_dir / "fmjob-inputs"
    if inputs.is_dir():
        for rd in inputs.glob("*/root-data"):
            if _looks_like_task_root(rd):
                return rd
    wt = run_dir / "famou/terminal_task_agents/branches/verifier/worktree"
    if wt.is_dir() and _looks_like_task_root(wt):
        return wt
    return None


def _find_candidate(run_dir: Path) -> Path | None:
    for rel in ("famou/artifacts/final_workspace",
                "famou/terminal_task_agents/branches/solver/worktree",
                "submission"):
        p = run_dir / rel
        if p.is_dir():
            return p
    return None


def _last_proxy_round(run_dir: Path) -> Path | None:
    d = run_dir / "famou/agent_control/surrogate"
    rounds = sorted(d.glob("round_*.json"),
                    key=lambda p: int(re.search(r"round_(\d+)", p.name).group(1))) if d.is_dir() else []
    return rounds[-1] if rounds else None


def _gt_from_final_audit(run_dir: Path) -> dict | None:
    p = run_dir / "famou/controller/final_audit/result.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text())
    reward = (r.get("metrics") or {}).get("reward")
    return {"source": "final_audit", "reward": reward, "valid": r.get("valid"),
            "stdout": r.get("stdout", ""), "path": str(p)}


def _gt_from_shadow(run_dir: Path) -> dict | None:
    """dual_shadow embeds shadow GT per round as `gt_evaluation` in the report.
    Take the last round that carries one."""
    d = run_dir / "famou/controller/surrogate"
    if not d.is_dir():
        d = run_dir / "famou/agent_control/surrogate"
    best = None
    for p in sorted(d.glob("round_*.json"),
                    key=lambda q: int(re.search(r"round_(\d+)", q.name).group(1))) if d.is_dir() else []:
        try:
            g = json.loads(p.read_text()).get("gt_evaluation")
        except Exception:
            continue
        if g and (g.get("stdout") or "").strip():
            reward = (g.get("metrics") or {}).get("reward")
            if reward is None:
                reward = g.get("reward")
            best = {"source": "gt_shadow", "reward": reward, "valid": g.get("valid"),
                    "stdout": g.get("stdout", ""), "path": str(p)}
    return best


def discover(run_dir: Path) -> dict:
    """Return a dict of resolved paths + a `ready` flag and `missing` list."""
    bundle = run_dir / "famou/controller/verifier/bundle"
    task_root = _find_task_root(run_dir)
    candidate = _find_candidate(run_dir)
    gt = _gt_from_final_audit(run_dir) or _gt_from_shadow(run_dir)
    proxy_report = _last_proxy_round(run_dir)
    missing = []
    if not (bundle / "verifier.py").exists():
        missing.append("bundle/verifier.py")
    if task_root is None:
        missing.append("task_root")
    if candidate is None:
        missing.append("candidate")
    if gt is None:
        missing.append("gt_result")
    return {
        "run_dir": run_dir, "task": _task_id(run_dir),
        "bundle": bundle, "task_root": task_root, "candidate": candidate,
        "gt": gt, "proxy_report": proxy_report,
        "ready": not missing, "missing": missing,
    }


# ------------------------------------------------------------ proxy exec

def run_proxy_content(bundle_dir: Path, candidate_root: Path, task_root: Path) -> dict:
    """Run the frozen (or revised) `verifier.py` offline; return its JSON report.
    Only the proxy's own content checks — no harness wrapper checks.

    The candidate is copied to a scratch dir first (ignoring __pycache__) and the
    subprocess runs with PYTHONDONTWRITEBYTECODE=1. Otherwise importing the
    candidate's code writes new .pyc files into the stored artifact, which (a)
    pollutes the .famou corpus and (b) makes the verifier's own
    `behavior.workspace_readonly` hygiene check fail spuriously — an offline
    replay artifact unrelated to candidate quality."""
    out = tempfile.mkdtemp(prefix="coevolve_proxy_")
    scratch = tempfile.mkdtemp(prefix="coevolve_cand_")
    cand = Path(scratch) / "candidate"
    try:
        shutil.copytree(candidate_root, cand, ignore=shutil.ignore_patterns("__pycache__"))
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, str(bundle_dir / "verifier.py"),
             "--candidate-root", str(cand),
             "--task-root", str(task_root),
             "--output-dir", out],
            capture_output=True, text=True, timeout=PROXY_TIMEOUT, env=env,
        )
        # verifier.py exits rc=1 when a content check FAILS, but still emits a
        # valid JSON report on stdout. So parse stdout regardless of rc; only a
        # missing/unparseable report is a real execution error.
        s = proc.stdout or ""
        if s.strip():
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                try:
                    return json.loads(s[s.find("{"): s.rfind("}") + 1])
                except Exception:
                    pass
        return {"_error": f"rc={proc.returncode}", "_stderr": (proc.stderr or "")[-2000:], "checks": []}
    finally:
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)


def proxy_verdict(report: dict) -> str:
    """PASS iff no content check is 'failed'. 'unknown' is not a failure but is
    tracked separately by the caller. An execution error is FAIL(=cannot pass)."""
    if report.get("_error"):
        return "ERROR"
    checks = report.get("checks") or []
    if any(c.get("status") == "failed" for c in checks):
        return "FAIL"
    return "PASS"


def _proxy_unknowns(report: dict) -> list[str]:
    return [c.get("id") for c in (report.get("checks") or []) if c.get("status") == "unknown"]


def gt_verdict(gt: dict) -> str:
    reward = gt.get("reward")
    if reward is None:
        return "PASS" if gt.get("valid") else "FAIL"
    try:
        return "PASS" if float(reward) >= 1.0 else "FAIL"
    except (TypeError, ValueError):
        return "FAIL"


def _agree(proxy: str, gt: str) -> bool | None:
    if proxy == "ERROR":
        return None
    return proxy == gt


# --------------------------------------------------------------- repair

def _error_lines(stdout: str, limit: int = 2500) -> str:
    lines = [l.strip()[2:].strip() for l in (stdout or "").splitlines()
             if l.startswith("E ") and len(l.strip()) > 3]
    fails = [l for l in (stdout or "").splitlines() if l.strip().startswith(("FAILED", "PASSED", "= "))]
    txt = "\n".join(dict.fromkeys(lines + fails))
    return txt if len(txt) <= limit else txt[:limit] + "…"


REPAIR_SYSTEM = (
    "你在做「proxy↔GT 协同进化」的离线校准。一个 AI 造的 proxy 校验器（verifier.py）"
    "试图在看不到隐藏答案的情况下，本地重建官方 GT 的判定。现在给你这个 proxy 的代码、"
    "它自己跑出的报告、以及官方 GT 的真实评测输出（pytest）。请修订 proxy 代码，让它下次"
    "对同类产物的 PASS/FAIL 判定更贴近 GT。\n\n"
    "两条红线，违反即判失败：\n"
    "1) GT 的用途是「校准 proxy 的可靠性与重建逻辑」，不是「给这一份解打分」。绝对不许把 GT "
    "的期望答案、期望数值、通过阈值上的具体解、或任何只对当前这份产物成立的常量硬编码进 proxy"
    "（那会退化成 oracle 搜索，proxy 就废了）。你要改的是「重建方法/判据/容差的做法」，使它对"
    "整个同类分布都成立。\n"
    "2) proxy 的职责是用公开/已有数据构造**最佳代理度量**去近似 GT 的判定，并靠多次 GT 反馈"
    "迭代校准让它越来越准。近似天然不完美——这正是需要多次校准的原因，不是拒绝的理由。因此"
    "**绝不许**因为「隐藏目标无法完美重建 / 代理精度不达标 / 拿不到隐藏数据」就把该轴一律判"
    "failed（也不许一律放行）：那等于放弃近似、退化成恒 FAIL（或恒 PASS）的空壳，这种做法可以"
    "套到任何隐藏轴上，proxy 就废了。你必须用当前最好的代理度量给出**实际**的 PASS/FAIL，目标是"
    "让判定整体对齐 GT：既要拦住 GT=FAIL，也要放行 GT=PASS，不能顾此失彼。只有当某条轴在公开数据"
    "下确实没有任何可近似的信号（真盲轴，如隐藏构型根本无法合成）时，才可标注为诚实不可判定，且"
    "该「不可判定」不得单独用来否决一个候选。\n"
    "3) 对齐是双向的，禁止「往严里改」的过拟合：只许纠正 GT 确实会判 FAIL 的偏差，不许无中"
    "生有地新增、收紧、或从公开物料臆造 GT 并不强制的判据。公开物料（metadata.json / 模板 / "
    "说明文本）可能只是**描述性**信息（如数据表列名、量纲、时间列名），不等于提交必须满足的通过"
    "契约；拿不准某条判据 GT 是否真的强制时，宁可不加。下方标注为「确认通过」的正例是 GT 已判 "
    "PASS 的铁样本，你的任何改动都**不得**把它们判成 FAIL——误杀正例与放行假绿灯同样是失败。\n\n"
    "输出要求：先用不超过 6 行说明你判断 proxy 哪里与 GT 背离、以及你的修法（不要贴 GT 数值）。"
    "然后把**完整**的修订版文件各放进一个带标签的代码块：\n"
    "===FILE verifier.py===\n```python\n<完整文件>\n```\n"
    "若需要同时改 goal_reference.py，再加：\n"
    "===FILE goal_reference.py===\n```python\n<完整文件>\n```\n"
    "只输出没改的文件可以省略。verifier.py 必须保留 `def verify(candidate_root, task_root, output_dir)` "
    "与 `if __name__ == \"__main__\"` 的 argparse 接口（--candidate-root/--task-root/--output-dir/--describe）不变。"
)

_FILE_RE = re.compile(r"===FILE\s+(?P<name>[\w./-]+)===\s*```(?:python)?\s*\n(?P<body>.*?)```", re.S)


def _call_model(prompt: str) -> str:
    """Call the repair model. Any failure (timeout, non-zero exit, unparseable
    JSON) degrades to an empty string so the caller reports 'no ===FILE=== parsed'
    and the ship-gate rolls back to the frozen bundle — never crashes the sweep."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        out = subprocess.run(
            ["claude", "--bare", "--print", "--model", MODEL, "--output-format", "json", prompt],
            capture_output=True, text=True, timeout=REPAIR_TIMEOUT, env=env, cwd="/tmp",
        ).stdout
        return json.loads(out).get("result", "")
    except subprocess.TimeoutExpired:
        print(f"    [_call_model] TIMEOUT after {REPAIR_TIMEOUT}s -> treat as failed repair", file=sys.stderr, flush=True)
        return ""
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    [_call_model] bad model output ({e}) -> treat as failed repair", file=sys.stderr, flush=True)
        return ""


def repair_bundle(bundle_dir: Path, proxy_report: dict, gt: dict, out_dir: Path) -> dict:
    """Copy the frozen bundle to out_dir, ask the model for revised files, write
    them in, validate they compile. Return {ok, files, note, raw}."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(bundle_dir, out_dir, ignore=shutil.ignore_patterns("__pycache__"))
    src = (bundle_dir / "verifier.py").read_text(encoding="utf-8", errors="replace")
    goal = bundle_dir / "goal_reference.py"
    goal_src = goal.read_text(encoding="utf-8", errors="replace") if goal.exists() else ""
    spec = bundle_dir / "verifier_spec.md"
    spec_src = spec.read_text(encoding="utf-8", errors="replace")[:3000] if spec.exists() else ""

    failed = [c for c in (proxy_report.get("checks") or []) if c.get("status") in ("failed", "unknown")]
    prompt = (
        REPAIR_SYSTEM + "\n\n"
        f"【proxy 规格摘要】\n{spec_src}\n\n"
        f"【proxy 当前判定】status={proxy_report.get('status')}；"
        f"失败/未知检查：{json.dumps([{'id': c.get('id'), 'status': c.get('status')} for c in failed], ensure_ascii=False)}\n\n"
        f"【官方 GT 真实输出（这份产物的正解口径，仅供校准，禁止照抄数值）】\n{_error_lines(gt.get('stdout', ''))}\n\n"
        f"【verifier.py 全文】\n```python\n{src}\n```\n\n"
        + (f"【goal_reference.py 全文】\n```python\n{goal_src}\n```\n" if goal_src else "")
    )
    raw = _call_model(prompt)
    files = {}
    for m in _FILE_RE.finditer(raw):
        files[m.group("name").strip()] = m.group("body")
    if not files:
        return {"ok": False, "files": [], "note": "no ===FILE=== block parsed", "raw": raw[:1500]}
    written, errs = [], []
    for name, body in files.items():
        base = os.path.basename(name)
        if base not in ("verifier.py", "goal_reference.py"):
            continue
        try:
            ast.parse(body)
        except SyntaxError as e:
            errs.append(f"{base}: syntax {e}")
            continue
        (out_dir / base).write_text(body, encoding="utf-8")
        written.append(base)
    if "verifier.py" not in written:
        return {"ok": False, "files": written, "note": "verifier.py not written; " + "; ".join(errs), "raw": raw[:800]}
    return {"ok": True, "files": written, "note": "; ".join(errs) or "ok",
            "explanation": raw[:raw.find("===FILE")].strip()[:600]}


# --------------------------------------------------------------- per-run

def evaluate_run(run_dir: Path, *, repair: bool, out_root: Path | None) -> dict:
    d = discover(run_dir)
    res = {"run": run_dir.name, "task": d["task"], "ready": d["ready"], "missing": d["missing"]}
    if not d["ready"]:
        return res
    before = run_proxy_content(d["bundle"], d["candidate"], d["task_root"])
    gt = d["gt"]
    pv, gv = proxy_verdict(before), gt_verdict(gt)
    res["gt_source"] = gt.get("source")
    res["before"] = {"proxy": pv, "gt": gv, "agree": _agree(pv, gv),
                     "unknowns": _proxy_unknowns(before),
                     "n_failed": sum(1 for c in before.get("checks", []) if c.get("status") == "failed")}
    if before.get("_error"):
        res["before"]["error"] = before["_error"] + " " + before.get("_stderr", "")[-400:]
    if not repair:
        return res
    out_dir = (out_root or Path(tempfile.mkdtemp())) / run_dir.name / "revised_bundle"
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rep = repair_bundle(d["bundle"], before, gt, out_dir)
    res["repair"] = {k: rep[k] for k in ("ok", "files", "note") if k in rep}
    if rep.get("explanation"):
        res["repair"]["explanation"] = rep["explanation"]
    if rep["ok"]:
        after = run_proxy_content(out_dir, d["candidate"], d["task_root"])
        av = proxy_verdict(after)
        res["after"] = {"proxy": av, "gt": gv, "agree": _agree(av, gv),
                        "unknowns": _proxy_unknowns(after),
                        "n_failed": sum(1 for c in after.get("checks", []) if c.get("status") == "failed")}
        if after.get("_error"):
            res["after"]["error"] = after["_error"] + " " + after.get("_stderr", "")[-400:]
    return res


def _expand(paths: list[str]) -> list[Path]:
    out = []
    for p in paths:
        hits = _glob.glob(p)
        for h in (hits or [p]):
            hp = Path(h)
            # accept either a run dir or a batch dir containing run dirs
            if (hp / "famou/controller/verifier").exists() or (hp / "famou").exists():
                out.append(hp)
            elif hp.is_dir():
                out.extend(c for c in sorted(hp.iterdir()) if (c / "famou").exists())
    return out


# =====================================================================
# Per-task limited-GT co-evolve experiment (--mode task-coevolve).
#
# Unit of work is the TASK, not the run. A task owns:
#   - one canonical frozen proxy bundle (the in-loop proxy to calibrate),
#   - one resolved task_root,
#   - a POOL of candidate artifacts, each with a real official-GT verdict.
#
# The candidate/GT source is UNIFORM across every batch: surrogate round
# payloads `artifacts/famou/surrogate/round_N/payload` (clean app/submission
# layout) + that round's `gt_evaluation` (real official GT — shadow GT in
# dual_shadow, per-round GT in gt_primary/gt_budget). Deduped by sha256.
#
# The pool is split into calibration / holdout. A fixed GT-spend policy on the
# calibration set simulates the Verifier gate (spend K GT on proxy=PASS
# candidates = false-green hunting); the K disagreements repair ONE proxy per
# task; the revised proxy is scored on the HOLDOUT the Verifier never saw.
# KPI = false-green rate (proxy=PASS ∧ GT=FAIL) on holdout, vs K, with the
# GT=PASS holdout agreement printed as the anti-gaming guard (a conservative
# flip-to-FAIL drives false-green to 0 but tanks GT=PASS agreement).
# =====================================================================

TASK_ALIASES = {
    "ode": "ode-law-discovery", "reactor": "reactor-safety-control",
    "traffic": "traffic-flux-inversion", "rdkit": "rdkit-ic-constraints",
    "guided-wave": "guided-wave-localization", "guided": "guided-wave-localization",
    "ankle": "ankle-mri-findings", "tamp": "tamp-skill-planning",
    "hbv": "hbv-calibration-1", "linked-cell": "linked-cell-suppression",
    "small-area": "small-area-equivalence", "baseline-free": "baseline-free-localization",
    "finite-free": "finite-free-stam",
}


def _gt_from_round(round_json: dict) -> dict | None:
    """Build a GT dict from a surrogate round's embedded `gt_evaluation`
    (real official GT). Same shape as `_gt_from_shadow`. None if no GT ran."""
    g = round_json.get("gt_evaluation")
    if not g or not (g.get("stdout") or "").strip():
        return None
    reward = g.get("reward")
    if reward is None:
        reward = (g.get("metrics") or {}).get("reward")
    return {"source": "round_gt", "reward": reward, "valid": g.get("valid"),
            "stdout": g.get("stdout", "")}


def _iter_run_candidates(run_dir: Path):
    """Yield (sha256, payload_root: Path, gt: dict) for every surrogate round of
    this run that has both a real candidate payload and a real GT verdict."""
    sdir = run_dir / "famou/controller/surrogate"
    if not sdir.is_dir():
        return
    for rp in sorted(sdir.glob("round_*.json"),
                     key=lambda p: int(re.search(r"round_(\d+)", p.name).group(1))):
        try:
            j = json.loads(rp.read_text())
        except Exception:
            continue
        ar = j.get("artifact_ref") or {}
        sha, sp = ar.get("sha256"), ar.get("storage_path")
        if not sha or not sp or not Path(sp).is_dir():
            continue
        gt = _gt_from_round(j)
        if gt is None:
            continue
        gt["path"] = str(rp)
        yield sha, Path(sp), gt


def resolve_task_root(task: str, run_dirs: list[Path]) -> Path | None:
    """Per-task singleton task_root. Prefer a real task-data root, fall back to
    the verifier worktree (carries fixtures/tests), then any candidate payload —
    proxies like reactor resolve their spec via a bundled fallback anyway."""
    for d in run_dirs:
        tr = _find_task_root(d)
        if tr is not None:
            return tr
    for d in run_dirs:
        wt = d / "famou/terminal_task_agents/branches/verifier/worktree"
        if wt.is_dir():
            return wt
    for d in run_dirs:
        for sha, root, _ in _iter_run_candidates(d):
            return root
    return None


def pick_canonical_bundle(task: str, run_dirs: list[Path]) -> Path | None:
    """One frozen `bundle/verifier.py` as this task's baseline proxy."""
    for d in run_dirs:
        b = d / "famou/controller/verifier/bundle"
        if (b / "verifier.py").exists():
            return b
    return None


def build_task_pool(task: str, run_dirs: list[Path]) -> dict:
    """Collect all distinct (candidate, GT-verdict) pairs for the task, deduped
    by sha256 across runs. Returns {task, bundle, task_root, candidates, missing}."""
    task_runs = [d for d in run_dirs if _task_id(d) == task]
    bundle = pick_canonical_bundle(task, task_runs)
    task_root = resolve_task_root(task, task_runs)
    seen: set[str] = set()
    candidates = []
    for d in task_runs:
        for sha, root, gt in _iter_run_candidates(d):
            if sha in seen:
                continue
            seen.add(sha)
            candidates.append({
                "cand_id": f"{d.name}:{Path(gt['path']).stem}",
                "root": root, "gt": gt, "verdict": gt_verdict(gt),
                "sha": sha, "source": gt.get("source"),
            })
    missing = []
    if bundle is None:
        missing.append("bundle")
    if task_root is None:
        missing.append("task_root")
    if not candidates:
        missing.append("candidates")
    return {"task": task, "bundle": bundle, "task_root": task_root,
            "candidates": candidates, "missing": missing}


def split_pool(candidates: list[dict], seed: int, holdout_frac: float) -> tuple[list[dict], list[dict]]:
    """Stratified split by GT verdict so both PASS and FAIL land in each split
    where available. Deterministic in `seed`. Holdout is anti-gaming: it is
    never shown to the GT-spend / repair steps."""
    import random
    rng = random.Random(seed)
    calib, holdout = [], []
    for verdict in ("PASS", "FAIL"):
        grp = [c for c in candidates if c["verdict"] == verdict]
        rng.shuffle(grp)
        n_hold = int(round(len(grp) * holdout_frac))
        # keep at least one in each split when the group has >= 2
        if len(grp) >= 2:
            n_hold = min(max(n_hold, 1), len(grp) - 1)
        holdout.extend(grp[:n_hold])
        calib.extend(grp[n_hold:])
    # Shuffle calib so the GT-spend policy encounters candidates in an order
    # UNCORRELATED with GT verdict — the Verifier cannot see GT when choosing
    # whom to spend a GT on. Without this, the stratified concat lists all
    # GT=PASS first, so a small K only ever hits proxy/GT agreements (true
    # passes) and never reaches a false-green in the GT=FAIL tail.
    rng.shuffle(calib)
    return calib, holdout


def gt_spend_policy(calib: list[dict], bundle: Path, task_root: Path, K: int) -> tuple[list[dict], int]:
    """Fixed offline simulation of the Verifier gate: run the frozen proxy on the
    calibration candidates, and among those the proxy calls PASS, spend one GT
    each (up to budget K). Every spent GT yields a signal carrying its GT verdict:
    gt_verdict="FAIL" is a false-green the repair must LEARN TO BLOCK, gt_verdict=
    "PASS" is a confirmed pass the repair must NOT BREAK. Feeding both directions
    stops the repair from collapsing the proxy into a blanket-reject. Returns
    (signals, gt_spent)."""
    if K <= 0:
        return [], 0
    signals, spent = [], 0
    for c in calib:
        if spent >= K:
            break
        report = run_proxy_content(bundle, c["root"], task_root)
        if proxy_verdict(report) != "PASS":
            continue  # proxy already rejects it → no GT spent on it
        spent += 1  # Verifier spends one GT to check this suspected pass
        signals.append({"candidate": c, "proxy_report": report,
                        "gt": c["gt"], "gt_verdict": c["verdict"]})
    return signals, spent


def repair_bundle_multi(bundle_dir: Path, signals: list[dict], out_dir: Path,
                        feedback: str = "") -> dict:
    """Per-task repair from K false-green signals in ONE model call. Mirrors
    repair_bundle's contract (red lines, ===FILE=== output, AST validation) but
    feeds all K (proxy-said-PASS, GT-said-FAIL) disagreements at once."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(bundle_dir, out_dir, ignore=shutil.ignore_patterns("__pycache__"))
    src = (bundle_dir / "verifier.py").read_text(encoding="utf-8", errors="replace")
    goal = bundle_dir / "goal_reference.py"
    goal_src = goal.read_text(encoding="utf-8", errors="replace") if goal.exists() else ""
    spec = bundle_dir / "verifier_spec.md"
    spec_src = spec.read_text(encoding="utf-8", errors="replace")[:3000] if spec.exists() else ""

    def _sig_block(s: dict) -> str:
        failed = [c for c in (s["proxy_report"].get("checks") or [])
                  if c.get("status") in ("failed", "unknown")]
        detail = (json.dumps([{"id": c.get("id"), "status": c.get("status")} for c in failed],
                             ensure_ascii=False) if failed else "无（proxy 内容检查全 passed）")
        return (f"  proxy 失败/未知检查：{detail}\n"
                f"  GT 真实输出（仅供校准，禁止照抄数值）：\n{_error_lines(s['gt'].get('stdout', ''))}")

    neg = [s for s in signals if s["gt_verdict"] == "FAIL"]   # false-greens: must block
    pos = [s for s in signals if s["gt_verdict"] == "PASS"]   # confirmed passes: must not break
    neg_blocks = [f"【假绿灯 {i}】proxy 判 PASS 但官方 GT 判 FAIL——必须学会拦住这一类。\n"
                  + _sig_block(s) for i, s in enumerate(neg, 1)]
    pos_blocks = [f"【确认通过 {i}】proxy 判 PASS 且官方 GT 也判 PASS——改完后必须仍然放行这一类，绝不许误杀。\n"
                  + _sig_block(s) for i, s in enumerate(pos, 1)]
    prompt = (
        REPAIR_SYSTEM + "\n\n"
        f"【proxy 规格摘要】\n{spec_src}\n\n"
        f"下面给出 {len(neg)} 个假绿灯（proxy 漏放的 GT=FAIL）与 {len(pos)} 个确认通过（GT=PASS 正例）。"
        "你的目标是让 proxy 判定**整体对齐 GT**：把重建方法/判据/容差改成对整个同类分布成立"
        "（不是对这几份产物成立），既要拦住假绿灯、又要继续放行确认通过的正例。特别重申红线②——"
        "不许因为某条隐藏轴难以完美重建就把它一律判 failed，那会把下面的正例一并误杀；必须用当前"
        "最好的代理度量做出**实际**判定：\n\n"
        "== 必须拦住（假绿灯，GT=FAIL）==\n" + ("\n\n".join(neg_blocks) if neg_blocks else "（无）") + "\n\n"
        "== 必须继续放行（确认通过，GT=PASS）==\n" + ("\n\n".join(pos_blocks) if pos_blocks else "（无）") + "\n\n"
        + (f"【上一轮修订被上线硬闸拒绝，必须修正后重交】\n{feedback}\n\n" if feedback else "")
        + f"【verifier.py 全文】\n```python\n{src}\n```\n\n"
        + (f"【goal_reference.py 全文】\n```python\n{goal_src}\n```\n" if goal_src else "")
    )
    raw = _call_model(prompt)
    files = {}
    for m in _FILE_RE.finditer(raw):
        files[m.group("name").strip()] = m.group("body")
    if not files:
        return {"ok": False, "files": [], "note": "no ===FILE=== block parsed", "raw": raw[:1500]}
    written, errs = [], []
    for name, body in files.items():
        base = os.path.basename(name)
        if base not in ("verifier.py", "goal_reference.py"):
            continue
        try:
            ast.parse(body)
        except SyntaxError as e:
            errs.append(f"{base}: syntax {e}")
            continue
        (out_dir / base).write_text(body, encoding="utf-8")
        written.append(base)
    if "verifier.py" not in written:
        return {"ok": False, "files": written, "note": "verifier.py not written; " + "; ".join(errs), "raw": raw[:800]}
    return {"ok": True, "files": written, "note": "; ".join(errs) or "ok",
            "explanation": raw[:raw.find("===FILE")].strip()[:600]}


def _run_signals(bundle_dir: Path, signals: list[dict], task_root: Path,
                 want_verdict: str) -> list[dict]:
    """Run a bundle on the calibration signals whose GT verdict == want_verdict.
    Returns the ones the proxy MISJUDGES relative to GT, each with the failing
    check ids. For want_verdict=="PASS": confirmed passes the proxy now flips to
    FAIL (regressions we must not ship). For "FAIL": false-greens still let
    through (leaks)."""
    wrong = []
    for sig in signals:
        if sig["gt_verdict"] != want_verdict:
            continue
        rep = run_proxy_content(bundle_dir, sig["candidate"]["root"], task_root)
        verdict = proxy_verdict(rep)
        misjudged = (verdict != "PASS") if want_verdict == "PASS" else (verdict == "PASS")
        if misjudged:
            failed = [c.get("id") for c in (rep.get("checks") or [])
                      if c.get("status") in ("failed", "unknown")]
            wrong.append({"cand_id": sig["candidate"]["cand_id"], "checks": failed})
    return wrong


def repair_task_with_gate(bundle_dir: Path, signals: list[dict], out_dir: Path,
                          task_root: Path, max_attempts: int = 3) -> dict:
    """Repair the proxy, then GATE it before it 'goes live': the revised proxy
    must not regress any confirmed-pass anchor (GT=PASS) to FAIL. If it does,
    feed back exactly which anchors broke on which checks and ask for another
    revision (reject-and-retry, up to max_attempts). If it still regresses after
    the last attempt, ROLL BACK to the frozen bundle rather than ship a proxy
    that introduced a new false-negative. Returns the repair dict plus a `gate`
    record: {attempts, broke_pos, leaked_fg, shipped}. shipped is "revised" or
    "frozen_rollback"."""
    # Two-sided gate. All false-green signals leak under the FROZEN proxy by
    # construction (gt_spend_policy only spends a GT on candidates the frozen
    # proxy already called PASS). So the revision must (a) break NO confirmed
    # pass AND (b) block at least one of those false-greens — a strict net
    # improvement — or we roll back to frozen rather than ship a proxy that is
    # looser (more false-greens) or tighter (kills real passes) than doing
    # nothing.
    n_fg = sum(1 for sig in signals if sig["gt_verdict"] == "FAIL")
    feedback = ""
    last = None
    broke, leaked = [], []
    for attempt in range(1, max_attempts + 1):
        rep = repair_bundle_multi(bundle_dir, signals, out_dir, feedback=feedback)
        last = rep
        if not rep["ok"]:
            rep["gate"] = {"attempts": attempt, "broke_pos": None,
                           "leaked_fg": None, "shipped": "frozen_rollback",
                           "reason": "repair did not compile/parse"}
            return rep
        broke = _run_signals(out_dir, signals, task_root, "PASS")   # confirmed passes now FAIL
        leaked = _run_signals(out_dir, signals, task_root, "FAIL")  # false-greens still PASS
        blocked = n_fg - len(leaked)
        if not broke and blocked > 0:
            rep["gate"] = {"attempts": attempt, "broke_pos": [],
                           "leaked_fg": len(leaked), "blocked_fg": blocked,
                           "n_fg": n_fg, "shipped": "revised"}
            return rep
        # not shippable yet → build targeted feedback and retry
        parts = []
        if broke:
            lines = [f"  确认通过样本 {b['cand_id']} 被你新判为 FAIL，挂在检查 {b['checks']}"
                     for b in broke]
            parts.append(
                f"太严：你把 {len(broke)} 个 GT 已确认通过的正例误判成了 FAIL：\n"
                + "\n".join(lines) + "\n"
                "这些是 GT=PASS 铁样本，绝不能判失败。放宽/移除是你新增或收紧过头、"
                "很可能从公开物料臆造的那条判据。")
        if blocked <= 0:
            parts.append(
                f"太松：你没有拦住任何一个假绿灯（{n_fg} 个 GT=FAIL 仍被判 PASS）。"
                "必须真正重建导致 GT 判 FAIL 的那条判据/度量，把它们拦下来。")
        feedback = ("\n".join(parts) +
                    "\n目标是同时做到：拦住上面的假绿灯，且不误杀任何确认通过的正例。重交完整文件。")
    # exhausted attempts without a net-improving, non-regressing revision
    if last is not None:
        last["ok"] = False
        last["gate"] = {"attempts": max_attempts,
                        "broke_pos": [b["cand_id"] for b in broke],
                        "leaked_fg": len(leaked), "blocked_fg": n_fg - len(leaked),
                        "n_fg": n_fg, "shipped": "frozen_rollback",
                        "reason": "no net-improving revision (too tight or too loose) after retries"}
        return last
    return {"ok": False, "files": [], "note": "no repair produced",
            "gate": {"attempts": max_attempts, "shipped": "frozen_rollback"}}


def _metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    """Confusion-matrix derived metrics (positive class = proxy PASS, truth = GT).
    All values are derivable from the four cells, so they are verifiable, not
    self-reported. false_green_rate = FP/(FP+TN); recall = TP/(TP+FN) (the
    anti-gaming guard: a 'flip all to FAIL' proxy tanks it); precision =
    TP/(TP+FP) = how trustworthy a proxy PASS is."""
    def _r(num, den):
        return (num / den) if den else None
    return {
        "false_green_rate": _r(fp, fp + tn),      # FP among GT=FAIL
        "recall": _r(tp, tp + fn),                # TP among GT=PASS (gt_pass_agree)
        "precision": _r(tp, tp + fp),             # trust of a proxy PASS
        "accuracy": _r(tp + tn, tp + fp + fn + tn),
    }


def evaluate_holdout(bundle_dir: Path, task_root: Path, holdout: list[dict]) -> dict:
    """Score a proxy on the holdout as a binary classifier (positive = proxy
    PASS, truth = GT). Returns the full confusion matrix TP/FP/FN/TN plus
    derived metrics. FP is the false-green (proxy PASS but GT FAIL)."""
    tp = fp = fn = tn = err = 0
    for c in holdout:
        report = run_proxy_content(bundle_dir, c["root"], task_root)
        pv = proxy_verdict(report)
        if pv == "ERROR":
            err += 1
            continue
        gt_pass = c["verdict"] == "PASS"
        proxy_pass = pv == "PASS"
        if gt_pass and proxy_pass:
            tp += 1
        elif gt_pass and not proxy_pass:
            fn += 1
        elif not gt_pass and proxy_pass:
            fp += 1          # false green
        else:
            tn += 1
    out = {
        "n_holdout": len(holdout), "n_error": err,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "n_pass": tp + fn, "n_fail": fp + tn,   # verifiable: GT=PASS / GT=FAIL counts
    }
    out.update(_metrics(tp, fp, fn, tn))
    return out


# =====================================================================
# Continuous layer (score = gate × value). BINARY PATH ABOVE IS UNCHANGED.
# value ∈ [0,1] via a public/math-constant continuize; gate is the hard-0
# format/behavior guard. GT value comes from the modified official grader's
# uncensored METRIC lines (regrade_continuous_gt.py jsonl); proxy value comes
# from the proxy's OWN public-data advisory numbers (red line ②). No GT
# reference-solution measured value ever enters the scale (red line ③).
# =====================================================================

def continuize(err) -> float:
    """err≥0, smaller better. Theoretical optimum err=0 → 1. err≥1 means "no better
    than the trivial mean/zero baseline" — a math property of nRMSE (normalised by
    std) and relative-L2 (‖pred-true‖/‖true‖), NOT a GT reference value — → 0.
    Scale is therefore a math constant (red line ③)."""
    try:
        return max(0.0, min(1.0, 1.0 - float(err)))
    except (TypeError, ValueError):
        return 0.0


# ode: the three hidden GT value axes (keys as emitted by the modified grader).
_ODE_GT_AXES = ("standard_rollout_nrmse", "stress_rollout_nrmse", "vector_field_rel_error")

# ode: GT axis -> (proxy check id, regex pulling the advisory 'actual' from its summary).
# The proxy reconstructs each hidden axis from PUBLIC data; these are its own numbers.
_ODE_PROXY_AXES = {
    "standard_rollout_nrmse": ("public_validation_nrmse", r"nRMSE\s+([0-9.eE+\-]+)"),
    "stress_rollout_nrmse": ("extended_rollout_nrmse", r"rollout nRMSE\s+([0-9.eE+\-]+)"),
    "vector_field_rel_error": ("vector_field_data_agreement", r"relative L2 error\s+([0-9.eE+\-]+)"),
}


def load_continuous_gt(path: Path) -> dict:
    """Map realpath(<candidate>/results) -> regrade row (from regrade_continuous_gt.py)."""
    out: dict = {}
    if not path or not Path(path).exists():
        return out
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[os.path.realpath(r["id"])] = r
    return out


def cont_gt_for_candidate(cont_gt: dict, cand: dict) -> dict | None:
    """Harness candidate root is `.../payload`; continuous GT is keyed on
    `.../payload/results`. Returns the regrade row or None."""
    key = os.path.realpath(str(Path(cand["root"]) / "results"))
    return cont_gt.get(key)


def gt_score_from_metrics(rec: dict | None) -> float | None:
    """Continuous GT value ∈ [0,1] = gate × min-axis continuize (min mirrors the
    official AND over axes). Missing axis (integration/parse crash) → that axis 0.
    gate fail (format/schema/complexity) → hard 0. None if the candidate has no
    regrade row at all."""
    if rec is None:
        return None
    if not rec.get("gate_pass", True):
        return 0.0
    vals = []
    for ax in _ODE_GT_AXES:
        m = (rec.get("metrics") or {}).get(ax)
        vals.append(continuize(m["err"]) if m else 0.0)
    return min(vals) if vals else 0.0


def _proxy_axis_actual(check: dict, rx: str):
    """Prefer a structured actual field; else parse it out of the summary text."""
    for k in ("actual", "value", "measured"):
        v = check.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    m = re.search(rx, check.get("summary", "") or "")
    return float(m.group(1)) if m else None


def proxy_score(report: dict) -> float | None:
    """Continuous proxy value ∈ [0,1] = gate × min-axis continuize, from the proxy's
    own public-data advisory numbers. gate = every NON-axis proxy check passed (any
    failed → hard 0). None if the proxy failed to execute."""
    if report.get("_error"):
        return None
    checks = {c.get("id"): c for c in (report.get("checks") or [])}
    axis_ids = {cid for cid, _ in _ODE_PROXY_AXES.values()}
    for cid, c in checks.items():
        if cid not in axis_ids and c.get("status") == "failed":
            return 0.0
    vals = []
    for _gt_ax, (cid, rx) in _ODE_PROXY_AXES.items():
        c = checks.get(cid)
        a = _proxy_axis_actual(c, rx) if c else None
        vals.append(continuize(a) if a is not None else 0.0)
    return min(vals) if vals else 0.0


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (ties → average ranks). None if n<2 or no variance."""
    n = len(xs)
    if n < 2:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    return (num / (dx * dy)) if dx and dy else None


def evaluate_holdout_continuous(bundle_dir: Path, task_root: Path, holdout: list[dict],
                                cont_gt: dict) -> dict:
    """Three-layer proxy↔GT continuous alignment on the holdout (design §5):
    ①序对齐 Spearman(proxy_value, gt_value) — most important;
    ②不高估 overestimate = mean/max of max(0, proxy−gt) — single-sided anti-Goodhart;
    ③数值对齐 MAE/RMSE. Positive class semantics gone: both sides are [0,1] values."""
    pairs = []  # (proxy_value, gt_value, cand_id)
    n_err = n_nogt = 0
    for c in holdout:
        gv = gt_score_from_metrics(cont_gt_for_candidate(cont_gt, c))
        if gv is None:
            n_nogt += 1
            continue
        pv = proxy_score(run_proxy_content(bundle_dir, c["root"], task_root))
        if pv is None:
            n_err += 1
            continue
        pairs.append((pv, gv, c["cand_id"]))
    xs = [p for p, _, _ in pairs]
    ys = [g for _, g, _ in pairs]
    over = [max(0.0, p - g) for p, g, _ in pairs]
    return {
        "n": len(pairs), "n_error": n_err, "n_no_gt": n_nogt,
        "spearman": _spearman(xs, ys),
        "overestimate_mean": (sum(over) / len(over)) if over else None,
        "overestimate_max": max(over) if over else None,
        "mae": (sum(abs(p - g) for p, g, _ in pairs) / len(pairs)) if pairs else None,
        "rmse": (math.sqrt(sum((p - g) ** 2 for p, g, _ in pairs) / len(pairs))) if pairs else None,
        "pairs": [{"cand": cid, "proxy": round(p, 4), "gt": round(g, 4)} for p, g, cid in pairs],
    }


_RED_LINES = (
    "两条红线，违反即判失败：\n"
    "1) GT 的用途是「校准 proxy 的可靠性与重建逻辑」，不是「给这一份解打分」。绝对不许把 GT "
    "的期望答案、期望数值、通过阈值上的具体解、或任何只对当前这份产物成立的常量硬编码进 proxy"
    "（那会退化成 oracle 搜索，proxy 就废了）。你要改的是「重建方法/判据/容差的做法」，使它对"
    "整个同类分布都成立。\n"
    "2) proxy 的职责是用公开/已有数据构造**最佳代理度量**去近似 GT 的判定，并靠多次 GT 反馈"
    "迭代校准让它越来越准。近似天然不完美——这正是需要多次校准的原因，不是拒绝的理由。因此"
    "**绝不许**因为「隐藏目标无法完美重建 / 代理精度不达标 / 拿不到隐藏数据」就把该轴一律判"
    "0 分（也不许一律给满分）：那等于放弃近似、退化成恒 0（或恒满分）的空壳，这种做法可以"
    "套到任何隐藏轴上，proxy 就废了。你必须用当前最好的代理度量给出**实际**的连续分。\n"
    "3) 对齐是双向的，禁止「往严里改」的过拟合：只许纠正 GT 确实判低分的偏差，不许无中生有地"
    "新增、收紧、或从公开物料臆造 GT 并不强制的判据。下方标注为「高分锚点」的正例是 GT 已给"
    "高分的铁样本，你的任何改动都**不得**把它们的连续分压低——压低高分锚点与吹高低质量解同样是失败。\n"
)

_REPAIR_SYSTEM_CONT = (
    "你在做「proxy↔GT 协同进化」的离线校准。一个 AI 造的 proxy 校验器（verifier.py）在看不到隐藏"
    "答案的情况下，用公开数据重建官方 GT 的判定。现在评分已从 0/1 改成**连续分**：proxy 对每个"
    "候选用它的公开代理度量给出一个 [0,1] 的连续质量分（越接近 1 越好），要去逼近官方 GT 在隐藏"
    "测试集上算出的连续质量分。给你 proxy 代码、它的报告、以及若干候选上「proxy 连续分 vs 官方 GT "
    "连续分」的对照。请修订 proxy，让它下次对同类产物的**连续分**更贴近 GT——重点是两件事：\n"
    "  ① 序对齐：proxy 分的高低排序要和 GT 一致（proxy 认为更好的，GT 也更好）；\n"
    "  ② 不高估：proxy 分不许系统性地高于 GT 分（高估会被解题方钻空子 Goodhart）。\n\n"
    + _RED_LINES +
    "\n输出要求：先用不超过 6 行说明 proxy 的连续分在哪与 GT 背离（排序错 / 高估）、以及你的修法"
    "（改重建度量/容差/聚合，不要贴 GT 数值）。然后把**完整**的修订版文件各放进带标签代码块：\n"
    "===FILE verifier.py===\n```python\n<完整文件>\n```\n"
    "若需要同时改 goal_reference.py，再加：\n"
    "===FILE goal_reference.py===\n```python\n<完整文件>\n```\n"
    "只输出没改的文件可以省略。verifier.py 必须保留 `def verify(candidate_root, task_root, output_dir)` "
    "与 `if __name__ == \"__main__\"` 的 argparse 接口（--candidate-root/--task-root/--output-dir/--describe）不变。\n\n"
    "【执行环境说明——很重要】你**不能运行任何代码、也不能创建临时文件来试跑**；由离线 harness "
    "负责把你交回的 verifier.py 跑在候选上重新打分。所以**不要**写「try/except 里出错就回退旧行为」"
    "这种防御性空操作——那等于没改。请直接依据上面给出的候选公开作业(equations.json)和 proxy↔GT "
    "对照，判断该收紧/重建哪条判据，然后**直接交出完整的修订文件**。"
)

# ship-gate thresholds for the continuous repair
_ANCHOR_HI = 0.6      # gt_value >= this ⇒ a high-quality anchor the revision must not push down
_ANCHOR_EPS = 0.05    # allowed downward drift of an anchor's proxy value before it counts as broken


def _cont_sig_block(s: dict) -> str:
    """One calibration signal: proxy's continuous value vs GT's, plus the proxy's own
    per-axis advisory actuals and GT's real per-axis errors (calibration data — must
    NOT be hardcoded). GT stdout carries the uncensored METRIC lines."""
    rec = s.get("gt_rec") or {}
    gt_axes = {ax: (rec.get("metrics", {}).get(ax) or {}).get("err") for ax in _ODE_GT_AXES}
    checks = {c.get("id"): c for c in (s["proxy_report"].get("checks") or [])}
    proxy_axes = {}
    for gt_ax, (cid, rx) in _ODE_PROXY_AXES.items():
        c = checks.get(cid)
        proxy_axes[gt_ax] = _proxy_axis_actual(c, rx) if c else None
    lines = [f"  proxy 连续分={s['proxy_value']:.3f}  官方 GT 连续分={s['gt_value']:.3f}  "
             f"(高估={max(0.0, s['proxy_value']-s['gt_value']):.3f})"]
    lines.append("  逐轴（仅供校准，禁止照抄这些数值进代码）：")
    for ax in _ODE_GT_AXES:
        lines.append(f"    {ax}: proxy估≈{proxy_axes.get(ax)}  GT实测≈{gt_axes.get(ax)}")
    if not rec.get("gate_pass", True):
        lines.append(f"    注意：该候选被官方硬约束判死(gate_failed={rec.get('gate_failed')})，GT 连续分应为 0")
    # 候选自己提交的 equations.json：这是产物**公开的作业**（非 GT、非隐藏答案），
    # 贴出来让你能直接 diff 出「被 GT 判低分的候选」违反了哪条**公开任务契约**
    # （state_variables/time_variable/parameters/complexity 等格式约束都是公开的）。
    try:
        eq_path = Path(s["candidate"]["root"]) / "results" / "equations.json"
        eq_txt = eq_path.read_text(encoding="utf-8", errors="replace")
        if len(eq_txt) > 1800:
            eq_txt = eq_txt[:1800] + "\n…(截断)"
        lines.append("  该候选提交的 equations.json（公开作业，可据此判断它违反了哪条公开格式契约）：")
        lines.append("    " + eq_txt.replace("\n", "\n    "))
    except Exception as _e:
        lines.append(f"  （该候选 equations.json 读取失败：{_e}）")
    return "\n".join(lines)


def repair_bundle_multi_continuous(bundle_dir: Path, signals: list[dict], out_dir: Path,
                                   feedback: str = "") -> dict:
    """Continuous analogue of repair_bundle_multi: feed K (proxy_value, gt_value)
    divergences at once and ask for a revised proxy whose continuous scores track GT
    in ORDER and do not OVERESTIMATE. Same ===FILE=== + AST-validation contract."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(bundle_dir, out_dir, ignore=shutil.ignore_patterns("__pycache__"))
    src = (bundle_dir / "verifier.py").read_text(encoding="utf-8", errors="replace")
    goal = bundle_dir / "goal_reference.py"
    goal_src = goal.read_text(encoding="utf-8", errors="replace") if goal.exists() else ""
    spec = bundle_dir / "verifier_spec.md"
    spec_src = spec.read_text(encoding="utf-8", errors="replace")[:3000] if spec.exists() else ""

    over = [s for s in signals if (s["proxy_value"] - s["gt_value"]) > _ANCHOR_EPS]   # proxy 高估：要压
    anchors = [s for s in signals if s["gt_value"] >= _ANCHOR_HI]                      # GT 高分：不许压低
    over_blocks = [f"【高估 {i}】proxy 把它捧得比 GT 高——要把这类的 proxy 分压到贴近 GT。\n" + _cont_sig_block(s)
                   for i, s in enumerate(over, 1)]
    anch_blocks = [f"【高分锚点 {i}】GT 给了高分——改完后 proxy 仍须给它高分，绝不许压低。\n" + _cont_sig_block(s)
                   for i, s in enumerate(anchors, 1)]
    prompt = (
        _REPAIR_SYSTEM_CONT + "\n\n"
        f"【proxy 规格摘要】\n{spec_src}\n\n"
        f"下面给出 {len(over)} 个高估样本与 {len(anchors)} 个高分锚点。目标：让 proxy 的连续分**整体对齐 GT**"
        "（序一致、不高估），既压住高估、又不压低锚点，且改的是对整个同类分布成立的重建方法（不是这几份产物）。\n\n"
        "== 要压住高估（proxy > GT）==\n" + ("\n\n".join(over_blocks) if over_blocks else "（无）") + "\n\n"
        "== 不许压低（GT 高分锚点）==\n" + ("\n\n".join(anch_blocks) if anch_blocks else "（无）") + "\n\n"
        + (f"【上一轮修订被放行闸拒绝，必须修正后重交】\n{feedback}\n\n" if feedback else "")
        + f"【verifier.py 全文】\n```python\n{src}\n```\n\n"
        + (f"【goal_reference.py 全文】\n```python\n{goal_src}\n```\n" if goal_src else "")
    )
    raw = _call_model(prompt)
    files = {}
    for m in _FILE_RE.finditer(raw):
        files[m.group("name").strip()] = m.group("body")
    if not files:
        return {"ok": False, "files": [], "note": "no ===FILE=== block parsed", "raw": raw[:1500]}
    written, errs = [], []
    for name, body in files.items():
        base = os.path.basename(name)
        if base not in ("verifier.py", "goal_reference.py"):
            continue
        try:
            ast.parse(body)
        except SyntaxError as e:
            errs.append(f"{base}: syntax {e}")
            continue
        (out_dir / base).write_text(body, encoding="utf-8")
        written.append(base)
    if "verifier.py" not in written:
        return {"ok": False, "files": written, "note": "verifier.py not written; " + "; ".join(errs), "raw": raw[:800]}
    return {"ok": True, "files": written, "note": "; ".join(errs) or "ok",
            "explanation": raw[:raw.find("===FILE")].strip()[:600]}


def _score_signals(bundle_dir: Path, signals: list[dict], task_root: Path) -> list[float]:
    """Re-score each signal candidate's proxy value under a (revised) bundle."""
    vals = []
    for s in signals:
        vals.append(proxy_score(run_proxy_content(bundle_dir, s["candidate"]["root"], task_root)))
    return vals


def repair_task_with_gate_continuous(bundle_dir: Path, signals: list[dict], out_dir: Path,
                                     task_root: Path, max_attempts: int = 3) -> dict:
    """Repair the proxy, then GATE before shipping (continuous): the revision must
    (a) NOT push any GT-high anchor's proxy value down by more than _ANCHOR_EPS, AND
    (b) strictly REDUCE the total overestimate Σ max(0, proxy−gt) over the verified
    signals (proxy less optimistic where GT says lower). Else retry with feedback,
    else roll back to the frozen bundle."""
    def total_over(vals):
        return sum(max(0.0, (v if v is not None else 0.0) - s["gt_value"]) for v, s in zip(vals, signals))

    frozen_vals = [s["proxy_value"] for s in signals]
    base_over = total_over(frozen_vals)
    anchors = [(i, s) for i, s in enumerate(signals) if s["gt_value"] >= _ANCHOR_HI]
    feedback = ""
    last = None
    for attempt in range(1, max_attempts + 1):
        rep = repair_bundle_multi_continuous(bundle_dir, signals, out_dir, feedback=feedback)
        last = rep
        if not rep["ok"]:
            rep["gate"] = {"attempts": attempt, "shipped": "frozen_rollback",
                           "reason": "repair did not compile/parse"}
            return rep
        new_vals = _score_signals(out_dir, signals, task_root)
        broke = [signals[i]["candidate"]["cand_id"] for (i, s) in anchors
                 if (new_vals[i] is None) or (frozen_vals[i] - new_vals[i] > _ANCHOR_EPS)]
        new_over = total_over(new_vals)
        improved = new_over < base_over - 1e-9
        if not broke and improved:
            rep["gate"] = {"attempts": attempt, "broke_anchors": [], "shipped": "revised",
                           "overestimate_before": round(base_over, 4), "overestimate_after": round(new_over, 4)}
            return rep
        parts = []
        if broke:
            parts.append(f"太严：你把 {len(broke)} 个 GT 高分锚点的 proxy 分压低了：{broke}。"
                         "这些是 GT 铁高分，绝不能压低——放宽你新增或收紧过头、很可能从公开物料臆造的那条判据。")
        if not improved:
            parts.append(f"没改善：高估总量没下降（改前 {base_over:.3f} → 改后 {new_over:.3f}）。"
                         "必须真正重建导致 GT 给低分的那条度量，把被高估的候选的 proxy 分压到贴近 GT。")
        # 补上完整评测结果：把这次参与打分的**每一个**产物摊开——官方 GT 分、修订前 proxy 分、
        # 你这版改完后 proxy 分。让你看清自己把哪个候选动到了哪里（离线实验里 GT 分对校准侧全公开）。
        tbl = ["本次评测全部产物的逐一结果（改前 proxy → 你改后 proxy vs 官方 GT）："]
        for i, s in enumerate(signals):
            cid = s["candidate"]["cand_id"]
            gtv = s["gt_value"]
            fz = frozen_vals[i]
            nv = new_vals[i]
            nv_s = f"{nv:.3f}" if nv is not None else "None(崩)"
            tag = "  ←GT高分锚点(不许压低)" if gtv >= _ANCHOR_HI else (
                  "  ←proxy高估(要压向GT)" if (fz - gtv) > _ANCHOR_EPS else "")
            tbl.append(f"  {cid}: GT={gtv:.3f}  改前proxy={fz:.3f}  改后proxy={nv_s}{tag}")
        parts.append("\n".join(tbl))
        feedback = ("\n".join(parts) + "\n目标：压住高估且不压低任何高分锚点。重交完整文件。")
    if last is not None:
        last["ok"] = False
        last["gate"] = {"attempts": max_attempts, "shipped": "frozen_rollback",
                        "reason": "no net-improving revision (broke anchors or no overestimate drop)"}
        return last
    return {"ok": False, "files": [], "note": "no repair produced",
            "gate": {"attempts": max_attempts, "shipped": "frozen_rollback"}}


def gt_spend_policy_continuous(calib: list[dict], bundle: Path, task_root: Path,
                               cont_gt: dict, K: int) -> tuple[list[dict], int]:
    """Verifier gate (continuous): pick candidates by PROXY signal only (highest proxy
    value = the proxy's most-confident 'good' ones, most worth a GT check), spend one
    GT each up to K, and reveal the continuous GT. The revealed divergences (proxy≫gt
    = overestimate) are what the repair must fix; GT-high ones are anchors to protect.
    Selection never sees GT (red line). Returns (signals, gt_spent)."""
    if K <= 0:
        return [], 0
    scored = []
    for c in calib:
        rec = cont_gt_for_candidate(cont_gt, c)
        if rec is None:
            continue  # no continuous GT available to reveal → cannot spend here
        report = run_proxy_content(bundle, c["root"], task_root)
        pv = proxy_score(report)
        if pv is None:
            continue
        scored.append((pv, c, report, rec))
    # rank by proxy value desc (proxy-only), deterministic tie-break by cand_id
    scored.sort(key=lambda t: (-t[0], t[1]["cand_id"]))
    signals = []
    for pv, c, report, rec in scored[:K]:
        signals.append({
            "candidate": c, "proxy_report": report,
            "proxy_value": pv, "gt_value": gt_score_from_metrics(rec) or 0.0,
            "gt_rec": rec, "gt": c["gt"],
        })
    return signals, len(signals)


def run_task_continuous_baseline(task: str, run_dirs: list[Path], *, seed: int,
                                 holdout_frac: float, cont_gt_path: Path) -> dict:
    """K=0 continuous baseline: freeze the canonical proxy and report the three-layer
    alignment on the holdout. This is the pre-calibration starting point (§11.2 checkpoint)."""
    pool = build_task_pool(task, run_dirs)
    res = {"task": task, "n_candidates": len(pool["candidates"]), "missing": pool["missing"]}
    if pool["missing"]:
        return res
    cont_gt = load_continuous_gt(cont_gt_path)
    calib, holdout = split_pool(pool["candidates"], seed, holdout_frac)
    res["n_calib"] = len(calib)
    res["n_holdout"] = len(holdout)
    res["cont_gt_rows"] = len(cont_gt)
    align = evaluate_holdout_continuous(pool["bundle"], pool["task_root"], holdout, cont_gt)
    res["K0"] = align
    print(f"  {task:<26} K=0 continuous | n={align['n']} "
          f"(noGT={align['n_no_gt']} err={align['n_error']}) | "
          f"Spearman={_fmt_rate(align['spearman'])} "
          f"overest(mean/max)={_fmt_rate(align['overestimate_mean'])}/{_fmt_rate(align['overestimate_max'])} "
          f"MAE={_fmt_rate(align['mae'])} RMSE={_fmt_rate(align['rmse'])}", flush=True)
    return res


def run_task_continuous_coevolve(task: str, run_dirs: list[Path], *, seed: int,
                                 holdout_frac: float, cont_gt_path: Path,
                                 k_values: list[int], out_root: Path,
                                 repair: bool = True) -> dict:
    """Continuous co-evolve K-sweep (§11.3). For each K: spend <=K continuous GT on
    the calib pool (proxy-only selection), repair the proxy toward rank/value alignment
    behind a ship-gate, then measure the three-layer alignment on the untouched holdout.
    K=0 is the frozen baseline; a very large K (>= #calib) is the 'unlimited' arm."""
    pool = build_task_pool(task, run_dirs)
    res = {"task": task, "n_candidates": len(pool["candidates"]), "missing": pool["missing"]}
    if pool["missing"]:
        return res
    cont_gt = load_continuous_gt(cont_gt_path)
    calib, holdout = split_pool(pool["candidates"], seed, holdout_frac)
    res["n_calib"] = len(calib)
    res["n_holdout"] = len(holdout)
    res["cont_gt_rows"] = len(cont_gt)
    bundle, task_root = pool["bundle"], pool["task_root"]
    ks = sorted(set(k_values)) if k_values else [0, 1, 5, max(1, len(calib))]
    sweep = []
    for K in ks:
        row = {"K": K}
        if K == 0 or not repair:
            row["gt_spent"] = 0
            row["repair_ok"] = None
            row["shipped"] = "frozen"
            row["align"] = evaluate_holdout_continuous(bundle, task_root, holdout, cont_gt)
        else:
            signals, spent = gt_spend_policy_continuous(calib, bundle, task_root, cont_gt, K)
            over = [s for s in signals if (s["proxy_value"] - s["gt_value"]) > _ANCHOR_EPS]
            anchors = [s for s in signals if s["gt_value"] >= _ANCHOR_HI]
            row["gt_spent"] = spent
            row["n_overest"] = len(over)        # revealed overestimates to fix
            row["n_anchors"] = len(anchors)     # GT-high anchors to protect
            # nothing to fix if the proxy did not overestimate any spent candidate
            # (the gate's "reduce overestimate" test could never pass) -> keep frozen,
            # exactly like the binary path skips repair when there are no false-greens.
            if not signals or not over:
                row["repair_ok"] = None
                row["shipped"] = "frozen"
                row["align"] = evaluate_holdout_continuous(bundle, task_root, holdout, cont_gt)
            else:
                out_dir = out_root / f"{task}_contK{K}_seed{seed}" / "revised_bundle"
                out_dir.parent.mkdir(parents=True, exist_ok=True)
                rep = repair_task_with_gate_continuous(bundle, signals, out_dir, task_root)
                gate = rep.get("gate") or {}
                row["repair_ok"] = rep["ok"]
                row["repair_note"] = rep.get("note")
                row["gate"] = gate
                if rep.get("explanation"):
                    row["repair_explanation"] = rep["explanation"]
                row["shipped"] = gate.get("shipped")
                # ship revised proxy only if the gate accepted it; else frozen rollback
                eval_bundle = out_dir if gate.get("shipped") == "revised" else bundle
                row["align"] = evaluate_holdout_continuous(eval_bundle, task_root, holdout, cont_gt)
        a = row["align"]
        print(f"  {task:<26} K={K} spent={row['gt_spent']} "
              f"over={row.get('n_overest', 0)} anchors={row.get('n_anchors', 0)} "
              f"ship={row.get('shipped')} | n={a['n']} "
              f"Spearman={_fmt_rate(a['spearman'])} "
              f"overest(mean/max)={_fmt_rate(a['overestimate_mean'])}/{_fmt_rate(a['overestimate_max'])} "
              f"MAE={_fmt_rate(a['mae'])} RMSE={_fmt_rate(a['rmse'])}"
              + (f" repair_ok={row['repair_ok']}" if row.get("repair_ok") is not None else ""),
              flush=True)
        sweep.append(row)
    res["sweep"] = sweep
    return res


def run_task_experiment(task: str, run_dirs: list[Path], *, k_max: int, seed: int,
                        holdout_frac: float, out_root: Path, repair: bool,
                        k_values: list[int] | None = None) -> dict:
    pool = build_task_pool(task, run_dirs)
    res = {"task": task, "n_candidates": len(pool["candidates"]), "missing": pool["missing"]}
    if pool["missing"]:
        return res
    calib, holdout = split_pool(pool["candidates"], seed, holdout_frac)
    res["n_calib"] = len(calib)
    res["n_holdout"] = len(holdout)
    res["holdout_pass"] = sum(1 for c in holdout if c["verdict"] == "PASS")
    res["holdout_fail"] = sum(1 for c in holdout if c["verdict"] == "FAIL")
    bundle, task_root = pool["bundle"], pool["task_root"]
    ks = sorted(set(k_values)) if k_values else list(range(0, k_max + 1))
    sweep = []
    for K in ks:
        row = {"K": K}
        if K == 0 or not repair:
            row["gt_spent"] = 0
            row["repair_ok"] = None
            row.update(evaluate_holdout(bundle, task_root, holdout))
        else:
            signals, spent = gt_spend_policy(calib, bundle, task_root, K)
            false_greens = [s for s in signals if s["gt_verdict"] == "FAIL"]
            row["gt_spent"] = spent
            row["n_signals"] = len(false_greens)      # false-greens to fix
            row["n_pos_anchors"] = len(signals) - len(false_greens)  # confirmed passes to protect
            if not false_greens:
                row["repair_ok"] = None  # proxy let nothing wrong through → keep frozen
                row.update(evaluate_holdout(bundle, task_root, holdout))
            else:
                out_dir = out_root / f"{task}_K{K}_seed{seed}" / "revised_bundle"
                out_dir.parent.mkdir(parents=True, exist_ok=True)
                rep = repair_task_with_gate(bundle, signals, out_dir, task_root)
                row["repair_ok"] = rep["ok"]
                row["repair_note"] = rep.get("note")
                gate = rep.get("gate") or {}
                row["gate"] = gate
                if rep.get("explanation"):
                    row["repair_explanation"] = rep["explanation"]
                # ship the revised proxy only if the pre-live gate accepted it;
                # otherwise fall back to the frozen bundle (no regressed proxy)
                eval_bundle = out_dir if gate.get("shipped") == "revised" else bundle
                row.update(evaluate_holdout(eval_bundle, task_root, holdout))
        sweep.append(row)
        print(f"  {task:<26} K={K} gt_spent={row['gt_spent']} "
              f"holdout(P/F)={res['holdout_pass']}/{res['holdout_fail']} "
              f"| TP={row['tp']} FP={row['fp']} FN={row['fn']} TN={row['tn']}"
              + (f" ERR={row['n_error']}" if row['n_error'] else "") + " | "
              f"FPR(false-green)={row['fp']}/{row['fp']+row['tn']}"
              f"={_fmt_rate(row['false_green_rate'])} "
              f"recall={row['tp']}/{row['tp']+row['fn']}={_fmt_rate(row['recall'])} "
              f"prec={_fmt_rate(row['precision'])} acc={_fmt_rate(row['accuracy'])}"
              + (f" repair_ok={row['repair_ok']}" if row.get("repair_ok") is not None else "")
              + (f" gate={row['gate'].get('shipped')}"
                 f"(try{row['gate'].get('attempts')},"
                 f"brokePos={len(row['gate'].get('broke_pos') or [])},"
                 f"leakFG={row['gate'].get('leaked_fg')})" if row.get("gate") else ""),
              flush=True)
    res["sweep"] = sweep
    return res


def _fmt_rate(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def main_continuous_baseline(args) -> list:
    run_dirs = _expand(args.runs)
    all_tasks = sorted({_task_id(d) for d in run_dirs})
    if args.tasks:
        wanted = [TASK_ALIASES.get(t, t) for t in args.tasks]
        tasks = [t for t in wanted if t in all_tasks]
        missing = [t for t in wanted if t not in all_tasks]
        if missing:
            print(f"# no runs found for: {missing}", file=sys.stderr)
    else:
        tasks = all_tasks
    print(f"# continuous-baseline: {len(run_dirs)} run(s), {len(tasks)} task(s): {tasks}", file=sys.stderr)
    print(f"# cont-gt: {args.cont_gt}", file=sys.stderr)
    results = []
    for task in tasks:
        print(f"\n# === {task} (continuous K=0) ===", flush=True)
        r = run_task_continuous_baseline(task, run_dirs, seed=args.seed,
                                         holdout_frac=args.holdout_frac, cont_gt_path=args.cont_gt)
        results.append(r)
        if r.get("missing"):
            print(f"  SKIP  missing={r['missing']} (n_candidates={r['n_candidates']})")
    print("\n# three-layer alignment (design §5): ①Spearman↑  ②overestimate↓  ③MAE/RMSE↓")
    print(f"#   {'task':<26} {'n':>4}  {'Spearman':>9}  {'over(mean)':>10}  {'over(max)':>9}  {'MAE':>6}  {'RMSE':>6}")
    for r in results:
        if r.get("missing"):
            continue
        a = r["K0"]
        print(f"#   {r['task']:<26} {a['n']:>4}  {_fmt_rate(a['spearman']):>9}  "
              f"{_fmt_rate(a['overestimate_mean']):>10}  {_fmt_rate(a['overestimate_max']):>9}  "
              f"{_fmt_rate(a['mae']):>6}  {_fmt_rate(a['rmse']):>6}")
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
        print(f"\n# wrote {args.json}")
    return results


def main_continuous_coevolve(args) -> list:
    run_dirs = _expand(args.runs)
    all_tasks = sorted({_task_id(d) for d in run_dirs})
    if args.tasks:
        wanted = [TASK_ALIASES.get(t, t) for t in args.tasks]
        tasks = [t for t in wanted if t in all_tasks]
        missing = [t for t in wanted if t not in all_tasks]
        if missing:
            print(f"# no runs found for: {missing}", file=sys.stderr)
    else:
        tasks = all_tasks
    print(f"# continuous-coevolve: {len(run_dirs)} run(s), {len(tasks)} task(s): {tasks}", file=sys.stderr)
    print(f"# cont-gt: {args.cont_gt}  model: {MODEL}", file=sys.stderr)
    results = []
    for task in tasks:
        print(f"\n# === {task} (continuous co-evolve) ===", flush=True)
        r = run_task_continuous_coevolve(task, run_dirs, seed=args.seed,
                                         holdout_frac=args.holdout_frac, cont_gt_path=args.cont_gt,
                                         k_values=args.k_values, out_root=args.out,
                                         repair=not args.no_repair)
        results.append(r)
        if r.get("missing"):
            print(f"  SKIP  missing={r['missing']} (n_candidates={r['n_candidates']})")
    # KPI vs K (design §5): want Spearman↑, overestimate↓, MAE/RMSE↓ with K;
    # 判成立 = 三层随 K 改善且 K=5 逼近 unlimited (largest K arm).
    print("\n# KPI — three-layer alignment vs K (Spearman | over(mean) | MAE):")
    for r in results:
        if r.get("missing"):
            continue
        ks = [row["K"] for row in r["sweep"]]
        print(f"#   {r['task']:<26} (n_holdout={r.get('n_holdout')})  "
              + "  ".join(f"{'K='+str(k):>16}" for k in ks))
        cells = [f"{_fmt_rate(row['align']['spearman'])}|"
                 f"{_fmt_rate(row['align']['overestimate_mean'])}|"
                 f"{_fmt_rate(row['align']['mae'])}" for row in r["sweep"]]
        print(f"#   {'':<26} {'':>13}  " + "  ".join(f"{c:>16}" for c in cells))
        ships = [f"{row.get('shipped')}({row.get('gt_spent')})" for row in r["sweep"]]
        print(f"#   {'ship(spent)':<26} {'':>13}  " + "  ".join(f"{c:>16}" for c in ships))
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
        print(f"\n# wrote {args.json}")
    return results


def main_task_coevolve(args) -> list:
    run_dirs = _expand(args.runs)
    all_tasks = sorted({_task_id(d) for d in run_dirs})
    if args.tasks:
        wanted = [TASK_ALIASES.get(t, t) for t in args.tasks]
        tasks = [t for t in wanted if t in all_tasks]
        missing = [t for t in wanted if t not in all_tasks]
        if missing:
            print(f"# no runs found for: {missing}", file=sys.stderr)
    else:
        tasks = all_tasks
    print(f"# {len(run_dirs)} run(s), {len(tasks)} task(s): {tasks}", file=sys.stderr)
    results = []
    for task in tasks:
        print(f"\n# === {task} ===", flush=True)
        r = run_task_experiment(task, run_dirs, k_max=args.k_max, seed=args.seed,
                                holdout_frac=args.holdout_frac, out_root=args.out,
                                repair=not args.no_repair, k_values=args.k_values)
        results.append(r)
        if r.get("missing"):
            print(f"  SKIP  missing={r['missing']} (n_candidates={r['n_candidates']})")
    # summary: confusion matrix vs K per task. Each cell is TP/FP/FN/TN on the
    # holdout; watch FP (false-green, want ↓) AND FN (real PASS killed, the
    # anti-gaming cost, want steady). GT=FAIL/GT=PASS denominators shown as guard;
    # n<3 on either side → that rate is unstable.
    ks = sorted(set(args.k_values)) if args.k_values else list(range(0, args.k_max + 1))
    print("\n# KPI — confusion matrix (TP/FP/FN/TN) on holdout vs K:")
    print(f"#   {'task':<26} {'hold P/F':>9}  " + "  ".join(f"{'K='+str(k):>13}" for k in ks))
    for r in results:
        if r.get("missing"):
            continue
        cells = [f"{row['tp']}/{row['fp']}/{row['fn']}/{row['tn']}" for row in r["sweep"]]
        guard = f"{r['holdout_pass']}/{r['holdout_fail']}"
        print(f"#   {r['task']:<26} {guard:>9}  " + "  ".join(f"{c:>13}" for c in cells))
    # derived: false-green rate (FPR) and precision, the two headline numbers
    print("# derived — false-green rate FPR=FP/(FP+TN) | precision=TP/(TP+FP):")
    print(f"#   {'task':<26} {'':>9}  " + "  ".join(f"{'K='+str(k):>13}" for k in ks))
    for r in results:
        if r.get("missing"):
            continue
        cells = [f"{_fmt_rate(row['false_green_rate'])}|{_fmt_rate(row['precision'])}" for row in r["sweep"]]
        print(f"#   {r['task']:<26} {'':>9}  " + "  ".join(f"{c:>13}" for c in cells))
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
        print(f"\n# wrote {args.json}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Offline proxy↔GT co-evolve repair harness")
    ap.add_argument("runs", nargs="+", help="run dirs or batch dirs / globs")
    ap.add_argument("--mode", choices=("per-run", "task-coevolve", "continuous-baseline", "continuous-coevolve"), default="per-run",
                    help="per-run: legacy single-candidate replay; task-coevolve: per-task "
                         "binary calibration/holdout limited-GT experiment; continuous-baseline: "
                         "K=0 three-layer proxy↔GT continuous alignment on the holdout")
    ap.add_argument("--no-repair", action="store_true", help="only measure BEFORE agreement (no model call)")
    ap.add_argument("--out", type=Path, default=Path(".famou/coevolve_out"), help="where revised bundles go")
    ap.add_argument("--json", type=Path, default=None, help="write full per-run/per-task JSON here")
    # task-coevolve knobs
    ap.add_argument("--tasks", nargs="*", default=None,
                    help="task ids to run in task-coevolve mode (default: all discovered)")
    ap.add_argument("--k-max", type=int, default=3, help="task-coevolve: sweep K=0..k-max GT calls")
    ap.add_argument("--k-values", nargs="*", type=int, default=None,
                    help="task-coevolve: evaluate only these K (e.g. 0 5); overrides --k-max")
    ap.add_argument("--seed", type=int, default=0, help="task-coevolve: calibration/holdout split seed")
    ap.add_argument("--holdout-frac", type=float, default=0.4, help="task-coevolve: holdout fraction")
    ap.add_argument("--cont-gt", type=Path,
                    default=Path(".famou/continuous-gt/ode_continuous_gt.jsonl"),
                    help="continuous-baseline: regrade jsonl with uncensored continuous GT")
    args = ap.parse_args(argv)

    if args.mode == "continuous-baseline":
        return main_continuous_baseline(args)
    if args.mode == "continuous-coevolve":
        return main_continuous_coevolve(args)
    if args.mode == "task-coevolve":
        return main_task_coevolve(args)

    runs = _expand(args.runs)
    results = []
    for rd in runs:
        r = evaluate_run(rd, repair=not args.no_repair, out_root=args.out)
        results.append(r)
        if not r["ready"]:
            print(f"SKIP {r['task']:<26} {rd.name}  missing={r['missing']}")
            continue
        b = r["before"]
        line = f"{r['task']:<26} BEFORE proxy={b['proxy']} gt={b['gt']} agree={b['agree']}"
        if "after" in r:
            a = r["after"]
            line += f" | AFTER proxy={a['proxy']} agree={a['agree']} (repair={r['repair']['ok']})"
        elif "repair" in r:
            line += f" | repair_failed: {r['repair']['note']}"
        print(line)

    ready = [r for r in results if r.get("ready")]
    if ready:
        ba = sum(1 for r in ready if r["before"].get("agree") is True)
        print(f"\n# BEFORE agreement: {ba}/{len(ready)}")
        aft = [r for r in ready if "after" in r]
        if aft:
            aa = sum(1 for r in aft if r["after"].get("agree") is True)
            print(f"# AFTER  agreement: {aa}/{len(aft)}")
        # Per-(task, GT-verdict) breakdown. A conservative PASS->FAIL flip
        # trivially "agrees" on every GT=FAIL artifact, so agreement is only
        # meaningful when a task has BOTH GT=PASS and GT=FAIL artifacts. This
        # table makes that gaming visible: watch the GT=PASS rows.
        from collections import defaultdict
        groups = defaultdict(lambda: {"n": 0, "b": 0, "a": 0, "a_n": 0})
        for r in ready:
            g = groups[(r["task"], r["before"]["gt"])]
            g["n"] += 1
            g["b"] += 1 if r["before"].get("agree") is True else 0
            if "after" in r:
                g["a_n"] += 1
                g["a"] += 1 if r["after"].get("agree") is True else 0
        print("\n# per (task, GT) — GT=PASS rows are the ones a conservative flip cannot fake:")
        print(f"#   {'task':<26} {'GT':<5} {'n':>3} {'before_agree':>13} {'after_agree':>12}")
        for (task, gv) in sorted(groups):
            g = groups[(task, gv)]
            aft_s = f"{g['a']}/{g['a_n']}" if g["a_n"] else "-"
            print(f"#   {task:<26} {gv:<5} {g['n']:>3} {g['b']:>12}/{g['n']} {aft_s:>12}")
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
        print(f"# wrote {args.json}")
    return results


if __name__ == "__main__":
    main()
