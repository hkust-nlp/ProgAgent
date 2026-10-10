## Task Topic

Track competitor pricing changes by cross-referencing daily web-scraped price lists, historical pricing data, internal cost sheets, and product catalog mappings to identify market share threats, outputting an alert dashboard with recommended price adjustments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task exercises the following structural dimensions:

- **Conditional Constraints**: Alert classification depends on category-specific thresholds (from a JSON config file) and competitor reliability tiers (from a text policy file). Only Tier A and Tier B competitors are included; Tier C is excluded entirely.
- **Deliverable Constraints**: The output CSV must use exact column names in a fixed order, monetary values rounded to two decimal places, and rows sorted by alert priority ascending then price gap percentage ascending. The summary JSON has a prescribed key structure.
- **Information Scattering**: Scraped prices live in workspace CSV files, catalog mappings and internal costs are only reachable via tools, and classification rules / adjustment formulas are spread across YAML, JSON, Markdown, and plain-text config files.
- **Multi-Hop Reasoning**: Scraped CSV → `lookup_catalog_mapping` tool → product_id → `get_product_details` tool (category) → `get_internal_cost` tool (floor price, unit cost) → apply category thresholds from JSON config → compute adjustment per Markdown policy.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (dashboard_columns 10, alert_entries 20, price_gap_values 15, recommended_prices 15, sort_order 10, pricing_summary 15, action_summary 15)
- Solver source-access: clean black-box. Solver written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()` output; no escalation to `env.py` was needed.
- Issues found and fixed: stale `v1/__pycache__/` directory present at start — removed during Section 1 structural cleanup. Byte-for-byte invariants for `env.py`/`prompt.md` across v0..v3 verified; `data.py` differs only in `SCALE`. SCALE ratios match spec (rows 50/100/200/400 = 1×/2×/4×/8×; files 8/16/24/32 = base + 0/N/2N/3N).
- Blockers: none.
