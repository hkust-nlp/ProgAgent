## Task Topic

Identify unspent grant funds nearing expiration. Cross-reference general ledger expenditure transactions, award modification notices, sponsor payment records, and institutional indirect cost rates to calculate remaining balances, outputting a priority use-it-or-lose-it list for project directors with 90-day deadlines.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x progression; workspace files follow base/base+N/base+2N/base+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Grant details live in the database (accessible only through tools), while carryover approvals are buried in batch memo text files, director contact emails are split across JSON batch files, and pending obligations reside in CSV batch files. No single source contains everything needed.
- **Multi-Hop Reasoning**: The computation chain spans at least four hops — list grants via tool → check award modifications for no-cost extensions via tool → read memo files to filter carryover-approved grants → retrieve expenditures and IDC rates via tools → read pending obligations from workspace CSVs → compute remaining balance and assign priority tier from config.
- **Conditional Constraints**: Priority tier assignment depends on both days-to-expiration and remaining-balance percentage thresholds defined in a JSON config file; IDC charges depend on excluded expense categories defined in a YAML policy file; grants with sponsor-approved carryover are conditionally excluded.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 8 (`report_file_exists`, `correct_columns`, `correct_grant_set`, `correct_remaining_balance`, `correct_idc_charges`, `correct_priority_tier`, `correct_sorting`, `correct_director_emails`)
- Source-access during Section 2: escalated to step 6 (read `v3/env.py`) once after the prompt-only solver scored 89/100, to diagnose the priority-tier mismatch.
- Issue found: `_compute_ground_truth` (and `verify`) defaulted `priority_tier = "low"` for grants matching no tier rule, silently including grants whose remaining-balance percentage was below every tier's threshold (i.e., already overspent). The prompt explicitly requires assigning the first tier whose day AND percentage thresholds are both satisfied, and frames the report as awards "whose remaining budget has not been fully exhausted", so step had a hidden criterion that contradicted the prompt.
- Fix: in `v0/env.py`, replaced the `"low"` default in both `_compute_ground_truth` and `verify` with `priority_tier = None` plus a `continue` when no tier matches; re-propagated byte-identically to `v1/v2/v3`. After the fix, the prompt-only solver scored 100/100 at v3.
