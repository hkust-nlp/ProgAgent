## Task Topic

Optimize perishable ingredient orders to reduce waste. Analyze daily sales data, current inventory levels from multiple stores, supplier delivery schedules, and weekly waste logs to generate a recommended purchase order for each location, minimizing overstock of short-shelf-life items.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Critical data is split between database (sales, inventory, supplier pricing) and workspace files (delivery schedules, ingredient specs with shelf life and waste thresholds, supplier reliability ratings, ordering policy parameters). Solving the task requires both tool calls and file reads.
- **Conditional Constraints**: Order quantities depend on multi-factor business rules — waste percentage must exceed per-ingredient thresholds before reduction applies, priority classification uses tiered days-of-supply thresholds from a policy file, and supplier selection uses cost-then-reliability tiebreaking across two data sources.
- **Deliverable Constraints**: Output files have strict column ordering, sort keys (store_id → priority rank → ingredient_id), specific column names, and quantities rounded up to supplier pack sizes.
- **Multi-Hop Reasoning**: Computing an order line requires: sales tool → avg daily demand → combined with delivery schedule from workspace → forecast demand → minus inventory from tool → plus safety stock from policy file → times reorder multiplier from ingredient specs → waste adjustment using waste tool data and spec thresholds → supplier selection from tool results tie-broken by workspace ratings → pack-size rounding from supplier catalog.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_structure, store_coverage, order_quantity_accuracy, supplier_validity, priority_accuracy, waste_report, action_summary)
- Source-access: clean — solver written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No escalation to `env.py`/`data.py` was required.
- Structural integrity: PASS. Top-level contains only `README.md` and `v0..v3/`. Each `v_n/` contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; only `SCALE` differs in `data.py`.
- Solvability: PASS at v3 scale (240 stores / 240 ingredients / 240 suppliers / 35 workspace files). Reference date determined empirically as the day after the latest sale date returned by `get_sales_summary` over a 14-day window.
- Issues found: none. No fixes needed to `v0/` or any propagation.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from every `v_n/`; removed `/tmp/solve_perishable_inventory_optimization.py`.
