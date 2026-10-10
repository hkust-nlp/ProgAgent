## Task Topic

Validate pipeline capacity bookings by cross-referencing shipper reservation requests, historical segment flow volatility models, scheduled maintenance calendars for valves/pumps, and real-time weather impact forecasts to confirm or adjust allocated capacities, outputting a finalized and balanced capacity allocation report.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Structural dimensions used:

- **Information Scattering**: Task-critical data is split across workspace files (reservation nominations in CSVs, priority flags in JSONs, equipment condition factors in YAMLs, regulatory capacity limits in TXTs) and tool calls (segment capacities, shipper profiles, maintenance events, flow volatility, weather forecasts). Neither source alone is sufficient to compute the allocation.
- **Multi-Hop Reasoning**: The allocation requires a dependency chain of length 4+: read reservation CSVs to identify segment IDs, call tools for segment details to obtain regions, call weather forecast tool with those regions, then apply severity-to-impact mapping from the allocation policy config to compute weather adjustments, which feed into the effective capacity calculation that determines each shipper's allocation.
- **Conditional Constraints**: Allocation order depends on priority flags, contract tiers, and reliability scores with a multi-level tiebreaker. Maintenance reductions are modulated by equipment age factors and capped by policy. Regulatory limits override physical capacity when lower.

## Harness Report

- **v3 reward**: 1.0 (110/110)
- **Eval criteria**: 7 (`report_structure` 15 pts, `row_count` 10 pts, `effective_capacity` 20 pts, `allocation_amounts` 25 pts, `allocation_status` 15 pts, `summary_statistics` 15 pts, `decisions_recorded` 10 pts)
- **Solver source-access**: clean black-box — solver written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- **Issues found and fixed**:
  - **Completeness gap in `summary_statistics` criterion** (Section 3, rule 2): `step()` computed `n_reservations`, `total_nominated`, and `total_allocated` but never checked them against the agent response, leaving 3 of 8 prompt-required summary values unevaluated. Fixed in `v0/env.py` by adding the 3 missing substring checks and updating `total_checks` from 5 to 8. Re-propagated to `v1–v3`; reward confirmed 1.0 after fix.
  - **Redundant sort sub-rule in `allocation_methodology.md`** (Section 3, documented only): Step 3 of the priority ordering ("within the same priority flag rank and tier, critical before normal") is a no-op — each flag maps to a unique rank, so no two records within the same `pf_rank` group can differ in criticality. The corresponding 4th sort key `(0 if flag=="critical" else 1)` in `step()` is likewise constant within every group. This is a documentation ambiguity in the generated workspace file; it does not affect scoring or ground truth. Noted but not fixed (changing `allocation_methodology.md` requires modifying `data.py`'s template, and the redundancy causes no wrong answers).
- **Section 1 structural check**: passed — `env.py` and `prompt.md` byte-for-byte identical across v0–v3; `data.py` differs only in the `SCALE` block; no stale artifacts.
- **Section 4 prompt quality**: passed — no title/headers, no bulleted lists, no tool names or source filenames, scale-invariant wording, all output columns explicitly named.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/capacity_booking_validation`. Ground truth (`_compute_ground_truth`) and the six original scoring criteria are unchanged; per the M4 conversion rule, `step()` gains exactly one DB-state criterion (`decisions_recorded`, 10 pts; max score is now 110 and reward is normalized).

### Mutators

- **M1 JSON-string parameters**: `query_maintenance` and `get_weather_forecast` each take a single `filter` parameter that must be a JSON-encoded string (`'{"segment_id": "SEG-0001", "active_on": "2026-04-25"}'` / `'{"region": "Northeast", "date": "2026-04-25"}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, missing required keys, or wrong-typed values return recoverable API-style errors, one at a time.
- **M4 nested write payload**: new write tool `create_allocation_decision(payload)` takes a Notion-style nested body (`parent.type="nomination_cycle"` + `parent.segment_id`, `properties.Reservation.reference.reservation_id`, `properties.Allocation.number`, `properties.Status.select.name` ∈ {confirmed, curtailed, rejected}, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.segment_id should be a non-empty string, instead was 'undefined'.` — followed by business checks (reservation exists → 404, is pending, parent segment matches). The write is an `INSERT OR REPLACE` into an `allocation_decisions` table; `step()` criterion 7 checks each expected reservation has a recorded decision with matching status and allocated volume (±0.02). This converts the previously prompt-only "finalize" semantics into a DB-recorded deliverable (the report CSV deliverable is unchanged).
- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 7 route-narrating paragraphs to 4 — scenario/goal, a pointer to the policy + methodology documents as the governing specification (plus the record-in-the-booking-system requirement), and the two deliverable-contract paragraphs kept verbatim (the only edit: "the allocation priority order described above" → "defined in the methodology"). `data.py` change is additive only: `write_workspace` now also emits a fixed, non-scaling `allocation_methodology.md` carrying every formerly prompt-only rule (baseline = min(physical, regulatory); per-event maintenance reduction = base pct × equipment age factor, summed and capped; maintenance → weather → volatility multiplicative order with single final rounding; volatility tier classification; five-level priority order; greedy per-segment allocation with per-step rounding; confirmed/curtailed/rejected definitions; default flag `normal`; default age factor 1.0). SCALE blocks preserved per version.

### Per-tool surface map

| tool | params | success shape | notes |
|---|---|---|---|
| get_segment_info | segment_id | native dict (row) | 404 `_error` if unknown |
| get_shipper_profile | shipper_id | native dict (row) | 404 `_error` if unknown |
| query_maintenance | `filter` JSON string (segment_id, active_on) | `{"maintenance_events": [...], "matched": n}` | M1 |
| get_flow_volatility | segment_id | native dict (row) | 404 `_error` if no data |
| get_weather_forecast | `filter` JSON string (region, date) | native dict (row) | M1; 404 if no forecast |
| create_allocation_decision | nested `payload` | deep echo `{"object": "allocation_decision", ..., "created": true}` | M4; layered validation |

### Error contract

Tools never raise. Every failure returns `{"status", "object": "error", "code", "message", "request_id"}` — no keys shared with any tool's success shape. Codes: `invalid_json` (with line/column/char), `invalid_request` (wrong parameter encoding), `validation_error` (unsupported/missing/wrong-typed fields, layered one-at-a-time for M4; business-state violations), `object_not_found` (404, `Could not find <entity> with ID: <id>.`).

### Completeness audit (step() criterion → info source)

| criterion | source |
|---|---|
| report_structure | prompt para 3 (verbatim contract: filename, columns, order, precision) |
| row_count | prompt ("every pending reservation") + allocation_methodology.md Scope (`reservation_batch_*.csv` define the pending set) |
| effective_capacity | allocation_methodology.md "Effective segment capacity" + allocation_policy.yaml parameters |
| allocation_amounts | allocation_methodology.md "Allocation priority order" + "Greedy allocation" + policy ranks |
| allocation_status | allocation_methodology.md "Greedy allocation" (confirmed/curtailed/rejected definitions) |
| summary_statistics | prompt para 4 (verbatim summary contract incl. utilization definition) |
| decisions_recorded | prompt para 2 ("recorded in the operator's booking system") + allocation_methodology.md "Recording decisions" |

### Verification

- v3 (`rows_per_table=240`): `verify()` reward **1.0** (110/110), 602 tool calls.
- v0 (`rows_per_table=30`): `verify()` reward **1.0**, 80 tool calls (≥ 15 floor).
- Negative-path smoke tests pass: malformed M1 JSON → `invalid_json` with position; dict-instead-of-string → `invalid_request`; unsupported/missing/wrong-typed filter keys → `validation_error`; M4 layered errors surface one at a time (body → parent → parent.type → properties → Reservation → Allocation → Status.select.name); unknown segment/forecast/reservation → 404 `object_not_found`.
- `env.py`, `prompt.md` identical across v0–v3; `data.py` differs only in the SCALE block; no runtime artifacts left in version directories.
