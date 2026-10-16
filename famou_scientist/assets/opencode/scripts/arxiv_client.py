"""arXiv API client.

Primary backend is the ``arxiv`` pip package (2.4+) when installed: robust
search with built-in rate limiting, retries, pagination, and PDF download.

When the library is **not** installed, we fall back to the public
``export.arxiv.org/api/query`` Atom API using only the standard library
(``urllib`` + ``xml.etree``) — so arXiv search keeps working with zero deps.

Public API
----------
- ``search_arxiv(query, limit, sort_by, year_min)`` → ``list[Paper]``
- ``download_pdf(arxiv_id, dirpath)`` → ``Path | None``
- ``get_paper_by_id(arxiv_id)`` → ``Paper | None``

Circuit breaker is preserved for extra resilience beyond the library's
built-in retry logic.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import arxiv  # pip install arxiv
except ImportError:
    arxiv = None  # type: ignore[assignment]

from models import Author, Paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Circuit breaker (kept for extra safety on top of arxiv library retries)
# ---------------------------------------------------------------------------

_CB_THRESHOLD = 3
_CB_INITIAL_COOLDOWN = 180
_CB_MAX_COOLDOWN = 600

_CB_CLOSED = "closed"
_CB_OPEN = "open"
_CB_HALF_OPEN = "half_open"

_cb_state: str = _CB_CLOSED
_cb_consecutive_429s: int = 0
_cb_cooldown_sec: float = _CB_INITIAL_COOLDOWN
_cb_open_since: float = 0.0
_cb_trip_count: int = 0
_cb_lock = threading.Lock()


def _reset_circuit_breaker() -> None:
    """Reset circuit breaker state (for tests)."""
    global _cb_state, _cb_consecutive_429s, _cb_cooldown_sec  # noqa: PLW0603
    global _cb_open_since, _cb_trip_count  # noqa: PLW0603
    with _cb_lock:
        _cb_state = _CB_CLOSED
        _cb_consecutive_429s = 0
        _cb_cooldown_sec = _CB_INITIAL_COOLDOWN
        _cb_open_since = 0.0
        _cb_trip_count = 0


def _cb_should_allow() -> bool:
    global _cb_state  # noqa: PLW0603
    with _cb_lock:
        if _cb_state == _CB_CLOSED:
            return True
        if _cb_state == _CB_OPEN:
            elapsed = time.monotonic() - _cb_open_since
            if elapsed >= _cb_cooldown_sec:
                _cb_state = _CB_HALF_OPEN
                logger.info("arXiv circuit breaker → HALF_OPEN (%.0fs cooldown elapsed)", elapsed)
                return True
            return False
        return True  # HALF_OPEN: allow probe


def _cb_on_success() -> None:
    global _cb_state, _cb_consecutive_429s, _cb_cooldown_sec  # noqa: PLW0603
    with _cb_lock:
        _cb_consecutive_429s = 0
        if _cb_state != _CB_CLOSED:
            logger.info("arXiv circuit breaker → CLOSED (request succeeded)")
            _cb_state = _CB_CLOSED
            _cb_cooldown_sec = _CB_INITIAL_COOLDOWN


def _cb_on_failure() -> bool:
    global _cb_state, _cb_consecutive_429s, _cb_cooldown_sec  # noqa: PLW0603
    global _cb_open_since, _cb_trip_count  # noqa: PLW0603
    with _cb_lock:
        _cb_consecutive_429s += 1
        if _cb_state == _CB_HALF_OPEN or _cb_consecutive_429s >= _CB_THRESHOLD:
            if _cb_state == _CB_HALF_OPEN:
                _cb_cooldown_sec = min(_cb_cooldown_sec * 2, _CB_MAX_COOLDOWN)
            _cb_state = _CB_OPEN
            _cb_open_since = time.monotonic()
            _cb_trip_count += 1
            logger.warning(
                "arXiv circuit breaker TRIPPED (trip #%d, cooldown %.0fs)",
                _cb_trip_count, _cb_cooldown_sec,
            )
            return True
        return False


# ---------------------------------------------------------------------------
# Shared arxiv.Client instance (reuses connection, respects rate limits)
# ---------------------------------------------------------------------------

_client: arxiv.Client | None = None


def _get_client() -> arxiv.Client:
    """Get or create the shared arxiv Client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = arxiv.Client(
            page_size=100,       # fetch up to 100 per API call
            delay_seconds=3.1,   # arXiv requires ≥3s between requests
            num_retries=3,       # tolerate transient source/network failures
        )
    return _client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_arxiv(
    query: str,
    *,
    limit: int = 50,
    sort_by: str = "relevance",
    year_min: int = 0,
) -> list[Paper]:
    """Search arXiv for papers matching *query*.

    Parameters
    ----------
    query:
        Free-text search query. Supports arXiv field syntax
        (e.g., ``ti:transformer``, ``au:vaswani``, ``cat:cs.LG``).
    limit:
        Maximum number of results (up to 300).
    sort_by:
        Sort criterion: "relevance", "submitted_date", or "last_updated".
    year_min:
        If > 0, only return papers published in this year or later.

    Returns
    -------
    list[Paper]
        Parsed papers. Empty list on failure.
    """
    if not _cb_should_allow():
        logger.info("[rate-limit] arXiv circuit breaker OPEN — skipping")
        return []

    limit = min(limit, 300)

    # No arxiv library? Fall back to the export.arxiv.org HTTP API (stdlib only).
    if arxiv is None:
        return _search_arxiv_http(query, limit=limit, sort_by=sort_by, year_min=year_min)

    sort_map = {
        "relevance": arxiv.SortCriterion.Relevance,
        "submitted_date": arxiv.SortCriterion.SubmittedDate,
        "last_updated": arxiv.SortCriterion.LastUpdatedDate,
    }
    criterion = sort_map.get(sort_by, arxiv.SortCriterion.Relevance)

    search = arxiv.Search(
        query=query,
        max_results=limit,
        sort_by=criterion,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: list[Paper] = []
    try:
        client = _get_client()
        for result in client.results(search):
            paper = _convert_result(result)
            if year_min > 0 and paper.year < year_min:
                continue
            papers.append(paper)
        _cb_on_success()
        logger.info("arXiv: found %d papers for %r", len(papers), query)
    except arxiv.HTTPError as exc:
        logger.warning("arXiv HTTP error: %s", exc)
        _cb_on_failure()
    except arxiv.UnexpectedEmptyPageError:
        logger.warning("arXiv returned unexpected empty page for %r", query)
        _cb_on_failure()
    except Exception as exc:  # noqa: BLE001
        logger.warning("arXiv search failed: %s", exc)
        _cb_on_failure()

    return papers


def get_paper_by_id(arxiv_id: str) -> Paper | None:
    """Fetch a single paper by arXiv ID (e.g., '2301.00001')."""
    if arxiv is None:
        return _get_paper_by_id_http(arxiv_id)
    try:
        search = arxiv.Search(id_list=[arxiv_id])
        client = _get_client()
        for result in client.results(search):
            return _convert_result(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("arXiv ID lookup failed for %s: %s", arxiv_id, exc)
    return None


def download_pdf(
    arxiv_id: str,
    dirpath: str | Path = ".",
    filename: str = "",
) -> Path | None:
    """Download PDF for a given arXiv ID.

    Parameters
    ----------
    arxiv_id:
        arXiv paper ID (e.g., '2301.00001').
    dirpath:
        Directory to save the PDF.
    filename:
        Custom filename. If empty, uses ``{arxiv_id}.pdf``.

    Returns
    -------
    Path | None
        Path to downloaded PDF, or None on failure.
    """
    if arxiv is None:
        return _download_pdf_http(arxiv_id, dirpath, filename)
    try:
        search = arxiv.Search(id_list=[arxiv_id])
        client = _get_client()
        for result in client.results(search):
            dirpath = Path(dirpath)
            dirpath.mkdir(parents=True, exist_ok=True)
            fname = filename or f"{arxiv_id.replace('/', '_')}.pdf"
            result.download_pdf(dirpath=str(dirpath), filename=fname)
            pdf_path = dirpath / fname
            logger.info("Downloaded arXiv PDF: %s → %s", arxiv_id, pdf_path)
            return pdf_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF download failed for %s: %s", arxiv_id, exc)
    return None


def search_arxiv_advanced(
    *,
    title: str = "",
    author: str = "",
    abstract: str = "",
    category: str = "",
    limit: int = 50,
    year_min: int = 0,
) -> list[Paper]:
    """Advanced arXiv search using field-specific queries.

    Example: search_arxiv_advanced(title="transformer", category="cs.LG")
    """
    parts = []
    if title:
        parts.append(f"ti:{title}")
    if author:
        parts.append(f"au:{author}")
    if abstract:
        parts.append(f"abs:{abstract}")
    if category:
        parts.append(f"cat:{category}")

    if not parts:
        return []

    query = " AND ".join(parts)
    return search_arxiv(query, limit=limit, year_min=year_min)


# ---------------------------------------------------------------------------
# HTTP API fallback (stdlib only) — used when the ``arxiv`` package is absent.
# Talks to the public Atom API at export.arxiv.org. Honors env proxies via
# urllib (HTTP(S)_PROXY), same as the OpenAlex client.
# ---------------------------------------------------------------------------

_ARXIV_API = "http://export.arxiv.org/api/query"
_HTTP_TIMEOUT = 30
_ATOM_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_SORT_MAP_HTTP = {
    "relevance": "relevance",
    "submitted_date": "submittedDate",
    "last_updated": "lastUpdatedDate",
}


def _arxiv_api_get(params: dict[str, str]) -> bytes | None:
    url = _ARXIV_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ResearchClaw/1.0 (arxiv HTTP fallback)"})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("arXiv HTTP API request failed: %s", exc)
        return None


def _convert_atom_entry(entry: ET.Element) -> Paper | None:
    """Convert one Atom <entry> element to a ``Paper`` (returns None if untitled)."""
    def _txt(tag: str) -> str:
        el = entry.find(tag, _ATOM_NS)
        return (el.text or "").strip() if el is not None and el.text else ""

    entry_id = _txt("a:id")
    arxiv_id = ""
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", entry_id)
    if m:
        arxiv_id = m.group(1)

    title = re.sub(r"\s+", " ", _txt("a:title"))
    if not title:
        return None

    authors = tuple(
        Author(name=(n.text or "").strip())
        for n in entry.findall("a:author/a:name", _ATOM_NS)
        if n is not None and n.text and n.text.strip()
    )

    published = _txt("a:published")
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else 0

    doi = _txt("arxiv:doi")

    venue = ""
    pc = entry.find("arxiv:primary_category", _ATOM_NS)
    if pc is not None:
        venue = pc.get("term") or ""

    url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else entry_id

    return Paper(
        paper_id=f"arxiv-{arxiv_id}" if arxiv_id else f"arxiv-{entry_id}",
        title=title,
        authors=authors,
        year=year,
        abstract=_txt("a:summary"),
        venue=venue,
        citation_count=0,  # arXiv doesn't provide citation counts
        doi=doi,
        arxiv_id=arxiv_id,
        url=url,
        source="arxiv",
    )


def _search_arxiv_http(
    query: str,
    *,
    limit: int = 50,
    sort_by: str = "relevance",
    year_min: int = 0,
) -> list[Paper]:
    """arXiv search via the export.arxiv.org Atom API (no ``arxiv`` package)."""
    raw = _arxiv_api_get({
        "search_query": query,
        "start": "0",
        "max_results": str(min(limit, 300)),
        "sortBy": _SORT_MAP_HTTP.get(sort_by, "relevance"),
        "sortOrder": "descending",
    })
    if raw is None:
        _cb_on_failure()
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        logger.warning("arXiv HTTP API returned non-XML: %s", exc)
        _cb_on_failure()
        return []

    papers: list[Paper] = []
    for entry in root.findall("a:entry", _ATOM_NS):
        paper = _convert_atom_entry(entry)
        if paper is None:
            continue
        if year_min > 0 and paper.year < year_min:
            continue
        papers.append(paper)
    _cb_on_success()
    logger.info("arXiv (HTTP API): found %d papers for %r", len(papers), query)
    return papers


def _get_paper_by_id_http(arxiv_id: str) -> Paper | None:
    raw = _arxiv_api_get({"id_list": arxiv_id, "max_results": "1"})
    if raw is None:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    for entry in root.findall("a:entry", _ATOM_NS):
        return _convert_atom_entry(entry)
    return None


def _download_pdf_http(
    arxiv_id: str,
    dirpath: str | Path = ".",
    filename: str = "",
) -> Path | None:
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(pdf_url, headers={"User-Agent": "ResearchClaw/1.0 (arxiv HTTP fallback)"})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = resp.read()
        dirpath = Path(dirpath)
        dirpath.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{arxiv_id.replace('/', '_')}.pdf"
        pdf_path = dirpath / fname
        pdf_path.write_bytes(data)
        logger.info("Downloaded arXiv PDF (HTTP): %s → %s", arxiv_id, pdf_path)
        return pdf_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF download (HTTP) failed for %s: %s", arxiv_id, exc)
        return None


# ---------------------------------------------------------------------------
# Internal: convert arxiv.Result → Paper
# ---------------------------------------------------------------------------


def _convert_result(result: arxiv.Result) -> Paper:
    """Convert an ``arxiv.Result`` to our ``Paper`` dataclass."""
    # Extract arXiv ID from entry_id URL
    arxiv_id = ""
    if result.entry_id:
        m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", result.entry_id)
        if m:
            arxiv_id = m.group(1)

    # Authors
    authors = tuple(Author(name=a.name) for a in result.authors)

    # Year from published date
    year = result.published.year if result.published else 0

    # DOI
    doi = result.doi or ""

    # Primary category as venue
    venue = result.primary_category or ""

    # Prefer HTML abstract URL
    url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else result.entry_id

    return Paper(
        paper_id=f"arxiv-{arxiv_id}" if arxiv_id else f"arxiv-{result.entry_id}",
        title=result.title or "",
        authors=authors,
        year=year,
        abstract=result.summary or "",
        venue=venue,
        citation_count=0,  # arXiv doesn't provide citation counts
        doi=doi,
        arxiv_id=arxiv_id,
        url=url,
        source="arxiv",
    )
