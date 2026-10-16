#!/usr/bin/env python3
"""Figure 2 — how the solution graph is extended, and the three operators.

Publication schematic, double-column (6.9 in), vector PDF + 300-dpi PNG.
This figure is architectural: it shows the *mechanism* by which the graph
grows, with no run, no node identifiers and no scores in it. A worked example
of an actual graph belongs in a separate results figure.

Panel (a) is the extension step, which is identical for every operator: the
graph is read, a parent set is chosen, one mechanism is written against that
context, it is implemented and evaluated, and the result is written back as a
new node together with its parent set.

Panel (b) is the only thing the operators disagree about: the size of the
parent set, and what is carried forward from it. `ensemble`, a fourth operator
that carries a parent's *trained artifacts* rather than its mechanism, is out
of scope here.

The structural consequence, stated in the footnote, is the reason the on-disk
record stores a parent *list*: two of the three operators leave each node with
at most one parent, but `cross` does not, so the search structure is a DAG and
cannot be serialised as a tree.

Style notes: light tints with a matching darker stroke rather than heavy black
outlines; colour is decorative here (each operator is already named in its own
column) so the figure survives greyscale; node glyphs are plot markers, which
stay circular regardless of the axes' aspect ratio.

    python3 fig_operators.py                       # writes PDF + PNG alongside
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

FS_PANEL, FS_BOX, FS_OP, FS_BODY = 8.5, 7.5, 8.0, 6.5

INK = "#1A1A1A"
GREY = "#5A5A5A"
HAIR = "#A8A8AD"
NEUTRAL = "#F4F4F5"

# Okabe–Ito hues. Each gets a tint for the name band and a paler wash for the
# card behind it, so the three columns read as parallel alternatives.
OPS = [
    dict(name="innovate", fill="#F7E4EF", wash="#FCF4F8", line="#CC79A7",
         text="#8E4C74",
         rule="no parent (ROOT)",
         body="Reads the task contract and the list\n"
              "of what has been tried, and nothing\n"
              "else. Opens a route, not a tweak.",
         parents=1, root=True),
    dict(name="exploit", fill="#DFEDF7", wash="#F1F7FC", line="#0072B2",
         text="#005B8E",
         rule="1 parent",
         body="Reads one parent in full: its code,\n"
              "its score, its failure trace. Changes\n"
              "one thing, so the effect is readable.",
         parents=1, root=False),
    dict(name="cross", fill="#FCEFD6", wash="#FEF9EE", line="#E69F00",
         text="#9A6B00",
         rule="≥ 2 scored parents",
         body="Reads two scored solutions whose\n"
              "mechanisms differ, keeps the part of\n"
              "each that worked, and rebuilds it.",
         parents=2, root=False),
]

fig = plt.figure(figsize=(6.9, 3.8))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x, y, w, h, title, sub, fc=NEUTRAL, ec=HAIR):
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.4",
        linewidth=0.8, edgecolor=ec, facecolor=fc, zorder=2))
    ax.text(x, y + 3.3, title, ha="center", va="center", fontsize=FS_BOX,
            color=INK, zorder=3)
    ax.text(x, y - 2.8, sub, ha="center", va="center", fontsize=FS_BODY,
            color=GREY, zorder=3, linespacing=1.4)


def arrow(p, q, colour=GREY, lw=0.9):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle="-|>", mutation_scale=8, linewidth=lw, color=colour,
        shrinkA=0, shrinkB=0, zorder=1))


def glyph(x, y, *, fc, ec, size=7.5, shape="o"):
    """A node. Drawn as a plot marker so it stays round whatever the axes
    aspect ratio is — a patch would come out as an ellipse on this canvas."""
    ax.plot([x], [y], marker=shape, markersize=size, markerfacecolor=fc,
            markeredgecolor=ec, markeredgewidth=1.0, linestyle="none",
            zorder=3)


# ══ (a) the extension step, shared by all three operators ══════════════════
ax.text(1.5, 95.5, "a", ha="left", va="center", fontsize=FS_PANEL,
        fontweight="bold", color=INK)

BY, BH, BW = 82.0, 14.0, 18.0
COLS = [12.0, 37.0, 62.0, 87.0]

box(COLS[0], BY, BW, BH, "Solution graph",
    "every proposal,\nits parents, its score")
box(COLS[1], BY, BW, BH, "Operator",
    "picks the parent set\nand what to carry")
box(COLS[2], BY, BW, BH, "Idea agent",
    "writes one mechanism\nagainst that context")
box(COLS[3], BY, BW, BH, "Implement + score",
    "isolated workspace,\nsealed evaluator")

for a, b in zip(COLS, COLS[1:]):
    arrow((a + BW / 2 + 1.2, BY), (b - BW / 2 - 1.2, BY))

# The return rail. The host writes the node; the operator is a *claim about
# provenance*, so the parent set travels back with the score.
ax.plot([COLS[3], COLS[3], COLS[0]], [BY - BH / 2 - 0.4, 68.5, 68.5],
        color=GREY, linewidth=0.9, solid_joinstyle="round", zorder=1)
arrow((COLS[0], 68.5), (COLS[0], BY - BH / 2 - 0.8))
ax.text(49.5, 68.5, "written back as a new node, with its score and its "
        "parent set", ha="center", va="center", fontsize=FS_BODY, color=GREY,
        zorder=4, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"))

# ══ (b) what the three operators disagree about ════════════════════════════
ax.text(1.5, 59.5, "b", ha="left", va="center", fontsize=FS_PANEL,
        fontweight="bold", color=INK)

CX = [17.0, 50.0, 83.0]
CW = 30.0
Y_CARD, CARD_H = 35.5, 41.0          # card spans y 15 – 56
Y_BAND, Y_DIAG, Y_BODY = 51.5, 38.0, 24.0

for cx, op in zip(CX, OPS):
    # A soft card per operator, with the name band as its header. The card is
    # what makes the three read as parallel alternatives rather than a chain.
    ax.add_patch(FancyBboxPatch(
        (cx - CW / 2, Y_CARD - CARD_H / 2), CW, CARD_H,
        boxstyle="round,pad=0.4", linewidth=0, edgecolor="none",
        facecolor=op["wash"], zorder=0))
    ax.add_patch(FancyBboxPatch(
        (cx - CW / 2, Y_BAND - 4.0), CW, 8.0, boxstyle="round,pad=0.4",
        linewidth=0.9, edgecolor=op["line"], facecolor=op["fill"], zorder=2))
    ax.text(cx - CW / 2 + 2.5, Y_BAND, op["name"], ha="left", va="center",
            fontsize=FS_OP, color=op["text"], zorder=3)
    ax.text(cx + CW / 2 - 2.5, Y_BAND, op["rule"], ha="right", va="center",
            fontsize=FS_BODY, color=op["text"], zorder=3)

    # The parent pattern: grey glyphs are solutions already in the graph, the
    # tinted one is what this operator creates.
    if op["root"]:
        glyph(cx - 10, Y_DIAG, fc="#EFEFF1", ec=HAIR, shape="s", size=6.5)
        ax.text(cx - 10, Y_DIAG - 5.8, "ROOT", ha="center", va="center",
                fontsize=FS_BODY, color=HAIR)
        ax.text(cx + 7, Y_DIAG - 5.8, "new node", ha="center", va="center",
                fontsize=FS_BODY, color=GREY)
        arrow((cx - 8, Y_DIAG), (cx + 4.4, Y_DIAG), colour=op["line"])
    elif op["parents"] == 1:
        glyph(cx - 10, Y_DIAG, fc="#DCDCDE", ec=GREY)
        ax.text(cx - 10, Y_DIAG - 5.8, "parent", ha="center", va="center",
                fontsize=FS_BODY, color=GREY)
        arrow((cx - 8, Y_DIAG), (cx + 4.4, Y_DIAG), colour=op["line"])
    else:
        for dy in (4.6, -4.6):
            glyph(cx - 10, Y_DIAG + dy, fc="#DCDCDE", ec=GREY)
            arrow((cx - 8.3, Y_DIAG + dy * 0.82),
                  (cx + 4.4, Y_DIAG + dy * 0.16), colour=op["line"])

    glyph(cx + 7, Y_DIAG, fc=op["fill"], ec=op["line"], size=8.5)

    ax.text(cx - CW / 2 + 1.5, Y_BODY, op["body"], ha="left", va="center",
            fontsize=FS_BODY, color=INK, zorder=3, linespacing=1.55)

# ── footnote ───────────────────────────────────────────────────────────────
ax.text(50.0, 7.0,
        "innovate and exploit leave every node with at most one parent; "
        "cross does not, so the search structure is a DAG, not a tree.",
        ha="center", va="center", fontsize=FS_BODY, color=INK)

# `figure_lint.py` execs this file without `__file__`, so fall back to cwd.
out = Path(globals().get("__file__", "x")).resolve().parent / "fig_operators.pdf"
fig.savefig(out)                                   # exact 6.9 in column width
fig.savefig(out.with_suffix(".png"), dpi=300)
print("wrote", out.name, "and", out.with_suffix(".png").name)
