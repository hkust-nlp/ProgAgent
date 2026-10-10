## Task Topic

Identify underperforming catalytic cracking units by correlating catalyst activity logs, feedstock quality reports, unit throughput data, and energy consumption records to produce a maintenance priority list for catalyst regeneration or replacement.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Feedstock quality data resides exclusively in workspace CSV files, while catalyst activity, throughput, and energy data are only accessible via tool calls. The scoring configuration, catalyst reference specs, and maintenance decision rules are split across three separate workspace files (YAML, JSON, TXT). Solving the task requires reading all of these sources and cross-referencing them per unit.

- **Multi-Hop Reasoning**: The priority score computation involves a dependency chain of length ≥ 3: retrieve catalyst batch info (tool) → use catalyst type to look up baseline conversion from reference JSON (file) → compare against throughput records (tool) → compute conversion loss → normalize using config thresholds (file) → weight and sum into final score. Similarly, energy efficiency requires matching energy records with throughput records by closest date before computing per-barrel ratios.

- **Conditional Constraints**: The recommended maintenance action depends on both the priority tier (derived from the composite score) and the catalyst age factor (days since load / expected lifetime). A Critical-tier unit with age factor above 1.5 receives "immediate_replacement" while one at or below 1.5 receives "emergency_regeneration", each with different downtime estimates.

## Harness Report

- v3 reward: **1.0** (100/100).
- Eval criteria: 7 — csv_format (15 pts), all_units_present (15 pts), priority_scores (20 pts), ranking_order (15 pts), recommended_actions (15 pts), downtime_values (10 pts), response_summary (10 pts).
- Structural check: top-level contains exactly README.md + v0/..v3/; each version has exactly data.py, env.py, prompt.md; no stale artifacts. `diff v0/env.py v{1,2,3}/env.py` empty; same for prompt.md; data.py differs only in the SCALE block (v0: 100 rows/10 files → v1: 200/20 → v2: 400/30 → v3: 800/40). No issues.
- Solvability: solver written from prompt.md + get_assistant_tools() output alone (no env.py/data.py read at solve time); achieved reward 1.0 on first semantically-correct run. No step-6 escalation required.
- Env quality: all 7 criteria correspond to explicit prompt requirements; ground truth derived from DB/workspace at step-time (scale-invariant); no hardcoded counts; score tolerance ±2.0 handles floating-point rounding; downtime compared via int(float(...)) to accept "7.0" == 7. No issues.
- prompt.md quality: no title/heading, no bold section headers, no bulleted/numbered deliverable lists, no tool names, no source filenames, exact output column names specified, scale-invariant wording ("every unit"). No issues.
- Issues found and fixed: **none** — task passed all checks as delivered.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/catalyst_performance_analysis`; `step()` / `_compute_ground_truth()` scoring is unchanged. Only the tool surface, `verify()`, `prompt.md` (M0), and additive policy text in `data.py` (M0 rule 4) changed.

### M2 — mixed return encodings (per-tool return-shape map)

| Tool | Success shape | Error shape |
|---|---|---|
| `list_units` | native dict, deep-nested list (`{"object": "list", "results", "has_more", "next_cursor"}`) | `_error` dict |
| `get_unit_details` | JSON-encoded string (nested unit record + nested inspections list) | `json.dumps(_error(...))` |
| `get_catalyst_info` | plain `key: value` text (single flat record) | `_error` dict |
| `get_activity_logs` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) wrapping a nested list | `_error` dict |
| `get_throughput_data` | native dict, deep-nested list | `_error` dict |
| `get_energy_data` | Python-repr string of a nested list payload (single quotes; `json.loads` fails, needs `ast.literal_eval`) | `_error` dict |

2/6 tools stay native dicts (~33%); descriptions state only WHAT is returned, never the encoding.

### M3 — deep-nested records

Records are Notion-style, 3–4 levels deep: display text at `properties.<X>.title[0].plain_text` (unit names) / `rich_text[0].plain_text`, categorical values at `properties.<X>.select.name`, numbers at `properties.<X>.number`, dates at `properties.<X>.date.start`, foreign keys at `properties.<X>.relation[0].id` (Batch/Unit relations). All list tools use cursor-style pagination (`has_more` / `next_cursor`; record-offset cursor for per-unit logs, page cursor for `list_units`) instead of `total`/`total_pages`.

### Error contract

Tools never raise. Errors are `{"status", "object": "error", "code", "message", "request_id"}` — no keys shared with any tool's success payload other than the `object` type discriminator. Not-found → `404 object_not_found` ("Could not find unit with ID: FCC-99."); malformed input → `400 validation_error` ("body.unit_id should be a non-empty string, instead was 'undefined'.", "body.page should be an integer, instead was ''one''."). Wrong-typed parameters reach validation (params typed `Any`) instead of crashing.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 10 route-narrating paragraphs to 4: scenario/goal, a pointer to the policy/reference documents as the authoritative specification (plus the workspace location of feedstock reports), and the verbatim deliverable contract (ranking order, tie-breaker, ranks from one, filename, exact column order, two-decimal rounding, final-response content). Removed: tool hand-holding, sequencing scaffolds, per-file navigation, and all formula restatements (verified discoverable in `maintenance_guidelines.txt` + `scoring_config.yaml` + `catalyst_reference.json`). `data.py` change (additive only, `write_fixed_workspace_files`): `maintenance_guidelines.txt` gained the fixed analysis reference date (2025-12-31) — previously stated only in the prompt — plus the odd-count half-split convention for the energy ratio and the <2-records defaults (decline 0.0, ratio 1.0, single/zero-throughput conversion fallback, severity 0.0). Per-version `data.py` files differ only in the `SCALE` block.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| csv_format (columns) | prompt para 3 (verbatim contract) |
| all_units_present | prompt para 1 ("every unit") + `list_units` tool |
| priority_scores | maintenance_guidelines.txt (all five factor formulas, normalization, weighted sum, reference date) + scoring_config.yaml (weights/ranges/conversions/severity weights) + catalyst_reference.json (baselines) + feedstock report CSVs |
| ranking_order | prompt para 3 (descending score, alphabetical tie-break, ranks from 1) |
| recommended_actions | maintenance_guidelines.txt (tier thresholds + tier×age-factor decision rules) |
| downtime_values | maintenance_guidelines.txt (downtime per action) |
| response_summary | prompt para 4 (verbatim final-response requirement) |

### Verification

- v3: `verify()` reward 1.0 (100/100, all 7 criteria passed), 82 tool calls.
- v0: `verify()` reward 1.0, 82 tool calls (≥ 15 floor).
- Negative-path smoke tests passed: 404 dict on unknown unit (native and JSON-string forms), `validation_error` on wrong-typed `unit_id`/`page`/`limit` (no raise), envelope/repr/text/JSON-string success shapes probed (`json.loads` confirmed to fail on the repr form), pagination cursors followed, success/error key disjointness confirmed.
- `diff v0/env.py v{1,2,3}/env.py` empty; `prompt.md` identical across versions; no runtime artifacts left.
