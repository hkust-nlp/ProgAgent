## Task Topic

Reconcile concession stand inventory and sales to detect shrinkage. Cross-reference point-of-sale transaction logs, vendor delivery invoices, shift-based staff schedules, and waste log sheets to identify discrepancies between sold and used stock, outputting a variance report with flagged stands for investigation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios follow the standard progression: rows double each version (v1 = 2×, v2 = 4×, v3 = 8× base), while workspace files grow linearly (v1 = base + N, v2 = base + 2N, v3 = base + 3N where N = base = 10).

**Structural dimensions used:**

- **Information Scattering**: Sales data, customer returns, inter-stand transfers, and staff schedules live in the database (accessible only via tool queries), while vendor delivery invoices and waste log sheets are spread across multiple workspace files in mixed formats (CSV, pipe-delimited TXT, Markdown tables). Beginning and ending physical inventory counts, the product catalog, and the shrinkage policy are additional workspace files. Solving the task requires combining all sources.

- **Multi-Hop Reasoning**: The dependency chain involves reading policy thresholds → querying per-stand sales/returns/transfers via tools → parsing delivery invoices and waste logs from files → computing per-product variance → aggregating per-stand shrinkage → applying policy bands to assign investigation priority → querying staff schedules for flagged stands only (chain length ≥ 4).

- **Conditional Constraints**: A stand is flagged only when both its aggregate shrinkage value exceeds the dollar threshold and its aggregate shrinkage percentage exceeds the percentage threshold (both from the policy file). Investigation priority is then tiered based on percentage bands defined in the same policy.

- **Deliverable Constraints**: Exact column order, naming, sort keys, rounding precision (2 decimal places), and delimiter for staff names (semicolon-space) are all specified and evaluated strictly.

## Harness Report

- v3 solver reward: 1.0 (100/100)
- Eval criteria: 6 (variance_report_format 10, variance_calculations 25, flagged_stands_identification 20, priority_assignment 15, staff_association 15, response_summary 15)
- Solver source-access: clean black-box solve using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. No step-6 escalation to `env.py` was needed.
- Section 1 structural integrity: passed (env.py and prompt.md byte-identical across v0..v3, only SCALE differs in data.py, ratios 1×/2×/4×/8× rows and base+0N/+N/+2N/+3N files all correct).
- Section 3/4 quality review: prompt-step alignment verified; criteria are scale-invariant (computed from current data each call); prompt is clean prose with no headings/lists/tool-names and uses scale-invariant wording.
- Issues found / fixes: none.
