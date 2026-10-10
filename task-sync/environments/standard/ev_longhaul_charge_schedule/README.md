## Task Topic

Plan electric vehicle long-haul routes by factoring in vehicle battery state-of-charge telemetry, charging station real-time occupancy, driver hours-of-service limits, and delivery deadline windows to output a turn-by-turn charge-stop schedule per truck.

## Version Overview

| Version | rows_per_table | num_workspace_files | Active Deliveries |
|---------|----------------|---------------------|-------------------|
| v0      | 20             | 10                  | 5                 |
| v1      | 40             | 20                  | 10                |
| v2      | 80             | 30                  | 15                |
| v3      | 160            | 40                  | 20                |

Scaling ratios follow the standard progression: rows at 1×/2×/4×/8× of the v0 base, workspace files at base/base+N/base+2N/base+3N where N = 10 (the v0 base). Active deliveries equal half the workspace file count (one telemetry CSV and one HOS log per delivery).

Structural dimensions used by this task:

- **Information Scattering**: The truck's current state of charge and cargo weight live exclusively in per-truck telemetry CSV files, while the driver's continuous driving hours appear only in per-driver HOS log text files. Truck specifications and route segments are available only through tool calls. Configuration parameters (charging policy, HOS regulations, terrain efficiency factors, cargo weight multipliers) reside in separate workspace config files spanning four formats. No single source contains all the data needed for any one delivery's schedule.

- **Multi-Hop Reasoning**: Each delivery requires a chain of at least four dependent lookups — delivery details → truck specs via tool → telemetry file for current SoC and cargo weight → route segments via tool → station lookup per waypoint via tool — before the planning algorithm can even begin. The planning itself layers terrain factors from a CSV, weight factors from a Markdown table, and HOS rules from a YAML file on top of the tool-sourced data.

- **Conditional Constraints**: Charging stops are triggered by a state-of-charge threshold (from the charging policy JSON), rest stops by a continuous-driving-hours limit (from the HOS regulations YAML), and the combination of both at a single location follows overlap rules also defined in those config files. Station selection at multi-station locations is governed by a tie-breaking rule in the charging policy.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (file_format 10, delivery_coverage 15, stop_correctness 25, soc_accuracy 20, duration_accuracy 15, summary_response 15)
- Section 1 structural integrity: passed. Top-level contains README.md + v0/v1/v2/v3 only; each version has exactly data.py/env.py/prompt.md; env.py and prompt.md are byte-identical across versions; data.py differs only in SCALE.
- Section 2 solvability: solver written from prompt.md + get_assistant_tools() only; reached reward 1.0 on first run, no env.py escalation required.
- Section 3 env quality: prompt-step coverage and completeness aligned; ground truth derived dynamically from data.db/workspace; tolerances reasonable (SoC +-1.0, charge_dur +-2 min, rest +-1 min).
- Section 4 prompt quality: no headings, no bullets, no tool/source filenames; deliverable column names and rounding rules explicit; scale-invariant phrasing ("all deliveries whose status is pending").
- Issues found: none. No fixes needed.
- Cleanup: removed runtime artifacts (none persisted) and tmp solver.
