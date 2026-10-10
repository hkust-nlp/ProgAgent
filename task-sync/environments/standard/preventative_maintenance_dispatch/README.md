## Task Topic

Optimize preventative maintenance schedules to minimize unscheduled downtime. Analyze vehicle telemetry (mileage, engine hours), upcoming reservation calendars, parts inventory levels, and technician certification rosters to generate a prioritized weekly maintenance dispatch list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task uses the following structural dimensions:

- **Conditional Constraints**: Eligibility for scheduling depends on overdue-ratio thresholds (due vs. critical), technician certification level requirements per maintenance type, depot matching between vehicles and technicians, and daily/weekly hour caps — all parameterized in workspace configuration files rather than hard-coded.
- **Information Scattering**: Current vehicle telemetry (odometer, engine hours) lives exclusively in workspace CSV files, while service history and maintenance rules are only accessible through tool calls. Reservation calendars are workspace-only JSON files, and parts inventory is DB-only. Solving the task requires merging data from both sources.
- **Multi-Hop Reasoning**: The dependency chain is at least four hops deep: read telemetry files → query service history per vehicle → look up maintenance rules by category → compute overdue ratios → check parts availability → match technicians by certification and depot → apply greedy scheduling with constraint propagation.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 8 (`dispatch_file_format`, `vehicle_coverage`, `urgency_scores`, `priority_ranking`, `technician_validity`, `parts_status`, `scheduling_validity`, `response_summary`)
- Source-access: clean. Solver wrote against `v3/prompt.md` + `Task_Env(...).get_assistant_tools()` only; no escalation to step 6 was needed.
- Section 1 structural integrity: passed. `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the top-level `SCALE` block.
- Section 2 solvability: solver at `/tmp/solve_preventative_maintenance_dispatch.py` ran once at v3 scale (400 rows, 32 workspace files) and produced reward 1.0 on first attempt.
- Section 3 env quality: every criterion in `step()` is grounded in `prompt.md`; ground truth is recomputed from the live DB and workspace, so scoring is scale-invariant. No over-normalization.
- Section 4 prompt quality: no headings, no bulleted/numbered deliverable lists, no tool or internal filenames leaked, scale-invariant wording (e.g. "every vehicle"), output filenames and column orders explicit.
- Issues found: none. No edits to `v0/` or v1..v3 were required.
- Blockers: none.
