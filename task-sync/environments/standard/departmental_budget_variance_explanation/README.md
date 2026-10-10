## Task Topic

Analyze departmental budget variance by correlating general ledger actuals, purchase order commitments, vendor invoice line items, and project milestone forecasts to identify overspending categories, outputting a variance explanation report with flagged items exceeding 10% variance.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: The adjusted budget requires combining base allocations (tool) with amendments (workspace CSVs). Open PO committed amounts require vendor discount rates from workspace JSON files. Milestone forecasts require risk adjustment factors from workspace YAML files. No single source is sufficient.
- **Multi-Hop Reasoning**: Computing total exposure for a department-category pair requires a chain of at least length 3: retrieve budget allocations (tool) → read amendments (workspace CSV) → query GL entries (tool) → query open POs (tool) → look up vendor discounts (workspace JSON) → query project milestones (tool) → look up risk factors (workspace YAML) → compute variance → determine flagging → query invoice lines for top vendor (tool).
- **Conditional Constraints**: Flagging depends on the variance threshold from the workspace policy file; PO committed amounts are conditionally discounted based on vendor contract terms; only "Open" POs and "Pending" milestones contribute to exposure.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 7 (`report_file_format`, `row_coverage`, `adjusted_budget_accuracy`, `gl_actual_accuracy`, `total_exposure_accuracy`, `variance_pct_accuracy`, `flagged_items_in_response`).
- Structural integrity: removed stray `__pycache__/` directories from `v0`, `v1`, and `v3`. `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 80/160/320/640, files 8/16/24/32).
- Solvability: solved at v3 scale using only `prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was required. The only solver-side gotcha was that `list_projects` returns project entries keyed as `project_name` rather than `name`.
- Env quality (Section 3): no issues. All seven criteria correspond to explicit prompt requirements; ground truth is computed from the live `data.db` / workspace / `data.py`.
- Prompt quality (Section 4): no issues. No headings, no bullet lists for deliverables, scale-invariant wording, exact column names specified, no tool or `env.py` internals leaked.
- Cleanup: removed all `data.db`, `workspace/`, and `__pycache__/` artifacts from each version, and the temporary solver at `/tmp/solve_departmental_budget_variance_explanation.py`.
- Blockers: none.
