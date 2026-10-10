## Task Topic

Identify units at risk of wastage by analyzing real-time inventory levels, blood type demand forecasts from hospital contracts, upcoming expiration dates, and inter-bank transfer request logs to produce a prioritized redistribution list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

**Structural dimensions used:**

- **Conditional Constraints**: Wastage risk scoring depends on multi-factor brackets (days-to-expiry, surplus ratio, transfer activity) with weights and thresholds defined in workspace YAML config; platelet bonus, reserved-unit reduction, and quarantine exclusion add further conditional logic.
- **Information Scattering**: Scoring parameters live in YAML/Markdown/JSON config files in the workspace, while unit inventory, hospital contracts, and transfer logs are only accessible through tool calls. Both sources are required to compute the redistribution list.
- **Multi-Hop Reasoning**: Computing a unit's suggested recipient requires: (1) tool call to get expiring units → (2) tool call to get demand from contracts → (3) tool call to get available inventory at candidate banks → (4) workspace config to determine eligible transfer partners → (5) compute unmet demand to pick the best recipient.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 7 (file_exists 10, correct_columns 10, correct_unit_set 25, correct_risk_scores 20, correct_sort_order 15, correct_recipients 20, response_unit_count 10)
- Section 1 (structural integrity): clean. Top-level contains only README.md and v0..v3; each v_n has exactly data.py/env.py/prompt.md; env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE block.
- Section 2 (solvability at v3): solver written from prompt.md + get_assistant_tools() only; achieved reward 1.0 on first attempt without opening env.py or data.py (no step-6 escalation needed).
- Section 3 (env quality): step() ground truth derived from current data.db / workspace; no hard-coded counts; criteria match prompt deliverables (file, columns, unit set, risk scores, sort, recipients, response summary).
- Section 4 (prompt quality): no headings/bold/bulleted deliverables; computation described in prose; no tool names or source filenames leaked; deliverable file/columns named explicitly; scale-invariant wording ("every blood bank", "every unit").
- Issues found: none. No fixes required.
- Blockers: none.
