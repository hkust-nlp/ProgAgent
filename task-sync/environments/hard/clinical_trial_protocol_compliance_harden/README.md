## Task Topic

A health authority updates clinical trial safety protocols. The process cross-references the new guidelines, active trial phase statuses, patient consent form versions, and site audit histories to produce a compliance action plan with prioritized protocol amendments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 8                   |
| v1      | 60             | 16                  |
| v2      | 120            | 24                  |
| v3      | 240            | 32                  |

The scaling ratios follow the standard progression: rows scale at 2x/4x/8x, and workspace files scale at base+N/base+2N/base+3N where N=8 (the v0 base).

**Structural dimensions used:**

- **Conditional Constraints**: Amendment type and deadline are determined by multi-factor business rules involving guideline severity, consent form status, site audit findings, and priority score brackets. Thresholds and scoring weights reside in workspace configuration files (severity_matrix.json, amendment_priority_rules.yaml, phase_requirements.csv).

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Trial metadata, consent records, and audit histories are only accessible via tools, while site risk scores (inspection reports), protocol deviation counts (trial dossiers), scoring parameters (severity matrix), and the new guidelines themselves are only available in workspace files. Solving the task requires combining both sources.

- **Multi-Hop Reasoning**: The priority score computation forms a dependency chain of length 4+: read new guideline → query matching active trials → for each trial, query consent forms and site audits → look up site inspection reports and trial dossiers from workspace → apply scoring matrix → determine amendment type via precedence rules → compute deadline from priority brackets.

## Harness Report

- v3 reward: 1.0 (100/100), confirmed after fixes.
- Eval criteria: 6 (action_plan_structure 15, trial_guideline_pairs 20, priority_scores 20, amendment_types 15, consent_update_report 15, sorting_and_deadlines 15).
- Solver source-access: clean black-box. Solved using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Section 1 structural integrity: passed; `env.py`/`prompt.md` byte-identical across v0..v3, only `SCALE` differs in `data.py`.
- Section 3/4 review: two evaluation-strictness gaps found and fixed (see below); prompt wording is scale-invariant prose with no tool-name leakage, and ground truth is computed dynamically.
- Issues + fixes:
  1. **Column order not enforced** — `prompt.md` requires the nine CSV columns "in this exact order", but `_eval_action_plan_structure` used a set comparison that ignored order. Fixed: converted to an ordered list and reduced partial credit from 15 → 12 when columns are present but mis-ordered. Full 15 pts still awarded when order is correct.
  2. **Consent report sort order not enforced** — `prompt.md` requires the JSON array to be "sorted by trial identifier in ascending order", but `_eval_consent_report` never checked the sort. Fixed: added a trailing sort check that deducts 2 pts when the array is unsorted.
  Both fixes applied to `v0/env.py` and propagated to v1..v3. Reward remains 1.0 after both fixes.
- Blockers: none.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/clinical_trial_protocol_compliance`; `step()`, `_compute_ground_truth()`, criteria weights, DB schema, row generation, and seeds are unchanged.

### M2 — mixed return encodings (per-tool shape map)

| Tool | Success shape | Error shape |
|---|---|---|
| `list_trials` | native dict, M3 nested list (`{"object": "list", "results", "has_more", "next_cursor"}`) | `_error` dict |
| `get_site_audits` | native dict, M3 nested list (no pagination: `has_more: false`) | `_error` dict |
| `get_trial_details` | JSON-encoded string of an M3 nested record | `json.dumps(_error(...))` |
| `list_sites` | JSON-encoded string of an M3 nested list with cursor pagination | `json.dumps(_error(...))` |
| `get_consent_forms` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) wrapping an M3 nested list | `_error` dict |
| `get_site_info` | plain `key: value` text (single flat record) | `_error` dict |
| `query_guidelines` | Python-repr string (single quotes; `json.loads` fails, needs `ast.literal_eval`) with cursor pagination | `_error` dict |

Tool descriptions state what is returned, never how it is encoded.

### M3 — deep-nested record structures

Trial, site, consent-form, and audit records are Notion-style, 3-4 levels deep: display text at `properties.<K>.title[0].plain_text` (NOT `.text.plain_text`), category values at `properties.<K>.select.name`, foreign keys at `properties.<K>.relation[0].id`, strings at `rich_text[0].plain_text`, dates at `date.start` (nullable), booleans at `checkbox`. List tools use cursor pagination (`has_more`/`next_cursor`) instead of `total`/`total_pages`.

### Error contract

Tools never raise. Not-found → `_error(404, "object_not_found", "Could not find <entity> with ID: <id>.")`; bad input → `_error(400, "validation_error", "body.<param> should be ..., instead was '...'.")`. Error objects (`{"status", "object": "error", "code", "message", "request_id"}`) share no informative keys with any success shape, so consumers must branch on shape. Negative paths smoke-tested: 404 on nonexistent trial/site (dict and JSON-string forms), non-integer `page`/`phase`, negative `page`, undefined `trial_id`.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 5: scenario/goal, a pointer to the policy/configuration documents as the authoritative spec, and the verbatim deliverable contracts (CSV filename + exact column order + sort/tie-break rules; JSON report filename + field definitions + ordering; final-summary requirement). Deleted: workspace filename navigation, the full priority-score formula walkthrough, and the amendment-type/deadline rule restatements. `data.py` change (additive only, fixed non-scaling doc): new `compliance_methodology.md` written into the workspace, containing the scope rule (active trials whose phase AND area fall in a guideline's lists), the six-component priority-score formula (with audit-penalty cap, latest-consent-by-approval-date convention, `missing` status, strictly-greater thresholds, and absent-file defaults), the amendment-type condition-term definitions, the first-matching deadline-bracket rule, and the consent-report version convention. Per-version `data.py` files differ from each other only in the `SCALE` block; the diff vs SOURCE is purely additive (0 lines removed).

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| action_plan_structure (15) | prompt para 3 (verbatim contract: filename + exact columns) |
| trial_guideline_pairs (20) | prompt para 1 (goal) + compliance_methodology.md §1 scope rule + new_guidelines_2026.yaml applicability lists |
| priority_scores (20) | compliance_methodology.md §2 formula + severity_matrix.json + phase_requirements.csv + site_inspection_*.md + trial_dossier_*.json |
| amendment_types (15) | amendment_priority_rules.yaml precedence + compliance_methodology.md §3 condition-term definitions |
| consent_update_report (15) | prompt para 4 (verbatim contract) + compliance_methodology.md §5 version convention |
| sorting_and_deadlines (15) | prompt para 3 (verbatim sort/tie-break) + amendment_priority_rules.yaml deadline_brackets + compliance_methodology.md §4 |

### Verify results

- v3: reward 1.0 (425 tool calls).
- v0: reward 1.0 (62 tool calls; floor ≥ 15 satisfied).
- `verify()` consumes the full hardened surface: cursor pagination on the nested trial list, `json.loads` on detail/site-list strings, envelope unwrapping for consent forms, nested-property walking (`title[0].plain_text`, `select.name`, `relation[0].id`, `rich_text[0].plain_text`, `date.start`), `key: value` text parsing for site info, and `ast.literal_eval` on the repr guideline registry.
