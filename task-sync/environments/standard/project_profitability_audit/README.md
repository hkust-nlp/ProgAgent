## Task Topic

Assess project profitability by cross-referencing architect timesheet entries, project budget allocations, client billing invoices, and vendor/subcontractor cost ledgers to identify projects with significant budget overruns, outputting a detailed variance report for management review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 8                   |
| v1      | 60             | 16                  |
| v2      | 120            | 24                  |
| v3      | 240            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=8.

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across database tools and workspace files in four formats (CSV, JSON, YAML, TXT). Overhead multipliers live in a YAML config, architect role premiums are spread across multiple JSON files, retention percentages across CSV batches, indirect costs across TXT logs, and change orders across YAML files. No single source suffices.
- **Multi-Hop Reasoning**: Computing actual labor cost requires a chain of length ≥ 3: list projects (tool) → retrieve timesheet entries per project (tool) → look up each architect's hourly rate (tool) → look up role multiplier from workspace JSON → apply overhead multiplier from workspace YAML → sum. Adjusted budget similarly chains budget allocations (tool) with change order amounts (workspace YAML).
- **Conditional Constraints**: Variance classification depends on threshold ranges defined in a workspace JSON policy file; the agent must parse and apply these dynamically.
- **Deliverable Constraints**: Output CSV must have 14 columns in exact order, all monetary values rounded to 2 decimal places, sorted descending by variance percentage. The action text must include classification counts and top-3 overrun projects.

## Harness Report

- v3 solver reward: 1.0 (100/100).
- Number of eval criteria: 7 (`report_structure`, `project_coverage`, `adjusted_budget_accuracy`, `actual_costs_accuracy`, `variance_classification`, `sort_order`, `action_summary`).
- Source-access escalation: not required. Solver passed using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`.
- Structural integrity: `v0/v1/v2/v3` each contain exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the top-level `SCALE` dict.
- Issues found / fixes: none. No edits to `v0/` were needed.
- Cleanup: removed all `data.db`, `workspace/`, and `__pycache__/` runtime artifacts and the temporary solver script.
- Blockers: none.
