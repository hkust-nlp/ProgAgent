## Task Topic

Automatically route technical support tickets by parsing error codes from ticket descriptions, matching to product SKU from support portal logs, checking agent certification records, and analyzing current team queue depth to assign to the first available qualified engineer.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 12                  |
| v1      | 100           | 24                  |
| v2      | 200           | 36                  |
| v3      | 400           | 48                  |

Structural dimensions used:

- **Information Scattering**: Error codes are embedded in ticket description text files; the error-code-to-product-SKU mapping lives in portal log CSV files; product category is only available via the product lookup tool; routing rules and shift schedule are in separate JSON config files. No single source contains all the information needed to make a routing decision.
- **Multi-Hop Reasoning**: Ticket file → parse error code → portal log CSV → product SKU → tool: lookup product → category → config: severity-to-cert-level mapping → tool: engineer certifications → tool: queue depth → tool: assign ticket. This is a dependency chain of length 5+.
- **Conditional Constraints**: Assignment eligibility depends on severity-driven certification level requirements, shift-matching, active status, non-expired certifications, and queue capacity limits. Thresholds and rules live in workspace configuration files.

## Harness Report

- v3 solver reward: 1.0 (total_score 100/100).
- Eval criteria: 7 (`assignments_file_format` 10, `all_tickets_covered` 10, `error_codes_correct` 15, `product_mapping_correct` 15, `certification_valid` 20, `optimal_assignment` 20, `db_assignments_recorded` 10).
- Source-access: clean. Solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; `env.py` was opened in Section 3 for prompt-step alignment review only.
- Structural integrity: passed. `diff` confirmed `env.py`/`prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 50/100/200/400, files 12/24/36/48 — matches harness ratios with N=12).
- Prompt-step alignment: every criterion in `step()` maps to a prompt requirement; no hidden criteria; no over-normalization; ground truth derived dynamically from `data.db`/workspace.
- Prompt quality: no title/headings, no bullet lists, no tool names, scale-invariant wording, output filename and column order specified.
- Issues found and fixed: none. No edits to `v0/` or any version were required.
- Blockers: none.
