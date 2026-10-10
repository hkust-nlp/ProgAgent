## Task Topic

Detect royalty overpayments from incorrect territory splits. Analyze distributor sales reports, artist contracts specifying regional revenue shares, and tax treaty documentation to find mismatches, producing a recovery claim list with calculated overpayment amounts per territory.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Gross revenue figures are only available in workspace CSV files (distributor sales reports), contractual revenue share rates are only accessible via tool queries, withholding tax rates reside in a workspace YAML file, and actual payment amounts come from tool queries. No single source contains all fields needed to compute the correct royalty or detect an overpayment.
- **Multi-Hop Reasoning**: The dependency chain is: read sale CSV (gross revenue, actual territory) → query payment tool (applied territory, amount paid) → query contract tool (correct revenue share for actual territory) → read tax treaty file (withholding rate) → compute correct royalty → compare with paid amount → apply policy thresholds from config file. This is a chain of length 5+.
- **Conditional Constraints**: Recovery priority classification depends on overpayment amount thresholds defined in a workspace policy configuration file, and only overpayments above a minimum threshold are included.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (file_exists, correct_columns, correct_identification, correct_amounts, correct_priority, correct_sorting, response_summary)
- Source-access: clean — solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`. No step-6 escalation to `env.py` was required.
- Section 1 structural integrity: passed (env.py and prompt.md byte-identical across v0..v3; data.py differs only in SCALE; SCALE rows ×1/2/4/8 = 50/100/200/400 and files +0/N/2N/3N = 8/16/24/32).
- Section 3 prompt-step alignment: passed (every criterion maps to a prompt requirement; ground truth recomputed dynamically from data.db + workspace; no hard-coded counts).
- Section 4 prompt quality: passed (no title/headings/bold/bullets; column list woven into prose; no tool or source-filename leakage; scale-invariant wording).
- Issues found and fixes: none. No edits needed to v0 or any version.
- Blockers: none.
