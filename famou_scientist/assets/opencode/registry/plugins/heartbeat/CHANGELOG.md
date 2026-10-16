# heartbeat plugin changelog

## 20260810-001-async-wakeup

- Accept terminal and semantic-checkpoint wakeups with `promptAsync()`.
- Mark a completion/failure notification as sent after OpenCode accepts it, without waiting for the Agent round.
- Keep experiment progress in the Process panel and avoid repeated heartbeat rows or chat messages.

## 20260809-001-singleton-backoff

- Run one heartbeat scheduler per OpenCode process instead of one scanner per workspace.
- Use atomic per-job claims so concurrent OpenCode processes cannot inject duplicate completion turns.
- Back off unchanged job checks through 1, 2, 4, 8, ... minutes, capped at 2 hours.
- Keep periodic progress in the Process panel and reserve Agent wake-ups for semantic checkpoints and terminal states.

## 20260730-001-adaptive-progress

- Replace fixed running-progress cadence with policy-driven adaptive reporting.
- Support `meta.progress_policy` with time milestones, log milestones, quiet alerts, fixed/off modes, and interval bounds.
- Keep done/failed notifications as highest priority.
- Route running progress to the Process panel instead of encouraging a standalone user-facing reply.
