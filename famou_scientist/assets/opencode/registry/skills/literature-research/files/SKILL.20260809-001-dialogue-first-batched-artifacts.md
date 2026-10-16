---
name: literature-research
description: Research synthesis workflow for understanding a field, clustering subtopics, identifying evidence-backed gaps, recommending research directions, and ranking candidate ideas. Use this instead of literature-search when the user asks what is worth studying, where the gaps are, or how a research area is structured.
metadata:
  category: experiment
  trigger-keywords: "field map,gap map,idea bank,hotspot,subtopic,literature research,review,related work"
  applicable-stages: "3,4,5,6"
  priority: "2"
  version: "20260809-001-dialogue-first-batched-artifacts"
  author: local-admin
  references: "Famou Scientist literature survey notes, 2026-07-15; Chain-of-Evidence workflow notes, 2026-07-18"
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

### Dialogue and Bounded Artifact Contract
Research synthesis must remain a conversation, including in full-auto mode.

1. For exploratory questions such as "what directions are worth studying?", run one coherent seed batch and then give the user a provisional, evidence-backed direction map before deeper expansion. Do not withhold the answer until every artifact is complete.
2. Emit a concise assistant-text checkpoint whenever a completed evidence batch changes the research judgment: a new cluster, representative work, credible gap, counterexample, rejected direction, or recommendation. State:
   - the 2-4 most important findings;
   - representative evidence and confidence;
   - unresolved points;
   - the next evidence check or artifact.
3. Before a potentially long retrieval, synthesis, or artifact task, give a concise work preview in assistant text: the current objective, the action being taken, why it is needed, and the expected artifact or decision. Do not expose hidden chain-of-thought or raw commands.
4. If rate-limit retries, weak evidence, a plan change, or a real blocker occurs, explain the reason and the revised action. Do not emit timer-based heartbeats when the plan has not changed.
5. Before a large artifact write, communicate the current conclusions in assistant text. Full artifacts belong in files, but files never replace user-facing synthesis.
6. Append structured evidence in bounded semantic batches. Write at most five `PaperCard` records in one tool call. Separate datasets/benchmarks, model families, generalization methods, and optimization applications when practical. Never embed a large corpus or several complete reports in one shell/write argument.
7. Keep channels distinct:
   - chat: conclusions, evidence quality, recommendations, risks, and next research decision;
   - process: searches, commands, file operations, retries, and other execution detail;
   - artifacts: complete cards, maps, diagnostics, and reports.
8. Checkpoints are milestone-driven, not timer-driven. Do not send empty "still searching" updates; communicate only when there is a new research judgment or a real blocker.
9. In full-auto mode, continue after the checkpoint unless a hard gate requires user input. In gradual/stepwise modes, preserve the existing phase gates.


### Chain-of-Evidence Object Model
Use explicit objects rather than loose prose. Keep object files append-only where practical so the evidence trail can be audited later.

#### PaperCard
Write accepted papers to `paper_cards.jsonl`. Required fields:
- `paper_id`: stable local ID, e.g. `paper:short-title-year` or arXiv/DOI when available;
- `title`, `authors`, `year`, `venue`, `url`, `doi`, `arxiv_id`;
- `problem`, `method`, `task_or_application`, `evaluation`;
- `claimed_contribution`;
- `limitations`;
- `relation_to_user_topic`;
- `relevance_score`: 0-1;
- `match_reasons`: concrete reasons it belongs;
- `source_queries`: queries/sources that found it.

#### RejectedPaper
Write rejected or low-confidence candidates to `rejected_papers.jsonl`. Required fields:
- `title`, `url`, `source_query`, `source`;
- `reject_reason`;
- `mismatch_type`: `off_domain`, `keyword_only`, `version_only`, `year_only`, `weak_metadata`, `duplicate`, or `too_uncertain`;
- `could_be_reconsidered_if`: optional missing evidence that would make it relevant.

#### SearchDiagnostic
Write retrieval diagnostics to `search_diagnostics.jsonl`. Required fields:
- `query`;
- `user_query`;
- `intent`: `paper`, `topic`, `systematic`, `gap_research`, or `auto`;
- `sources`;
- `raw_count`;
- `accepted_count`;
- `rejected_count`;
- `uncertain_count`;
- `failure_mode`: empty when successful, otherwise one of `source_miss`, `query_too_broad`, `filter_too_weak`, `agent_wrong_tool`, or `insufficient_retrieval_evidence`;
- `notes`.

Use `SearchDiagnostic` to explain retrieval quality. Do not turn `failure_mode: insufficient_retrieval_evidence` into a novelty or gap claim.

#### ClaimCard
Write important synthesis claims to `claim_cards.jsonl`. Required fields:
- `claim_id`;
- `claim`;
- `claim_type`: `definition`, `trend`, `cluster_summary`, `limitation`, `comparison`, `gap_evidence`;
- `supporting_papers`;
- `contradicting_or_qualifying_papers`;
- `confidence`: `high`, `medium`, or `low`;
- `evidence_notes`.

#### GapCard
Write gaps to `gap_map.yaml`. Required fields:
- `gap_id`;
- `gap_statement`;
- `gap_type`: `subfield_internal`, `between_subfields`, `method`, `evaluation`, `data`, `engineering`, or `theory`;
- `covered_by_prior_work`;
- `missing_or_weak_part`;
- `supporting_papers`;
- `possible_counterexamples`;
- `targeted_checks_run`;
- `confidence`;
- `why_it_matters`.

#### IdeaCard
Write ideas to `idea_bank.yaml` only after the gap map exists and the user has approved moving into idea generation. Required fields:
- `idea_id`;
- `source_gap`;
- `idea`;
- `status`: `verified_candidate`, `needs_more_check`, or `draft_unverified`;
- `novelty_or_improvement_type`;
- `evidence_chain`;
- `overlap_with_prior_work`;
- `targeted_checks_run`: exact queries/sources used before presenting the idea;
- `overlapping_work`: directly related papers/systems and what each already covers;
- `overlap_class`: `direct_duplicate`, `partial_overlap`, `improvable_baseline`, `adjacent_work`, or `no_known_overlap`;
- `existing_defects`: limitations, missing evaluations, cost issues, scope limits, or mechanism gaps in overlapping work;
- `improvement_space`: what remains worth doing despite prior work;
- `why_not_duplicate`: concise evidence-backed explanation, or `not_established`;
- `confidence`: `high`, `medium`, or `low`;
- `feasibility`;
- `validation_plan`;
- `cost_estimate`;
- `risks`;
- `reviewer_objections`;
- `priority_score`.

#### EvidenceEdge
Write graph edges to `evidence_edges.jsonl` and summarize them in `literature_map.md`. Required fields:
- `source`;
- `target`;
- `relation`;
- `evidence`;
- `confidence`.

Allowed `relation` values:
- `retrieved_by`: paper was found by a query or source;
- `cites`: source cites target;
- `extends`: source extends target;
- `uses_method`: source uses a method from target;
- `same_task`: both papers evaluate the same task/problem;
- `same_benchmark`: both papers use the same benchmark/dataset;
- `compares_with`: source explicitly compares with target;
- `contradicts`: source challenges or qualifies target;
- `survey_of`: source surveys target or its cluster;
- `application_of`: source applies target's method to another setting;
- `gap_supports`: paper supports a gap claim;
- `gap_counterexample`: paper may weaken or refute a gap claim.

If an edge is inferred from abstracts or related-work text rather than explicit citation metadata, mark `confidence: medium` or `low` and explain the inference in `evidence`.

### Phase Gate Contract
The workflow has strict review gates:
1. Do not enter Phase 3 unless Phase 1-2 produced a verified seed/candidate set with accepted and rejected records.
2. Do not enter Phase 4 unless `paper_cards.jsonl`, `claim_cards.jsonl`, and an initial `evidence_edges.jsonl` exist.
3. Do not enter Phase 5 unless `gap_map.yaml` exists and the user explicitly asks for ideas or approves moving from gaps to ideas.
4. Do not treat a user approval for one phase as approval for multiple phases.
5. If evidence is weak, stop at the current phase and report retrieval uncertainty rather than fabricating a map, gap, or idea.

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
7. Create `EvidenceEdge` records with `relation: retrieved_by` for accepted seeds.
8. In gradual/stepwise interaction mode, pause after the seed set and show only the evidence quality, not new ideas.

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
7. Create `EvidenceEdge` records for explicit or well-supported relations: citations, same task, same benchmark, method reuse, direct comparison, or survey coverage.
8. If the candidate set is thin, low-confidence, or dominated by weak matches, stop and report retrieval uncertainty instead of building gaps.

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
5. Write key synthesis claims to `claim_cards.jsonl` before presenting the map.
6. Also save a literature map in `literature_map.md` so the user can see the useful papers at a glance:
   - Mermaid `graph LR` or adjacency-list view of paper/topic relationships;
   - cluster table;
   - representative papers per cluster;
   - citation/lineage links where known;
   - method overlap matrix;
   - task/application coverage matrix;
   - known limitations and open improvement space.
7. Also save graph edges in `evidence_edges.jsonl` using the EvidenceEdge schema.
8. Exclude rejected or uncertain papers from the literature map; mention their count separately if useful.
9. In gradual/stepwise interaction mode, pause here and ask whether to refine the map before moving to gaps.

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
7. Add `gap_supports` and `gap_counterexample` edges to `evidence_edges.jsonl`.
8. In gradual/stepwise interaction mode, pause here and let the user choose which gap family to explore. Do not present ideas yet unless the user asks for them.

### Phase 5: Idea Bank
1. Generate ideas only from verified gaps or explicit improvement opportunities.
2. Each idea must include:
   - source gap;
   - novelty or improvement type;
   - status;
   - targeted prior-work checks;
   - overlapping work;
   - overlap class;
   - existing-work defects;
   - improvement space;
   - why the idea is not a duplicate;
   - confidence;
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
4. Treat the targeted existence check as a hard gate:
   - if a direct duplicate is found, do not recommend the idea; either discard it or rewrite it as a clearly different improvement opportunity;
   - if partial overlap or an improvable baseline is found, keep the direction only when `existing_defects`, `improvement_space`, and `why_not_duplicate` are concrete;
   - if checks are incomplete, set `status: draft_unverified`, `confidence: low`, and do not present it as a recommended idea.
5. Do not reject a direction only because related work exists. First identify whether the prior work leaves room for a different mechanism, stronger benchmark, lower cost, better generalization, clearer theory, or a cleaner ablation.
6. Rank only `verified_candidate` ideas by evidence strength, feasibility, potential contribution, and compute cost. Keep `needs_more_check` and `draft_unverified` separate.
7. Save the result in `idea_bank.yaml`.
8. In gradual/stepwise interaction mode, present at most 2-3 verified ideas per turn and pause. If no verified ideas exist, present the evidence limitation and the next checks instead.

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
- `search_diagnostics.jsonl`
- `seed_papers.jsonl`
- `candidate_papers.jsonl`
- `rejected_papers.jsonl`
- `paper_cards.jsonl`
- `claim_cards.jsonl`
- `evidence_edges.jsonl`
- `literature_map.md`
- `field_map.md`
- `gap_map.yaml`
- `idea_bank.yaml`
- `review_notes.md`
- `final_report.md`

### Artifact Visibility Contract
Separate user-facing deliverables from diagnostic artifacts.

User-facing artifacts:
- `scope.md`: research scope and constraints;
- `paper_cards.jsonl`: render as paper cards or a literature graph, not raw JSONL;
- `literature_map.md`: render as the field/literature map;
- `field_map.md`: render as the subtopic and hotspot map;
- `gap_map.yaml`: render as gap cards with evidence and counterexamples;
- `idea_bank.yaml`: render only verified or explicitly marked candidate ideas; do not present `draft_unverified` items as recommendations;
- `review_notes.md` and `final_report.md`: render as reports when present.

Diagnostic artifacts:
- `queries.jsonl`;
- `search_diagnostics.jsonl`;
- `seed_papers.jsonl`;
- `candidate_papers.jsonl`;
- `rejected_papers.jsonl`;
- `claim_cards.jsonl`;
- `evidence_edges.jsonl`.

Diagnostic artifacts should be available for trace review and debugging, but they should not be shown as primary user deliverables by default.

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
