## Task Topic

Detect food safety issues in cold-chain shipments by monitoring IoT temperature excursions, tracing lot-level ingredient genealogy, reviewing third-party sanitation audit violations, and analysing consumer complaint symptom frequencies to flag lot codes for immediate product hold.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10 (the v0 base).

### Structural Dimensions

- **Information Scattering**: temperature thresholds live in a YAML config, product categories in a CSV catalog, audit violations in CSV report files, complaint symptom codes in JSON detail files, and supplier certification status in a CSV directory. Raw sensor readings, ingredient genealogy, and complaint-lot associations are only accessible through query tools. Solving the task requires combining data from both workspace files and tool calls at every step.

- **Multi-Hop Reasoning**: the temperature excursion check follows a chain of length 4: lot → product_id (tool) → storage category (product catalog CSV) → threshold (YAML policy) → compare against sensor readings (tool). The sanitation criterion requires: lot → shipments (tool) → transit facilities (manifest JSON) → violations (audit CSV). The ingredient-link criterion chains: primary-flagged lot → ingredients (tool) → shared lots (reverse-lookup tool) → supplier status (CSV directory).

- **Conditional Constraints**: each of the four hold criteria involves threshold-based conditions drawn from workspace configuration files (count thresholds, temperature excess limits, violation severity and resolution status, complaint cluster counts, symptom severity ratings, supplier certification status).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (report_structure 10, temp_excursion_lots 20, sanitation_lots 15, complaint_cluster_lots 15, ingredient_link_lots 20, risk_scores 10, final_response 10)
- Section 1 (structural integrity): passed. Each `v_n/` contains only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Section 2 (solvability): passed cleanly. Solver written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` (no escalation to `env.py`); reward 1.0 on first run.
- Section 3 (env quality): step-criterion coverage matches prompt requirements; ground truth is recomputed from `data.db`/workspace at every call; criteria and weights are scale-invariant.
- Section 4 (prompt quality): prose-only, no tool names or source filenames leaked, no absolute row counts.
- Issues found and fixed: none.
- Note (non-blocking): under v3 SCALE, ~99% of lots are flagged once `INGREDIENT_LINK` propagates from primary-flagged lots; the env logic and prompt agree, so this is a difficulty-tuning observation rather than a correctness bug.
- Cleanup: all `data.db`, `workspace/`, `__pycache__/` removed from every `v_n/`; `/tmp` solver removed.
