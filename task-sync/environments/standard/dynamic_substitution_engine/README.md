## Task Topic

When a customer's ordered item is out-of-stock, the system must cross-reference product category, brand affinity, nutritional profiles, price sensitivity, and real-time inventory to propose the best substitute, outputting a ranked substitution list for pickers.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Product specifications (dietary tags, allergens, quality scores) live in workspace files across four formats (JSON, CSV, YAML, TXT), while core product attributes, inventory, and orders are only accessible via tools. Customer brand preferences and order-level substitution notes are also scattered across workspace files. Solving the task requires combining both sources.
- **Multi-Hop Reasoning**: The dependency chain is at least length 4: list OOS orders → get order details → look up customer profile and preferences → retrieve original product details and nutritional info → search category for candidates → check each candidate's inventory, price, allergens (from files), and nutritional profile → compute composite score using policy weights (from files) and brand affinity matrix (from files).
- **Conditional Constraints**: Substitution eligibility depends on price-sensitivity tier thresholds, allergen avoidance rules, inventory sufficiency, and per-order substitution permission flags — all sourced from different locations.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (csv_file_format, oos_pair_coverage, rank1_accuracy, score_accuracy, max_subs_per_item, response_summary, exclusion_compliance)
- Source-access: clean. Solver authored using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No env.py escalation was required to reach reward 1.0; env.py was only consulted after the prompt fix below was identified, to confirm the candidate-pool logic.

Issues found and fixes:

- Prompt-step misalignment: `step()` restricts the candidate pool to products in the same top-level category as the original and to those whose `current_stock` is at least the ordered quantity, but `v0/prompt.md` did not state these eligibility rules. A solver that scored cross-category candidates and ignored stock thresholds produced extra rows (861 vs the GT's 840) and failed `response_summary`'s count check, dropping reward to 0.9479. Fixed by adding a sentence to `v0/prompt.md` (propagated byte-identically to v1/v2/v3) that explicitly limits the candidate pool to same-category products with sufficient on-hand inventory to cover the order line. After the fix, the solver reproduced the GT exactly and reward rose to 1.0.

Blockers: none.
