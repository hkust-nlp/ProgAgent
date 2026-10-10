## Task Topic

Identify underutilized public facilities for potential consolidation. Analyze utility bills, scheduled maintenance logs, program attendance records, and annual capital improvement requests to flag buildings with occupancy below 30%, generating a recommendation report for closures or shared-space initiatives.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 20            | 10                  |
| v1      | 40            | 20                  |
| v2      | 80            | 30                  |
| v3      | 160           | 40                  |

`rows_per_table` determines the number of public facilities and serves as the minimum row count for each database table (utility_bills, maintenance_logs, program_attendance, and capital_improvement_requests all contain significantly more rows due to per-facility record multipliers). `num_workspace_files` controls the number of monthly occupancy survey CSV files; fixed policy/config files (consolidation_policy.yaml, annual_budgets.json, metric_definitions.md, zone_adjacency.txt) are produced at every scale.

### Structural Dimensions

- **Information Scattering**: Facility capacity and square footage are only available through tool calls, occupancy survey data lives exclusively in workspace CSV files, annual operating budgets reside in a separate JSON file, and scoring parameters are split between a YAML policy config and a Markdown definitions document. No single source is sufficient.
- **Multi-Hop Reasoning**: The dependency chain spans at least four hops — read policy YAML for thresholds → aggregate workspace CSVs for visitor averages → call facility tools for capacity to compute occupancy rates → for flagged facilities, call utility/maintenance/capital/attendance tools → combine with workspace budget data to compute component scores → apply policy recommendation thresholds.
- **Conditional Constraints**: Eligibility for consolidation depends on the occupancy threshold from the policy config; the consolidation score combines five weighted components with benchmark-relative clamping; and the recommendation label is assigned by score-tier thresholds, all defined in workspace configuration files rather than the prompt.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 8 (`report_structure`, `flagged_facilities`, `occupancy_accuracy`, `cost_metrics`, `maint_capital_metrics`, `consolidation_scores`, `recommendations_and_sort`, `response_summary`)
- Source-access: clean — solver completed using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no Section-6 escalation needed.
- Section 1 structural integrity: `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the SCALE block; no stray runtime artifacts.
- Section 2 solvability: solver scored 1.0 on first attempt; flagged 48 facilities at v3 scale.
- Section 3 env quality: every step criterion maps to an explicit prompt requirement; no hidden criteria; tolerances are reasonable; ground truth derived dynamically from `data.db`/workspace, so scale invariance holds.
- Section 4 prompt quality: prose-only, no headings/bold/lists for deliverables, no tool names, exact column names and rounding/sort rules specified, no absolute counts.
- Issues found: none. No edits required.
- Blockers: none.
