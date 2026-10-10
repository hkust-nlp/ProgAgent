## Task Topic

Detect anomalous residential energy consumption by cross-referencing smart meter interval data, household appliance registration databases, local weather station feeds, and tariff change logs to pinpoint faulty meters or unauthorized usage, producing a field inspection list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Structural dimensions used:

- **Information Scattering**: Actual consumption comes from tool-accessible meter readings; expected baselines require tool-fetched appliance registrations plus weather data; billing figures live in workspace CSVs; maintenance issues are in workspace JSONs; detection thresholds and priority rules sit in workspace config files (YAML, Markdown, TXT). No single source suffices.
- **Multi-Hop Reasoning**: Appliance registry (tool) → base expected kWh → weather observations (tool) → adjusted expected → meter readings (tool) → deviation ratio → maintenance logs (workspace JSON) → anomaly classification → priority rules (workspace MD) → final ranked inspection list. The dependency chain has length ≥ 4.
- **Conditional Constraints**: Anomaly type depends on whether the meter has maintenance issues (faulty_meter vs unauthorized_usage); weather adjustment differs by heating type (electric/heat_pump vs gas); billing discrepancy is only assigned when no consumption anomaly was already flagged.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (inspection_list_exists, correct_anomaly_count, correct_household_identification, correct_anomaly_classification, correct_deviation_values, correct_priority_ranking)
- Solver source-access: clean black-box. The solver was authored from `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()` only; no Section 2 step-6 escalation was required. `env.py` was first opened in Section 3 for prompt-step alignment review.
- Issues found: none. Section 1 byte-for-byte invariants passed (env.py and prompt.md identical across v0..v3; data.py differs only in the SCALE block with rows 50/100/200/400 and files 8/16/24/32, matching the 1x/2x/4x/8x and base+0/N/2N/3N ratios). Section 3 found criteria coverage, scale invariance, and matching strictness (±0.03 deviation tolerance, exact sort order) consistent with the prompt. Section 4 prompt formatting was clean (no headings, no bullets, scale-invariant wording).
- Fixes applied: none.
- Blockers: none.
