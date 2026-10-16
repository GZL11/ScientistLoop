"""Fetch a cited source's abstract for claim-faithfulness ("L3") auditing.

Citation *existence* verification (verify.py) only confirms a paper is real and
its title matches. It does NOT check whether the cited source actually supports
the claim the paper attributes to it — the most common real-world citation
failure ("real reference deployed to support a claim it does not make").

This kernel closes the gap on the retrieval side: given a title / arXiv id / DOI,
it locates the best-matching real paper and returns its **abstract**, so the
agent (or an independent subagent) can judge SUPPORTED / UNSUPPORTED / AMBIGUOUS.
Abstract-level only — full text is usually paywalled — so the judgment is
advisory, not a hard gate.

Self-contained: reuses the literature-search clients (OpenAlex / Semantic
Scholar / arXiv) already used by ``search.py``. No researchclaw dependency.

Public API
----------
- ``fetch_source(title="", arxiv_id="", doi="") -> dict``
  Returns ``{found, title, abstract, abstract_available, year, venue, doi,
  arxiv_id, source, match_similarity}`` on a hit, or ``{found: False, reason}``.
"""

from __future__ import annotations

import re
from typing import Any

from search import search_papers


def _normalise(title: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace (for fuzzy matching)."""
    t = re.sub(r"[^a-z0-9\s]", "", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def _title_overlap(a: str, b: str) -> float:
    """Jaccard word-overlap between two titles (0.0–1.0)."""
    wa = set(_normalise(a).split())
    wb = set(_normalise(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def fetch_source(title: str = "", arxiv_id: str = "", doi: str = "") -> dict[str, Any]:
    """Locate a cited source and return its abstract for claim-faithfulness audit.

    Matching priority: exact arXiv id / DOI → fuzzy title overlap. Returns the
    best candidate only if it is a confident match (id hit, or title overlap
    ≥ 0.5), otherwise reports ``found: False`` rather than guess.
    """
    title = (title or "").strip()
    arxiv_id = (arxiv_id or "").strip()
    doi = (doi or "").strip()

    query = title or arxiv_id or doi
    if not query:
        return {"found": False, "reason": "需要 title / arxiv_id / doi 至少一项"}

    papers = search_papers(query, limit=8)
    if not papers:
        return {"found": False, "reason": "未检索到候选文献", "query": query}

    best = None
    best_score = -1.0
    for p in papers:
        if arxiv_id and p.arxiv_id and arxiv_id in p.arxiv_id:
            score = 1.0
        elif doi and p.doi and doi.lower() == p.doi.lower():
            score = 1.0
        elif title:
            score = _title_overlap(title, p.title)
        else:
            # only an id was given but it didn't match this candidate
            score = 0.0
        if score > best_score:
            best_score = score
            best = p

    if best is None or best_score < 0.5:
        return {
            "found": False,
            "reason": "候选与目标不匹配（相似度过低，疑似查无此文）",
            "query": query,
            "best_similarity": round(max(best_score, 0.0), 3),
        }

    abstract = (best.abstract or "").strip()
    return {
        "found": True,
        "title": best.title,
        "abstract": abstract,
        "abstract_available": bool(abstract),
        "year": getattr(best, "year", None),
        "venue": best.venue,
        "doi": best.doi,
        "arxiv_id": best.arxiv_id,
        "source": best.source,
        "match_similarity": round(best_score, 3),
    }
