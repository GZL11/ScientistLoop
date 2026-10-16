# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""Compile a LaTeX paper and run a deterministic pre-submission compile check.

The "compile gate" — the typesetting-side analogue of the figure gate
(``figure_lint.py``) and the paper-number gate (``verify_paper_cli.py``). The
core insight, agreed with the user: **"it produced a PDF / exit code 0" does NOT
mean the paper is fine.** LaTeX splits problems into two tiers:

- **Error** → compilation halts, no / partial PDF. LaTeX reports these itself.
- **Warning** → a PDF *is* produced and the exit code can be 0, yet the artifact
  is broken: ``Overfull \\hbox`` (text spilling into the margin),
  ``Reference/Citation undefined`` (rendered as ``??`` in the body), a missing
  figure. Looking only at the exit code silently ships these.

So this kernel does not trust the exit code. It compiles with ``latexmk`` (which
runs the needed passes + bibtex/biber, so the "undefined ref needs two passes"
artefact resolves on its own) and then **parses the .log** for the warnings that
matter. Page count is split honestly: LaTeX provides the actual page count
(``Output written on ... (N pages``); the *limit* is our rule (``VENUE_PAGE_LIMITS``,
mirroring the ``latex-fmt`` skill) — LaTeX cannot define "over the limit" itself.

Division of labour, matching the famou philosophy:
- deterministic, checkable -> here (kernel) + ``arc_latex_check`` tool + a
  guardrail hook that hard-blocks on ``severity == "FAIL"``.
- "does the prose read well" -> the ``peer-review`` / ``quality-gate`` skills.

Self-contained: pure stdlib. No TeX at import time — ``check`` degrades
gracefully (``severity == "ERROR"`` + an install hint) when no TeX toolchain is
found, so the tool always loads and the parsing functions stay unit-testable
without a TeX install.

Public API
----------
- ``parse_log(log_text) -> dict`` — pure; extract findings from a .log string.
- ``findings_to_checks(findings, *, venue=None, pages=None, pdf_ok=True)
  -> (checks, severity)`` — pure; map findings to ``[{name,level,msg}]`` + severity.
- ``check(tex_path, venue=None, timeout=180) -> dict`` — compile + parse + judge.
  Returns ``{ok, severity, pdf_path, pages, page_limit, venue, checks, log_tail}``;
  on no-TeX / bad input returns ``{ok: False, severity: "ERROR", error, checks}``.

``severity``: ``ERROR`` (can't assess: no TeX / bad path / timeout) > ``FAIL``
(assessed and broken: undefined ref/cite -> ``??``, missing file, fatal error,
no PDF) > ``WARN`` (overfull/underfull hbox, over page limit) > ``PASS``.

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = ["parse_log", "findings_to_checks", "check", "VENUE_PAGE_LIMITS"]

# Venue page limits — mirrors `latex-fmt/SKILL.md` Phase 4 table. The *limit* is a
# venue policy, not a LaTeX concept; LaTeX only tells us the actual page count.
# NOTE: keep in sync with the skill's table. Limits are MAIN-content pages; most
# venues exclude references/appendices, which we cannot split out here — hence the
# page check is an honest WARN ("total pages, rough") rather than a hard FAIL.
VENUE_PAGE_LIMITS = {
    "neurips": 9,
    "icml": 8,
    "cvpr": 8,
    "iccv": 8,
    "eccv": 14,
    "acl": 8,
    "emnlp": 8,
    "coling": 8,
    "naacl": 8,
    "aaai": 7,
    "kdd": 10,
    "sigir": 8,
    "interspeech": 5,
    "iclr": None,  # no strict limit
}


VENUE_TEMPLATE_RULES = {
    "asme": {"classes": {"asmeconf"}},
    "asmeconf": {"classes": {"asmeconf"}},
    "asme-idetc": {"classes": {"asmeconf"}},
    "idetc": {"classes": {"asmeconf"}},
    "ieee": {"classes": {"ieeetran"}},
    "kdd": {"classes": {"acmart"}},
    "sigir": {"classes": {"acmart"}},
    "eccv": {"classes": {"llncs"}},
    "neurips": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{neurips_\d{4}\}",),
    },
    "icml": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{icml\d{4}\}",),
    },
    "cvpr": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{cvpr\}",),
    },
    "acl": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{acl\}",),
    },
    "emnlp": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{acl\}",),
    },
    "iclr": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{iclr\d{4}_conference\}",),
    },
    "tmlr": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{tmlr\}",),
    },
    "aaai": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{aaai\d{2}\}",),
    },
    "interspeech": {
        "classes": {"article"},
        "markers": (r"\\usepackage(?:\[[^]]*\])?\{interspeech(?:_\d{4})?\}",),
    },
}


_GENERIC_DOCUMENT_CLASSES = {"article", "report", "book", "minimal", "standalone"}


def _local_template_styles(tex_path: Path, source: str) -> list[str]:
    """Return style packages shipped beside the manuscript or in its subdirectories."""
    styles: set[str] = set()
    for group in re.findall(r"\\usepackage(?:\[[^]]*\])?\{([^}]+)\}", source):
        for package in group.split(","):
            package = package.strip()
            if not package:
                continue
            rel = Path(package)
            if rel.suffix.lower() != ".sty":
                rel = Path(f"{package}.sty")
            candidate = tex_path.parent / rel
            try:
                if candidate.is_file():
                    styles.add(package)
            except OSError:
                continue
    return sorted(styles)


def _template_gate(tex_path: Path, venue: str | None, env: dict) -> list[str]:
    """Validate the selected venue class in the actual TeX environment before compiling."""
    try:
        source = tex_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    match = re.search(r"\\documentclass(?:\[[^]]*\])?\{([^}]+)\}", source)
    if not match:
        return ["主文件缺少 \\documentclass，无法确认投稿模板。"]
    cls = match.group(1).strip().lower()
    venue_key = str(venue or "").strip().lower().replace("_", "-")
    rule = VENUE_TEMPLATE_RULES.get(venue_key)
    if rule:
        expected_classes = rule["classes"]
        if cls not in expected_classes:
            expected = " / ".join(sorted(expected_classes))
            return [f"目标 venue={venue} 要求 document class {expected}，当前是 {match.group(1)}。"]
        markers = rule.get("markers") or ()
        if markers and not any(re.search(pattern, source, re.IGNORECASE) for pattern in markers):
            return [f"目标 venue={venue} 缺少官方模板 style marker；不能把通用 {match.group(1)} 当成已按 venue 排版。"]
    elif venue_key and cls in _GENERIC_DOCUMENT_CLASSES:
        local_styles = _local_template_styles(tex_path, source)
        if not local_styles:
            return [
                f"目标 venue={venue} 尚无内置规则，且当前仅使用通用 {match.group(1)}，未加载随官方 author kit 落盘的本地 style；请先按官方示例建立稿件。"
            ]
    if cls != "asmeconf":
        return []
    engine = shutil.which("pdflatex", path=env.get("PATH"))
    if not engine:
        return ["asmeconf 模板探测需要 pdflatex，但当前 TeX 环境未提供。"]
    with tempfile.TemporaryDirectory(prefix="famou-tex-probe-") as tmp:
        probe = Path(tmp) / "probe.tex"
        probe.write_text("\\DocumentMetadata{}\n\\documentclass{asmeconf}\n\\begin{document}\nprobe\\end{document}\n", encoding="utf-8")
        probe_env = dict(env)
        probe_env["TEXINPUTS"] = str(tex_path.parent) + os.pathsep + probe_env.get("TEXINPUTS", "")
        try:
            subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error", probe.name],
                           cwd=tmp, env=probe_env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=45, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [f"asmeconf 官方模板探测失败：{type(exc).__name__}。"]
        log = probe.with_suffix(".log")
        findings = parse_log(log.read_text(encoding="utf-8", errors="replace") if log.exists() else "")
        errors = findings.get("errors") or []
        if errors:
            return ["当前 TinyTeX/LaTeX 与 asmeconf 不兼容：" + "；".join(errors[:3])]
    return []
def _check(checks: list[dict], name: str, level: str, msg: str) -> None:
    checks.append({"name": name, "level": level, "msg": msg})


# ── log parsing (pure — unit-testable without a TeX install) ──────────────────
# LaTeX wraps log lines hard at ~79 columns *mid-token*, so a warning's keyword
# ("undefined") can land on the next physical line. We therefore search both the
# raw text (line-anchored patterns: overfull, pages, file:line errors) and a
# newline-stripped copy (warning patterns that may have wrapped).
def parse_log(log_text: str) -> dict:
    """Extract structured findings from a LaTeX .log string. Pure function."""
    text = log_text or ""
    flat = text.replace("\n", "")  # de-wrap (LaTeX breaks mid-token, no space)

    def _uniq(seq):
        seen, out = set(), []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    # Undefined references / citations -> render as `??` in the PDF (FAIL-worthy).
    undefined_refs = _uniq(re.findall(r"Reference [`'\"]([^'`\"]+)['`\"][^.]*?undefined", flat))
    undefined_cites = _uniq(re.findall(r"Citation [`'\"]([^'`\"]+)['`\"][^.]*?undefined", flat))

    # Missing input files (figures, \input, .bib) -> FAIL-worthy.
    missing_files = _uniq(re.findall(r"File [`'\"]([^'`\"]+)['`\"] not found", flat))

    # Overfull / underfull hboxes -> content past the margin / ugly spacing (WARN).
    overfull = []
    for m in re.finditer(
        r"Overfull \\hbox \(([\d.]+)pt too wide\)(?:.*?lines? (\d+)(?:--(\d+))?)?", text
    ):
        overfull.append({
            "pts": float(m.group(1)),
            "lines": (m.group(2) + ("--" + m.group(3) if m.group(3) else "")) if m.group(2) else "",
        })
    underfull = len(re.findall(r"Underfull \\hbox", text))

    # Fatal errors: `! ...` (classic) and `file:line: ...` (-file-line-error mode).
    errors = []
    for line in text.splitlines():
        s = line.rstrip()
        if s.startswith("! "):
            errors.append(s[2:].strip())
        else:
            m = re.match(r".+?:\d+:\s+(.+)$", s)
            if m:
                errors.append(m.group(1).strip())
    errors = _uniq(errors)

    # Page count: `Output written on paper.pdf (8 pages, ... bytes).`
    pm = re.search(r"Output written on .*?\((\d+) pages?", text)
    pages = int(pm.group(1)) if pm else None

    return {
        "errors": errors,
        "undefined_refs": undefined_refs,
        "undefined_cites": undefined_cites,
        "missing_files": missing_files,
        "overfull": overfull,
        "underfull": underfull,
        "pages": pages,
    }


def findings_to_checks(findings: dict, *, venue: str | None = None,
                       pages: int | None = None, pdf_ok: bool = True) -> tuple[list[dict], str]:
    """Map parsed findings to ``[{name,level,msg}]`` + rolled-up severity. Pure."""
    checks: list[dict] = []

    # ── FAIL-tier: the artifact is broken even though it may have "compiled" ──
    errs = findings.get("errors") or []
    if errs:
        head = "；".join(errs[:3])
        _check(checks, "compile_error", "FAIL",
               f"编译报错 {len(errs)} 处：{head}" + (" …" if len(errs) > 3 else ""))

    if not pdf_ok:
        _check(checks, "no_pdf", "FAIL", "未产出 PDF——编译失败（见 compile_error / 日志末尾）")

    refs = findings.get("undefined_refs") or []
    if refs:
        _check(checks, "undefined_reference", "FAIL",
               f"{len(refs)} 个悬空 \\ref（正文会渲成 ??）：{', '.join(refs[:6])}"
               + (" …" if len(refs) > 6 else ""))

    cites = findings.get("undefined_cites") or []
    if cites:
        _check(checks, "undefined_citation", "FAIL",
               f"{len(cites)} 个悬空 \\cite（正文会渲成 ??；检查 .bib 与 bibtex/biber）："
               f"{', '.join(cites[:6])}" + (" …" if len(cites) > 6 else ""))

    miss = findings.get("missing_files") or []
    if miss:
        _check(checks, "missing_file", "FAIL",
               f"{len(miss)} 个文件找不到（缺图/缺 \\input/缺 .bib）：{', '.join(miss[:6])}"
               + (" …" if len(miss) > 6 else ""))

    # ── WARN-tier: real but not desk-reject ──
    over = findings.get("overfull") or []
    if over:
        worst = max(o["pts"] for o in over)
        _check(checks, "overfull_hbox", "WARN",
               f"{len(over)} 处 overfull \\hbox（最宽溢出 {worst:.1f}pt，文字会戳出版心）；"
               f"常见诱因：长 URL/宽表/不换行公式")
    under = findings.get("underfull") or 0
    if under:
        _check(checks, "underfull_hbox", "WARN", f"{under} 处 underfull \\hbox（行内间距被拉伸，排版偏丑）")

    # ── page count vs venue limit: LaTeX gives the count, OUR rule gives limit ──
    page_limit = None
    if venue:
        v = str(venue).strip().lower()
        if v in VENUE_PAGE_LIMITS:
            page_limit = VENUE_PAGE_LIMITS[v]
    if page_limit and pages:
        if pages > page_limit:
            _check(checks, "page_limit", "WARN",
                   f"总页数 {pages} > {venue} 上限 {page_limit}（粗判：本数为总页数，venue 上限通常"
                   f"不含 references/appendix，请据此核对正文页数）")
        else:
            _check(checks, "page_limit", "PASS",
                   f"总页数 {pages} ≤ {venue} 上限 {page_limit}（粗判，不拆 refs/appendix）")

    severity = "PASS"
    if any(c["level"] == "FAIL" for c in checks):
        severity = "FAIL"
    elif any(c["level"] == "WARN" for c in checks):
        severity = "WARN"
    return checks, severity


# ── compile orchestration ─────────────────────────────────────────────────────
def _tex_env() -> dict:
    """A copy of os.environ with common TeX bin dirs prepended to PATH.

    TinyTeX installs to ``~/.TinyTeX/bin/<arch>`` which is often not on the PATH of
    a spawned subprocess; surface it so ``latexmk``/``pdflatex`` are found.
    """
    env = dict(os.environ)
    extra = []
    home = Path(os.environ.get("HOME") or str(Path.home()))
    for base in (home / ".TinyTeX" / "bin", Path("/usr/local/texlive")):
        if base.exists():
            for sub in sorted(base.glob("*")):
                if (sub / "latexmk").exists() or (sub / "pdflatex").exists():
                    extra.append(str(sub))
                # texlive layout: <year>/bin/<arch>
                binp = sub / "bin"
                if binp.exists():
                    for arch in sorted(binp.glob("*")):
                        extra.append(str(arch))
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def _find_engine(env: dict) -> tuple[str | None, str | None]:
    """Return (latexmk_path, pdflatex_path) honouring the augmented PATH."""
    path = env.get("PATH")
    return shutil.which("latexmk", path=path), shutil.which("pdflatex", path=path)


def check(tex_path: str, venue: str | None = None, timeout: int = 180) -> dict:
    """Compile ``tex_path`` and run the deterministic compile check.

    Args:
        tex_path: path to the main ``.tex`` file.
        venue: optional venue key (e.g. ``neurips``) for the page-limit check.
        timeout: per-compile wall-clock seconds.

    Returns:
        ``{ok, severity, pdf_path, pages, page_limit, venue, checks, log_tail}``;
        ``severity == "ERROR"`` (with ``error``) when it cannot even assess.
    """
    p = Path(str(tex_path or "").strip())
    if not str(p):
        return {"ok": False, "severity": "ERROR", "error": "tex_path 不能为空", "checks": []}
    if p.suffix.lower() != ".tex":
        return {"ok": False, "severity": "ERROR",
                "error": f"不是 .tex 文件：{p}", "checks": []}
    if not p.exists():
        return {"ok": False, "severity": "ERROR", "error": f"文件不存在：{p}", "checks": []}

    env = _tex_env()
    latexmk, pdflatex = _find_engine(env)
    if not latexmk and not pdflatex:
        return {
            "ok": False,
            "severity": "ERROR",
            "error": "本机未找到 TeX 工具链（latexmk/pdflatex）。请装 TinyTeX："
                     "wget -qO- https://yihui.org/tinytex/install-bin-unix.sh | sh"
                     "（或 apt install texlive-latex-extra latexmk）。装好后重试本工具。",
            "checks": [],
        }

    template_errors = _template_gate(p, venue, env)
    if template_errors:
        checks = [{"name": "template_environment", "level": "FAIL", "msg": msg} for msg in template_errors]
        return {
            "ok": False,
            "severity": "FAIL",
            "pdf_path": "",
            "pages": None,
            "page_limit": VENUE_PAGE_LIMITS.get(str(venue).strip().lower()) if venue else None,
            "venue": venue or "",
            "engine": "template-probe",
            "checks": checks,
            "error": "官方投稿模板/LaTeX 环境不兼容，已阻断编译导出。",
        }
    workdir = str(p.parent)
    base = p.stem
    if latexmk:
        cmd = [latexmk, "-pdf", "-interaction=nonstopmode", "-file-line-error", "-f", p.name]
    else:
        # Fallback: two pdflatex passes resolve most cross-references.
        cmd = [pdflatex, "-interaction=nonstopmode", "-file-line-error", p.name]

    try:
        for _ in range(1 if latexmk else 2):
            subprocess.run(cmd, cwd=workdir, env=env, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "severity": "ERROR",
                "error": f"编译超时（>{timeout}s）：{p.name}", "checks": []}
    except Exception as e:  # pragma: no cover - env-dependent
        return {"ok": False, "severity": "ERROR",
                "error": f"调用 latexmk/pdflatex 失败：{type(e).__name__}: {e}", "checks": []}

    log_path = p.with_suffix(".log")
    log_text = ""
    if log_path.exists():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            log_text = ""

    pdf_path = p.with_suffix(".pdf")
    pdf_ok = pdf_path.exists() and pdf_path.stat().st_size > 0

    findings = parse_log(log_text)
    checks, severity = findings_to_checks(
        findings, venue=venue, pages=findings.get("pages"), pdf_ok=pdf_ok)

    page_limit = None
    if venue:
        page_limit = VENUE_PAGE_LIMITS.get(str(venue).strip().lower())

    return {
        "ok": True,
        "severity": severity,
        "pdf_path": str(pdf_path) if pdf_ok else "",
        "pages": findings.get("pages"),
        "page_limit": page_limit,
        "venue": venue or "",
        "engine": "latexmk" if latexmk else "pdflatex",
        "checks": checks,
        "log_tail": log_text[-2000:] if log_text else "",
    }


def _main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="编译 LaTeX 论文 + 确定性投稿前体检")
    ap.add_argument("tex", help="主 .tex 文件路径")
    ap.add_argument("--venue", default="", help="目标会议/期刊（页限核对用，可选）")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args(argv)
    res = check(args.tex, venue=args.venue or None, timeout=args.timeout)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
