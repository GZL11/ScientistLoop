# -*- coding: UTF-8 -*-
"""单测：famou_rcb 的产物搬运逻辑（不真跑 famou、不调 judge）。

验证「把 famou 的 research-runs 产物搬进 RCB report/ 布局」的确定性逻辑：
选 paper、figures/→images/ 链接重写、拷 png、排除 reviews/citations、空 workspace 兜底。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 适配器脚本住在本目录上一级（benchmark/researchclawbench/famou_rcb.py），不在 pip 包里。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import famou_rcb as rcb  # noqa: E402


def test_rewrite_fig_links():
    assert rcb._rewrite_fig_links("![](figures/a.png)") == "![](images/a.png)"
    assert rcb._rewrite_fig_links("![x](./figures/b.png)") == "![x](images/b.png)"
    # 非图前缀的 figures 不动
    assert rcb._rewrite_fig_links("[ref](http://x/figures/no)") == "[ref](http://x/figures/no)"
    # 正文里的 figures 字样不动（只动 markdown 链接语法）
    assert rcb._rewrite_fig_links("see figures/ below") == "see figures/ below"


def _make_run(ws, *, paper_name="paper.md", with_reviews=True):
    deliv = ws / "research-runs" / "topicX" / "deliverables"
    deliv.mkdir(parents=True)
    (deliv / paper_name).write_text("# Paper\n\n![fig1](figures/f1.png)\n", encoding="utf-8")
    figs = ws / "research-runs" / "topicX" / "figures"
    figs.mkdir(parents=True)
    (figs / "f1.png").write_bytes(b"\x89PNG\r\n")
    if with_reviews:
        (deliv / "reviews.md").write_text("# Reviews", encoding="utf-8")
        (deliv / "citations.md").write_text("# Citations", encoding="utf-8")
    return deliv


def test_map_deliverables_happy(tmp_path):
    _make_run(tmp_path)
    ok = rcb._map_deliverables(tmp_path)
    assert ok is True
    report = tmp_path / "report" / "report.md"
    assert report.is_file() and report.stat().st_size > 0
    # 图链接被重写为 images/
    assert "](images/f1.png)" in report.read_text(encoding="utf-8")
    assert "](figures/" not in report.read_text(encoding="utf-8")
    # png 拷进 report/images/
    assert (tmp_path / "report" / "images" / "f1.png").is_file()


def test_map_deliverables_excludes_reviews(tmp_path):
    # 没有 paper.md，只有 reviews/citations + 一个真正的论文 .md → 应选论文、排除 reviews/citations
    deliv = tmp_path / "research-runs" / "topicX" / "deliverables"
    deliv.mkdir(parents=True)
    (deliv / "reviews.md").write_text("# Reviews", encoding="utf-8")
    (deliv / "citations.md").write_text("# Citations", encoding="utf-8")
    (deliv / "final_writeup.md").write_text("# Real Paper\n本体", encoding="utf-8")
    picked = rcb._pick_paper(deliv)
    assert picked is not None and picked.name == "final_writeup.md"


def test_map_deliverables_prefers_paper_md(tmp_path):
    deliv = _make_run(tmp_path)
    (deliv / "other.md").write_text("# other", encoding="utf-8")
    picked = rcb._pick_paper(deliv)
    assert picked.name == "paper.md"


def test_map_deliverables_empty_workspace(tmp_path):
    # 没有任何 research-runs → 搬运失败、不报错
    assert rcb._map_deliverables(tmp_path) is False


def test_parse_workspace_forms():
    assert rcb._parse_workspace(["-w", "/a/b"]) == "/a/b"
    assert rcb._parse_workspace(["--workspace=/c/d"]) == "/c/d"
    # 缺省 → cwd（非空）
    assert rcb._parse_workspace([]) != ""
