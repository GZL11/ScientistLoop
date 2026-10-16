#!/usr/bin/env python3
"""traffic K=0(未校准)三层对齐基线:join 连续 GT × 连续 proxy,算 §5 三层 KPI。

GT value 轴 = gate_pass × min_over_heldout(continuize(err)),held-out 族 =
hidden_smooth/hidden_shock/probes/transfer(官方隐藏数据)。
proxy score = proxy_gate × continuize(worst 合成 held-out rel_l1)(公开重建)。
两边同一把尺 continuize=clip(1-err,0,1)(红线③ 数学常量)。

三层(§5):①序对齐 Spearman ②不高估 (proxy-gt)+ mean/max ③数值 MAE/RMSE。
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
VALUE_FAMILIES = ("hidden_smooth", "hidden_shock", "probes", "transfer")


def continuize(err: float) -> float:
    return max(0.0, min(1.0, 1.0 - err))


def gt_score(rec: dict) -> float | None:
    vm = rec.get("value_metrics") or {}
    if not vm:
        # no value metrics emitted (integration/parse failure) → hard 0 if we know it ran
        return 0.0 if rec.get("metrics") is not None else None
    if not rec.get("gate_pass"):
        return 0.0
    return min(continuize(v["err"]) for v in vm.values())


def spearman(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    def rank(a):
        order = sorted(range(n), key=lambda i: a[i])
        r = [0.0]*n
        i = 0
        while i < n:
            j = i
            while j+1 < n and a[order[j+1]] == a[order[i]]:
                j += 1
            avg = (i+j)/2.0 + 1
            for k in range(i, j+1):
                r[order[k]] = avg
            i = j+1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    cov = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    vx = math.sqrt(sum((rx[i]-mx)**2 for i in range(n)))
    vy = math.sqrt(sum((ry[i]-my)**2 for i in range(n)))
    if vx == 0 or vy == 0:
        return None
    return cov/(vx*vy)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default=str(REPO / ".famou" / "continuous-gt" / "traffic_continuous_gt.jsonl"))
    ap.add_argument("--proxy", default=str(REPO / ".famou" / "continuous-gt" / "traffic_proxy_scores.jsonl"))
    ap.add_argument("--drop-double-zero", action="store_true",
                    help="exclude candidates where both gt=0 and proxy=0 (pure stubs)")
    args = ap.parse_args()

    gt = {json.loads(l)["cand"]: json.loads(l) for l in open(args.gt) if l.strip()}
    px = {json.loads(l)["cand"]: json.loads(l) for l in open(args.proxy) if l.strip()}
    common = sorted(set(gt) & set(px))
    print(f"gt={len(gt)} proxy={len(px)} common={len(common)}")

    rows = []
    for c in common:
        g = gt_score(gt[c])
        p = px[c].get("proxy_score")
        if g is None or p is None:
            continue
        rows.append((c, g, p))
    if args.drop_double_zero:
        rows = [r for r in rows if not (r[1] == 0.0 and r[2] == 0.0)]

    print(f"\n{'candidate':40s} {'gt':>7s} {'proxy':>7s} {'over':>7s}")
    for c, g, p in rows:
        print(f"{c:40s} {g:7.3f} {p:7.3f} {max(0.0,p-g):7.3f}")

    if len(rows) < 2:
        print("\n<2 joinable rows; cannot compute KPI"); return 0
    gs = [r[1] for r in rows]; ps = [r[2] for r in rows]
    over = [max(0.0, p-g) for _, g, p in rows]
    absd = [abs(p-g) for _, g, p in rows]
    rho = spearman(gs, ps)
    mae = sum(absd)/len(absd)
    rmse = math.sqrt(sum(d*d for d in absd)/len(absd))
    print(f"\n=== K=0 three-layer KPI (n={len(rows)}) ===")
    print(f"① Spearman(gt,proxy) = {rho if rho is None else round(rho,3)}   (higher=better)")
    print(f"② overestimate mean/max = {round(sum(over)/len(over),3)} / {round(max(over),3)}   (lower=better)")
    print(f"③ MAE / RMSE = {round(mae,3)} / {round(rmse,3)}   (lower=better)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
