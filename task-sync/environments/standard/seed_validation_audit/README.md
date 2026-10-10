## Task Topic

Identify potential seeding errors by cross-referencing player regional ranking tables, historical head-to-head match records, qualifier stage performance metrics, and current bracket progression to output a flagged match list for manual review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task exhibits the following structural dimensions:

- **Conditional Constraints**: Flagging rules depend on seed tiers, head-to-head thresholds, and qualifier performance thresholds drawn from a workspace configuration file. Each flag type combines conditions across multiple data columns and sources.
- **Deliverable Constraints**: The output CSV requires exact column ordering, specific flag-type identifiers, severity values restricted to high/medium/low, and a precise three-key sort order (severity descending, round ascending, match_id ascending).
- **Information Scattering**: Power-index data lives in regional CSV files, form-trend data in qualifier-detail JSON files, surface-specific H2H records in TXT files, while overall H2H totals and qualifier round results are only accessible through tools. No single source suffices.
- **Multi-Hop Reasoning**: The H2H surface dominance check requires reading tournament surface from config, looking up surface-specific records from workspace files, retrieving overall H2H from the tool, and comparing against thresholds from the rules config (chain length 4).

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 6 (file_format, rank_seed_mismatch_flags, h2h_surface_dominance_flags, qualifier_form_concern_flags, severity_accuracy, sort_order)
- Source-access: clean. Solver succeeded using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; `env.py` was opened only for Section 3 quality review (per harness flow), not for solver debugging.
- Issues found and fixes: none. Structural integrity, byte-for-byte invariance across v0..v3 (only `SCALE` block differs), prompt-step alignment, and prompt formatting all passed without modification. Initial solver attempt scored 75/100 due to a solver-side bug (unwrapping the `{"record": {...}}` envelope returned by `get_head_to_head`); fixing the solver — not the env — produced reward 1.0.
