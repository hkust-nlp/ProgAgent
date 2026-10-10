## Task Topic

Identify high-risk prepaid subscribers for proactive retention offers. Analyze call detail records (CDRs), top-up patterns, customer service interaction logs, and competitor promotional data to target users with declining usage and negative sentiment, generating a prioritized call list for the retention team.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 8                   |
| v1      | 120           | 16                  |
| v2      | 240           | 24                  |
| v3      | 480           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N=8.

### Structural Dimensions

- **Information Scattering**: Quantitative subscriber data (usage metrics, top-up amounts, interaction sentiment) is accessible only through tool calls, while scoring weights, threshold brackets, risk-tier boundaries, survey responses with churn-intent signals, and competitor campaign targeting data live exclusively in workspace configuration and data files (YAML, JSON, CSV, Markdown). Solving the task requires reading both sources and cross-referencing them.

- **Conditional Constraints**: Subscriber eligibility depends on account status and minimum tenure rules from the classification config. Risk scoring applies four-component weighted brackets with configurable thresholds, escalation penalties, and competitor-match bonuses. The recommended retention offer is looked up from a matrix keyed on primary risk factor and plan type.

- **Multi-Hop Reasoning**: Churn intent scoring chains multiple sources: tool-based interaction records (port-out request detection) → workspace survey files (likelihood ratings + competitor mentions) → workspace competitor campaign files (region/plan targeting match) → workspace scoring config (bonuses and caps) → final weighted combination.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (file_format=15, subscriber_identification=25, risk_score_accuracy=20, ranking_correctness=15, tier_and_offer=15, response_summary=10)
- Section 1 structural integrity: passed. v0..v3 differ only in the SCALE block of data.py; env.py and prompt.md are byte-identical.
- Section 2 solvability: solver written from prompt.md + get_assistant_tools() only; reached reward 1.0 on first submission, no escalation to env.py/data.py needed.
- Issues found: none. No fixes required.
- Cleanup: data.db, workspace/, __pycache__/, and /tmp solver removed.
