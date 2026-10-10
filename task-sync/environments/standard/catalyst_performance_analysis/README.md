## Task Topic

Identify underperforming catalytic cracking units by correlating catalyst activity logs, feedstock quality reports, unit throughput data, and energy consumption records to produce a maintenance priority list for catalyst regeneration or replacement.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Feedstock quality data resides exclusively in workspace CSV files, while catalyst activity, throughput, and energy data are only accessible via tool calls. The scoring configuration, catalyst reference specs, and maintenance decision rules are split across three separate workspace files (YAML, JSON, TXT). Solving the task requires reading all of these sources and cross-referencing them per unit.

- **Multi-Hop Reasoning**: The priority score computation involves a dependency chain of length ≥ 3: retrieve catalyst batch info (tool) → use catalyst type to look up baseline conversion from reference JSON (file) → compare against throughput records (tool) → compute conversion loss → normalize using config thresholds (file) → weight and sum into final score. Similarly, energy efficiency requires matching energy records with throughput records by closest date before computing per-barrel ratios.

- **Conditional Constraints**: The recommended maintenance action depends on both the priority tier (derived from the composite score) and the catalyst age factor (days since load / expected lifetime). A Critical-tier unit with age factor above 1.5 receives "immediate_replacement" while one at or below 1.5 receives "emergency_regeneration", each with different downtime estimates.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 7 (csv_format=15, all_units_present=15, priority_scores=20, ranking_order=15, recommended_actions=15, downtime_values=10, response_summary=10).
- Solver source-access: required step-6 escalation. The first solver achieved 0.93; `step()` uses a hard-coded reference date `2025-12-31` for `catalyst_age_days`, but the prompt did not specify any reference date, so age computation was non-deterministic from the agent's perspective.
- Issue and fix: prompt.md was ambiguous about the "today" anchor for catalyst age. Fixed in `v0/prompt.md` by clarifying that the reference date is treated as December 31, 2025; propagated to v1/v2/v3. After the fix, the solver reaches reward 1.0 cleanly. byte-for-byte invariant on `env.py` and `prompt.md` re-verified.
