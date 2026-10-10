## Task Topic

Validate subcontractor progress payment applications. Cross-reference submitted work completion certificates, daily site supervisor logs, material delivery invoices, and architect inspection reports against the project schedule to calculate approved payment amounts, outputting a certified payment schedule.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 20             | 10                  |
| v1      | 40             | 20                  |
| v2      | 80             | 30                  |
| v3      | 160            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=10.

Structural dimensions used:

- **Information Scattering**: Payment applications, schedule items, inspection reports, and material delivery totals live in the database (accessible only via tools), while completion certificates (JSON), supervisor daily logs (Markdown), material invoices (CSV), and the payment policy (YAML) reside in workspace files. Solving the task requires merging data from both sources for every pending application.
- **Multi-Hop Reasoning**: Each application requires a dependency chain of length ≥ 4: retrieve the pending application → look up the schedule item and subcontractor → fetch the inspection report and material deliveries → read the workspace certificate, invoice, and supervisor logs → apply policy rules → compute the certified payment amount.
- **Conditional Constraints**: Approval depends on supervisor sign-off (from certificates), minimum approved percentage (from policy), deficiency deductions (from inspection reports), material discrepancy penalties (comparing tool data against invoice files), and delay penalties (parsed from supervisor logs against policy thresholds).

## Harness Report

- v3 reward: 1.0
- Eval criteria: 7 (output_file_structure, entry_count, approved_pct_accuracy, gross_approved_accuracy, deductions_accuracy, retention_net_payable_accuracy, response_totals)
- Source-access: clean. Section 2 was completed using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`. `env.py` was opened only under step-6 escalation to confirm the solver bug was mine, not a prompt/step issue.
- Structural integrity: v0/env.py == v1/v2/v3/env.py byte-for-byte; same for prompt.md; data.py differs only in SCALE block (rows 20/40/80/160; files 10/20/30/40, matching N/2N/4N/8N rows and +0/N/2N/3N files with N=10).
- Issues found: none requiring fixes. The initial sub-1.0 reward was a solver-side bug (applying the material-discrepancy penalty when the invoice CSV was missing); the env correctly skips this check when the corresponding `invoice_SI-XXX.csv` does not exist, which is reasonable behavior consistent with the prompt's wording. After fixing the solver, reward reached 1.0.
- Blockers: none.
