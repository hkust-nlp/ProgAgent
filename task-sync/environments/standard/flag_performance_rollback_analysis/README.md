## Task Topic

Analyze feature flag performance and user impact. Correlate flag configuration changes, application error logs, user session analytics, and support ticket volume to identify flags causing increased errors or negative feedback, outputting a rollback recommendation report with supporting metrics.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Task-critical fields are split across sources. Error counts, satisfaction scores, and ticket volumes come from tool calls, while response time data is only available in workspace session log CSVs, rollback thresholds live in a YAML policy file, service criticality in a JSON config, flag complexity in JSON metadata files, and incident mentions in text files. No single source is sufficient.
- **Multi-Hop Reasoning**: The agent must chain together multiple sources in sequence — read the rollback policy (thresholds + window size) → list flags via tool → get each flag's change date → call metric comparison tool with that date and window → read session CSVs and filter by flag + date window → read flag detail JSONs for complexity → read incident notes for mentions → apply thresholds → produce report.
- **Conditional Constraints**: Recommendation classification depends on multi-threshold business rules (rollback vs. monitor vs. keep) read from a workspace config file, with primary-reason determination following a fixed evaluation order.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 9 (report_format 10, correct_flags 10, error_metrics 15, satisfaction_metrics 15, ticket_metrics 10, response_time_metrics 10, recommendations 15, sort_order 5, action_summary 10).
- Source-access: clean — solver written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`. No step-6 escalation needed; reaching reward 1.0 only required passing the full `last_change_date` (with HH:MM:SS) into `get_flag_metric_comparison` so before/after windows align with the env's ground-truth windows. No edits made to env.py, data.py, or prompt.md.
- Section 1 structural integrity, Section 3 prompt-step alignment, and Section 4 prompt formatting all pass with no fixes required.
- Blockers: none.
