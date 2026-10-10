## Task Topic

Identify underperforming stations for relocation by analyzing monthly usage trends, station maintenance logs, surrounding points-of-interest density, and user complaint reports, outputting a ranked list of candidate stations for decommissioning or relocation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Maintenance financial costs come exclusively from a tool, while downtime hours come from workspace YAML files. Complaint severity scores come exclusively from a tool, while unresolved counts come from workspace text files. Usage trends and POI density are found only in workspace CSV and JSON files respectively. Scoring weights and thresholds reside in workspace config files. No single source is sufficient.
- **Multi-Hop Reasoning**: The agent must read config files to learn the scoring methodology, read multiple workspace file types for partial station data, call paginated station listing to discover eligible stations, call two per-station tools (maintenance cost and complaint severity) for every eligible station, cross-reference all sources to compute composite scores, and apply decision rules to produce recommendations — a dependency chain of length ≥ 4.
- **Conditional Constraints**: Stations installed after a cutoff date are excluded from evaluation. The decommission recommendation requires both low POI density and high usage decline, while all other candidates receive a relocate recommendation.
- **Deliverable Constraints**: The output CSV requires exact column ordering, composite scores at exactly two decimal places, uppercase recommendation labels, descending score sort with station-ID tie-breaking, and a response summary with specific counts.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (file_structure 10, candidate_ids 20, composite_scores 20, recommendations 20, ranking_order 15, response_summary 15)
- Source-access: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to read `env.py`/`data.py` was required.
- Structural integrity: passed. v0..v3 differ only in the `SCALE` block of `data.py`; `env.py` and `prompt.md` are byte-identical across versions.
- Section 3 (prompt-step alignment): step() recomputes ground truth from DB + workspace configs, with no hard-coded counts; criteria are scale-invariant.
- Section 4 (prompt formatting): prompt.md uses prose only — no headings, bullets, tool names, or absolute counts.
- Issues found: none. No fixes required.
- Blockers: none.
