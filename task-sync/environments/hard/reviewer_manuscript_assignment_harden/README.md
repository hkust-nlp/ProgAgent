## Task Topic

Assigning manuscripts to reviewers requires matching manuscript keywords, reviewer publication histories, declared conflicts of interest, and past review quality scores to create an optimized and conflict-free reviewer assignment matrix for the editor.

## Version Overview

| Version | `rows_per_table` | `num_workspace_files` |
|---------|------------------|-----------------------|
| v0      | 20               | 10                    |
| v1      | 40               | 20                    |
| v2      | 80               | 30                    |
| v3      | 160              | 40                    |

Scaling follows the standard formula: rows grow as 1×/2×/4×/8× of the v0 base, and workspace files grow as base/base+N/base+2N/base+3N where N = base (10).

**Structural dimensions used:**

- **Information Scattering**: Manuscript keywords and reviewer expertise keywords live exclusively in workspace CSV/JSON files, while manuscript metadata (field, submission date), reviewer capacity limits, conflict-of-interest declarations, and historical review quality/timeliness scores are only available through tool calls. Solving the task requires combining both sources.
- **Conditional Constraints**: Reviewer eligibility depends on multiple cross-table conditions — absence of declared conflicts (conflicts_of_interest table vs. manuscripts), average historical quality score meeting a minimum threshold (review_history table + policy config file), and remaining round capacity (reviewers table, decremented during assignment).
- **Multi-Hop Reasoning**: The assignment score for each manuscript–reviewer pair requires a chain of at least three hops: (1) retrieve manuscript keywords from workspace files, (2) retrieve reviewer expertise keywords from workspace files, (3) compute Jaccard similarity, (4) retrieve historical quality/timeliness scores via tool call, (5) combine using weights from the YAML scoring rubric.
- **Deliverable Constraints**: The output CSV must have exact column names, exact column order, scores rounded to two decimal places, and rows sorted by submission date then manuscript ID.

## Harness Report

- v3 reward: **1.0** (total_score 110/110)
- Eval criteria: 7 — file_format (10), all_manuscripts_assigned (15), no_conflict_violations (20), capacity_respected (15), quality_threshold (15), assignment_quality (25), db_assignments_recorded (10).
- Scale: 160 pending manuscripts, 160 reviewers (v3). All 480 assignments made (3 per manuscript). Average assignment score 133.74.
- Structural checks: `env.py` and `prompt.md` byte-identical across v0–v3 (confirmed via `diff`); only `SCALE` block differs in `data.py`. No stale artifacts in any `v_n/` at completion.
- Source-access: clean — only `v3/prompt.md` was read before writing the solver; public interface discovered via `Task_Env.get_assistant_tools()` only; `env.py` not opened until Section 3 review.
- prompt.md quality: passes all formatting checks (no title, no bold headers, no lists, all computation in natural language, no tool/file/env internals leaked, exact column names specified, scale-invariant wording).
- Issues found and fixed: none. First solver run returned reward 1.0 with no env or prompt changes required.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/reviewer_manuscript_assignment`. Ground truth (`_compute_ground_truth`) and the six original scoring criteria are unchanged; `step()` gains one DB-state criterion for the M4 write API (10 pts, total now 110). `env.py`/`prompt.md`/`data.py` are identical across v0–v3 except each version's original `SCALE` block.

- **M1 JSON-string parameters**: `list_manuscripts` and `list_reviewers` each take a single `filter` parameter that must be a JSON-encoded string (`'{"field": "Physics", "min_pages": 10}'` / `'{"institution": "MIT", "min_capacity": 3}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values returns recoverable API-style errors. Pagination params are also validated (`body.offset should be an integer, instead was ...`).
- **M4 nested write payload**: new `create_review_assignment(payload)` tool (SOURCE had no write tool; the "record assignments in the system" deliverable was added per the M4 no-write-tool exception). Notion-style nested body: `parent.type='review_panel'` + `parent.manuscript_id`, `properties.Reviewer.reference.reviewer_id`, optional `Note` rich_text. Validation is layered — one error at a time, messages like `body.parent.manuscript_id should be a non-empty string, instead was 'undefined'.` Business checks: manuscript exists & pending, reviewer exists, duplicate registration rejected. Writes one row into a lazily-created `review_assignments` table (data.py untouched); step criterion 7 (`db_assignments_recorded`) scores the fraction of ground-truth (manuscript, reviewer) pairs recorded.
- **Return shapes**: all success responses remain native dicts (M2 not assigned). Errors are always the `{status, object, code, message, request_id}` dict — no keys shared with any success shape; tools never raise. Not-found ids return 404 `object_not_found` (previously `{"error": ...}` or silent empty lists).

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 4: scenario/goal (records in the editorial system, keyword/expertise data partitioned across files), a pointer to the policy/methodology documents as the authoritative spec (+ the load-bearing hint that processing order consumes capacity, + the M4 "record every assignment" requirement), then the verbatim deliverable contract and final-response paragraphs from SOURCE (with one appended sentence confirming DB recording). Deleted: tool hand-holding, file-by-file navigation with filenames/columns/keys, and the step-by-step algorithm narration.

`data.py` change (additive only, per M0 rule 4): new fixed document `assignment_methodology.md` carrying the previously prompt-only rules — processing order (submission date asc, manuscript_id asc), eligibility (no declared COI / avg quality ≥ policy threshold, no-history ⇒ ineligible / remaining capacity), Jaccard definition (|∩|/|∪|, empty-vs-empty = 0), arithmetic-mean averages, rank-order assignment of top-K with immediate capacity deduction. Formula weights/scale factors were already in `scoring_rubric.yaml`; tie-breakers already in `load_balancing_guidelines.txt`; threshold already in `assignment_policy.json` + `quality_tiers.md`.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| file_format (10) | prompt para 3 (verbatim contract) |
| all_manuscripts_assigned (15) | prompt para 1 ("every pending manuscript") + assignment_policy.json (`reviewers_per_manuscript`) |
| no_conflict_violations (20) | assignment_methodology.md (eligibility rule 1); conflicts discoverable via query tool |
| capacity_respected (15) | assignment_methodology.md (eligibility rule 3) + load_balancing_guidelines.txt (hard capacity rule) |
| quality_threshold (15) | assignment_methodology.md (eligibility rule 2) + assignment_policy.json (`min_quality_threshold`) + quality_tiers.md |
| assignment_quality (25) | assignment_methodology.md (order, scoring, selection) + scoring_rubric.yaml (weights/scale factors/formula) + load_balancing_guidelines.txt (tie-breakers) |
| db_assignments_recorded (10) | prompt para 2 ("record every individual reviewer assignment in the editorial system") |

### Verification

- v3: `verify()` reward **1.0** (110/110), 1152 tool calls.
- v0: `verify()` reward **1.0** (110/110), 144 tool calls (≥ 15 floor met).
- Negative-path smoke tests all pass: malformed M1 filter JSON → `invalid_json` with line/column/char; dict-instead-of-string → `invalid_request`; unsupported/wrong-typed filter keys → `validation_error`; M4 layered payload errors surface one at a time from `body` down to `...reference.reviewer_id`; unknown ids → 404 `object_not_found`; duplicate panel registration → 400.
