## Task Topic

Validate deployment readiness by cross-referencing recent commit test coverage percentages, open high-priority Jira tickets, environment-specific configuration drift reports, and last successful security scan timestamps to output a go/no-go dashboard with blocking issues.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

Structural dimensions used:

- **Information Scattering**: Decision thresholds, required scan types, and release scope live in workspace files (YAML, JSON), while live data on commits, tickets, drift, and scans is only accessible through tool calls. Solving the task requires combining both sources.
- **Conditional Constraints**: The go/no-go decision depends on multi-table business rules — service criticality determines coverage thresholds and required scan types; drift severity is compared against a policy-defined maximum; Jira blocking depends on both priority and status matching policy criteria.
- **Multi-Hop Reasoning**: Release manifest → service IDs → service criticality (tool) → required scan types (policy file) → scan history (tool) → freshness and vulnerability check against policy thresholds. This is a dependency chain of length ≥ 4.
- **Deliverable Constraints**: The output CSV has a fixed column order, specific formatting (two-decimal coverage, PASS/FAIL statuses, semicolon-separated issues), required sort order, and a companion JSON file with a prescribed structure.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (`dashboard_file_exists` 10, `correct_columns` 10, `correct_pairs` 15, `correct_go_nogo` 25, `correct_status_columns` 15, `blocking_issues_file` 15, `summary_in_response` 10)
- Section 1 (structural integrity): passed. Top-level contains only `README.md` and `v0/..v3/`. Each version directory contains exactly `data.py`, `env.py`, `prompt.md`. `diff` confirmed `env.py` and `prompt.md` are byte-identical across v0..v3, with `data.py` differing only in the `SCALE` block (rows ×1/2/4/8 = 50/100/200/400; files +0/N/2N/3N = 10/20/30/40).
- Section 2 (solvability at v3): solved on the first attempt using only `v3/prompt.md` and the public `Task_Env.get_assistant_tools()` interface. Solver wrote `deployment_dashboard.csv` and `blocking_issues.json` under `workspace/` and submitted the summary via `env.step(...)`; reward returned 1.0. No escalation to step 6 was needed; `env.py` was not opened during solving.
- Section 3 (env quality): coverage and completeness verified — each criterion in `step` maps to a requirement explicitly stated in `prompt.md`, and every prompt deliverable (CSV, JSON, summary) is scored. Ground truth is computed dynamically from `data.db` + workspace files, so criteria are scale-invariant.
- Section 4 (prompt quality): no headings, bold sections, or bulleted deliverable lists; no tool/source-table names leak; column names and file names are explicit; phrasing ("each service", "every target environment") is scale-invariant.
- Issues found and fixes: none. No edits were required to `v0/` or any propagated copy.
- Section 5 cleanup: removed runtime `data.db`, `workspace/`, and `__pycache__/` from every `v_n/`, and deleted the `/tmp/` solver. Final tree is `README.md` plus `v0/..v3/` only.
