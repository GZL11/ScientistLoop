#!/usr/bin/env python3
"""对 traffic 候选池跑**代理**打分(离线),抽连续代理分,供 K=0 三层对齐用。

与 GT(regrade_traffic_gt.py,官方隐藏数据)对偶:代理**拿不到隐藏数据**,它用
公开 episodes.npz 重建一套近似参考 + 生成合成系统(syn_*),在合成留出场景上算
rel_l1(红线②:只用公开重建,不一律拒/放行;红线③:continuize=clip(1-rel_l1,0,1)
数学常量,与 GT 同一把尺)。用已冻结的 v86 dual_shadow proxy bundle。

每候选起一个容器跑 bundle/verifier.py --candidate-root <cand> --task-root <task>,
解析 out/evidence/system_*.json 的 scenarios[].rel_l1 → 每合成系统最差 → 全系统最差
→ proxy_value = continuize(worst)。同时记录 format/behavior/value_proxy 门。

用法: python3 regrade_traffic_proxy.py [--conc 3] [--timeout 2400] [--nsyn 4]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
IMAGE = "<你的镜像仓库>/famou-public/tb-science-traffic-flux-inversion-verifier:official-v1"
BUNDLE = REPO / ".famou" / "continuous-gt" / "traffic_proxy_bundle"
TASKROOT = REPO / ".famou" / "continuous-gt" / "traffic_proxy_taskroot"


def cand_id(solver_path: Path) -> str:
    parts = solver_path.parts
    ver = next((p for p in parts if p.startswith("tbs-reruns-")), "unknown")
    rnd = next((p for p in parts if p.startswith("round_")), "round_?")
    return f"{ver}__{rnd}"


def _worst_heldout(sysjson: dict):
    """最差 held-out rel_l1(排除 visible 系统,它天然=0)。返回 (worst, n_ok, n_total)."""
    sc = sysjson.get("scenarios") or sysjson.get("heldout") or []
    rels = [x.get("rel_l1") for x in sc if isinstance(x, dict) and x.get("rel_l1") is not None]
    n_total = len([x for x in sc if isinstance(x, dict)])
    if not rels:
        return None, 0, n_total
    return max(rels), len(rels), n_total


def grade_one(solver: Path, workbase: Path, timeout: int, nsyn: int) -> dict:
    cid = cand_id(solver)
    w = workbase / cid
    (w / "cand").mkdir(parents=True, exist_ok=True)
    (w / "out").mkdir(parents=True, exist_ok=True)
    shutil.copy(solver, w / "cand" / "traffic_solver.py")
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{w}:{w}",
        "-v", f"{BUNDLE}:{BUNDLE}:ro",
        "-v", f"{TASKROOT}:{TASKROOT}:ro",
        "-w", str(w),
        "--entrypoint", "python3", IMAGE, str(BUNDLE / "verifier.py"),
        "--candidate-root", str(w / "cand"),
        "--task-root", str(TASKROOT),
        "--output-dir", str(w / "out"),
        "--n-synthetic", str(nsyn),
    ]
    rec = {"id": str(solver), "cand": cid, "error": None,
           "syn_worst": {}, "proxy_worst_heldout": None, "proxy_value": None,
           "format_pass": None, "behavior_pass": None, "value_proxy_pass": None,
           "status": None}
    try:
        subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        rec["error"] = f"container timeout ({timeout}s)"
    ev = w / "out" / "evidence"
    # aggregate report (gates)
    rep = ev / "verifier_report.json"
    if rep.exists():
        try:
            d = json.loads(rep.read_text())
            rec["status"] = d.get("status")
            rec["format_pass"] = d.get("format_pass")
            rec["behavior_pass"] = d.get("behavior_pass")
            rec["value_proxy_pass"] = d.get("value_proxy_pass")
        except Exception as e:
            rec["error"] = (rec["error"] or "") + f" report parse: {e}"
    # per-system held-out rel_l1 (synthetic only; skip visible)
    worst_all = None
    if ev.exists():
        for f in sorted(ev.glob("system_*.json")):
            name = f.stem.replace("system_", "")
            if "visible" in name:
                continue
            try:
                sj = json.loads(f.read_text())
            except Exception:
                continue
            worst, n_ok, n_tot = _worst_heldout(sj)
            fit_err = sj.get("fit_error") or sj.get("import_error")
            rec["syn_worst"][name] = {"worst_rel_l1": worst, "n_ok": n_ok,
                                       "n_total": n_tot, "fit_error": bool(fit_err)}
            if worst is not None:
                worst_all = worst if worst_all is None else max(worst_all, worst)
    rec["proxy_worst_heldout"] = worst_all
    if worst_all is not None:
        rec["proxy_value"] = max(0.0, min(1.0, 1.0 - worst_all))
    # proxy gate: format+behavior+value_proxy all pass → proxy_score = gate×value
    gate = bool(rec["format_pass"]) and bool(rec["behavior_pass"])
    rec["proxy_gate_pass"] = gate
    rec["proxy_score"] = (rec["proxy_value"] if (gate and rec["proxy_value"] is not None) else 0.0)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conc", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--nsyn", type=int, default=4)
    ap.add_argument("--out", default=str(REPO / ".famou" / "continuous-gt" / "traffic_proxy_scores.jsonl"))
    args = ap.parse_args()
    if not BUNDLE.exists() or not TASKROOT.exists():
        print(f"missing bundle {BUNDLE} or taskroot {TASKROOT}", file=sys.stderr); return 2

    pat = ".famou/tbs-reruns-*/tbs-traffic-*/artifacts/famou/surrogate/round_*/payload/app/traffic_solver.py"
    cands = sorted(REPO.glob(pat))
    if not cands:
        print(f"no candidates matched {pat}", file=sys.stderr); return 2
    print(f"found {len(cands)} candidates; conc={args.conc} nsyn={args.nsyn}", file=sys.stderr)

    workbase = Path(tempfile.mkdtemp(prefix="traffic-proxy-"))
    out_path = Path(args.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.conc) as ex:
        futs = {ex.submit(grade_one, c, workbase, args.timeout, args.nsyn): c for c in cands}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result(); results.append(rec); done += 1
            print(f"[{done}/{len(cands)}] {rec['cand']} proxy_worst={rec.get('proxy_worst_heldout')} "
                  f"proxy_value={rec.get('proxy_value')} gate={rec.get('proxy_gate_pass')} "
                  f"proxy_score={rec.get('proxy_score')} err={rec.get('error')}", file=sys.stderr)
    results.sort(key=lambda r: r["cand"])
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {out_path} ({len(results)} records); work in {workbase}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
