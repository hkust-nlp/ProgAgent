## Task Topic

Generate a weekly referee assignment roster by cross-referencing referee availability logs, their certification levels for different match types, historical team-referee conflict records, and venue locations to ensure compliant and conflict-free officiating for all fixtures.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 10                  |
| v1      | 50            | 20                  |
| v2      | 100           | 30                  |
| v3      | 200           | 40                  |

Scaling ratios: rows_per_table follows 1x/2x/4x/8x; num_workspace_files follows base/base+N/base+2N/base+3N where N=10 (base).

Structural dimensions used:

- **Conditional Constraints**: Referee eligibility depends on certification level vs. match type requirement (from workspace config), active conflict status (from DB), travel distance vs. maximum threshold (from workspace CSV), and per-referee weekly assignment caps.
- **Information Scattering**: Fixture details, referee profiles, certifications, and conflicts live in the database (tool-only access). Availability schedules, the travel distance matrix, and assignment policy rules reside in workspace files. Both sources are required to determine any single assignment.
- **Multi-Hop Reasoning**: For each fixture: retrieve fixture details (tool) -> look up venue city (tool) -> read travel matrix (file) -> check referee home city (tool) -> compare distance against policy threshold (file). Certification check requires: fixture match_type (tool) -> match_requirements.json (file) -> referee certifications (tool) -> numeric comparison.

## Harness Report

- v3 reward: **1.0** (110/110)
- Eval criteria: 8 — `roster_file_exists` (10), `correct_columns` (10), `all_fixtures_present` (10), `fixture_metadata_accuracy` (20), `referee_assignment_accuracy` (30), `referee_name_accuracy` (10), `sort_order` (10), `db_assignments_recorded` (10). The 8th criterion (`db_assignments_recorded`) was added by hardening under the M4 no-write-tool exception; see the Hardening section below.
- Independent solver result: reward 1.0 confirmed by a from-scratch solver using only `v3/prompt.md` and the public `Task_Env.get_assistant_tools()` interface (no `env.py` / `data.py` reads); solver queried SQLite and workspace files directly, recorded 128 assignments via `create_assignment`, wrote `roster.csv`, and received all 8 criteria passed.
- Structural integrity: PASS — `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (2 lines).
- Prompt quality: PASS — no title, no bold headers, no lists, natural-language only, no tool names or internal filenames, output deliverable named, scale-invariant wording.
- Env quality: PASS — all 8 criteria correspond to explicit prompt requirements; ground truth derived from live DB (scale-invariant); no hard-coded counts; no over-normalization beyond acceptable `.strip()` on referee names.
- Issues found and fixed: none.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/referee_assignment_scheduling`. `_compute_ground_truth()` and the seven original criteria are unchanged. Under the M4 no-write-tool exception `step()` gains one DB-state criterion (`db_assignments_recorded`, 10 pts) and `prompt.md` gains one recording sentence, so `max_score` is 100 → 110 (reward is normalized as `total_score / max_score`, so it stays in `[0, 1]`). `env.py`/`prompt.md` are byte-identical across v0–v3; per-version `data.py` differs only in its `SCALE` block plus one additive policy document.

- **M0 de-proceduralized prompt**: rewritten from the SOURCE route narration to 5 sentences of scenario/goal + a pointer to "the policy and configuration documents stored alongside the data" as the authoritative spec, the central-registry recording requirement (M4), and the verbatim deliverable contract (`roster.csv`, columns and order per the output-format document, sort by `fixture_id` ascending, no index column) + final-response requirement. Deleted: tool hand-holding and file-by-file navigation. Rules moved additively into `assignment_methodology.md` (greedy per-fixture procedure, certification levels basic=1/advanced=2/elite=3); the active-pool/priority-order/tie-break/`max_travel`=300/`conflict_policy` active=1/slot rules live in `policy.yaml`, per-match cert requirements in `match_requirements.json`, distances in `travel_matrix.csv`, and the column list/order/sentinel convention in `output_format.md` + `scheduling_notes.txt`.
- **M1 JSON-string parameters**: `get_fixtures` (keys `day_of_week`, `time_slot`, `match_type`) and `get_conflicts` (keys `active`, `conflict_type`) each collapse their filters into a single `filter` parameter that must be a JSON-encoded string (e.g. `'{"day_of_week": "Saturday", "match_type": "..."}'`, `'{"active": true}'`; pass `'{}'` or omit for no filtering). The Python parameter is typed `Any`; malformed JSON → `invalid_json` with line/column/char, a dict/list instead of a string → `invalid_request`, unsupported keys / wrong-typed values → `validation_error`, one error at a time. Pagination args (`page`, `page_size`) are coerced/validated via `_coerce_int`.
- **M4 nested write payload**: new write tool `create_assignment(payload)` taking a Notion-style nested body — `parent.type='fixture_slot'` + `parent.fixture_id`, `properties.Referee.reference.referee_id`, optional `Note` rich_text. Validation is layered, one error per call, in order: `body` defined → object → `parent` defined → object → `parent.type` == `"fixture_slot"` → `parent.fixture_id` non-empty string → `properties` defined → object → `Referee` defined → object → `Referee.type` == `"reference"` → `Referee.reference` object → `Referee.reference.referee_id` non-empty string → optional `Note` (`type` == `"rich_text"` + rich_text shape). Only then the business checks (fixture/referee exist, etc.) as `_error(404/400, …)`. The write does `INSERT OR REPLACE` into a lazily-created `roster_assignments` table; SOURCE had no write tool, so this is the sanctioned "convert one deliverable to a write API" case. Success returns a deep echo `{"object": "assignment", id, parent, properties, created: true}`.

Return-shape map (M2 not assigned — all successes are native dicts; the shared `_envelope` helper is unused):

| tool | success shape | error shape |
|---|---|---|
| get_fixtures | `{fixtures, page, page_size, total_fixtures, total_pages}` | `_error` dict |
| get_referee_info | flat referee dict | `_error` dict |
| get_certifications | `{referee_id, certifications}` | `_error` dict |
| get_conflicts | `{referee_id, conflicts}` | `_error` dict |
| get_venue_info | flat venue dict | `_error` dict |
| get_team_info | flat team dict | `_error` dict |
| list_referees | `{referees, page, page_size, total_referees, total_pages}` | `_error` dict |
| create_assignment | deep echo `{object: "assignment", id, parent, properties, created}` | `_error` dict |

Error contract: tools never raise; every failure returns `{status, object: "error", code, message, request_id}` sharing no top-level keys with any success shape (`object` is the discriminator on `create_assignment`). Not-found → 404 `object_not_found`; bad input → 400 `validation_error` / `invalid_json` / `invalid_request`.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| roster_file_exists (10) | prompt para 5 + `output_format.md` (filename `roster.csv`) |
| correct_columns (10) | `output_format.md` (exact columns + order); prompt para 5 points to it |
| all_fixtures_present (10) | prompt para 1 (every fixture appears) + `scheduling_notes.txt` (unassigned still listed with the sentinel) |
| fixture_metadata_accuracy (20) | fixture details via `get_fixtures` / `get_venue_info` |
| referee_assignment_accuracy (30) | `policy.yaml` (eligibility, priority order, `max_travel`=300, `conflict_policy` active=1, slot rule) + `match_requirements.json` (cert levels) + `travel_matrix.csv` + `assignment_methodology.md` (greedy procedure; basic=1/advanced=2/elite=3) |
| referee_name_accuracy (10) | `get_referee_info` |
| sort_order (10) | `output_format.md` (sort by `fixture_id` asc); prompt para 5 |
| db_assignments_recorded (10) | prompt para 3 (record every assigned fixture in the central assignment registry) + `create_assignment` |

Verification: `verify()` reward 1.0 at v0 (110/110, 94 tool calls, ≥ 15 floor) and v3 (110/110, 668 tool calls). Negative-path checks: malformed M1 filter JSON → `invalid_json` with line/column/char; dict-instead-of-string → `invalid_request`; unsupported/wrong-typed filter keys → `validation_error`; the M4 layered payload surfaces one error at a time from `body` down to `properties.Referee.reference.referee_id`; unknown fixture/referee ids → 404 `object_not_found`.
