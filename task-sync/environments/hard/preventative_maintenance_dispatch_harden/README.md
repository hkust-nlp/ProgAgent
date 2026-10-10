## Task Topic

Optimize preventative maintenance schedules to minimize unscheduled downtime. Analyze vehicle telemetry (mileage, engine hours), upcoming reservation calendars, parts inventory levels, and technician certification rosters to generate a prioritized weekly maintenance dispatch list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task uses the following structural dimensions:

- **Conditional Constraints**: Eligibility for scheduling depends on overdue-ratio thresholds (due vs. critical), technician certification level requirements per maintenance type, depot matching between vehicles and technicians, and daily/weekly hour caps — all parameterized in workspace configuration files rather than hard-coded.
- **Information Scattering**: Current vehicle telemetry (odometer, engine hours) lives exclusively in workspace CSV files, while service history and maintenance rules are only accessible through tool calls. Reservation calendars are workspace-only JSON files, and parts inventory is DB-only. Solving the task requires merging data from both sources.
- **Multi-Hop Reasoning**: The dependency chain is at least four hops deep: read telemetry files → query service history per vehicle → look up maintenance rules by category → compute overdue ratios → check parts availability → match technicians by certification and depot → apply greedy scheduling with constraint propagation.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 9 (`dispatch_file_format`, `db_dispatches_recorded`, `vehicle_coverage`, `urgency_scores`, `priority_ranking`, `technician_validity`, `parts_status`, `scheduling_validity`, `response_summary`)
- Source-access: clean. Solver wrote against `v3/prompt.md` + `Task_Env(...).get_assistant_tools()` only; `env.py` was inspected only in Section 3.
- Section 1 structural integrity: passed. `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the top-level `SCALE` block (rows_per_table: 50/100/200/400; num_workspace_files: 8/16/24/32).
- Section 2 solvability: solver required two iterations. First attempt scored 0.91 — `parts_status` criterion failed with accuracy 5.33%. Root cause: tiered maintenance types (e.g. `brake_inspection_tier2`) have no direct entry in `parts_inventory`; the solver must strip the `_tier\d+` suffix before querying parts (matching what `check_parts_availability` already does internally). After applying that fix, second attempt scored 1.0 (100/100). No edits to `env.py` or `prompt.md` were needed — the issue was in the solver only.
- Section 3 env quality: all 9 criteria in `step()` are grounded in explicit `prompt.md` requirements; ground truth is recomputed live from the current DB and workspace files, making scoring fully scale-invariant. No over-normalization; urgency scores compared after float→`:.2f` round-trip only. Priority ranking enforced by exact sequence comparison.
- Section 4 prompt quality: passed. No title/heading at top, no bold section headers, no bulleted/numbered deliverable lists, no tool names or internal filenames, scale-invariant wording, output file and all column names are explicit.
- Issues found and fixed: solver parts-status lookup bug (described in Section 2 above). No edits to any task file (`env.py`, `prompt.md`, `data.py`) were required.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/preventative_maintenance_dispatch`. Ground truth (`_compute_ground_truth`) is byte-unchanged; `step()` is unchanged except the permitted M4 DB-state addition: new criterion `db_dispatches_recorded` (10 pts) checking that every expected dispatch row was recorded via the write API with the correct technician and day, offset by `technician_validity` 15 → 5 (the DB criterion subsumes most of what it checked). All other criteria and weights unchanged; total stays 100.

- **M1 JSON-string parameters**: `list_vehicles` and `list_technicians` each collapse their filters into a single `filter` parameter that must be a JSON-encoded string (`'{"depot_id": "North", "category": "truck"}'` / `'{"depot_id": "South", "min_cert_level": 3}'`). Malformed JSON returns `invalid_json` with line/column/char; passing an object instead of a string, unsupported keys, or wrongly-typed values (incl. bool-where-int) returns recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_dispatch(payload)` tool records work orders through a Notion-style nested body (`parent.type='dispatch_queue'` + `parent.tech_id`, `properties.Vehicle.reference.vehicle_id`, `properties.Maintenance.select.name`, `properties.Day.date.start`, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.tech_id should be a non-empty string, instead was 'undefined'.` — followed by business checks (404 unknown tech/vehicle, 400 duplicate work order). The tool creates/inserts into a `dispatch_orders` table (`CREATE TABLE IF NOT EXISTS`; data.py untouched for tables). Success echo `{"object": "work_order", ...}` shares only the `object` discriminator with error responses.
- **Return shapes / error contract**: all tools return native dicts (M2 not assigned). Tools never raise; every failure is the `_error` dict (`status`/`object`/`code`/`message`/`request_id`). Not-found → 404 `object_not_found`; bad input → 400 `validation_error` / `invalid_json` / `invalid_request`. The former `{"error": ...}` returns were converted to this contract.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 4: scenario/goal (verbatim from source), a pointer to the policy/methodology/configuration documents as the governing spec plus the work-order recording requirement (M4), and the verbatim deliverable contract + final-response paragraphs. Deleted route narration (per-file navigation, "query the database", per-step sequencing) and business-rule restatements after verifying discoverability. `data.py` change (additive only, all versions, SCALE preserved): `generate_policy_files` now also writes a fixed `dispatch_methodology.md` capturing the rules that previously lived only in the prompt — telemetry/service baselines, no-history default, due candidacy (`overdue_ratio >= due_threshold`), qualified-technician definition (depot, cert, daily/weekly hour caps), reservation-day blocking, omit-if-unschedulable, parts-status semantics, tier assignment, and the work-order recording convention.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| dispatch_file_format | prompt paragraph 3 (verbatim contract) |
| db_dispatches_recorded | prompt paragraph 2 ("record every dispatched work order...") + dispatch_methodology.md "Work order recording" |
| vehicle_coverage | dispatch_methodology.md "Due candidacy" + maintenance_policy.yaml (due_threshold, overdue_ratio_formula) |
| urgency_scores | maintenance_policy.yaml (scoring_formula, multiplier_rule) + dispatch_methodology.md (service baseline, no-history default) |
| priority_ranking | scheduling_constraints.json (scheduling_order) + prompt paragraph 3 (rank definition) |
| technician_validity | scheduling_constraints.json (technician_assignment_rule) + dispatch_methodology.md "Scheduling" + certification_guide.md |
| parts_status | dispatch_methodology.md "Parts status" (+ parts tool returns status directly) |
| scheduling_validity | scheduling_constraints.json (available_days, max_dispatches_per_day, day_selection) + reservations files + dispatch_methodology.md (reservation blocking) |
| response_summary | prompt paragraph 4 (verbatim) + maintenance_policy.yaml urgency_tiers + dispatch_methodology.md "Urgency tiers" |

### Verify results

- v3 (400 rows / 32 files): reward 1.0 (100/100), 601 tool calls.
- v0 (50 rows / 8 files): reward 1.0 (100/100), 146 tool calls (≥ 15 floor).
- Negative-path smoke tests pass: M1 malformed JSON (`invalid_json` with line/col/char), dict-instead-of-string, unsupported key, wrong-typed value, bool-as-int, non-object JSON; M4 layered errors surfaced one at a time (missing body → string body → missing parent → wrong parent.type → missing tech_id → missing properties → missing/mistyped Vehicle/Maintenance/Day → bad ISO date), 404 unknown tech/vehicle, 400 duplicate work order; 404s on detail lookups.
