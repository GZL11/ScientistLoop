# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""latex_check 内核测试：编译日志解析 + severity 滚动 + 页限 + 无 TeX 优雅降级。

全部离线、**不需要安装 TeX**：核心是 ``parse_log`` / ``findings_to_checks`` 两个纯
函数（喂合成 .log 文本断言），加 ``check`` 在无工具链时的降级路径（monkeypatch
``shutil.which``）。真编译留给手动验证（见 plan 的验证清单），CI 不依赖 TeX。

守护的核心命题：**"编出 PDF / 退出码 0" ≠ 没问题**——悬空 \\ref/\\cite、缺图要判 FAIL。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from famou_scientist import launcher


def _scripts_dir() -> Path:
    return launcher.opencode_config_dir() / "scripts"


@pytest.fixture(scope="module")
def L():
    sd = str(_scripts_dir())
    sys.path.insert(0, sd)
    try:
        import latex_check  # noqa: E402
        yield latex_check
    finally:
        sys.path.remove(sd)


def test_kernel_present():
    assert (_scripts_dir() / "latex_check.py").exists()


# ── parse_log：从合成日志抓 findings ─────────────────────────────
def test_parse_log_undefined_reference(L):
    log = "LaTeX Warning: Reference `fig:result' on page 3 undefined on input line 42.\n"
    f = L.parse_log(log)
    assert "fig:result" in f["undefined_refs"]


def test_parse_log_undefined_citation(L):
    log = "LaTeX Warning: Citation `smith2020' on page 1 undefined on input line 10.\n"
    f = L.parse_log(log)
    assert "smith2020" in f["undefined_cites"]


def test_parse_log_undefined_wrapped_across_lines(L):
    # LaTeX 在 ~79 列硬换行（会把 token/关键字拆到下一行）——去换行后仍应抓到
    log = ("LaTeX Warning: Reference `tab:big' on page 2 undef\n"
           "ined on input line 88.\n")
    f = L.parse_log(log)
    assert "tab:big" in f["undefined_refs"]


def test_parse_log_missing_file(L):
    log = "! LaTeX Error: File `figures/fig1.png' not found.\n"
    f = L.parse_log(log)
    assert "figures/fig1.png" in f["missing_files"]


def test_parse_log_overfull_with_pts(L):
    log = "Overfull \\hbox (15.38356pt too wide) in paragraph at lines 42--45\n"
    f = L.parse_log(log)
    assert len(f["overfull"]) == 1
    assert abs(f["overfull"][0]["pts"] - 15.38356) < 1e-3
    assert f["overfull"][0]["lines"] == "42--45"


def test_parse_log_underfull_count(L):
    log = ("Underfull \\hbox (badness 10000) in paragraph at lines 1--2\n"
           "Underfull \\hbox (badness 5000) in paragraph at lines 3--4\n")
    f = L.parse_log(log)
    assert f["underfull"] == 2


def test_parse_log_pages(L):
    log = "Output written on paper.pdf (8 pages, 123456 bytes).\n"
    f = L.parse_log(log)
    assert f["pages"] == 8


def test_parse_log_fatal_error(L):
    log = "./paper.tex:12: Undefined control sequence.\n"
    f = L.parse_log(log)
    assert any("Undefined control sequence" in e for e in f["errors"])


def test_parse_log_clean(L):
    log = "Output written on paper.pdf (6 pages, 99 bytes).\n"
    f = L.parse_log(log)
    assert not f["errors"] and not f["undefined_refs"] and not f["overfull"]


# ── findings_to_checks：severity 滚动 ───────────────────────────
def test_checks_undefined_ref_is_fail(L):
    f = {"undefined_refs": ["fig:x"], "undefined_cites": [], "missing_files": [],
         "overfull": [], "underfull": 0, "errors": [], "pages": 6}
    checks, sev = L.findings_to_checks(f, pdf_ok=True)
    assert sev == "FAIL"
    assert any(c["name"] == "undefined_reference" and c["level"] == "FAIL" for c in checks)


def test_checks_missing_file_is_fail(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": ["a.png"],
         "overfull": [], "underfull": 0, "errors": [], "pages": 6}
    _, sev = L.findings_to_checks(f, pdf_ok=True)
    assert sev == "FAIL"


def test_checks_no_pdf_is_fail(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": [],
         "overfull": [], "underfull": 0, "errors": [], "pages": None}
    checks, sev = L.findings_to_checks(f, pdf_ok=False)
    assert sev == "FAIL"
    assert any(c["name"] == "no_pdf" for c in checks)


def test_checks_overfull_is_warn(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": [],
         "overfull": [{"pts": 20.0, "lines": "1--2"}], "underfull": 0, "errors": [], "pages": 6}
    _, sev = L.findings_to_checks(f, pdf_ok=True)
    assert sev == "WARN"


def test_checks_clean_is_pass(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": [],
         "overfull": [], "underfull": 0, "errors": [], "pages": 6}
    _, sev = L.findings_to_checks(f, pdf_ok=True)
    assert sev == "PASS"


def test_checks_fail_beats_warn(L):
    # 同时有溢出(WARN)与悬空引用(FAIL) → 滚动到 FAIL
    f = {"undefined_refs": ["x"], "undefined_cites": [], "missing_files": [],
         "overfull": [{"pts": 9.0, "lines": ""}], "underfull": 0, "errors": [], "pages": 6}
    _, sev = L.findings_to_checks(f, pdf_ok=True)
    assert sev == "FAIL"


# ── 页限：LaTeX 给页数，venue 上限是我们的规则 ──────────────────
def test_page_limit_over_is_warn(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": [],
         "overfull": [], "underfull": 0, "errors": [], "pages": 11}
    checks, sev = L.findings_to_checks(f, venue="neurips", pages=11, pdf_ok=True)
    assert sev == "WARN"
    assert any(c["name"] == "page_limit" and c["level"] == "WARN" for c in checks)


def test_page_limit_within_is_pass(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": [],
         "overfull": [], "underfull": 0, "errors": [], "pages": 8}
    checks, sev = L.findings_to_checks(f, venue="icml", pages=8, pdf_ok=True)
    assert sev == "PASS"
    assert any(c["name"] == "page_limit" and c["level"] == "PASS" for c in checks)


def test_page_limit_unknown_venue_no_check(L):
    f = {"undefined_refs": [], "undefined_cites": [], "missing_files": [],
         "overfull": [], "underfull": 0, "errors": [], "pages": 99}
    checks, _ = L.findings_to_checks(f, venue="nonexistent-venue", pages=99, pdf_ok=True)
    assert not any(c["name"] == "page_limit" for c in checks)


def test_venue_page_limits_mirror_skill_table(L):
    # 与 latex-fmt SKILL.md Phase 4 表对齐（抽查几条）
    assert L.VENUE_PAGE_LIMITS["neurips"] == 9
    assert L.VENUE_PAGE_LIMITS["icml"] == 8
    assert L.VENUE_PAGE_LIMITS["kdd"] == 10
    assert L.VENUE_PAGE_LIMITS["iclr"] is None


# ── check：无 TeX 工具链优雅降级 ────────────────────────────────
def test_check_no_texlive_degrades(L, tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}\\begin{document}hi\\end{document}", encoding="utf-8")
    monkeypatch.setattr(L.shutil, "which", lambda *a, **k: None)  # 模拟没装 TeX
    res = L.check(str(tex))
    assert res["ok"] is False
    assert res["severity"] == "ERROR"
    assert "TinyTeX" in res["error"]


def test_check_rejects_non_tex(L, tmp_path):
    bad = tmp_path / "paper.md"
    bad.write_text("# not tex", encoding="utf-8")
    res = L.check(str(bad))
    assert res["severity"] == "ERROR" and ".tex" in res["error"]


def test_check_rejects_missing_file(L, tmp_path):
    res = L.check(str(tmp_path / "nope.tex"))
    assert res["severity"] == "ERROR" and "不存在" in res["error"]
