## Task Topic

Evaluate commercial property insurance applications by cross-referencing building construction permits, historical regional flood/fire claims, current occupancy sensor data, and applicant financial stability scores to generate a risk-tiered quote list with recommended coverage limits and premiums.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Risk factors are split across seven database tables (accessible only via tools) and workspace property assessment files. Environmental risk data (flood zone distance, fire station proximity, building condition) exists only in workspace JSON files, while construction, claims, occupancy, and financial data are only available through tool calls. Neither source alone is sufficient.
- **Conditional Constraints**: Eligibility screening requires checking two financial thresholds simultaneously (stability score < 30 AND debt ratio > 0.70). Coverage limits depend on a two-dimensional lookup (tier code x construction type). Premium calculation includes a conditional stability discount.
- **Multi-Hop Reasoning**: Computing a quote requires a chain of at least four hops: application -> property -> region -> claims history -> avg severity -> risk score -> tier -> coverage matrix lookup -> premium calculation. Environmental risk adds another chain: property ID -> assessment file lookup -> flood/fire/condition scores.
- **Deliverable Constraints**: The output CSV has a fixed nine-column schema with exact column order, specific status labels (QUOTED/DECLINED), empty fields for declined rows, descending risk-score sort with application_id tie-breaking, and premiums rounded to exactly two decimal places.

## Harness Report

- **v3 reward:** 1.0 (100/100)
- **Eval criteria count:** 8 (quote_list_structure, row_count, status_accuracy, risk_score_accuracy, tier_accuracy, coverage_accuracy, premium_accuracy, risk_summary)
- **Solver source-access:** Clean black-box. Solver written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; passed on first run without inspecting `env.py` or `data.py`.
- **Issues found:** None. Structural integrity intact (env.py and prompt.md byte-for-byte identical across v0-v3; data.py differs only in SCALE block; SCALE ratios match the 1/2/4/8 row and +0/+N/+2N/+3N file convention). Prompt is well-formed (no headings, lists, tool names, or absolute counts). step() coverage and completeness align with prompt deliverables; scale-invariant (ground truth recomputed from data.db/workspace).
