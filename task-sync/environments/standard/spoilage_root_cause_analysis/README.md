## Task Topic

Identify the source of post-harvest spoilage in leafy greens by analyzing temperature logs from refrigerated transport, warehouse humidity records, batch harvest timestamps, and quality inspection reports, producing a root-cause analysis with corrective action recommendations.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 8                   |
| v1      | 120           | 16                  |
| v2      | 240           | 24                  |
| v3      | 480           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8× of v0 base (60). Workspace scalable files follow base/base+N/base+2N/base+3N where N = 8.

**Structural dimensions used:**

- **Information Scattering**: Field conditions at harvest (temperature, rainfall) are only available in workspace CSV files and are not exposed through any tool. Transport/warehouse data is only accessible via tool calls. Crop-specific thresholds and severity classifications live in workspace config files (YAML/JSON). The agent must combine all three sources to determine root causes.
- **Multi-Hop Reasoning**: The dependency chain is: (1) read spoilage classification config to learn the flagged threshold, (2) call `find_flagged_inspections` with that threshold, (3) for each flagged batch call `get_batch_details` to learn crop type, (4) call `get_transport_legs` then `get_temperature_readings` per leg, (5) call `get_warehouse_records`, (6) read field condition CSVs for harvest-time weather, (7) look up crop-specific thresholds from YAML config, (8) apply ordered classification rules. This is a chain of length >= 4.
- **Conditional Constraints**: Root cause classification depends on crop-specific thresholds (6 crop types x 5 threshold parameters), applied in strict priority order. The first matching rule wins.
- **Deliverable Constraints**: Output CSV must have exact column order and descending sort. JSON must contain exact counts and quantities. Action string must use specified format strings.

## Harness Report

- v3 reward: 1.0
- Number of eval criteria: 7 (csv_format, batch_identification, root_cause_accuracy, severity_accuracy, sort_order, corrective_actions, action_summary)
- Source-access: clean (solver used only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed).
- Structural integrity: passed. Top-level holds only `README.md` + `v0..v3/`. Each version directory contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Issues found: none. The solver succeeded on first complete pass once the env tool return shapes (`{'inspections': [...]}`, `{'legs': [...]}`, `{'readings': [...]}`, `{'records': [...]}`) were correctly unpacked.
- Blockers: none.
