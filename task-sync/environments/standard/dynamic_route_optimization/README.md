## Task Topic

Optimize weekly collection routes by cross-referencing historical bin weight sensor data, resident subscription tiers, real-time traffic patterns, and truck fuel consumption logs to generate a dynamic route schedule minimizing total drive time and fuel cost.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 10                  |
| v1      | 50            | 20                  |
| v2      | 100           | 30                  |
| v3      | 200           | 40                  |

The scaling follows fixed ratios: rows grow as 1×, 2×, 4×, 8× of the v0 base, and workspace files grow as base, base+N, base+2N, base+3N where N = base (10).

### Structural Dimensions

- **Information Scattering**: Task-critical data is split across database tables (bin weights, resident tiers, truck specs, fuel logs) accessible only via tools and workspace configuration files (traffic data, maintenance schedule, subscription tier definitions, fuel prices, district schedule, collection policy). Solving the task requires cross-referencing both sources.

- **Multi-Hop Reasoning**: The solution requires a dependency chain of length ≥ 3: retrieve fuel logs per truck → compute actual fuel efficiency → use efficiency to rank trucks for assignment → calculate fuel costs using efficiency and fuel prices from config files. Similarly: query resident tiers per area → cross-reference tier config to determine high-demand forcing → look up district schedule for secondary collection day.

- **Conditional Constraints**: Area demand classification depends on a weight threshold from the policy file AND subscription tier status from the tier config; truck availability depends on both maintenance schedule and fuel-log existence; truck assignment uses a greedy capacity-and-efficiency algorithm with specific tie-breaking rules.

- **Deliverable Constraints**: Output files have exact column orders, decimal precision requirements (1 decimal for weights, 2 for costs), and the final response must state specific monetary and time totals to exact decimal precision.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (schedule_format=10, area_coverage=20, day_assignments=15, truck_constraints=15, route_ordering=10, cost_report=15, response_summary=15)
- Structural integrity: passed. v0..v3 share byte-identical env.py and prompt.md; only data.py SCALE block differs.
- Solvability: solver written using only v3/prompt.md plus get_assistant_tools() output reached reward 1.0. No env.py/data.py source access was required beyond step-6 inspection of step()/_solve() to diagnose a floating-point sensitivity in the greedy capacity check (subtracting w from remaining_cap in-place vs. tracking accumulated load gives FP-divergent residuals on capacity-tight days). The env's algorithm is consistent with the policy; no env.py or prompt.md change made — solver was aligned to the natural "remaining_cap -= w" formulation.
- Prompt quality: passes formatting and content rules (no title, no bold headers, no bulleted deliverables, scale-invariant wording, no source filenames or tool names exposed).
- Cleanup: data.db, workspace/, __pycache__/ removed from all v_n/.
