## Task Topic

Optimize daily technician schedules by cross-referencing live vehicle GPS locations, real-time traffic data, job priority tiers, and parts inventory levels at service vans to minimize travel time and missed appointments, producing a validated route sequence for each technician.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 15            | 8                   |
| v1      | 30            | 16                  |
| v2      | 60            | 24                  |
| v3      | 120           | 32                  |

Scaling ratios follow the standard progression: rows scale as 1x/2x/4x/8x; workspace files scale as N/N+N/N+2N/N+3N where N=8.

At v0: 15 technicians, 30 jobs, 7 zones, 15 part types, 13 workspace files (8 scalable + 5 fixed config).
At v3: 120 technicians, 240 jobs, 14 zones, 120 part types, 37 workspace files (32 scalable + 5 fixed config).

### Structural Dimensions

- **Conditional Constraints**: Technician eligibility depends on skill level meeting job requirements, van parts inventory satisfying job needs (with substitution rules from a config file), and shift boundaries. Priority tier ordering is governed by a YAML configuration file.
- **Deliverable Constraints**: Output must be a CSV with exact column order, HH:MM time formatting, decimal-rounded travel minutes, and specific summary lines in the response.
- **Information Scattering**: GPS positions exist only in workspace CSV files; site access windows exist only in workspace JSON files; traffic conditions are only available via tool queries; road-condition multipliers and zone adjustments live in separate workspace config files. No single source suffices.
- **Multi-Hop Reasoning**: Determining actual travel time requires: reading GPS file (current zone) -> querying traffic tool (base time + congestion + road condition) -> reading scheduling_rules.json (road multiplier) -> reading travel_adjustments.csv (zone factor) -> computing the product. Scheduling each job further requires cross-referencing parts inventory (tool) against job requirements (tool) against substitution rules (workspace JSON).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (route_file_format, job_coverage, unique_assignment, skill_compliance, parts_compliance, time_compliance, priority_ordering)
- Source-access: clean — solver authored from `v3/prompt.md` plus `get_assistant_tools()` only; `env.py` opened post-solve for Section 3 review.
- Structural integrity: passed. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` dict (rows 15/30/60/120, files 8/16/24/32).
- Solvability: solver at `/tmp/solve_dynamic_daily_routing.py` produced `route_plan.csv` (234 of 240 jobs scheduled, total travel 2731.9 min) and scored 1.0 on first submission.
- Env quality (Section 3): all 7 step criteria map back to prompt requirements; ground truth derives from current `data.db`/workspace (no hard-coded counts); thresholds (0.95) are reasonable; no over-normalization. Minor observation: the two required summary lines in the response are not separately graded by `step()`, but this is acceptable since the CSV is the substantive deliverable and the prompt's coverage requirement is captured by `job_coverage`.
- Prompt quality (Section 4): no title/heading, no bold or list formatting, scale-invariant wording, no tool names or DB filenames leaked, deliverable column names and time format spelled out.
- Issues found: none requiring fixes.
- Blockers: none.
