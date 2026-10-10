## Task Topic

Monitor competitor price changes and stock availability for key product categories. Analyze daily scraped competitor prices, our current catalog pricing, supplier cost sheets, and historical conversion rate data to generate a price adjustment alert list with recommended actions (match, hold, or promote).

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 40            | 8                   |
| v1      | 80            | 16                  |
| v2      | 160           | 24                  |
| v3      | 320           | 32                  |

Structural dimensions used:

- **Information Scattering**: Competitor tier classifications and price flags (clearance, bundle) live exclusively in workspace files, while actual product prices, supplier costs, and conversion metrics are only available through tool queries. Solving the task requires cross-referencing both sources.
- **Conditional Constraints**: The recommended action depends on a multi-branch decision tree involving category-specific margin thresholds (workspace CSV), competitor tier filtering (workspace JSON), price flag exclusions (workspace scrape CSVs), and conversion trend analysis (tool-based, with parameters from workspace YAML).
- **Multi-Hop Reasoning**: The decision chain spans Tool (list categories) → Tool (list products) → Tool (get competitor prices) → Workspace (filter by tier and flag) → Tool (get supplier costs) → compute margin → Workspace (check category min margin) → Tool (get conversion history) → compute trend → final action.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (file_format=10, product_coverage=15, action_accuracy=25, competitor_prices=20, margin_calculations=15, response_summary=15)
- Solver source-access: clean black-box. Solver was written using only `v3/prompt.md` plus the public `Task_Env.get_assistant_tools()` catalog. No step-6 escalation needed; `env.py`, `data.py`, and `README.md` were not consulted during Section 2.
- Issues found: none. Structural integrity passed (only `SCALE` differs across versions). Prompt is prose-only, no headings/bullets, scale-invariant wording, exact column spec for `price_alerts.csv`. `step()` derives ground truth dynamically from `data.db` and workspace files (no hardcoded counts), enforces precise column set, applies tolerant numeric matching (<0.5pp for margins, <0.015 for prices) which is appropriate for the rounding the prompt specifies.
- Fixes applied: none.
