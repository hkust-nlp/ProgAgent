## Task Topic

Identify potential fraudulent ticket purchases. Cross-reference purchase transaction timestamps, device/IP geolocation data, customer account purchase histories, and ticket resale platform listings to flag high-risk orders, generating a daily review queue for the fraud prevention team.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Structural dimensions used:

- **Information Scattering**: Customer verified-country data is only available in workspace text files (not via tools), event pricing is only in workspace JSON files, and processor flags are only in workspace CSV files. Device geolocation and purchase history are only available via tools. Solving the task requires cross-referencing both workspace files and tool results.
- **Conditional Constraints**: Six distinct risk factors are evaluated per transaction, each with configurable weights from a YAML config file. Velocity violation thresholds depend on the customer's account tier as defined in a CSV policy file. Risk level classification and recommended actions follow threshold rules from the config.
- **Multi-Hop Reasoning**: Transaction → device session (tool) + customer verified country (workspace file) → geo_mismatch check. Transaction → customer profile (tool for tier) + purchase history (tool for counts) + velocity policy (workspace file) → velocity_violation check. Transaction → event pricing (workspace file) + transaction amount (tool) → price_anomaly check.
- **Deliverable Constraints**: Output CSV requires exact column names, semicolon-separated alphabetically-sorted risk factor names, specific sort order (risk_score descending, transaction_id ascending), and integer risk scores. Response must include specific summary statistics.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_structure 10, transaction_ids 20, risk_scores 20, risk_levels 15, risk_factors 15, sorting 10, response_summary 10)
- Source-access: clean (no escalation to env.py during Section 2; env.py read in Section 3 only)
- Section 1 structural integrity: passed (env.py and prompt.md byte-identical across v0..v3; data.py differs only in SCALE)
- Section 2 solvability: solver at /tmp/solve_fraud_detection_review.py achieved reward 1.0 on v3 using only prompt.md plus get_assistant_tools(); minor solver-side fix needed (history records use purchase_date / purchase_timestamp, not generic timestamp keys) — not an env issue
- Section 3 prompt-step alignment: every step criterion is grounded in prompt.md; ground truth is fully derived from data.db and workspace files (scale invariant); tolerant string matching only used on response summary (lowercased for HIGH/MEDIUM keyword presence) which is acceptable
- Section 4 prompt quality: no headings, no bold, no bullets, no code, no tool/file-name leakage, scale-invariant wording — passed
- Issues found / fixed: none
- Blockers: none
