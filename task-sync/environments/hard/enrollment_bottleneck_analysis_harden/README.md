## Task Topic

Analyze patient screening logs, electronic health record eligibility flags, site investigator availability calendars, and historical enrollment rates to identify recruitment bottlenecks, generating a prioritized site intervention list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|-------------------|
| v0      | 100           | 10                |
| v1      | 200           | 20                |
| v2      | 400           | 30                |
| v3      | 800           | 40                |

Scaling ratios: rows v1=2x, v2=4x, v3=8x base; files v1=base+N, v2=base+2N, v3=base+3N where N=10.

The task exercises the following structural dimensions:

- **Information Scattering**: Per-site risk adjustment factors and custom enrollment targets are distributed across workspace files in five different formats (CSV, JSON, TXT, YAML, MD), while screening outcomes, eligibility results, enrollment history, and investigator details are only accessible through tool calls. Scoring thresholds, regional benchmarks, and intervention text live in separate fixed configuration files.

- **Multi-Hop Reasoning**: Computing each site's severity score requires a dependency chain of length 4+: (1) read scoring config for thresholds and weights, (2) read regional benchmarks for default targets, (3) read supplement files for risk adjustment and custom target overrides, (4) call tools for screening/eligibility/enrollment/investigator data, (5) combine all to compute bottleneck type and severity, (6) apply tier multiplier and risk adjustment, (7) rank across all sites.

- **Conditional Constraints**: Bottleneck classification depends on four threshold-based rules (screen failure rate, eligibility barrier index, enrollment ratio, investigator utilization/certification expiry), each involving data from different tables and workspace files. The enrollment target used for comparison depends conditionally on whether a custom target exists for that site.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (file_format=10, site_coverage=15, bottleneck_accuracy=20, severity_accuracy=20, ranking_accuracy=15, intervention_accuracy=10, response_summary=10)
- Source-access: clean. Solver was authored using only `v3/prompt.md` and the public `Task_Env.get_assistant_tools()` interface. `env.py` was opened only after achieving reward=1.0, for the Section 3 quality review.
- Section 1 structural integrity: passed. Top-level contains exactly `README.md` plus `v0/`–`v3/`; each version dir contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` diffs are confined to the `SCALE` block (v1 rows=2×, v2=4×, v3=8×; files +N, +2N, +3N).
- Section 2 solvability: initial solver submitted reward=0.695; root cause was using wrong raw-DB outcome literals (`'passed'`/`'failed'`) instead of the actual values (`'pass'`/`'fail'`) when querying `screening_logs` directly. Fixing the DB query produced reward=1.0. No edits to `env.py`, `data.py`, or `prompt.md` were needed — the task and grader were correct throughout.
- Section 3 env quality: no issues found. Step criteria cover every deliverable in `prompt.md` (coverage + completeness), enforce exact column names, use ±0.5 tolerance for numeric severity scores (appropriate given 2-decimal rounding), derive all ground truth from the live `data.db`/workspace (no hard-coded counts), and criterion set is identical across versions via the byte-for-byte invariant.
- Section 4 prompt quality: no issues found. No title/heading, no bold section headers, no lists for deliverables, computation logic delegated to workspace documents, no tool names or internal filenames leaked, output filename and column names explicit, scale-invariant wording throughout.
- Issues and fixes: none. No edits were needed in `v0/` or any other version.
- Blockers: none.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/enrollment_bottleneck_analysis`; `step()`, `_compute_ground_truth()`, ground truth, and criteria weights are unchanged.

### M2 — mixed return encodings (per-tool map)

| tool | success shape | error shape |
|---|---|---|
| `list_sites` | native dict, deep-nested list (`{"object": "list", "results", "has_more", "next_cursor"}`) with cursor pagination | `_error` dict |
| `get_site_details` (added probe/detail tool) | plain `key: value` text, one flat record | `_error` dict |
| `get_screening_summary` | Python-repr string (single quotes; `json.loads` fails, needs `ast.literal_eval`) | `_error` dict |
| `get_eligibility_breakdown` | native dict, deep-nested criterion-assessment records | `_error` dict |
| `get_enrollment_history` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) wrapping nested records | `_error` dict |
| `get_site_investigators` | JSON-encoded string of nested investigator records | `json.dumps(_error(...))` |

Native-dict share: 2/6 tools (~33%). Tool descriptions state content only, never encoding.

### M3 — deep nesting

Record fields live 3–4 levels deep in Notion-style property objects: display text at `properties.Name.title[0].plain_text`, categorical values at `properties.<X>.select.name`, numbers at `properties.<X>.number`, dates at `properties.<X>.date.start`, foreign keys at `properties.Site.relation[0].id`. List tools use `has_more`/`next_cursor` cursor pagination instead of `total`/`total_pages`.

### Error contract

Tools never raise. Bad input → `_error(400, "validation_error", "body.<param> should be ..., instead was '<value>'.")`; unknown site → `_error(404, "object_not_found", "Could not find site with ID: <id>.")`. Error responses are `{"status", "object": "error", "code", "message", "request_id"}` — no key overlap with success payloads except the `object` discriminator (`"error"` vs `"list"`/entity kinds), matching the template.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 4: scenario/goal, an authoritative-documents pointer, the verbatim deliverable contract (sort keys, tie-breaker, rank origin, filename, exact column order), and the verbatim final-response requirement. Removed: tool hand-holding, sequencing scaffolds, per-file navigation, and all formula/rule restatements. `data.py` change (additive only, fixed non-scaling file): `create_fixed_workspace_files` now also writes `bottleneck_methodology.md` carrying the previously prompt-only rules — active-only scope, supplement-file semantics (risk factor multiplicative, custom target override, 1.0/regional defaults), all four indicator formulas with strict-inequality flagging, the +5 expiring-certification points, the certification window convention, the multiple/exclusion classification rules, exact bottleneck-type labels, the severity formula with cap and 2-decimal rounding, and the catalog-keyed intervention rule. Per-version `data.py` files differ only in the `SCALE` block.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| file_format (10) | prompt para 3 (verbatim contract: filename + exact columns) |
| site_coverage (15) | bottleneck_methodology.md (active-only scope; no-bottleneck exclusion) |
| bottleneck_accuracy (20) | bottleneck_methodology.md (flagging rules, exact labels, `multiple` rule) + scoring_config.yaml thresholds |
| severity_accuracy (20) | bottleneck_methodology.md (component formulas, +5 cert points, severity = base × tier mult × risk adj, cap 100, round 2dp) + scoring_config.yaml weights/multipliers/reference date + supplement files + regional_benchmarks.csv |
| ranking_accuracy (15) | prompt para 3 (sort desc by severity, tie-break by site_id asc, rank from 1) |
| intervention_accuracy (10) | bottleneck_methodology.md (catalog keyed by type) + intervention_catalog.yaml |
| response_summary (10) | prompt para 4 (verbatim final-response requirement) |

### Verify results

- v3: reward 1.0 (100/100), 2061 tool calls.
- v0: reward 1.0 (100/100), 258 tool calls (≥ 15 floor).
- Negative paths exercised: wrong-typed `page`/`site_id`, invalid `status_filter` enum, nonexistent site on native/envelope/JSON-string tools (404 in the tool's error form), repr success string rejected by `json.loads` and accepted by `ast.literal_eval`.
