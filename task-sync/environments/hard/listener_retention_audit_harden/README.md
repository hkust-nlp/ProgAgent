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

## Hardening (M5 + M2)

Applied on top of `environments/standard/listener_retention_audit`; data.py, prompt.md, and step() scoring are unchanged.

- **M5 unbounded bulk export**: new tool `export_retention_overview()` returns the entire episode-level retention dataset as one JSON string with no pagination — ~16k tokens at v0 (survivable but expensive) up to ~131k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and filtered before printing). Paginated / per-entity tools remain available.
- **M2 mixed return shapes**: `list_podcasts` stays a native dict; `get_episodes` / `get_competitor_shows` return JSON-encoded strings; `get_episode_retention` returns plain `key: value` text; `get_episode_ad_placements` returns a Python-repr string; `get_podcast_demographics` returns an MCP-style envelope. Errors are `{"status", "object": "error", "code", "message", "request_id"}`.
- verify() passes with reward 1.0 at v0 and v3 scales (598 tool calls at v3; consumes the bulk export once, in memory).

### M0 — de-proceduralized prompt (added 2026-07-02)

`prompt.md` rewritten from 7 formula-narrating paragraphs to 4: scenario/goal, a pointer to the audit methodology document + configuration files as the authoritative spec, the verbatim deliverable contract (columns, two-decimal precision, sort key, tie-breaker, flagged_episode_count definition — kept unchanged per review), and the final-response summary requirement. `data.py` change (additive only): new `audit_methodology.md` containing all metric definitions previously stated only in the prompt — flagging computation, competitor gap, demographic shift, ad-revenue impact formula, priority-score normalization/weighting, and revision-segment selection + "EpN:SegM-type" formatting.

Completeness audit (step() criterion -> info source):
| criterion | source |
|---|---|
| file_format | prompt (verbatim contract); also scoring_rubric.json output_format |
| flagged_podcasts | audit_methodology.md (flagging) + retention_config.yaml threshold |
| retention_values | audit_methodology.md (drop formula) |
| priority_scores | audit_methodology.md (normalization + weighting) + scoring_rubric.json bounds + retention_config.yaml weights |
| sorting | prompt (verbatim contract) |
| revision_segments | audit_methodology.md (selection + format) + retention_config.yaml max segments |
| demographic_flags | audit_methodology.md (shift computation) + retention_config.yaml threshold + demographic_baseline.csv |
v3 verify (unchanged) re-run after M0: reward 1.0.
