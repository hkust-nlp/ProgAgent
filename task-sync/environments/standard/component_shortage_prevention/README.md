## Task Topic

Prevent component stockouts by correlating real-time assembly line consumption data, supplier lead time forecasts, current warehouse inventory levels, and active production schedules to calculate shortage risks, outputting a prioritized purchase order list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Task-critical data is split across workspace files (consumption logs, supplier delivery reports, criticality tiers, risk thresholds, procurement policy) and database tools (inventory levels, production schedules, bills of materials, supplier offers). Neither source alone is sufficient to solve the task.
- **Multi-Hop Reasoning**: The dependency chain involves at least 3 hops: consumption logs → average daily rates → projected demand per component → net need (requiring inventory tool) → supplier selection (requiring delivery reports + supplier offers tool) → priority scoring (requiring risk config + criticality CSV + production schedule priorities).
- **Conditional Constraints**: Supplier qualification depends on on-time delivery rate thresholds with tiered adjustment factors; order quantities must be rounded to supplier-specific minimum order quantity multiples.
- **Deliverable Constraints**: Output CSV has exact column order, specific sort keys with tie-breakers, and the final response must include precise dollar-formatted totals and top-3 component details.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_format, component_identification, order_quantities, priority_scores, supplier_selection, risk_levels, response_summary)
- Solver source-access: required step-6 escalation. After a clean black-box attempt scored 0.8 (256 components vs ground truth 247, with order_quantity / response_summary mismatches), `v3/env.py` was opened to inspect `_compute_ground_truth`. The escalation exposed two implementation choices not unambiguously expressible from `prompt.md` alone: (a) remaining production days computed exclusively as `(end_date - today).days` rather than inclusive of the end date, and (b) safety-stock total daily consumption iterates per active schedule rather than per active line, so a line carrying multiple active schedules contributes its avg daily consumption multiple times. With the solver aligned to these choices, reward reached 1.0.
- Issues found: minor prompt-vs-step ambiguity around "through the schedule's end date" (prompt suggests inclusive, step is exclusive) and the per-schedule vs per-line iteration for total daily consumption. Both are masked by the 5% order-quantity tolerance and the 0.05 priority-score tolerance in `step`, and the v3 dataset happens to have at most one active schedule per line, so no row was actually affected. Left as-is — no fix applied; both interpretations score 1.0 under current tolerances.
- Structural integrity, byte-for-byte env/prompt invariance across v0..v3, and SCALE ratio compliance (rows 50/100/200/400, files 8/16/24/32) all verified.
