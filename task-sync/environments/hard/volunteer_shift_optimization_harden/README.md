## Task Topic

Optimize volunteer shift coverage by analyzing individual availability calendars, historical no-show rates, event-specific role requirements, and real-time weather forecasts to generate a finalized weekly schedule with prioritized backup assignments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 10                  |
| v1      | 60            | 20                  |
| v2      | 120           | 30                  |
| v3      | 240           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8× of the v0 base; workspace files follow base/base+N/base+2N/base+3N where N = base (10).

**Structural dimensions used:**

- **Information Scattering**: Role certification requirements live in a workspace CSV, additional per-event certification requirements are in event briefing JSON files, volunteer certifications and experience are only available via tool queries, weather forecasts are in a workspace JSON file, and the scheduling policy thresholds are in a workspace YAML file. Solving the task requires combining all of these sources.

- **Conditional Constraints**: Primary assignment eligibility depends on matching certifications (role-level + event-level), minimum experience years, availability window coverage, weekly shift cap, time-conflict avoidance, and no-show rate threshold — spanning three database tables and four workspace file types.

- **Multi-Hop Reasoning**: The dependency chain runs: event briefing (additional cert) → role certification matrix (base certs + min experience) → volunteer query (filter by certs/experience) → availability query (filter by day/time) → attendance summary (compute reliability) → weather forecast (determine backup count) → policy rules (apply thresholds) → schedule output.

- **Deliverable Constraints**: Exact CSV column names and ordering, two-decimal-place formatting for reliability scores, and specific summary statistics with prescribed precision.

## Harness Report

- v3 reward: **1.0** (120/120)
- Eval criteria count: **10** — schedule_format (10), all_shifts_covered (10), certification_compliance (20), availability_compliance (15), max_shifts_compliance (10), no_time_conflicts (10), noshow_threshold_compliance (10), backup_assignments (15), summary_statistics (10), assignments_recorded (10)
- v3 scale: 240 volunteers, 40 events, 240 shifts, 1194 availability records, 2436 attendance records, 45 workspace files
- v3 solver result: 240/240 shifts assigned, coverage 100.0%, average primary reliability 0.99
- Issues found and fixes:
  - **Section 1 (structure):** PASS — top-level has exactly `README.md + v0..v3/`; each version has exactly `data.py env.py prompt.md`; `env.py` and `prompt.md` are byte-for-byte identical across versions; `data.py` diffs are confined to the SCALE dict.
  - **Section 2 (solvability):** First run achieved reward 1.0 immediately.
  - **Section 3 (env quality) — one fix:** `step()` criterion 8 checked backup column presence and count, but did NOT enforce the prompt's requirement that `reliability_score` be formatted to exactly two decimal places. Added a format validation pass inside criterion 8 (`parts = rel_str.split("."); assert len(parts)==2 and len(parts[1])==2`). Fix made in `v0/env.py` and propagated to `v1..v3`. Reward re-confirmed at 1.0.
  - **Section 4 (prompt quality):** PASS — no title, no bold headers, no bullet lists for deliverables, computation logic in prose, no tool names or source filenames, output files and columns named explicitly, wording scale-invariant.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/volunteer_shift_optimization`. Ground truth, criteria weights, and all original scoring logic are unchanged; `step()` gains one DB-state criterion (`assignments_recorded`, 10 pts, max_score now 120) under the M4 no-source-write-tool conversion rule.

- **M1 JSON-string parameters**: `list_volunteers` and `list_shifts` each take a single `filter` parameter that must be a JSON-encoded string (`'{"day_of_week": "Monday", "is_outdoor": true}'`, `'{"certification": "first_aid", "min_experience_years": 2}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values returns recoverable API-style errors, one at a time. `list_shifts` no longer takes a bare `day_of_week` argument — day filtering goes through the JSON string.
- **M4 nested write payload**: new `create_assignment(payload)` tool records each primary assignment into the DB (`shift_assignments` table, created lazily by the tool; `INSERT OR REPLACE` so re-recording a shift replaces the previous row). Notion-style nested body (`parent.type='shift_roster'` + integer `parent.shift_id`, `properties.Volunteer.type='reference'` + `properties.Volunteer.reference.volunteer_id`, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.shift_id should be an integer, instead was ''1''.` — followed by business 404s. Success responses (`{"object": "assignment", "id", "parent", "properties", "created"}`) share no keys with error responses (`{"object": "error", "status", "code", "message", "request_id"}`) apart from the `object` discriminator.
- **Error contract**: tools never raise. All list/lookup tools keep their original JSON-string success encoding and return `json.dumps(_error(...))` on failure (including 404s for unknown volunteer IDs and pagination-type errors); `create_assignment` returns native dicts for both branches.

Per-tool return-shape map (M2 not assigned; success encodings kept identical to SOURCE):

| tool | success shape | error shape |
|---|---|---|
| list_volunteers | JSON string `{"volunteers": [...], "has_more"}` | JSON string of `_error` |
| list_shifts | JSON string `{"shifts": [...], "has_more"}` | JSON string of `_error` |
| get_volunteer_availability | JSON string `{"volunteer_id", "windows"}` | JSON string of `_error` |
| get_attendance_summary | JSON string `{"volunteer_id", "total_records", "attended", "no_shows", "no_show_rate"}` | JSON string of `_error` |
| create_assignment | native dict `{"object": "assignment", ...}` deep echo | native `_error` dict |

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 4: scenario/goal (verbatim from SOURCE), a pointer to the policy/configuration documents as the governing spec (with the load-bearing hints that processing order matters and that each primary assignment must be recorded in the scheduling system), and the verbatim deliverable contract + final-response requirement. Deleted: per-file navigation (para 2), tool hand-holding (para 3), and the step-by-step assignment/backup procedure narration (paras 4-5). `data.py` change (additive fixed policy document only, SCALE untouched): `create_workspace` now also writes `primary_assignment_rules.md`, carrying the previously prompt-only primary-selection rules (processing order, eligibility definition, overlap/cap restrictions, no-show threshold, reliability ranking + volunteer-ID tie-breaker, threshold-relaxation fallback, record-in-system step). Backup selection rules were already fully specified in `backup_priority_rules.md`; thresholds/counts in `scheduling_policy.yaml`; role requirements in `role_certification_matrix.csv`; event-level extra certifications in the event briefs.

Completeness audit (step() criterion -> info source):

| criterion | source |
|---|---|
| schedule_format | prompt (verbatim deliverable contract) |
| all_shifts_covered | prompt ("exactly one primary volunteer to every shift") |
| certification_compliance | primary_assignment_rules.md + role_certification_matrix.csv + event_brief_*.json |
| availability_compliance | primary_assignment_rules.md (full-duration window rule) |
| max_shifts_compliance | primary_assignment_rules.md (weekly cap, primaries only) + volunteers.max_shifts_per_week |
| no_time_conflicts | primary_assignment_rules.md (same-day overlap ineligibility) |
| noshow_threshold_compliance | primary_assignment_rules.md + scheduling_policy.yaml (no_show_threshold) |
| backup_assignments | backup_priority_rules.md + scheduling_policy.yaml (counts, rain_threshold) + weather_forecast.json + prompt (columns, 2-dp reliability) |
| summary_statistics | prompt (final-response requirement, formulas + rounding) |
| assignments_recorded | prompt ("record the assignment in the organization's scheduling system") + primary_assignment_rules.md |

### Verification

- v3 (`rows_per_table=240`): `verify()` reward **1.0**, 747 tool calls.
- v0 (`rows_per_table=30`): `verify()` reward **1.0**, 104 tool calls (>= 15 floor).
- Negative-path smoke tests pass: M1 malformed JSON (`invalid_json` with line/column/char), dict-where-string-required, unsupported filter key, wrong-typed filter value; M4 layered messages one at a time (undefined body -> string body -> missing parent -> wrong parent.type -> non-integer shift_id -> missing Volunteer -> wrong property type -> undefined volunteer_id), business 404s for unknown shift/volunteer, lookup-tool 404s, optional Note rich_text success path.
- `diff v0/env.py v{1,2,3}/env.py` empty; prompt.md identical across versions; per-version data.py differ only in the SCALE block; no runtime artifacts left.
