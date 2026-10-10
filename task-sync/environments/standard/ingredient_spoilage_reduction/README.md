## Task Topic

Reduce ingredient spoilage by analyzing supplier delivery schedules, real-time fridge temperature logs, recipe-based ingredient usage rates, and daily waste logs to produce a prioritized use-it-first list for kitchen staff.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Difficulty scales only through data volume: more ingredient records, more delivery/waste/temperature log entries, and more workspace files to parse. The task logic (`env.py`) and instructions (`prompt.md`) are identical across all versions.

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across multiple sources. Ingredient shelf life and storage temperature limits come only from tool calls; current stock quantities and fridge assignments come only from workspace JSON snapshots; delivery condition flags come only from workspace text files; scoring coefficients come only from the YAML configuration. No single source is sufficient.

- **Multi-Hop Reasoning**: The dependency chain is at least four hops deep: stock snapshot (batch_code, fridge_id) → tool lookup (delivery date for batch) → tool lookup (ingredient shelf life and max temp) → tool query (fridge temperature logs) → config file (penalty coefficients) → compute effective remaining days and risk score.

- **Conditional Constraints**: The recommended action for each batch depends on configurable thresholds read from a YAML file. Condition flags in delivery notes trigger an additional penalty. Temperature excursions above the ingredient's max storage temp trigger a scaled penalty via a coefficient.

## Harness Report

- v3 reward: 1.0 (perfect score)
- Eval criteria count: 7 (csv_structure 10, batch_coverage 15, effective_remaining_days 20, spoilage_risk_score 20, recommended_actions 15, ranking_order 10, response_summary 10; total 100)
- Source-access: clean. Did not need to escalate to step 6 (env.py never opened beyond the public `get_assistant_tools()` interface).
- Structural integrity: clean. v0->v3 byte-identical for `env.py` and `prompt.md`; `data.py` differs only in the `SCALE` block (rows 50/100/200/400 = 1x/2x/4x/8x; files 8/16/24/32 = N/2N/3N/4N). Stale `__pycache__` directories were present in v0 and v1 from prior runs and were removed.
- Solver iteration: First attempt scored 0.73 because I included the on-hand quantity as a multiplier in the spoilage risk score. The YAML config and `prompt.md` (`(1 / max(effective_remaining_days, 0.1)) * (1 + historical_waste_rate * waste_rate_multiplier)`) do not include quantity. After dropping the quantity factor the solver reached 1.0; ranking_order and response_summary were cascading failures from the score mismatch, both green after the fix. The prompt phrase "multiply by the quantity one plus the waste rate times the waste rate multiplier" parses as "multiply by the quantity (1 + waste_rate * multiplier)" -- "quantity" used as a math noun, not on-hand stock. Wording is mildly awkward but not ambiguous enough to require rewording given the explicit YAML formula exposed in `spoilage_config.yaml`.
- Issues fixed: removed stale `__pycache__` from v0/v1.
- Blockers: none.
