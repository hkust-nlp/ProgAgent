## Task Topic

Optimize public charger availability by cross-referencing real-time session logs, upcoming reservations, maintenance schedules, and local grid demand forecasts to generate a dynamic pricing and availability matrix for the next 24 hours.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N = 8.

### Structural Dimensions

- **Conditional Constraints**: Dynamic pricing depends on multi-source threshold lookups — grid demand percentage maps to tariff-tier multipliers, station historical utilization rates select surcharge brackets, zone maintenance reduction percentages trigger capacity surcharges, and renewable energy percentages gate discount eligibility. All thresholds and brackets reside in workspace configuration files.
- **Deliverable Constraints**: Output CSVs require exact column names (`charger_id`, `hour_0`–`hour_23`), rows sorted by charger_id, prices formatted to exactly two decimal places or the literal `N/A`, and summary metrics in a precise `key: value` line format.
- **Information Scattering**: Charger attributes and schedules come from tool calls; pricing rules, tariff tiers, and maintenance impact rules live in workspace JSON/YAML files; historical utilization rates are spread across per-station CSV files whose names must be resolved through a separate zone-station mapping CSV.
- **Multi-Hop Reasoning**: Computing a single cell's price requires: charger → station_id (tool) → station usage file (workspace) → utilization rate at clock hour → threshold comparison (pricing policy YAML) → surcharge. Similarly: charger → zone_id (tool) → grid forecast (tool) → demand_pct → tariff tier lookup (JSON) → multiplier. Maintenance surcharge requires aggregating per-charger maintenance across an entire zone per hour, then dividing by the zone's active charger count.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (availability_structure, availability_correctness, pricing_structure, pricing_correctness, total_available_slots, peak_pricing_hour, estimated_max_revenue)
- Section 1 structural integrity: clean (only SCALE differs across data.py)
- Section 2 solvability: solved without escalating to env.py; solver used only v3/prompt.md + get_assistant_tools()
- Section 3 env quality: criteria match prompt deliverables; ground truth derived from current data; no hard-coded counts
- Section 4 prompt quality: no title/bold headers, no bulleted lists for deliverables, scale-invariant wording, no env.py internals exposed
- Issues found and fixed: none
- Final cleanup: removed any data.db/workspace/__pycache__ artifacts from v0..v3
