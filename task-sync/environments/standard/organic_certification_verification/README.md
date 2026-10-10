## Task Topic

Verify organic certification compliance for a batch of avocados by cross-referencing farm pesticide application logs, soil test results, processor lot codes, and third-party audit certificates, outputting a compliance validation report for the retail buyer.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 8                   |
| v1      | 120           | 16                  |
| v2      | 240           | 24                  |
| v3      | 480           | 32                  |

Scaling ratios: `rows_per_table` doubles each version (v1=2x, v2=4x, v3=8x of v0 base). `num_workspace_files` grows as base + N, base + 2N, base + 3N where N = base (8).

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Lot declared weights live in the database (via `lookup_lot`), while measured weights and inspection temperatures are only in workspace inspection report files. Banned-substance lists are in a YAML config file, while actual pesticide application records are only accessible through the `get_pesticide_applications` tool. Approved laboratory names are in a CSV file, while soil test lab names come from the `get_soil_tests` tool.

- **Multi-Hop Reasoning**: The task involves dependency chains of length ≥ 3. For example: batch manifest → `lookup_lot` (get farm_id) → `get_pesticide_applications` (get chemical names per year) → cross-reference with YAML banned-substances list → determine compliance. Similarly: batch manifest → `lookup_lot` → `get_soil_tests` → cross-reference lab name with approved_labs.csv → determine lab accreditation status.

- **Conditional Constraints**: Compliance determination depends on multiple threshold-based rules from the organic standards YAML (soil pH range, heavy metal limits, temperature caps, weight tolerance percentages, defect rate limits) combined with categorical checks (audit certificate status must be "approved", lab must be accredited, pesticide category must not be "synthetic").

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (`report_format`, `row_count`, `overall_status_accuracy`, `individual_checks_accuracy`, `failure_reasons_accuracy`, `summary_file`, `response_batch_status`)
- Source-access: clean — solver written using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no step-6 escalation needed.
- Structural integrity: passed (`v0..v3` byte-identical for `env.py`/`prompt.md`; only `SCALE` differs in `data.py`).
- Issues found: none. Prompt-step alignment, scale-invariance (ground truth recomputed from DB/workspace each step), and prompt formatting (no headings/bullets/tool names) all verified.
- Fixes applied: none.
- Blockers: none.
