## Task Topic

Flagging grant applications with high-risk budget allocations requires analyzing proposed expense line items, historical awardee financial reports, institutional overhead rate tables, and PI publication-to-funding ratios to identify proposals exceeding category benchmarks, generating a risk assessment report for panel review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Information Scattering**: PI publication and funding data lives exclusively in workspace JSON batch files, while application details, expense items, historical reports, and institution info are only accessible through tools. Benchmark thresholds and scoring rules reside in separate YAML, JSON, and CSV config files. Solving the task requires cross-referencing all of these sources.
- **Multi-Hop Reasoning**: Each application requires a dependency chain of length ≥ 3: retrieve application → get expense items and aggregate by category → read benchmarks from YAML → compute flags; separately, get PI profile → find PI in batch JSON files → compute pub-to-funding ratio → apply thresholds from JSON config. These chains converge into a single risk score.
- **Conditional Constraints**: Risk scoring follows multi-threshold rules (critical vs. warning thresholds for pub-funding ratio and historical variance) with different point allocations, and the category benchmark score scales with the number of categories in the budget.
- **Deliverable Constraints**: The output CSV has a fixed 15-column schema, exact column order, specific formatting for boolean flags and category lists, and mandated sort order with tie-breaking rules.

## Harness Report

- v3 reward: **1.0** (100/100).
- Eval criteria (7 total, 100 pts max):
  | criterion | pts | description |
  |---|---|---|
  | report_file_structure | 15 | CSV exists, all 15 columns present in order |
  | application_count | 10 | all pending_review apps covered |
  | risk_tier_accuracy | 20 | correct Low/Medium/High/Critical per app |
  | risk_score_accuracy | 20 | numeric score within 0.1 of ground truth |
  | category_flag_accuracy | 15 | correct categories_over_benchmark per app |
  | sort_order | 10 | risk_score desc, app_id asc tie-break |
  | response_summary | 10 | High/Critical app IDs present in text response |
- Structural checks (Section 1): PASS. Top-level contains exactly README.md + v0/..v3/. Each vN/ contains exactly data.py, env.py, prompt.md. env.py and prompt.md byte-identical across all four versions (`diff` returns 0). data.py diffs are confined to the `SCALE` block (rows_per_table: 50/100/200/400; num_workspace_files: 10/20/30/40).
- Solvability (Section 2): PASS. Black-box solver (prompt.md + get_assistant_tools() only; env.py/data.py/README.md not read during solve phase) achieved reward=1.0 first attempt. No step-6 escalation required. v3 has 160 pending applications.
- Env quality (Section 3): PASS. All 7 step() criteria correspond to explicit prompt.md requirements. Ground truth computed dynamically from data.db + workspace files (no hardcoded counts). Score tolerance 0.1 is appropriate given rounding rules. Minor note: C7 (response_summary) only checks that High/Critical app IDs appear in the response string; it does not individually verify PI name / institution / tier per line, slightly under-checking the prompt's "including its application ID, PI name, institution name, risk score, and tier" requirement — but this does not affect solvability.
- Prompt quality (Section 4): PASS. No title/heading at top; no bold section headers; deliverables woven into prose (no lists); no tool names, internal filenames, or env.py internals mentioned; all column names explicit; wording scale-invariant.
- Issues found: None.
- Fixes applied: None.
- Blockers: None.


## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/budget_risk_assessment`; `step()` / `_compute_ground_truth()` scoring are unchanged. Only the `@tool` surface, `verify()`, `prompt.md` (M0), and `data.py` (M0, additive policy text only) changed.

- **M2 mixed return shapes** (per-tool map):
  | tool | success shape |
  |---|---|
  | `list_applications` | native dict — deep-nested list object (`{"object": "list", "results": [...], "has_more", "next_cursor"}`) |
  | `get_application_budget` | JSON-encoded string of a nested list object (line_item records + `application` echo) |
  | `get_pi_profile` | plain `key: value` text (one flat record) |
  | `get_pi_historical_reports` | Python-repr string (single quotes; `json.loads` fails, needs `ast.literal_eval`) |
  | `get_institution_info` | MCP-style envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) |
  | `list_expense_categories` | native flat dict (unchanged from SOURCE) |
  2/6 tools stay native so the encoding cannot be assumed uniform. Descriptions state what is returned, never how it is encoded.
- **M3 deep nesting**: record fields live 3–4 levels deep in Notion-style property objects — display text at `properties.Title.title[0].plain_text`, category-ish values at `properties.<X>.select.name`, foreign keys at `properties.PI.relation[0].id` / `properties.Institution.relation[0].id`, amounts at `properties.<X>.number`, dates at `properties.<X>.date.start`. List tools use cursor pagination (`has_more`/`next_cursor`) instead of `total`/`total_pages`.
- **Error contract**: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` (JSON-string form for the JSON-string tool), sharing no success keys other than the generic `"object"` discriminator. Not-found → `404 object_not_found` ("Could not find <entity> with ID: <id>."); bad input → `400 validation_error` one error at a time (`body.status is not a supported status value...`, `body.app_id should be an integer, instead was '...'`). The SOURCE `{"error": ...}` soft-failure dicts were removed.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 4: scenario/goal (naming the four risk dimensions), a pointer to the policy/configuration documents and workspace funding records as the authoritative spec, and the two verbatim deliverable-contract paragraphs (CSV filename/columns/order/formatting/sorting; final-response summary requirement). Removed: tool hand-holding, sequencing scaffolds ("Begin by..."), per-file navigation (YAML/JSON/CSV descriptions, `pi_funding_records` layout), and formula/threshold restatements that are discoverable in `category_benchmarks.yaml`, `risk_scoring_config.json`, `overhead_rate_tiers.csv`, and `review_guidelines.md`.

`data.py` change (additive only, all versions, per-version SCALE preserved): `review_guidelines.md` gained a "Scoring and tier assignment conventions" section covering the previously prompt-only rules — total score = sum of four components; two-decimal rounding before threshold comparison; max_pct-only strict-greater flagging (warning_pct informational); half-open tier intervals with the ≥ Critical-minimum exception; zero/missing funding → ratio 0.0; no historical reports → variance 0.0.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| report_file_structure (15) | prompt para 3 (verbatim contract: filename, 15 columns, order) |
| application_count (10) | prompt paras 1 & 3 ("every application currently awaiting review"); pending apps enumerable via the status-filtered listing tool |
| risk_tier_accuracy (20) | `risk_scoring_config.json` `risk_tiers` + `review_guidelines.md` half-open boundary / Critical-minimum convention |
| risk_score_accuracy (20) | `risk_scoring_config.json` `scoring_rules` + thresholds; `category_benchmarks.yaml` max_pct; `overhead_rate_tiers.csv` approved maxes; `review_guidelines.md` (sum of components, rounding, ratio/variance formulas with worked example, edge-case defaults) |
| category_flag_accuracy (15) | `category_benchmarks.yaml` (max_pct + "Exceeding max_pct triggers a flag" note) + `review_guidelines.md` (same-category summing, strict-greater convention) + prompt para 3 (column formatting: ", "-joined, alphabetical, `none`) |
| sort_order (10) | prompt para 3 + `review_guidelines.md` (risk_score desc, app_id asc) |
| response_summary (10) | prompt para 4 (verbatim final-response requirement) |

### Verification

- v3: `verify()` reward **1.0** (100/100), 657 tool calls (160 pending applications).
- v0: `verify()` reward **1.0** (100/100), 83 tool calls (≥ 15 floor satisfied; 20 pending applications).
- Negative-path smoke tests pass: 404 `object_not_found` error dicts for nonexistent app/PI/institution IDs (including via the repr-string and JSON-string tools), `validation_error` for unsupported status enum, undefined status, non-integer page/app_id/pi_id (dict passed where integer required), one error per call.
- `env.py` and `prompt.md` byte-identical across v0..v3; per-version `data.py` differs only in the `SCALE` block; no runtime artifacts committed.
