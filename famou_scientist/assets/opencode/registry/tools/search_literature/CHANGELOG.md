# ARC Literature Search Changelog


## 20260809-002-concurrent-three-source-retrieval

- Query OpenAlex, Semantic Scholar, and arXiv concurrently for every search.
- Remove candidate-count short-circuiting and OpenAlex-first fallback behavior.
- Isolate source failures and retain successful results from the other sources.
- Report per-source status, result count, and elapsed time in diagnostics.

## 20260809-001-responsive-retrieval

- Run literature Python retrieval asynchronously so OpenCode API and SSE stay responsive.
- Return interactive topic searches once enough unique OpenAlex-first results are available.
- Keep Semantic Scholar and arXiv as fallbacks; systematic mode still exhausts all sources.
- Reduce per-source retry and timeout budgets and cap one interactive tool call at 45 seconds.
- Preserve structured accepted/rejected/uncertain output and retrieval diagnostics.

## 20260718-003-structured-search-diagnostics

- Change default `arc_search_literature` output to a structured object with `accepted`, `rejected`, `uncertain`, `diagnostics`, and `edges`.
- Add conservative relevance scoring and explicit rejection reasons for weak metadata and version-only matches.
- Write best-effort `search_diagnostics.jsonl` and `queries.jsonl` records in the current workspace.
- Keep `output_format=array` for legacy callers that still need a flat accepted list.

## 20260715-004-unified-literature-search

- Keep `search_literature` as the unified literature retrieval entry point.
- Allow both topic search and academic metadata enrichment.
- Preserve web-first behavior for specific paper lookup outside this tool.

## 20260715-003-survey-only-search-literature

- Scope `search_literature` to topic-level literature survey and related-work discovery.
- Reject concrete paper lookup attempts with a structured guard.
- Keep `lookup_paper` disabled in the tool export.
