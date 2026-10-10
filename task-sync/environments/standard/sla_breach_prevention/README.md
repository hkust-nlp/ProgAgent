## Task Topic

Detect aging high-impact tickets at risk of breaching SLAs. Monitor ticket priority, assignment history, escalation logs, and real-time technician availability to generate a daily intervention list requiring managerial escalation or resource reassignment.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Structural dimensions used:

- **Conditional Constraints**: Intervention eligibility depends on SLA policy thresholds (priority × customer tier), risk-score thresholds from escalation rules, and skill-level requirements that vary by ticket priority. All thresholds live in workspace configuration files.
- **Information Scattering**: Ticket metadata, assignment history, and escalation logs are only available through tool calls; business impact scores reside in JSON batch files; technician availability lives in CSV reports; SLA windows, risk formulas, and department managers are spread across YAML, JSON, CSV, and Markdown config files.
- **Multi-Hop Reasoning**: Ticket → customer_id → customer tier → SLA hours → hours remaining → time urgency → risk score → recommendation → department lookup → manager name (chain length ≥ 5).
- **Deliverable Constraints**: Output CSV has a fixed 12-column schema with specified decimal precision, sort order (risk score descending, hours remaining ascending as tiebreaker), and the final response must include exact-format summary lines.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (file_exists, correct_columns, ticket_identification, risk_scores, recommendations, sort_order, summary_accuracy)
- Source-access: clean (Section 2 solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`); escalated to read `v3/env.py` only after a confident solver hit 0.85 due to the recommendations criterion mismatch described below.
- Issue 1 - Recommendation label mismatch: `prompt.md` instructs the agent to "recommend escalation" / "recommend reassignment" (nouns), but `step()` and `verify()` in `env.py` compared against the verbs `"escalate"` / `"reassign"`. A correct solver scored 85/100 because the recommendations criterion failed for all 113 rows. Fix: replaced `"escalate"` -> `"escalation"` and `"reassign"` -> `"reassignment"` in `v0/env.py` (in `_compute_ground_truth`, `step` summary counters, and `verify`), then re-propagated byte-identically to v1/v2/v3. Re-running the solver yielded reward 1.0.
- Blockers: none.
