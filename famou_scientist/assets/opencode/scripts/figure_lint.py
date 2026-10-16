"""Render scientific plotting code and run a deterministic publication-spec lint.

The "figure quality gate" — the figure-side analogue of the paper *number* gate
(``verify_paper_cli.py``). LLM-drafted figures fail in deterministic, checkable
ways: a ``jet`` colormap, unreadably small fonts, a canvas that doesn't match the
target journal column width, missing axis labels, a raster export where a vector
was needed. None of that needs judgment — it needs a checklist. This kernel runs
that checklist against the *rendered Figure object* (introspection is far more
robust than scraping the source text), and saves the figure for the agent to
then actually *look at* (the visual-feedback loop lives in the
``scientific-visualization`` skill).

Division of labour, matching the famou philosophy:
- deterministic, checkable  -> here (kernel) + ``arc_render_figure`` tool + a
  guardrail hook that hard-blocks on ``severity == "FAIL"``
- aesthetic / "does it read well" -> the skill's render -> read -> critique loop

Self-contained: pure stdlib + matplotlib (imported lazily so ``import
figure_lint`` never fails when matplotlib is absent). No researchclaw dependency.

Public API
----------
- ``render_and_lint(code, out_path, kind="data", journal="single",
  results_path="") -> dict``
  Execs the plotting ``code``, saves the first figure to ``out_path`` (>=300 DPI;
  a ``.png`` sibling is also written for vector targets so the agent can read it),
  and returns ``{rendered, image_path, vector_path, size_inches, dpi, n_axes,
  checks:[{name, level, msg}], advisories:[...], severity}``. On a render error
  returns ``{rendered: False, error, severity: "ERROR"}``.

``kind``: ``"data"`` (full rubric) | ``"schematic"`` (relaxed — only canvas/DPI/
export; conceptual/architecture diagrams have no data axes to label).
``journal``: ``"single"`` | ``"double"`` column target width.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Deprecated rainbow-family colormaps: perceptually non-uniform, not colorblind
# safe — a hard no for quantitative scientific figures.
BAD_CMAPS = {"jet", "rainbow", "gist_rainbow", "hsv", "nipy_spectral", "gist_ncar"}

# Vector formats preferred for line art (scalable, sharp at any zoom).
VECTOR_EXTS = {".pdf", ".svg", ".eps", ".ps"}

# Acceptable physical widths (inches) per journal column target. Target band is
# tighter; the acceptable band is slightly wider to avoid nagging on near-misses.
JOURNAL_WIDTH = {
    "single": {"target": (3.3, 3.5), "ok": (3.0, 3.8)},
    "double": {"target": (6.5, 7.1), "ok": (6.0, 7.5)},
}

MIN_FONT_FAIL = 5.0   # < 5pt at print size = effectively unreadable -> FAIL
MIN_FONT_WARN = 6.0   # < 6pt = risky -> WARN


def _check(checks: list[dict], name: str, level: str, msg: str) -> None:
    checks.append({"name": name, "level": level, "msg": msg})


def _figure_fontsizes(fig: Any) -> list[float]:
    """Collect every text element's fontsize (in points) across all axes."""
    sizes: list[float] = []
    for ax in fig.axes:
        for obj in (ax.xaxis.label, ax.yaxis.label, ax.title):
            try:
                sizes.append(float(obj.get_fontsize()))
            except Exception:
                pass
        for tl in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            try:
                sizes.append(float(tl.get_fontsize()))
            except Exception:
                pass
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                try:
                    sizes.append(float(t.get_fontsize()))
                except Exception:
                    pass
    return [s for s in sizes if s > 0]


def _figure_cmaps(fig: Any) -> set[str]:
    """Colormap names used by images / scatter / mesh collections."""
    names: set[str] = set()
    for ax in fig.axes:
        mappables = list(getattr(ax, "images", [])) + list(getattr(ax, "collections", []))
        for m in mappables:
            try:
                cmap = m.get_cmap()
                if cmap is not None and getattr(cmap, "name", None):
                    names.add(cmap.name)
            except Exception:
                pass
    return names


def _hardcoded_data_suspected(code: str) -> bool:
    """Heuristic: many bare numeric literals + no results.json reference."""
    if "results.json" in code:
        return False
    # count standalone numbers (ints/floats), ignore tiny ones like axis args
    nums = re.findall(r"(?<![\w.])-?\d+\.\d+(?![\w.])", code)
    return len(nums) >= 8


def render_and_lint(
    code: str,
    out_path: str,
    kind: str = "data",
    journal: str = "single",
    results_path: str = "",
) -> dict:
    """Render ``code`` to a figure file and lint it against publication specs."""
    out_path = str(out_path or "").strip()
    if not out_path:
        return {"rendered": False, "error": "out_path 不能为空", "severity": "ERROR"}
    kind = kind if kind in ("data", "schematic") else "data"
    journal = journal if journal in JOURNAL_WIDTH else "single"

    # Lazy import: keeps `import figure_lint` safe when matplotlib is absent.
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless render, no display required
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover - env-dependent
        return {
            "rendered": False,
            "error": f"matplotlib 不可用（请在 ARC_PYTHON 环境安装）：{e}",
            "severity": "ERROR",
        }

    plt.close("all")  # start from a clean figure registry
    ns: dict[str, Any] = {"__name__": "__figure__"}
    try:
        exec(compile(code, "<plot>", "exec"), ns)  # noqa: S102 - same trust model as sandbox
    except Exception as e:
        plt.close("all")
        import traceback
        return {
            "rendered": False,
            "error": f"绘图代码执行出错：{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-1500:],
            "severity": "ERROR",
        }

    fignums = plt.get_fignums()
    if not fignums:
        return {
            "rendered": False,
            "error": "代码未创建任何 figure（确认用了 plt.figure()/plt.subplots() 且没有 plt.close）",
            "severity": "ERROR",
        }

    fig = plt.figure(fignums[0])  # lint + save the first figure
    advisories: list[str] = []
    if len(fignums) > 1:
        advisories.append(f"检测到 {len(fignums)} 个 figure，只体检并保存第一个；多图请分次渲染。")

    # ── save: force >=300 DPI; vector target also gets a .png sibling to read ──
    outp = Path(out_path)
    try:
        outp.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    ext = outp.suffix.lower()
    is_vector = ext in VECTOR_EXTS
    vector_path = ""
    try:
        fig.savefig(str(outp), dpi=300, bbox_inches="tight")
    except Exception as e:
        plt.close("all")
        return {"rendered": False, "error": f"保存图失败：{e}", "severity": "ERROR"}
    if is_vector:
        vector_path = str(outp)
        png_path = str(outp.with_suffix(".png"))
        try:
            fig.savefig(png_path, dpi=300, bbox_inches="tight")
        except Exception:
            png_path = str(outp)  # fall back to the vector path
        image_path = png_path
    else:
        image_path = str(outp)

    # ── introspect ──
    w, h = (float(x) for x in fig.get_size_inches())
    n_axes = len(fig.axes)
    checks: list[dict] = []

    # 1. canvas width vs journal column
    band = JOURNAL_WIDTH[journal]
    if band["ok"][0] <= w <= band["ok"][1]:
        lvl = "PASS" if band["target"][0] <= w <= band["target"][1] else "WARN"
        msg = f"画布宽 {w:.2f}in（{journal} 栏目标 {band['target'][0]}–{band['target'][1]}in）"
        _check(checks, "canvas_width", lvl, msg)
    else:
        _check(checks, "canvas_width", "WARN",
               f"画布宽 {w:.2f}in 偏离 {journal} 栏（建议 {band['target'][0]}–{band['target'][1]}in）")

    # 2. export format
    if is_vector:
        _check(checks, "export_format", "PASS", f"矢量导出（{ext}），可无损缩放")
    else:
        _check(checks, "export_format", "WARN",
               f"位图导出（{ext}）；线条图建议用矢量（pdf/svg/eps）以保证印刷清晰")

    # 3. font size (read against print-size points)
    sizes = _figure_fontsizes(fig)
    if sizes:
        smin = min(sizes)
        if smin < MIN_FONT_FAIL:
            _check(checks, "font_size", "FAIL", f"最小字号 {smin:.1f}pt 不可读（< {MIN_FONT_FAIL}pt）")
        elif smin < MIN_FONT_WARN:
            _check(checks, "font_size", "WARN", f"最小字号 {smin:.1f}pt 偏小（建议 ≥ {MIN_FONT_WARN}pt）")
        else:
            _check(checks, "font_size", "PASS", f"最小字号 {smin:.1f}pt")

    # 4. deprecated colormap (hard fail — applies to both kinds)
    cmaps = _figure_cmaps(fig)
    bad = sorted(cmaps & BAD_CMAPS)
    if bad:
        _check(checks, "colormap", "FAIL",
               f"使用了被废弃的彩虹系 colormap：{', '.join(bad)}（请换 viridis/cividis 等感知均匀且色盲友好的）")
    elif cmaps:
        _check(checks, "colormap", "PASS", f"colormap：{', '.join(sorted(cmaps))}")

    if kind == "data":
        # 5. axis labels present
        missing = [i for i, ax in enumerate(fig.axes)
                   if not (ax.get_xlabel().strip() and ax.get_ylabel().strip())]
        if missing:
            _check(checks, "axis_labels", "WARN",
                   f"{len(missing)}/{n_axes} 个坐标轴缺 x/y 轴标签")
        elif n_axes:
            _check(checks, "axis_labels", "PASS", "坐标轴均有 x/y 标签")
        # 6. units in labels (advisory — some quantities are unitless)
        no_units = []
        for ax in fig.axes:
            for lbl in (ax.get_xlabel(), ax.get_ylabel()):
                if lbl.strip() and "(" not in lbl and "[" not in lbl:
                    no_units.append(lbl.strip())
        if no_units:
            advisories.append(
                "部分轴标签未带单位（如 'Time (s)'）：" + "、".join(sorted(set(no_units))[:4])
                + "（无量纲量可忽略）")
        # 7. chartjunk: top/right spines
        spiny = sum(1 for ax in fig.axes
                    if ax.spines.get("top") and ax.spines["top"].get_visible()
                    or ax.spines.get("right") and ax.spines["right"].get_visible())
        if spiny:
            advisories.append(f"{spiny} 个坐标轴保留了 top/right 边框，建议 sns.despine 或手动去掉以减 chartjunk。")
        # 8. data provenance (advisory only — can't be hard-checked)
        if not results_path and _hardcoded_data_suspected(code):
            advisories.append(
                "绘图数据疑似硬编码：检出多个数值字面量且未引用 results.json。"
                "图里的数字必须来自真实实验（results.json），否则等同造图。")

    severity = "PASS"
    if any(c["level"] == "FAIL" for c in checks):
        severity = "FAIL"
    elif any(c["level"] == "WARN" for c in checks):
        severity = "WARN"

    plt.close("all")
    return {
        "rendered": True,
        "image_path": image_path,
        "vector_path": vector_path,
        "out_path": out_path,
        "n_figures": len(fignums),
        "n_axes": n_axes,
        "size_inches": [round(w, 3), round(h, 3)],
        "saved_dpi": 300,
        "kind": kind,
        "journal": journal,
        "checks": checks,
        "advisories": advisories,
        "severity": severity,
    }


def _main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="渲染绘图代码 + 出版规范确定性体检")
    ap.add_argument("--code-file", required=True, help="绘图 Python 代码文件路径")
    ap.add_argument("--out", required=True, help="图保存路径（.pdf/.svg/.png …）")
    ap.add_argument("--kind", default="data", choices=["data", "schematic"])
    ap.add_argument("--journal", default="single", choices=["single", "double"])
    ap.add_argument("--results-path", default="", help="results.json 路径（溯源用，可选）")
    args = ap.parse_args(argv)

    code = Path(args.code_file).read_text(encoding="utf-8")
    res = render_and_lint(code, args.out, kind=args.kind, journal=args.journal,
                          results_path=args.results_path)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
