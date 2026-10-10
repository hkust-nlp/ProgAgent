## Task Topic

Identify user-journey conversion bottlenecks by replaying session error logs, aggregating rage-click heatmaps, measuring funnel step abandonment rates, and correlating A/B test variant assignments to build a prioritised UX fix backlog per page.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Error severity weights, heatmap zone boundaries, funnel definitions, A/B test hypotheses, and confirmed-issue counts each live in separate workspace files (JSON, YAML, CSV, Markdown), while actual error logs, rage-click events, funnel metrics, and A/B variant session counts are only reachable through tool calls. Solving the task requires cross-referencing both sources.
- **Multi-Hop Reasoning**: Computing the priority score for a page requires a dependency chain of length ≥ 3, for example: read zone definitions from CSV → retrieve rage-click coordinates via tool → match coordinates to zones → multiply by zone-type weight from YAML → normalise by cap → combine with four other components using weights from the config → produce final score. A/B impact similarly chains through test-hypothesis lookup → per-variant metric retrieval → problem-rate computation → absolute difference.
- **Conditional Constraints**: Whether a page receives a non-zero abandonment rate or A/B impact depends on whether it appears in the funnel definition or is targeted by an A/B test, respectively; these conditions are encoded in workspace configuration files rather than in the prompt.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (backlog_file_format 10, backlog_pages_complete 10, priority_scores_accuracy 25, backlog_ranking_top5 15, funnel_report_structure 10, abandonment_rates_accuracy 15, top3_in_response 15).
- Source-access: clean. Solver succeeded using only `v3/prompt.md` and `Task_Env(...).get_assistant_tools()`; no escalation to `env.py`/`data.py` was required.
- Structural integrity: passed. Top-level holds only `README.md` + `v0..v3/`; each version dir holds only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Issues found and fixed: none. Section 3 (env quality) and Section 4 (prompt.md formatting and scale invariance) reviews uncovered no problems requiring changes.
- Cleanup: runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) removed from every version directory; `/tmp/solve_ux_conversion_fix_backlog.py` removed.
