## Task Topic

Investigate suspected insurance claims fraud by cross-referencing claimant policy details, medical provider billing codes, historical claim patterns, and independent adjuster field reports to identify inconsistencies, outputting a prioritized case list with evidence summaries.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 10                  |
| v1      | 120           | 20                  |
| v2      | 240           | 30                  |
| v3      | 480           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow N/N+N/N+2N/N+3N where N=10.

The claims table contains 2x rows_per_table entries (allowing claimant concentration for rapid-claims pattern detection). All other tables (claimants, providers, policies, billing_codes) contain exactly rows_per_table entries.

Structural dimensions used:

- **Information Scattering**: Fraud scoring requires data from multiple complementary sources. Policy details, claim histories, and billing codes are accessible only through tool calls, while scoring weights/thresholds live in a YAML config file, regional cost adjustments in a CSV file, provider billing deviations in JSON audit files, and qualitative red flags in markdown adjuster field reports.

- **Multi-Hop Reasoning**: Each fraud factor involves a dependency chain of length 3+. For example, `amount_anomaly` requires: get claim details (tool) -> get provider info for region (tool) -> read regional adjustment CSV (file) -> look up billing code expected range (tool) -> compute adjusted threshold and compare. The `provider_risk` factor requires: get provider_id from claim (tool) -> scan all provider audit JSON files for the provider's deviation percentage (files) -> apply risk tier thresholds from YAML config (file).

- **Conditional Constraints**: Each of the six fraud factors has distinct trigger conditions involving numeric thresholds, date windows, keyword matching, and ratio comparisons, all parameterized through workspace configuration files rather than hard-coded.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (csv_structure, csv_completeness, fraud_scores, ranking, evidence_summaries, summary_statistics)
- Source-access: clean (only `v3/prompt.md` consulted during Section 2; `env.py` opened only for Section 3 quality review)
- Issues found: stale `__pycache__/` directories present in `v0/`, `v1/`, `v2/`, `v3/` at start. Fix: removed all `__pycache__/` and runtime artifacts (`data.db`, `workspace/`) from each version directory; no source edits needed.
- Structural integrity, prompt-step alignment, and scale-invariant wording all pass.
