# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""latex_template 内核测试：venue→源解析、安全护栏（离线，不触网）。

只测可离线判定的部分：resolve() 的映射/别名/年份填充、未知 venue、
以及 fetch() 的越权护栏与 manual 分支。真实下载留给手动验证，CI 不触网。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import os
import sys
import tempfile
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
        import latex_template  # noqa: E402
        yield latex_template
    finally:
        sys.path.remove(sd)


def test_kernel_present():
    assert (_scripts_dir() / "latex_template.py").exists()


def test_resolve_year_filled(L):
    r = L.resolve("neurips")
    assert r["kind"] == "zip"
    assert "{year}" not in r["url"]
    assert str(r["year"]) in r["url"]  # 默认年份已填进 URL


def test_resolve_offline_default_is_current_year(L):
    # 不传 year、不 probe（离线）→ 名义填当年，绝不写死某旧年
    r = L.resolve("neurips")
    assert r["year"] == L._current_year()


def test_resolve_probe_picks_latest_available(L, monkeypatch):
    # probe=True 时从当年往回探，取第一个可达年份；这里仅放行 (当年-1)
    target = L._current_year() - 1
    monkeypatch.setattr(L, "_url_ok", lambda url, timeout=15: str(target) in url)
    r = L.resolve("neurips", probe=True)
    assert r["year"] == target
    assert r.get("latest") is True
    assert str(target) in r["url"]


def test_resolve_explicit_year_skips_probe(L, monkeypatch):
    # 显式传 year → 钉该年，不探测（即便 probe=True）
    monkeypatch.setattr(L, "_url_ok", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该探测")))
    r = L.resolve("neurips", year=2019, probe=True)
    assert r["year"] == 2019
    assert not r.get("latest")


def test_resolve_probe_all_missing_errors(L, monkeypatch):
    # 窗口内都不可达 → 诚实报错，不瞎填
    monkeypatch.setattr(L, "_url_ok", lambda *a, **k: False)
    r = L.resolve("neurips", probe=True)
    assert "error" in r and "未探测到" in r["error"]


def test_resolve_case_insensitive(L):
    assert L.resolve("NeurIPS")["venue"] == "neurips"


def test_resolve_alias(L):
    # emnlp/coling 复用 acl 的 files 源
    for v in ("emnlp", "coling"):
        r = L.resolve(v)
        assert r["kind"] == "files"
        assert any("acl" in u for u in r["urls"])


def test_resolve_manual_has_source(L):
    for v in ("nature", "science", "aaai", "interspeech"):
        r = L.resolve(v)
        assert r["kind"] == "manual"
        assert r.get("where")


def test_resolve_auto_github(L):
    # iclr/cvpr/tmlr 已从 manual 升级为 raw.github 自动源（files）
    for v in ("iclr", "cvpr", "tmlr"):
        r = L.resolve(v, probe=False)
        assert r["kind"] == "files"
        assert r["urls"]
    # iclr 带 {year}：resolve 后应已填成具体年份，不再残留占位
    r = L.resolve("iclr", probe=False)
    assert all("{year}" not in u for u in r["urls"])
    assert any("iclr" in u for u in r["urls"])


def test_resolve_unknown(L):
    assert "error" in L.resolve("definitely-not-a-venue")


def test_allowed_hosts_only(L):
    # 所有自动源必须落在白名单 host 内（防 SSRF）
    from urllib.parse import urlparse

    for venue, spec in L.SOURCES.items():
        if spec.get("kind") == "alias":
            spec = L.SOURCES[spec["of"]]
        urls = []
        if "url" in spec:
            urls.append(spec["url"])
        urls += spec.get("urls", [])
        for u in urls:
            host = urlparse(u.replace("{year}", "2024")).hostname
            assert host in L._ALLOWED_HOSTS, f"{venue}: {host} 不在白名单"


def test_fetch_manual_no_download(L):
    r = L.fetch("nature", "deliverables")
    assert r.get("manual") is True
    assert r["placed"] == []


def test_fetch_dest_escape_blocked(L):
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            r = L.fetch("ieee", "../../../etc")
            assert "error" in r and "越出" in r["error"]
        finally:
            os.chdir(cwd)


def test_place_zip_skips_apple_double(L):
    # 合成 zip：真类文件 + macOS 垃圾(._xxx / __MACOSX/)——只应落真文件，不写垃圾
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("neurips_2024.sty", "% real")
        zf.writestr("._neurips_2024.sty", "appledouble junk")
        zf.writestr("__MACOSX/._neurips_2024.sty", "junk")
    with tempfile.TemporaryDirectory() as d:
        placed = L._place_zip(buf.getvalue(), d)
        assert placed == ["neurips_2024.sty"]
        # 目录里也不该出现 ._ 隐藏垃圾
        assert sorted(os.listdir(d)) == ["neurips_2024.sty"]
