## Task Topic

Produce a venue utilization and maintenance schedule by analyzing the upcoming fixture calendar, historical pitch wear data, contracted third-party events, and ground staff shift patterns to optimize pitch readiness and allocate resources.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 40             | 8                   |
| v1      | 80             | 16                  |
| v2      | 160            | 24                  |
| v3      | 320            | 32                  |

Structural dimensions used:

- **Conditional Constraints**: Maintenance eligibility depends on surface type exclusions, wear-index thresholds (from a YAML policy file), recent-maintenance adjustments (from log files), weather precipitation limits, and staff skill-level plus certification requirements. These span multiple tables and workspace config files.
- **Information Scattering**: Venue metadata and fixture/event/wear data live in the database (tool-accessible only), while maintenance history logs, weather forecasts, staff certifications, scheduling policy, and priority rules are split across workspace files in four different formats (YAML, JSON, CSV, TXT/MD).
- **Multi-Hop Reasoning**: The dependency chain for each scheduling decision is at least four hops deep: venue details (tool) -> latest wear record (tool) -> maintenance log adjustment (file) -> adjusted wear -> policy thresholds (file) -> maintenance type -> eligible date selection requiring fixture check (tool) + event check (tool) + weather check (file) -> staff availability (tool) + certification check (file) -> final assignment.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (schedule_file_format=10, venue_maintenance_identification=20, no_scheduling_conflicts=15, valid_staff_assignments=15, priority_scores_correct=15, utilization_report_correct=15, response_summary=10)
- Source-access: clean — solver written from `v3/prompt.md` + `Task_Env.get_assistant_tools()` only; passed on first attempt.
- Structural integrity: clean. v0..v3 differ only in the `SCALE` block; `env.py` and `prompt.md` byte-identical across versions.
- Prompt-step alignment: every criterion in `step` traces to a prompt requirement; deliverables, columns, sort orders, and summary fields all enforced.
- Issues found: none requiring fixes. Minor non-blocker noted: `_compute_ground_truth` line ~631 references an undefined `PLANNING_DAYS` symbol guarded by `hasattr(self, '_planning_days')` (always False), so the `else` branch (30) is always taken — dead code, no runtime impact.
- Blockers: none.
