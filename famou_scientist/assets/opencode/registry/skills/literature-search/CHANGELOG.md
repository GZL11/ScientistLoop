# Literature Search Skill Changelog

## 20260809-001-progressive-retrieval-batches

- Submit only one or two complementary topic queries in the first retrieval batch.
- Screen returned evidence before deciding whether another batch is necessary.
- Keep each follow-up batch at two queries or fewer.
- Reserve exhaustive multi-source retrieval for explicit systematic-review requests.

## 20260716-001-retrieval-boundary

- Narrow `literature-search` to retrieval execution: lookup, query design, corpus expansion, screening, and source verification.
- Add an explicit handoff rule: field maps, gap discovery, research-direction recommendation, and idea ranking belong to `literature-research`.
- Keep topic search and systematic-review protocol support, but prevent this skill from becoming the owner of research synthesis.

## 20260715-003-web-first-unified-routing

- Expand `literature-search` into a unified routing skill covering specific paper lookup, fuzzy lookup, topic search, systematic review, and corpus reading.
- Keep specific paper lookup web-first at the skill level while leaving the actual web search to native tools.
- Allow `arc_search_literature` to serve as academic metadata enrichment / topic retrieval instead of rejecting specific-paper-shaped queries.
- Keep retrieval policy versioned in the skill rather than in `AGENTS.md`.

## 20260715-002-disable-lookup-paper-fallback

- Removed `arc_lookup_paper` fallback guidance while the `lookup_paper` tool export is disabled.
- Specific-paper lookup should use native websearch/webfetch and ask for stronger identifiers if evidence is insufficient.
- Topic literature search guidance remains unchanged.

## 20260714-001-web-first-paper-lookup

- Changed specific-paper lookup to native websearch/webfetch first.
- Keeps query expansion short: original phrase plus at most one or two focused variants.
- Downgrades `arc_lookup_paper` to fallback or optional metadata enrichment.
- Keeps `arc_search_literature` reserved for topic-level literature review, related work, and survey tasks.
- Still blocks version-only, year-only, number-only, and generic-word-only matches from being shown as plausible papers.

## 20260713-002-parallel-paper-lookup

- Changed specific-paper lookup from lookup-first to parallel academic lookup plus native websearch/webfetch.
- Requires webfetch verification for trusted paper pages found through websearch.
- Blocks version-only, year-only, number-only, and generic-word-only candidates from being shown as plausible papers.
- Asks the user for more clues only after both academic and web lookup fail.

## 20260713-001-paper-lookup

- Added Paper Lookup guidance for specific-paper requests.
- Clarified that medium/low-confidence lookup candidates require user confirmation.
- Preserved existing systematic topic-search guidance.
