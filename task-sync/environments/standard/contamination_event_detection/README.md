## Task Topic

Identify potential seed lot contamination events during storage. Correlate warehouse environmental sensor logs, lot movement histories, pest control treatment schedules, and adjacent lot phytosanitary statuses to flag compromised inventory, producing a quarantine advisory list for suspect lots.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Lot metadata (crop type, variety, grade) lives in workspace manifest files, while current locations and inspection results are only accessible via tools. Sensor daily summaries are in workspace CSVs, but phytosanitary outcomes and pest treatment schedules require tool calls. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The MOVEMENT_EXPOSURE flag requires a chain of length 4: retrieve lot movement history (tool) → identify previous zones and date ranges → look up sensor maximums for those zones/dates (workspace files) → compare against crop-specific thresholds (config file). The ADJACENT_CONTAMINATION flag similarly chains: find failed-inspection lots (tool) → get their current zones (tool) → check adjacency mapping (workspace file) → flag neighboring lots.
- **Conditional Constraints**: Contamination determination depends on crop-specific thresholds (from YAML config), temporal overlap between lot stays and sensor exceedances, grace-period calculations for overdue treatments, and tiered action assignment based on cumulative risk scores (from JSON config).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (file_structure 10, lot_identification 25, contamination_flags 20, risk_scores 15, recommended_actions 15, response_summary 15)
- Solver source-access: clean black-box solve using only `v3/prompt.md` + `Task_Env.get_assistant_tools()` (no Section-2 step-6 escalation; `env.py` was opened only later for Section 3 review).
- Issues found: none. Structural integrity (single-source v0, byte-identical env.py/prompt.md across versions, only SCALE differing in data.py) verified. Env step() recomputes ground truth from data.db / workspace at runtime, so it is scale-invariant. Prompt formatting follows the no-title, no-headers, prose-only conventions; no tool names or source filenames are leaked.
- Solver note: MOVEMENT_EXPOSURE includes from-zones equal to the current zone (the prompt's "previously resided" reading does not exclude the current zone); aligning with that interpretation moved the solver from 0.97 to 1.0.
