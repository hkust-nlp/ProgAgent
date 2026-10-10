## Task Topic

Detect patterns of upcoding by analyzing procedure code frequencies, provider specialty registries, patient demographic data, and historical claim denial rates to generate a prioritized provider audit list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Structural dimensions used:

- **Conditional Constraints**: Provider flagging depends on composite risk scores derived from five weighted factors (frequency deviation, out-of-scope billing rate, denial rate deviation from peer group average, historical adjustment rate, demographic anomaly rate), each with thresholds and weights defined in workspace configuration files. Peer group membership, specialty authorization scope, and age-range boundaries for demographic anomaly detection all originate from separate workspace files.
- **Information Scattering**: Critical data is distributed across multiple file types (YAML config, JSON scope map, CSV benchmarks split across files, CSV provider supplements split across files, CSV historical adjustments split across files) and database tools (provider roster, claims, procedure details, denial statistics). No single source is sufficient; the agent must consolidate all of them.
- **Multi-Hop Reasoning**: Computing the denial rate deviation requires: listing providers → reading supplement files for peer group assignments → calling denial stats tool per provider → aggregating by peer group → computing per-provider deviation. Computing frequency deviation requires: getting claims per provider → looking up procedure category per code → computing distributions → comparing against regional benchmarks from files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_structure 10, flagged_providers 20, composite_scores 20, priority_assignments 15, sorting_order 10, score_components 15, response_summary 10)
- Source-access: clean (no step-6 escalation; solver succeeded using only `v3/prompt.md` + `get_assistant_tools()`).
- Structural integrity: passed. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in `SCALE`.

**Verification pass (2026-07-02):**

- Issue found and fixed: `sorting_order` criterion in `step()` only checked the primary descending sort on `composite_risk_score` but did not enforce the tie-break rule stated in `prompt.md` ("breaking ties by provider_id in ascending order"). At v3 scale 48 ties exist. Fixed by replacing the single `all()` comprehension with an explicit loop that checks both the primary order (`s1 < s2 → fail`) and the tie-break (`s1 == s2 and pid1 > pid2 → fail`). Fix applied to `v0/env.py` and propagated to `v1–v3`. Reward remains 1.0 after the fix.
- No issues in `prompt.md`: starts with prose (no heading), no bold headers, no bulleted lists for deliverables, computation logic delegated to workspace documents, no tool names exposed, all column names explicit, wording is scale-invariant.
- Solver bugs encountered (not env issues): providers table uses column `name` (not `provider_name`) — purely solver-side.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/upcoding_pattern_detection`. `step()`, `_compute_ground_truth()`, criteria weights, seeds, tables, and `SCALE` are unchanged; only the tool surface, `prompt.md` (M0), and additive policy-document generation in `data.py` (M0) changed.

### M2 — mixed return encodings (per-tool return-shape map)

| Tool | Success shape | Error shape |
|---|---|---|
| `list_providers` | native dict, Notion-style list (`{"object": "list", "results", "has_more", "next_cursor"}`) | `_error` dict |
| `get_provider_claims` | native dict, Notion-style list (cursor pagination) | `_error` dict |
| `get_procedure_info` | JSON-encoded string of a nested record | `json.dumps(_error(...))` string |
| `get_provider_denial_stats` | Python-repr string (single quotes; `json.loads` fails, needs `ast.literal_eval`) | `_error` dict |
| `get_patient_demographics` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) | `_error` dict |
| `get_provider_profile` (new detail lookup, same data as `list_providers` + `npi_number`) | plain `key: value` text | `_error` dict |

2/6 tools stay native dicts; descriptions state what is returned, never how it is encoded.

### M3 — deep-nested record structures

Provider/claim/procedure records are Notion-style, 3–4 levels deep: display text at `properties.Name.title[0].plain_text`, categorical values at `properties.<X>.select.name`, foreign keys at `properties.<X>.relation[0].id` (`Patient`, `Procedure`, `Provider`), numbers at `properties.<X>.number`, dates at `properties.<X>.date.start`, free text at `properties.<X>.rich_text[0].plain_text`. List tools use `has_more`/`next_cursor` cursor pagination instead of `total`/`page`.

### Error contract

Tools never raise. Errors are `{"status", "object": "error", "code", "message", "request_id"}` — sharing **no** keys with any success shape. Not-found → `404 object_not_found` ("Could not find <entity> with ID: <id>."); bad input (wrong type / empty / non-positive page) → `400 validation_error` with `body.<param> should be ..., instead was '<value>'.` Smoke-tested: nonexistent provider/procedure/patient IDs, string `page`, `None`/integer/dict where non-empty strings are required.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 4: scenario/goal (kept), a pointer to the workspace methodology/configuration documents as the authoritative spec (plus the multi-file consolidation note), and the verbatim deliverable-contract and final-response paragraphs. Deleted: the per-file navigation paragraph, the tool hand-holding paragraph, and the two computation paragraphs (five component formulas, composite/rounding/priority rules). `data.py` change (additive only): new fixed document `audit_methodology.md` now carries the previously prompt-only rules — the five component formulas (including the divide-by-100, authorized-categories-only, positive-differences-only conventions), denial-rate peer-group averaging, adjustment-rate definition, inclusive age-boundary convention, weighted composite, round-then-threshold order, and the High/Medium/Low priority label mapping.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| file_structure (name + columns) | prompt (verbatim contract); also `audit_config.yaml` `output` block |
| flagged_providers | `audit_methodology.md` (components, composite, flag rule) + `audit_config.yaml` (weights, thresholds) + `specialty_scope.json` + benchmark/supplement/adjustment files |
| composite_scores | `audit_methodology.md` (formulas, weighted sum, rounding) + `audit_config.yaml` (`scoring_weights`, `decimal_places`) |
| priority_assignments | `audit_methodology.md` (label mapping) + `audit_config.yaml` (`thresholds`) |
| sorting_order | prompt (verbatim contract: descending composite, provider_id tie-break) |
| score_components | `audit_methodology.md` (per-component formulas, rounding) |
| response_summary | prompt (verbatim final-response paragraph) |

### Verify results

- v3: reward 1.0, 1222 tool calls.
- v0: reward 1.0, 164 tool calls (≥ 15 floor).
- `env.py`/`prompt.md` byte-identical across v0–v3; per-version `data.py` differs only in `SCALE`.
