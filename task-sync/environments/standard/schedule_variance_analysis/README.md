## Task Topic

Monitor project schedule compliance. Analyze daily equipment telemetry, labor timecard allocations, material procurement status updates, and weather delay logs against the baseline Gantt chart to generate a variance report with critical path impact assessments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Planned schedule and budget data live exclusively in workspace CSV files (gantt_baseline.csv, budget_allocation.csv). Actual progress, labor hours, equipment telemetry, procurement quantities, and weather delays are only accessible through tool calls to the database. Worker hourly rates (needed to compute labor cost) are in a YAML roster file, while equipment daily rental costs are in a JSON registry. Risk flags are spread across daily inspection reports in five different file formats (.md, .json, .csv, .txt, .yaml).

- **Multi-Hop Reasoning**: Computing actual cost requires a chain of length ≥ 3: query labor summary per task (tool) → look up worker hourly rate from roster (YAML file) → apply overtime multiplier from thresholds config (JSON file) → sum with material cost from procurement query (tool) and equipment cost derived from equipment summary (tool) cross-referenced with equipment registry (JSON file).

- **Conditional Constraints**: Impact assessment depends on multiple interacting conditions — critical-path status, schedule variance thresholds, and cost variance percentage thresholds — all read from a workspace configuration file. Weather delay weighting depends on severity-to-weight mappings in a separate policy file.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 7 (`report_structure` 10, `task_coverage` 15, `schedule_variance_accuracy` 25, `cost_variance_accuracy` 20, `critical_path_and_weather` 15, `impact_assessment_accuracy` 15, `response_summary` 10)
- Issue found: `env.py` compared `is_critical_path` from the gantt CSV using `str(r["is_critical_path"]) == "TRUE"`, but `pandas.read_csv` auto-coerces the column to Python booleans, so `str(True)` is `"True"` (not `"TRUE"`). All tasks were therefore treated as off the critical path, breaking `_compute_ground_truth`'s `is_critical_path` column, the impact-assessment CRITICAL branch, and the `get_task_predecessors` tool's flag.
- Fix: Replaced the three occurrences in `v0/env.py` with `str(...).upper() == "TRUE"` (in `_compute_ground_truth`, `verify`, and `get_task_predecessors`) and re-propagated byte-identically to v1/v2/v3. v3 solver then scored 1.0.
- Other checks: structural integrity OK (only `data.py` differs across versions, only in `SCALE`); `data.py` runs cleanly at v3 (400 rows, 46 workspace files); prompt.md is prose-form without headings, lists, tool names, or absolute counts; step's eval criteria all map to prompt requirements; tolerances are reasonable and ground truth is recomputed from the live DB / workspace.
- Blockers: none.
