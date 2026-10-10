## Task Topic

Plan school bus evacuation staging. Cross-reference student home addresses, bus GPS capacity logs, designated shelter locations with capacity limits, and road network bridge weight restrictions to produce per-school loading schedules and bus dispatch routes.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 10                  |
| v1      | 60            | 20                  |
| v2      | 120           | 30                  |
| v3      | 240           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Bus deployability depends on fuel level vs. policy threshold and maintenance status (from workspace CSV files); shelter feasibility depends on current status (closed/reduced from workspace JSON) and remaining capacity; route feasibility depends on loaded bus weight vs. effective bridge limits (base from DB, overrides from workspace JSON).
- **Information Scattering**: Bus specs (capacity, weight, accessibility) live in the database, but operational readiness (fuel, driver cert, maintenance status) is only in workspace CSV files. Shelter base capacity comes from the database, but closures and reductions are only in a workspace JSON file. Bridge weight limits have a base value in the DB but may be overridden by a workspace inspection-updates file.
- **Multi-Hop Reasoning**: To validate a bus-route assignment requires: query bus specs (Tool) -> read bus fuel/status (workspace CSV) -> query route segments (Tool) -> query each segment's bridge limit (Tool) -> check bridge-update overrides (workspace JSON) -> compute loaded weight using passenger weight factor (workspace YAML policy) -> compare against effective bridge limit.
- **Deliverable Constraints**: Three output files with exact column names, semicolon-separated ID lists sorted ascending, decimal formatting to two places, and a final response line in a prescribed format.

## Harness Report

- v3 reward: 1.0 (110/110)
- Number of eval criteria: 9 (loading_schedule_format, dispatch_routes_format, all_students_assigned, no_capacity_violations, bridge_weight_respected, shelter_capacity_respected, only_deployable_buses, evacuation_summary, response_summary)
- Source-access: escalated to Section 2 step 6 to inspect `v3/env.py` and confirm the reference `find_bus_for_route` falls back to non-accessible buses when accessible ones are exhausted; once the solver mirrored that behavior the v3 run returned 1.0 with no fixes required.
- Issues found: none. Structural integrity, scale-invariant scoring, prompt formatting, and SCALE propagation all verified clean.
