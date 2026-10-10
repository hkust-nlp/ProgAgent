## Task Topic

Identify mis-sorted packages before shipping by cross-referencing item dimension scans, weight sensor readings, destination postal codes, and packing station worker logs to output a daily re-sort list with location and cost-avoidance estimates.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The v0 base values are `rows_per_table = 100` and `num_workspace_files = 10` (N = 10). Subsequent versions scale as: v1 = 2× rows / +N files, v2 = 4× rows / +2N files, v3 = 8× rows / +3N files.

**Structural dimensions used:**

- **Information Scattering**: Zone-to-postal-code mappings and customer tier data live exclusively in workspace files, while package routing details and sensor readings are only accessible through tool calls. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: Determining whether a package is mis-sorted requires a chain of at least three lookups: destination postal code → zone (workspace JSON) → correct lane (workspace YAML) → comparison with assigned lane (tool). Cost avoidance then adds another hop through batch manifests (customer tier) and cost rate tables.
- **Deliverable Constraints**: The output CSV enforces exact column names, specific sort order (cost_avoidance descending, package_id ascending as tiebreaker), two-decimal-place precision on cost values, and boolean flags formatted as True/False.

## Harness Report

- v3 reward: 1.0 (115/115)
- Eval criteria count: 9 (`file_structure`, `package_identification`, `correct_lanes`, `discrepancy_flags`, `cost_avoidance_values`, `sort_order`, `total_count_response`, `total_cost_response`, `top_station_response`)
- Source-access: clean (no step-6 escalation; solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`)
- Structural integrity: passed (`env.py`/`prompt.md` byte-identical across v0..v3; only `SCALE` differs in `data.py`; SCALE follows ×1/2/4/8 rows and +0/N/2N/3N files with N=10)
- Issues found: none. No fixes required.
- Blockers: none.
