## Task Topic

Tracking illegal deforestation requires analyzing satellite imagery change detection, land ownership registries, permitted logging concession maps, and historical habitat conservation reports to produce a verified incident dossier for regulatory enforcement action.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Scale ratios follow the standard progression: rows scale at 1×/2×/4×/8× of the v0 base (80), and workspace files scale at base/base+N/base+2N/base+3N where N = 10 (the v0 base count). Scalable workspace files consist of field inspection JSON reports and species survey CSVs; three fixed configuration files (policy YAML, protected species JSON, severity matrix CSV) are produced at every scale and are not counted in the scaling parameter.

**Structural dimensions used:**

- **Information Scattering**: Task-critical data is split across database tables (satellite changes, ownership, concessions, conservation reports) and workspace files (field inspection verification status, species survey observations, policy thresholds, protected species list). No single source is sufficient; solving the task requires cross-referencing tools and files.
- **Conditional Constraints**: Incident classification depends on multi-table business rules: confidence thresholds, concession validity windows (date ranges + status), area tolerance percentages, conservation priority levels, biodiversity index floors, and protected species presence. All numeric thresholds reside in workspace configuration files.
- **Multi-Hop Reasoning**: Dependency chains of length ≥ 3 arise naturally, e.g., satellite change → field inspection verification → concession validity check → conservation report + species survey cross-reference → severity assignment from matrix.
- **Deliverable Constraints**: Output CSV has strict column order, sequential incident IDs assigned post-sort, a precise two-tier sort key (severity priority order then affected area descending), and specific formatting for the final response (counts and area to two decimal places).

## Harness Report

- v3 reward: 1.0 (total_score 100/100)
- Eval criteria: 7 (`dossier_file` 10pts, `incident_identification` 20pts, `severity_classification` 20pts, `violation_types` 15pts, `sort_order` 10pts, `enforcement_summary` 10pts, `response_accuracy` 15pts)
- Source-access: clean. Solver used only `v3/prompt.md` and `Task_Env.get_assistant_tools()` plus runtime artifacts (`data.db`, `workspace/`). No step-6 escalation needed.
- Structural integrity: all checks pass. `env.py` and `prompt.md` are byte-identical across v0/v1/v2/v3; `data.py` differs only in the `SCALE` block (rows 80/160/320/640, files 10/20/30/40 — ratios 1x/2x/4x/8x and +0/N/2N/3N with N=10).
- Prompt-step alignment: every prompt-required deliverable (dossier CSV, summary md, four-fact final response) is graded by at least one criterion; no hidden criteria; ground truth recomputed from `data.db` + workspace at evaluation time (scale-invariant).
- Prompt quality: no title/headings/bullets/code; tool names and source filenames absent; counts referenced as "all" / "every", not absolutes.
- Issues found and fixes: none. No edits to v0 were required.
- Final cleanup: removed `data.db`, `workspace/`, and `__pycache__/` from each `v_n/`; deleted scratch solver `/tmp/solve_deforestation_incident_verification.py`.
