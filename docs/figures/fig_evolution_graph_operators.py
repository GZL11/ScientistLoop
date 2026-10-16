#!/usr/bin/env python3
"""Figure 2 — the solution-evolution graph and its three operators.

Publication schematic, drawn in the style of AIDE's solution tree (Jiang et
al., arXiv:2502.13138, Fig. 1): every node is one complete solution, every
directed edge is one operator application, and the graph grows left to right.

The substantive difference from AIDE is drawn deliberately. AIDE's `draft /
debug / improve` each take exactly one parent, so its search structure is a
*tree*. Our `cross` takes two or more scored parents, so ours is a **DAG** —
node 0005 below has two incoming edges. That is why the on-disk index needs an
explicit `parents` list rather than a single `parent_id`, and why a lineage
view has to list root-to-leaf chains rather than print a tree.

`ensemble` (a fourth operator, which reuses the *trained artifacts* of its
parents instead of their mechanisms) is out of scope for this figure.

The worked example is the one documented in `prompts/cli_agents/
idea_agent_v9.md`; it is illustrative, not a transcript of a single run.

Encoding, kept to one dimension each so the figure survives greyscale print:
  * edge colour AND dash pattern  -> which operator produced the node
  * node border: solid = it ran; dashed = no result yet
  * node border weight: heavy = best score so far

    python3 fig_evolution_graph_operators.py       # writes PDF + PNG alongside
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ── house style ────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Helvetica", "Arial"],
    "pdf.fonttype": 42,   # TrueType, not Type-3: required by most journals
    "ps.fonttype": 42,
})

FS_ID, FS_MECH, FS_OUT, FS_LEG = 8.0, 6.5, 6.8, 6.5

# Okabe–Ito, three well-separated hues. Colour names the operator, nothing else.
C_INNOVATE = "#CC79A7"   # reddish purple
C_EXPLOIT = "#0072B2"    # blue
C_CROSS = "#E69F00"      # orange
INK = "#1A1A1A"
GREY = "#4D4D4D"

# Dash patterns carry the same information as the hues, for greyscale print.
STYLE = {
    "innovate": (C_INNOVATE, (0, (1, 1.6))),
    "exploit": (C_EXPLOIT, "solid"),
    "cross": (C_CROSS, (0, (4, 1.8))),
}

fig = plt.figure(figsize=(6.9, 4.2))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")

NW, NH = 20.0, 17.0          # node box; three depth columns at x = 30, 55, 80
PAD = 0.3                    # `boxstyle="round,pad=..."` draws outside the rect
GAP = 1.2                    # breathing room between an arrow tip and a border
HEAD = 3.5                   # length of the solid arrowhead segment

centres: dict[str, tuple[float, float]] = {}
halfdims: dict[str, tuple[float, float]] = {}


def node(key, x, y, mech, outcome, *, ran=True, best=False):
    """One solution. Address on top, mechanism in the middle, result at the
    bottom — the same three things the on-disk index prints per solution."""
    ax.add_patch(FancyBboxPatch(
        (x - NW / 2, y - NH / 2), NW, NH,
        boxstyle=f"round,pad={PAD}", linewidth=1.8 if best else 1.0,
        edgecolor=INK, facecolor="white", zorder=2,
        linestyle="solid" if ran else (0, (3, 2)),
    ))
    centres[key] = (x, y)
    halfdims[key] = (NW / 2 + PAD, NH / 2 + PAD)
    ax.text(x, y + 5.6, key, ha="center", va="center", fontsize=FS_ID,
            color=INK, zorder=3)
    ax.text(x, y + 0.2, mech, ha="center", va="center", fontsize=FS_MECH,
            color=GREY, zorder=3, linespacing=1.3)
    ax.text(x, y - 5.9, outcome, ha="center", va="center", fontsize=FS_OUT,
            color=INK if ran else GREY, zorder=3)
    if best:
        ax.text(x, y + NH / 2 + 2.6, "best so far", ha="center", va="center",
                fontsize=FS_LEG, color=GREY, zorder=3)


def _border(key, tx, ty):
    """Where the centre-to-(tx, ty) ray leaves the node's rectangle."""
    cx, cy = centres[key]
    hw, hh = halfdims[key]
    dx, dy = tx - cx, ty - cy
    s = min(hw / abs(dx) if dx else 1e9, hh / abs(dy) if dy else 1e9)
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    return cx + dx * s + dx / n * GAP, cy + dy * s + dy / n * GAP


def _stroke(a, b, colour, dash):
    """Dashed shaft, solid head. Drawing them as one patch makes matplotlib
    dash the arrowhead outline too, which reads as a broken tip in print."""
    (ax_, ay_), (bx, by) = a, b
    n = ((bx - ax_) ** 2 + (by - ay_) ** 2) ** 0.5 or 1.0
    ux, uy = (bx - ax_) / n, (by - ay_) / n
    joint = (bx - ux * HEAD, by - uy * HEAD)
    if dash != "solid":
        ax.add_patch(FancyArrowPatch(
            a, joint, arrowstyle="-", linewidth=1.1, color=colour,
            linestyle=dash, zorder=1, shrinkA=0, shrinkB=0))
        a = (bx - ux * HEAD * 1.15, by - uy * HEAD * 1.15)
    ax.add_patch(FancyArrowPatch(
        a, b, arrowstyle="-|>", mutation_scale=9, linewidth=1.1, color=colour,
        zorder=1, shrinkA=0, shrinkB=0))


def edge(src, dst, op):
    """One operator application, clipped to both node borders."""
    colour, dash = STYLE[op]
    _stroke(_border(src, *centres[dst]), _border(dst, *centres[src]),
            colour, dash)


# ── the graph ──────────────────────────────────────────────────────────────
# ROOT is not a solution; it is the sentinel every `innovate` points at, so
# that "no parent" and "parent list omitted" cannot be confused on disk.
ax.add_patch(FancyBboxPatch((1.5, 47.5), 11, 7, boxstyle=f"round,pad={PAD}",
                            linewidth=1.0, edgecolor=GREY, facecolor="white",
                            zorder=2))
centres["ROOT"] = (7, 51)
halfdims["ROOT"] = (5.5 + PAD, 3.5 + PAD)
ax.text(7, 51, "ROOT", ha="center", va="center", fontsize=FS_ID, color=GREY,
        zorder=3)

node("0001", 30, 74, "energy-grid\ndescriptors + GBDT", "−0.0422")
node("0007", 30, 28, "rank-space\ntraining objective", "running", ran=False)
node("0003", 55, 87, "gated residual\nconsensus correction", "+0.0530",
     best=True)
node("0002", 55, 58, "dual-branch\nend-to-end network", "−0.0421")
node("0004", 80, 87, "+ per-instance\ncalibration", "not run", ran=False)
node("0005", 80, 58, "gated + quality-\nweighted fusion", "failed × 1")

edge("ROOT", "0001", "innovate")
edge("ROOT", "0007", "innovate")
edge("0001", "0003", "exploit")
edge("0001", "0002", "exploit")
edge("0003", "0004", "exploit")
edge("0003", "0005", "cross")
edge("0002", "0005", "cross")

# ── what a node carries ────────────────────────────────────────────────────
# Parked in the block the graph leaves empty above ROOT. Without this the
# dashed border has no legend, and a reader cannot tell "never ran" from
# "ran and scored badly" — the distinction the index exists to preserve.
ax.text(2.0, 93.0,
        "Each node is one complete solution:\n"
        "a four-digit address (this is what an\n"
        "operator cites as its parent), the\n"
        "mechanism in one line, then the best\n"
        "score — or why there is not one yet.",
        ha="left", va="center", fontsize=FS_LEG, color=GREY, zorder=3,
        linespacing=1.45)

# Sits under 0007, which is itself dashed, so the convention is shown where it
# is used. "Never ran" and "ran and scored badly" must not collapse together.
ax.text(30, 14.0, "dashed border: no result yet", ha="center", va="center",
        fontsize=FS_LEG, color=GREY, zorder=3)

# ── operator panel ─────────────────────────────────────────────────────────
# Sits in the block the graph leaves empty. The parent-count rule is the
# whole definition: 0 parents, 1 parent, or >= 2 decides the operator, and the
# host rejects any idea whose declared operator disagrees with its parent list.
PANEL = [
    ("innovate", "parents = ROOT",
     "open a new line of attack, not a tweak"),
    ("exploit", "exactly 1 parent",
     "one atomic change on an existing solution"),
    ("cross", "≥ 2 scored parents",
     "re-implement their mechanisms from scratch"),
]

for i, (op, rule, gloss) in enumerate(PANEL):
    y = 36.0 - i * 12.0
    colour, dash = STYLE[op]
    _stroke((47, y), (56, y), colour, dash)
    ax.text(58, y + 2.3, f"{op}   ·   {rule}", ha="left", va="center",
            fontsize=FS_LEG, color=colour, zorder=3)
    ax.text(58, y - 2.4, gloss, ha="left", va="center", fontsize=FS_LEG,
            color=GREY, zorder=3)

ax.text(47, 4.0,
        "cross gives a node two parents — the search structure is a DAG, "
        "not a tree.",
        ha="left", va="center", fontsize=FS_LEG, color=INK, zorder=3)

# `figure_lint.py` execs this file without `__file__`, so fall back to cwd.
out = (Path(globals().get("__file__", "x")).resolve().parent
       / "fig_evolution_graph_operators.pdf")
fig.savefig(out)                                   # exact 6.9 in column width
fig.savefig(out.with_suffix(".png"), dpi=300)
print("wrote", out.name, "and", out.with_suffix(".png").name)
