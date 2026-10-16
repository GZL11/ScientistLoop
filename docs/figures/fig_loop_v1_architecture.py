#!/usr/bin/env python3
"""Figure 1 — Famou Loop V1: the baseline closed-loop research agent.

Publication schematic. Double-column width (6.9 in), vector PDF + 300-dpi PNG.
Conventions followed: sans-serif >= 6.5 pt, >= 0.7 pt strokes, Okabe-Ito
colour-blind-safe palette used only to separate *roles* (agent / host / store /
sealed), no decorative fill, TrueType-embedded text.

Layout: the acting pipeline reads left to right across the top (idea →
implementation → evaluation); the return path drops down the right edge
through the validity gate and runs back along the bottom into ExpBank, which
sits directly under the agent that reads it. One loop, no crossing edges.

The topology is transcribed from `loop/runtime/orchestrator.py::tick` on the
`benchmark_managed` path — the arm every NatureBench run uses. Three details
that are easy to get wrong and are therefore drawn explicitly:

  * the validity verifier is a gate on whether a score *counts*, not on
    whether an attempt runs (`_update_leaderboard` runs dry, then the
    verifier, then for real);
  * ExpBank is read by the idea agent and written by the host; no agent ever
    writes it. `record.json` is machine-authoritative, `INDEX.md` agent-facing;
  * the hidden evaluation set reaches only the evaluator, never an agent.

    python3 fig_loop_v1_architecture.py            # writes PDF + PNG alongside
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

FS_BOX, FS_SUB, FS_EDGE = 8.0, 6.5, 6.5

# Okabe–Ito. Colour encodes role only, never magnitude.
C_AGENT = "#0072B2"   # LLM agent               (blue)
C_HOST = "#D55E00"    # deterministic host code (vermilion)
C_STORE = "#009E73"   # persistent store        (bluish green)
C_SEAL = "#595959"    # sealed from every agent (grey)
INK = "#1A1A1A"

fig = plt.figure(figsize=(6.9, 4.0))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 100)
ax.set_ylim(8, 100)   # crop the dead strip under the store band
ax.axis("off")

# Three columns, three bands. Everything snaps to these, so re-wording a label
# cannot knock the figure out of alignment. Boxes are 26 wide, which leaves a
# 7-unit gutter between columns — wide enough to hold an edge label without
# its opaque background eating a neighbouring border.
L, M, R = 17.0, 50.0, 83.0
Y_TOP, Y_ACT, Y_STORE = 90.0, 62.0, 20.0
BW = 26.0


def box(x, y, w, h, title, sub=None, colour=INK, lw=1.0, dashed=False):
    """A labelled block; (x, y) is its centre. Title above, detail below."""
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.25", linewidth=lw, edgecolor=colour,
        facecolor="white", zorder=2,
        linestyle=(0, (3, 2)) if dashed else "solid",
    ))
    ax.text(x, y + (3.0 if sub else 0), title, ha="center", va="center",
            fontsize=FS_BOX, color=INK, zorder=3)
    if sub:
        ax.text(x, y - 3.2, sub, ha="center", va="center", fontsize=FS_SUB,
                color="#3D3D3D", zorder=3, linespacing=1.35)


def arrow(p, q, colour=INK, style="arc3,rad=0", lw=1.0, dashed=False):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle="-|>", mutation_scale=9, linewidth=lw, color=colour,
        zorder=1, linestyle=(0, (3, 2)) if dashed else "solid",
        connectionstyle=style, shrinkA=0, shrinkB=0,
    ))


def label(x, y, text, colour=INK, ha="center"):
    """Edge label. The opaque background lets a label sit on top of an edge."""
    ax.text(x, y, text, ha=ha, va="center", fontsize=FS_EDGE, color=colour,
            zorder=4, linespacing=1.35,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none"))


# ── inputs, public and sealed ──────────────────────────────────────────────
box(L, Y_TOP, BW, 13, "Task contract (public)",
    "problem statement · metric\nwall-clock & resource limits", colour=C_SEAL)

box(R, Y_TOP, BW, 8.5, "Hidden evaluation set", colour=C_SEAL, dashed=True)

# ── acting band: one turn, left to right ───────────────────────────────────
box(L, Y_ACT, BW, 14, "Idea agent",
    "long-lived session\none proposal per turn", colour=C_AGENT, lw=1.3)

box(M, Y_ACT, BW, 14, "Implementation agent",
    "isolated workspace\n≤ 3 self-debug attempts", colour=C_AGENT, lw=1.3)

box(R, Y_ACT, BW, 14, "Evaluator",
    "sealed environment\nper-instance, per-sub-metric", colour=C_HOST, lw=1.3)

# ── return band: the gate, and the store the next turn reads ───────────────
box(L, Y_STORE, BW, 16, "ExpBank",
    "record.json   authoritative\nSUMMARY.md   per attempt\nINDEX.md   agent-facing",
    colour=C_STORE, lw=1.3)

box(R, Y_STORE, BW, 14, "Validity verifier",
    "gates promotion,\nnot every attempt", colour=C_HOST)

# ── edges: the acting band ─────────────────────────────────────────────────
arrow((L, 83.5), (L, 69.0))
label(L + 2.2, 76.2, "goal", ha="left")

arrow((30.0, Y_ACT), (37.0, Y_ACT))
label(33.5, 66.0, "idea\nJSON")

arrow((63.0, Y_ACT), (70.0, Y_ACT))
label(66.5, 66.0, "artifacts\n+ weights")

arrow((R, 85.75), (R, 69.0), colour=C_SEAL, dashed=True)

# ── edges: the return path ─────────────────────────────────────────────────
arrow((R, 55.0), (R, 27.0), colour=C_HOST)
label(R - 2.2, 41.0, "scores +\nraw outputs", colour=C_HOST, ha="right")

# The host writes the record — this edge never passes through an agent.
arrow((70.0, Y_STORE), (30.0, Y_STORE), colour=C_HOST)
label(M, Y_STORE, "host writes the record", colour=C_HOST)

arrow((L, 28.0), (L, 55.0), colour=C_STORE)
label(L + 2.2, 41.5, "read back:\nwhat was tried,\nwhat it scored",
      colour=C_STORE, ha="left")

# ── legend ─────────────────────────────────────────────────────────────────
# Parked in the empty middle column. Everything stays inside the 0–100 canvas,
# so the saved width is exactly the declared figsize; `bbox_inches="tight"`
# would let a stray label decide the column width instead.
for (lx, ly), (c, lab, dash) in zip(
    [(34.0, 45.0), (34.0, 38.0), (52.0, 45.0), (52.0, 38.0)],
    [(C_AGENT, "LLM agent", False),
     (C_HOST, "deterministic host", False),
     (C_STORE, "persistent store", False),
     (C_SEAL, "sealed from agents", True)],
):
    ax.add_patch(FancyBboxPatch(
        (lx, ly - 1.05), 2.4, 2.1, boxstyle="round,pad=0.1", linewidth=1.0,
        edgecolor=c, facecolor="white",
        linestyle=(0, (2, 1.6)) if dash else "solid"))
    ax.text(lx + 3.6, ly, lab, ha="left", va="center", fontsize=FS_SUB,
            color=INK)

# `figure_lint.py` execs this file without `__file__`, so fall back to cwd.
out = Path(globals().get("__file__", "x")).resolve().parent / "fig_loop_v1_architecture.pdf"
fig.savefig(out)                                   # exact 6.9 in column width
fig.savefig(out.with_suffix(".png"), dpi=300)
print("wrote", out.name, "and", out.with_suffix(".png").name)
