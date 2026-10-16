# Consolidated Failure Analysis Across 11 Optimization Runs

## 1. Missing or Misnamed Output Artifact (Deliverable Contract Violation) [8/11 runs]

**Patches:** #1, #2, #3, #4, #7, #8, #10, #11

### Root Cause
The dominant failure mode by far. Solvers built correct optimization models (MILP, CP-SAT, DFS chain enumeration) but failed to emit the canonical artifact the evaluator's `EXTRACTOR_SPEC` expects. Concrete variants observed:
- **No file written at all** (#1, #2, #11): solver focused on modeling/plotting and never reached a serialization step.
- **Wrong filename** (#3, #4, #10): wrote `schedule_result.csv` instead of `surgery_schedule.csv` / `schedule.json` / `crew_schedule.csv`. Evaluator's column-normalizer either failed or fell back to a wrong file (e.g. `driver_summary.csv`, a per-driver aggregate with no per-task rows).
- **Wrong schema / column names** (#3, #7, #8): wrote `room_id` instead of `room`; omitted required `quantity` and `End` columns; auto-normalization mapped values to blanks.
- **Wrong row granularity** (#10): per-driver summary instead of one-row-per-task long format.

The recurring signal: `extraction_status: failed` or `validity=0` despite no constraint violations.

### Consolidated Fix
**Before writing any solver code, inspect `EXTRACTOR_SPEC` and record (filename, format, exact column names, row granularity, value formats). Treat the output contract as a hard constraint equal to any modeled constraint.**

1. **Emit the canonical artifact first, supplementary artifacts (Gantt, summaries, plots) second.** Never rely on visualization or aggregates as substitutes.
2. **Build DataFrames from a `REQUIRED_COLS` constant** mirroring the evaluator schema (case-sensitive). Examples:
   - JSSP: `schedule.json` with `{makespan, schedule:[{job_id, step, machine, start_time, end_time, duration}]}`
   - OR scheduling: `surgery_schedule.csv` with `surgery_id, day, room, surgeon, start_time, end_time`
   - Production: `solution.csv` with `Task, Machine, Mold, Start, End, quantity` (emit BOTH End and quantity)
   - Crew scheduling: `crew_schedule.csv` with `driver_id, sequence, train_no, pickup_loc, dropoff_loc, pickup_time, dropoff_time` (one row per task)
3. **Emit unconditionally**, even on infeasibility — wrap solve in try/except and dump a feasible fallback (all-outsource, trivial pairing, singleton assignments) so validity > 0.
4. **Self-validate before exit:** reload the file, assert all required columns are non-empty, value formats parse (`YYYY-MM-DD`, `HH:MM`), enums match (`OR1..OR6`, `Line-1/2/3`), and row counts match expectations (e.g., `len(schedule) == len(tasks)`).
5. **Heuristic:** "no errors during execution + score 0" almost always means missing/misnamed output, not a modeling bug. Add a final deliverable-checklist block that asserts each required filename exists.
6. **Anti-pattern:** after 2 rewrites of the solver script without producing output, abandon sophistication and emit a trivial feasible baseline.

---

## 2. Decision Variable Hardcoded Instead of Being Optimized [2/11 runs]

**Patches:** #5, #6 (both microgrid dispatch tasks, possibly the same task class)

### Root Cause
PV usage was hardcoded as `P_pv_used = pv_available` rather than declared as a bounded decision variable. When PV exceeded `load + charging_capacity`, the power balance forced negative grid or negative reconstructed PV use (evaluator saw `P_pv_used min=-0.8`). The model was missing curtailment as a feasibility safety valve.

### Consolidated Fix
**Never hardcode "always-fully-used" assumptions for renewable/flexible resources.** Declare every quantity that *could* need slack as a bounded decision variable:
```python
P_pv_used[t] ∈ [0, P_pv_available[t]]
# Power balance uses the variable, not raw availability:
P_pv_used[t] + P_grid[t] + P_discharge[t] == load[t] + P_charge[t]
```
If the spec discourages curtailment, enforce it as a soft penalty in the objective rather than removing the variable — infeasibility must remain impossible. Add output assertions: `assert (P_pv_used >= -1e-6).all() and (P_pv_used <= P_pv + 1e-6).all()` before writing.

---

## 3. Enumeration/Search Pipeline Fails to Produce Any Output [2/11 runs]

**Patches:** #9, #11 (crew scheduling with closed-tour constraints)

### Root Cause
For closed-tour crew scheduling, DFS chain enumeration was over-pruned (`remaining_km < 10` cutoff dropped feasible short returns) or got tangled in closure-constraint reasoning, leading to repeated rewrites and no chains generated within the time budget. Set cover then had nothing to select.

### Consolidated Fix
1. **Emit a feasible baseline before optimizing.** For closed-tour shuttle problems, pair every outbound `X→Y` with the earliest compatible return `Y→X` to form 2-task closed chains; write that immediately, then iterate.
2. **Flush output incrementally** so partial progress survives timeouts: `writer.writerow(...); f.flush()` after each driver finalized.
3. **Remove arbitrary pruning safety margins** (e.g., `remaining_km < 10`); use exact feasibility checks only.
4. **Encode domain facts up front** for closed-tour shuttle problems: chains have even task count and alternate direction; "terminal-isolated" tasks must be last in their chain; min chain count ≥ max isolated-task count per start station.

---

## One-Off Failure Modes (mentioned briefly, not featured)

- **Aggressive pruning thresholds** (#9): `remaining_km < 10` heuristic — subsumed under #3 above.
- **Solver script proliferation without convergence** (#11): author wrote 4+ exploratory scripts, none completing — process anti-pattern, addressed in the "anti-pattern" rule under #1.

---

## Top-Level Takeaway

**~73% of failures (8/11) are output-contract violations, not modeling bugs.** The single highest-leverage intervention is: **read `EXTRACTOR_SPEC` first, define `REQUIRED_COLS`/`REQUIRED_FILES` as constants, emit a feasible baseline immediately, and self-validate the artifact before exit.** Modeling correctness is necessary but contributes only ~27% of observed failures.