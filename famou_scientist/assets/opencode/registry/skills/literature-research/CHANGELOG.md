# Literature Research Skill Changelog

## 20260810-001-canonical-paper-cards

- Make `paper_cards.jsonl` the canonical screened literature set.
- Require the master Agent to consolidate subagent retrieval before synthesis completion.
- Align chat summaries, reports, the right panel, and later bibliography generation to that set.

## 20260809-001-dialogue-first-batched-artifacts

- Give a work preview before long retrieval, synthesis, or artifact operations.
- Return a provisional direction map after the first coherent evidence batch.
- Report checkpoints when evidence changes the research judgment, and disclose real retries, weak evidence, plan changes, or blockers.
- Keep conclusions in chat, execution detail in process, and complete reports in artifacts.
- Write at most five `PaperCard` records per tool call and avoid oversized multi-document writes.
- Keep the implementation Agent-first; do not add timers or workflow orchestration.

## 20260719-002-artifact-visibility-contract

- Add an explicit artifact visibility contract.
- Separate user-facing deliverables from diagnostic trace files.
- Keep diagnostics available for debugging and trace review without showing them as primary user outputs.

## 20260719-001-pre-idea-prior-work-gate

- Add hard prior-work gating before idea recommendation.
- Require each `IdeaCard` to record targeted checks, overlapping work, overlap class, existing-work defects, improvement space, non-duplication rationale, status, and confidence.
- Separate direct duplicates from partial overlap and improvable baselines, so related work is not treated as automatic rejection.
- Mark incomplete ideas as `draft_unverified` and keep them out of ranked recommendations.

## 20260718-003-search-diagnostic-artifacts

- Add `SearchDiagnostic` as a first-class Chain-of-Evidence object.
- Add `search_diagnostics.jsonl` to the workspace contract.
- Require retrieval failures to be reported as evidence limitations, not novelty or gap claims.

## 20260718-002-coe-literature-workflow

- Add explicit Chain-of-Evidence object schemas: `PaperCard`, `RejectedPaper`, `ClaimCard`, `GapCard`, `IdeaCard`, and `EvidenceEdge`.
- Add strict phase gates: no field map without verified papers/claims/edges, no gap map without evidence, no idea bank without user approval.
- Add semantic literature graph relations such as `cites`, `extends`, `uses_method`, `same_task`, `same_benchmark`, `compares_with`, `survey_of`, `gap_supports`, and `gap_counterexample`.
- Require `claim_cards.jsonl` and `evidence_edges.jsonl` as durable audit artifacts.
- Keep related work as evidence for overlap or improvement space rather than automatic idea rejection.

## 20260718-001-evidence-first-literature-map

- Add evidence-first retrieval discipline: no "empty search means open gap" claims.
- Require native `websearch`/`webfetch` plus `arc_search_literature` before research-level conclusions.
- Add accepted paper cards, explicit rejected-paper reasons, and retrieval uncertainty stops.
- Add `literature_map.md` as the user-facing literature graph/map over accepted papers.
- Treat related work as overlap/improvement evidence rather than automatic rejection.
- Add targeted literature checks and cost estimates before presenting each idea.
- Strengthen gradual/stepwise pause points.

## 20260716-001-research-boundary

- Clarify that `literature-research` owns research synthesis: field mapping, subtopic clustering, gap mapping, direction recommendation, and idea ranking.
- Document that `literature-search` may be used only as a retrieval subroutine inside this workflow.
- Add simple related-paper listing to the non-goals, so lightweight retrieval does not accidentally trigger a full research workflow.

## 20260715-001-literature-research-workflow

- Add a dedicated literature research workflow skill for scope confirmation, seed search, expansion, field mapping, gap mapping, and idea ranking.
- Separate the workflow from single-paper lookup and from the existing `literature-search` routing skill.
- Make every phase versionable and workspace-backed so search traces, gaps, and idea rankings can be reviewed later.
