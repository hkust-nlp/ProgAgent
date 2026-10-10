## Task Topic

Identify unauthorized subletting and occupancy violations. Cross-reference tenant lease agreements, utility consumption patterns, property access logs, and resident complaint histories to output a list of units requiring formal investigation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Scaling ratios: `rows_per_table` follows 1×/2×/4×/8× of the v0 base (50). `num_workspace_files` follows base/base+N/base+2N/base+3N where N = 10 (the v0 base).

### Structural dimensions

- **Information Scattering**: Task-critical data is split across workspace files (utility CSVs, access card JSONs) and tool calls (lease details, complaint records). Neither source alone is sufficient; the agent must read files for consumption and access patterns, then call tools for lease constraints and complaint categories.
- **Conditional Constraints**: Flagging a unit requires evaluating a multi-signal scoring formula with thresholds, multipliers, per-complaint caps, and a conditional bonus (subletting-prohibited applies only when other signals are already present). All parameters reside in a workspace YAML policy file.
- **Deliverable Constraints**: The output CSV enforces exact column names, semicolon-separated alphabetically-sorted signal lists, a specific sort order (score descending, unit_id ascending as tiebreaker), and yes/no subletting encoding.
- **Multi-Hop Reasoning**: Utility CSV → compute per-unit average → tool call for max_occupants → compare against policy threshold → tool call for complaints → check categories against policy concern list → apply conditional subletting bonus → aggregate score → compare against investigation threshold.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria count: 8 (`report_format`, `flagged_precision`, `flagged_recall`, `correct_scores`, `correct_signals`, `correct_subletting_allowed`, `sort_order`, `response_units`)
- Source-access escalation: not needed (solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`)
- Issues found and fixed:
  1. **Completeness gap (env.py):** `step()` never verified the `subletting_allowed` column values even though `prompt.md` explicitly requires `"yes"`/`"no"`. Added `correct_subletting_allowed` criterion (10 pts). Fixed in `v0/env.py`, re-propagated byte-for-byte to `v1/v2/v3`.
  2. **Solver debug (non-env issue):** Initial solver compared `subletting_allowed` as the string `"no"` but SQLite stores it as integer `0`/`1`. Fixed in solver only; `env.py` and `data.py` were correct.
- Blockers: none

Section 1 (structural integrity), Section 2 (solvability at v3 scale), Section 3 (env quality), Section 4 (prompt quality), and Section 5 (cleanup) all pass.

## Hardening (M0, M5, M2)

Source: `environments/standard/unauthorized_occupancy_detection`. Task semantics, data tables, seeds, `SCALE`, `step()`, and `_compute_ground_truth()` are unchanged. Only the tool surface, `verify()`, the prompt (M0), and an additive policy document in `data.py` (M0) changed.

### Mutators applied

- **M0 — de-proceduralized prompt.** Route narration (tool hand-holding, per-file navigation, sequencing scaffolds) deleted; the multi-signal methodology paragraph moved into a new fixed workspace document `investigation_methodology.md` (written by `data.py`; the only `data.py` change, additive and non-scaling — per-version `data.py` files differ only in their original `SCALE` blocks). The deliverable contract and final-response paragraphs survive verbatim.
- **M5 — unbounded bulk export.** New `export_occupancy_dataset` tool: one JSON string, one record per unit-month joined with lease occupancy terms and per-unit unique access-card counts, no pagination. Sufficient for the utility, access-card, and subletting components of the scoring; complaints still require the per-unit tool, and the policy/methodology live in the workspace. Paginated `list_units` and all per-entity tools remain as the safe alternative.
- **M2 — mixed return encodings** (one stable form per tool, descriptions never reveal the encoding):

| Tool | Success shape |
|------|---------------|
| `list_units` | native dict |
| `export_occupancy_dataset` | JSON-encoded string (M5 bulk export) |
| `get_lease_info` | plain `key: value` text |
| `get_registered_occupants` | MCP envelope (`content[0].text` is JSON) |
| `get_complaints_for_unit` | Python-repr string (needs `ast.literal_eval`; `json.loads` fails) |

### Error contract

Tools never raise. Every failure returns the `_error` dict `{status, object:"error", code, message, request_id}` — a shape sharing **no keys** with any success form. Not-found → `404 object_not_found` (`get_lease_info`, `get_registered_occupants`, `get_complaints_for_unit` with unknown IDs); bad/missing/wrong-typed input → `400 validation_error` with Notion-style messages (`body.page should be an integer, instead was ''abc''.`). All parameters are typed `Any` internally so malformed inputs reach validation instead of crashing.

### M5 size calibration (`len(raw) // 4`)

| Scale | Export chars | Est. tokens | Bound |
|-------|-------------|-------------|-------|
| v0 | 72,399 | ~18.1k | ≤ 20k ✓ (survivable but expensive) |
| v3 | 579,387 | ~144.8k | ≥ 100k ✓ (fatal to echo natively) |

### M0 completeness audit (every `step()` criterion → where the information lives)

| Criterion | Information required | Lives in |
|-----------|---------------------|----------|
| `report_format` (10) | filename `investigation_report.csv`, exact 4 columns | prompt, deliverable paragraph (verbatim) + policy `output_format` |
| `flagged_precision` (15) / `flagged_recall` (15) | which units to flag: signal trigger conditions, strict inequalities, max-occupant basis, complaint cap, conditional subletting bonus, ≥-threshold flagging | workspace `investigation_methodology.md` (computations) + `investigation_policy.yaml` (numbers, categories, threshold) |
| `correct_scores` (20) | per-signal point values, complaint cap, summation | `investigation_policy.yaml` scores + `investigation_methodology.md` |
| `correct_signals` (15) | exact signal names, alphabetical order, `"; "` separator | signal names in methodology + policy criterion keys; ordering/separator in prompt deliverable paragraph + policy `output_format` |
| `correct_subletting_allowed` (10) | `"yes"` when lease permits subletting, `"no"` when it does not | prompt deliverable paragraph (verbatim) + policy `output_format` |
| `sort_order` (10) | `total_score` desc, `unit_id` asc tiebreak | prompt deliverable paragraph (verbatim) + policy `output_format` |
| `response_units` (15) | final response lists flagged unit IDs, comma-separated, report order | prompt final paragraph (verbatim) |

No criterion depends on information reachable only from `env.py` source.

### Verification & smoke tests

- v3: harness solver reward **1.0** (110/110), 8 criteria all passing.
- v0: `verify()` reward **1.0** (110/110), 115 tool calls (≥ 15 floor).
- Negative paths exercised: unknown-ID 404s on lease/complaints tools, `'undefined'` and wrong-typed `unit_id`, non-integer / zero / missing `page`; success-vs-error key-disjointness asserted; repr return confirmed non-JSON-parseable and `ast.literal_eval`-parseable; envelope round-trip confirmed.
- `v0/env.py` byte-identical across v1–v3; `prompt.md` identical across versions; per-version `data.py` differ only in `SCALE`; no runtime artifacts left.
