## Task Topic

Analyze daily package volumes, driver shift capacities, real-time traffic patterns, and vehicle load capacities to dynamically partition delivery zones, generating an optimized daily zone assignment map for dispatch teams.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Package demand and traffic base data live in the database (accessible only through tools), while forecast factors, performance scores, congestion adjustments, vehicle availability, clustering parameters, and certification rules are spread across JSON, CSV, TXT, YAML, and Markdown workspace files spanning 5 formats.

- **Multi-Hop Reasoning**: The dependency chain includes: tool call (zone package summary) → workspace file (forecast factor) → tool call (traffic base congestion) → workspace file (traffic bulletin adjustment) → compute adjusted demand → workspace file (clustering config) → cluster formation → tool call (driver search) → workspace file (driver performance scores) → workspace file (vehicle availability) → tool call (vehicle specs) → final assignment.

- **Conditional Constraints**: Driver certification requirements depend on per-zone priority distributions checked against configurable thresholds (urgent percentage triggers expert requirement, express+urgent percentage triggers advanced requirement), with the thresholds stored in workspace configuration files.

## Harness Report

- v3 reward: 1.0 (100/100, all 7 criteria passed: csv_structure, zone_coverage, cluster_formation, driver_validity, vehicle_validity, dispatch_summary, response_metrics).
- Source-access: clean. The solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` on the first run; no escalation to step 6 was needed.
- Structural integrity: clean. `v0..v3/` each contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Issue found and fixed: `_compute_ground_truth` in `env.py` hard-coded `day_of_week="Tuesday"` when querying `traffic_patterns`. Although the current `data.py` happens to set `target_date` to a Tuesday so the bug was latent, this couples ground truth to a specific date. Fix: derive day-of-week from the configured `target_date` via `datetime.strptime(...).strftime("%A")`. Patched `v0/env.py` and re-propagated byte-identically to `v1/v2/v3`. Solver re-run yielded reward 1.0.
- Prompt and step alignment: every prompt deliverable (CSV with the named columns, JSON with the named fields, three response metrics) is checked by step; step does not enforce hidden criteria. No over-normalization or scale-dependent constants remain.
