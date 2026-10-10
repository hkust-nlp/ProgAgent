## Task Topic

Detect unpermitted short-term rental properties. Analyze property tax records, rental platform listing data, utility consumption patterns, and occupancy permit registries to output a compliance case file for enforcement with evidence summaries.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Structural dimensions used:

- **Information Scattering**: Complaint counts are only available from workspace CSV files (keyed by address), permit data is only available via tools (keyed by property_id), platform revenue estimates are in workspace JSON files, and property details come from tool calls. Solving the task requires joining across all these sources.
- **Conditional Constraints**: Violation classification depends on zoning rules (from a workspace JSON config), permit status checks (via tools), and risk-score computation uses thresholds and modifiers defined in a workspace YAML config file. The recommended enforcement action is determined by score tiers in the same config.
- **Multi-Hop Reasoning**: Active listings (tool) → property zone (tool) → zoning rules (file) → permit check (tool) → utility baseline lookup (file) → utility history (tool) → complaint count (file) → risk score computation → action tier (file).

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 6 (csv_structure, property_identification, violation_types, risk_scores, recommended_actions, response_summary).
- Source-access path: clean. Solver written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`. No step-6 escalation; `env.py` was never opened.
- Structural integrity: passed. Top-level contains `README.md` + `v0..v3`; each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across all four versions; `data.py` differs only in the `SCALE` block (rows ×1/2/4/8, files +0/N/2N/3N).
- Issues found: none. The task is solvable as-specified; prompt.md, env.py, and data.py are mutually consistent. (One initial solver miss came from the solver guessing the wrong permit_type literal — agents at runtime observe permit records via `get_permit_status`, so this is not a task defect and no fix was applied.)
- Final clean-up: removed runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) and the temporary solver.
