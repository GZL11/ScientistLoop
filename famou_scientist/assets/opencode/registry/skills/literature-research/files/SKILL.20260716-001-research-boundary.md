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

### Phase 1: Seed Search
1. Start with anchors:
   - recent surveys;
   - benchmarks;
   - representative systems;
   - seminal papers;
   - user-provided seeds.
2. Prefer broad but controlled retrieval over deep expansion.
3. Record every query in `queries.jsonl`.
4. Record accepted seeds in `seed_papers.jsonl`.
5. Record obvious mismatches in `rejected_papers.jsonl`.

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
3. Do not present a gap without checking for obvious counterexamples.
4. Save the gap structure in `gap_map.yaml`.

### Phase 5: Idea Bank
1. Generate ideas only from verified gaps.
2. Each idea must include:
   - source gap;
   - novelty;
   - feasibility;
   - validation plan;
   - required data/tools;
   - expected contribution;
   - risk;
   - reviewer objections;
   - priority score.
3. Rank ideas by evidence strength, feasibility, and potential contribution.
4. Save the result in `idea_bank.yaml`.

### Phase 6: Review and Rank
1. Present a compact summary to the user:
   - what was searched;
   - what clusters were found;
   - what gaps are most credible;
   - what ideas are most promising.
2. Pause before deep reading, writing, or experiment planning unless the user has explicitly approved the next step.
3. If the user wants a narrower pass, restart from Phase 0 with the narrower scope.

### Workspace Contract
For each session, keep the work in a dedicated workspace and preserve traces:
- `scope.md`
- `queries.jsonl`
- `seed_papers.jsonl`
- `candidate_papers.jsonl`
- `rejected_papers.jsonl`
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
