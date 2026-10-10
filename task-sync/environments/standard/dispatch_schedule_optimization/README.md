## Task Topic

Analyze customer service request descriptions, technician skill certifications, parts inventory levels across warehouses, and seasonal demand forecasts to optimize weekly technician dispatch schedules, outputting a recommended assignment roster minimizing travel time and wait-for-part delays.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Scaling ratios: rows grow as 1×, 2×, 4×, 8× of the v0 base (50). Workspace files grow as base, base+N, base+2N, base+3N where N = 8 (the v0 base file count). Only the `SCALE` dict in `data.py` differs across versions; `env.py` and `prompt.md` are byte-identical.

### Structural Dimensions

- **Conditional Constraints**: Technician eligibility depends on priority level → minimum certification level (from dispatch policy YAML), certification expiry versus a reference date, and customer tier multipliers — spanning the service_requests table, technician_certifications table, and workspace configuration files.
- **Deliverable Constraints**: The output `assignment_roster.csv` requires exact column order, integer travel times, integer wait days, cost rounded to two decimal places, and specific summary metrics in the final response.
- **Information Scattering**: Service request core data (zone, skill, priority) lives in the database and is only accessible through tools, while customer tier, preferred scheduling day, travel times, dispatch rules, cost weights, seasonal demand factors, and warehouse zones are spread across CSV, JSON, and YAML workspace files.
- **Multi-Hop Reasoning**: For each assignment the agent must chain: service request (tool) → required parts (tool) → inventory check per warehouse (tool) → warehouse zone (YAML file) → travel time (CSV file) → cost formula (JSON file) → certification validation (tool + YAML policy) → capacity tracking → scheduling.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (roster_format=10, dispatch_priority_order=15, technician_eligibility=20, parts_sourcing=15, capacity_compliance=15, travel_accuracy=10, summary_metrics=15)
- Source-access: clean — v3/prompt.md only; tools discovered via `Task_Env.get_assistant_tools()`; no escalation to env.py/data.py needed.
- Section 1 (structure): pass — only `README.md` + v0..v3; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` byte-identical across versions; only `SCALE` differs in `data.py`.
- Section 2 (solvability): solver achieved reward 1.0 on the first successful run; minor solver-side adjustments to match documented tool return shapes (`{requests: [...]}`, `{technicians: [...]}`, `{certifications: [...]}`, `{parts: [...]}`, inventory key `quantity`) — no env or prompt changes required.
- Issues found and fixed: none.
- Blockers: none.
