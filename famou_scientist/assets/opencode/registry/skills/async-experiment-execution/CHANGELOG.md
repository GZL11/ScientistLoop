# async-experiment-execution changelog

## 20260730-001-progress-policy

- Add `progress_policy_json` guidance for local async experiments.
- Let agents declare time milestones, log milestones, quiet-alert thresholds, and adaptive interval bounds.
- Clarify that running progress belongs in the Process panel and should not produce a standalone user-facing reply.
- Keep completion/failed heartbeat notifications as the trigger for `arc_experiment_status`.
