## Task Topic

Identify perishable goods at risk of spoilage by cross-referencing real-time shelf-life data, daily sales velocity, upcoming promotional calendars, and warehouse stock levels to generate a priority markdown list for items within 48 hours of expiry.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Scaling ratios: rows grow at 2x/4x/8x; workspace files grow at base+N/base+2N/base+3N where N=10 (base).

**Structural dimensions used:**

- **Information Scattering**: Supplier reliability scores and unit weights live exclusively in workspace supplement files (spread across CSV, JSON, YAML, and TXT formats), while product details, inventory, sales, and promotions are only accessible through tool calls. Both sources are required to compute the priority score.
- **Conditional Constraints**: Priority scoring depends on configurable weights and markdown tiers read from `config.yaml`, category-specific risk multipliers from `category_risk_factors.json`, and an overstock threshold — all workspace-resident parameters that gate eligibility and scoring.
- **Multi-Hop Reasoning**: Computing a single item's priority requires: list warehouses → get inventory batches → filter by expiry → get product details → get sales history → get promotions → read supplement files → apply formula from config → determine markdown tier.
- **Deliverable Constraints**: Exact column order, decimal precision, sort keys with tie-breaker, and summary format are all strictly specified.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (file_exists 10, correct_items 25, priority_scores 20, markdown_percentages 15, sort_order 10, column_completeness 10, summary_accuracy 10)
- Source-access: clean — solved using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` discovery; `env.py` was opened only afterwards for the Section 3 prompt/step alignment review.
- Structural integrity: passed. v0/v1/v2/v3 each contain only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (80/10 → 160/20 → 320/30 → 640/40, matching the rows ×1/2/4/8 and files +0/N/2N/3N invariant for N=10).
- Solvability: at v3 scale, 256 at-risk batches were identified and the solver achieved reward 1.0 on the first end-to-end run; total estimated markdown loss was $319,767.66.
- Prompt/step alignment: every scored criterion maps to a prompt requirement; ground truth in `step` is recomputed from `data.db` and the workspace, so the grader is scale-invariant.
- prompt.md quality: no leading title, no bold section headers, no list bullets for deliverables; column names, precision, sort order, and summary format are all spelled out in prose; no tool names or source-DB filenames are leaked.
- Issues found and fixes: none. No edits to `v0/` were required, so no re-propagation was needed.
- Cleanup: removed runtime `data.db`, `workspace/`, and `__pycache__/` from every version directory.
