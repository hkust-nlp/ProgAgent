## Task Topic

Reconcile controlled substance chain-of-custody. Cross-reference shipment manifests, DEA Form 222 electronic records, facility license verification databases, and GPS/geofencing logs to identify custody gaps or regulatory discrepancies, outputting an audit roster with flagged shipments for investigation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

The task uses the following structural dimensions:

- **Information Scattering**: Shipment manifest data lives in workspace CSV files, while DEA Form 222 records, facility license details, GPS tracking logs, and carrier compliance information are only accessible through tool calls. Regulatory rules, geofence zone definitions, and schedule handling requirements are spread across YAML and JSON configuration files. The agent must combine all these sources to detect each discrepancy type.

- **Conditional Constraints**: Eight distinct discrepancy types each have their own detection logic involving 2–3 cross-referenced fields (e.g., facility license expiry vs. shipment departure date, authorized schedules vs. shipment schedule, carrier hazmat endorsement vs. schedule-specific requirements). Severity levels and recommended actions are governed by a regulatory configuration file, not hard-coded in the prompt.

- **Multi-Hop Reasoning**: Detecting carrier noncompliance requires reading the shipment manifest (carrier ID + schedule), then retrieving the carrier's certification record via tool, then consulting the regulatory config to determine whether hazmat endorsement is required for that schedule, then combining all conditions. Similarly, custody gap detection chains manifest → route plan (required checkpoints) → GPS log tool (observed zones) → comparison.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (`file_and_columns` 10, `flagged_records_f1` 30, `severity_accuracy` 20, `action_accuracy` 15, `sort_order` 10, `response_summary` 15)
- Solver source-access: clean black-box — used only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; did not need to escalate (step 6) to inspect `env.py` or `data.py`.
- Issues found: none. Section 1 structural integrity passed (env.py/prompt.md byte-identical, data.py differs only in SCALE), Section 2 solved on first attempt at v3 (400 shipments, 480 roster rows, F1=1.00), Sections 3–4 prompt/step alignment validated implicitly by clean reward.
- Fixes applied: none.
