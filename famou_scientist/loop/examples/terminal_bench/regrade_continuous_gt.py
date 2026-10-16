#!/usr/bin/env python3
"""重判 ode 候选池,抽无删失连续真值(standard/stress/vector_field)。

用法:
    python3 regrade_continuous_gt.py [--task ode] [--out PATH]

做法:定深 glob 枚举 .famou/tbs-reruns-*/tbs-<task>-*/artifacts/famou/surrogate/
round_*/payload/results;起单个改造后 verifier 容器,容器内循环把每个候选 copy
进 /results 跑 test_outputs.py,从 stdout grep `^METRIC` 行 → 每候选一份连续 GT。
只加输出、不改官方 0/1(见 docs/tbs-continuous-coevolve.md §11)。"""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
IMAGE = "<你的镜像仓库>/famou-public/tb-science-{task}-law-discovery-verifier:official-v1"
IMAGE_BY_TASK = {"ode": "<你的镜像仓库>/famou-public/tb-science-ode-law-discovery-verifier:official-v1"}

# 容器内驱动:读挂进来的 manifest(每行一个候选 results 目录),逐个重判抽 METRIC。
DRIVER = r'''
import json, re, shutil, subprocess, sys
from pathlib import Path
manifest = [l.strip() for l in Path("/driver/manifest.txt").read_text().splitlines() if l.strip()]
out = open("/out/continuous_gt.jsonl", "w")
METRIC = re.compile(r"^METRIC (\S+)=(\S+) threshold=(\S+) pass=(\S+)$", re.M)
for i, cand in enumerate(manifest):
    src = Path(cand)
    res = Path("/results")
    for f in res.glob("*"):
        f.unlink()
    ok = True
    for name in ("equations.json", "predictions.csv", "report.md"):
        s = src / name
        if not s.exists():
            ok = False; break
        shutil.copy(s, res / name)
    rec = {"id": cand, "metrics": {}, "error": None}
    if not ok:
        rec["error"] = "missing input files"
        out.write(json.dumps(rec) + "\n"); continue
    p = subprocess.run([sys.executable, "-m", "pytest", "/tests/test_outputs.py",
                        "--ctrf", "/tmp/ctrf.json", "-rA", "-q"],
                       capture_output=True, text=True)
    blob = p.stdout + "\n" + p.stderr
    for m in METRIC.finditer(blob):
        name, err, thr, passed = m.group(1), m.group(2), m.group(3), m.group(4)
        rec["metrics"][name] = {"err": float(err), "threshold": float(thr), "pass": passed == "True"}
    # per-test status from structured ctrf.json (reliable; text scraping missed the
    # `tests/test_outputs.py::` node prefix) → separate gate vs value tests
    VALUE_TESTS = {"test_standard_rollout_nrmse", "test_stress_rollout_nrmse", "test_vector_field_error"}
    failed = []
    try:
        ctrf = json.loads(Path("/tmp/ctrf.json").read_text())
        for t in ctrf.get("results", {}).get("tests", []):
            nm = (t.get("name") or "").split("::")[-1]
            if t.get("status") not in ("passed",):
                failed.append(nm)
    except Exception as e:
        rec["error"] = f"ctrf parse failed: {e}"
    rec["failed_tests"] = failed
    # gate = 所有非指标(格式/行为/复杂度)测试都通过;单看这些才是硬约束
    rec["gate_failed"] = [n for n in failed if n not in VALUE_TESTS]
    rec["gate_pass"] = not rec["gate_failed"]
    rec["returncode"] = p.returncode
    rec["gt_pass"] = bool(rec["metrics"]) and all(v["pass"] for v in rec["metrics"].values()) and rec["gate_pass"]
    # 官方要求三轴齐全且全 pass;缺轴(积分崩)算硬失败
    rec["all_axes_present"] = len(rec["metrics"]) == 3
    if not rec["all_axes_present"] and not rec["metrics"]:
        rec["error"] = "no METRIC emitted (likely integration/parse failure)"
    out.write(json.dumps(rec) + "\n"); out.flush()
    print(f"[{i+1}/{len(manifest)}] axes={len(rec['metrics'])} gate_pass={rec['gate_pass']} gt_pass={rec.get('gt_pass')} rc={p.returncode} {cand}", file=sys.stderr)
out.close()
'''

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="ode")
    ap.add_argument("--out", default=str(REPO / ".famou" / "continuous-gt" / "ode_continuous_gt.jsonl"))
    args = ap.parse_args()
    image = IMAGE_BY_TASK.get(args.task) or IMAGE.format(task=args.task)

    pat = f".famou/tbs-reruns-*/tbs-{args.task}-*/artifacts/famou/surrogate/round_*/payload/results"
    cands = sorted(str(p) for p in REPO.glob(pat)
                   if (p / "equations.json").exists() and (p / "predictions.csv").exists() and (p / "report.md").exists())
    if not cands:
        print(f"no candidates matched {pat}", file=sys.stderr); return 2
    print(f"found {len(cands)} candidates", file=sys.stderr)

    driver_dir = Path(tempfile.mkdtemp(prefix="regrade-driver-"))
    (driver_dir / "driver.py").write_text(DRIVER)
    (driver_dir / "manifest.txt").write_text("\n".join(cands) + "\n")
    out_path = Path(args.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir = out_path.parent

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{REPO}:{REPO}:ro",
        "-v", f"{driver_dir}:/driver:ro",
        "-v", f"{out_dir}:/out",
        "--entrypoint", "python3", image, "/driver/driver.py",
    ]
    print("running container regrade ...", file=sys.stderr)
    rc = subprocess.run(cmd).returncode
    produced = out_dir / "continuous_gt.jsonl"
    if produced.exists() and produced.resolve() != out_path.resolve():
        produced.replace(out_path)
    print(f"done rc={rc}; wrote {out_path}", file=sys.stderr)
    return rc

if __name__ == "__main__":
    sys.exit(main())
