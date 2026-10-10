## Task Topic

Monitor delivery fleet adherence to customer site geofence policies. Correlate GPS location pings, customer contract service-level agreements, driver shift logs, and geofence violation incident reports to generate a weekly compliance scorecard per depot with flagged drivers for retraining.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 15             | 10                  |
| v1      | 30             | 20                  |
| v2      | 60             | 30                  |
| v3      | 120            | 40                  |

Scaling ratios: rows_per_table follows 1×, 2×, 4×, 8× of the v0 base (15). num_workspace_files follows base, base+N, base+2N, base+3N where N = 10 (the v0 base).

The task exercises the following structural dimensions:

- **Information Scattering**: Scoring parameters (severity weights, SLA tier multipliers, retraining thresholds) live in workspace configuration files (JSON/YAML), while violation records, driver rosters, and customer contracts are only accessible through tool calls. Incident adjustment factors are spread across multiple workspace CSV files. Solving the task requires combining data from both sources.
- **Multi-Hop Reasoning**: Computing a single violation's penalty requires a chain of at least four lookups: violation record (tool) → customer_id → contract/SLA tier (tool) → tier weight multiplier (workspace YAML) → adjustment factor (workspace CSV) → final penalty. SLA breach detection adds another hop checking per-customer violation counts against contractual limits.
- **Deliverable Constraints**: Output CSVs have exact column names and ordering, numeric precision (two decimal places), specific sort keys with tie-breakers, and prescribed string values for flag reasons and recommended actions.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 6 (`scorecard_structure` 15, `scorecard_completeness` 15, `scorecard_accuracy` 25, `flagged_structure` 10, `flagged_accuracy` 25, `response_summary` 10).
- Source-access: clean. Solver written using only `v3/prompt.md` plus the public `Task_Env.get_assistant_tools()` interface; no escalation to `env.py` or `data.py` was required.
- Structural integrity: passes. Top-level contains only `README.md` and `v0..v3/`; each `v_n/` contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions. `data.py` differs only in the `SCALE` block (rows 15/30/60/120, files 10/20/30/40 -- matches the ×1/2/4/8 row and +0/N/2N/3N file convention).
- Prompt quality: passes. No top heading, no bold headers, no bullet/numbered lists for deliverables, computation logic in prose, no tool or source-data filenames mentioned, output filenames and column orders explicit, scale-invariant wording ("every depot", "all drivers").
- Env quality: passes. `step` derives ground truth from `data.db` and the workspace configs, no hardcoded counts; all six criteria align with prompt requirements (scorecard schema/values, flagged-drivers schema/values, response summary). Numeric tolerance is 0.05 for compliance and weighted-severity scores; categorical fields use exact match.
- Issues found and fixed: none. No edits to `v0/` were necessary.
- Blockers: none.
