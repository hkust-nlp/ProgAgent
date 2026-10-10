## Task Topic

Identify high-volume requesters and potential commercial data mining. Cross-reference requestor contact details, request metadata, document production logs, and fee waiver approvals to flag patterns of systematic extraction, generating a report for legal review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Critical fields are split across database tools and workspace files. Requestor primary emails live in the database, while alternate emails and cross-agency request counts are only available in workspace CSV profile batches. Document sensitivity ratings are only in workspace JSON production manifests. Scoring thresholds, commercial domain lists, department sensitivity levels, and category risk scores all reside in separate workspace configuration files of different formats.

- **Multi-Hop Reasoning**: The dependency chain is at least length 4: (1) read thresholds.yaml to learn the volume threshold → (2) paginate through all requests via tool calls to identify high-volume requestors → (3) for each high-volume requestor, retrieve fee waiver records and production summaries via tools, and cross-reference alternate emails from workspace profile CSVs against the commercial domain list from a workspace JSON file → (4) combine all six risk-score components using weights from the config to compute the final composite score and determine flag status.

- **Conditional Constraints**: Flagging depends on multi-table business rules: a requestor must first meet the volume threshold, then their composite risk score (computed from six components spanning database and workspace data) must meet or exceed the risk-score threshold. Additional flag reasons are conditional on sub-thresholds (fee waiver ratio > 50%, department spread >= cap, cross-agency count >= cap, commercial keyword presence in approved waiver reasons).

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 6 (`report_file_format`, `flagged_requestor_ids`, `risk_scores_accuracy`, `report_sort_order`, `commercial_waiver_language`, `action_summary`).
- Source-access: clean. Solver was authored using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` was required.
- Structural integrity: all four versions contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Issues found: none. No fixes were applied.
- Blockers: none.
