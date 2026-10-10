## Task Topic

Identify podcasts with declining listener retention for content strategy review. Analyze episode-level drop-off rates, listener demographic shifts, ad placement logs, and competitor show performance to flag series with >15% retention drop, outputting a priority list with episode segments for revision.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

The task uses the following structural dimensions:

- **Information Scattering**: Episode-level retention metrics and demographic data are accessible only through tool calls, while segment-level drop-off data (listener counts per segment, content types, segment topics) lives exclusively in workspace CSV batch files. Configuration parameters—thresholds, scoring weights, normalization bounds, genre-specific ad-rate multipliers, and demographic baselines—are spread across four different workspace files in YAML, JSON, and CSV formats. Solving the task requires combining all of these sources.
- **Multi-Hop Reasoning**: The dependency chain runs at least four hops deep: list podcasts → retrieve episodes per period → fetch per-episode retention → compute podcast-level retention drop → cross-reference workspace segment files to identify worst-performing segments. Computing the priority score adds further hops through competitor benchmarks, demographic comparisons against genre baselines, and ad-revenue impact estimation from placement data combined with genre multipliers.
- **Conditional Constraints**: Whether a podcast is flagged depends on a configurable retention-drop threshold read from a YAML file. The demographic-shift flag is determined by comparing actual listener demographics against genre-specific baselines from a CSV file, with the threshold also drawn from configuration. Ad-revenue impact requires combining per-episode ad placements (from tool calls) with genre multipliers (from a JSON config file).
- **Deliverable Constraints**: The output CSV must have exactly seven columns in a prescribed order, with retention drop and priority score rounded to exactly two decimal places. Rows must be sorted by priority score descending with retention drop as tie-breaker. Segment identifiers follow a strict "EpN:SegM-content_type" format joined by "; ".

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 — `file_format` (10), `flagged_podcasts` (20), `retention_values` (15), `priority_scores` (15), `sorting` (10), `revision_segments` (15), `demographic_flags` (15).
- Source-access: clean. Solver was written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` output and the workspace config files; reward reached 1.0 on first successful run, no step-6 escalation needed.
- Section 1 structural integrity: passed. `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 50/100/200/400, files 10/20/30/40).
- Section 3 prompt-step alignment: passed. All seven criteria map to explicit prompt requirements; ground truth recomputed dynamically from `data.db` and workspace, no hard-coded scale assumptions; tolerances on retention/priority/segments are reasonable for floating-point variation.
- Section 4 prompt.md quality: passed. No headings/bold/lists for deliverables, no tool or source-filename leaks, scale-invariant wording ("every podcast", "all such segments"), explicit column names and formatting rules.
- Issues found and fixed: none.
- Blockers: none.
