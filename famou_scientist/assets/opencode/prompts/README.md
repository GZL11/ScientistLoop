# Prompt Versioning

This directory stores versioned prompt snapshots and lightweight regression cases for
`assets/opencode/AGENTS.md`.

- `AGENTS.v20260710.pre-task-routing.md`: baseline before task-routing rules.
- `AGENTS.v20260710.task-routing.md`: current version with request-boundary and compact recovery discipline.
- `PROMPT_CHANGELOG.md`: audit trail for prompt changes.
- `tests/`: behavioral cases to validate prompt changes manually or with a future prompt-eval runner.

`../AGENTS.md` remains the active prompt loaded by OpenCode.
