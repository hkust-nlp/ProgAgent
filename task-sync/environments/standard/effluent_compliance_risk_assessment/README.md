## Task Topic

Identifying industrial facilities at risk of non-compliance requires cross-referencing real-time effluent sensor data, permitted discharge limits, historical inspection violation reports, and scheduled maintenance logs to generate a prioritized list for field inspector dispatch.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 10                  |
| v1      | 60            | 20                  |
| v2      | 120           | 30                  |
| v3      | 240           | 40                  |

Structural dimensions used:

- **Information Scattering**: Critical risk-scoring parameters (environmental sensitivity zones, lab-verified discharge values, corrective action statuses) live exclusively in workspace files across JSON, CSV, YAML, Markdown, and plain-text formats, while facility details, sensor readings, permit limits, violation history, and maintenance logs are only accessible through tool calls. Both sources must be combined to compute the composite risk score.
- **Conditional Constraints**: Exceedance computation depends on comparing effective pollutant concentrations (the higher of sensor and lab values) against permit limits, weighted by hazard-tier multipliers from a reference file. Violation scoring applies recency-based weights and an unresolved multiplier from a YAML configuration. Zone multipliers from site assessments modify the final score.
- **Multi-Hop Reasoning**: Computing a single facility's risk score requires: tool call for sensor readings → workspace lab files to determine effective value → tool call for permit limits → workspace pollutant tiers for hazard multiplier → tool call for violations → workspace config for recency weights → tool call for maintenance → workspace corrective action files → workspace site assessments for zone multiplier (chain length ≥ 5).
- **Deliverable Constraints**: Output CSV must have exact column names, two-decimal precision for risk scores, specific sort order with tie-breaking rule, and rank column starting from one.

## Harness Report

- v3 solver reward: 1.0 (100/100).
- Eval criteria count: 8 (csv_structure 10, facility_set 15, risk_scores 25, ranking 15, risk_categories 10, dispatch_urgency 10, primary_concern 10, response_summary 5).
- Source-access: clean run. Section 2 escalation to step 6 (opening env.py) was needed once to confirm that the violation `resolved` flag is the boolean DB column rather than a status string; this matched the prompt's "unresolved" wording, so no env/prompt change was required.
- Structural integrity: passed (only `data.py` differs across v0..v3, only in the SCALE block).
- Prompt quality: passed (no headings, no bullets, scale-invariant wording, explicit column spec, no tool/file leakage).
- Step quality: passed (partial-credit scoring is consistent across v0..v3, no hard-coded counts, ground truth derived live from data.db + workspace).
- Issues found and fixes: none required.
- Cleanup: removed runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) from every `v_n/` and the temporary solver under `/tmp/`.

