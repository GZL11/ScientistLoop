"""Unified literature search with deduplication.

Combines results from OpenAlex, Semantic Scholar, and arXiv,
deduplicates by DOI → arXiv ID → fuzzy title match, and returns
a merged list sorted by citation count (descending).

OpenAlex, Semantic Scholar, and arXiv run concurrently. A failed source falls
back to its local cache without delaying or disabling the other sources.

Public API
----------
- ``search_papers(query, limit, sources, year_min, deduplicate)``
  → ``list[Paper]``
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
import importlib
import logging
import re
import time
import urllib.error
from typing import cast

from arxiv_client import search_arxiv
from models import Author, Paper
from openalex_client import search_openalex
from semantic_scholar import search_semantic_scholar

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES = ("openalex", "semantic_scholar", "arxiv")


CacheGet = Callable[[str, str, int], list[dict[str, object]] | None]
CachePut = Callable[[str, str, int, list[dict[str, object]]], None]


def _cache_api() -> tuple[CacheGet, CachePut]:
    cache_mod = importlib.import_module("cache")
    return cast(CacheGet, cache_mod.get_cached), cast(CachePut, cache_mod.put_cache)


def _papers_to_dicts(papers: list[Paper]) -> list[dict[str, object]]:
    """Convert papers to serializable dicts for caching."""
    return [asdict(p) for p in papers]


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _dicts_to_papers(dicts: list[dict[str, object]]) -> list[Paper]:
    """Reconstruct Paper objects from cached dicts."""
    papers: list[Paper] = []
    for d in dicts:
        try:
            authors_raw = d.get("authors", ())
            if not isinstance(authors_raw, list):
                authors_raw = []
            authors = tuple(
                Author(
                    name=str(cast(dict[str, object], a).get("name", "")),
                    affiliation=str(cast(dict[str, object], a).get("affiliation", "")),
                )
                for a in authors_raw
                if isinstance(a, dict)
            )
            paper_id = cast(str, d["paper_id"])
            title = cast(str, d["title"])
            papers.append(
                Paper(
                    paper_id=paper_id,
                    title=title,
                    authors=authors,
                    year=_as_int(d.get("year", 0), 0),
                    abstract=str(d.get("abstract", "")),
                    venue=str(d.get("venue", "")),
                    citation_count=_as_int(d.get("citation_count", 0), 0),
                    doi=str(d.get("doi", "")),
                    arxiv_id=str(d.get("arxiv_id", "")),
                    url=str(d.get("url", "")),
                    source=str(d.get("source", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return papers


def search_papers(
    query: str,
    *,
    limit: int = 20,
    sources: Sequence[str] = _DEFAULT_SOURCES,
    year_min: int = 0,
    deduplicate: bool = True,
    s2_api_key: str = "",
    exhaust_sources: bool = False,
) -> list[Paper]:
    """Search all configured academic sources concurrently."""
    papers, _ = search_papers_with_diagnostics(
        query,
        limit=limit,
        sources=sources,
        year_min=year_min,
        deduplicate=deduplicate,
        s2_api_key=s2_api_key,
        exhaust_sources=exhaust_sources,
    )
    return papers


def search_papers_with_diagnostics(
    query: str,
    *,
    limit: int = 20,
    sources: Sequence[str] = _DEFAULT_SOURCES,
    year_min: int = 0,
    deduplicate: bool = True,
    s2_api_key: str = "",
    exhaust_sources: bool = False,
) -> tuple[list[Paper], list[dict[str, object]]]:
    """Search every configured source concurrently and report source status.

    ``exhaust_sources`` remains accepted for compatibility. All requested
    sources are now always queried, regardless of mode or candidate count.
    """
    del exhaust_sources
    cache_get: CacheGet
    cache_put: CachePut
    cache_get, cache_put = _cache_api()

    source_names: list[str] = []
    for source in sources:
        normalized = source.lower().replace("-", "_").replace(" ", "_")
        if normalized == "s2":
            normalized = "semantic_scholar"
        if normalized not in _DEFAULT_SOURCES:
            logger.warning("Unknown literature source: %s (skipped)", source)
            continue
        if normalized not in source_names:
            source_names.append(normalized)

    def search_one(source: str) -> tuple[list[Paper], dict[str, object]]:
        started = time.monotonic()
        try:
            if source == "openalex":
                papers = search_openalex(query, limit=limit, year_min=year_min)
            elif source == "semantic_scholar":
                papers = search_semantic_scholar(
                    query,
                    limit=limit,
                    year_min=year_min,
                    api_key=s2_api_key,
                )
            else:
                papers = search_arxiv(query, limit=limit, year_min=year_min)

            try:
                cache_put(query, source, limit, _papers_to_dicts(papers))
            except (OSError, TypeError, ValueError):
                logger.warning(
                    "Could not cache results for %s/%r", source, query
                )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            logger.info("%s returned %d papers for %r", source, len(papers), query)
            return papers, {
                "source": source,
                "status": "ok",
                "count": len(papers),
                "elapsed_ms": elapsed_ms,
            }
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as error:
            logger.warning(
                "[retrieval] Source %s failed for %r — trying cache", source, query
            )
            try:
                cached = cache_get(query, source, limit)
            except (OSError, TypeError, ValueError):
                cached = None
                logger.warning(
                    "Could not read cached results for %s/%r", source, query
                )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            if cached:
                papers = _dicts_to_papers(cached)
                logger.info(
                    "[cache] HIT: %d papers for %s/%r", len(papers), source, query
                )
                return papers, {
                    "source": source,
                    "status": "cache",
                    "count": len(papers),
                    "elapsed_ms": elapsed_ms,
                    "error": type(error).__name__,
                }
            logger.warning("No cache available for %s/%r — skipping", source, query)
            return [], {
                "source": source,
                "status": "failed",
                "count": 0,
                "elapsed_ms": elapsed_ms,
                "error": type(error).__name__,
            }

    results: dict[str, list[Paper]] = {}
    diagnostics: dict[str, dict[str, object]] = {}
    if source_names:
        with ThreadPoolExecutor(
            max_workers=len(source_names), thread_name_prefix="literature-source"
        ) as executor:
            futures = {executor.submit(search_one, source): source for source in source_names}
            for future in as_completed(futures):
                source = futures[future]
                papers, status = future.result()
                results[source] = papers
                diagnostics[source] = status

    all_papers = [paper for source in source_names for paper in results.get(source, [])]
    source_diagnostics = [
        diagnostics[source] for source in source_names if source in diagnostics
    ]

    total = len(all_papers)
    parts = [
        f"{status['source']}: {status['count']} ({status['status']})"
        for status in source_diagnostics
    ]
    logger.info(
        "[literature] Found %d papers (%s) for %r",
        total,
        ", ".join(parts) if parts else "none",
        query,
    )

    if deduplicate:
        all_papers = _deduplicate(all_papers)
    all_papers.sort(key=lambda p: (p.citation_count, p.year), reverse=True)
    return all_papers, source_diagnostics


def search_papers_multi_query(
    queries: list[str],
    *,
    limit_per_query: int = 20,
    sources: Sequence[str] = _DEFAULT_SOURCES,
    year_min: int = 0,
    s2_api_key: str = "",
    inter_query_delay: float = 1.5,
) -> list[Paper]:
    """Run multiple queries and return deduplicated union.

    Adds a delay between queries to respect rate limits.
    """
    all_papers: list[Paper] = []

    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(inter_query_delay)
        results = search_papers(
            q,
            limit=limit_per_query,
            sources=sources,
            year_min=year_min,
            s2_api_key=s2_api_key,
            deduplicate=False,  # we dedup globally below
        )
        all_papers.extend(results)
        logger.info("Query %d/%d %r → %d papers", i + 1, len(queries), q, len(results))

    deduped = _deduplicate(all_papers)
    deduped.sort(key=lambda p: (p.citation_count, p.year), reverse=True)
    return deduped


# ------------------------------------------------------------------
# Deduplication
# ------------------------------------------------------------------


def _normalise_title(title: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _deduplicate(papers: list[Paper]) -> list[Paper]:
    """Remove duplicates.  Priority: DOI > arXiv ID > fuzzy title.

    When a duplicate is found, the entry with higher citation_count wins
    (i.e. Semantic Scholar data is preferred over arXiv-only data).
    """
    seen_doi: dict[str, int] = {}
    seen_arxiv: dict[str, int] = {}
    seen_title: dict[str, int] = {}
    result: list[Paper] = []

    def _update_indices(p: Paper, idx: int) -> None:
        """Register all identifiers of *p* in the lookup dicts at *idx*."""
        if p.doi:
            seen_doi[p.doi.lower().strip()] = idx
        if p.arxiv_id:
            seen_arxiv[p.arxiv_id.strip()] = idx
        norm = _normalise_title(p.title)
        if norm:
            seen_title[norm] = idx

    def _replace_at(old: Paper, new: Paper, idx: int) -> None:
        """Replace paper at *idx* and clean up stale index entries."""
        # Remove old identifiers that the new paper does NOT share
        if old.doi:
            old_doi = old.doi.lower().strip()
            new_doi = new.doi.lower().strip() if new.doi else ""
            if old_doi != new_doi and seen_doi.get(old_doi) == idx:
                del seen_doi[old_doi]
        if old.arxiv_id:
            old_ax = old.arxiv_id.strip()
            new_ax = new.arxiv_id.strip() if new.arxiv_id else ""
            if old_ax != new_ax and seen_arxiv.get(old_ax) == idx:
                del seen_arxiv[old_ax]
        old_norm = _normalise_title(old.title)
        new_norm = _normalise_title(new.title)
        if old_norm and old_norm != new_norm and seen_title.get(old_norm) == idx:
            del seen_title[old_norm]
        result[idx] = new
        _update_indices(new, idx)

    def _enrich(primary: Paper, secondary: Paper) -> Paper:
        """Backfill *primary*'s empty fields from *secondary* (a duplicate).

        Citation winner keeps its metadata, but we never throw away an
        identifier the other source had: e.g. OpenAlex often wins on citation
        count yet lacks ``arxiv_id``, while the arXiv copy carries it — merging
        means the survivor still links to free full text. Also adopt the longer
        abstract (OpenAlex/S2 sometimes truncate; arXiv has the full summary).
        """
        updates: dict[str, object] = {}
        if not primary.arxiv_id and secondary.arxiv_id:
            updates["arxiv_id"] = secondary.arxiv_id
        if not primary.doi and secondary.doi:
            updates["doi"] = secondary.doi
        if not primary.url and secondary.url:
            updates["url"] = secondary.url
        if len(secondary.abstract or "") > len(primary.abstract or ""):
            updates["abstract"] = secondary.abstract
        return replace(primary, **updates) if updates else primary

    def _merge_dup(idx: int, paper: Paper) -> None:
        """Resolve a detected duplicate at *idx* against incoming *paper*."""
        existing = result[idx]
        if paper.citation_count > existing.citation_count:
            winner, loser = paper, existing
        else:
            winner, loser = existing, paper
        merged = _enrich(winner, loser)
        if merged is not existing:
            _replace_at(existing, merged, idx)

    for paper in papers:
        is_dup = False

        # Check DOI
        if paper.doi:
            doi_key = paper.doi.lower().strip()
            if doi_key in seen_doi:
                _merge_dup(seen_doi[doi_key], paper)
                is_dup = True

        # Check arXiv ID
        if not is_dup and paper.arxiv_id:
            ax_key = paper.arxiv_id.strip()
            if ax_key in seen_arxiv:
                _merge_dup(seen_arxiv[ax_key], paper)
                is_dup = True

        # Check fuzzy title
        if not is_dup:
            norm = _normalise_title(paper.title)
            if norm and norm in seen_title:
                _merge_dup(seen_title[norm], paper)
                is_dup = True

        if is_dup:
            continue

        # Not a duplicate — store indices and append
        new_idx = len(result)
        _update_indices(paper, new_idx)
        result.append(paper)

    return result


def papers_to_bibtex(papers: Sequence[Paper]) -> str:
    """Generate a combined BibTeX file from a list of papers."""
    entries = [p.to_bibtex() for p in papers]
    return "\n\n".join(entries) + "\n"
