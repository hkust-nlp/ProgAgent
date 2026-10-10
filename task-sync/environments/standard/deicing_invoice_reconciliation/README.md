## Task Topic

Reconcile aircraft de-icing service invoices. Cross-reference de-icing truck fluid usage logs, scheduled departure times, actual pushback timestamps, and contracted per-unit fluid rates to validate charges against actual winter operations, outputting an approved payment file with flagged discrepancies.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Structural dimensions used:

- **Information Scattering**: Actual fluid quantities are in workspace CSV truck logs, while invoice charges, service records, and flight pushback times are only available through tool queries. Contract rates and validation thresholds live in separate workspace config files (JSON and YAML). No single source contains all the data needed to validate an invoice.
- **Conditional Constraints**: Validation depends on business rules involving multiple tolerance parameters (quantity deviation percentage, rate matching, pushback timing) defined in the workspace YAML policy file, cross-referenced against contracted rates from the JSON rate schedule and service/flight records from tools.
- **Deliverable Constraints**: Output files have strict column ordering, exact status labels (`approved`/`flagged`), pipe-delimited discrepancy flags using specific type labels, and amounts rounded to two decimal places.
- **Multi-Hop Reasoning**: Invoice → service record (tool) → flight info (tool) → pushback time comparison; Invoice → truck log (file) → quantity comparison → contracted rate (file) → approved amount computation.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (`payments_file_format`, `payments_row_count`, `approved_amounts_accuracy`, `status_accuracy`, `discrepancy_report`, `discrepancy_flags_accuracy`, `response_summary`)
- Source-access: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no step-6 escalation needed.
- Structural integrity: passed. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block. No stale `data.db`/`workspace/`/`__pycache__/`.
- Prompt quality: passed. No headings, bold section titles, bullet/numbered deliverable lists, tool names, or source filenames. Output filenames (`approved_payments.csv`, `discrepancy_report.csv`) and column orderings are explicit. Wording is scale-invariant ("all invoices", "every invoice").
- Issues found / fixes: none. No edits were required to `data.py`, `env.py`, or `prompt.md`.
- Blockers: none.
