## Task Topic

Flag high-risk rental applicants by cross-referencing credit score thresholds, national eviction database records, income-to-rent ratio calculations, and previous landlord reference patterns to generate a prioritized review queue with risk scores.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 40             | 8                   |
| v1      | 80             | 16                  |
| v2      | 160            | 24                  |
| v3      | 320            | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Applicant income data and property rent amounts live exclusively in workspace files (JSON and CSV), while credit reports, eviction records, and landlord references are only accessible through tool calls. Reference verification status is stored in workspace TXT files and must be cross-referenced with tool-returned reference IDs. Risk scoring parameters, tier thresholds, and eviction severity weights reside in workspace configuration files (YAML, CSV, MD).

- **Multi-Hop Reasoning**: Solving the task requires a dependency chain of length ≥ 3. For example, to compute the income-to-rent ratio sub-score: list applicants via tool → read the applicant's property_id → look up the monthly rent from workspace CSV files → read income from workspace JSON files → compute the ratio → apply the configured threshold from workspace YAML. Similarly, the reference sub-score requires: retrieve references via tool → match reference IDs against verification status in workspace TXT files → filter to verified only → compute ratings → apply penalties from configuration.

- **Conditional Constraints**: Risk scoring depends on multiple configurable thresholds (credit base threshold, income minimum ratio, eviction recency window, reference verification status) that are read from workspace configuration files rather than hard-coded. Tier assignment and review queue inclusion depend on the computed risk score crossing configured boundaries.

- **Deliverable Constraints**: The output CSV requires exact column ordering, specific rounding (2 decimal places for risk_score and income_to_rent_ratio), tie-breaking rules for both sorting (risk_score DESC then applicant_id ASC) and primary_flag assignment (alphabetical), and a prescribed format for missing data (N/A for avg_reference_rating when no verified references exist).

## Harness Report

- v3 reward: 1.0 (perfect score, 100/100).
- Eval criteria count: 6 (`file_format` 10, `applicant_set` 20, `risk_scores` 25, `sorting` 15, `risk_tiers` 15, `summary_response` 15).
- Solver source-access: clean black-box. The solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; `env.py`, `data.py`, and the v0/v1/v2 sources were not opened during Section 2. No step-6 escalation triggered.
- Section 1 structural integrity: passed. Top-level has only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (rows 40/80/160/320 = 1x/2x/4x/8x; files 8/16/24/32 = base + 0/N/2N/3N with N=8).
- Section 3 / 4 review: prompt-step alignment is complete (every deliverable scored, no hidden criteria); `step` derives ground truth dynamically from `data.db` and workspace files (no hard-coded counts); prompt has no headings/bullets/tool-names/absolute counts.
- Issues found: none. No fixes required.
- Blockers: none.

**Re-verification (2026-07-02):** Full Section 1–5 pass on v3 (320 applicants, 32 workspace files). Structural integrity ✓ (no artifacts, byte-identical env.py/prompt.md, SCALE-only data.py diffs). Black-box solver built from `prompt.md` + `get_assistant_tools()` only achieved reward 1.0 (100/100) on first attempt without escalation to env.py. Env quality ✓ (all 6 criteria map to explicit prompt requirements; ground truth is dynamic). Prompt quality ✓ (no title/headings/bullets/tool-names/absolute counts). Runtime artifacts cleaned from all v0–v3 directories.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/applicant_risk_scoring`; `step()` ground truth, criteria, and weights are unchanged.

- **M2 mixed return shapes** (per-tool map):
  | tool | return shape |
  |---|---|
  | `list_applicants` | native dict — deep-nested list object with cursor pagination (`{"object": "list", "results", "has_more", "next_cursor"}`) |
  | `get_applicant_details` (new detail lookup over the same `applicants` table) | native dict — deep-nested record |
  | `get_credit_report` | JSON-encoded string of a deep-nested record |
  | `check_eviction_history` | MCP-style envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) around a nested list object |
  | `get_landlord_references` | Python-repr string of a nested list object (single quotes; `json.loads` fails, needs `ast.literal_eval`) |
  | `get_property_details` | plain `key: value` text (flat single record) |
  2/6 tools stay native so the surface cannot be assumed to be all-string. Descriptions state what each tool returns, never how it is encoded.
- **M3 deep nesting**: record fields live 3–4 levels deep in Notion-style property objects — `properties.Name.title[0].plain_text` (NOT `.text.plain_text`), `properties.Reason.select.name`, `properties.Property.relation[0].id`, `properties["Eviction Date"].date.start`, numbers at `properties.X.number`. `list_applicants` uses `has_more`/`next_cursor` pagination instead of `total`/`total_pages`.
- **Error contract**: tools never raise. Not-found → `{"status": 404, "object": "error", "code": "object_not_found", "message", "request_id"}`; bad input → `_error(400, "validation_error", "body.<param> should be a positive integer, instead was '...'.")`. JSON-string tools return the error JSON-encoded. Success and error responses share no keys except the `object` discriminator (`"error"` vs the entity type), forcing a branch on shape.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 4: scenario/goal (incl. the verbatim queue-membership sentence), a pointer to the policy/configuration documents as the authoritative specification, the verbatim deliverable contract (filename, exact column list/order, field definitions, precision, sort keys, tie-breakers), and the verbatim final-summary requirement. Removed: all per-dimension formula narration, tool hand-holding, and per-file navigation. `data.py` change (additive only, fixed non-scaling doc): new `scoring_methodology.md` carries the precise formulas previously stated only in the prompt — credit/income/eviction/reference sub-score formulas, strict-vs-inclusive boundary conventions, the 365.25 day-year and recency rule, the 0.5 default severity for unlisted reasons, the VERIFIED-only reference filter, aggregate-rating definition, weighting/rounding, highest-qualifying-tier rule, queue threshold inclusion, and primary-flag tie-break. `SCALE` blocks preserved per version; per-version `data.py` files differ only in `SCALE`.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| file_format (10) | prompt ¶3 (verbatim contract: filename, columns, order) |
| applicant_set (20) | prompt ¶1/¶3 (score ≥ review threshold) + `risk_config.yaml` (`review_threshold`) + `scoring_methodology.md` (score computation) |
| risk_scores (25) | `scoring_methodology.md` (all four sub-score formulas, caps, defaults) + `risk_config.yaml` (parameters) + `eviction_severity.csv` + income/rental/verification workspace files |
| sorting (15) | prompt ¶3 (risk_score DESC, applicant_id ASC, verbatim) |
| risk_tiers (15) | `scoring_methodology.md` (highest-qualifying-tier rule) + `risk_config.yaml` (`risk_tiers` bounds) |
| summary_response (15) | prompt ¶4 (verbatim: total screened, queue count, per-tier counts, highest-risk name + score) |

### Verification

- v3 (320 applicants): `verify()` reward **1.0** consuming only the hardened surface (envelope unwrap, `json.loads`, `ast.literal_eval`, key:value parsing, nested-property walking, cursor pagination).
- v0 (40 applicants): `verify()` reward **1.0** with **172** tool calls (floor: 15).
- Negative-path smoke tests: nonexistent IDs → 404 error objects (dict and JSON-string forms); non-integer / None / bool / float parameters → 400 `validation_error` dicts on every tool, no exceptions; repr returns fail `json.loads` and parse with `ast.literal_eval`; cursor pagination walks 6 pages at v0 covering all 40 applicants.
- `env.py` and `prompt.md` byte-identical across v0–v3; runtime artifacts removed.
