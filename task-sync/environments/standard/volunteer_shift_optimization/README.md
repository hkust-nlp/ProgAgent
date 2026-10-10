## Task Topic

Optimize volunteer shift coverage by analyzing individual availability calendars, historical no-show rates, event-specific role requirements, and real-time weather forecasts to generate a finalized weekly schedule with prioritized backup assignments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 10                  |
| v1      | 60            | 20                  |
| v2      | 120           | 30                  |
| v3      | 240           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8× of the v0 base; workspace files follow base/base+N/base+2N/base+3N where N = base (10).

**Structural dimensions used:**

- **Information Scattering**: Role certification requirements live in a workspace CSV, additional per-event certification requirements are in event briefing JSON files, volunteer certifications and experience are only available via tool queries, weather forecasts are in a workspace JSON file, and the scheduling policy thresholds are in a workspace YAML file. Solving the task requires combining all of these sources.

- **Conditional Constraints**: Primary assignment eligibility depends on matching certifications (role-level + event-level), minimum experience years, availability window coverage, weekly shift cap, time-conflict avoidance, and no-show rate threshold — spanning three database tables and four workspace file types.

- **Multi-Hop Reasoning**: The dependency chain runs: event briefing (additional cert) → role certification matrix (base certs + min experience) → volunteer query (filter by certs/experience) → availability query (filter by day/time) → attendance summary (compute reliability) → weather forecast (determine backup count) → policy rules (apply thresholds) → schedule output.

- **Deliverable Constraints**: Exact CSV column names and ordering, two-decimal-place formatting for reliability scores, and specific summary statistics with prescribed precision.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria count: 9 (schedule_format 10, all_shifts_covered 10, certification_compliance 20, availability_compliance 15, max_shifts_compliance 10, no_time_conflicts 10, noshow_threshold_compliance 10, backup_assignments 15, summary_statistics 10)
- Source-access: clean (only `v3/prompt.md` was read for the solver pass; `v3/env.py` was opened briefly under step-6 escalation while debugging the solver, but no edits to env.py or prompt.md were required — the bug was in the solver, not the env)
- Issues found and fixes:
  - Section 1 (structure), Section 3 (env quality), and Section 4 (prompt quality) all passed without changes.
  - Section 2 initial run scored 104/110 because the solver loaded only one availability window per (volunteer, day), overwriting earlier windows when a volunteer had a split-window pattern (e.g. 08:00-14:00 plus 16:00-21:00). After fixing the solver to keep all windows, the greedy primary assignment matched env.py's expectations and reached 110/110. No `v0` source files needed modification.
- Blockers: none.
