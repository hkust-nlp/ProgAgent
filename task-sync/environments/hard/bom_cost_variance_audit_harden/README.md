## Task Topic

Validate finished goods cost accuracy. Reconcile current raw material prices, approved vendor lists, labor routing standards, and actual production yield reports against the standard cost bill of materials, outputting a variance report for cost revision.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 20            | 8                   |
| v1      | 40            | 16                  |
| v2      | 80            | 24                  |
| v3      | 160           | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Standard costs (BOM quantities, material standard prices, labor routing hours/rates) are accessible only through tool calls, while actual costs require reading workspace files — vendor quoted prices from JSON files, material handling surcharges from TXT files, actual labor hours from Markdown production summaries, and yield data from CSV reports. Threshold parameters live in a YAML configuration file and revision rules in a separate TXT policy file.
- **Multi-Hop Reasoning**: Determining the actual material price for a single BOM line requires a chain of at least length 3: query the BOM for material IDs → query approved vendors for each material → filter active/preferred vendors → look up the preferred vendor's quoted price in workspace JSON files → add the handling surcharge from workspace TXT files. The revision recommendation further chains yield rate computation and threshold lookups.
- **Conditional Constraints**: Flagging and revision decisions depend on multi-condition business rules involving variance thresholds, preferred-vendor fallback status, and yield rate floors, all parameterised in workspace configuration files.

## Harness Report

**v3 solver reward:** 1.0 (100/100)

**Eval criteria (7 total, 100 pts):**

| Criterion | Points | What it checks |
|---|---|---|
| `file_structure` | 15 | CSV exists (5), correct columns (5), rows sorted by descending abs(total_variance_pct) (5) |
| `all_products_present` | 10 | Every product in the DB has a row in the CSV |
| `material_cost_accuracy` | 20 | Standard/actual material cost and variance match ground truth (1% rel, ±$1 abs) |
| `labor_cost_accuracy` | 20 | Standard/actual labor cost and variance match ground truth (1% rel, ±$1 abs) |
| `yield_and_totals` | 15 | Yield rate, yield-adjusted total, total variance/pct match ground truth |
| `flags_and_revision` | 10 | `flag` and `revision_recommended` (YES/NO) match ground truth for every product |
| `action_revision_summary` | 10 | Final response mentions every product ID that has `revision_recommended = YES` |

**Issues found and fixed:**

1. **Runtime artifacts in v3/** (structural): `v3/data.db` and `v3/workspace/` were left over from a prior generation run. Removed.

2. **Sort order not enforced in `step()`** (env quality / completeness): `prompt.md` requires the CSV to be "sorted in descending order by the absolute value of total variance percentage", but the original `step()` never validated the row order. Fixed by redistributing the 15-pt `file_structure` criterion as: 5 pts for file existence + 5 pts for correct columns + 5 pts for non-increasing abs(total_variance_pct) order. Updated in `v0/env.py` and propagated byte-for-byte to `v1/`, `v2/`, `v3/`. Reward re-verified at 1.0 after fix.

**Independent verification (harness check pass):**

Re-run on 2026-07-03. Checked all five sections:
- Structural integrity: exactly `README.md` + `v0/..v3/`, each with exactly `data.py/env.py/prompt.md`; `env.py` and `prompt.md` byte-for-byte identical across versions; `data.py` differs only in the `SCALE` block (20/40/80/160 rows; 8/16/24/32 workspace files).
- Solvability at v3: independent solver reading only `prompt.md` + `get_assistant_tools()` output achieved reward 1.0 (100/100) on first attempt; all 7 criteria passed.
- Env quality: every criterion in `step()` maps to an explicit prompt requirement; scoring denominates on `total_products` (scale-invariant); numeric comparison uses proportional tolerance; no hardcoded counts.
- Prompt quality: no title/heading, no bold headers, no bulleted deliverable lists, no tool names, column names explicit, wording scale-invariant.
- No fixes required this pass; runtime artifacts cleaned up.

## Hardening (M0 + M1 + M3 + M5)

Applied on top of `environments/standard/bom_cost_variance_audit`; `step()` is byte-identical to SOURCE (verified by extraction diff), ground truth (`_compute_ground_truth` in `data.py`) untouched, and the `data.py` change is additive only (a fixed, non-scaling methodology document; per-version `SCALE` blocks preserved — v1/v2/v3 `data.py` differ from v0 only in `SCALE`).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 10 route-narrating paragraphs to 4: scenario/goal, a pointer to the costing methodology document + policy/configuration documents as the authoritative spec, the verbatim deliverable contract (file name, exact column list and order, two-decimal monetary/percentage rounding, four-decimal yield rate, YES/NO domain, descending-abs(total_variance_pct) sort, percentage field definition), and the verbatim final-response requirement. `data.py` gains a new fixed workspace document `costing_methodology.md` carrying every rule that previously lived only in the prompt: standard material/labor cost formulas, the actual-material-price rule (active vendors → preferred vendor's most recent quote + handling surcharge; fallback to the lowest active quote; non-preferred sourcing must be recorded per product), the actual-labor rule (actual hours × standard rate; standard hours apply when no actual hours are recorded), the yield-rate and yield-adjusted-total formulas, all six variance/percentage definitions, and the flag rule (thresholds live in `cost_thresholds.yaml`; revision conditions stay in `revision_policy.txt`).
- **M1 JSON-encoded string filters**: `get_approved_vendors` takes `filter` with supported properties `status` ('active' | 'inactive') and `preferred_only` (boolean); `get_labor_routing` takes `filter` with `operation_name` (string) and `min_standard_hours` (number). Both params are typed `Any = None`; validation is layered, one error per call: dict body → `invalid_request` ("serialize it to a JSON string"), malformed JSON → `invalid_json` with line/column/char, non-object JSON → `invalid_request`, unsupported key → supported-property list, wrong-typed value → `body.filter.<key> should be ..., instead was '<shape>'.`
- **M3 deep-nested records**: `list_products` returns `{"object": "list", "results": [...], "has_more", "next_cursor"}` (cursor pagination, no total/total_pages); `get_bom` returns a list of nested `bom_line` records; `get_material_info` returns a nested `{"object": "material", "id", "properties": {...}}` record. Traps kept: display names at `properties.Name.title[0].plain_text`, categorical values (Category/Unit) at `properties.<K>.select.name`, foreign keys at `properties.Product.relation[0].id` / `properties.Material.relation[0].id`, numbers at `properties.<K>.number`.
- **M5 unbounded bulk export**: new tool `export_bom_sourcing_matrix()` returns every BOM line joined with product name, material name, standard qty/unit price, and each approved vendor (id, name, preferred flag, status) as ONE JSON string, no pagination. Measured `len(raw)//4`: **~19.1k tokens at v0** (267 records; survivable but expensive) and **~158.7k tokens at v3** (2,217 records; echoing it into context is fatal under a ~70k response budget — it must be consumed inside the programmatic sandbox and filtered before printing). It is genuinely sufficient for the core BOM/vendor-selection step; all paginated/per-entity tools remain available.

Per-tool return-shape map:
| tool | success shape | error shape |
|---|---|---|
| `list_products` | native dict, M3 nested list w/ cursor | `_error` dict |
| `get_bom` | native dict, M3 nested `bom_line` list (relation traps) | `_error` dict |
| `get_material_info` | native dict, M3 nested record | `_error` dict |
| `get_approved_vendors` | native dict `{material_id, vendors}` (M1 filter param) | `_error` dict |
| `get_labor_routing` | native dict `{product_id, routings}` (M1 filter param) | `_error` dict |
| `export_bom_sourcing_matrix` | ONE JSON string `{record_count, records}` (M5) | — (parameterless) |

Error contract: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` — sharing no keys with any success shape. Not-found → `404 object_not_found` ("Could not find product/material with ID: ..."), bad input → `400 validation_error` / `400 invalid_json` / `400 invalid_request`. Unknown product/material IDs now 404 on every per-entity tool (SOURCE returned an `{"error": ...}` dict from `get_material_info` only).

Completeness audit (step() criterion → info source after M0):
| criterion | source |
|---|---|
| `file_structure` | prompt (verbatim contract: filename, column list/order, descending-abs(total_variance_pct) sort) |
| `all_products_present` | prompt ("one row per product" + "every finished good" in the goal paragraph) |
| `material_cost_accuracy` | `costing_methodology.md` §1–2 + vendor query data + `vendor_quotes_*.json` + `material_specs_*.txt` |
| `labor_cost_accuracy` | `costing_methodology.md` §1, §3 + routing query data + `production_summary_*.md` |
| `yield_and_totals` | `costing_methodology.md` §4–5 + `yield_report_*.csv` |
| `flags_and_revision` | `costing_methodology.md` §6 + `cost_thresholds.yaml` + `revision_policy.txt` |
| `action_revision_summary` | prompt (verbatim final-response paragraph; reasons defined in `revision_policy.txt`) |

verify() results (hardened surface: M3 cursor walk + nested-property/relation parsing, M5 export consumed once in memory and cross-checked against per-entity tools, M1 JSON-string `{"status": "active"}` filters):
- v0: reward 1.0 (100/100), 73 tool calls.
- v3: reward 1.0 (100/100), 499 tool calls.
- Negative-path smoke tests all pass: malformed M1 JSON → `invalid_json` with line/column/char; dict-instead-of-string → `invalid_request`; non-object JSON → `invalid_request`; unsupported filter key / wrong-typed values (`status`, `preferred_only`, `min_standard_hours`) → layered `validation_error` messages; nonexistent product/material → 404 `object_not_found`; undefined `product_id` / non-integer `page` → 400 `validation_error`.
