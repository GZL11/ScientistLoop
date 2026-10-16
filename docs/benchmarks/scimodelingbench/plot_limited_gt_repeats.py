"""Plot all three repetitions, using best_score rather than reported_score."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


OUT = Path(__file__).resolve().parent / "limited_gt_blackbox_20261009"
BUDGETS = (0, 1, 5, 20)
TASKS = (
    ("tfbind8", "TFBind8 · 八碱基结合优化"),
    ("tfbind10_pho4", "TFBind10 / Pho4 · 十碱基结合优化"),
    ("cell_dag_nas", "CellDAG-NAS · 神经网络架构搜索"),
)
COLORS = ("#279F95", "#C96570", "#547FA9")
MARKERS = ("o", "s", "^")
# Offsets keep nearby and coincident points' GT counts legible.
LABEL_OFFSETS = {
    "tfbind8": (
        ((0, -20), (0, 13), (0, -20), (0, 13)),
        ((0, -20), (0, -20), (0, 14), (0, -20)),
        ((0, 13), (0, 13), (23, -2), (25, -2)),
    ),
    "tfbind10_pho4": (
        ((0, -20), (0, 14), (0, -24), (0, -20)),
        ((0, 13), (0, -20), (0, 13), (0, 13)),
        ((0, 13), (0, -20), (0, -20), (0, 13)),
    ),
    "cell_dag_nas": (
        ((-18, 19), (0, 0), (0, 14), (0, 14)),
        ((23, -2), (0, 0), (-23, 0), (0, 0)),
        ((0, -22), (0, 0), (12, -22), (0, -20)),
    ),
}


def main() -> None:
    with (OUT / "all_repeats_results.csv").open(newline="") as stream:
        records = list(csv.DictReader(stream))
    lookup = {(r["task"], int(r["k"]), int(r["repeat"])): r for r in records}
    expected = {(task, k, repeat) for task, _ in TASKS
                for k in BUDGETS for repeat in (1, 2, 3)}
    assert len(records) == 36 and set(lookup) == expected
    assert all(0 <= int(r["gt_used"]) <= int(r["k"]) for r in records)

    plt.rcParams.update({"font.family": "WenQuanYi Micro Hei", "font.size": 12,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.unicode_minus": False, "pdf.fonttype": 42,
                         "axes.edgecolor": "#A4ADB5", "axes.linewidth": 0.9,
                         "text.color": "#33434E", "axes.labelcolor": "#45545F",
                         "xtick.color": "#65717B", "ytick.color": "#65717B"})
    fig, axes = plt.subplots(1, 3, figsize=(20, 5.7))
    fig.subplots_adjust(left=0.055, right=0.982, bottom=0.15, top=0.87, wspace=0.24)

    counts = {"best": 0, "supplemental": 0, "missing": 0}
    for ax, (task, title) in zip(axes, TASKS):
        for repeat, color, marker in zip((1, 2, 3), COLORS, MARKERS):
            rows = [lookup[task, k, repeat] for k in BUDGETS]
            values = [float(r["best_score"]) if r["best_score"] else float("nan")
                      for r in rows]
            ax.plot(range(4), values, color=color, marker=marker, linewidth=2.7,
                    markersize=10 - repeat, markerfacecolor="white",
                    markeredgewidth=2.2, solid_capstyle="round", zorder=3 + repeat)
            if task == "cell_dag_nas":
                valid_positions = [x for x, row in enumerate(rows) if row["best_score"]]
                for left, right in zip(valid_positions, valid_positions[1:]):
                    if right - left > 1:
                        ax.plot([left, right], [values[left], values[right]],
                                color=color, linestyle=(0, (4, 3)), linewidth=2.1,
                                alpha=0.75, zorder=2)
            for x, row in enumerate(rows):
                suffix = ""
                score = values[x]
                if row["best_score"]:
                    counts["best"] += 1
                    if row["score_source"] == "best_research_query":
                        ax.scatter(x, values[x], marker="*", s=220, color=color,
                                   edgecolors="white", linewidths=0.6, zorder=9)
                        suffix = "★"
                elif row["supplemental_score"]:
                    counts["supplemental"] += 1
                    score = float(row["supplemental_score"])
                    ax.scatter(x, score, marker="D", s=75, facecolors="none",
                               edgecolors=color, linewidths=1.8, zorder=6)
                else:
                    counts["missing"] += 1
                    ax.text(x, 0.27 - repeat * 0.065,
                            f"{row['gt_used']} ×",
                            transform=ax.get_xaxis_transform(), ha="center",
                            color=color, fontsize=11, weight="bold",
                            bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                      edgecolor="#E4E8EC", linewidth=0.7))
                    continue
                ax.annotate(f"{row['gt_used']}{suffix}", (x, score),
                            xytext=LABEL_OFFSETS[task][repeat - 1][x],
                            textcoords="offset points", ha="center", va="center",
                            color=color, fontsize=12, weight="bold", zorder=10,
                            bbox=dict(boxstyle="round,pad=0.16", facecolor="white",
                                      edgecolor="#E4E8EC", linewidth=0.7, alpha=0.96),
                            arrowprops=dict(arrowstyle="-", color=color, alpha=0.35,
                                            linewidth=0.65, shrinkA=2, shrinkB=6))
        ax.set_title(title, fontsize=16, pad=25, weight="bold", color="#238F87")
        ax.set_xticks(range(4), [str(k) for k in BUDGETS])
        ax.set_xlim(-0.30, 3.38)
        ax.margins(y=0.20)
        ax.set_xlabel("GT 评测预算 k", labelpad=12, fontsize=13)
        ax.set_ylabel("最高分数", labelpad=10, fontsize=13)
        ax.yaxis.set_major_locator(MaxNLocator(5))
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        ax.grid(axis="y", color="#CDD5DB", linewidth=1, linestyle=":")
        ax.tick_params(axis="both", labelsize=11, length=3.5, pad=7)
        ax.set_axisbelow(True)

    # Explanatory caption lives below the image in the experiment report.
    assert counts == {"best": 31, "supplemental": 1, "missing": 4}, counts
    for extension in ("png", "pdf"):
        path = OUT / f"three_repeats_best_score_1x3_styled.{extension}"
        fig.savefig(path, dpi=220, facecolor="white", bbox_inches="tight", pad_inches=0.22)
        print(path)
    plt.close(fig)
    print(f"Plot accounting: {counts}")


if __name__ == "__main__":
    main()
