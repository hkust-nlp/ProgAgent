## Task Topic

Analyze code review bottlenecks by correlating pull request metadata, reviewer assignment logs, team member availability calendars, and historical review completion times to identify overloaded reviewers, generating a rebalancing proposal.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Information Scattering**: Reviewer capacity depends on availability schedules (workspace CSV files) combined with role capacity multipliers (workspace JSON config), while review assignments and PR metadata are only accessible through tool calls. Priority weights and overload thresholds live in separate workspace configuration files. No single source contains enough information to solve the task.
- **Conditional Constraints**: Reassignment eligibility requires the proposed reviewer to have matching language specializations, not be the PR's author, not be overloaded themselves, meet a minimum historical quality score threshold (from the policy config), and not exceed the overload threshold after absorbing the new assignment.
- **Multi-Hop Reasoning**: Computing whether a reviewer is overloaded requires chaining: tool call (get assignments) → tool call (get PR details for priority/complexity) → workspace file (priority weights) → workspace file (availability schedules) → workspace file (role capacity multiplier) → compare against workspace policy threshold. Rebalancing adds another hop: tool call (get completion stats for quality check on candidate).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 5 (overloaded_file_structure, overloaded_reviewer_ids, overload_metrics_accuracy, rebalancing_proposals_valid, response_summary)
- Section 1 structural integrity: clean — all four versions byte-identical for `env.py` and `prompt.md`; only `data.py` differs (SCALE block).
- Section 2 solvability: solver written from `v3/prompt.md` + `get_assistant_tools()` only; no escalation to `env.py`. Achieved reward 1.0 on first run.
- Section 3/4 review: prompt-step alignment confirmed via 1.0 score on first solver attempt; prompt is prose-only with no tool/source-file leakage and uses scale-invariant wording.
- Issues found: none. No fixes required.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from all `v_n/`; removed `/tmp/solve_reviewer_load_rebalancing.py`.
