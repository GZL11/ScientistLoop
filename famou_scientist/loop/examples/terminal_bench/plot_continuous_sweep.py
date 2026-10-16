#!/usr/bin/env python3
"""连续 co-evolve K 扫描作图：读 .famou/continuous-gt/*_sweep.json，
单行 = 主 KPI Spearman（proxy↔GT 排序一致性）随 GT 预算 K，灰虚线叠 MAE。
x 轴取真实 K 数值，缺的档位留空。数据来源既有扫描产物,不重跑。"""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = ".famou/continuous-gt"
OUT = "docs/benchmarks/terminal_bench_science/figs/continuous_coevolve_sweep.png"

TASKS = [
    ("ode_coevolve_k5_fixed.json",   "ode-law-discovery",       "#2a8a5a"),
    ("reactor_coevolve_sweep.json",  "reactor-safety-control",  "#2a8a5a"),
    ("gw_coevolve_sweep.json",       "guided-wave-localization","#b23a3a"),
    ("traffic_coevolve_sweep.json",  "traffic-flux-inversion",  "#b23a3a"),
]
ALL_K = [0, 1, 5, 15]

def load(f):
    d = json.load(open(os.path.join(ROOT, f)))
    return d[0] if isinstance(d, list) else d

fig, axes = plt.subplots(1, len(TASKS), figsize=(20, 5))
fig.suptitle("Continuous co-evolve: proxy↔GT alignment (Spearman ρ) vs GT budget K", fontsize=16)

xpos = {k: i for i, k in enumerate(ALL_K)}
for col, (f, name, color) in enumerate(TASKS):
    d = load(f)
    sweep = d["sweep"]
    Ks = [s["K"] for s in sweep]
    sp = [s["align"]["spearman"] for s in sweep]
    mae = [s["align"]["mae"] for s in sweep]
    xs = [xpos[k] for k in Ks]

    ax = axes[col]
    ax.plot(xs, sp, "-o", color=color, lw=2.6, ms=8, label="Spearman ρ (proxy vs GT)")
    ax.axhline(0, color="#999", lw=0.8, ls=":")
    ax.set_ylim(-0.3, 1.05)
    ax.set_xticks(list(xpos.values())); ax.set_xticklabels([str(k) for k in ALL_K])
    ax.set_xlim(-0.4, len(ALL_K) - 0.6)
    ax.set_title(name, fontsize=13)
    ax.set_xlabel("GT budget K")
    if col == 0:
        ax.set_ylabel("Spearman ρ")
    ax2 = ax.twinx()
    ax2.plot(xs, mae, "--s", color="#888", lw=1.6, ms=6, label="MAE")
    ax2.set_ylim(0, 0.6)
    if col == len(TASKS) - 1:
        ax2.set_ylabel("MAE (proxy − GT)", color="#666")
    for x, s, y in zip(xs, sweep, sp):
        ax.annotate(s.get("shipped", ""), (x, y), textcoords="offset points",
                    xytext=(0, 9), fontsize=7, color="#555", ha="center")
    lines = ax.get_lines()[:1] + ax2.get_lines()[:1]
    ax.legend(lines, [l.get_label() for l in lines], fontsize=8, loc="lower right")

fig.tight_layout(rect=[0, 0, 1, 0.93])
fig.savefig(OUT, dpi=130, bbox_inches="tight")
print("wrote", OUT)
