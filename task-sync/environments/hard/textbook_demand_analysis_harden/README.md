## Task Topic

Monitor high-demand textbook availability by cross-referencing course enrollment rosters, current library inventory counts, historical circulation data, and student reservation queues to identify shortage risks, outputting a procurement priority list with recommended purchase quantities.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Shortage risk classification depends on a weighted scoring formula with four normalized components (demand-supply ratio, reservation pressure, circulation intensity, waitlist factor), where weights and risk thresholds are defined in a workspace policy file. Purchase quantities follow a formula involving a target ratio and minimum order floor.
- **Information Scattering**: Course enrollment headcounts and waitlist counts live exclusively in workspace CSV files, while textbook-course mappings, inventory counts, circulation statistics, and reservation queues are only accessible through tool calls. Procurement policy parameters, budget allocations, and supplier discount schedules are spread across YAML, JSON, and CSV config files.
- **Multi-Hop Reasoning**: The dependency chain is: read enrollment files → call tool to get course-textbook mappings (required only) → call tool for inventory per textbook → call tool for circulation stats → call tool for reservations → read policy for scoring weights → compute risk scores → read supplier discounts → compute purchase quantities and costs → produce sorted output.

## Harness Report

- v3 reward: **1.0** (100/100)
- Eval criteria: 8 — `output_file_exists` (10 pts), `correct_columns` (10 pts), `correct_textbooks` (15 pts), `correct_demand` (15 pts), `correct_risk_scores` (15 pts), `correct_risk_levels` (10 pts), `correct_quantities` (15 pts), `correct_sort_order` (10 pts)
- Issues found and fixed: **none**

**Section 1 — Structural integrity:** passed. Top-level contains only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md` (no stray databases, workspace dirs, or bytecode). `env.py` and `prompt.md` are byte-identical across all four versions (`diff` returns no output). `data.py` differs across versions only in the `SCALE` block (`rows_per_table`: 50/100/200/400; `num_workspace_files`: 10/20/30/40 — correct 2×/4×/8× and +N/+2N/+3N ratios).

**Section 2 — Solvability at v3:** `python data.py --db_path data.db --workspace workspace` ran without error. Solver written using only `v3/prompt.md` and `env.get_assistant_tools()`. Used `export_library_dataset()` for the full joined dataset, read enrollment batch CSVs for demand, read `procurement_policy.yaml` and `procurement_methodology.md` for scoring formula and thresholds, `supplier_discounts.csv` for cost brackets. Produced `workspace/procurement_priority_list.csv` with 235 textbooks. `env.step(summary)` returned reward=1.0 on the first run; all 8 criteria passed.

**Section 3 — Env quality:** All 8 `step()` criteria map directly to explicit requirements in `prompt.md`. Ground truth is recomputed at eval time from `data.db` and workspace files — no hard-coded counts or distribution assumptions. Risk-score tolerance (`abs(diff) < 0.01`) is appropriate for 4-decimal scores. Sort-order tie-breaking uses `abs(rs1 - rs2) < 0.001`, which is correct. No hidden criteria; no over-normalization beyond `.strip().lower()` on risk level (prompt does not specify case).

**Section 4 — prompt.md quality:** No title or heading; no bold section headers; column list embedded in prose (not a bullet list); computation logic deferred to methodology documents (not coded in prompt); no tool names or internal filenames; 14 output columns named explicitly; sort order and scope are unambiguous; wording is scale-invariant ("all course sections", no absolute counts).

## Hardening (M0 + M1 + M3 + M5)

Applied on top of `environments/standard/textbook_demand_analysis`; `step()` scoring and ground truth are unchanged. Only the tool surface, `verify()`, `prompt.md` (M0), and `data.py` (M0, additive policy document only) changed.

- **M1 JSON-encoded string filter**: `get_department_courses` is replaced by `search_courses`, which takes a single `filter` parameter typed `string` — a JSON-encoded object supporting `department`, `semester`, `section` — plus `page`/`page_size`. Malformed JSON → `invalid_json` with line/column/char; a dict where a string is required → `invalid_request` ("Serialize it to a JSON string..."); unsupported keys and wrong-typed values → `validation_error`, one error per call.
- **M3 deep-nested records + cursor pagination**: `list_departments`, `search_courses`, `get_course_textbooks`, `get_textbook_info`, and `get_inventory_status` return Notion-style records (`{"object": ..., "id": ..., "properties": {...}}`) with the deliberate traps: display text at `title[0].plain_text`, category values at `select.name`, foreign keys at `relation[0].id` (`get_course_textbooks` records carry the textbook ID only in `properties.Textbook.relation[0].id`). List tools return `{"object": "list", "results", "has_more", "next_cursor"}`; `search_courses` is genuinely paginated (max 20/page). `get_inventory_status` no longer pre-sums totals — consumers must sum per-branch `Total Copies` / `Available Copies` numbers.
- **M5 unbounded bulk export**: new tool `export_library_dataset()` returns the complete dataset (courses, textbooks, course-textbook mappings, inventory, circulation, reservations) as ONE JSON string, no pagination. Measured size: **~14.9k tokens at v0** (≤ 20k bound), **~120.4k tokens at v3** (≥ 100k bound) — echoing it into context at v3 is fatal; it must be consumed inside the programmatic sandbox. All paginated / per-entity tools remain available as the safe alternative.
- **Unchanged (native) tools**: `get_circulation_stats`, `get_pending_reservations`, `list_textbook_ids` keep their original native return shapes.

Per-tool return-shape map:

| tool | success shape | error shape |
|---|---|---|
| `list_departments` | native dict, M3 list of `department` records | — |
| `search_courses` | native dict, M3 list of `course` records, cursor pagination | `_error` dict |
| `get_course_textbooks` | native dict, M3 list of `course_textbook` records (textbook id in relation) | `_error` dict (404/400) |
| `get_textbook_info` | native dict, M3 `textbook` detail record | `_error` dict (404/400) |
| `get_inventory_status` | native dict, M3 list of `inventory_holding` records (no totals) | `_error` dict (404/400) |
| `get_circulation_stats` | native flat dict (unchanged) | `_error` dict (404/400) |
| `get_pending_reservations` | native flat dict (unchanged) | `_error` dict (404/400) |
| `list_textbook_ids` | native list of ints (unchanged) | — |
| `export_library_dataset` | ONE JSON-encoded string (M5) | — |

Error contract: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` — not-found → `404 object_not_found`, bad input → `400 validation_error` / `400 invalid_json` / `400 invalid_request`, layered one error per call. Success and error responses share no keys except the `object` type discriminator mandated by the M3 record shape (values always differ).

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 9 route-narrating paragraphs to 4: scenario/goal, a pointer to the methodology + policy/configuration documents as the authoritative specification, the verbatim deliverable contract (file name, exact column list and order, sort keys and tie-breakers — unchanged word for word), and a final-response summary requirement. All formula/route sentences were deleted; rules that existed only in the prompt (risk-component normalizations and caps, 4-decimal rounding, threshold boundary convention, cost/discount computation and 2-decimal rounding, alphabetical department assignment) were moved into a new workspace document `procurement_methodology.md` written by `data.py` (the only `data.py` change; additive, fixed/non-scaling, `SCALE` blocks preserved per version).

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| output_file_exists | prompt (verbatim deliverable contract) |
| correct_columns | prompt (verbatim deliverable contract) |
| correct_textbooks | procurement_methodology.md (required-only scope) + procurement_policy.yaml `demand_calculation` |
| correct_demand | procurement_methodology.md (enrolled + waitlisted definition) + enrollment_batch_*.csv |
| correct_risk_scores | procurement_methodology.md (component formulas, normalizations, 4-decimal rounding) + procurement_policy.yaml weights |
| correct_risk_levels | procurement_methodology.md (≥-boundary convention) + procurement_policy.yaml thresholds & tier scores |
| correct_quantities | procurement_methodology.md + procurement_policy.yaml `purchase_quantity_formula` (target ratio, minimum order) |
| correct_sort_order | prompt (verbatim deliverable contract) |

### Verification

- `verify()` re-solves the task through the hardened surface only: consumes the bulk export once in memory (core required-mapping filter), walks `list_departments`/`search_courses` with JSON-string filters and `has_more`/`next_cursor` pagination, parses nested `title[0].plain_text` / `select.name` / `relation[0].id` paths, sums per-branch inventory, and cross-checks the export-derived mapping against the per-course tool-derived mapping.
- v0: reward **1.0** (≥ 15 tool calls; export ≈ 14.9k tokens). v3: reward **1.0** (export ≈ 120.4k tokens).
- Negative-path smoke tests passed: malformed M1 JSON → `invalid_json` with line/column/char; dict-typed filter → `invalid_request`; unsupported filter key and wrong-typed value → `validation_error`; nonexistent course/textbook IDs → 404 `object_not_found` error dicts on all five lookup tools; wrong-typed IDs → 400 without raising.
