## Task Topic

Audit franchisee inventory for unauthorized supplier usage. Cross-reference purchase order invoices, approved vendor lists, central distribution center shipment records, and product quality complaints to flag procurement violations, generating a supplier compliance report with evidence.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=8.

Structural dimensions used:

- **Conditional Constraints**: Violation identification depends on cross-referencing purchase orders against regional approved vendor lists (with approval date windows), complaint thresholds from the compliance policy, and DC shipment matching. The audit scope file filters franchisees by status.
- **Information Scattering**: Approved vendor lists and DC shipment records live in workspace CSV/JSON files; purchase orders, supplier details, and quality complaints are only accessible via tool calls. Compliance thresholds and severity multipliers are in a YAML config file, and audit scope parameters are in a separate text file.
- **Multi-Hop Reasoning**: Franchisee region (tool) -> regional approved vendor CSV (file) -> supplier approval dates (file) -> purchase order dates (tool) -> violation determination. Similarly: supplier complaints (tool) -> complaint count vs threshold (file) -> severity multiplier lookup (file) -> severity score computation.

## Harness Report

- v3 reward: **1.0** (100/100). Eval criteria: 6 — report_format (10), violations_recall (25), violations_precision (20), severity_scores (15), sort_order (10), response_summary (20).
- Structural integrity: pass. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows_per_table 30/60/120/240; num_workspace_files 8/16/24/32). No stale artifacts.
- Solvability: solver written using only `v3/prompt.md` + `Task_Env.get_assistant_tools()` + runtime DB/workspace inspection. One debug iteration was required before reward 1.0: the franchisee `region` field in the DB uses `Region_A` style but the approved-vendor CSV filenames use `region_a`, so the lookup key must extract just the trailing letter (`split("_")[-1].upper()`), not uppercase the full region string. The first solver attempt (keying by `REGION_A`) got precision 0.38 / recall 0.84; after fixing the region key both reached 1.0. No changes to any task file were needed.
- Env quality: `step()` — all 6 criteria correspond to explicit requirements in `prompt.md`; all prompt deliverables are covered. Ground truth is computed dynamically from `data.db` and workspace files; no hardcoded counts. Severity tolerance (`< 0.01`) is appropriate for 2 dp. Sort check is correct (desc severity → asc franchisee_id → asc order_date). Response summary checks for total count, per-type breakdown, distinct franchisee/supplier counts, and top-3 franchisee names. `env.py` is byte-for-byte identical across all four versions.
- prompt.md quality: prose-only (no title, no bold headers, no bullet/numbered lists); computation logic in natural language; no tool names or source-data filenames exposed; output file named explicitly with all 10 column names; scale-invariant wording throughout.
- Issues fixed: none — no edits to `env.py`, `prompt.md`, or `data.py` were required.

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/unauthorized_supplier_audit`; ground truth (`_compute_ground_truth`) and `step()` scoring are unchanged. Only the tool surface, `verify()`, the prompt (M0), and one additive workspace document (M0) changed.

- **M5 unbounded bulk export**: new tool `export_procurement_ledger()` returns the entire purchase-order ledger (POs joined with franchisee name/region/status and supplier name/category/certification) as ONE JSON string, no pagination — measured ~18.6k tokens at v0 (survivable but expensive) and ~149k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and filtered before printing). It is sufficient for the core filtering step (status scoping + per-PO franchisee/supplier join); the paginated/per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (per-tool map):
  | tool | success shape |
  |---|---|
  | `list_franchisees` | native dict (paginated) |
  | `get_franchisee_details` | native dict (`{"franchisee": {...}}`) |
  | `get_purchase_orders` | MCP-style envelope (`content[0].text` holds JSON) |
  | `get_supplier_info` | plain `key: value` text |
  | `get_quality_complaints` | Python-repr string (`ast.literal_eval`, not `json.loads`) |
  | `export_procurement_ledger` | JSON-encoded string |
- **Error contract**: tools never raise. All failures return `{"status", "object": "error", "code", "message", "request_id"}` — not-found → `404 object_not_found`, bad input → `400 validation_error`. Success and error responses share no top-level keys (franchisee detail is nested under `"franchisee"` to avoid colliding on `status`), so consumers must branch on shape.
- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 6 route-narrating paragraphs to 4: scenario/goal (kept verbatim), a pointer to the audit methodology/policy/configuration documents as the authoritative specification, the verbatim deliverable contract (file name, exact column list and order, non-QUALITY_FLAGGED severity rule, two-decimal precision, per-type evidence content, sort key and both tie-breakers), and the verbatim final-response requirement. All tool hand-holding, sequencing scaffolds, and per-file navigation deleted. `data.py` change (additive fixed-file only, SCALE untouched): new workspace document `audit_methodology.md` carrying the rules that previously lived only in the prompt — status-filter scoping, regional approved-vendor check, UNAPPROVED_SUPPLIER vs EXPIRED_APPROVAL determination and their mutual exclusivity, order-date-after-`approval_end` boundary, system-wide complaint counting for QUALITY_FLAGGED, invoice-number matching against shipment `invoice_ref` for DC_BYPASS, and one-row-per-(PO, violation-type) counting.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| report_format (file + exact columns) | prompt (verbatim contract); also compliance_policy.yaml `report_requirements` |
| violations_recall / violations_precision | audit_methodology.md (scoping, all four determination rules, mutual exclusivity, invoice matching, multi-type counting) + compliance_policy.yaml `violation_types` + audit_parameters.txt `franchisee_status_filter` + approved_vendors_*.csv + dc_shipment_batch_*.json |
| severity_scores | compliance_policy.yaml (`severity_weight`s, `severity_multipliers`, `severity_score_formula`) + prompt contract (non-QUALITY_FLAGGED rule, two-decimal precision) |
| sort_order | prompt (verbatim contract); also compliance_policy.yaml `report_requirements.sort_order` |
| response_summary | prompt final paragraph (verbatim) |

Verification: `verify()` consumes the bulk export once in memory, pages the native-dict franchisee list, cross-checks the ledger against the envelope-returning paginated PO tool, parses `key: value` supplier text and repr-string complaint pages — reward **1.0 at v0 (65 tool calls) and v3 (485 tool calls)**. Negative-path smoke tests: 404 error dicts for nonexistent franchisee/supplier IDs (including from string-returning tools), `validation_error` with `'undefined'` / wrong-type shapes for bad `page`/`page_size`/ID params, envelope/kv/repr/JSON-string shape assertions, and success∩error key disjointness per tool.
