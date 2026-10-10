## Task Topic

Optimize industrial conveyor belt replacement by cross-referencing IoT vibration sensor feeds, historical component lifespan logs, production throughput schedules, and supplier lead times to produce a validated maintenance calendar minimizing unplanned downtime.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Conditional Constraints**: Belt replacement eligibility depends on three criteria spanning vibration readings, visual wear scores from inspection files, and historical lifespan statistics — each with configurable thresholds from workspace policy files. Urgency tier assignment follows layered rules (critical threshold, multi-criteria count).
- **Information Scattering**: Vibration data and lifespan records live in the database (accessed via tools), while visual wear scores reside in workspace JSON inspection reports and decision thresholds/rules are spread across YAML, JSON, CSV, and TXT configuration files.
- **Multi-Hop Reasoning**: Scheduling requires a chain of at least four steps — retrieve supplier options → compute adjusted scores using contract terms from workspace files → determine earliest date from lead time → cross-reference production schedules to find maintenance-eligible windows.
- **Deliverable Constraints**: The output CSV has exact column order, specific sort keys (date ascending, urgency descending), and precise numeric formatting (cost to 2 decimals, impact to 1 decimal).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_format 10, belt_identification 25, urgency_assignment 20, supplier_selection 15, replacement_dates 15, cost_and_impact 10, response_summary 5)
- Solver source-access: clean black-box — solver written from `v3/prompt.md` + `get_assistant_tools()` only; no escalation to `env.py` needed.
- Issues found: none. Structural integrity passed (env.py and prompt.md byte-identical across v0..v3; data.py differs only in SCALE). Prompt quality clean (prose-only, no tool names, scale-invariant wording). step() is scale-invariant (ground truth derived from current db/workspace) and column/precision strict per prompt.
- Fixes: none required.
