## Task Topic

Validate declared customs values to prevent underpayment. Analyze supplier invoices, freight and insurance cost ledgers, current exchange rate tables, and product-specific market value benchmarks to flag entries with >10% value discrepancy, outputting a discrepancy report for audit.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Invoice details, product HS codes, shipment incoterms/ports come from tools; exchange rates, freight/insurance costs, packaging/handling supplements, port surcharges, and market benchmarks come from workspace files. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: Multiple dependency chains of length >= 3. For example: query invoice (tool) -> get product_id -> query product (tool) -> get hs_code -> search benchmark files (workspace) -> retrieve benchmark price. Similarly: query invoice (tool) -> query shipment (tool) -> get incoterm + port -> read policy + surcharge files (workspace) -> compute adjustment.
- **Conditional Constraints**: CIF calculation depends on the incoterm (FOB/CIF/CFR/EXW), with rules defined in workspace policy files. Risk classification tiers (Medium/High/Critical) depend on discrepancy thresholds from the policy.
- **Deliverable Constraints**: Output CSV requires exact column order, 2-decimal rounding, specific sort order (discrepancy_pct descending, invoice_id ascending as tie-breaker), and the final response must include precise summary statistics.

## Harness Report

- v3 reward: 1.0 (100/100) using a solver that uses only `prompt.md` and `Task_Env.get_assistant_tools()`.
- Eval criteria: 7 (`report_exists` 10, `correct_invoice_ids` 25, `correct_cif_values` 15, `correct_discrepancy_pct` 15, `correct_risk_levels` 15, `correct_sort_order` 10, `response_summary` 10; total 100).
- Source-access: step-6 escalation to read `v3/env.py` was needed.
- Issues and fixes:
  - Section 1-2 (structural integrity): clean — `env.py` and `prompt.md` byte-identical across versions; only `SCALE` differs in `data.py`.
  - Section 2 (response_summary tolerance bug): the `total_underpayment` check in `step()` used `< 1.0` USD tolerance against ground-truth computed from values rounded to 2dp before multiplying by quantity. An agent that follows the prompt naturally and computes underpayment from unrounded intermediates can land off by several USD across hundreds of flagged entries (e.g. ~6 USD on v3 with 182 entries), incorrectly losing the 5-pt amount sub-criterion. Fix: replaced the fixed `< 1.0` threshold with `max(1.0, 0.05 * len(ground_truth), 0.001 * abs(total_underpayment_gt))` so the tolerance scales with both entry count and magnitude. Edited `v0/env.py` and propagated byte-identical to `v1/v2/v3`. Re-verified with the unrounded-value solver: reward 1.0.
- Sections 3-4: criteria coverage matches every prompt requirement; ground truth is computed dynamically from current `data.db` / workspace, no hardcoded counts; prompt.md uses prose only, no bullets/headings/bold/code, no tool or source-data filenames, columns/precision/sort order specified, scale-invariant wording.
- Blockers: none.

