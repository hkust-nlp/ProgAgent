## Task Topic

Cross-reference applicant biometric submissions, visa category quotas, embassy appointment backlogs, and document verification flags to identify stalled high-priority applications, generating a prioritized intervention list for case officers.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

The task exercises the following structural dimensions:

- **Conditional Constraints**: Whether an application is "stalled" depends on five independent conditions checked against thresholds stored in workspace configuration files (SLA multipliers, biometric expiry windows, document flag counts, appointment wait limits, quota utilization percentages). High-priority eligibility adds a second layer of conditional logic combining database fields with case-dossier attributes.
- **Information Scattering**: Applicant records live in the database (accessible only via tools), while escalation levels and sponsor tiers are spread across multi-format case dossier batch files in the workspace. Stall thresholds, scoring rules, and SLA standards each reside in separate config files. No single source is sufficient to solve the task.
- **Multi-Hop Reasoning**: The dependency chain runs at least four hops deep: search for active applicants (tool) → retrieve biometrics/documents/appointments per applicant (tools) → cross-reference with quota data (tool) → look up escalation level and sponsor tier from workspace dossier files → apply scoring formula from workspace config → determine recommended action from priority-ordered stall reasons.
- **Deliverable Constraints**: The output CSV has a fixed column order, semicolon-and-space-separated stall reasons, scores rounded to two decimal places, and a three-level sort key (priority_score DESC, days_stalled DESC, applicant_id ASC).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (output_file_format 15, stalled_identification 25, priority_score_accuracy 20, stall_reasons_accuracy 15, sorting_order 10, recommended_actions 15)
- Source-access: clean for Section 2 (`prompt.md` + `get_assistant_tools()` only). Escalated to read `v3/env.py` per step-6 to diagnose a quota-utilization mismatch.

Issues found and fixes:

- Section 1 structural integrity: stale `v0/__pycache__` was present at the top level of `v0/`. Removed.
- Section 2 solvability blocker: `generate_visa_quotas` in `data.py` enumerated the full embassy×category×quarter grid (240 rows) and then padded with random duplicates up to `rows_per_table`, producing multiple `visa_quotas` rows for the same `(visa_category, embassy_id, quarter)` key. Both `get_visa_quota` and `step()`'s ground-truth use `fetchone()` against this key, so the utilization any solver computes (last-inserted) disagreed non-deterministically with what `step()` saw (first-inserted). At v3 this caused 70/254 priority-score and stall-reason mismatches. Fixed in `v0/data.py` by removing the duplicate-padding loop so `(visa_category, embassy_id, quarter)` is unique; re-propagated to v1/v2/v3 with only `SCALE` differing. The quota table is now sized by the natural grid (240 rows for 10 embassies × 6 categories × 4 quarters), independent of `rows_per_table` — the per-table scale ratio still holds for all other tables.

Section 3/4 checks (env-prompt alignment, prompt formatting, scale-invariant wording) passed without further edits.
