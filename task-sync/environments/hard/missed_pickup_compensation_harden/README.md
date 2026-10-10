## Task Topic

Identify missed pickups requiring compensation by analyzing GPS truck stop locations, resident service request tickets, bin lift arm sensor activation logs, and contractual service level agreements to output a validated refund list with calculated credit amounts.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10 (the v0 base).

### Structural Dimensions

- **Conditional Constraints**: Eligibility depends on multiple cross-referenced conditions — the scheduled date must match the zone's pickup days, the date must not be excused (exception code + advance notice from route logs), and GPS proximity/duration thresholds plus bin-lift success from the SLA configuration determine miss classification. Repeat-miss status adds another conditional multiplier.
- **Information Scattering**: SLA thresholds, compensation rates, and excused-date flags live in workspace files (YAML, CSV, JSON, and CSV route logs); service request details, resident coordinates, GPS stops, and bin-lift records are only reachable via tool calls. Both sources are required for every refund determination.
- **Multi-Hop Reasoning**: Each validated refund requires a chain of at least four hops: service request → resident info → zone config (workspace) → GPS stops (tool) → bin lifts (tool) → rate lookup (workspace) → prior-claims check (tool) → final credit computation.

## Harness Report

- v3 reward: **1.0** (110 / 110)
- Number of eval criteria: **8** — csv_exists (10 pts), csv_columns (10 pts), correct_request_ids (25 pts), correct_miss_types (15 pts), correct_credits (20 pts), sort_order (10 pts), action_summary (10 pts), db_credits_recorded (10 pts)
- Verified by: independent solver written from `prompt.md` + `get_assistant_tools()` only (no `env.py` / `data.py` read during solve); all 8 criteria passed on first submission.
- Issues found and fixed: **none**. Structural integrity (§1), solvability (§2), env quality (§3), and prompt quality (§4) all passed without modification.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/missed_pickup_compensation`. `data.py` is byte-identical to SOURCE in all four versions (no additive policy docs were needed — `compensation_policy.md` already specifies every business rule); `_compute_ground_truth()` and all seven original `step()` criteria are unchanged. One DB-state criterion was added under the M4 no-write-tool exception (see below).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 route-narrating paragraphs to 5: scenario/goal, a pointer to the policy and configuration documents as the authoritative specification, the credit-memo recording requirement (M4), and the verbatim deliverable contract + final-response paragraphs (including the exact `full_miss`/`partial_miss` strings, column list/order, two-decimal formatting, and sort key). All per-file navigation ("A JSON file describes… A YAML file spells out…"), sequencing scaffolds, and business-rule restatements (pickup-day eligibility, excused exceptions, GPS/bin-lift miss classification, credit formula, 30-day repeat-miss window) were deleted after confirming each rule is stated in `compensation_policy.md` (with thresholds in `sla_terms.yaml`, rates in `compensation_rates.csv`, trucks/pickup days in `zone_boundaries.json`, exceptions in `route_log_*.csv`).
- **M1 JSON-string parameter**: `search_service_requests` collapses `request_type`/`status` into a single `filter` parameter that must be a JSON-encoded string (`'{"request_type": "missed_pickup", "status": "pending_review"}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values returns recoverable API-style errors.
- **M4 nested write payload**: new write tool `create_credit_memo(payload)` taking a Notion-style nested body (`parent.type='resident_account'` + `parent.resident_id`, `properties.Request.reference.request_id`, `properties.MissType.select.name`, `properties.Credit.number`, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.resident_id should be a non-empty string, instead was 'undefined'.` — followed by business checks (request exists → 404; is a pending missed-pickup complaint; belongs to the named resident account; no duplicate memo). The write inserts into a lazily-created `credit_memos` table; SOURCE had no write tool, so this is the sanctioned "convert one deliverable to a write API" case: `step()` gained one criterion, `db_credits_recorded` (10 pts, scale-invariant fraction of ground-truth refunds with a memo matching resident, miss_type, and amount ±0.01), and the prompt gained one recording paragraph. All other criteria and weights are untouched (max_score 100 → 110).

Per-tool return-shape map (M2 not assigned — all successes are native dicts):

| tool | success shape | error shape |
|---|---|---|
| search_service_requests | `{total, page, page_size, results}` | `_error` dict |
| get_request_details | `{"request": {...}}` (nested to avoid `status` key collision with errors) | `_error` dict |
| get_resident_info | flat resident dict | `_error` dict |
| query_gps_stops | `{truck_id, date, stops}` | `_error` dict |
| query_bin_lifts | `{bin_id, date, lifts}` | `_error` dict |
| check_prior_claims | `{resident_id, window, count, claims}` | `_error` dict |
| create_credit_memo | deep echo `{"object": "credit_memo", id, parent, properties, created}` | `_error` dict |

Error contract: tools never raise; every failure returns `{status, object: "error", code, message, request_id}` sharing no top-level keys with any success shape (`object` is the discriminator on `create_credit_memo`). Not-found → 404 `object_not_found`; bad input → 400 `validation_error` / `invalid_json` / `invalid_request`.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| csv_exists | prompt (verbatim contract); also compensation_policy.md Output Requirements |
| csv_columns | prompt (verbatim contract); also compensation_policy.md Output Requirements |
| correct_request_ids | compensation_policy.md Eligibility 1–4 + sla_terms.yaml thresholds/excused codes + zone_boundaries.json pickup days & trucks + route_log_*.csv exceptions |
| correct_miss_types | compensation_policy.md Eligibility 4 (full/partial/invalid definitions) + prompt exact-string sentence |
| correct_credits | compensation_policy.md Credit Calculation (rates, repeat-miss 30-day window, rounding) + compensation_rates.csv |
| sort_order | prompt (verbatim contract); also compensation_policy.md |
| action_summary | prompt final paragraph; also compensation_policy.md |
| db_credits_recorded | prompt paragraph 3 (record a credit memo per validated complaint with request reference, classification, amount) |

Verification: verify() reward 1.0 at v0 (140 tool calls, ≥15 floor) and at v3 (1117 tool calls). Negative-path smoke tests pass: malformed M1 JSON → `invalid_json` with line/column/char, dict-instead-of-string → serialization error, unsupported/wrong-typed filter keys, the full M4 layered sequence (body → parent → parent.type → parent.resident_id → properties → Request → MissType → Credit, one error at a time), 404s on unknown request/resident/truck/bin, and duplicate-memo rejection.
