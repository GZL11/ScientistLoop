"""Plot independent GT-budget arms, preserving missing and supplemental results.

For this diagnostic chart, best-score is the maximum of valid research queries
and the independent final audit. It is not the protocol's final_score metric.
An unaccepted selection's supplemental audit is shown separately.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


ROOT = Path(__file__).resolve().parents[3]
BATCH = ROOT / ".famou/scimodelingbench-batches/blackbox-huayan-20261009"
OUT = Path(__file__).resolve().parent / "limited_gt_blackbox_20261009"
TASKS = ("tfbind8", "tfbind10_pho4", "cell_dag_nas")
TITLES = {
    "tfbind8": "八碱基转录因子结合优化（TFBind8）",
    "tfbind10_pho4": "十碱基转录因子结合优化（TFBind10 / PHO4）",
    "cell_dag_nas": "神经网络单元架构搜索（CellDAG-NAS）",
}
BLUE = "#1565c0"
ORANGE = "#d97706"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (BATCH / "results_after_recovery.csv").open(newline="") as stream:
        records = list(csv.DictReader(stream))
    plotted = []
    plt.rcParams.update({"font.family": "WenQuanYi Micro Hei", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False})
    for task in TASKS:
        rows = sorted((r for r in records if r["task"] == task), key=lambda r: int(r["k"]))
        used = {int(r["k"]): int(r["gt_used"]) for r in rows}
        xs, ys, supplements, missing = [], [], [], []
        for row in rows:
            k = int(row["k"])
            scores = [float(row[key]) for key in ("best_query_score", "final_score") if row[key]]
            best = max(scores) if scores else None
            extra = float(row["supplemental_score"]) if row["supplemental_score"] else None
            xs.append(k)
            ys.append(best if best is not None else float("nan"))
            if best is None:
                if extra is not None:
                    supplements.append((k, extra))
                else:
                    missing.append(k)
            plotted.append({**row, "best_score_including_final_audit": best,
                            "plot_value": best if best is not None else extra,
                            "point_type": "official" if best is not None else
                                          "supplemental" if extra is not None else "missing"})

        fig, ax = plt.subplots(figsize=(9, 6.5))
        fig.subplots_adjust(left=0.12, right=0.96, bottom=0.28, top=0.83)
        ax.plot(xs, ys, color=BLUE, linewidth=2, marker="o", markersize=7,
                label="有效评测最高分")
        for x, y in zip(xs, ys):
            if y == y:
                ax.annotate(f"{y:.5f}\n实际评测 {used[x]} 次", (x, y), xytext=(0, 11), textcoords="offset points",
                            ha="center", fontsize=10, color=BLUE)
        for x, y in supplements:
            ax.scatter([x], [y], marker="D", s=70, color=ORANGE, zorder=4,
                       label="补测分数（提交未被接受）")
            ax.annotate(f"{y:.5f}*\n实际评测 {used[x]} 次", (x, y), xytext=(0, 11), textcoords="offset points",
                        ha="center", fontsize=10, color=ORANGE)
        for x in missing:
            ax.text(x, 0.02, f"提交无效，无分数\n实际评测 {used[x]} 次", transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", color="#777777", fontsize=9)
        ax.set_title(TITLES[task], fontsize=17, weight="bold", pad=28)
        ax.text(0.5, 1.025, "黑盒优化｜研究预算 2 小时｜每个 k 独立运行 1 次",
                transform=ax.transAxes, ha="center", fontsize=10, color="#666666")
        ax.set_xlabel("k（研究阶段真实评测次数上限）")
        ax.set_ylabel("最高分数")
        ax.set_xticks([0, 1, 5, 20])
        ax.set_xlim(-1.3, 21.3)
        ax.margins(y=0.35)
        ax.yaxis.set_major_locator(MaxNLocator(6))
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        ax.grid(axis="y", alpha=0.22)
        ax.set_axisbelow(True)
        if supplements:
            ax.legend(loc="upper right", fontsize=8, frameon=False)
        fig.text(0.12, 0.17,
                 "最高分数：研究阶段有效真实评测分数与最终审计分数中的最大值。\n"
                 "实际评测次数仅指研究阶段 GT 调用，包含无效调用，不含最终审计或补测。\n"
                 "k=0 使用最终审计分数；各预算组独立运行，分数不保证随 k 单调上升。",
                 fontsize=9, color="#555555", va="top")
        if supplements:
            fig.text(0.12, 0.04,
                     "* k=5 研究阶段未调用 GT；超时后补测其指定文件，得到 −0.03571。\n"
                     "  该提交未被控制器接受，补测分数不计入正式最终分数比较。",
                     fontsize=9, color=ORANGE)
        for extension in ("png", "pdf"):
            fig.savefig(OUT / f"{task}_best_score_vs_k.{extension}", dpi=200)
        plt.close(fig)
    with (OUT / "plotted_scores.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(plotted[0]))
        writer.writeheader()
        writer.writerows(plotted)
    print(OUT)


if __name__ == "__main__":
    main()
