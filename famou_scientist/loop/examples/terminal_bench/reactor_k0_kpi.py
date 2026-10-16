#!/usr/bin/env python3
"""Reactor K=0 三层 KPI (standalone, reactor-only).

不改 coevolve_proxy_repair.py。仅消费:
  - GT:  .famou/continuous-gt/reactor_continuous_gt.jsonl  (regrade_reactor_gt.py 产物)
  - Proxy: 冻结的 reactor proxy bundle verifier.py (K=0 = 未校准)

连续分口径(与 ode 一致):
  score = gate x value
  gate  = 硬 0 来源(format/behavior/safety/completion/structural),布尔
  value = 生产率轴归一 clip((1.06 - worst_ratio)/1.06, 0, 1)
          1.06 = TH_RATIO_MAX(public 每场景硬上限);floor 0 = 数学下界。

三层 KPI(设计 §5):
  ① 序对齐  Spearman(gt_value, proxy_value)          —— 最重要
  ② 不高估  overestimate = max(0, proxy - gt) 的 mean / max  —— 单边反 Goodhart
  ③ 数值对齐 MAE / RMSE
"""
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GT_JSONL = REPO / ".famou/continuous-gt/reactor_continuous_gt.jsonl"
CACHE_DIR = REPO / ".famou/continuous-gt/reactor_proxy_cache"
OUT_JSON = REPO / ".famou/continuous-gt/reactor_k0_kpi.json"

# 冻结的 proxy bundle(K=0 代表:未经任何 GT 校准的 AI 生成 proxy)
PROXY_VERIFIER = (REPO / ".famou/tbs-reruns-v84-dualshadow-c1"
                  "/tbs-reactor-safety-control-tbs-reruns-v84-dualshadow-c1"
                  "/famou/controller/verifier/bundle/verifier.py")
# public 环境(proxy 的"山寨考场"输入)
TASK_ROOT = Path("/path/to/workspace/opensource/terminal-bench-science"
                 "/tasks/engineering-sciences/chemical-engineering"
                 "/reactor-safety-control/environment")

TH_RATIO_MAX = 1.06  # public 每场景硬上限,归一化分母/参照点
PROXY_VALUE_AXIS = "value.hidden_proxy_ratio"  # proxy 生产率轴 check id


def clip01(x):
    return max(0.0, min(1.0, x))


def value_from_ratio(worst_ratio):
    """生产率轴归一。worst_ratio 越小越好;>=1.06 -> 0。"""
    if worst_ratio is None or not math.isfinite(worst_ratio):
        return 0.0
    return clip01((TH_RATIO_MAX - worst_ratio) / TH_RATIO_MAX)


# ---------------- GT ----------------
def load_gt():
    rows = []
    for line in GT_JSONL.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        scen = d.get("scenarios") or {}
        ratios = [v.get("ratio") for v in scen.values()
                  if isinstance(v, dict) and v.get("ratio") is not None]
        worst = max(ratios) if ratios else None
        gate = bool(d.get("gate_pass"))
        gt_value = value_from_ratio(worst) if gate else 0.0
        rows.append({
            "id": d["id"],
            "gate": gate,
            "worst_ratio": worst,
            "mean_ratio": d.get("mean_ratio"),
            "gt_pass": bool(d.get("gt_pass")),
            "gt_value": gt_value,
            "gt_score": gt_value if gate else 0.0,
        })
    return rows


# ---------------- Proxy (K=0, frozen) ----------------
def candidate_root_for(submission_id):
    """id 形如 .../payload/app/submission -> candidate-root=.../payload"""
    p = Path(submission_id)
    if p.name == "submission" and p.parent.name == "app":
        return p.parent.parent  # payload
    return p


def run_proxy(submission_id):
    """跑一次冻结 proxy;缓存到 CACHE_DIR。返回 (proxy_gate, worst_proxy_ratio, status)。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    import hashlib
    key = hashlib.sha1(submission_id.encode()).hexdigest()[:16]
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        return c["proxy_gate"], c["worst_proxy_ratio"], c["status"]

    cand_root = candidate_root_for(submission_id)
    import shutil
    with tempfile.TemporaryDirectory(prefix="reactor_proxy_") as td:
        # 关键:proxy 有 behavior.workspace_readonly 卫生检查(比对 candidate_root
        # 前后 tree digest)。就地跑会因 import controller.py 生成 __pycache__ 而
        # 误判失败 -> 必须拷到 scratch 再判,污染落到临时目录。
        scratch = os.path.join(td, "candidate")
        shutil.copytree(cand_root, scratch)
        # proxy worker 用 os.fork,而 PYTHONDONTWRITEBYTECODE 需在解释器启动时生效。
        # 官方容器在启动 python 前已导出它;host 直跑必须在父进程 env 里带上,
        # 否则 fork 出的 worker import controller.py 会写 __pycache__ -> 卫生检查误判。
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, str(PROXY_VERIFIER),
                 "--candidate-root", scratch,
                 "--task-root", str(TASK_ROOT),
                 "--output-dir", td],
                capture_output=True, text=True, timeout=1800, env=env)
        except subprocess.TimeoutExpired:
            res = {"proxy_gate": False, "worst_proxy_ratio": None,
                   "status": "timeout"}
            cache.write_text(json.dumps(res))
            return res["proxy_gate"], res["worst_proxy_ratio"], res["status"]

        try:
            result = json.loads(proc.stdout)
        except Exception:
            res = {"proxy_gate": False, "worst_proxy_ratio": None,
                   "status": "parse_error", "stderr": proc.stderr[-400:]}
            cache.write_text(json.dumps(res))
            return res["proxy_gate"], res["worst_proxy_ratio"], res["status"]

        # proxy gate = 除生产率轴外的所有 blocking check 均通过
        checks = result.get("checks", [])
        gate_ok = all(c.get("status") == "passed" for c in checks
                      if c.get("blocking") and c.get("id") != PROXY_VALUE_AXIS)

        # worst_proxy_ratio: 直接读 evidence,pass/fail 都稳(不依赖人读摘要正则)
        worst = None
        ev = Path(td) / "evidence" / "hidden_proxy_scenarios.json"
        if ev.exists():
            proxy_rows = json.loads(ev.read_text())
            vals = [r.get("ratio_vs_calibrated_reference") for r in proxy_rows
                    if r.get("blocking") and r.get("ratio_vs_calibrated_reference") is not None]
            worst = max(vals) if vals else None
        res = {"proxy_gate": bool(gate_ok), "worst_proxy_ratio": worst,
               "status": result.get("status", "unknown")}
        cache.write_text(json.dumps(res))
        return res["proxy_gate"], res["worst_proxy_ratio"], res["status"]


# ---------------- KPI ----------------
def spearman(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy)


def main():
    gt = load_gt()
    print(f"[gt] loaded {len(gt)} candidates from {GT_JSONL.name}", file=sys.stderr)
    joined = []
    for i, g in enumerate(gt, 1):
        pg, pr, st = run_proxy(g["id"])
        pv = value_from_ratio(pr) if pg else 0.0
        row = dict(g)
        row.update({"proxy_gate": pg, "worst_proxy_ratio": pr,
                    "proxy_status": st, "proxy_value": pv})
        joined.append(row)
        tag = Path(g["id"]).parts[-6] if len(Path(g["id"]).parts) >= 6 else g["id"]
        print(f"[{i}/{len(gt)}] gt_v={g['gt_value']:.3f} px_v={pv:.3f} "
              f"gate(gt={g['gate']},px={pg}) worst(gt={g['worst_ratio']},px={pr}) "
              f"[{st}] {tag}", file=sys.stderr)

    gtv = [r["gt_value"] for r in joined]
    pxv = [r["proxy_value"] for r in joined]
    n = len(joined)
    over = [max(0.0, p - g) for p, g in zip(pxv, gtv)]
    diff = [p - g for p, g in zip(pxv, gtv)]
    rho = spearman(gtv, pxv)
    kpi = {
        "n": n,
        "spearman": rho,
        "overestimate_mean": sum(over) / n if n else float("nan"),
        "overestimate_max": max(over) if over else float("nan"),
        "mae": sum(abs(d) for d in diff) / n if n else float("nan"),
        "rmse": math.sqrt(sum(d * d for d in diff) / n) if n else float("nan"),
        "gt_gate_pass": sum(1 for r in joined if r["gate"]),
        "proxy_gate_pass": sum(1 for r in joined if r["proxy_gate"]),
        "proxy_status_counts": {},
    }
    for r in joined:
        kpi["proxy_status_counts"][r["proxy_status"]] = \
            kpi["proxy_status_counts"].get(r["proxy_status"], 0) + 1

    OUT_JSON.write_text(json.dumps({"kpi": kpi, "rows": joined}, indent=2))
    print("\n===== REACTOR K=0 三层 KPI =====")
    print(f"n(joined)            = {n}")
    print(f"① Spearman           = {rho:.4f}")
    print(f"② overestimate mean  = {kpi['overestimate_mean']:.4f}")
    print(f"② overestimate max   = {kpi['overestimate_max']:.4f}")
    print(f"③ MAE                = {kpi['mae']:.4f}")
    print(f"③ RMSE               = {kpi['rmse']:.4f}")
    print(f"gate: gt_pass={kpi['gt_gate_pass']}  proxy_pass={kpi['proxy_gate_pass']}")
    print(f"proxy status         = {kpi['proxy_status_counts']}")
    print(f"written -> {OUT_JSON}")


if __name__ == "__main__":
    main()
