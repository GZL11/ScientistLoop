"""Plot cumulative best official score against submission number.

For each task, the run with the highest final score is selected.  The plotted
series is then reconstructed from that run's official evaluator artifacts.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


TASK_FORMS = {
    "tfbind8": "black-box optimization",
    "tfbind10_pho4": "black-box optimization",
    "cell_dag_nas": "black-box optimization",
    "superconductor": "candidate-pool ranking",
    "hopper_controller": "candidate-pool ranking",
    "utr_mrl_egfp_unmodified": "candidate-pool ranking",
    "gfp": "candidate-pool ranking",
    "drugmatrix_mchc": "candidate-pool ranking",
    "drugmatrix_mch": "candidate-pool ranking",
    "drugmatrix_creatinine": "candidate-pool ranking",
    "drugmatrix_sodium": "candidate-pool ranking",
    "drugmatrix_chloride": "candidate-pool ranking",
    "drugmatrix_phosphorus": "candidate-pool ranking",
}


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = ROOT / ".famou" / "scimodelingbench-fmjob-runs"
OUT_DIR = Path(__file__).resolve().parent
PNG = OUT_DIR / "submission_best_score_curves.png"
CSV = OUT_DIR / "submission_best_score_curves.csv"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_records(run: Path) -> list[dict]:
    """Read valid, deduplicated official evaluations in time order."""
    records: dict[str, dict] = {}
    for path in (run / "artifacts" / "evaluator_scores").glob("official_eval_*.json"):
        value = read_json(path)
        if value.get("valid") is not True:
            continue
        metrics = value.get("metrics") or value.get("official_metrics") or {}
        score = metrics.get("score")
        if not isinstance(score, (int, float)):
            continue
        request_id = str(value.get("request_id") or path.name)
        # A resumed run can retain a second copy of the same response.
        records[request_id] = {
            "request_id": request_id,
            "score": float(score),
            "primary_metric": metrics.get("primary_metric"),
            "evaluated_at": int(value.get("evaluated_at") or 0),
            "artifact": str(value.get("artifact") or value.get("metadata", {}).get("artifact") or ""),
        }
    return sorted(records.values(), key=lambda item: (item["evaluated_at"], item["request_id"]))


def main() -> None:
    selected: dict[str, tuple[Path, list[dict], float]] = {}
    for run in sorted(RUN_ROOT.iterdir()):
        summary_path = run / "controller" / "run_summary.json"
        if not run.is_dir() or not summary_path.is_file():
            continue
        summary = read_json(summary_path)
        task = str(summary.get("task_id") or "")
        records = run_records(run)
        if not task or not records:
            continue
        final_score = max(item["score"] for item in records)
        previous = selected.get(task)
        if previous is None or final_score > previous[2]:
            selected[task] = (run, records, final_score)

    ordered = sorted(selected.items())
    with CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["task_id", "task_form", "selected_run", "submission_number", "score", "best_score_so_far", "primary_metric"])
        for task, (run, records, _) in ordered:
            task_form = TASK_FORMS[task]
            best = float("-inf")
            for number, item in enumerate(records, 1):
                best = max(best, item["score"])
                writer.writerow([task, task_form, run.name, number, f"{item['score']:.12g}", f"{best:.12g}", item.get("primary_metric") or ""])

    columns, rows = 4, 4
    fig, axes = plt.subplots(rows, columns, figsize=(17, 14), constrained_layout=True)
    axes = list(axes.flat)
    colors = {"black-box optimization": "#1565c0", "candidate-pool ranking": "#d97706"}
    for ax in axes[len(ordered):]:
        ax.axis("off")
    fig.legend(
        handles=[
            Line2D([0], [0], color=color, marker="o", linewidth=2,
                   label=("Black-box optimization" if form == "black-box optimization" else "Candidate-pool ranking"))
            for form, color in colors.items()
        ],
        loc="lower center", bbox_to_anchor=(0.5, 0.005), ncol=2,
        frameon=False, fontsize=11,
    )
    for ax, (task, (run, records, _)) in zip(axes, ordered):
        task_form = TASK_FORMS[task]
        color = colors[task_form]
        best_values: list[float] = []
        best = float("-inf")
        for item in records:
            best = max(best, item["score"])
            best_values.append(best)
        x = list(range(1, len(records) + 1))
        ax.plot(x, best_values, marker="o", markersize=4, linewidth=1.8, color=color)
        ax.scatter([x[-1]], [best_values[-1]], color=color, s=35, zorder=3)
        ax.set_title(f"{task}\n{run.name}", fontsize=9)
        ax.set_xlabel("Official submissions", fontsize=8)
        ax.set_ylabel("Best score so far", fontsize=8)
        ax.grid(True, alpha=0.25)
        ax.set_xlim(left=1)
        ax.text(
            0.98,
            0.06,
            f"n={len(records)}, max={best_values[-1]:.4f}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none"},
        )
    fig.suptitle(
        "SciModelingBench: cumulative best score by official submission\n"
        "Selected run per task = highest historical final score",
        fontsize=15,
    )
    fig.savefig(PNG, dpi=180, bbox_inches="tight")
    print(f"wrote {PNG}")
    print(f"wrote {CSV}")
    for task, (run, records, final_score) in ordered:
        print(f"{task}: {run.name} | submissions={len(records)} | max={final_score:.6f}")


if __name__ == "__main__":
    main()
