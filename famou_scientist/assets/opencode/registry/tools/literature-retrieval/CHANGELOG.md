# Literature Retrieval Tool Changelog

## 20260715-004-unified-literature-search

- Remove the hard reject path from `arc_search_literature` for paper-shaped queries.
- Add optional `user_query` and `mode` arguments so the tool can carry the original request and intent marker.
- Keep `arc_search_literature` usable for academic metadata enrichment after native web-first lookup.
- Preserve `lookup_paper` as a disabled export.

## 20260715-003-survey-only-search-literature

- Re-scoped `arc_search_literature` to topic-level literature survey and related-work discovery.
- Added a runtime guard for short named/versioned/identifier-like queries so exact paper lookup does not receive broad, weakly related academic-search candidates.
- Kept `lookup_paper` disabled; concrete paper lookup should be handled by native web search / webfetch evidence first.

## 20260713-002-lookup-precision

- Tightened `arc_lookup_paper` scoring so version tokens like `1.5` cannot produce relevant-looking candidates by themselves.
- Added meaningful-token filtering to remove unrelated results such as `LongCat-Video-Avatar 1.5` for `InterAgent-1.5`.
- Added fuzzy long-token matching for typo-tolerant paper-name lookup without hard-coded title rewrites.

## 20260713-001-paper-lookup

- Added `arc_lookup_paper` for specific-paper lookup before broad topic search.
- Fuses academic results with optional web-search candidates.
- Returns confidence, best candidate, candidates, and `needs_confirmation`.
- Leaves existing `arc_search_literature` behavior unchanged.
