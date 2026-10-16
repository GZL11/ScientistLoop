#!/usr/bin/env python3
"""Regrade the reactor-safety-control candidate pool -> uncensored continuous GT.

Mirrors regrade_continuous_gt.py (ode) but adapts to reactor's execution model:
the submission is a controller.py + design_report.json graded by *running* the
controller against the trusted plant inside the verifier image. We emit only
(print-before-assert in test_outputs.py); nothing about the official 0/1 or
reward.txt changes.

Value axis = per-scenario batch-time ratio (batch_time_s / reference_time),
gated by safety (violations==0) + completion (finite batch time) + the
structural tests. Lower ratio is better.

Usage: python3 regrade_reactor_gt.py [--out PATH]
"""
from __future__ import annotations
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
IMAGE = "<你的镜像仓库>/famou-public/tb-science-reactor-safety-control-verifier:official-v1"

# Container-side driver: for each submission dir in the manifest, copy it into
# /app/submission, run the grader, parse METRIC lines + ctrf per-test status.
DRIVER = r'''
import json, re, shutil, subprocess, sys
from pathlib import Path
manifest = [l.strip() for l in Path("/driver/manifest.txt").read_text().splitlines() if l.strip()]
out = open("/out/reactor_continuous_gt.jsonl", "w")
SC = re.compile(r"^METRIC reactor_scenario=(\S+) violations=(\S+) max_t_k=(\S+) batch_time_s=(\S+) "
                r"conversion=(\S+) dosed_kg=(\S+) ratio=(\S+) ref_s=(\S+) pass=(\S+)$", re.M)
MEAN = re.compile(r"^METRIC reactor_mean_productivity_ratio=(\S+) limit=(\S+) pass=(\S+)$", re.M)
SUB = Path("/app/submission")
for i, cand in enumerate(manifest):
    src = Path(cand)
    for f in SUB.glob("*"):
        if f.is_file(): f.unlink()
        elif f.is_dir(): shutil.rmtree(f)
    ok = True
    for name in ("controller.py", "design_report.json"):
        s = src / name
        if not s.exists(): ok = False; break
        shutil.copy(s, SUB / name)
    rec = {"id": cand, "scenarios": {}, "mean_ratio": None, "error": None}
    if not ok:
        rec["error"] = "missing controller.py/design_report.json"
        out.write(json.dumps(rec) + "\n"); out.flush(); continue
    p = subprocess.run([sys.executable, "-m", "pytest", "/tests/test_outputs.py",
                        "--ctrf", "/tmp/ctrf.json", "-rA", "-q"],
                       capture_output=True, text=True)
    blob = p.stdout + "\n" + p.stderr
    for m in SC.finditer(blob):
        sid, viol, maxt, bt, conv, dosed, ratio, refs, passed = m.groups()
        rec["scenarios"][sid] = {
            "violations": int(float(viol)), "max_t_k": float(maxt),
            "batch_time_s": (float(bt) if bt not in ("inf", "nan") else None),
            "final_conversion": float(conv), "final_dosed_kg": float(dosed),
            "ratio": (float(ratio) if ratio not in ("inf", "nan") else None),
            "ref_s": float(refs), "pass": passed == "True"}
    mm = MEAN.search(blob)
    if mm: rec["mean_ratio"] = float(mm.group(1))
    # per-test status from structured ctrf (reliable)
    VALUE_PREFIXES = ("test_scenario_safe_complete_and_productive", "test_mean_productivity_ratio")
    failed = []
    try:
        ctrf = json.loads(Path("/tmp/ctrf.json").read_text())
        for t in ctrf.get("results", {}).get("tests", []):
            nm = (t.get("name") or "").split("::")[-1]
            if t.get("status") != "passed": failed.append(nm)
    except Exception as e:
        rec["error"] = f"ctrf parse failed: {e}"
    rec["failed_tests"] = failed
    # gate = every structural (non value-axis) test passed; safety+completion live
    # inside the per-scenario value test, so we read them from the METRIC lines.
    rec["gate_structural_failed"] = [n for n in failed if not n.startswith(VALUE_PREFIXES)]
    unsafe_or_incomplete = any((s["violations"] != 0 or s["batch_time_s"] is None)
                               for s in rec["scenarios"].values())
    rec["gate_pass"] = (not rec["gate_structural_failed"]) and bool(rec["scenarios"]) and not unsafe_or_incomplete
    rec["returncode"] = p.returncode
    rec["gt_pass"] = (p.returncode == 0)
    out.write(json.dumps(rec) + "\n"); out.flush()
    nsc = len(rec["scenarios"]); ok_sc = sum(1 for s in rec["scenarios"].values() if s["pass"])
    print(f"[{i+1}/{len(manifest)}] scen={nsc} pass={ok_sc} gate={rec['gate_pass']} gt_pass={rec['gt_pass']} rc={p.returncode} {cand}", file=sys.stderr)
out.close()
'''

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / ".famou" / "continuous-gt" / "reactor_continuous_gt.jsonl"))
    args = ap.parse_args()

    subs = []
    for rd in sorted(REPO.glob("tbs-reruns-*/tbs-reactor-*")):
        pass
    # bounded glob under .famou (avoid full-tree find)
    for rd in sorted((REPO / ".famou").glob("tbs-reruns-*/tbs-reactor-*")):
        for sub in sorted(rd.glob("artifacts/famou/surrogate/round_*/payload/app/submission")):
            if (sub / "controller.py").is_file() and (sub / "design_report.json").is_file():
                subs.append(str(sub))
    if not subs:
        print("no reactor submissions found", file=sys.stderr); return 2
    print(f"found {len(subs)} reactor submissions", file=sys.stderr)

    driver_dir = Path(tempfile.mkdtemp(prefix="regrade-reactor-"))
    (driver_dir / "driver.py").write_text(DRIVER)
    (driver_dir / "manifest.txt").write_text("\n".join(subs) + "\n")
    out_path = Path(args.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir = out_path.parent

    cmd = ["docker", "run", "--rm",
           "-v", f"{REPO}:{REPO}:ro",
           "-v", f"{driver_dir}:/driver:ro",
           "-v", f"{out_dir}:/out",
           "--entrypoint", "python3", IMAGE, "/driver/driver.py"]
    print("running container regrade ...", file=sys.stderr)
    rc = subprocess.run(cmd).returncode
    print(f"done rc={rc}; wrote {out_path}", file=sys.stderr)
    return rc

if __name__ == "__main__":
    sys.exit(main())
