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

- v3 reward: 1.0 (100/100) after fixes
- Eval criteria count: 6 (file_structure 10 pts, candidate_ids 20 pts, composite_scores 20 pts, recommendations 20 pts, ranking_order 15 pts, response_summary 15 pts)
- Source-access: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to read `env.py`/`data.py` was required.
- Structural integrity: passed. v0..v3 differ only in the `SCALE` block of `data.py`; `env.py` and `prompt.md` are byte-identical across versions.
- Section 4 (prompt formatting): prompt.md uses prose only — no headings, bullets, tool names, or absolute counts. No changes required.

Issues fixed in `v0/env.py` (propagated to v1..v3):

1. **Over-normalization in criterion 4** (`recommendations`): `step()` was applying `.upper()` to the submitted recommendation value before comparing, so lowercase `decommission`/`relocate` would pass even though `prompt.md` explicitly requires uppercase. Fixed by removing `.upper()`, leaving only `.strip()` to trim surrounding whitespace.

2. **Completeness gap in criterion 6** (`response_summary`): `step()` only checked whether the top-1 candidate's name or ID appeared in the response, but `prompt.md` requires "the station identifier and name of the top five candidates ranked by composite score." Fixed by checking that all top-5 candidates each have at least their station name or station ID mentioned in the response before awarding the 5 points.

Both fixes leave the reward at 1.0 for a correct solver and correctly penalise responses that violate `prompt.md`'s stated requirements.

## Hardening (M0 + M1 + M3 + M5)

Applied on top of the base `station_performance_review` env (pre-hardening); the SQLite data, the four workspace data-file types, prompt.md, and `step()`/`verify()` scoring logic are unchanged. M0 only adds *additive* methodology/policy prose to the two config docs written by data.py (details below) — none of the numbers the scorer reads are touched. env.py and prompt.md are byte-identical across v0..v3; only data.py's `SCALE` block differs.

Return-shape / tooling map (verified against every tool `return`):

- **M5 unbounded bulk export**: new tool `export_station_usage_history()` returns the full station master joined with every station's complete monthly ridership history as **one `json.dumps` string**, with no pagination and no arguments — **~16.5k tokens at v0** (66,130 chars; survivable but expensive) rising to **~132k tokens at v3** (529,353 chars; echoing it into context is fatal under a ~70k response budget — it must be consumed inside the programmatic sandbox and filtered before printing). The paginated `list_stations` and the per-station report tools remain available.
- **M1 JSON-encoded string parameter**: `list_stations` takes a single `filter` parameter typed as a **JSON-encoded string** (e.g. `filter='{"installed_on_or_before":"2024-10-01"}'`), parsed by `_parse_json_string_param`; passing an object/array/non-string, malformed JSON, or an unsupported filter key each returns a distinct `_error`.
- **M3 deep-nested Notion-style records**: `list_stations` returns a list envelope `{"object":"list","results":[...],"has_more":...,"next_cursor":...}` and must be cursor-paginated; each station record and both per-station reports expose their data through nested `properties` blocks (`title` / `select` / `number` / `date` / `relation`, plus `rollup` arrays of `cost_line` / `severity_bucket` objects), so scalar values sit two-to-four levels deep.
- **Return encodings** (no M2 mixing beyond the M5 export): `list_stations`, `get_maintenance_cost_report`, `get_complaint_severity_report` → **native Python dict** (Notion records); `export_station_usage_history` → **JSON-encoded string**. The `_envelope` (MCP content-block) helper is defined but unused, and no tool returns `key: value` text or a Python-repr string.
- **Error contract**: `_error(status, code, message)` → `{"status", "object": "error", "code", "message", "request_id"}` (with `request_id = "req_" + md5(...)[:12]`). Success payloads instead set `object` to `"list"` / `"station"` / `"maintenance_report"` / `"complaint_report"` and carry `results` / `properties` / `id`; a caller distinguishes an error by `object == "error"` together with the `code` / `message` / `request_id` fields (the shared key is only `object`, whose value disambiguates).
- **verify() passes with reward 1.0 at both v0 (86 tool calls: 1 export + 3 `list_stations` pages + 41 `get_maintenance_cost_report` + 41 `get_complaint_severity_report`) and v3 (707 tool calls: 1 export + 18 pages + 344 + 344 per-station reports)**, consuming the bulk export exactly once and in memory (`json.loads` on the single string, never re-emitted).

### M0 — de-proceduralized prompt

prompt.md is a goal + deliverable contract: it states the objective (produce a ranked list of underperforming stations for relocation/decommissioning), points at "the scoring and criteria documents stored alongside the data" as the authoritative spec, warns that "no single source is sufficient," and fixes the output CSV schema and response-summary requirements — with **no step-by-step route, no tool names, and no absolute counts**. The concrete methodology instead lives as *additive* prose in the config docs that data.py writes but that `step()`/`verify()` never read: the `formulas` block of `scoring_config.yaml` (per-component + composite pseudocode) and the `decision_rules` / `description` fields of `relocation_criteria.json`. The scorer consumes only `weights` / `normalization` / `thresholds`, `eligibility.max_install_date`, and `output_format.{file_name,columns}`.

Completeness audit — every scored criterion remains fully specified by the de-proceduralized prompt plus the workspace docs and tools:

| `step()` criterion (pts) | Where the requirement / data comes from |
|---|---|
| file_structure (10) | prompt.md (exact column list + filename) and `relocation_criteria.json` → `output_format.file_name` / `columns` |
| candidate_ids (20) | eligibility cutoff `relocation_criteria.json` → `eligibility.max_install_date`; candidate threshold `scoring_config.yaml` → `thresholds.candidate_score_min`; station set via `list_stations` (JSON-string `installed_on_or_before` filter, cursor-paginated) |
| composite_scores (20) | weights / caps / formulas in `scoring_config.yaml`; component inputs spread across `export_station_usage_history` (usage decline), `get_maintenance_cost_report` (cost) + `maintenance_notes_*.yaml` (downtime hours), `get_complaint_severity_report` (weighted severity) + `complaint_summary_*.txt` (unresolved count), and `poi_survey_*.json` (POI count within 500 m) |
| recommendations (20) | decision rule `scoring_config.yaml` → `thresholds.critical_poi_count` & `severe_usage_decline_pct` (narrated in `relocation_criteria.json` → `decision_rules`); inputs = POI count + usage-decline % |
| ranking_order (15) | prompt.md ("descending composite score, ties broken by station identifier ascending") and `relocation_criteria.json` → `output_format.sort_by` / `tie_breaking` |
| response_summary (15) | prompt.md (total candidate count, decommission-vs-relocate breakdown, and the id + name of the top five candidates) |
