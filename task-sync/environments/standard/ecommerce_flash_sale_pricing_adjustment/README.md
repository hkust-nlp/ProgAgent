## Task Topic

Optimize e-commerce flash sale pricing by correlating real-time website clickstreams, competitor price tracking data, warehouse inventory turnover rates, and customer segment lifetime value scores to adjust discount tiers, producing a validated pricing schedule for the campaign.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The scalable workspace files are daily clickstream session logs (CSV). Fixed configuration files (campaign config YAML, discount tier definitions JSON, competitor reputation CSV, warehouse priority YAML, pricing policy MD) are produced independently and do not scale.

The task employs the following structural dimensions:

- **Information Scattering**: Critical parameters are distributed across workspace configuration files (YAML, JSON, CSV, MD) and database-backed tools. Clickstream engagement data lives in workspace CSV files while product details, competitor prices, inventory status, and customer segment LTV scores are accessible only through tools. The discount tier thresholds and scoring weights come from JSON/YAML config files, and the margin-enforcement formula is documented solely in a Markdown policy file.

- **Multi-Hop Reasoning**: Computing the final sale price for each product requires a dependency chain of length ≥ 4: daily clickstream CSVs → segment IDs from events → tool lookup for segment LTV scores → raw segment value → min-max normalization across eligible products → weighted composite score → tier mapping from JSON config → margin check using policy formula → capped discount and final price.

- **Conditional Constraints**: Product eligibility depends on category membership (from campaign config) and margin viability (cost-price-to-base-price ratio vs. the minimum margin threshold). Discount assignment involves a two-stage gating process: first mapping the composite score to a tier, then verifying the tier's discount against the margin floor and capping or excluding as needed.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (output_file_format, eligible_products, composite_scores, discount_tiers, margin_enforcement, sort_order, response_summary).
- Source-access: clean. Solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; `env.py` / `data.py` were not opened.
- Structural integrity: stale `v0/__pycache__` was present; removed during cleanup. `env.py` and `prompt.md` are byte-identical across v0-v3; `data.py` differs only in the `SCALE` block.
- Solver-side learnings (no env changes required): paginated tools return data under `products` / `segments` keys with `has_more`, and `get_competitor_prices` / `get_inventory_status` wrap their lists under `competitors` / `warehouses`; products with score < 15 (NoDiscount tier, 0% discount) must remain in the schedule because the prompt only excludes products whose margin floor blocks any positive discount.
- Blockers: none.
