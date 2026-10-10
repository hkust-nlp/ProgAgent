## Task Topic

Identify high-risk loan applications by correlating applicant credit bureau data, submitted income verification documents, internal fraud alert flags, and historical default rates by region to generate a prioritized review queue for underwriters.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow N/N+N/N+2N/N+3N where N=8.

Structural dimensions used:

- **Information Scattering**: Credit scores, fraud alerts, debt details, regional default rates, and prior loan history are only available through tool calls; verified income amounts live exclusively in workspace JSON batch files, and property appraisals live in workspace CSV files. Solving the task requires cross-referencing both sources.
- **Conditional Constraints**: Three policy override rules (critical fraud escalation, multiple-alert score adjustment, combined DTI-fraud escalation) modify the base risk score or force priority-tier assignments based on multi-table conditions. Thresholds are defined in the YAML configuration; rule descriptions are in the policy document.
- **Multi-Hop Reasoning**: The dependency chain includes Tool (search pending apps) -> Tool (credit report for monthly debt) -> File (income batch for annual income) -> compute DTI -> File (config for DTI threshold) -> compute risk component -> File (policy overrides) -> File (config override params) -> final tier.

## Harness Report

- v3 reward: 1.0 (all eight criteria pass; total_score 100/100).
- Eval criteria (8): csv_format (10), app_count (15), risk_scores (20), tier_accuracy (15), sorting (10), policy_overrides (10), summary_json (10), response_completeness (10).
- Source-access: clean - solver written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`. No step-6 escalation; `env.py` was only inspected during Section 3 review.
- Structural integrity: cleared a stale `v0/__pycache__` directory found in initial `ls`. All four versions diff clean except for the SCALE block in `data.py` (rows 50/100/200/400, files 8/16/24/32 satisfying the 1/2/4/8 row and N/2N/3N file deltas).
- Section 2 fixes: none to env.py / prompt.md / data.py - first reward of 0.9 was a solver-side bug (sort key used full-precision float instead of the displayed 4-decimal `risk_score`). After sorting on the rounded value, reward reached 1.0 with no environment edits.
- Section 3/4 review: prompt-step alignment, scale-invariance, prose-only formatting, and absence of tool-name leakage all hold.
- Blockers: none.
