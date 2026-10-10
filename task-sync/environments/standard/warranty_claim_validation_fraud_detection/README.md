## Task Topic

Validating warranty claim legitimacy requires cross-referencing customer-submitted failure photos, serial number production dates, quality control pass/fail records from final test stations, and repair center service histories, outputting a flagged claims report for fraud investigation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 12                  |
| v1      | 160           | 24                  |
| v2      | 320           | 36                  |
| v3      | 640           | 48                  |

The task uses the following structural dimensions:

- **Information Scattering**: Photo timestamps are only available in workspace JSON batch files, repair costs are only in workspace CSV center logs, while claim details, product info, QC records, and service visit counts are only reachable via tool calls. Rule thresholds and warranty durations live in workspace YAML config files. No single source is sufficient.
- **Multi-Hop Reasoning**: Each fraud flag requires a dependency chain of length >= 3. For example, EXCESSIVE_REPAIR_COST requires: list pending claims (tool) -> get product info for MSRP (tool) -> read repair center logs for costs (workspace) -> read rules for threshold (workspace) -> compute and compare.
- **Conditional Constraints**: Six distinct fraud rules with thresholds drawn from workspace configuration files, each combining 2-3 data sources with specific comparison logic.

## Harness Report

- v3 reward: 1.0
- Number of eval criteria: 7 (`report_format`, `flagged_completeness`, `no_false_positives`, `correct_flags`, `correct_risk_scores`, `sort_order`, `summary_count`)
- Source-access: clean (Section 2 solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no step-6 escalation required)
- Section 1 (structural integrity): pass — `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block.
- Section 2 (solvability at v3): pass — solver computed 69 flagged claims and `env.step` returned reward 1.0 on first successful run.
- Section 3 (env quality): pass — every `step` criterion maps to a prompt requirement and vice versa; ground truth recomputed from current DB/workspace, no hard-coded counts.
- Section 4 (prompt quality): pass — no headings/bullets, no tool/internal names, scale-invariant language ("every pending claim", "all pending claims"), output filename and column names explicit.
- Issues found and fixed: none. No edits to `v0/` were required.
- Cleanup: removed `data.db`, `workspace/`, and `__pycache__/` from each version directory; removed temporary solver under `/tmp`.
