#!/usr/bin/env python3
"""K=0 冻结 proxy 打分器:对每个 guided-wave 候选跑同一版冻结 bundle verifier(山寨考场),
抽合成 tier(matched+perturbed)定位误差 → proxy 连续分。红线②清:合成真值由公开
healthy_reference 重建、非隐藏 GT;红线③清:归一尺度用公开 panel 对角线。"""
import argparse, json, os, subprocess, sys, tempfile, shutil
from pathlib import Path

REPO = Path("/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist")
GW = Path("/path/to/workspace/opensource/terminal-bench-science/tasks/engineering-sciences/mechanical-engineering/guided-wave-localization")
IMG = "<你的镜像仓库>/famou-public/tb-science-guided-wave-localization-verifier:official-v1"
# 冻结 proxy = 单一 canonical bundle 版本(v26),对所有候选一视同仁(K=0 要求 proxy 冻结)
BUNDLE = REPO / ".famou/tbs-reruns-v26/tbs-guided-wave-localization-tbs-reruns-v26/famou/controller/verifier/bundle/verifier.py"
OUT = REPO / ".famou/continuous-gt/guided_wave_proxy_k0.jsonl"

DRIVER = r'''
import json, subprocess, sys, shutil
from pathlib import Path
manifest = [l.strip() for l in Path("/driver/manifest.txt").read_text().splitlines() if l.strip()]
out = open("/out/guided_wave_proxy_k0.jsonl", "w")
appdir = Path("/work/app"); appdir.mkdir(parents=True, exist_ok=True)
for i, cand in enumerate(manifest):
    src = Path(cand)
    rec = {"id": cand, "proxy_matched_errors_m": None, "proxy_perturbed_errors_m": None,
           "proxy_max_m": None, "proxy_median_m": None, "proxy_status": None, "error": None}
    try:
        for f in appdir.glob("*"):
            f.unlink()
        if not src.exists():
            rec["error"] = "missing solution.py"; out.write(json.dumps(rec)+"\n"); out.flush(); continue
        shutil.copy(src, appdir/"solution.py"); (appdir/"solution.py").chmod(0o644)
        odir = Path(f"/work/out_{i}"); odir.mkdir(parents=True, exist_ok=True)
        p = subprocess.run([sys.executable, "/proxy/verifier.py",
                            "--candidate-root", str(appdir), "--output-dir", str(odir)],
                           capture_output=True, text=True, timeout=300)
        import re, ast, statistics as st
        try:
            res = json.loads(p.stdout)
            rec["proxy_status"] = res.get("status")
        except Exception:
            rec["proxy_status"] = "parse_fail"
            rec["error"] = "stdout not JSON; stderr: " + (p.stderr or "")[-300:]
            out.write(json.dumps(rec)+"\n"); out.flush()
            print(f"[{i+1}/{len(manifest)}] PARSEFAIL {cand}", file=sys.stderr)
            shutil.rmtree(odir, ignore_errors=True); continue
        m_pc, p_pc = [], []
        for c in res.get("checks", []):
            if c.get("id") in ("localization_matched","localization_perturbed"):
                mo = re.search(r"per-case (\[[^\]]*\])", c.get("summary",""))
                pc = ast.literal_eval(mo.group(1)) if mo else []
                if c["id"]=="localization_matched": m_pc = pc
                else: p_pc = pc
        rec["proxy_matched_errors_m"] = m_pc
        rec["proxy_perturbed_errors_m"] = p_pc
        allv = [float(x) for x in (m_pc + p_pc)]
        if allv:
            rec["proxy_max_m"] = max(allv)
            rec["proxy_median_m"] = st.median(allv)
        else:
            rec["error"] = "no per-case errors in summaries (candidate may have crashed in proxy runner)"
        shutil.rmtree(odir, ignore_errors=True)
    except Exception as ex:
        rec["error"] = f"{type(ex).__name__}: {ex}"
    out.write(json.dumps(rec)+"\n"); out.flush()
    print(f"[{i+1}/{len(manifest)}] proxy_max={rec['proxy_max_m']} status={rec['proxy_status']} {cand}", file=sys.stderr)
out.close()
'''

def main():
    pat = ".famou/tbs-reruns-*/tbs-guided-wave-*/artifacts/famou/surrogate/round_*/payload/app/solution.py"
    cands = sorted(str(p) for p in REPO.glob(pat) if p.exists())
    print(f"found {len(cands)} candidates; frozen proxy bundle = {BUNDLE.relative_to(REPO)}", file=sys.stderr)
    dd = Path(tempfile.mkdtemp(prefix="gw-proxy-driver-"))
    (dd/"driver.py").write_text(DRIVER)
    (dd/"manifest.txt").write_text("\n".join(cands)+"\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # public data at /app/data (healthy_reference + geometry are solver-visible/public)
    pubdata = Path(tempfile.mkdtemp(prefix="gw-pubdata-")); (pubdata).mkdir(exist_ok=True)
    shutil.copy(GW/"tests/data/healthy_reference.npz", pubdata/"healthy_reference.npz")
    shutil.copy(GW/"tests/data/reference_geometry.json", pubdata/"reference_geometry.json")
    cmd = ["docker","run","--rm",
           "-v", f"{REPO}:{REPO}:ro",
           "-v", f"{BUNDLE}:/proxy/verifier.py:ro",
           "-v", f"{pubdata}:/app/data:ro",
           "-v", f"{dd}:/driver:ro",
           "-v", f"{OUT.parent}:/out",
           "--tmpfs","/work",
           "--entrypoint","python3", IMG, "/driver/driver.py"]
    rc = subprocess.run(cmd).returncode
    print(f"done rc={rc}; wrote {OUT}", file=sys.stderr)
    return rc

if __name__ == "__main__":
    sys.exit(main())
