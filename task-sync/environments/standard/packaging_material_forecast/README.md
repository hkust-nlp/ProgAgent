## Task Topic

Predict next quarter's packaging material needs. Analyze subscriber growth projections, box assembly schedules, supplier lead times, and current inventory levels to produce a purchase requisition with material types and order dates.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 20            | 8                   |
| v1      | 40            | 16                  |
| v2      | 80            | 24                  |
| v3      | 160           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Growth forecast rates live exclusively in workspace CSV files; subscriber counts come only from tool calls; supplier discount percentages are only in workspace JSON contract files; inventory adjustments (damaged/expired stock) are only in workspace YAML files; base inventory quantities come only from tool calls. No single source contains everything needed to compute the requisition.
- **Multi-Hop Reasoning**: The dependency chain is at least 4 hops deep — growth forecasts × subscriber counts → weighted growth rate → adjusted assembly quantities × BOM → gross material need → minus effective inventory (DB + workspace adjustments) → net need → supplier selection (tool + workspace discounts) → order date calculation (lead time + category-based buffer).
- **Conditional Constraints**: Supplier eligibility depends on reliability score threshold and active status; material priority classification determines which buffer-day parameter applies; only confirmed (not tentative) assembly schedule entries are included; order quantities must round up to the supplier's minimum order quantity.
- **Deliverable Constraints**: Output CSV must use exact column names and order, dates in YYYY-MM-DD, costs rounded to two decimal places, rows sorted by order date then material ID, and the final response must contain specific formatted summary strings.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (file_exists 10, correct_columns 10, correct_materials 20, correct_quantities 20, correct_suppliers 15, correct_dates 15, summary_accuracy 10)
- Source-access: clean (no step-6 escalation; solver succeeded using only v3/prompt.md and Task_Env.get_assistant_tools())
- Structural integrity: env.py and prompt.md byte-identical across v0-v3; data.py differs only in SCALE block; SCALE follows expected 1x/2x/4x/8x rows and N/2N/3N file growth
- Issues found: none. Prompt is prose-only, scale-invariant, no leaked tool/source filenames; step uses runtime ground truth derived from data.db and workspace; precision-aware string matching for summary, exact column enforcement, F1-style materials scoring.
- Blockers: none.
