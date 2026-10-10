## Task Topic

Identify unauthorized subletting and occupancy violations. Cross-reference tenant lease agreements, utility consumption patterns, property access logs, and resident complaint histories to output a list of units requiring formal investigation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Scaling ratios: `rows_per_table` follows 1×/2×/4×/8× of the v0 base (50). `num_workspace_files` follows base/base+N/base+2N/base+3N where N = 10 (the v0 base).

### Structural dimensions

- **Information Scattering**: Task-critical data is split across workspace files (utility CSVs, access card JSONs) and tool calls (lease details, complaint records). Neither source alone is sufficient; the agent must read files for consumption and access patterns, then call tools for lease constraints and complaint categories.
- **Conditional Constraints**: Flagging a unit requires evaluating a multi-signal scoring formula with thresholds, multipliers, per-complaint caps, and a conditional bonus (subletting-prohibited applies only when other signals are already present). All parameters reside in a workspace YAML policy file.
- **Deliverable Constraints**: The output CSV enforces exact column names, semicolon-separated alphabetically-sorted signal lists, a specific sort order (score descending, unit_id ascending as tiebreaker), and yes/no subletting encoding.
- **Multi-Hop Reasoning**: Utility CSV → compute per-unit average → tool call for max_occupants → compare against policy threshold → tool call for complaints → check categories against policy concern list → apply conditional subletting bonus → aggregate score → compare against investigation threshold.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (`flagged_precision`, `flagged_recall`, `correct_scores`, `correct_signals`, `sort_order`, `response_units`)
- Source-access escalation: not needed (clean — solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`)
- Issues found / fixes: none
- Blockers: none

Section 1 (structural integrity), Section 2 (solvability at v3 scale), Section 3 (env quality — implicit via 100% reward), Section 4 (prompt quality), and Section 5 (cleanup) all pass on first attempt.
