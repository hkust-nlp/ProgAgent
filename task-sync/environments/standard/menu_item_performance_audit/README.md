## Task Topic

Identify underperforming menu items for menu engineering. Cross-reference point-of-sales mix reports, ingredient cost data, kitchen prep time logs, and customer satisfaction scores to output a ranked list of candidates for removal or recipe revision.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 10                  |
| v1      | 120            | 20                  |
| v2      | 240            | 30                  |
| v3      | 480            | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Ingredient costs live in workspace CSV files while ingredient quantities per item are only accessible via tool calls. Sales data, prep times, and ratings are tool-only; thresholds and scoring formulas live in workspace config/methodology files.
- **Multi-Hop Reasoning**: Computing food cost percentage requires: (1) calling `get_item_ingredients` for each item → (2) reading workspace cost CSVs to look up unit costs → (3) calling `get_item_pricing` for the menu price → (4) computing the ratio. The full composite score depends on all five dimensions, each from a different data source.
- **Conditional Constraints**: Action classification (REMOVAL/REVISION/MONITOR/OK) depends on threshold failures with must-fail conditions, minimum failure counts, and a revenue-based exclusion rule (top 25% by revenue downgrades REVISION to MONITOR).
- **Deliverable Constraints**: Output CSV requires exact column names, sort order (ascending composite score with alphabetical tie-breaker), and 2-decimal precision on numeric fields.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 7 (output_file_exists, correct_columns, all_items_present, action_classification, composite_score_accuracy, correct_sort_order, response_summary)
- Source-access: clean — solver authored using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Section 1 structural integrity: passed; `env.py` and `prompt.md` byte-identical across v0..v3, only `SCALE` differs in `data.py`.
- Section 3-4 quality: criteria coverage and completeness verified; ground truth derived dynamically from `data.db` / workspace; no hard-coded counts; prompt formatting has no headings, bold, or bulleted deliverables.
- Issues found: none.
- Cleanup: removed runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) from each `v_n/`; removed temp solver.
