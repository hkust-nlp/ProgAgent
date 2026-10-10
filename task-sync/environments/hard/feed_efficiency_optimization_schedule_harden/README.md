## Task Topic

Optimize feed efficiency and cost by analyzing automated feeder consumption logs, breed-specific growth target curves, silo inventory levels, and recent bulk commodity market prices, producing a weekly adjusted feed ration schedule for each pen.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Health flag multipliers and waste-threshold reductions alter each pen's intake; feeding phase (growing vs. finishing) switches category allocation percentages based on an age-week boundary; protein and energy shortfall triggers iterative reallocation of category shares.
- **Deliverable Constraints**: Output CSV requires exact column order, two-decimal precision, ascending sort by pen_id then commodity; adjustment report JSON must carry specific keys and types; final response must include formatted cost and count strings.
- **Information Scattering**: Pen details, growth targets, market prices, and silo stocks are available only through tools; health/condition assessments live in workspace CSV batch files; formulation rules, cost policy, nutrient computation procedures, and output specifications are spread across YAML, JSON, Markdown, and TXT config files.
- **Multi-Hop Reasoning**: pen → breed + age → growth target (DMI%, protein, energy) → health flag from condition file → waste from feeder logs → adjusted DMI → category allocation from rules → commodity selection via latest market price → protein/energy blend check → iterative adjustment → cost computation.

## Harness Report

- v3 reward: 1.0 (110/110).
- Eval criteria: 8 — file_structure (10 pts), pen_coverage (15 pts), nutritional_adequacy (20 pts), schedule_accuracy (20 pts), inventory_feasibility (15 pts), adjustment_report (10 pts), action_string (10 pts), db_adjustments_recorded (10 pts).
- Structural integrity: passed. All four versions contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 50/100/200/400, workspace files 10/20/30/40).
- Solvability: solver written from `v3/prompt.md` + `get_assistant_tools()` only. No `env.py`/`data.py` inspection was needed. Initial run scored 90/110 (two criteria failed); both issues were in the solver, not in the env or prompt — no source-file changes required.
- Env quality: all 8 `step()` criteria map to explicit prompt requirements; ground truth is computed dynamically from data.db and workspace files (no hard-coded row counts or values); criteria weights are identical across v0..v3 (byte-for-byte env.py invariant).
- Prompt quality: no title, no bold headers, no bullet/numbered lists; deliverables and column names described in prose; no tool names, table names, or db filenames leaked; scale-invariant wording throughout.
- Issues found and fixed (solver only — no env.py or prompt.md changes):
  1. **Cost accumulation**: initial solver summed unrounded `daily_cost_usd` values; env sums per-row `round(daily_cost_usd, 2)` × 7. Fixed by rounding each row's cost to 2 dp before accumulating the total. Result shifted from 146493.06 to 146495.30.
  2. **Ledger Description format**: `create_adjustment_record` payload `properties.Description` requires `{"type": "rich_text", "rich_text": [...]}` but the initial solver omitted the `"type"` key, causing silent rejection (0/333 records written). Fixed by adding `"type": "rich_text"`.
- Cleanup: removed `v3/data.db`, `v3/workspace/`, and all `__pycache__/` produced during verification.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/feed_efficiency_optimization_schedule`. Data generation (tables, rows, seeds, SCALE), `_compute_ground_truth()`/`_compute_rations()`, and the original 7 scoring criteria are unchanged; `step()` gained one DB-state criterion under the M4 no-write-tool exception (total now 110 pts).

- **M1 JSON-string parameters**: `list_pens` takes a `filter` parameter that must be a JSON-encoded string supporting `breed` and `barn_id`; `get_feeder_logs` moved its lookback option into a JSON-string `filter` supporting `num_days`. Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values return recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_adjustment_record(payload)` tool with a Notion-style nested body (`parent.type='pen_ledger'` + `parent.pen_id`, `properties.Adjustment.select.name` in {health, waste, both}, optional `Description` rich_text). Validation is layered — one error per call, messages like `body.parent.pen_id should be a non-empty string, instead was 'undefined'.` It writes `INSERT OR REPLACE INTO pen_adjustments` (table created on first write, keyed by pen_id so retries are idempotent). New `step()` criterion `db_adjustments_recorded` (10 pts) checks one correctly-typed ledger record per expected adjusted pen, penalizing spurious records; `prompt.md` gained one sentence requiring the ledger recording. Success responses (`{"object": "adjustment_record", ..., "created": true}`) share no keys with error responses.
- **Return shapes**: all success returns remain native dicts/lists (M2 not assigned). All lookups (`get_pen_details`, `get_growth_target`, `get_latest_price`, `get_silo_stock`, `get_feeder_logs`) return `_error(404, "object_not_found", ...)` instead of raising or `{"error": ...}`; tools never raise.
- **Error contract**: errors are `{status, object: "error", code, message, request_id}`; success responses never carry any of these keys, so consumers must branch on shape.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 5: scenario/goal, a pointer to the policy/rules/reference documents as the authoritative specification (plus where assessments and feeder history live), the verbatim CSV deliverable contract, the verbatim `adjustment_report.json` contract (+ the M4 ledger sentence), and the verbatim final-response format. `data.py` change (additive only): new fixed workspace document `ration_methodology.md` carrying the previously prompt-only rules — base-intake formula (avg weight x DMI%/100 x head count), health-multiplier application, waste-window averaging and reduction formula (multiplicative, after health), phase determination and category allocation, price-based commodity selection with alphabetical tie-break, prescribed supplement split, protein-then-energy floor ordering, and the inventory-feasibility rule. SCALE blocks preserved per version; per-version `data.py` files differ only in `SCALE`.

Completeness audit (step() criterion -> info source):
| criterion | source |
|---|---|
| file_structure | prompt (verbatim contract); also workspace `output_spec.txt` |
| pen_coverage | prompt ("for every pen") |
| nutritional_adequacy | `ration_methodology.md` (base intake, floors) + `nutrient_reference.md` (blend formulas, iterative adjustment) + growth-target tool |
| schedule_accuracy | `ration_methodology.md` (full computation chain) + `formulation_rules.yaml` (parameters) + `output_spec.txt` (rounding, cost formula) + prompt contract |
| inventory_feasibility | `ration_methodology.md` (feasibility rule) + `cost_policy.json` (safety margin) |
| adjustment_report | prompt (verbatim contract); also `output_spec.txt` |
| action_string | prompt (final-response formats, verbatim) |
| db_adjustments_recorded | prompt (ledger sentence) + write-tool description (example body) |

### Verification

- v3: `verify()` reward 1.0 (110/110), 1300 tool calls.
- v0: `verify()` reward 1.0 (110/110), 207 tool calls (>= 15 floor).
- Negative-path smoke tests pass: malformed M1 filter -> `invalid_json` with line/column/char; dict-for-string -> serialize hint; unsupported/wrong-typed filter keys -> `validation_error`; M4 payload validated layer by layer (undefined body -> string body -> missing parent -> wrong parent.type -> missing pen_id -> missing properties -> missing Adjustment -> missing select -> bad select.name -> 404 unknown pen); all lookups return 404 error dicts for unknown ids.
- `env.py` and `prompt.md` byte-identical across v0..v3; no runtime artifacts left in any version directory.
