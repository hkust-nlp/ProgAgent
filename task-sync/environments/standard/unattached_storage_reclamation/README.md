## Task Topic

Identify unattached persistent storage volumes. Cross-reference volume creation timestamps, last attachment events, associated snapshot histories, and current project budget alerts to generate a reclamation report listing volumes unused for over 90 days with estimated monthly savings.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 10                  |
| v1      | 160            | 20                  |
| v2      | 320            | 30                  |
| v3      | 640            | 40                  |

The v0 base values are `rows_per_table = 80` and `num_workspace_files = 10` (N = 10). Scaling follows the standard ratios: v1 = 2× rows / +N files, v2 = 4× rows / +2N files, v3 = 8× rows / +3N files. Only the `SCALE` block in `data.py` differs across versions; `env.py` and `prompt.md` are shared byte-for-byte.

**Structural dimensions used:**

- **Information Scattering**: Pricing tiers, region multipliers, volume labels, and maintenance schedules live in workspace files (JSON, CSV, YAML), while volume details, attachment histories, snapshots, and budget alerts are only available through tool calls. Solving the task requires combining both sources.
- **Conditional Constraints**: Eligibility depends on multiple exclusion rules — volumes with specific labels (retain, do-not-delete, compliance-hold) from workspace CSV files must be filtered out, as must volumes listed in active maintenance windows from workspace YAML files. The unattached-days threshold itself comes from a policy YAML config.
- **Multi-Hop Reasoning**: The dependency chain is: list volumes (tool) → get attachment history per volume (tool) → compute days unattached using reference date from policy file → check labels across multiple workspace CSVs → check maintenance schedules → get snapshots (tool) → get project info (tool) → get budget alerts (tool) → apply pricing from JSON + region multipliers from CSV → produce final report.
- **Deliverable Constraints**: Exact column order, sort keys with tiebreaker, boolean formatting (True/False), two-decimal savings values, and specific summary statistics in the final response.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (`report_file_structure` 15, `correct_volume_set` 20, `sort_order` 15, `field_accuracy` 20, `summary_statistics` 15, `exclusion_filtering` 15)
- Section 1 (structural integrity): passed. Top-level contains only `README.md` and `v0/..v3/`; each version contains only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Section 2 (solvability at v3): solver written using only `v3/prompt.md` + `get_assistant_tools()` achieved reward 1.0 on first run. No escalation to read `env.py` was needed.
- Section 3 (env quality): every criterion in `step()` maps to a prompt requirement (CSV deliverable, column names, sort, exclusion rules, summary stats); ground truth is computed dynamically from the live DB and workspace, so no hard-coded counts.
- Section 4 (prompt quality): prose only, no headings/bold/bullets, columns and constraints described inline; no tool names or source-data filenames leaked; output filename `reclamation_report.csv` is permitted; no absolute counts.
- Issues found: none requiring fixes. No edits made to `v0/`.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from each version directory and removed `/tmp/solve_unattached_storage_reclamation.py`.
