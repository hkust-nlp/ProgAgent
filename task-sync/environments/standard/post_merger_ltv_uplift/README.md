## Task Topic

Calculate the post-merger customer lifetime value (LTV) uplift. Integrate target company's historical purchase data, product-level profitability matrices, customer churn probabilities, and planned cross-sell conversion rates to model the combined entity's LTV, outputting a segmented customer list with projected 3-year value.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

Structural dimensions used:

- **Information Scattering**: Customer loyalty scores and cross-sell propensity live exclusively in workspace CSV profile files, while product synergy factors reside in workspace JSON analysis files. Purchase history, churn probabilities, and product cost/price data are only accessible through tool calls. Configuration parameters (discount rate, growth rate, segment multipliers, integration costs, conversion rates) are spread across YAML, JSON, CSV, and TXT config files. Solving the task requires combining all these sources.
- **Multi-Hop Reasoning**: The LTV calculation involves a dependency chain of length ≥ 4: retrieve customer list (tool) → fetch purchase aggregates per customer (tool) → look up product margins and synergy factors (tool + workspace files) → compute weighted cost ratio and synergy-adjusted profit → read cross-sell propensity (workspace) and conversion matrix (workspace) → read integration costs (workspace) → combine with churn data (tool) and loyalty score (workspace) → project and discount over 3 years.
- **Deliverable Constraints**: The output CSV must use exact column names in a fixed order, all values rounded to exactly two decimal places, rows sorted descending by total 3-year LTV. The final response must list segment totals in a specific format sorted by value, and identify the top 5 customers with precise values.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_exists 10, columns_correct 10, row_count 10, ltv_accuracy 30, sort_order 10, segment_summary 15, top_customers 15)
- Source-access: clean — solver passed using only `v3/prompt.md` + `Task_Env(...).get_assistant_tools()`; no step-6 escalation needed.
- Structural integrity: passed. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; only the SCALE block in `data.py` differs. SCALE follows rows ×1/2/4/8 (80/160/320/640) and files +0/N/2N/3N (8/16/24/32).
- Issues found and fixes: none. Prompt is scale-invariant prose, no leaked tool names, all deliverable columns enumerated. `step()` derives ground truth from current DB/workspace, uses sane numeric tolerances ($1 or 1%), and matches every prompt requirement.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from all versions and the `/tmp/` solver.
