## Task Topic

Identify startups for follow-on investment by analyzing portfolio company performance metrics (monthly burn, revenue growth), founder cap table dilution, competitor funding rounds, and internal partner sentiment scores, outputting a prioritized outreach list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 20            | 10                  |
| v1      | 40            | 20                  |
| v2      | 80            | 30                  |
| v3      | 160           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N=10.

**Structural dimensions used:**

- **Information Scattering**: Strategic fit scores exist only in workspace intelligence report files (across 5 formats: .md, .json, .txt, .csv, .yaml), while financial metrics, cap table data, and partner sentiments are only accessible through tools. Solving the task requires combining both sources.
- **Conditional Constraints**: Eligibility depends on four gates spanning three data sources — funding stage (company info), average monthly revenue (financials), founder ownership percentage (cap table), and average partner sentiment (sentiment records). Thresholds are defined in a workspace YAML configuration file.
- **Multi-Hop Reasoning**: The composite score requires a chain of at least length 3: retrieve company info (tool) → read scoring config (file) → retrieve financials/cap table/sentiments (tools) → read intelligence reports for strategic fit (files) → compute normalized factor scores → weighted composite → tier assignment.
- **Deliverable Constraints**: Output CSV has exact column order, sort key with tie-breaker, specified decimal precision per field, and defined tier labels.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (file_structure, eligible_completeness, no_ineligible, score_accuracy, ranking_order, tier_assignment, response_summary).
- Section 1 structural integrity: passed. Each `v_n/` contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (rows 20/40/80/160; workspace files 10/20/30/40, matching the +0/N/2N/3N convention with N=10).
- Section 2 solvability: solver authored under `/tmp/` using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; submitted via `env.step` and reached reward 1.0 without inspecting `env.py` or `data.py`.
- Issues found: none. No edits required to `env.py`, `prompt.md`, or `data.py`. Prompt is scale-invariant prose with explicit column/precision/sort spec; tool names and source filenames are not leaked.
- Cleanup: removed `data.db`, `workspace/`, and `__pycache__/` from every `v_n/`; removed `/tmp/` solver.
