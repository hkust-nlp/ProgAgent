## Task Topic

Balance student course requests against teacher availability. Analyze student elective preference surveys, teacher contracted periods and subject assignments, core course requirements, and maximum class size limits to generate a finalized student timetable for the semester.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 8                   |
| v1      | 50            | 16                  |
| v2      | 100           | 24                  |
| v3      | 200           | 32                  |

The v0→v3 scaling ratios follow the standard pattern: rows scale as 1×, 2×, 4×, 8× of the base, and workspace files scale as N, N+N, N+2N, N+3N where N is the v0 base count.

**Structural dimensions used:**

- **Information Scattering**: Student rosters, course catalogs, section details, and teacher-to-section assignments live in the database (accessible only through tools), while elective preference surveys, teacher contracted availability schedules, core curriculum requirements, and scheduling policy parameters reside in workspace files. Solving the task requires cross-referencing both sources — for example, determining whether a section is "active" requires joining the tool-provided teacher assignment with the workspace-provided teacher availability schedule.

- **Multi-Hop Reasoning**: Determining a valid section assignment requires a dependency chain of length ≥ 3: query course sections (tool) → look up assigned teacher for each section (tool) → cross-reference teacher availability in that time slot (workspace file) → check remaining capacity against class size limit (tool-provided max_capacity minus current enrollments) → apply scheduling policy tie-breaking rules (workspace config).

- **Conditional Constraints**: Section eligibility depends on multiple interacting rules: the teacher must be available in the section's time slot (teacher schedule file), the section must have remaining capacity (max_capacity from DB), the time slot must not conflict with the student's already-assigned courses, and core courses take precedence over electives. The scheduling policy file specifies the priority order (GPA-based) and tie-breaking rules for section selection.

## Harness Report

- v3 reward: **1.0** (110 / 110)
- Eval criteria: **8** — file_format (10 pts), student_coverage (15 pts), schedule_completeness (15 pts), core_requirements (20 pts), capacity_limits (15 pts), teacher_availability (15 pts), summary_statistics (10 pts), db_enrollments_recorded (10 pts)
- Section 1 — structural integrity: PASSED. Top-level contains exactly README.md + v0..v3; each version directory contains exactly data.py / env.py / prompt.md; env.py and prompt.md are byte-identical across v0–v3; data.py differs only in the SCALE dict (rows_per_table 25/50/100/200, num_workspace_files 8/16/24/32).
- Section 2 — solvability at v3: Initial greedy solver (core courses placed in declaration order) scored 0.9848 — core_requirements criterion 550/600 because some students' three required cores share time slots and picking them in list order leaves one unplaceable. Fixed by switching to most-constrained-first ordering (sort core courses by number of available active slots ascending before assigning). This yielded reward 1.0 on the first retry. No env.py or prompt.md changes were needed.
- Section 3 — env quality: All 8 step() criteria have a direct corresponding requirement in prompt.md (see completeness audit table below). Ground truth is derived entirely from data.db / workspace files — no hardcoded counts or distributions. One minor gap noted but not fixed: prompt specifies row sort order (student_id ASC, time_slot ASC) but step() does not verify it; this is acceptable since row order does not affect timetable correctness.
- Section 4 — prompt quality: PASSED. No title or bold headers; deliverables woven into prose (no lists); column names specified inline; no tool names or env internals mentioned; all wording is scale-invariant (uses "every student", "all elective assignments", "exactly six time slots" — six is a fixed business rule, not a data count).
- Issues fixed: none — no edits to v0/ or any version were required.
- Artifacts cleaned: data.db and workspace/ removed from v3/ after the solve run.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/student_timetable_generation`. `data.py` is byte-identical to SOURCE in all four versions (all business rules were already discoverable in the generated workspace policy documents, so no additive policy-doc edits were needed). Original step() criteria 1–7 and their weights are unchanged; per the M4 no-write-tool exception, step() gains one DB-state criterion (`db_enrollments_recorded`, 10 pts → max_score 110, reward still normalized).

- **M1 JSON-string parameters**: `list_students` and `list_courses` each collapse their filters into a single `filter` parameter that must be a JSON-encoded string (`'{"grade": 10, "program": "Science"}'` / `'{"course_type": "core", "subject_area": "Music"}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrong-typed values returns recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_enrollment(payload)` tool records each student-section placement into a lazily-created `enrollments` table via a Notion-style nested body (`parent.type="section_roster"` + `parent.section_id` + `properties.Student.reference.student_id`, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.section_id should be a non-empty string, instead was 'undefined'.` Business checks (section/student exist → 404, duplicate enrollment → 400) run only after structural validation. Success echo (`{"object": "enrollment", ..., "created": true}`) is shape-disjoint from errors.
- **Universal error contract**: tools never raise; every failure returns `{"status", "object": "error", "code", "message", "request_id"}`; all lookup tools (`get_student_info`, `get_course_info`, `get_course_sections`, `get_section_teacher`, `get_teacher_sections`) return `object_not_found` 404s instead of `{"error": ...}` dicts. Success and error responses share no keys (except the deliberate `object` discriminator on the write tool's deep echo, per the M4 template).

Per-tool return-shape map (M2 not assigned — all success returns stay native dicts):

| tool | success shape | error shape |
|---|---|---|
| list_students | dict (students/total/page/page_size/total_pages) | `_error` dict |
| list_courses | dict (courses/total/page/page_size/total_pages) | `_error` dict |
| get_student_info / get_course_info | flat record dict | `_error` 404 |
| get_course_sections | dict (course_id/sections) | `_error` 404 |
| get_section_teacher | dict (section_id/teacher_id/teacher_name/department) | `_error` 404 |
| get_teacher_sections | dict (teacher_id/sections) | `_error` 404 |
| create_enrollment | deep echo (object/id/parent/properties/created) | `_error` 400/404 |

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 6 route-narrating paragraphs to 5: scenario/goal (kept verbatim from SOURCE para 1, incl. the "exactly six sections, one per slot" contract), a pointer paragraph naming the policy/configuration documents as the authoritative specification (with the load-bearing hint that each placement changes remaining capacity), the M4 recording requirement, and the two deliverable-contract paragraphs kept **verbatim** (timetable.csv columns/order/sort and the four summary statistics with field definitions). Deleted route narration: the step-by-step GPA ordering, core-first sequencing, section-selection and tie-break rules, active-section definition, and elective-preference walk-through — all verified present in the generated workspace (`scheduling_policy.yaml`: priority_order/tiebreaker/section-selection/tiebreakers/max_time_slots; `enrollment_rules.md`: processing order, core-first, ascending-rank electives, active-section definition, leave-empty rule). No prompt-only rules existed, so no `data.py` additions were required.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| file_format (c1) | prompt para 4 (verbatim contract) |
| student_coverage (c2) | prompt para 1 ("Every student") + para 4 ("After processing every student") |
| schedule_completeness (c3) | prompt para 1 ("exactly six course sections, one for each time slot"); scheduling_policy.yaml max_time_slots |
| core_requirements (c4) | prompt para 1 (mandatory cores by program/grade) + core_requirements.json + enrollment_rules.md §2 |
| capacity_limits (c5) | enrollment_rules.md §2–3 (remaining capacity) + section max_capacity via tools |
| teacher_availability (c6) | enrollment_rules.md §4 (active-section definition) + teacher_schedules/*.csv |
| summary_statistics (c7) | prompt para 5 (verbatim contract incl. elective-rank definition) |
| db_enrollments_recorded (c8) | prompt para 3 ("record the enrollment in the school's enrollment system") |

### Verification

- v3 (rows=200, files=32): verify() reward **1.0** (110/110), 1772 tool calls.
- v0 (rows=25, files=8): verify() reward **1.0**, 224 tool calls (≥ 15 floor).
- Negative-path smoke tests passed: malformed M1 JSON → `invalid_json` with line/column/char; dict-for-string → serialize hint; unsupported/wrong-typed filter keys → per-key `validation_error`; M4 layered messages fire one at a time down to the innermost `student_id`; nonexistent section/student → 404; duplicate enrollment → 400; success/error key disjointness confirmed.
- `env.py` and `prompt.md` byte-identical across v0–v3; `data.py` byte-identical to SOURCE per version; no runtime artifacts.
