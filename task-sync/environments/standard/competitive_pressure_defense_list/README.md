## Task Topic

Analyze competitor web activity by aggregating daily search result rankings, product pricing feeds, social media post volumes, and internal deal pipeline stages to flag accounts with rising competitive pressure, generating a prioritized defense list for sales teams.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 8.

**Structural dimensions used:**

- **Information Scattering**: Scoring weights, thresholds, stage-risk mappings, and defense actions live in workspace config files (YAML, JSON, CSV, Markdown). Intel modifiers that adjust each account's score are spread across multiple field intelligence report files. Quantitative signals (search rankings, pricing feeds, social media volumes, deal pipeline stages) are only accessible via tool calls. Solving the task requires combining data from both sources.

- **Multi-Hop Reasoning**: The dependency chain has depth ≥ 3: retrieve account list → retrieve deals per account (links to competitors) → for each competitor, query search/pricing/social tools → look up stage risk from CSV → apply intel modifier from JSON files → compute weighted composite → classify via thresholds → map to defense action from playbook.

- **Conditional Constraints**: Pressure classification depends on configurable thresholds read from a JSON file; pipeline risk depends on stage-to-risk mappings from a CSV; the intel modifier from workspace files multiplicatively adjusts the composite score before classification.

- **Deliverable Constraints**: Output CSV requires exact column names and order, scores rounded to four decimal places, descending sort with account-ID tie-breaking, and recommended-action text that must match the playbook verbatim.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (csv_structure, pressure_scores, pressure_levels, sort_order, recommended_actions, high_count_in_response, top5_in_response)
- Solver source-access: clean black-box solve. Used only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Issues found and fixes: only one minor structural artifact — a stray `v0/__pycache__/` directory was present at the start. Removed it during cleanup. All four `env.py` and `prompt.md` files are byte-for-byte identical across v0..v3, and `data.py` differs only in the `SCALE` block (rows 50/100/200/400, files 8/16/24/32 — matching the 1×/2×/4×/8× and base+0/N/2N/3N ratios).
- No blockers.
