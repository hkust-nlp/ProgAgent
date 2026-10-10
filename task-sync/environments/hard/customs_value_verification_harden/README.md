## Task Topic

Validate declared customs values to prevent underpayment. Analyze supplier invoices, freight and insurance cost ledgers, current exchange rate tables, and product-specific market value benchmarks to flag entries with >10% value discrepancy, outputting a discrepancy report for audit.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Invoice details, product HS codes, shipment incoterms/ports come from tools; exchange rates, freight/insurance costs, packaging/handling supplements, port surcharges, and market benchmarks come from workspace files. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: Multiple dependency chains of length >= 3. For example: query invoice (tool) -> get product_id -> query product (tool) -> get hs_code -> search benchmark files (workspace) -> retrieve benchmark price. Similarly: query invoice (tool) -> query shipment (tool) -> get incoterm + port -> read policy + surcharge files (workspace) -> compute adjustment.
- **Conditional Constraints**: CIF calculation depends on the incoterm (FOB/CIF/CFR/EXW), with rules defined in workspace policy files. Risk classification tiers (Medium/High/Critical) depend on discrepancy thresholds from the policy.
- **Deliverable Constraints**: Output CSV requires exact column order, 2-decimal rounding, specific sort order (discrepancy_pct descending, invoice_id ascending as tie-breaker), and the final response must include precise summary statistics.

## Harness Report

- v3 reward: 1.0 (100/100) using a solver that uses only `prompt.md` and `Task_Env.get_assistant_tools()`.
- Eval criteria: 7 (`report_exists` 10, `correct_invoice_ids` 25, `correct_cif_values` 15, `correct_discrepancy_pct` 15, `correct_risk_levels` 15, `correct_sort_order` 10, `response_summary` 10; total 100).
- Source-access: step-6 escalation to read `v3/env.py` was needed.
- Issues and fixes:
  - Section 1-2 (structural integrity): clean — `env.py` and `prompt.md` byte-identical across versions; only `SCALE` differs in `data.py`.
  - Section 2 (response_summary tolerance bug): the `total_underpayment` check in `step()` used `< 1.0` USD tolerance against ground-truth computed from values rounded to 2dp before multiplying by quantity. An agent that follows the prompt naturally and computes underpayment from unrounded intermediates can land off by several USD across hundreds of flagged entries (e.g. ~6 USD on v3 with 182 entries), incorrectly losing the 5-pt amount sub-criterion. Fix: replaced the fixed `< 1.0` threshold with `max(1.0, 0.05 * len(ground_truth), 0.001 * abs(total_underpayment_gt))` so the tolerance scales with both entry count and magnitude. Edited `v0/env.py` and propagated byte-identical to `v1/v2/v3`. Re-verified with the unrounded-value solver: reward 1.0.
- Sections 3-4: criteria coverage matches every prompt requirement; ground truth is computed dynamically from current `data.db` / workspace, no hardcoded counts; prompt.md uses prose only, no bullets/headings/bold/code, no tool or source-data filenames, columns/precision/sort order specified, scale-invariant wording.
- Blockers: none.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/customs_value_verification`; `data.py` is byte-identical to SOURCE in all four versions (no M0 data change was needed — every deleted prompt rule was already stated in the generated workspace documents), and `step()` / `_compute_ground_truth()` scoring is unchanged.

### M2 — mixed return encodings (per-tool return-shape map)

| Tool | Success shape | Error shape |
|---|---|---|
| `count_invoices` | native dict `{"object": "count", "count": n}` | n/a (no failure path) |
| `list_invoice_ids` | native M3 list object (`{"object": "list", "results", "has_more", "next_cursor"}`) | `_error` dict |
| `get_invoice` | JSON-encoded string of a nested record | `json.dumps(_error(...))` |
| `get_product` | Python-repr string of a nested record (single quotes; needs `ast.literal_eval`) | `_error` dict |
| `get_shipment` | MCP-style envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) | `_error` dict |
| `get_supplier` | plain `key: value` text | `_error` dict |

2/6 tools return native dicts, so the model cannot assume a single encoding. Descriptions state what each tool returns, never how it is encoded.

### M3 — deep-nested record structures

`list_invoice_ids` uses cursor pagination (`has_more`/`next_cursor`, no `total`) over `{"object": "invoice", "id": ...}` records. `get_invoice` and `get_product` return Notion-style records with fields 3–4 levels deep: display text at `properties.<Name>.title[0].plain_text` (product name) and `properties["HS Code"].rich_text[0].plain_text`, category-ish values at `select.name` (currency, category, unit of measure), foreign keys at `properties.Supplier.relation[0].id` / `properties.Product.relation[0].id`, numerics at `.number`, dates at `.date.start`.

### Error contract

Tools never raise. Not-found → `_error(404, "object_not_found", "Could not find <entity> with ID: <id>.")`; bad input → `_error(400, "validation_error", ...)` with `_shape()`-rendered offending values (e.g. `body.invoice_id should be a non-empty string, instead was 'undefined'.`). Error dicts are `{"status", "object": "error", "code", "message", "request_id"}` and share no payload keys with any success shape; string-returning `get_invoice` returns its errors JSON-encoded so the shape branch survives serialization. All id parameters are typed `Any = None` in Python so malformed inputs reach validation instead of crashing.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 5 paragraphs to 4: scenario/goal (verbatim P1), an authoritative-documents pointer replacing the route-narration paragraph (which walked through database/tool querying) and the full valuation-methodology paragraph, then the verbatim deliverable contract and the verbatim final-response requirement. Every deleted methodology sentence (currency conversion formula, incoterm freight/insurance rules, always-applied port surcharge as pct of freight, always-included packaging/handling, per-unit division, discrepancy formula, >10 flag threshold, risk tiers) was verified to be stated in `customs_valuation_policy.md` / `incoterm_reference.yaml` in the generated workspace, so no additive `data.py` change was required.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| report_exists | prompt P3 (verbatim contract: `discrepancy_report.csv`) |
| correct_invoice_ids | customs_valuation_policy.md (CIF formula, discrepancy formula, flag rule `> 10.0`) + prompt P1 goal |
| correct_cif_values | customs_valuation_policy.md formula + incoterm_reference.yaml + exchange_rates.csv + freight_insurance_ledger_*.csv + invoice_supplements_*.csv + port_surcharges.yaml; 2dp rounding in prompt P3 |
| correct_discrepancy_pct | customs_valuation_policy.md discrepancy formula; 2dp rounding in prompt P3 |
| correct_risk_levels | customs_valuation_policy.md Risk Classification tiers |
| correct_sort_order | prompt P3 (sort key + tie-breaker, verbatim) |
| response_summary | prompt P4 (count, underpayment definition and total, risk-tier counts, verbatim) |

### Verification

- v3 (`rows_per_table=800`): `verify()` reward **1.0** (100/100), 2298 tool calls.
- v0 (`rows_per_table=100`): `verify()` reward **1.0** (100/100), 293 tool calls (≥ 15 floor).
- Negative-path smoke tests passed: 404 on nonexistent invoice/product/shipment/supplier ids (each in that tool's error form), 400 validation errors for `None`/non-string/dict-valued id params and non-integer pagination params, repr output rejected by `json.loads` but parsed by `ast.literal_eval`, envelope unwrap, `key: value` parse, cursor pagination without `total`.
- `env.py` and `prompt.md` byte-identical across v0–v3; no runtime artifacts left in any version directory.

## Harness Report (Verification Pass — 2026-07-02)

**v3 reward:** 1.0 (100/100)
**Eval criteria:** 7 — `report_exists` (10 pts), `correct_invoice_ids` (25 pts), `correct_cif_values` (15 pts), `correct_discrepancy_pct` (15 pts), `correct_risk_levels` (15 pts), `correct_sort_order` (10 pts), `response_summary` (10 pts); max 100.

**Section 1 — Structural integrity:** clean. `env.py` and `prompt.md` byte-identical across all versions; only `SCALE` dict differs in `data.py` (v0 100/10, v1 200/20, v2 400/30, v3 800/40). No stale databases, workspace dirs, pycache, or loose scripts.

**Section 2 — Solvability at v3:** solver written using only `prompt.md` + `get_assistant_tools()`. Loaded workspace reference docs (exchange rates, incoterm rules, port surcharges, market benchmarks, freight/insurance ledgers, supplements), queried DB directly, computed adjusted CIF per unit per policy formula, flagged 182 entries with discrepancy > 10%, wrote `discrepancy_report.csv`, submitted response. reward = 1.0 on first attempt; no env.py or data.py access needed before step.

**Section 3 — Env quality:** one completeness gap found and fixed.
- **Issue:** `response_summary` criterion only checked for total flagged count (5 pts) and total underpayment (5 pts). The prompt explicitly requires "a count of entries in each risk tier" in the final response, but no criterion enforced it — an agent could omit tier counts and still score 10/10 on that criterion.
- **Fix:** Resplit `response_summary` into three sub-checks: total flagged count (4 pts), total underpayment (4 pts), per-tier counts (2 pts — verifies the correct count for each non-empty tier appears in the response as a word-boundary-delimited number). Applied to `v0/env.py`, propagated byte-identical to `v1/v2/v3`. Re-verified: reward remains 1.0.
- All other criteria: coverage matches every prompt requirement; no hidden criteria; ground truth computed dynamically from `data.db` + workspace; no hard-coded counts; CIF tolerance (< 0.02 USD) and discrepancy tolerance (< 0.05 pct) are tight but fair; risk levels matched exactly; sort order enforced on the intersection of correct IDs.

**Section 4 — prompt.md quality:** all checks pass. No title/heading, no bold headers, no lists, no source filenames, no tool names. Computation logic delegated to workspace policy doc. Output file named, columns listed in exact order, sort key specified, scale-invariant wording throughout.

**Section 5 — Clean-up:** runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) removed from all version directories. Final structure: `README.md`, `v0/`, `v1/`, `v2/`, `v3/`, each version containing exactly `data.py`, `env.py`, `prompt.md`.
