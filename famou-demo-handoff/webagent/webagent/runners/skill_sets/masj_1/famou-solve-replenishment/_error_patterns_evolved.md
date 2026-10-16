# Consolidated Failure Analysis: Replenishment MILP Solver

## 1. Output File Schema Mismatch — Empty `location` / `order_units` Fields [6/9 runs]

**Patches:** #1, #2, #3, #7, #8, #9

### Root Cause
The MILP model itself is generally sound, but the **output serialization layer** fails the evaluator's contract. Specific manifestations:
- Writer iterates over `(period, product)` only, omitting the per-DC location dimension
- `pulp.LpVariable` objects or `None` values (from variables untouched by the solver) are written directly, yielding empty strings in CSV
- Aggregated/summary rows are mixed into the plan file, leaving `location`/`order_units` blank
- Column names don't match the evaluator (e.g., `dc`/`order_quantity` vs required `location`/`order_units`)
- Code truncation prevents the write step from running, leaving a placeholder CSV

### Consolidated Fix
**Enforce a strict output contract for `wb_replenishment_with_lead_time`:**

1. **Required schema:** `period` (int), `product` (str), `location` (str, non-empty), `order_units` (int ≥ 0, non-empty).
2. **Dense Cartesian product:** Emit exactly `|DCS| × |PRODUCTS| × |PERIODS|` rows. Never skip a cell, never aggregate out the `location` dimension.
3. **Defensive value extraction** after `prob.solve()`:
   ```python
   rows = []
   for loc in LOCATIONS:
       for p in PRODUCTS:
           for t in PERIODS:
               v = pulp.value(order[(loc, p, t)])
               qty = int(round(v)) if v is not None else 0
               rows.append({"period": t, "product": p,
                            "location": loc, "order_units": qty})
   pd.DataFrame(rows).to_csv(OUTPUT_PATH, index=False)
   ```
4. **Separate auxiliary outputs:** Cost summaries, totals, and demand echoes go in `cost_summary.csv`, never mixed into the plan file.
5. **Round-trip validation before exit:**
   ```python
   df = pd.read_csv(OUTPUT_PATH)
   assert df["location"].str.len().gt(0).all()
   df["order_units"].astype(float)  # raises if blank
   assert len(df) == len(LOCATIONS) * len(PRODUCTS) * len(PERIODS)
   ```

---

## 2. No Plan File Written — Extractor Found Nothing to Score [3/9 runs]

**Patches:** #4, #5, #6

### Root Cause
The solver builds and solves the MILP but **never serializes decision variables to the path the evaluator's extractor reads**. The evaluator reports `extraction_status: failed` with note `"No plan_file in EXTRACTOR_SPEC"`. Even an optimal solution scores 0 if no artifact exists. Often compounded by code that focuses on model-building and runs out of context before the I/O stage.

### Consolidated Fix
**Lock in the I/O contract before modeling:**

1. **Discover `EXTRACTOR_SPEC` first:** Identify the required `plan_file` path, filename, and full schema (columns, dtypes, row granularity) before writing any constraints.
2. **Write `dump_plan(solution) -> DataFrame` early**, populate it after `prob.solve()`. For hub-spoke replenishment, separate action rows are typically required:
   - `purchase` rows (DC1 only): `period, product, location, order_units`
   - `transship` rows (DC1→spoke): `period, product, from_location, to_location, transfer_units`
   - `state` rows: `period, product, location, ending_inventory, shortage, waste`
   - `substitute` rows where applicable: `period, product, location, substitute_product, sub_units`
3. **Post-solve assertion:** `assert os.path.exists(plan_file)` and assert all required columns present and numeric.

---

## 3. Solver Status Not Checked / No Fallback on Infeasibility [shared across 5/9 runs]

**Patches:** #3, #4, #5, #6, #8, #9 (mentioned as supporting concern)

### Root Cause
When the model is infeasible or the solver fails (e.g., overly tight cold-storage capacity, EPS=1 safety margin on integer vars, or shelf-life constraints), the script silently writes blanks instead of a parseable fallback. Validity collapses to 0, blocking partial-credit on quality.

### Consolidated Fix
1. After `prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=...))`, check `pulp.LpStatus[prob.status] in ("Optimal", "Feasible")`.
2. **On failure, write a valid fallback plan** (zeros, or a heuristic like demand-share × total_demand rounded to int) so every row is parseable.
3. **Avoid spurious infeasibility:** don't subtract `EPS=1` from integer capacity (integrality already handles it); prefer soft penalty constraints over hard ones for capacity peaks.
4. Wrap the write step in `try/except` that emits a minimal valid CSV on any exception.

---

## 4. Tautological / Over-Engineered Substitution Constraints [1/9 runs]

**Patch:** #5 only — task-specific noise.

Brief note: avoid constraints like `shortage + sub + (d - shortage - sub) == d` that add no information. Prefer an explicit `sales` variable: `sales + shortage + sub_in = demand`, `sales ≤ available_inventory`. This also makes plan extraction cleaner.

---

# Skill-Level Rules to Encode

1. **"A MILP solver is incomplete until it emits the evaluator-specified plan_file with the exact column schema, dense keys, and numeric types — round-trip validated before exit. Objective value alone scores 0."**
2. **"Always discover EXTRACTOR_SPEC and write a `dump_plan()` skeleton before building constraints."**
3. **"Never let `None`, `LpVariable`, or empty strings reach `to_csv`. Coerce with `int(round(pulp.value(v) or 0))`."**
4. **"Always emit a fallback plan (zeros or heuristic) on solver failure — validity ≠ 0 is more valuable than blank cells."**