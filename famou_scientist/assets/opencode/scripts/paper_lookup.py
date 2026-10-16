"""Paper lookup with academic + web candidate fusion.

This module is intentionally lightweight and stdlib-only.  It is used by the
OpenCode tool layer when the user appears to ask for a specific paper by a
possibly misspelled title, acronym, versioned name, DOI, or arXiv ID.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from difflib import SequenceMatcher
from typing import Any

from arxiv_client import get_paper_by_id
from models import Paper
from search import search_papers


_ARXIV_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
_VERSION_RE = re.compile(r"\b(?:v?\d+(?:\.\d+)+)\b", re.I)
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "paper",
    "the",
    "this",
}


def _norm(text: str) -> str:
    return " ".join(_WORD_RE.findall((text or "").lower()))


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _meaningful_tokens(text: str) -> set[str]:
    versions = set()
    for v in _versions(text):
        versions.update(_tokens(v))
    return {
        t
        for t in _tokens(text)
        if t not in _STOP_TOKENS and t not in versions and not t.isdigit() and len(t) >= 3
    }


def _token_matches(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.86


def _core_match_ratio(query: str, text: str) -> float:
    qt = _meaningful_tokens(query)
    if not qt:
        return 1.0
    tt = _meaningful_tokens(text)
    if not tt:
        return 0.0
    hits = sum(1 for q in qt if any(_token_matches(q, t) for t in tt))
    return hits / len(qt)


def _has_core_match(query: str, *texts: str) -> bool:
    qt = _meaningful_tokens(query)
    if not qt:
        return True
    joined = " ".join(t or "" for t in texts)
    return _core_match_ratio(query, joined) > 0


def _versions(text: str) -> set[str]:
    return {m.group(0).lower().lstrip("v") for m in _VERSION_RE.finditer(text or "")}


def _arxiv_id(text: str) -> str:
    text = text or ""
    m = _ARXIV_URL_RE.search(text)
    if m:
        return m.group(1)
    m = _ARXIV_ID_RE.search(text)
    return m.group(1) if m else ""


def _doi(text: str) -> str:
    m = _DOI_RE.search(text or "")
    return m.group(0).rstrip(").,;").lower() if m else ""


def _acronym(text: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", text or "") if w]
    if not words:
        return ""
    # Preserve mixed/camel/versioned paper names such as Uni-OPD, MLS-Bench.
    caps = "".join(w[0] for w in words if w and w[0].isalpha())
    return caps.lower()


def _title_score(query: str, title: str) -> float:
    qn, tn = _norm(query), _norm(title)
    if not qn or not tn:
        return 0.0
    seq = SequenceMatcher(None, qn, tn).ratio()
    overlap = _core_match_ratio(query, title)
    containment = 1.0 if qn in tn or tn in qn else 0.0
    score = 0.55 * seq + 0.35 * overlap + 0.10 * containment

    qv = _versions(query)
    if qv:
        score += 0.08 if qv & _versions(title) else -0.08

    qa, ta = _acronym(query), _acronym(title)
    if qa and len(qa) >= 3 and ta and qa == ta:
        score += 0.12

    # Typo-friendly path for long paper-name tokens with high character
    # similarity but low exact token overlap. Keep this as a modest bump rather
    # than a hard match.
    if seq >= 0.82:
        score += 0.08
    if _meaningful_tokens(query) and overlap <= 0:
        score = min(score, 0.28)
    return max(0.0, min(1.0, score))


def _trusted_url_score(url: str) -> float:
    u = (url or "").lower()
    trusted = [
        "arxiv.org",
        "openreview.net",
        "biorxiv.org",
        "medrxiv.org",
        "aclanthology.org",
        "proceedings.mlr.press",
        "papers.nips.cc",
        "proceedings.neurips.cc",
        "doi.org",
        "dl.acm.org",
        "ieeexplore.ieee.org",
        "nature.com",
        "science.org",
        "github.com",
    ]
    for host in trusted:
        if host in u:
            return 0.10 if host == "github.com" else 0.18
    return 0.0


def _paper_to_candidate(p: Paper, query: str, source: str) -> dict[str, Any]:
    score = _title_score(query, p.title)
    if _doi(query) and p.doi and _doi(query) == p.doi.lower():
        score = 1.0
    if _arxiv_id(query) and p.arxiv_id and _arxiv_id(query) == p.arxiv_id:
        score = 1.0
    score += _trusted_url_score(p.url)
    if p.abstract and _tokens(query) & _tokens(p.abstract):
        score += 0.04
    if not _has_core_match(query, p.title, p.abstract, p.url, p.doi, p.arxiv_id):
        score = min(score, 0.25)
    return {
        "title": p.title,
        "authors": [a.name for a in p.authors[:6]],
        "year": p.year,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "url": p.url,
        "venue": p.venue,
        "source": source or p.source,
        "score": round(min(1.0, score), 3),
        "evidence": ["academic_search"],
        "abstract": (p.abstract or "")[:500],
    }


def _web_candidate(item: dict[str, Any], query: str) -> dict[str, Any]:
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()
    snippet = str(item.get("snippet") or "").strip()
    ax = _arxiv_id(url + " " + snippet + " " + title)
    doi = _doi(url + " " + snippet + " " + title)
    score = max(_title_score(query, title), _title_score(query, snippet) * 0.82)
    score += _trusted_url_score(url)
    if ax or doi:
        score += 0.15
    if not _has_core_match(query, title, snippet, url):
        score = min(score, 0.25)
    return {
        "title": title or url,
        "authors": [],
        "year": None,
        "doi": doi,
        "arxiv_id": ax,
        "url": url,
        "venue": "",
        "source": "web_search",
        "score": round(min(1.0, score), 3),
        "evidence": ["web_search"],
        "snippet": snippet[:500],
    }


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index: dict[str, int] = {}

    def keys(c: dict[str, Any]) -> list[str]:
        out: list[str] = []
        if c.get("doi"):
            out.append("doi:" + str(c["doi"]).lower())
        if c.get("arxiv_id"):
            out.append("arxiv:" + str(c["arxiv_id"]))
        nt = _norm(str(c.get("title") or ""))
        if nt:
            out.append("title:" + nt)
        return out

    for c in candidates:
        hit = None
        for k in keys(c):
            if k in index:
                hit = index[k]
                break
        if hit is None:
            index_id = len(merged)
            merged.append(c)
            for k in keys(c):
                index[k] = index_id
            continue
        old = merged[hit]
        old_score = float(old.get("score") or 0)
        new_score = float(c.get("score") or 0)
        winner, loser = (c, old) if new_score > old_score else (old, c)
        evidence = sorted(set(old.get("evidence") or []) | set(c.get("evidence") or []))
        winner = dict(winner)
        winner["evidence"] = evidence
        winner["score"] = round(min(1.0, max(old_score, new_score) + (0.08 if len(evidence) > 1 else 0)), 3)
        for field in ("authors", "year", "doi", "arxiv_id", "url", "venue", "abstract", "snippet"):
            if not winner.get(field) and loser.get(field):
                winner[field] = loser[field]
        merged[hit] = winner
        for k in keys(winner):
            index[k] = hit
    return sorted(merged, key=lambda x: float(x.get("score") or 0), reverse=True)


def _enrich_arxiv(candidates: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in candidates:
        ax = str(c.get("arxiv_id") or "")
        if ax and not c.get("authors"):
            p = get_paper_by_id(ax)
            if p:
                enriched = _paper_to_candidate(p, query, "web_search+arxiv")
                enriched["evidence"] = sorted(set(c.get("evidence") or []) | {"arxiv_id_lookup"})
                enriched["score"] = round(min(1.0, max(float(c.get("score") or 0), float(enriched["score"])) + 0.05), 3)
                out.append(enriched)
                continue
        out.append(c)
    return out


def _query_variants(query: str) -> list[str]:
    variants = [query]
    if "-" in query:
        variants.append(query.replace("-", " "))
    else:
        variants.append(query.replace(" ", "-"))
    return variants


def lookup_paper(query: str, *, limit: int = 5, web_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"query": query, "candidates": [], "needs_confirmation": True, "confidence": "none"}

    candidates: list[dict[str, Any]] = []
    ax = _arxiv_id(query)
    if ax:
        p = get_paper_by_id(ax)
        if p:
            candidates.append(_paper_to_candidate(p, query, "arxiv_id_lookup"))

    # Search with the original phrase plus a small number of high-precision
    # variants.  Paper Lookup is not a broad survey.
    variants = _query_variants(query)
    seen_variant: set[str] = set()
    for q in variants:
        qn = q.lower().strip()
        if not qn or qn in seen_variant:
            continue
        seen_variant.add(qn)
        for p in search_papers(q, limit=max(8, limit * 2), deduplicate=True):
            candidates.append(_paper_to_candidate(p, query, "academic_search"))

    for item in web_results or []:
        if isinstance(item, dict):
            candidates.append(_web_candidate(item, query))

    merged = _enrich_arxiv(_merge_candidates(candidates), query)
    merged = [
        c
        for c in merged
        if _has_core_match(
            query,
            str(c.get("title") or ""),
            str(c.get("abstract") or ""),
            str(c.get("snippet") or ""),
            str(c.get("url") or ""),
            str(c.get("doi") or ""),
            str(c.get("arxiv_id") or ""),
        )
        or float(c.get("score") or 0) >= 0.9
    ]
    top = merged[:limit]
    best = top[0] if top else None
    best_score = float(best.get("score") or 0) if best else 0.0
    second_score = float(top[1].get("score") or 0) if len(top) > 1 else 0.0
    confidence = "high" if best_score >= 0.78 and best_score - second_score >= 0.08 else "medium" if best_score >= 0.52 else "low"
    return {
        "query": query,
        "confidence": confidence,
        "needs_confirmation": confidence != "high",
        "best_candidate": best,
        "candidates": top,
        "notes": [
            "Use needs_confirmation=true to ask the user before reading a medium/low-confidence candidate.",
            "Scores combine academic search, web search, title similarity, trusted URLs, arXiv/DOI/version matches.",
        ],
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--web-results-json", default="")
    args = ap.parse_args()
    web_results: list[dict[str, Any]] = []
    if args.web_results_json:
        raw = json.loads(args.web_results_json)
        if isinstance(raw, list):
            web_results = [x for x in raw if isinstance(x, dict)]
    print(json.dumps(lookup_paper(args.query, limit=args.limit, web_results=web_results), ensure_ascii=False))


if __name__ == "__main__":
    main()
