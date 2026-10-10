## Task Topic

Identify fuel theft or unauthorized vehicle usage by analyzing GPS movement against approved depot geofences, fuel card transaction locations, scheduled maintenance periods, and after-hours ignition events to produce an anomaly report with suspected incidents.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

Derived table sizes: vehicles = 1x, fuel_transactions = 3x, gps_events = 6x, driver_shifts = 4x of `rows_per_table`. Maintenance schedules, fleet daily reports, fuel receipts, and incident history files scale with `num_workspace_files`.

### Structural Dimensions

- **Information Scattering**: Anomaly detection requires combining data from both queryable database tools (GPS events, fuel transactions, driver shifts, vehicle info) and workspace files (depot geofences, anomaly thresholds, vehicle type specs, maintenance schedules, overtime approvals, fuel receipts, incident history). No single source is sufficient.
- **Conditional Constraints**: Each anomaly type has configurable thresholds (distance, percentage, speed, liters) stored in workspace configuration files, with severity levels determined by additional cutoffs and prior-incident history upgrades.
- **Multi-Hop Reasoning**: After-hours ignition requires chaining shift lookup (tool) with GPS event filtering (tool) with overtime approval cross-check (workspace file) with prior-incident severity upgrade (workspace file). Overcapacity fueling requires vehicle type lookup (tool) then tank capacity cross-reference (workspace CSV) then threshold check (workspace JSON).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (`report_format`, `off_geofence_fueling`, `overcapacity_fueling`, `maintenance_movement`, `after_hours_ignition`, `fuel_receipt_mismatch`, `severity_accuracy`)
- Source-access: clean — solved using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`. No step-6 escalation; `env.py` was not opened.
- Section 1 structural integrity: PASS — top-level contains only `README.md` and `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across v0..v3; only `data.py` differs (and only in the `SCALE` block).
- Section 2 solvability: PASS — solver achieved reward 1.0 on first run.
- Issues found: none. No fixes required.
- Blockers: none.
