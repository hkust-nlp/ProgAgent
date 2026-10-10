## Task Topic

Detect fraudulent virtual item trading by cross-referencing player account histories, peer-to-peer marketplace listings, item rarity databases, and sudden wealth influx alerts, producing a daily report of suspicious accounts for manual review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Session logs (IP addresses), account flags (prior violations), and item price snapshots live exclusively in workspace files, while player profiles, marketplace listings, item details, and wealth alerts are accessible only through tool calls. Fraud scoring rules, rarity tier configurations, and region risk multipliers reside in separate config files. All three sources must be combined to compute the final score.
- **Multi-Hop Reasoning**: Computing the price-anomaly factor requires a chain of length 4: retrieve the player's marketplace listings (tool) -> for each listing retrieve the item details (tool) -> look up the item's recent price snapshots in workspace CSV files -> compare the listing price against the anomaly multiplier times the averaged market reference price.
- **Conditional Constraints**: Suspicious-account classification depends on a configurable threshold, and the recommendation tier (block / restrict / investigate) is determined by multiplier thresholds applied to the fraud score. Account-age bonuses, trade-frequency triggers, and multi-IP checks each gate on their own threshold parameters read from a YAML config file.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 6 (`report_structure` 15, `account_identification` 25, `fraud_scores` 20, `recommendations` 15, `sorting` 10, `response_summary` 15).
- Section 1 structural integrity: passed. Top-level contains only `README.md` and `v0..v3/`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the SCALE block (rows 100/200/400/800, files 10/20/30/40).
- Section 2 solvability: passed on first attempt. Solver used only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; `env.py`/`data.py` were not opened (no step-6 escalation needed).
- Issues found and fixes: none. No edits to `v0/` were required.
- Cleanup: removed runtime `data.db`, `workspace/`, `__pycache__/` from every `v_n/`; removed the temporary solver at `/tmp/solve_fraudulent_trading_detection.py`.
- Blockers: none.
