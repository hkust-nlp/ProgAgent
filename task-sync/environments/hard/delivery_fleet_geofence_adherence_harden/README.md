## Task Topic

Monitor delivery fleet adherence to customer site geofence policies. Correlate GPS location pings, customer contract service-level agreements, driver shift logs, and geofence violation incident reports to generate a weekly compliance scorecard per depot with flagged drivers for retraining.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 15             | 10                  |
| v1      | 30             | 20                  |
| v2      | 60             | 30                  |
| v3      | 120            | 40                  |

Scaling ratios: rows_per_table follows 1×, 2×, 4×, 8× of the v0 base (15). num_workspace_files follows base, base+N, base+2N, base+3N where N = 10 (the v0 base).

The task exercises the following structural dimensions:

- **Information Scattering**: Scoring parameters (severity weights, SLA tier multipliers, retraining thresholds) live in workspace configuration files (JSON/YAML), while violation records, driver rosters, and customer contracts are only accessible through tool calls. Incident adjustment factors are spread across multiple workspace CSV files. Solving the task requires combining data from both sources.
- **Multi-Hop Reasoning**: Computing a single violation's penalty requires a chain of at least four lookups: violation record (tool) → customer_id → contract/SLA tier (tool) → tier weight multiplier (workspace YAML) → adjustment factor (workspace CSV) → final penalty. SLA breach detection adds another hop checking per-customer violation counts against contractual limits.
- **Deliverable Constraints**: Output CSVs have exact column names and ordering, numeric precision (two decimal places), specific sort keys with tie-breakers, and prescribed string values for flag reasons and recommended actions.

## Harness Report

- v3 reward: 1.0 (100/100), confirmed by independent solver.
- Eval criteria: 6 (`scorecard_structure` 15 pts, `scorecard_completeness` 15 pts, `scorecard_accuracy` 25 pts, `flagged_structure` 10 pts, `flagged_accuracy` 25 pts, `response_summary` 10 pts).

**Section 1 — Structural integrity:** passes after cleanup. Top-level contains only `README.md` and `v0..v3/`. `env.py` and `prompt.md` are byte-identical across all four versions. `data.py` differs only in the `SCALE` block (rows_per_table: 15/30/60/120 matching ×1/2/4/8; num_workspace_files: 10/20/30/40 matching +0/N/2N/3N). Issue found: `v3/` contained stale runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) from the generation run; all were removed.

**Section 2 — Solvability at v3:** solver written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` or `data.py` required. First run achieved `reward = 1.0` with all six criteria passing.

**Section 3 — Env quality:** passes. Ground truth derived from live `data.db` and workspace configs — no hardcoded counts. All six criteria align with prompt requirements. `risk_rating` uses exact-match comparison (case-insensitive, but GT values are already lowercase). `compliance_score` and `weighted_severity_score` use ±0.05 tolerance, appropriate for "round to two decimal places." Design note: sort order for both output CSVs (scorecard: depot_id asc; flagged: weighted_severity_score desc + driver_id asc) is stated in the prompt but not verified by `step`. This is a minor gap — the solver produces correct order and reward is unaffected.

**Section 4 — Prompt quality:** passes. No top heading, no bold headers, no bullet/numbered lists for deliverables. Computation logic deferred to external methodology docs. No tool names or internal source-data filenames mentioned. All output filenames and column orders are explicitly stated. Wording is scale-invariant ("every depot in the network", "every driver across the entire fleet").

**Issues found and fixed:** stale runtime artifacts in `v3/` removed (Section 1). No edits to any source file were necessary.

## Hardening (M0 + M1 + M3 + M5)

Applied on top of `environments/standard/delivery_fleet_geofence_adherence`. Task semantics, data generation, ground truth, and `step()` scoring are unchanged; `prompt.md` was de-proceduralized (M0) and `data.py` additively gained a `compliance_methodology.md` document. The reskin only reshapes the tool surface and the prompt.

- **M5 unbounded bulk export**: new tool `export_fleet_activity()` returns the entire reporting-week dataset — the full depot directory, the full driver roster, every geofence violation joined with its driver / depot / active-contract terms, and the week's complete GPS ping trace — as one JSON string with no pagination: ~20k tokens at v0 (survivable but expensive) up to ~165k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and filtered before printing). The paginated per-entity tools (`list_depots`, `get_depot_drivers`, `query_violations`, `get_customer_contract`, `get_driver_shift_log`) remain available.
- **M1 JSON-encoded string filter**: `get_depot_drivers` and `query_violations` take their optional `filter` as a single JSON-encoded string parameter (e.g. `filter='{"status":"active"}'`, `filter='{"severity":"critical","resolved":false}'`), parsed by `_parse_json_string_param`; passing an object/non-string, malformed JSON, or an unsupported key returns a validation error rather than the object being accepted directly.
- **M3 nested Notion-style records**: `list_depots`, `get_depot_drivers`, `query_violations`, and `get_driver_shift_log` return cursor-paginated `{"object":"list","results":[...],"has_more":...,"next_cursor":...}` lists; `get_customer_contract` returns a single record. Every record is a `{"object","id","properties":{...}}` shape whose property values are title / select / number / relation / checkbox / date / rich_text blocks that must be unwrapped to read a plain value.
- **Return-shape / error contract**: all list and detail tools return **native dicts**; `export_fleet_activity` is the lone tool returning a **JSON-encoded string** (the M5 export). No MCP envelope, `key: value`, or Python-repr encodings are used (M2 is not applied), and there is no write tool (M4 is not applied). Errors are `{"status","object":"error","code","message","request_id"}`; success and error responses share only the `object` key (an entity kind such as `"list"`/`"depot"` vs. the literal `"error"`), no other keys.
- verify() passes with reward 1.0 at v0 (54 tool calls) and v3 (395 tool calls); it walks the nested records following `has_more`/`next_cursor`, builds JSON-string filters, and consumes the bulk export exactly once, in memory.

### M0 — de-proceduralized prompt

`prompt.md` states only the goal (a weekly per-depot compliance audit for 2025-01-06 … 2025-01-12) and the deliverable contract (the two output CSV filenames, their exact column names and order, sort keys, rounding, and the three figures to state in the final response). It names no tools and no internal source filenames; all computation rules are deferred to `compliance_methodology.md` (added additively by `data.py`) together with the config files `scoring_weights.json`, `sla_tiers.yaml`, and `retraining_policy.json`, plus the `incident_context_*.csv` adjustment/dispute records. Every `step()` criterion remains fully specified across those sources:

| `step()` criterion | Pts | Specification / data source |
| --- | --- | --- |
| `scorecard_structure` | 15 | prompt.md — exact `compliance_scorecard.csv` column names + order |
| `scorecard_completeness` | 15 | prompt.md ("every depot in the network"); depot set from `list_depots` |
| `scorecard_accuracy` | 25 | `compliance_methodology.md` + `scoring_weights.json` + `sla_tiers.yaml` (penalty, SLA breach, compliance score, risk thresholds) + `incident_context_*.csv` (adjustment factor / dispute); row data via `get_depot_drivers`, `query_violations`, `get_customer_contract` |
| `flagged_structure` | 10 | prompt.md — exact `flagged_drivers_report.csv` column names + order |
| `flagged_accuracy` | 25 | `retraining_policy.json` + `compliance_methodology.md` (flag conditions, reason precedence, action bands, weighted-severity formula); row data via the query tools |
| `response_summary` | 10 | prompt.md (state fleet-average compliance score, per-rating depot counts, total flagged); values computed from the sources above |
