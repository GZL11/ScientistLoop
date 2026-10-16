from __future__ import annotations

import threading
import sys
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "assets" / "opencode" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import search  # noqa: E402
from models import Paper  # noqa: E402


def paper(source: str, index: int) -> Paper:
    return Paper(
        paper_id=f"{source}-{index}",
        title=f"{source} paper {index}",
        authors=(),
        year=2026,
        abstract="",
        venue="",
        citation_count=index,
        doi=f"10.0/{source}-{index}",
        arxiv_id="",
        url="",
        source=source,
    )


def no_cache(monkeypatch):
    monkeypatch.setattr(
        search,
        "_cache_api",
        lambda: (lambda *_: None, lambda *_: None),
    )
    monkeypatch.setattr(search.time, "sleep", lambda *_: None)


def test_search_runs_all_three_sources_concurrently(monkeypatch):
    no_cache(monkeypatch)
    barrier = threading.Barrier(3)
    calls = []

    def source_result(source):
        calls.append(source)
        barrier.wait(timeout=1)
        return [paper(source, 1)]

    monkeypatch.setattr(search, "search_openalex", lambda *_, **__: source_result("oa"))
    monkeypatch.setattr(
        search, "search_semantic_scholar", lambda *_, **__: source_result("s2")
    )
    monkeypatch.setattr(search, "search_arxiv", lambda *_, **__: source_result("arxiv"))

    result = search.search_papers("vehicle CFD", limit=1)

    assert len(result) == 3
    assert set(calls) == {"oa", "s2", "arxiv"}


def test_source_failure_does_not_discard_other_results(monkeypatch):
    no_cache(monkeypatch)

    def fail_openalex(*_, **__):
        raise OSError("unavailable")

    monkeypatch.setattr(search, "search_openalex", fail_openalex)
    monkeypatch.setattr(
        search, "search_semantic_scholar", lambda *_, **__: [paper("s2", 1)]
    )
    monkeypatch.setattr(
        search, "search_arxiv", lambda *_, **__: [paper("arxiv", 1)]
    )

    result, diagnostics = search.search_papers_with_diagnostics(
        "vehicle CFD", limit=1
    )

    assert {item.source for item in result} == {"s2", "arxiv"}
    assert diagnostics[0]["source"] == "openalex"
    assert diagnostics[0]["status"] == "failed"
    assert [item["status"] for item in diagnostics[1:]] == ["ok", "ok"]


def test_legacy_exhaust_flag_does_not_change_source_coverage(monkeypatch):
    no_cache(monkeypatch)
    calls = []
    monkeypatch.setattr(
        search,
        "search_openalex",
        lambda *_, **__: calls.append("openalex") or [paper("oa", 1)],
    )
    monkeypatch.setattr(
        search,
        "search_semantic_scholar",
        lambda *_, **__: calls.append("s2") or [paper("s2", 1)],
    )
    monkeypatch.setattr(
        search,
        "search_arxiv",
        lambda *_, **__: calls.append("arxiv") or [paper("arxiv", 1)],
    )

    result = search.search_papers("vehicle CFD", limit=1, exhaust_sources=False)

    assert len(result) == 3
    assert set(calls) == {"openalex", "s2", "arxiv"}
