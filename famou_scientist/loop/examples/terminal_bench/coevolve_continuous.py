#!/usr/bin/env python3
"""Registry-driven continuous co-evolve K-sweep (泛化版,不改 ode 硬编码路径).

ode 的连续 co-evolve 在 coevolve_proxy_repair.py 里跑通(判成立);那份是 ode 硬编码
(_ODE_GT_AXES / proxy_score check-id 正则 / _cont_sig_block 读 equations.json)。本模块把
"每题不同的四件事"抽成 per-task 适配器,复用 ode 已验证的修复原语(_call_model /
_REPAIR_SYSTEM_CONT / _FILE_RE / _ANCHOR_HI / _ANCHOR_EPS / continuize / _spearman):
  ① gt_value(row)      —— 从连续 GT jsonl 一行算 [0,1] 真值分(gate×value)
  ② proxy_value_frozen —— 冻结 proxy 对候选的 [0,1] 代理分(K=0,缓存/jsonl)
  ③ score_live(bundle) —— 用「改后 bundle」重打候选(reactor host-run / gw·traffic docker)
  ④ sig_block(cand)    —— 喂给修复模型的候选签名块(每题物料不同)
候选池直接由 GT jsonl 驱动(与各题 standalone K=0 KPI 同源),不走 build_task_pool。
"""
from __future__ import annotations
import argparse, json, math, os, random, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coevolve_proxy_repair as H  # reuse ode-proven primitives

REPO = Path(__file__).resolve().parents[4]
CG = REPO / ".famou" / "continuous-gt"
TBS = Path("/path/to/workspace/opensource/terminal-bench-science")


def clip01(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, x))


# ============================================================ generic sweep core
def split_pool(cands, seed, frac):
    """Stratified by GT verdict (gt_pass True/False) so both land in each split;
    deterministic in seed; calib shuffled so spend order is uncorrelated with GT.
    Mirrors coevolve_proxy_repair.split_pool."""
    rng = random.Random(seed)
    calib, holdout = [], []
    for v in (True, False):
        grp = [c for c in cands if bool(c["gt_pass"]) == v]
        rng.shuffle(grp)
        n_hold = int(round(len(grp) * frac))
        if len(grp) >= 2:
            n_hold = min(max(n_hold, 1), len(grp) - 1)
        holdout.extend(grp[:n_hold])
        calib.extend(grp[n_hold:])
    rng.shuffle(calib)
    return calib, holdout


def kpi(pairs):
    """pairs: list of (proxy_value, gt_value, cand_id). Three-layer alignment §5."""
    xs = [p for p, _, _ in pairs]
    ys = [g for _, g, _ in pairs]
    over = [max(0.0, p - g) for p, g, _ in pairs]
    n = len(pairs)
    return {
        "n": n,
        "spearman": H._spearman(xs, ys),
        "overestimate_mean": (sum(over) / n) if n else None,
        "overestimate_max": max(over) if over else None,
        "mae": (sum(abs(p - g) for p, g, _ in pairs) / n) if n else None,
        "rmse": (math.sqrt(sum((p - g) ** 2 for p, g, _ in pairs) / n)) if n else None,
        "pairs": [{"cand": c, "proxy": round(p, 4), "gt": round(g, 4)} for p, g, c in pairs],
    }


def holdout_kpi(holdout, score_fn):
    pairs = []
    for c in holdout:
        pv = score_fn(c)
        if pv is None:
            continue
        pairs.append((pv, c["gt_value"], c["cand_id"]))
    return kpi(pairs)


def spend_topk(calib, K):
    """Verifier gate: pick top-K by FROZEN proxy value (proxy-only, never sees GT),
    reveal continuous GT. Returns signals ranked by proxy desc, tie-break cand_id."""
    if K <= 0:
        return []
    ranked = sorted(calib, key=lambda c: (-c["proxy_value_frozen"], c["cand_id"]))
    return ranked[:K]


def repair_with_gate(ad, signals, out_dir, max_attempts=3):
    """Generic continuous repair + ship-gate (mirror repair_task_with_gate_continuous):
    revised proxy must (a) not drop any GT-high anchor's proxy value > _ANCHOR_EPS and
    (b) strictly reduce total overestimate Σ max(0,proxy−gt) over the spent signals;
    else retry with feedback, else frozen_rollback. Uses ad.score_live / ad.sig_block."""
    frozen = [s["proxy_value_frozen"] for s in signals]
    gts = [s["gt_value"] for s in signals]

    def tot_over(vals):
        return sum(max(0.0, (v if v is not None else 0.0) - g) for v, g in zip(vals, gts))

    base_over = tot_over(frozen)
    anchors = [i for i, s in enumerate(signals) if s["gt_value"] >= H._ANCHOR_HI]
    feedback, last = "", None
    for attempt in range(1, max_attempts + 1):
        rep = _repair_call(ad, signals, out_dir, feedback)
        last = rep
        if not rep["ok"]:
            # Parse/compile failure = the model didn't emit a complete ===FILE=== block
            # (flaky for large verifiers). Retry with an explicit format reminder rather
            # than rolling back immediately; only give up after the last attempt.
            if attempt < max_attempts:
                feedback = (
                    "上一轮没解析到可用修订（既没有闭合的 ===FILE verifier.py=== 完整代码块，"
                    "也没有可套用的 ===EDIT=== 搜索替换块）。文件很大时**请优先用搜索替换块**，"
                    "每块格式：\n"
                    "===EDIT verifier.py===\n<<<SEARCH\n<原文里要改的一小段，逐字复制且全文唯一>\n"
                    "<<<REPLACE\n<新片段>\n<<<END\n"
                    "（可多块；SEARCH 必须与原文逐字一致、否则套用失败）。也可整文件重交 "
                    "===FILE verifier.py===。只输出不超过 6 行说明 + 代码块。\n"
                    f"（诊断：{rep.get('note')}）"
                )
                continue
            rep["gate"] = {"attempts": attempt, "shipped": "frozen_rollback",
                           "reason": "repair did not compile/parse"}
            return rep
        new_vals = [ad.score_live(out_dir, s) for s in signals]
        broke = [signals[i]["cand_id"] for i in anchors
                 if (new_vals[i] is None) or (frozen[i] - new_vals[i] > H._ANCHOR_EPS)]
        new_over = tot_over(new_vals)
        improved = new_over < base_over - 1e-9
        if not broke and improved:
            rep["gate"] = {"attempts": attempt, "broke_anchors": [], "shipped": "revised",
                           "overestimate_before": round(base_over, 4),
                           "overestimate_after": round(new_over, 4)}
            return rep
        parts = []
        if broke:
            parts.append(f"太严：你把 {len(broke)} 个 GT 高分锚点压低了：{broke}。")
        if not improved:
            parts.append(f"没改善：高估总量没下降（{base_over:.3f}→{new_over:.3f}）。")
        tbl = ["本次评测全部产物（改前 proxy → 改后 proxy vs 官方 GT）："]
        for i, s in enumerate(signals):
            nv = new_vals[i]
            nv_s = f"{nv:.3f}" if nv is not None else "None(崩)"
            tag = "  ←GT高分锚点(不许压低)" if gts[i] >= H._ANCHOR_HI else (
                  "  ←proxy高估(要压向GT)" if (frozen[i] - gts[i]) > H._ANCHOR_EPS else "")
            tbl.append(f"  {s['cand_id']}: GT={gts[i]:.3f} 改前={frozen[i]:.3f} 改后={nv_s}{tag}")
        parts.append("\n".join(tbl))
        feedback = "\n".join(parts) + "\n目标：压住高估且不压低任何高分锚点。用 ===EDIT=== 搜索替换块（或整文件）重交。"
    last["ok"] = False
    last["gate"] = {"attempts": max_attempts, "shipped": "frozen_rollback",
                    "reason": "no net-improving revision (broke anchors or no overestimate drop)"}
    return last


# Fallback repair format for LARGE verifiers (e.g. traffic's 2333-line file): the model
# emits only the changed regions as search→replace blocks instead of echoing the whole
# file (full-file echo truncates for big files). Applied onto the frozen source in-harness.
_EDIT_RE = re.compile(
    r"===EDIT\s+(?P<name>[\w./-]+)===\s*<<<SEARCH\s*\n(?P<old>.*?)\n<<<REPLACE\s*\n"
    r"(?P<new>.*?)\n<<<END",
    re.DOTALL)


def _apply_edits(raw, base_src):
    """Parse ===EDIT name=== / <<<SEARCH / <<<REPLACE / <<<END blocks and apply them onto
    base_src (only verifier.py is patchable here). Returns {name: patched_body} for every
    file that had at least one successfully-applied edit, plus a list of failure notes."""
    edits = list(_EDIT_RE.finditer(raw))
    if not edits:
        return {}, ["no ===EDIT=== blocks"]
    patched = {}
    notes = []
    for m in edits:
        name = os.path.basename(m.group("name").strip())
        if name != "verifier.py":
            notes.append(f"skip edit for {name} (only verifier.py patchable)")
            continue
        cur = patched.get(name, base_src)
        old, new = m.group("old"), m.group("new")
        cnt = cur.count(old)
        if cnt == 0:
            notes.append("SEARCH snippet not found in source (verbatim match failed)")
            continue
        if cnt > 1:
            notes.append(f"SEARCH snippet ambiguous ({cnt} matches); need more context")
            continue
        patched[name] = cur.replace(old, new, 1)
    return patched, notes


def _repair_call(ad, signals, out_dir, feedback):
    """Build the repair prompt from per-task sig_blocks and call the model; write the
    revised bundle. Reuses ode _REPAIR_SYSTEM_CONT / _FILE_RE / _call_model."""
    bundle = ad.frozen_bundle
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(bundle, out_dir, ignore=shutil.ignore_patterns("__pycache__"))
    src = (bundle / "verifier.py").read_text(encoding="utf-8", errors="replace")
    spec = bundle / "verifier_spec.md"
    spec_src = spec.read_text(encoding="utf-8", errors="replace")[:3000] if spec.exists() else ""
    over = [s for s in signals if (s["proxy_value_frozen"] - s["gt_value"]) > H._ANCHOR_EPS]
    anch = [s for s in signals if s["gt_value"] >= H._ANCHOR_HI]
    over_b = [f"【高估 {i}】proxy 捧得比 GT 高——把这类 proxy 分压到贴近 GT。\n" + ad.sig_block(s)
              for i, s in enumerate(over, 1)]
    anch_b = [f"【高分锚点 {i}】GT 高分——改完 proxy 仍须给高分，绝不许压低。\n" + ad.sig_block(s)
              for i, s in enumerate(anch, 1)]
    prompt = (
        H._REPAIR_SYSTEM_CONT + "\n\n"
        f"【proxy 规格摘要】\n{spec_src}\n\n"
        f"下面给出 {len(over)} 个高估样本与 {len(anch)} 个高分锚点。目标：让 proxy 连续分整体对齐 GT"
        "（序一致、不高估），既压住高估、又不压低锚点，改的是对整个同类分布成立的重建方法。\n\n"
        "== 要压住高估（proxy > GT）==\n" + ("\n\n".join(over_b) if over_b else "（无）") + "\n\n"
        "== 不许压低（GT 高分锚点）==\n" + ("\n\n".join(anch_b) if anch_b else "（无）") + "\n\n"
        + (f"【上一轮被放行闸拒绝，修正后重交】\n{feedback}\n\n" if feedback else "")
        + f"【verifier.py 全文】\n```python\n{src}\n```\n\n"
        "【交付格式】文件较大时**强烈建议只交改动片段**，用若干搜索替换块（我会替你套用到原文，"
        "SEARCH 片段必须与原文逐字一致、且在全文中唯一）：\n"
        "===EDIT verifier.py===\n<<<SEARCH\n<原文里要改的那一小段，逐字复制>\n<<<REPLACE\n"
        "<替换后的新片段>\n<<<END\n"
        "（可给多个 ===EDIT=== 块。）也可以整文件重交：===FILE verifier.py===\\n```python\\n<完整文件>\\n```。"
        "无论哪种，只输出不超过 6 行说明 + 代码块，别的都不要。\n"
    )
    raw = H._call_model(prompt)
    try:
        (out_dir / "_repair_raw.txt").write_text(raw or "", encoding="utf-8")
    except Exception:
        pass
    files = {}
    for m in H._FILE_RE.finditer(raw):
        files[m.group("name").strip()] = m.group("body")
    edit_notes = []
    if not files:
        # Full-file echo missing/truncated → try the search-replace fallback onto frozen src.
        files, edit_notes = _apply_edits(raw, src)
    if not files:
        detail = ("empty model output (timeout/JSON-fail)" if not raw
                  else f"non-empty ({len(raw)} chars) but no ===FILE===/===EDIT=== applied; "
                       f"has'===FILE'={('===FILE' in raw)} has'===EDIT'={('===EDIT' in raw)} "
                       f"fences={raw.count('```')}; edits={'; '.join(edit_notes)}")
        return {"ok": False, "note": f"no revision parsed: {detail}", "raw": raw[:1200]}
    import ast
    written, errs = [], []
    for name, body in files.items():
        base = os.path.basename(name)
        if base not in ("verifier.py", "goal_reference.py"):
            continue
        try:
            ast.parse(body)
        except SyntaxError as e:
            errs.append(f"{base}: {e}")
            continue
        (out_dir / base).write_text(body, encoding="utf-8")
        written.append(base)
    if "verifier.py" not in written:
        return {"ok": False, "note": "verifier.py not written; " + "; ".join(errs), "raw": raw[:800]}
    return {"ok": True, "files": written, "note": "; ".join(errs) or "ok",
            "explanation": raw[:raw.find("===FILE")].strip()[:600]}


def sweep(ad, k_values, seed, frac, out_root):
    pool = ad.load_pool()
    calib, holdout = split_pool(pool, seed, frac)
    res = {"task": ad.name, "n_candidates": len(pool),
           "n_calib": len(calib), "n_holdout": len(holdout),
           "k_values": k_values, "seed": seed, "sweep": []}
    frozen_score = lambda c: c["proxy_value_frozen"]
    for K in k_values:
        row = {"K": K}
        if K == 0:
            row.update(gt_spent=0, shipped="frozen",
                       align=holdout_kpi(holdout, frozen_score))
        else:
            signals = spend_topk(calib, K)
            over = [s for s in signals if (s["proxy_value_frozen"] - s["gt_value"]) > H._ANCHOR_EPS]
            anch = [s for s in signals if s["gt_value"] >= H._ANCHOR_HI]
            row.update(gt_spent=len(signals), n_overest=len(over), n_anchors=len(anch))
            if not signals or not over:
                row.update(shipped="frozen", repair_ok=None,
                           align=holdout_kpi(holdout, frozen_score))
            else:
                out_dir = out_root / f"{ad.name}_contK{K}_seed{seed}" / "revised_bundle"
                out_dir.parent.mkdir(parents=True, exist_ok=True)
                rep = repair_with_gate(ad, signals, out_dir)
                gate = rep.get("gate") or {}
                row.update(repair_ok=rep["ok"], repair_note=rep.get("note"),
                           gate=gate, shipped=gate.get("shipped"))
                if rep.get("explanation"):
                    row["repair_explanation"] = rep["explanation"]
                if gate.get("shipped") == "revised":
                    row["align"] = holdout_kpi(holdout, lambda c: ad.score_live(out_dir, c))
                else:
                    row["align"] = holdout_kpi(holdout, frozen_score)
        a = row["align"]
        def f(x): return "n/a" if x is None else f"{x:.3f}"
        print(f"  {ad.name:<26} K={K} spent={row['gt_spent']} "
              f"over={row.get('n_overest',0)} anch={row.get('n_anchors',0)} "
              f"ship={row.get('shipped')} | n={a['n']} "
              f"Spearman={f(a['spearman'])} over(m/M)={f(a['overestimate_mean'])}/{f(a['overestimate_max'])} "
              f"MAE={f(a['mae'])} RMSE={f(a['rmse'])}", flush=True)
        res["sweep"].append(row)
    return res


# ============================================================ REACTOR adapter
class Reactor:
    name = "reactor-safety-control"
    TH = 1.06
    frozen_bundle = (REPO / ".famou/tbs-reruns-v84-dualshadow-c1"
                     "/tbs-reactor-safety-control-tbs-reruns-v84-dualshadow-c1"
                     "/famou/controller/verifier/bundle")
    task_root = (TBS / "tasks/engineering-sciences/chemical-engineering"
                 "/reactor-safety-control/environment")
    CACHE = CG / "reactor_proxy_cache"
    PROXY_VALUE_AXIS = "value.hidden_proxy_ratio"

    def _val(self, worst):
        if worst is None or not math.isfinite(worst):
            return 0.0
        return clip01((self.TH - worst) / self.TH)

    def _cand_root(self, sid):
        p = Path(sid)
        return p.parent.parent if (p.name == "submission" and p.parent.name == "app") else p

    def _cand_id(self, sid):
        parts = Path(sid).parts
        try:
            i = parts.index(".famou")
            rnd = next((p for p in parts if p.startswith("round_")), "")
            return f"{parts[i+1]}::{rnd}" if rnd else parts[i+1]
        except (ValueError, IndexError):
            return sid

    def _frozen_proxy(self, sid):
        """Cached frozen-bundle proxy value (reactor_proxy_cache); run if missing."""
        import hashlib
        key = hashlib.sha1(sid.encode()).hexdigest()[:16]
        cache = self.CACHE / f"{key}.json"
        if cache.exists():
            c = json.loads(cache.read_text())
            return (self._val(c["worst_proxy_ratio"]) if c.get("proxy_gate") else 0.0)
        return self._run(self.frozen_bundle, sid, cache)

    def _run(self, bundle, sid, cache=None):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory(prefix="reactor_px_") as td:
            scratch = os.path.join(td, "candidate")
            shutil.copytree(self._cand_root(sid), scratch)
            env = dict(os.environ); env["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                proc = subprocess.run(
                    [sys.executable, str(Path(bundle) / "verifier.py"),
                     "--candidate-root", scratch, "--task-root", str(self.task_root),
                     "--output-dir", td],
                    capture_output=True, text=True, timeout=1800, env=env)
                result = json.loads(proc.stdout)
            except Exception:
                if cache is not None:
                    cache.write_text(json.dumps({"proxy_gate": False, "worst_proxy_ratio": None, "status": "error"}))
                return 0.0
            checks = result.get("checks", [])
            gate = all(c.get("status") == "passed" for c in checks
                       if c.get("blocking") and c.get("id") != self.PROXY_VALUE_AXIS)
            worst = None
            ev = Path(td) / "evidence" / "hidden_proxy_scenarios.json"
            if ev.exists():
                rows = json.loads(ev.read_text())
                vals = [r.get("ratio_vs_calibrated_reference") for r in rows
                        if r.get("blocking") and r.get("ratio_vs_calibrated_reference") is not None]
                worst = max(vals) if vals else None
            if cache is not None:
                cache.write_text(json.dumps({"proxy_gate": bool(gate), "worst_proxy_ratio": worst,
                                             "status": result.get("status", "unknown")}))
            return self._val(worst) if gate else 0.0

    def load_pool(self):
        pool = []
        for line in (CG / "reactor_continuous_gt.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            scen = d.get("scenarios") or {}
            ratios = [v.get("ratio") for v in scen.values()
                      if isinstance(v, dict) and v.get("ratio") is not None]
            worst = max(ratios) if ratios else None
            gate = bool(d.get("gate_pass"))
            gv = self._val(worst) if gate else 0.0
            pool.append({
                "cand_id": self._cand_id(d["id"]),
                "sid": d["id"], "gt_value": gv, "gt_pass": bool(d.get("gt_pass")),
                "gt_rec": d, "proxy_value_frozen": self._frozen_proxy(d["id"]),
            })
        return pool

    def score_live(self, bundle_dir, cand):
        return self._run(bundle_dir, cand["sid"])

    def sig_block(self, s):
        d = s["gt_rec"]
        scen = d.get("scenarios") or {}
        worst = max((v.get("ratio") for v in scen.values()
                     if isinstance(v, dict) and v.get("ratio") is not None), default=None)
        return (f"候选 {s['cand_id']}: 官方 GT value={s['gt_value']:.3f}"
                f"（最差场景批次时间比值 worst_ratio={worst}，公开硬上限 1.06）;"
                f" 冻结 proxy value={s['proxy_value_frozen']:.3f}。")



# ============================================================ GUIDED-WAVE adapter (negative control)
class GuidedWave:
    name = "guided-wave-localization"
    PANEL_DIAG = 0.5657
    IMG = "<你的镜像仓库>/famou-public/tb-science-guided-wave-localization-verifier:official-v1"
    GW = (TBS / "tasks/engineering-sciences/mechanical-engineering/guided-wave-localization")
    frozen_bundle = (REPO / ".famou/tbs-reruns-v26"
                     "/tbs-guided-wave-localization-tbs-reruns-v26"
                     "/famou/controller/verifier/bundle")
    task_root = None

    def _val(self, max_m):
        if max_m is None or not math.isfinite(max_m):
            return 0.0
        return clip01(1.0 - max_m / self.PANEL_DIAG)

    def _cand_id(self, sid):
        parts = Path(sid).parts
        try:
            i = parts.index(".famou")
            rnd = next((p for p in parts if p.startswith("round_")), "")
            return f"{parts[i+1]}::{rnd}" if rnd else parts[i+1]
        except (ValueError, IndexError):
            return sid

    def load_pool(self):
        gt = {}
        for line in (CG / "guided_wave_continuous_gt.jsonl").read_text().splitlines():
            if line.strip():
                d = json.loads(line); gt[d["id"]] = d
        px = {}
        for line in (CG / "guided_wave_proxy_k0.jsonl").read_text().splitlines():
            if line.strip():
                d = json.loads(line); px[d["id"]] = d
        pool = []
        for sid in sorted(set(gt) & set(px)):
            g, p = gt[sid], px[sid]
            gmax = g.get("max_localization_error_m")
            pmax = p.get("proxy_max_m")
            if gmax is None or pmax is None:
                continue  # candidate crashed one side -> no joinable pair
            gv = self._val(gmax) if g.get("gate_pass", True) else 0.0
            pool.append({
                "cand_id": self._cand_id(sid), "sid": sid,
                "gt_value": gv, "gt_pass": bool(g.get("gt_pass")),
                "gt_rec": g, "proxy_rec": p,
                "proxy_value_frozen": self._val(pmax),
            })
        return pool

    def score_live(self, bundle_dir, cand):
        """Re-run the REVISED bundle on one candidate in the gw verifier image, parse
        per-case synthetic localization errors -> proxy value. ~1 min/candidate."""
        import subprocess, tempfile, re, ast
        sol = Path(cand["sid"])
        if not sol.exists():
            return None
        with tempfile.TemporaryDirectory(prefix="gw_live_") as td:
            tdp = Path(td)
            app = tdp / "app"; app.mkdir()
            shutil.copy(sol, app / "solution.py"); (app / "solution.py").chmod(0o644)
            pub = tdp / "pub"; pub.mkdir()
            for f in ("healthy_reference.npz", "reference_geometry.json"):
                shutil.copy(self.GW / "tests/data" / f, pub / f)
            outd = tdp / "out"; outd.mkdir()
            cmd = ["docker", "run", "--rm",
                   "-v", f"{Path(bundle_dir) / 'verifier.py'}:/proxy/verifier.py:ro",
                   "-v", f"{tdp}:{tdp}",
                   "-v", f"{pub}:/app/data:ro",
                   "-w", str(tdp),
                   "--entrypoint", "python3", self.IMG, "/proxy/verifier.py",
                   "--candidate-root", str(app), "--output-dir", str(outd)]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=400)
                res = json.loads(p.stdout)
            except Exception:
                return None
            vals = []
            for c in res.get("checks", []):
                if c.get("id") in ("localization_matched", "localization_perturbed"):
                    mo = re.search(r"per-case (\[[^\]]*\])", c.get("summary", ""))
                    if mo:
                        try:
                            vals += [float(x) for x in ast.literal_eval(mo.group(1))]
                        except Exception:
                            pass
            if not vals:
                return None
            return self._val(max(vals))

    def sig_block(self, s):
        g, p = s["gt_rec"], s["proxy_rec"]
        return (f"cand {s['cand_id']}: official GT value={s['gt_value']:.3f}"
                f" (hidden-plate max localization error {g.get('max_localization_error_m'):.4f} m,"
                f" public tolerance 0.020 m, public panel diagonal {self.PANEL_DIAG} m);"
                f" frozen proxy value={s['proxy_value_frozen']:.3f}"
                f" (synthetic-arena max localization error {p.get('proxy_max_m')} m).")


# ============================================================ TRAFFIC adapter (main replication, HEAVY)
class Traffic:
    name = "traffic-flux-inversion"
    IMG = "<你的镜像仓库>/famou-public/tb-science-traffic-flux-inversion-verifier:official-v1"
    frozen_bundle = CG / "traffic_proxy_bundle"
    task_root = CG / "traffic_proxy_taskroot"
    LIVE_TIMEOUT = 2400
    NSYN = 4

    def load_pool(self):
        gt = {}
        for line in (CG / "traffic_continuous_gt.jsonl").read_text().splitlines():
            if line.strip():
                d = json.loads(line); gt[d["cand"]] = d
        px = {}
        for line in (CG / "traffic_proxy_scores.jsonl").read_text().splitlines():
            if line.strip():
                d = json.loads(line); px[d["cand"]] = d
        pool = []
        for cid in sorted(set(gt) & set(px)):
            g, p = gt[cid], px[cid]
            gv = self._gt_value(g)
            pv = p.get("proxy_score")
            if gv is None or pv is None:
                continue
            pool.append({
                "cand_id": cid, "sid": g["id"], "gt_value": gv,
                "gt_pass": bool(g.get("gt_pass_official")),
                "gt_rec": g, "proxy_rec": p, "proxy_value_frozen": pv,
            })
        return pool

    def _gt_value(self, rec):
        vm = rec.get("value_metrics") or {}
        if not vm:
            return 0.0 if rec.get("metrics") is not None else None
        if not rec.get("gate_pass"):
            return 0.0
        return min(clip01(1.0 - v["err"]) for v in vm.values())

    def score_live(self, bundle_dir, cand):
        """Re-run the REVISED proxy bundle on one traffic candidate: re-execute the
        inverted solver on synthetic held-out systems, worst rel_l1 -> proxy value.
        ~15-20 min/candidate (runs the candidate's solver as an unprivileged user)."""
        import subprocess, tempfile
        sol = Path(cand["sid"])
        if not sol.exists():
            return None
        bundle_dir = Path(bundle_dir)
        with tempfile.TemporaryDirectory(prefix="traffic_live_") as td:
            w = Path(td)
            (w / "cand").mkdir(); (w / "out").mkdir()
            shutil.copy(sol, w / "cand" / "traffic_solver.py")
            cmd = ["docker", "run", "--rm",
                   "-v", f"{w}:{w}",
                   "-v", f"{bundle_dir}:{bundle_dir}:ro",
                   "-v", f"{self.task_root}:{self.task_root}:ro",
                   "-w", str(w),
                   "--entrypoint", "python3", self.IMG, str(bundle_dir / "verifier.py"),
                   "--candidate-root", str(w / "cand"),
                   "--task-root", str(self.task_root),
                   "--output-dir", str(w / "out"),
                   "--n-synthetic", str(self.NSYN)]
            try:
                subprocess.run(cmd, timeout=self.LIVE_TIMEOUT, capture_output=True, text=True)
            except Exception:
                return None
            ev = w / "out" / "evidence"
            fmt = beh = None
            rep = ev / "verifier_report.json"
            if rep.exists():
                try:
                    d = json.loads(rep.read_text())
                    fmt, beh = d.get("format_pass"), d.get("behavior_pass")
                except Exception:
                    pass
            worst = None
            if ev.exists():
                for f in sorted(ev.glob("system_*.json")):
                    if "visible" in f.stem:
                        continue
                    try:
                        sj = json.loads(f.read_text())
                    except Exception:
                        continue
                    sc = sj.get("scenarios") or sj.get("heldout") or []
                    rels = [x.get("rel_l1") for x in sc
                            if isinstance(x, dict) and x.get("rel_l1") is not None]
                    if rels:
                        worst = max(rels) if worst is None else max(worst, max(rels))
            gate = bool(fmt) and bool(beh)
            if not gate or worst is None:
                return 0.0
            return clip01(1.0 - worst)

    def sig_block(self, s):
        g, p = s["gt_rec"], s["proxy_rec"]
        gate_fail = g.get("gate_test_fail") or []
        # ode Fix-A 等价物:摊出候选在【公开】稀疏观测一致性门上的实测误差 vs 公开容差。
        # sparse_obs_* = 候选预测场对【公开稀疏观测】的重建相对误差(公开量、非隐藏 GT 场;
        # 容差取自公开判分脚本),红线干净。让修复模型一眼看出"这些候选在公开数据上差 4~5
        # 个数量级、代理却放行了"→ 该在代理硬门里补上对公开观测的可见一致性检查。不摊
        # value_metrics(隐藏场误差),避免把隐藏考法泄漏进代理。
        m = g.get("metrics") or {}
        pub = [(k, v.get("err"), v.get("threshold")) for k, v in m.items()
               if k.startswith("sparse_obs") and isinstance(v, dict) and v.get("err") is not None]
        pub.sort(key=lambda t: -(t[1] or 0.0))
        ev = ""
        if pub:
            tol = pub[0][2] or 2e-5
            n_fail = sum(1 for _, e, th in pub if e is not None and e > (th or 2e-5))
            worst = ", ".join(f"{k}={e:.3f}(×{e / (th or 2e-5):.0f}容差)" for k, e, th in pub[:4])
            ev = (f" 【公开可见一致性门 sparse_obs=预测对公开稀疏观测的相对误差,公开容差{tol:.0e}】"
                  f"{n_fail}/{len(pub)} 个公开场景不达标,最差:{worst}"
                  f"（这些是公开数据上就能自查的偏差,冻结代理却给了 {s['proxy_value_frozen']:.3f} 高分）。")
        return (f"cand {s['cand_id']}: official GT value={s['gt_value']:.3f}"
                f" (official gate_pass={g.get('gate_pass')}, failed public/hidden gates={gate_fail});"
                f" frozen proxy value={s['proxy_value_frozen']:.3f}"
                f" (proxy gate format={p.get('format_pass')} behavior={p.get('behavior_pass')},"
                f" synthetic worst rel_l1={p.get('proxy_worst_heldout')})." + ev)


ADAPTERS = {"reactor": Reactor, "gw": GuidedWave, "traffic": Traffic}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=list(ADAPTERS))
    ap.add_argument("--k-values", default="0,1,5,15")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--holdout-frac", type=float, default=0.4)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    ad = ADAPTERS[args.task]()
    ks = [int(x) for x in args.k_values.split(",")]
    out_root = CG / "coevolve_out"
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"# {ad.name} K-sweep ks={ks} seed={args.seed} frac={args.holdout_frac} model={H.MODEL}", file=sys.stderr)
    res = sweep(ad, ks, args.seed, args.holdout_frac, out_root)
    out = Path(args.out) if args.out else CG / f"{args.task}_coevolve_sweep.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\nwritten -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
