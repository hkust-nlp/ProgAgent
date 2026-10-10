## Task Topic

Optimize replenishment labor by analyzing real-time pick-face stock levels, historical hourly order-picking rates, inbound receiving dock schedules, and forklift telemetry to generate a prioritized task list for stockers with expected time savings.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

The task uses the following structural dimensions:

- **Information Scattering**: Task-critical fields are split across database tables (stock levels, picking rates, dock schedules, forklift telemetry) and workspace files (policy thresholds, time standards, zone configuration, forklift efficiency ratings, demand adjustment multipliers). No single source contains enough information to complete the task.
- **Multi-Hop Reasoning**: The solution requires a dependency chain of length 4+: query pick faces → look up SKU details for case pack quantity → retrieve picking rate and apply demand multiplier from CSV files → cross-reference dock schedules for incoming shipments → assign forklifts using telemetry + roster efficiency → compute priority scores, time estimates, and savings.
- **Conditional Constraints**: Replenishment eligibility depends on storage-type-specific stock thresholds (ambient/chilled/frozen), forklift assignment requires meeting minimum battery thresholds, and dock proximity adjusts priority based on ETA windows — all configured via workspace policy files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_format, sku_identification, priority_ranking, depletion_accuracy, cases_accuracy, forklift_assignment, summary_response)
- Source-access: clean — solver used only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to env.py needed.
- Structural integrity: passed. v0..v3 byte-identical for `env.py` and `prompt.md`; only `data.py` differs in the `SCALE` block.
- Issues found: none. Prompt formatting is prose-only (no headings/bold/lists), computation in natural language, no tool names leaked, scale-invariant wording. Step criteria all map to explicit prompt requirements; ground truth is recomputed from current DB/workspace, so scale-invariant.
- Fixes: none.
