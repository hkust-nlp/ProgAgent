## Task Topic

Identify at-risk customer accounts for proactive credit management. Analyze historical payment terms, invoice aging reports, recent order patterns, and industry-specific economic indicators to flag accounts with high probability of >60 day delinquency, generating a prioritized contact list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Account eligibility depends on status filters from the credit policy; risk scoring applies five weighted components with thresholds, caps, and edge-case rules defined in workspace configuration files. Risk-level classification and recommended actions are determined by score-range mappings in a separate config file.
- **Information Scattering**: Scoring parameters, formulas, and industry economic indicators live in workspace files (YAML, JSON, CSV), while customer details, invoice aging, payment history, and order data are only accessible through tool calls. Both sources are required to compute the composite risk score.
- **Multi-Hop Reasoning**: Customer details → invoice aging → payment delay → industry indicators file → composite score computation → risk classification lookup → prioritized output. The dependency chain spans at least four hops across tools and files.

## Harness Report

- v3 reward: 1.00 (100/100)
- Eval criteria: 6 (csv_structure, account_identification, risk_score_accuracy, priority_ranking, risk_level_action, response_summary)
- Source-access: escalated to step 6 (read v3/env.py once) to confirm the env's hard-coded REFERENCE_DATE (2026-03-31) drove the order-trend window. The solver was the bug — it had used a placeholder reference date and produced wrong order-trend scores. Fixing the solver to anchor on the latest order date in the database produced reward=1.0. No edits were needed to env.py, prompt.md, or data.py.
- Structural integrity: all four versions present with only the SCALE block differing in data.py; env.py and prompt.md byte-identical across v0..v3.
- Cleanup: removed all runtime artifacts (data.db, workspace/, __pycache__) from every v_n/ and deleted the temporary solver.
- Blockers: none.
