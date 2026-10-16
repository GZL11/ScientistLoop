# Guardrails Plugin Changelog

## 20260810-001-literature-artifact-gate

- Warn when a literature report is written without non-empty canonical paper cards.
- Keep the guard soft: it preserves the write and asks the Agent to finish consolidation.
- Keep raw retrieval candidates and subagent returns out of the final screened set.

## 20260715-001-paper-retrieval-guards

- Add a paper candidate guard that warns when specific-paper lookup returns results with no core-term match.
- Add a retrieval escalation guard that warns when a specific-paper lookup context is widened into a broad literature review too early.
- Keep the guards soft so native web-first lookup still works and the agent can correct course.
