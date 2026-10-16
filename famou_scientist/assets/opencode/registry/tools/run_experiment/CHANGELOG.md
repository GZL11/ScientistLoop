# ARC Experiment Runner Changelog

## 20260730-001-progress-policy

- Add optional `progress_policy_json` for async experiment heartbeat monitoring.
- Persist parsed progress policy in job `meta.json`.
- Return parsed policy and invalid-JSON warnings from async launch responses.

## 20260716-001-run-experiment

- Split `arc_run_experiment` into its own registry entry.
- Keep synchronous and detached background execution under one tool.
