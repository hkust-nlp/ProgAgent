## Task Topic

Audit code review coverage across repositories by analysing pull request diffs, reviewer comment density, static analysis violation counts, and historical defect escape rates to flag releases with insufficient review and issue go/no-go reports.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

The task uses all four structural dimensions:

- **Conditional Constraints**: The go/no-go decision depends on criticality-tier-specific thresholds (from a YAML policy file) cross-referenced with per-repository minimum reviewer counts (from batch profile files). Different tiers impose different ceilings and floors on four independent metrics.
- **Deliverable Constraints**: The output CSV has prescribed column names, column order, decimal precision (four places), integer formatting, exact decision strings ("GO" / "NO-GO"), semicolon-delimited failure lists, and ascending sort by release ID. The response summary must match a rigid template.
- **Information Scattering**: Repository criticality tiers and reviewer requirements live exclusively in workspace configuration files (spread across CSV, JSON, YAML, TXT, and MD batches), while pull-request metrics, review comments, violations, and defect escapes are only accessible through tool calls. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: Each release decision requires a chain of at least four hops: read workspace profile → determine tier → look up tier thresholds from policy → query tool data for PRs, comments, violations, and historical defect stats → compute metrics → compare against thresholds → render decision.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (report_format, row_count, review_coverage_accuracy, density_violations_accuracy, defect_escape_rate_accuracy, decisions_accuracy, response_summary).
- Solver source-access: clean black-box. The solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` or any other source file was needed.
- Structural integrity: passed. `env.py` and `prompt.md` are byte-identical across v0..v3; only the `SCALE` block in `data.py` differs, and the v0/v1/v2/v3 ratios follow the prescribed 1x/2x/4x/8x rows and +0/+N/+2N/+3N files (N=8) progression.
- Issues found: none. Prompt formatting (no headings, no lists, scale-invariant wording) and step-prompt alignment (every criterion maps to a stated requirement; ground truth recomputed from the live DB and workspace) both check out.
- Fixes applied: none beyond the standard cleanup of `data.db`, `workspace/`, `__pycache__/`, and the `/tmp` solver script.
