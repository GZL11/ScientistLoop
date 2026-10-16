from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "assets" / "opencode" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from paper_lookup import lookup_paper  # noqa: E402


def test_lookup_paper_fuses_web_typo_candidate(monkeypatch):
    monkeypatch.setattr("paper_lookup.search_papers", lambda *args, **kwargs: [])
    monkeypatch.setattr("paper_lookup.get_paper_by_id", lambda *args, **kwargs: None)

    result = lookup_paper(
        "InterAgent 1.5",
        web_results=[
            {
                "title": "InternAgent-1.5: A Unified Agentic Framework for Long-Horizon Autonomous Scientific Discovery",
                "url": "https://arxiv.org/abs/2602.08990",
                "snippet": "arXiv:2602.08990 Shanghai AI Laboratory",
            }
        ],
    )

    assert result["confidence"] == "high"
    assert result["needs_confirmation"] is False
    assert result["best_candidate"]["arxiv_id"] == "2602.08990"
    assert "InternAgent-1.5" in result["best_candidate"]["title"]


def test_lookup_paper_requires_confirmation_for_weak_candidate(monkeypatch):
    monkeypatch.setattr("paper_lookup.search_papers", lambda *args, **kwargs: [])
    monkeypatch.setattr("paper_lookup.get_paper_by_id", lambda *args, **kwargs: None)

    result = lookup_paper(
        "UniOPD",
        web_results=[
            {
                "title": "A Generic Survey of Artificial Intelligence",
                "url": "https://example.com/survey",
                "snippet": "Unrelated content",
            }
        ],
    )

    assert result["confidence"] == "low"
    assert result["needs_confirmation"] is True
