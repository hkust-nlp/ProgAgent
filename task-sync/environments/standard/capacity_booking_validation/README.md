## Task Topic

Validate pipeline capacity bookings by cross-referencing shipper reservation requests, historical segment flow volatility models, scheduled maintenance calendars for valves/pumps, and real-time weather impact forecasts to confirm or adjust allocated capacities, outputting a finalized and balanced capacity allocation report.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Structural dimensions used:

- **Information Scattering**: Task-critical data is split across workspace files (reservation nominations in CSVs, priority flags in JSONs, equipment condition factors in YAMLs, regulatory capacity limits in TXTs) and tool calls (segment capacities, shipper profiles, maintenance events, flow volatility, weather forecasts). Neither source alone is sufficient to compute the allocation.
- **Multi-Hop Reasoning**: The allocation requires a dependency chain of length 4+: read reservation CSVs to identify segment IDs, call tools for segment details to obtain regions, call weather forecast tool with those regions, then apply severity-to-impact mapping from the allocation policy config to compute weather adjustments, which feed into the effective capacity calculation that determines each shipper's allocation.
- **Conditional Constraints**: Allocation order depends on priority flags, contract tiers, and reliability scores with a multi-level tiebreaker. Maintenance reductions are modulated by equipment age factors and capped by policy. Regulatory limits override physical capacity when lower.

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria**: 6 (`report_structure` 15, `row_count` 10, `effective_capacity` 20, `allocation_amounts` 25, `allocation_status` 15, `summary_statistics` 15)
- **Solver source-access**: clean black-box — solver written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- **Issues found**: none requiring fixes. Section 1 byte-for-byte invariants hold (env.py and prompt.md identical across v0–v3; data.py differs only in SCALE). Section 3 review noted two minor non-issues: (a) the prompt's "critical before normal" sub-tiebreaker is logically redundant since `priority_flag_rank` already orders `emergency<critical<normal`, but the redundant sort term in `step` is harmless; (b) the `summary_statistics` criterion checks summary numerics via substring `in action`, which is loose but accepted the natural-prose summary. No edits applied.
