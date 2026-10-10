## Task Topic

Identifying systemic manufacturing defects requires cross-referencing assembly line sensor logs, component supplier batch IDs, final inspection images, and operator shift schedules to pinpoint root causes, outputting a prioritized corrective action list for supplier rework and machine recalibration.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Sensor logs are generated at 8× the rows_per_table base; inspection results at 2× the base. Fixed configuration files (calibration_specs.csv, defect_severity_rules.yaml, action_priority_config.json) do not scale.

**Structural dimensions used:**

- **Information Scattering**: Task-critical data is split across database tables (sensor readings, batch quantities, inspection results) and workspace files (calibration specs, photo analysis root cause indicators, supplier audit scores, drift ratios). Neither source alone suffices.
- **Multi-Hop Reasoning**: Determining affected product counts requires a chain of at least length 4: query inspection failures → look up batch IDs → map batches to suppliers via tool calls → cross-reference photo analysis files for root cause classification → apply severity rules from config.
- **Conditional Constraints**: Whether a supplier or line triggers a corrective action depends on threshold comparisons (defect rate > 5%, anomaly rate > 15%) with parameters defined in workspace config files, not the prompt.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (file_format=10, entity_identification=25, severity_scores=25, ranking_order=20, affected_products=10, response_summary=10)
- Source-access escalation: clean — solver succeeded using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py`/`data.py`.
- Issues found and fixes:
  - Stale `v0/__pycache__` present in source tree. Fix: removed; final clean-up also strips runtime artifacts from every `v_n/`.
  - No content/logic bugs found in `data.py`, `env.py`, or `prompt.md`. Byte-for-byte invariance across v0–v3 holds (only `SCALE` differs); SCALE ratios match harness convention (rows ×1/2/4/8, files +0/N/2N/3N with N=10).
