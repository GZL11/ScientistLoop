# Runtime Patch Changelog

## 20260712-001-compaction-autocontinue-text-hook

- Add `output.text?: string` support to `experimental.compaction.autocontinue`.
- OpenCode continues to default to its built-in prompt when plugins do not set `output.text`.
- Enables managed plugin policy to replace the generic `Continue if you have next steps...` instruction with a task-scoped continuation prompt.
