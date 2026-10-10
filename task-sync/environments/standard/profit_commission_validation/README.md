## Task Topic

Validate a reinsurer's quarterly profit commission statement. Cross-reference ceded premium statements, paid loss bordereaux, treaty-defined sliding scale commission formulas, and prior year's loss carry-forward balances to verify the calculated commission amount, outputting a signed approval or a discrepancy report.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The number of treaties scales with `num_workspace_files` (one loss bordereaux CSV per treaty), while `rows_per_table` controls how many ceded-premium and paid-loss records are distributed across those treaties. Four fixed configuration files (YAML, JSON, TXT, MD) are produced at every scale.

**Structural dimensions used:**

- **Information Scattering** -- Paid losses and ceded premiums live in the database (accessible only through tools), while loss adjustment expenses sit in per-treaty bordereaux CSVs, expense percentages in a JSON config, and sliding-scale commission tables in a YAML file. Solving the task requires combining all of these sources.
- **Multi-Hop Reasoning** -- The dependency chain runs: treaty details (tool) -> line of business -> sliding-scale YAML lookup -> loss ratio calculation (requires DB losses + workspace LAE) -> bracket match -> commission rate -> net profit (requires expense loading from JSON + carry-forward from tool) -> final commission.
- **Conditional Constraints** -- Commission is only positive when net profit exceeds zero; the commission rate itself varies by loss-ratio bracket and line of business. Carry-forward uses the closing balance (not the opening balance), and loss adjustment expenses must be included in incurred losses.
- **Deliverable Constraints** -- The output CSV has a fixed column order, status values must be exactly `APPROVED` or `DISCREPANCY`, variance is defined as reported minus calculated, and the final response must state exact counts and aggregate variance.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (report_structure 10, treaty_coverage 10, status_accuracy 25, commission_calculation 25, variance_accuracy 15, summary_response 15)
- Source-access: clean — solver wrote against `v3/prompt.md` + `get_assistant_tools()` only; `env.py` opened only after solver achieved reward 1.0, for Section 3 review.
- Issues found and fixes:
  - Stale `v0/__pycache__` directory at start; removed during Section 1 cleanup.
  - No structural, prompt, or step-logic issues required propagated edits. `diff` confirmed v0/v1/v2/v3 share byte-identical `env.py` and `prompt.md`; `data.py` differs only in the `SCALE` block.
- Blockers: none.
