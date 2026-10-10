## Task Topic

Analyze historical bug fix times, current developer availability, customer contract SLA tiers, and feature usage telemetry to assign a priority score and recommended assignee for each new bug, outputting a ranked queue for the weekly triage meeting.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Assignee eligibility depends on workload cap (active_bugs / max_concurrent_bugs < 0.85), critical-severity experience minimum (≥ 5 years), available hours, and PTO thresholds — all read from workspace config files and cross-referenced with developer profiles retrieved via tools.
- **Information Scattering**: New bug details live in workspace files (mixed .json/.md/.yaml/.txt formats), developer availability in workspace CSVs, while customer contract tiers, feature telemetry, and historical fix records are only accessible through tool calls. Scoring weights and team-module mappings are in separate workspace config files.
- **Multi-Hop Reasoning**: Bug report → customer ID → tool call for contract tier → SLA urgency score; Bug report → feature ID → tool call for telemetry + tool call for historical fix records → normalized feature impact + complexity scores; Module → team mapping config → tool call for team roster → schedule CSV cross-reference → assignee selection.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (triage_csv_structure, priority_scores_accuracy, ranking_order, assignee_accuracy, sla_tier_accuracy, response_top3_summary, estimated_fix_hours_accuracy)
- Source-access: Section 2 escalated to step 6.2 (read v3/env.py) once. All other sections used only prompt.md plus the public Task_Env interface.
- Issues found and fixes:
  - Prompt ambiguity for the historical-complexity component when a feature has no historical fix records. The prompt only specified the no-history fallback for `estimated_fix_hours`, leaving the complexity score undefined; `step` (correctly) treats the missing average as the global maximum, which makes the urgency nudge zero. Fixed in `v0/prompt.md` with an explicit sentence ("treat its average fix time as the largest average fix time observed across all features for the purpose of this component") and re-propagated byte-identically to v1/v2/v3.
- Blockers: none.
