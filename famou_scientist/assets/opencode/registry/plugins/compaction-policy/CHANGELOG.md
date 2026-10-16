# Compaction Policy Changelog

## 20260712-001-narrow-autocontinue

- Add `plugins/compaction-policy.ts`.
- Disable compact auto-continue for lightweight paper QA / explanation style requests.
- Keep auto-continue for explicit long-running or artifact-producing requests.
- When runtime patch `compaction-autocontinue-text-hook` is available, replace the generic synthetic continue text with a narrow instruction scoped to the last real user request.
