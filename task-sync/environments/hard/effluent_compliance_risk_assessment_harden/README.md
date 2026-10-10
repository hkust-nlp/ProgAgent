## Task Topic

Identifying industrial facilities at risk of non-compliance requires cross-referencing real-time effluent sensor data, permitted discharge limits, historical inspection violation reports, and scheduled maintenance logs to generate a prioritized list for field inspector dispatch.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 10                  |
| v1      | 60            | 20                  |
| v2      | 120           | 30                  |
| v3      | 240           | 40                  |

Structural dimensions used:

- **Information Scattering**: Critical risk-scoring parameters (environmental sensitivity zones, lab-verified discharge values, corrective action statuses) live exclusively in workspace files across JSON, CSV, YAML, Markdown, and plain-text formats, while facility details, sensor readings, permit limits, violation history, and maintenance logs are only accessible through tool calls. Both sources must be combined to compute the composite risk score.
- **Conditional Constraints**: Exceedance computation depends on comparing effective pollutant concentrations (the higher of sensor and lab values) against permit limits, weighted by hazard-tier multipliers from a reference file. Violation scoring applies recency-based weights and an unresolved multiplier from a YAML configuration. Zone multipliers from site assessments modify the final score.
- **Multi-Hop Reasoning**: Computing a single facility's risk score requires: tool call for sensor readings → workspace lab files to determine effective value → tool call for permit limits → workspace pollutant tiers for hazard multiplier → tool call for violations → workspace config for recency weights → tool call for maintenance → workspace corrective action files → workspace site assessments for zone multiplier (chain length ≥ 5).
- **Deliverable Constraints**: Output CSV must have exact column names, two-decimal precision for risk scores, specific sort order with tie-breaking rule, and rank column starting from one.

## Harness Report

- v3 solver reward: 1.0 (100/100).
- Eval criteria count: 8 (csv_structure 10, facility_set 15, risk_scores 25, ranking 15, risk_categories 10, dispatch_urgency 10, primary_concern 10, response_summary 5).
- Source-access: clean run. Section 2 escalation to step 6 (opening env.py) was needed once to confirm that the violation `resolved` flag is the boolean DB column rather than a status string; this matched the prompt's "unresolved" wording, so no env/prompt change was required.
- Structural integrity: passed (only `data.py` differs across v0..v3, only in the SCALE block).
- Prompt quality: passed (no headings, no bullets, scale-invariant wording, explicit column spec, no tool/file leakage).
- Step quality: passed (partial-credit scoring is consistent across v0..v3, no hard-coded counts, ground truth derived live from data.db + workspace).
- Issues found and fixes: none required.
- Cleanup: removed runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) from every `v_n/` and the temporary solver under `/tmp/`.


## Hardening (M0 + M1 + M3 + M5)

Applied on top of `environments/standard/effluent_compliance_risk_assessment`; `step()` and `_compute_ground_truth()` are byte-identical to SOURCE, and the `data.py` change is additive only (a fixed, non-scaling methodology document; per-version `SCALE` blocks preserved).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 9 formula-narrating paragraphs to 4: scenario/goal, a pointer to the assessment methodology document + configuration/reference files as the authoritative spec, the verbatim deliverable contract (exact column list and order, "every Active facility exactly once", two-decimal risk score, sort key, tie-breaker, rank semantics — the round-to-two-decimals sentence was joined into the contract paragraph), and the final-response summary requirement. `data.py` gains a new fixed workspace document `assessment_methodology.md` carrying every rule that previously lived only in the prompt: scope (Active facilities), all five component formulas (lab-override rule, most-restrictive permit rule, skip unpermitted pollutants, recency buckets, unresolved multiplier, Overdue maintenance/corrective-action counts, >10% lab-discrepancy rule), composite weighting + zone multiplier + rounding, the CRITICAL/HIGH/MODERATE/LOW and IMMEDIATE/PRIORITY/ROUTINE/MONITOR mappings (LOW and MONITOR appear nowhere in the config files), and the exact primary-concern labels.
- **M1 JSON-encoded string filters**: `get_sensor_readings` takes `filter` with supported properties `pollutant_code`, `sensor_status`; `get_violation_records` takes `filter` with `resolved` (boolean), `min_severity` (integer 1-5), `violation_type`. Both params are typed `Any = None`; validation is layered, one error per call: dict body → `invalid_request` ("serialize it to a JSON string"), malformed JSON → `invalid_json` with line/column/char, non-object → `invalid_request`, unsupported key → supported-property list, wrong-typed value → `body.filter.<key> should be ..., instead was '<shape>'.`
- **M3 deep-nested records**: `list_facilities` returns `{"object": "list", "results": [...], "has_more", "next_cursor"}` (cursor pagination, no total/total_pages) and `get_facility_details` returns a nested `{"object": "facility", "id", "properties": {...}}` record. Traps kept: display name at `properties.Name.title[0].plain_text`, categorical values (Sector/Region/Operating Status) at `properties.<K>.select.name`, numbers at `properties.<K>.number`.
- **M5 unbounded bulk export**: new tool `export_compliance_snapshot()` returns every sensor reading joined with facility name/region/operating status and the applicable (most restrictive) permitted daily maximum as ONE JSON string, no pagination. Measured `len(raw)//4`: ~19.2k tokens at v0 (survivable but expensive), ~135k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and filtered before printing). It is genuinely sufficient for the core exceedance-filtering step; all paginated/per-entity tools remain available.

Per-tool return-shape map:
| tool | success shape | error shape |
|---|---|---|
| `list_facilities` | native dict, M3 nested list w/ cursor | `_error` dict |
| `get_facility_details` | native dict, M3 nested record | `_error` dict |
| `get_sensor_readings` | native dict `{facility_id, readings}` (M1 filter param) | `_error` dict |
| `get_permit_limits` | native dict `{facility_id, permits}` | `_error` dict |
| `get_violation_records` | native dict `{facility_id, violations}` (M1 filter param) | `_error` dict |
| `get_maintenance_status` | native dict `{facility_id, maintenance_logs}` | `_error` dict |
| `export_compliance_snapshot` | ONE JSON string `{record_count, records}` (M5) | — (parameterless) |

Error contract: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` — sharing no keys with any success shape. Not-found → `404 object_not_found` ("Could not find facility with ID: ..."), bad input → `400 validation_error` / `400 invalid_json` / `400 invalid_request`. Unknown facility IDs now 404 on every per-facility tool.

Completeness audit (step() criterion → info source after M0):
| criterion | source |
|---|---|
| csv_structure | prompt (verbatim contract); also dispatch_rules.json `output_format` |
| facility_set | prompt ("Every Active facility must appear exactly once") + assessment_methodology.md Scope |
| risk_scores | assessment_methodology.md (components 1-5, composite, rounding) + risk_scoring_config.yaml (weights, recency, unresolved multiplier, reference date) + pollutant_hazard_tiers.csv + site_assessment*.json + lab_analysis*.csv + corrective_actions* files |
| ranking | prompt (verbatim sort/tie-break/rank contract) |
| risk_categories | assessment_methodology.md (mapping incl. LOW) + risk_scoring_config.yaml thresholds |
| dispatch_urgency | assessment_methodology.md (mapping incl. MONITOR) + risk_scoring_config.yaml dispatch thresholds |
| primary_concern | assessment_methodology.md (exact labels: Exceedance, Violations, Maintenance, Lab Discrepancy, Corrective Actions) |
| response_summary | prompt (final-response paragraph) |

verify() results (hardened surface: M3 cursor walk + nested-property parsing, M5 export consumed once in memory, M1 JSON-string `resolved` filters):
- v0: reward 1.0 (100/100), 88 tool calls.
- v3: reward 1.0 (100/100), 601 tool calls.
- Negative-path smoke tests all pass: malformed M1 JSON → `invalid_json` with line/column/char; dict-instead-of-string → `invalid_request`; unsupported filter key / wrong-typed values → layered `validation_error` messages; nonexistent facility → 404 `object_not_found`; undefined facility_id / non-integer page → 400 `validation_error`.
