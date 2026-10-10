## Task Topic

Detect potential licensing revenue leakage by correlating global distributor shipment volumes, territory-specific license agreements, product SKU royalty rates, and audit exception reports, outputting a prioritized list of high-risk partners for compliance review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Information Scattering**: Territory royalty modifiers, risk scoring policy weights, and third-party verified shipment quantities live exclusively in workspace files (YAML, JSON, CSV), while SKU pricing, reported royalty amounts, license agreement discounts, and audit exceptions are only accessible through tool calls. No single source is sufficient to compute expected royalties or risk scores.
- **Multi-Hop Reasoning**: The dependency chain spans at least four hops: retrieve distributor list via tool, fetch each distributor's agreements and shipments via tools, look up each SKU's pricing via tool, read territory modifiers from workspace YAML, cross-reference verified quantities from workspace CSVs by invoice number, then combine all factors to compute expected royalty and leakage.
- **Conditional Constraints**: Leakage thresholds (absolute and percentage), fiscal year boundaries, agreement validity windows, and risk category cutoffs all gate which distributors appear in the final output; these parameters are spread across workspace configuration files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (`leakage_analysis_format`, `flagged_count`, `leakage_accuracy`, `risk_score_accuracy`, `sort_order`, `high_risk_summary`, `response_summary`)
- Source-access escalation: required step-6 escalation (env.py read once) to diagnose risk score mismatch.

Issues found and fixes:

1. Solver bug (not a task bug): the prompt says "reduce the expected royalty by the agreement's royalty discount percentage". The DB stores `royalty_discount_pct` as a percentage value (e.g., 5.67 means 5.67%); env divides by 100 before applying. Solver was corrected to do the same. Prompt wording is consistent.
2. `primary_risk_factor` label mismatch: the env's `_compute_ground_truth` and `verify` both used internal labels (`royalty_leakage`, `high_leakage_rate`, `audit_findings`, `volume_shortfall`, `quantity_discrepancy`) that are not derivable from `prompt.md`, which only names the five scoring dimensions as "leakage amount, leakage percentage, audit severity, volume gap, and quantity discrepancy". Fix: relabel the env components to match the prompt's natural names (`leakage_amount`, `leakage_percentage`, `audit_severity`, `volume_gap`, `quantity_discrepancy`). Propagated v0 -> v1/v2/v3.
3. Volume-gap quantity ambiguity: prompt says "the distributor's total shipped quantity"; env uses recorded shipment quantity (not the verified override). The prompt frames verified quantities only in the context of expected-royalty computation, so the recorded interpretation is internally consistent and was kept as-is.

No blockers.
