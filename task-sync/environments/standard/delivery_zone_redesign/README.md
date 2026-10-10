## Task Topic

Identify inefficient delivery zones by analyzing geofenced order clusters, average rider transit times between pickups, restaurant preparation duration logs, and customer address density to produce a re-zoning proposal with reassigned rider quotas and new zone boundaries.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Zone boundary definitions and customer address density data live in workspace files (JSON, YAML, CSV), while order volumes, rider assignments, transit times, and prep durations are only accessible through tool calls. Solving the task requires combining both sources.
- **Multi-Hop Reasoning**: The efficiency score computation requires a dependency chain of length ≥ 3: read sector density CSVs → compute per-zone weighted density via haversine overlap → combine with tool-sourced transit/prep/ratio metrics using policy-file weights → classify zones and apply adjustment formulas from the policy to derive new quotas and boundaries.
- **Conditional Constraints**: Zone classification and adjustments depend on policy-defined thresholds (efficiency cutoff, baseline minutes, penalty rates) stored in a YAML config file, with different formulas applied to INEFFICIENT vs EFFICIENT zones.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 6 (output_format=10, efficiency_scores=25, inefficient_identification=20, rider_quotas=20, zone_boundaries=15, response_summary=10).
- Source-access: clean. Solver was written using only `v3/prompt.md` and the public tool list from `Task_Env.get_assistant_tools()`. Step-6 escalation to read `env.py` was not triggered.
- Structural integrity: all four versions byte-identical for `env.py` and `prompt.md`; `data.py` differs only in the `SCALE` block. Row counts 100/200/400/800 (×1/2/4/8) and file counts 10/20/30/40 (+0/+N/+2N/+3N with N=10) match harness conventions.
- Prompt-step alignment: every deliverable in `prompt.md` (rezoning_proposal.csv with the eight named columns, sorted ascending; final response stating zone count, inefficient zones with names+IDs, and new total quota) is scored by `step`; `step` derives ground truth dynamically from `data.db` + policy YAML + sector CSVs (scale-invariant).
- Issues found and fixes: none. No edits to `v0/` were necessary.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from each `v_n/` and deleted the temporary solver under `/tmp/`.
