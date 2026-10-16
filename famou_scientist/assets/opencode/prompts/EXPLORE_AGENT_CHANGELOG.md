# Explore Agent Prompt Changelog

## explore.20260711-000-bounded-tool-output

Date: 2026-07-11

Active file: `famou_scientist/assets/opencode/agent/explore.md`

Motivation:
- A previous session delegated a truncated `/tool-output/` file to the explore subagent.
- The subagent read noisy generated content too broadly and returned unreadable mojibake, which the main agent echoed.

Behavioral target:
- Keep explore read-only and bounded.
- Search large/generated files with anchors first, then read only small ranges.
- Never return raw binary-like text, long HTML, base64, terminal control sequences, or mojibake.
- Report unreadable/noisy sources clearly instead of inventing or forwarding garbage.

Rollback:
- Remove `agent/explore.md` or restore it from a previous version in the management platform.
