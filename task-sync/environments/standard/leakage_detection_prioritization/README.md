## Task Topic

Identify water distribution zones with persistent high leakage. Cross-reference hourly flow meter readings, district pressure sensor data, pipe age and material logs, and maintenance work order history to flag zones where loss exceeds 15% for 72 hours, outputting a prioritized repair schedule.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 120            | 10                  |
| v1      | 240            | 20                  |
| v2      | 480            | 30                  |
| v3      | 960            | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Pipe inventory data (material, age, condition scores) lives exclusively in workspace CSV files, while flow readings, pressure sensors, and work orders are only accessible through tool calls. Both sources are required to compute the composite priority score.
- **Conditional Constraints**: Zones are flagged only when hourly loss exceeds a threshold for a required number of consecutive hours (parameters from `leakage_policy.yaml`). Priority scoring uses weighted normalization with material risk multipliers and age/condition formulas from `material_risk_factors.json`.
- **Multi-Hop Reasoning**: The dependency chain is: list zones (Tool) → get flow summary (Tool) → get detailed hourly flow (Tool, multiple windows) → compute consecutive-hour check → read pipe inventory (File) → apply material risk formulas (File) → get pressure anomalies (Tool) → get work orders (Tool) → read zone details (Tool) → normalize and compute composite score → assign recommended action.
- **Deliverable Constraints**: Output CSV has exact column names, specific decimal precision (2 for most fields, 4 for anomaly rate), defined sort order with alphabetical tie-breaking, and action labels determined by composite score thresholds.

## Harness Report

- v3 reward: 1.00 (100/100)
- Eval criteria (6): flagged_zones_correct (20), schedule_file_format (15), priority_ranking (20), loss_values_accuracy (15), recommended_actions (15), response_completeness (15)
- Source-access: clean — solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. `env.py` was inspected only after solver mismatches localised to the solver itself (work-order count extraction bug); no env/prompt changes were required.
- Structural integrity: v0/v1/v2/v3 contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; only `SCALE` differs in `data.py`.
- Issues found: none in env or prompt. Prompt-step coverage is complete and weights/criteria are scale-invariant.
- Blockers: none.

