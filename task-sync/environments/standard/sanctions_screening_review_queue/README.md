## Task Topic

Screen new customer registrations against sanctions lists by checking identity attributes against OFAC, EU, and UN consolidated records, tracing cross-border payment intermediaries, and reviewing ultimate-beneficial-ownership structures to flag positive matches for compliance review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 40            | 8                   |
| v1      | 80            | 16                  |
| v2      | 160           | 24                  |
| v3      | 320           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8× progression; workspace files follow base/base+N/base+2N/base+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Customer aliases exist only in workspace JSON files (not in the database). PEP status of beneficial owners is recorded exclusively in workspace YAML declaration files. Payment purposes and beneficiary details appear only in workspace CSV transaction logs. Screening thresholds and scoring weights live in a workspace configuration file. The agent must combine tool-returned database records with file-sourced attributes to complete the screening.

- **Multi-Hop Reasoning**: The task requires dependency chains of length 3 or more. For example: read UBO declaration YAML to find a PEP beneficial owner → retrieve that owner's nationality from the UBO database record via tool → look up the nationality's country risk tier from the workspace CSV → determine whether the PEP-in-high-risk-country flag applies. Similarly: read customer alias from workspace JSON → search alias against sanctions lists via tool → record the matched sanctions entry ID and raise the alias_match flag.

- **Conditional Constraints**: Flagging decisions depend on multiple configurable thresholds read from workspace files: name similarity threshold, UBO ownership percentage floor for screening eligibility, country risk tier cutoff, risk score weight per flag type, and priority classification breakpoints. All must be applied exactly as configured.

- **Deliverable Constraints**: The output CSV requires exact column names, semicolon-separated flag reasons in alphabetical order, semicolon-separated sanctions IDs in ascending order, specific sort order (risk score descending, customer ID ascending for ties), and boolean formatting for the flagged column.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (file_format=10, customer_completeness=15, flagged_accuracy=25, risk_score_accuracy=15, flag_reasons=15, sanctions_ids=10, review_priority=10)
- Section 1 structural integrity: passed (env.py and prompt.md byte-identical across v0..v3; data.py differs only in SCALE).
- Section 2 solvability: solver achieved reward=1.0 at v3 scale using only `prompt.md` plus `Task_Env.get_assistant_tools()` plus runtime artifacts (`data.db`, `workspace/`). No edits to env.py or prompt.md were required. Initial sub-1.0 reward was traced to solver bugs (mis-keyed UBO field, wrong PEP ownership-pct gating, missing default tier 2 for unknown countries) — all fixed in the solver, not the env.
- Section 3 quality: prompt-step alignment is consistent; step derives ground truth dynamically from data.db / workspace and contains no hard-coded scale values.
- Section 4 prompt.md quality: prose-only, no bold headers, no bullet lists for deliverables, scale-invariant wording ("all pending customers", "every beneficial owner"), no tool names leaked.
- Issues fixed: none in env.py / prompt.md / data.py — task held together byte-for-byte across versions.
