## Task Topic

Identify potential benefit overpayments by cross-referencing recipient employment status updates from payroll data hubs, declared income from periodic self-reports, and bank transaction alerts for large deposits, outputting a prioritized investigation list with calculated discrepancy amounts.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Self-reported income declarations live exclusively in workspace batch CSV files, while employment updates and bank transaction alerts are only accessible through tool calls. Benefit payment history and recipient details are also tool-only. Solving the task requires merging data from both sources for every active recipient.

- **Multi-Hop Reasoning**: The analysis follows a dependency chain of length ≥ 3: list active recipients (tool) → read self-report batches (files) → retrieve employment updates per recipient (tool) → retrieve bank alerts per recipient (tool) → retrieve benefit payments (tool) → cross-reference against eligibility rules (file) → compute flags, discrepancy amounts, and priority scores using formulas from the policy document (file) → produce sorted investigation report.

- **Conditional Constraints**: Three distinct flag types (EMPLOYMENT_MISMATCH, INCOME_OVER_LIMIT, UNDECLARED_DEPOSITS) each have multi-condition eligibility rules spanning tool data, workspace self-reports, and configuration thresholds. Priority scoring and severity assignment add additional rule layers from the YAML configuration.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 6 (file_structure 10, recipient_identification 25, flag_accuracy 20, discrepancy_amounts 20, priority_severity 15, sort_and_summary 10).
- Source-access: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no step-6 escalation needed.
- Section 1 (structure): pass — only `README.md` + `v0..v3/`; each `v_n/` holds exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (50/100/200/400 rows; 8/16/24/32 workspace files, matching the 1/2/4/8 and +0/N/2N/3N pattern).
- Section 2 (solvability): pass on first run; 96 recipients flagged at v3 scale; top three priorities returned.
- Section 3 (env quality): pass — every step criterion maps to an explicit prompt requirement; ground truth recomputed from DB + workspace each call (no hard-coded counts); 2% tolerance on discrepancy amounts is appropriate for floating-point arithmetic.
- Section 4 (prompt quality): pass — no headings/bold/lists, no tool or source filenames leaked, output filename `investigation_report.csv` and column names specified, scale-invariant wording ("every recipient", "all their self-reports").
- Issues found / fixes: none.
- Blockers: none.
