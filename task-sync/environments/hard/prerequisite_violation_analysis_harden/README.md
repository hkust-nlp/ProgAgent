## Task Topic

Identify prerequisite violation patterns. Analyze student academic transcripts, course prerequisite trees, registration attempt logs, and advisor override records to detect systemic gaps in prerequisite enforcement, outputting a violation report with recommended policy adjustments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task scales from 80 students/courses/prerequisites (v0) up to 640 (v3). Workspace files (advisor override batches, student-advisor maps, audit logs, department capacity data, and prerequisite review notes) grow proportionally.

**Structural dimensions used:**

- **Information Scattering**: Violation detection requires cross-referencing tool-only data (student transcripts, course prerequisites, registration attempts) with workspace-only data (grade conversion table, enforcement policy, advisor override records, student-advisor assignments). Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The dependency chain is at least 3 hops deep: query prerequisites (Tool) -> query student transcript (Tool) -> read grade scale (File) -> compare grades -> read enforcement policy (File) -> classify severity -> read override records (File) -> determine override status.
- **Conditional Constraints**: Severity classification depends on two conditions evaluated together (violation type and whether the course is in the student's major), with thresholds for recommendations defined in a workspace policy file.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 8 — report_structure (10 pts), violation_count (20 pts), violation_identification (20 pts), severity_classification (15 pts), override_status (10 pts), recommendations_structure (10 pts), recommendations_accuracy (10 pts), response_summary (5 pts); max_score = 100
- Source-access: clean — only `v3/prompt.md` read during solvability phase; tools discovered via `Task_Env.get_assistant_tools()`; no escalation to `env.py` needed
- Structural integrity: passed — v0/v1/v2/v3 differ only in `SCALE` block of `data.py`; `env.py` and `prompt.md` byte-identical across versions

**Issues found and fixed:**

1. **Sort order not enforced (Section 3, criterion 3)** — `prompt.md` specifies violations must be sorted critical→major→minor, then student identifier ascending, then course identifier ascending; `step()` never verified row order in `violation_report.csv`. Fixed: added sort-order sub-check to the `report_structure` criterion (c1 = 5 pts columns + 5 pts sort order, max unchanged at 10). Changed in `v0/env.py` and re-propagated to v1/v2/v3.

2. **Recommendations list content not evaluated (Section 3, criterion 2)** — `prompt.md` specifies that the `recommendations` list must contain one string per qualifying department, course, and advisor; `step()` only verified the summary counts, leaving the list content unchecked. Fixed: re-weighted `recommendations_accuracy` (c7) from 4+3+3 pts (summary only, total 10) to 3+2+2 pts for summary + 3 pts for recommendations coverage; the coverage check verifies that every department code, course ID, and advisor name meeting its alert threshold is present in the submitted list. Max score remains 100. Changed in `v0/env.py` and re-propagated to v1/v2/v3.

3. **Missing tiebreaker in `by_department` sort (Section 4, criterion 7)** — `prompt.md` required `by_department` sorted "by violation count descending" with no tiebreaker, while `top_violated_courses` had an explicit "course identifier ascending" tiebreaker. Added "with department code ascending as a tiebreaker" to `by_department` wording for consistency and unambiguity. Changed in `v0/prompt.md` and re-propagated to v1/v2/v3.

Post-fix v3 reward: 1.0 (100/100) — all 8 criteria pass.

## Hardening (M0 + M1 + M3 + M5)

Applied on top of `environments/standard/prerequisite_violation_analysis`; `step()` and `_compute_ground_truth()` are byte-identical to SOURCE, and the `data.py` change is additive only (a fixed, non-scaling methodology document `audit_methodology.md`; per-version `SCALE` blocks preserved — after propagation the four `data.py` files differ from each other only in `SCALE`).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 6 route-narrating paragraphs to 5: scenario/goal, a pointer to the policy and reference documents as the authoritative specification, the verbatim deliverable contract (the `violation_report.csv` sort/columns paragraph and the `policy_recommendations.json` structure paragraph survive word for word), and the final-response summary requirement (verbatim). `data.py` gains a new fixed workspace document `audit_methodology.md` carrying every rule that previously lived only in the prompt: scope (approved registrations only), the explicit semester chronology and the strictly-prior-semester convention, the two violation types with their exact labels (`missing` / `grade_insufficient`), the best-prior-grade / strictly-below-minimum rule, one-violation-per-unsatisfied-prerequisite with (student, course, prerequisite, semester) dedup, the pointer to the enforcement-policy severity rules, and the override matching key (student + course + prerequisite) with yes/no + reason capture. Severity tier definitions were already discoverable in `enforcement_policy.yaml` (`severity_classification` descriptions and rule expressions) and were deleted from the prompt without duplication.
- **M1 JSON-encoded string filters**: `list_courses` takes `filter` with supported properties `department` (string), `level` (integer); `search_registration_attempts` takes `filter` with `student_id`, `course_id`, `semester`, `outcome` (enum-validated against 'approved'/'denied'/'waitlisted'). Both params are typed `Any = None`; validation is layered, one error per call: dict body → `invalid_request` ("Serialize it to a JSON string"), malformed JSON → `invalid_json` with line/column/char, non-object → `invalid_request`, unsupported key → supported-property list, wrong-typed value → `body.filter.<key> should be ..., instead was '<shape>'.`
- **M3 deep-nested records**: `list_students` and `list_prerequisites` return `{"object": "list", "results": [...], "has_more", "next_cursor"}` (cursor pagination, no total/total_pages); `get_course_prerequisites` returns the same nested rule records in a non-paginated list. Traps kept: student display name at `properties.Name.title[0].plain_text`, categorical values (Major / Academic Standing / Minimum Grade) at `properties.<K>.select.name`, numbers at `properties.<K>.number`, foreign keys at `properties.Course.relation[0].id` / `properties.Requires.relation[0].id`.
- **M5 unbounded bulk export**: new tool `export_registration_ledger()` returns every registration attempt joined with its recorded transcript grade (`student_id`, `course_id`, `semester`, `outcome`, `grade`) as ONE JSON string (`{record_count, records}`), no pagination. Measured `len(raw)//4`: **~17.6k tokens at v0** (629 records; survivable but expensive) and **~117.6k tokens at v3** (4,215 records; echoing it into context is fatal under a ~70k response budget — it must be consumed inside the programmatic sandbox and filtered before printing). Because approved registrations and transcript rows correspond 1:1 in this data, the export is genuinely sufficient for the core violation-filtering step; all paginated/per-entity tools remain available as the safe alternative.

Per-tool return-shape map:
| tool | success shape | error shape |
|---|---|---|
| `list_students` | native dict, M3 nested list w/ cursor | `_error` dict |
| `get_student_transcript` | native dict `{student_id, records}` | `_error` dict |
| `list_courses` | native dict w/ total/total_pages (M1 filter param) | `_error` dict |
| `get_course_prerequisites` | native dict, M3 nested rule list | `_error` dict |
| `list_prerequisites` | native dict, M3 nested list w/ cursor | `_error` dict |
| `search_registration_attempts` | native dict w/ total/total_pages (M1 filter param) | `_error` dict |
| `get_departments` | native dict `{departments}` | — (parameterless) |
| `export_registration_ledger` | ONE JSON string `{record_count, records}` (M5) | — (parameterless) |

Error contract: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` — sharing no keys with any success shape. Not-found → `404 object_not_found` ("Could not find student/course with ID: ..."), bad input → `400 validation_error` / `400 invalid_json` / `400 invalid_request`. Unknown student/course IDs now 404 on the per-entity tools; non-integer or non-positive page/page_size → `400 validation_error`.

Completeness audit (step() criterion → info source after M0):
| criterion | source |
|---|---|
| report_structure | prompt (verbatim contract: filename, exact column list and order) |
| violation_count | audit_methodology.md (scope, violation definition, dedup rule) + grade_scale.json |
| violation_identification | audit_methodology.md (per-prerequisite checks, prior-semester convention, best-grade rule) + grade_scale.json |
| severity_classification | enforcement_policy.yaml `severity_classification` (+ audit_methodology.md pointer) |
| override_status | audit_methodology.md (match on student + course + prerequisite; yes/no + reason) + advisor_overrides_batch_*.json |
| recommendations_structure | prompt (verbatim contract: top-level keys, summary fields, sort orders, tiebreakers) |
| recommendations_accuracy | prompt contract + enforcement_policy.yaml (`thresholds`, `recommendation_rules`) |
| response_summary | prompt (final-response paragraph: totals, overridden vs unresolved, per-severity counts) |

verify() results (hardened surface: M3 cursor walk + nested-property parsing, M1 JSON-string filters incl. per-department course fetch and outcome=approved registration search, M5 export consumed once in memory and cross-checked against the paginated view):
- v0: reward 1.0 (100/100), 86 tool calls.
- v3: reward 1.0 (100/100), 448 tool calls.
- `validate_envs`: 4/4 versions pass.
- Negative-path smoke tests all pass: malformed M1 JSON → `invalid_json` with line/column/char; dict-instead-of-string → `invalid_request`; JSON array body → `invalid_request`; unsupported filter key / wrong-typed values / bad outcome enum → layered `validation_error` messages; nonexistent course/student → 404 `object_not_found`; undefined student_id and non-integer page → 400 `validation_error`.
