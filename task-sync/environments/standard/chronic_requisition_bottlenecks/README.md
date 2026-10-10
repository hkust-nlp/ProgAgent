## Task Topic

Identify high-volume job requisitions with chronic hiring delays. Analyze requisition age, candidate application flow rates, hiring manager feedback scores, and recruiter assignment logs to flag roles open >60 days, outputting a priority intervention list with bottleneck causes.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 8                   |
| v1      | 120            | 16                  |
| v2      | 240            | 24                  |
| v3      | 480            | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Bottleneck analysis requires combining tool-sourced data (candidate applications, recruiter assignments, feedback scores) with workspace files (department thresholds, weekly pipeline snapshots, bottleneck classification rules, priority scoring formulas). Neither source alone is sufficient.
- **Conditional Constraints**: Each bottleneck type has department-specific thresholds (minimum application rates, acceptable feedback scores, maximum recruiter changes) stored in workspace configuration files; eligibility depends on cross-referencing multiple tables and config parameters.
- **Multi-Hop Reasoning**: Determining whether a requisition has a "high_stage_stagnation" bottleneck requires: querying candidates (tool) → reading pipeline stage expected durations (workspace file) → comparing each candidate's tenure against the threshold → aggregating the stagnation percentage. Similarly, priority scoring chains through bottleneck detection → severity weight lookup → score computation.
- **Deliverable Constraints**: The output CSV must have exact column names, specific sort order (priority_score descending, requisition_id ascending as tiebreaker), and the response must include the total flagged count and top-priority requisition ID.

## Harness Report

- v3 reward: 1.0 (perfect score, 100/100).
- Eval criteria count: 7 (intervention_list_file_exists, correct_columns, correct_flagged_requisitions, correct_priority_scores, correct_bottleneck_classification, correct_sort_order, response_summary).
- Solver source-access: clean black-box. The solver was authored using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` or `data.py` was required.
- Issues found: none. Structural integrity (env.py and prompt.md byte-identical across v0-v3, only SCALE differs in data.py with rows 60/120/240/480 and files 8/16/24/32) is satisfied. Prompt formatting is heading/bullet/code-free, scale-invariant, and avoids tool/internal filename leaks. Step alignment covers every prompt deliverable; no hidden criteria; ground truth is recomputed from current data and configs each run.
- Fixes applied: none.
