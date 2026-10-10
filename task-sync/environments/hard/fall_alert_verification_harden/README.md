## Task Topic

Validate equipment-generated fall alerts by fusing motion sensor data, baseline activity profiles, scheduled caregiver visit logs, and audio event markers to filter false positives, producing a verified incident report for emergency contacts.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Structural dimensions used:

- **Conditional Constraints**: verification depends on cross-referencing acceleration against per-room baselines multiplied by a deviation factor, checking caregiver visit overlap with exempt-type filtering, and audio event confirmation with confidence thresholds — rules spanning five database tables and four workspace configuration files.
- **Information Scattering**: acceleration thresholds live in `validation_rules.json`, exempt caregiver types in `caregiver_exemptions.txt`, severity tiers in `severity_thresholds.csv`, device-to-room mapping in `device_registry.csv`, baseline profiles in per-zone JSON files, and emergency contacts in a separate JSON file. No single source is sufficient.
- **Multi-Hop Reasoning**: alert → device_id → device_registry.csv → room_number + zone → baseline JSON → compare peak acceleration → caregiver visits tool (by resident + date) → audio events tool (by room + window) → apply rules → severity assignment.
- **Deliverable Constraints**: output CSV with eleven named columns in fixed order, acceleration rounded to four decimals, three-token contributing-factors string with exact tokens, rows sorted by severity rank ascending then timestamp ascending, false positives assigned rank five.

## Harness Report

- v3 reward: 1.0 (100/100). v3 scale: 138 pending alerts reviewed; 58 verified, 80 false positives.
- Eval criteria (8): file_format (10), alerts_coverage (10), verification_accuracy (20), severity_accuracy (15), sort_order (10), contributing_factors (10), response_summary (15), db_dispositions_recorded (10). All passed.
- Source-access escalation: not needed. Solver written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()` plus workspace runtime files.
- Section 1: structural diffs clean. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the SCALE block (rows 30/60/120/240, workspace files 8/16/24/32). No stale artifacts found.
- Section 2: solver achieved reward 1.0 on first run after correcting field names in the `export_alert_evidence` response (`alert_status`, `alert_timestamp`, `triggering_device_id`, `acceleration_x_g/y_g/z_g`, `detected_at` vs the names expected from `get_motion_readings`/`get_audio_events` doc strings). No edits to any source file were required.
- Section 3: all 8 step() criteria correspond to explicit prompt.md requirements; no hidden criteria. Minor noted gap: `peak_acceleration`, `baseline_max`, and emergency-contact field *values* are not compared against ground truth (only column existence is checked via C1). Does not affect correctness or the 1.0 reward.
- Section 4: prompt.md passes all formatting and content checks (no title, no bold headers, no lists, no code, no tool names, scale-invariant wording throughout).
- Runtime artifacts (data.db, workspace/, __pycache__) removed from all version directories; solver script removed.

## Hardening (M0 + M4 + M5)

Applied on top of `environments/standard/fall_alert_verification`. Ground truth (`_compute_ground_truth`), business logic, and data generation are unchanged; `data.py` gained one additive fixed policy document (M0 rule 4), and `step()` gained one DB-state criterion (sanctioned M4 exception — SOURCE had no write tool).

- **M0 — de-proceduralized prompt**: `prompt.md` rewritten from 6 route-narrating paragraphs to 5: scenario/goal, a pointer to the verification methodology document + configuration files as the authoritative spec, the disposition-logging requirement, the verbatim deliverable contract (columns, four-decimal precision, exact tokens, sort keys, tie-breaker — unchanged word for word), and the final-response summary requirement. All formulas and decision rules previously stated only in the prompt (Euclidean-norm peak, greater-of threshold, caregiver presence window semantics, audio confirmation, verification decision, severity-tier walk, registry-based room identification) moved into a new fixed workspace document `verification_methodology.md` written by `data.py` (additive only; per-version `data.py` files differ from each other only in the `SCALE` block).
- **M4 — nested write payload**: new tool `create_alert_resolution` takes a single nested `payload` (`parent` = `{"type": "alert_record", "alert_id": "<string>"}` + `properties` with required `Disposition` and `Severity` select properties, optional `Note` rich_text). Validation is layered, one Notion-style error per call (`body.parent.alert_id should be a non-empty string, instead was 'undefined'.` etc.), then business checks (404 unknown alert, 400 non-pending). The write is an `INSERT OR REPLACE` into a new `alert_resolutions` register table (created on first write; `fall_alerts` is never touched, so ground truth is unaffected). Converted deliverable: dispositions are recorded via the write API; `step()` gained `db_dispositions_recorded` (10 pts) with minimal rebalance (`alerts_coverage` 15→10, `verification_accuracy` 25→20; all other criteria and weights unchanged; total stays 100).
- **M5 — unbounded bulk export**: new parameterless tool `export_alert_evidence` returns the complete joined dataset (all alerts joined with resident profiles, plus all motion readings, caregiver visits, and audio events) as ONE JSON string, no pagination. Measured `len(raw)//4`: ~15.4k tokens at v0 (survivable but expensive), ~124.5k tokens at v3 (echoing it natively into context is fatal; it must be consumed inside the programmatic sandbox and filtered before printing). All paginated/per-entity tools remain available as the safe alternative.

Per-tool return-shape map:

| tool | success shape | notes |
|---|---|---|
| list_pending_alerts | native dict | validates page/page_size |
| get_alert_detail | native dict `{"alert": {...}}` | wrapped to avoid key overlap with errors |
| get_motion_readings | native dict | unchanged |
| get_resident_info | native dict `{"resident": {...}}` | wrapped |
| get_caregiver_visits | native dict | unchanged |
| get_audio_events | native dict | unchanged |
| export_alert_evidence | JSON-encoded string | M5 bulk export |
| create_alert_resolution | deep-echo dict (`object`/`id`/`parent`/`properties`/`created`) | M4 write |

Error contract: tools never raise; every failure returns `{"status", "object": "error", "code", "message", "request_id"}` (400 `validation_error` / `invalid_json`, 404 `object_not_found`). Success and error responses share no keys (query tools); the M4 deep echo follows the spec template and is distinguished by `object` value and disjoint remaining keys.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| file_format (10) | prompt (verbatim contract); `output_specification.md` |
| alerts_coverage (10) | prompt ("one row per pending alert"); `output_specification.md` scope |
| verification_accuracy (20) | `verification_methodology.md` (threshold, caregiver, audio, decision) + `validation_rules.json` + `caregiver_exemptions.txt` |
| severity_accuracy (15) | `verification_methodology.md` (severity walk) + `severity_thresholds.csv` |
| sort_order (10) | prompt (verbatim contract); `output_specification.md` |
| contributing_factors (10) | prompt (verbatim contract, exact tokens); `output_specification.md` |
| response_summary (15) | prompt final paragraph |
| db_dispositions_recorded (10) | prompt paragraph 3 + `verification_methodology.md` (disposition logging) |

Verify results: v3 reward 1.0 (705 tool calls, export ~124,481 tokens); v0 reward 1.0 (68 tool calls, export ~15,354 tokens; ≥15 call floor met). Negative-path smoke tests passed: M4 layered messages fire one at a time (undefined body → string body → missing parent → wrong parent.type → non-string alert_id → missing properties → missing Disposition → invalid select name → missing Severity → bad Note), 404 on nonexistent/non-numeric alert ids, 400 on non-pending alerts, and 400/404 error dicts on all query tools for bad types and unknown ids.
