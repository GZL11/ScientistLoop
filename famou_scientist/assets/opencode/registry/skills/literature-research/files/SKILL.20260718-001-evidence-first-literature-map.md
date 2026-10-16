---
name: literature-research
description: Research synthesis workflow for understanding a field, clustering subtopics, identifying evidence-backed gaps, recommending research directions, and ranking candidate ideas. Use this instead of literature-search when the user asks what is worth studying, where the gaps are, or how a research area is structured.
metadata:
  category: experiment
  trigger-keywords: "field map,gap map,idea bank,hotspot,subtopic,literature research,review,related work"
  applicable-stages: "3,4,5,6"
  priority: "2"
  version: "1.0"
  author: local-admin
  references: "Famou Scientist literature survey notes, 2026-07-15"
---

## Literature Research Workflow

### Boundary
`literature-research` owns research synthesis:
- scope a research area;
- build a field map;
- cluster subtopics and methods;
- identify evidence-backed gaps;
- propose and rank candidate ideas.

It may call retrieval tools and may use `literature-search` as a subroutine for query design, corpus expansion, and source verification. Do not replace this workflow with `literature-search` when the user asks for research directions, gaps, hotspots, or idea selection.

### When to Use
Use this skill when the user wants to:
- understand a research area end to end;
- cluster papers into subtopics;
- identify evidence-backed gaps;
- compare candidate research directions;
- generate and rank candidate research ideas;
- produce a reusable field map rather than a flat paper list.

Do not use this skill for:
- single-paper lookup;
- fuzzy paper name confirmation only;
- plain citation checking;
- a simple list of related papers without synthesis;
- rewriting or polishing an existing paper without new retrieval.

### Phase 0: Scope
1. Confirm the research intent first.
2. Capture:
   - domain boundary;
   - time range;
   - target output style;
   - depth budget;
   - whether the user wants field map, gap map, or idea bank.
3. If the scope is too broad, ask 2-4 concise narrowing questions before searching.
4. Create a session workspace and record the scope in `scope.md`.

### Evidence Discipline
1. Use evidence-first reasoning. Do not infer that a topic is open only because one search returned no results.
2. For literature retrieval, run at least two source families before making a claim:
   - native `websearch` / `webfetch` for arXiv, OpenReview, ACL Anthology, PMLR, publisher pages, project pages, GitHub, blog announcements, and recent papers;
   - `arc_search_literature` for academic metadata, abstracts, DOI/arXiv IDs, and related scholarly candidates.
3. Use `arc_fetch_source` only to verify a known arXiv ID/title or enrich an already plausible candidate.
4. Each accepted paper must pass relevance filtering by problem, method, task/application, and evaluation. Keyword-only, version-only, year-only, or number-only matches are rejected.
5. Search failure means "not found by this retrieval pass", not "no one has done it".

### Phase 1: Seed Search
1. Start with anchors:
   - recent surveys;
   - benchmarks;
   - representative systems;
   - seminal papers;
   - user-provided seeds.
2. Prefer broad but controlled retrieval over deep expansion.
3. For each anchor, run parallel retrieval with native `websearch` and `arc_search_literature` unless the source is already supplied by the user.
4. Record every query in `queries.jsonl` with `source`, `query`, `intent`, `accepted_count`, `rejected_count`, and `notes`.
5. Record accepted seeds in `seed_papers.jsonl`.
6. Record obvious mismatches in `rejected_papers.jsonl` with a short rejection reason.
7. In gradual/stepwise interaction mode, pause after the seed set and show only the evidence quality, not new ideas.

### Phase 2: Expansion and Verification
1. Expand from each seed through:
   - references;
   - citations;
   - related work;
   - shared method names;
   - dataset or benchmark names;
   - system/project names.
2. Verify each candidate before promoting it:
   - title;
   - authors;
   - year;
   - venue/source;
   - relevance.
3. Never place version-only, year-only, or number-only matches into the candidate set.
4. If the result is borderline, stop and ask the user.
5. Record accepted candidates in `candidate_papers.jsonl`.
6. Create one paper card per accepted candidate in `paper_cards.jsonl`:
   - title;
   - authors;
   - year;
   - venue/source;
   - URL/arXiv/DOI;
   - problem;
   - method;
   - task/application;
   - evaluation;
   - claimed contribution;
   - stated or inferred limitation;
   - relation to the user topic.
7. If the candidate set is thin, low-confidence, or dominated by weak matches, stop and report retrieval uncertainty instead of building gaps.

### Phase 3: Field Map
1. Cluster papers by:
   - problem;
   - method;
   - data/task;
   - application;
   - evaluation.
2. For each cluster, write:
   - core problem;
   - representative papers;
   - technical route;
   - recent progress;
   - current bottlenecks.
3. Keep clusters evidence-backed, not keyword-only.
4. Save the synthesis in `field_map.md`.
5. Also save a literature map in `literature_map.md` so the user can see the useful papers at a glance:
   - Mermaid `graph LR` or adjacency-list view of paper/topic relationships;
   - cluster table;
   - representative papers per cluster;
   - citation/lineage links where known;
   - method overlap matrix;
   - task/application coverage matrix;
   - known limitations and open improvement space.
6. Exclude rejected or uncertain papers from the literature map; mention their count separately if useful.
7. In gradual/stepwise interaction mode, pause here and ask whether to refine the map before moving to gaps.

### Phase 4: Gap Map
1. Turn each gap into a structured object.
2. Each gap must include:
   - statement;
   - gap type;
   - prior work covered;
   - missing or weak part;
   - supporting papers;
   - possible counterexamples;
   - confidence.
3. Do not present a gap without checking for obvious counterexamples using targeted follow-up searches.
4. Classify gaps as:
   - open gap;
   - underexplored subproblem;
   - known problem with weak existing solutions;
   - improvement opportunity over existing baselines.
5. Do not discard a direction only because related work exists. Identify whether the existing work leaves room for a different mechanism, better evaluation, lower cost, stronger generalization, or clearer theory.
6. Save the gap structure in `gap_map.yaml`.
7. In gradual/stepwise interaction mode, pause here and let the user choose which gap family to explore.

### Phase 5: Idea Bank
1. Generate ideas only from verified gaps or explicit improvement opportunities.
2. Each idea must include:
   - source gap;
   - novelty or improvement type;
   - feasibility;
   - compute/time/data cost estimate;
   - validation plan;
   - required data/tools;
   - expected contribution;
   - risk;
   - reviewer objections;
   - competing papers and overlap summary;
   - priority score.
3. Before presenting an idea, run a targeted existence check:
   - exact idea query;
   - method-level query;
   - application/task query;
   - baseline or limitation query;
   - survey/benchmark query when available.
4. Rank ideas by evidence strength, feasibility, potential contribution, and compute cost.
5. Save the result in `idea_bank.yaml`.
6. In gradual/stepwise interaction mode, present at most 2-3 ideas per turn and pause.

### Phase 6: Review and Rank
1. Present a compact summary to the user:
   - what was searched;
   - what clusters were found;
   - what gaps are most credible;
   - what ideas are most promising.
2. Include a compact literature map view from `literature_map.md` so the user can inspect the evidence network quickly: clusters, key papers, links/lineage, and improvement spaces.
3. Pause before deep reading, writing, or experiment planning unless the user has explicitly approved the next step.
4. If the user wants a narrower pass, restart from Phase 0 with the narrower scope.

### Workspace Contract
For each session, keep the work in a dedicated workspace and preserve traces:
- `scope.md`
- `queries.jsonl`
- `seed_papers.jsonl`
- `candidate_papers.jsonl`
- `rejected_papers.jsonl`
- `paper_cards.jsonl`
- `literature_map.md`
- `field_map.md`
- `gap_map.yaml`
- `idea_bank.yaml`
- `review_notes.md`
- `final_report.md`

### Output Rules
1. Always separate:
   - verified papers;
   - rejected candidates;
   - inferred gaps;
   - ranked ideas.
2. Do not silently expand from a single-paper request into a field survey.
3. Do not propose ideas without a gap and evidence trail.
4. Do not continue expanding indefinitely; stop at clear review points and ask for confirmation.
5. Do not turn related work into automatic rejection. Separate direct duplication from partial overlap and improvable baselines.
6. In gradual/stepwise mode, never cross more than one phase after a user approval.
