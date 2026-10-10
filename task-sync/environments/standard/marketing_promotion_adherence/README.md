## Task Topic

Monitor franchisee adherence to national marketing promotions. Cross-reference point-of-sale transaction logs, digital coupon redemptions, local advertising spend reports, and brand guideline documents to identify non-compliant discounting or underfunded campaigns, outputting a corrective action list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

The task uses the following structural dimensions:

- **Conditional Constraints**: Violation detection depends on business rules spanning multiple tables and configuration files — discount tolerance bands, coupon invalid rate thresholds, minimum ad spend requirements, and mandatory participation flags each involve cross-referencing 2–3 data sources with thresholds defined in workspace YAML configuration.
- **Information Scattering**: Task-critical fields are split across tools and workspace files. POS discount data and coupon statistics are only accessible via tool calls, while advertising spend breakdowns exist only in per-franchisee CSV files in the workspace, and compliance thresholds and severity rules live in YAML/JSON configuration files.
- **Multi-Hop Reasoning**: Solving the task requires dependency chains of length ≥ 3, such as: read compliance config (YAML) → query promotion details (tool) → query discount analysis per franchisee (tool) → compare against tolerance → classify severity using config thresholds → map to recommended action from config.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (csv_file_valid, csv_correct_columns, violation_count_accuracy, violation_identification, severity_classification, correct_sort_order, response_summary)
- Source-access: clean for the discovery phase; v3/env.py was opened once under Section 2 step 6.2 to diagnose a solver/step disagreement.
- Issue identified: solver initially produced 100 violations vs ground-truth 120. Root cause was solver-side, not env-side: the underfunded-campaign severity buckets in compliance_thresholds.yaml only cover funding_ratio <= 75%, but `step()` defaults out-of-range ratios (75%-100%) to `MEDIUM`. The solver returned None and dropped those rows. After fixing the solver to mirror the same MEDIUM fallback, all 7 criteria pass.
- Note on prompt ambiguity (not blocking): prompt.md does not explicitly state how to classify underfunded violations whose funding ratio falls between the lowest YAML threshold (75%) and 100%. The env's MEDIUM-default behavior is sensible and consistent with "lower ratio = more severe", but a downstream agent could conceivably mishandle the 75%-100% band. No edits made to prompt.md or env.py.
- Structural integrity: all four versions present; env.py and prompt.md byte-identical across v0-v3; only the SCALE block in data.py differs (rows 100/200/400/800, files 10/20/30/40).

