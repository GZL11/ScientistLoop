# Prompt Changelog

## 20260810-001-dataset-and-literature-gates

Date: 2026-08-10

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Data acquisition failures were shown as ordinary messages and then silently bypassed.
- Dataset preparation needed a dedicated experiment-stage owner and an explicit user checkpoint.

Behavioral target:
- Load `dataset-acquisition` after benchmark choice.
- Offer an existing path, the active run's default data directory, or a custom destination.
- Validate real downloads and use structured user choices for unresolved blockers.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260809-002-dialogue-first-research.md`.

## 20260809-002-dialogue-first-research

Date: 2026-08-09

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Long research operations could remain opaque for minutes even when the Agent was making progress.
- Process details and artifact files did not tell the user what the Agent was trying to establish or how the evidence changed its judgment.

Behavioral target:
- Before long work, the Agent states the objective, planned action, reason, and expected result in normal assistant text.
- The Agent reports evidence-backed findings as soon as they change the research judgment, without waiting for every artifact to finish.
- Real retries, weak evidence, plan changes, and blockers are visible; fixed heartbeat messages are not used.
- Chat contains conclusions, process view contains execution detail, and artifact view contains full documents.
- Artifact writes use bounded semantic batches so one oversized tool call does not hide minutes of work.

Architecture:
- Agent-first prompt and skill guidance only; no frontend protocol, timer, hook, or backend workflow state machine is introduced.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260809-001-visible-stage-summaries.md`.

## 20260809-001-visible-stage-summaries

Date: 2026-08-09

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Full-auto research sessions could complete several document-producing stages without any assistant text visible to the user.
- Files are durable evidence, but they are not a substitute for communicating the conclusions and decisions that move the research forward.

Behavioral target:
- Full-auto mode skips confirmation waits but still reports each completed core stage.
- Literature findings, hypotheses, experiment design, job submission/results, and final delivery receive concise chat summaries with artifact paths.
- Fine-grained retrieval, tool execution, and file operations remain in the process view.
- A core stage is incomplete until its user-visible summary has been emitted.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260808-001-agent-first-writing.md`.

## 20260716-001-literature-skill-boundary

Date: 2026-07-16

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- `literature-search` and `literature-research` had overlapping surface descriptions.
- Runtime AGENTS still forced Stage 3-6 literature work to load `literature-search`, which prevented the new `literature-research` workflow from being selected for field mapping, gap discovery, and idea ranking.

Behavioral target:
- `literature-search` is selected for retrieval, candidate screening, and source verification.
- `literature-research` is selected for field understanding, subtopic clustering, gap mapping, research-direction recommendation, and idea ranking.
- AGENTS keeps only the routing boundary; concrete retrieval strategy remains owned by skill/tool versions.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260715-003-markdown-math-format.md`.

## 20260715-003-markdown-math-format

Date: 2026-07-15

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Technical notes written by the agent used code blocks and Unicode pseudo-formulas for math, which rendered poorly in the Web Markdown viewer.
- The Web UI already supports LaTeX math rendering, so the agent should write formulas using standard Markdown math delimiters.

Behavioral target:
- Markdown documents use `$...$` for inline math and `$$...$$` for block math.
- Code blocks are reserved for code, pseudocode, terminal commands, and ASCII diagrams.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260715-002-agents-remove-paper-lookup-skill-gate.md`.

## 20260715-002-agents-remove-paper-lookup-skill-gate

Date: 2026-07-15

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Forcing lightweight paper lookup to load `literature-search` re-coupled AGENTS to retrieval policy.
- The immediate problem is that `lookup_paper` was still enabled, so the correct fix is to disable that tool export rather than adding prompt routing.

Behavioral target:
- AGENTS stays focused on task boundaries.
- Tool availability and skill versions decide retrieval behavior.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260715-001-agents-paper-lookup-load-skill.md`.

## 20260715-001-agents-paper-lookup-load-skill

Date: 2026-07-15

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Lightweight single-paper lookup was not forced to load `literature-search`.
- In session `ses_09f341531ffedQQzTG6Io4w35Y`, the agent selected `arc_lookup_paper` directly by tool name instead of following the skill's web-first policy.

Behavioral target:
- In lightweight mode, any paper identity lookup or verification first loads `literature-search`.
- `AGENTS.md` still does not encode concrete retrieval tool order, query templates, or fallback policy.
- Retrieval details remain owned by `literature-search` and tool schema versions.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260714-003-agents-literature-skill-delegation.md`.

## 20260714-003-agents-literature-skill-delegation

Date: 2026-07-14

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- `AGENTS.md` still encoded concrete literature lookup tool order, so skill changes could be overridden by the main prompt.
- Tool/skill behavior should be versioned in their own registry entries instead of forcing an AGENTS version for every retrieval policy change.

Behavioral target:
- `AGENTS.md` owns only task boundaries and high-level safety constraints.
- `literature-search` owns specific-paper lookup, topic search, query expansion, fallback, and candidate verification strategy.
- Tool schema owns individual tool descriptions and arguments.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260714-002-agents-web-first-paper-lookup.md`.

## 20260714-002-agents-web-first-paper-lookup

Date: 2026-07-14

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- `literature-search` skill had been changed to web-first paper lookup, but `AGENTS.md` still required `arc_lookup_paper` in the first round.
- The main prompt overrode the skill in session `ses_09f45d3f2ffeIhkJIgRJrmst3e`, causing `InterAgent-1.5` lookup to start with `arc_lookup_paper` and drift to the wrong arXiv candidate.

Behavioral target:
- Specific-paper lookup starts with native websearch/webfetch.
- `arc_lookup_paper` is fallback or metadata enrichment, not the first step.
- `arc_search_literature` remains reserved for topic-level literature review, survey, and related work.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260713-003-tool-schema-decoupling.md`.

## 20260713-003-tool-schema-decoupling

Date: 2026-07-13

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Tool descriptions and arguments already live in OpenCode tool schema.
- Duplicating per-tool descriptions in `AGENTS.md` made prompt versions churn whenever a tool changed.
- Duplicated tool docs could drift from the actual registered tool schema.

Behavioral target:
- `AGENTS.md` owns cross-tool strategy and behavioral boundaries.
- Tool schema owns individual tool descriptions, parameters, and return expectations.
- Tool changes should primarily version the tool/registry entry, not force a prompt version unless behavior policy changes.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260713-002-parallel-paper-lookup.md`.

## 20260713-002-parallel-paper-lookup

Date: 2026-07-13

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Motivation:
- Specific-paper lookup was routed through only `arc_lookup_paper`, so a failed academic-library lookup could stop before native websearch/webfetch.
- Versioned names such as `InterAgent-1.5` exposed that academic lookup can return version-only false positives.

Behavioral target:
- For concrete paper names, run academic lookup and native websearch in the first round.
- Verify trusted web hits with webfetch before selecting a target paper.
- Do not show candidates that only match versions, years, numbers, or generic words.

Rollback:
- Restore `registry/prompts/agents/files/AGENTS.20260713-001-literature-retrieval-routing.md`.

## AGENTS.v20260710.task-routing

Date: 2026-07-10

Active file: `famou_scientist/assets/opencode/AGENTS.md`

Baseline: `AGENTS.v20260710.pre-task-routing.md`

Motivation:
- In session `ses_0c89723ffffevDB9C1iZUXmhOb`, paper-reading questions were upgraded into a broad research workflow without explicit user intent.
- The agent created multi-paper notes and a cross-paper comparison when the user had only asked for paper explanations and specific follow-up answers.
- After auto compact, OpenCode injected a synthetic user message with `metadata.compaction_continue=true`; the agent treated it as a real user request and resumed autonomous progress.

Behavioral target:
- Classify user requests before running the full research workflow.
- Use lightweight `paper_qa` behavior for single-paper explanations and follow-up questions.
- Do not create run directories, todo lists, files, cross-paper comparisons, or "next step" prompts unless the user explicitly asks.
- After compact recovery, continue only the latest unfinished real user question; do not treat compact summaries or synthetic continue messages as new instructions.

Risk:
- The stricter default may make the agent less proactive in ambiguous cases.
- Full research workflow still remains available when the user explicitly asks for a research project, survey, experiments, or document deliverable.

Rollback:
- Restore `AGENTS.v20260710.pre-task-routing.md` into `../AGENTS.md`.

Validation cases:
- See `tests/paper_qa.yaml`
- See `tests/compact_continue.yaml`
- See `tests/research_project.yaml`
