## Task Topic

Optimize classroom and specialist room assignments. Cross-reference teacher subject certifications, class enrollment rosters, room capacity and equipment lists, and mandatory weekly instructional minutes to produce a conflict-free weekly room allocation schedule.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 12            | 8                   |
| v1      | 24            | 16                  |
| v2      | 48            | 24                  |
| v3      | 96            | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N = 8.

Structural dimensions used:

- **Information Scattering**: Room equipment details live in YAML workspace manifests while room capacity and type are only available via query tools. Teacher availability constraints are in CSV workspace files while teacher certifications require per-teacher tool calls. Instructional minute requirements are in a workspace CSV while class enrollments and subjects come from query tools.
- **Multi-Hop Reasoning**: Determining how many periods each class needs requires reading the instructional-minutes CSV and the scheduling-policy YAML (for period duration), then computing the ceiling of their ratio. Assigning a room requires looking up the class's subject, mapping it to required equipment via a JSON reference, then checking each candidate room's equipment manifest in YAML files, and finally verifying capacity from the query tools — a dependency chain of length 4+.
- **Conditional Constraints**: Room eligibility depends on equipment match, capacity threshold, and specialist-room exclusivity rules. Teacher scheduling is constrained by per-day and per-week period caps plus unavailability slots.

## Harness Report

- **v3 reward: 1.0 (125/125)** after verification fixes.
- **Eval criteria: 10**

  | criterion | pts | source |
  |---|---|---|
  | schedule_file_valid | 10 | prompt: exact filename + required columns |
  | schedule_sorted | 5 | prompt: "Sort the rows first by day… then period… then class identifier" |
  | all_classes_covered | 20 | prompt para 1 + `scheduling_methodology.md` (ceil formula) |
  | no_room_conflicts | 15 | prompt para 1: no room hosts two classes in one slot |
  | no_teacher_conflicts | 15 | prompt para 1: no teacher double-booked in same day+period |
  | capacity_respected | 15 | `scheduling_methodology.md`: room capacity ≥ enrollment |
  | equipment_satisfied | 15 | `scheduling_methodology.md` + workspace JSON/YAML manifests |
  | specialist_rooms_respected | 10 | `room_priority_rules.txt`: regular classes may NOT use specialist rooms |
  | schedule_recorded_in_db | 10 | prompt: "record every period assignment in the room-booking system" |
  | summary_response | 10 | prompt: exact `"Scheduling Summary: X classes across Y periods using Z rooms"` line |

- **Solver source-access:** clean black-box. Solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no escalation to `env.py` was required.
- **Structural integrity:** passed. `env.py` and `prompt.md` are byte-for-byte identical across v0..v3; `data.py` differs only in `SCALE` (rows 12/24/48/96; files 8/16/24/32).
- **Issues found and fixed:**
  1. `step()` did not verify that CSV rows were sorted as specified in `prompt.md` ("Sort the rows first by day… then by period… then by class identifier"). Fixed by adding `schedule_sorted` criterion (5 pts) to `v0/env.py` and re-propagating.
  2. `step()` did not enforce the specialist-room exclusivity rule from `room_priority_rules.txt` (regular-subject classes must not be placed in specialist rooms such as labs, studios, gymnasium, computer labs). The `equipment_satisfied` criterion alone did not catch this because an empty required-equipment set is trivially a subset of any room's equipment. Fixed by adding `specialist_rooms_respected` criterion (10 pts) to `v0/env.py` and re-propagating. These 2 additions raise `max_score` from 110 to 125; reward remains normalized as `total_score / max_score`.
- **prompt.md quality:** passed all checks — no title/heading, no bold headers, no bulleted deliverable lists, column names inline in prose, sort order in natural language, no tool names or internal filenames, all deliverables explicitly named, wording scale-invariant.
- **Cleanup:** removed `data.db`, `workspace/`, `__pycache__/` from v3 (v0/v1/v2 were already clean).

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/classroom_assignment_optimization`. `_compute_ground_truth()` and the six original CSV/constraint criteria are unchanged. Under the M4 no-write-tool exception `step()` gains one DB-state criterion (`schedule_recorded_in_db`, 10 pts) and `prompt.md` gains one recording paragraph, so `max_score` is 100 → 110 (reward is normalized as `total_score / max_score`, so it stays in `[0, 1]`). `env.py`/`prompt.md` are byte-identical across v0–v3; per-version `data.py` differs only in its `SCALE` block plus one additive policy document.

- **M0 de-proceduralized prompt**: rewritten from the SOURCE route narration to 5 paragraphs — scenario/goal, a pointer to "the policy and configuration documents stored alongside the data" as the authoritative spec, the room-booking recording requirement (M4), and the verbatim deliverable contract + final-response paragraphs (exact filename `weekly_schedule.csv`, the 8-column list and order, the Monday-first / period / class_id sort, and the exact `"Scheduling Summary: X classes across Y periods using Z rooms"` line). Deleted: tool hand-holding and per-file navigation. The period-count derivation, room-eligibility, teacher-availability and load-limit rules were moved additively into `scheduling_methodology.md`; period duration lives in `scheduling_policy.yaml`, required minutes in `instructional_minutes.csv`, equipment mapping in `subject_equipment_requirements.json` + `room_equipment_*.yaml`.
- **M1 JSON-string parameters**: `list_classes` (keys `subject`, `grade_level`) and `list_rooms` (keys `room_type`, `min_capacity`) each collapse their filters into a single `filter` parameter that must be a JSON-encoded string (e.g. `'{"subject": "Chemistry", "grade_level": 10}'`, `'{"room_type": "science_lab", "min_capacity": 20}'`; pass `'{}'` or omit for no filtering). The Python parameter is typed `Any`; malformed JSON → `invalid_json` with line/column/char, a dict/list instead of a string → `invalid_request`, unsupported keys / wrong-typed values → `validation_error`, one error at a time.
- **M4 nested write payload**: new write tool `create_booking(payload)` taking a Notion-style nested body — `parent.type='room_calendar'` + `parent.room_id` (numeric string), `properties.Class.reference.class_id`, `properties.Slot.timeslot` (`{day, period}`), optional `Note` rich_text. Validation is layered, one error per call, in order: `body` defined → object → `parent` defined → object → `parent.type` == `"room_calendar"` → `parent.room_id` non-empty string → numeric string → `properties` defined → object → `Class` defined → object → `Class.type` == `"reference"` → `Class.reference` object → `Class.reference.class_id` non-empty/numeric string → `Slot` → optional `Note`. Only then the business checks (room/class exist, slot free) as `_error(404/400, …)`. The write inserts into a lazily-created `schedule_bookings` table; SOURCE had no write tool, so this is the sanctioned "convert one deliverable to a write API" case. Success returns a deep echo `{"object": "booking", id, parent, properties, created: true}`.

Return-shape map (M2 not assigned — all successes are native dicts; the shared `_envelope` helper is unused):

| tool | success shape | error shape |
|---|---|---|
| list_teachers | `{teachers, total, page, page_size, has_more}` | `_error` dict |
| get_teacher_certifications | `{teacher_id, certifications}` | `_error` dict |
| list_classes | `{classes, total, page, page_size, has_more}` | `_error` dict |
| list_rooms | `{rooms, total, page, page_size, has_more}` | `_error` dict |
| get_room_details | flat room dict | `_error` dict |
| get_class_details | flat class dict | `_error` dict |
| create_booking | deep echo `{object: "booking", id, parent, properties, created}` | `_error` dict |

Error contract: tools never raise; every failure returns `{status, object: "error", code, message, request_id}` sharing no top-level keys with any success shape (`object` is the discriminator on `create_booking`). Not-found → 404 `object_not_found`; bad input → 400 `validation_error` / `invalid_json` / `invalid_request`.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| schedule_file_valid (10) | prompt (verbatim contract: filename + column list/order) |
| all_classes_covered (20) | prompt para 1 (every class, each required period) + `scheduling_methodology.md` (periods = ceil(min_weekly_minutes / period_duration)) + `instructional_minutes.csv` + `scheduling_policy.yaml` |
| no_room_conflicts (15) | prompt para 1 (no room hosts two classes in one slot) |
| no_teacher_conflicts (15) | prompt para 1 (no teacher double-booked in a day+period) |
| capacity_respected (15) | `scheduling_methodology.md` (room eligibility: capacity) + `get_room_details` / `get_class_details` |
| equipment_satisfied (15) | `scheduling_methodology.md` (equipment match) + `subject_equipment_requirements.json` + `room_equipment_*.yaml` |
| schedule_recorded_in_db (10) | prompt para 5 (record every period assignment in the room-booking system) + `create_booking` |
| summary_response (10) | prompt final paragraph (verbatim summary-line format) |

Verification: `verify()` reward 1.0 at v0 (110/110, 66 tool calls, ≥ 15 floor) and v3 (110/110, 474 tool calls). Scoring stays intentionally lenient on the same prompt-mentioned constraints as SOURCE (teacher daily/weekly caps, unavailability, certification, best-fit room choice) — not separately scored, but a valid greedy solver that respects them earns full reward.
