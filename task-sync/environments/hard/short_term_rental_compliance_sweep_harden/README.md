## Task Topic

Detect unpermitted short-term rental properties. Analyze property tax records, rental platform listing data, utility consumption patterns, and occupancy permit registries to output a compliance case file for enforcement with evidence summaries.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Structural dimensions used:

- **Information Scattering**: Complaint counts are only available from workspace CSV files (keyed by address), permit data is only available via tools (keyed by property_id), platform revenue estimates are in workspace JSON files, and property details come from tool calls. Solving the task requires joining across all these sources.
- **Conditional Constraints**: Violation classification depends on zoning rules (from a workspace JSON config), permit status checks (via tools), and risk-score computation uses thresholds and modifiers defined in a workspace YAML config file. The recommended enforcement action is determined by score tiers in the same config.
- **Multi-Hop Reasoning**: Active listings (tool) → property zone (tool) → zoning rules (file) → permit check (tool) → utility baseline lookup (file) → utility history (tool) → complaint count (file) → risk score computation → action tier (file).

## Harness Report

- v3 reward: 1.0 (100/100) — confirmed after fix below.
- Eval criteria count: 6 (csv_structure, property_identification, violation_types, risk_scores, recommended_actions, response_summary). Max score: 100.
- Source-access path: clean. Solver written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()` and runtime workspace files (`enforcement_config.yaml`, `zoning_map.json`, `utility_baselines.csv`, `complaint_batch_*.csv`, `platform_intel_*.json`, `data.db`). `env.py` was not opened until step-6 of Section 2 (post-reward-1.0 Section 3 audit).
- Structural integrity: passed. Top-level contains `README.md` + `v0..v3` only; each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across all four versions; `data.py` differs only in the `SCALE` block (rows ×1/2/4/8, files +0/N/2N/3N).
- Issues found and fixed (1):
  - **Sort-order not enforced** (Section 3, Criterion 3 — Precise matching): `prompt.md` explicitly requires CSV rows to be sorted by `risk_score` descending, ties broken by `property_id` ascending. The original `step()` never verified this. Fix: the `csv_structure` criterion (v0/env.py → propagated to v1–v3) now checks sort order; scoring split to 8 pts (columns correct) + 2 pts (sort order correct), max remains 10. Solver already sorted correctly so reward stays 1.0.
- prompt.md quality: passed all Section 4 checks — no title, no bold headers, no bulleted lists, no tool names or source filenames, columns explicitly named and ordered, scale-invariant wording throughout.
- Final clean-up: removed runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) from all four version directories.

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/short_term_rental_compliance_sweep`; `step()` ground truth, criteria, and weights are unchanged.

- **M5 unbounded bulk export**: new tool `export_compliance_snapshot()` returns the complete joined dataset — one record per rental listing (any status) with the full nested property record, all occupancy permits on file, and the property's twelve-month average utility consumption — as ONE JSON string, no pagination. Measured size: ~14.2k tokens at v0 (56,836 chars; survivable but expensive), ~115.3k tokens at v3 (461,208 chars; echoing it natively into context is fatal under a ~70k-token response budget — it must be consumed inside the programmatic sandbox and filtered before printing). It is genuinely sufficient for the core filtering step (zoning classification, permit checks, utility anomaly, extra-listing counting). All original paginated/per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (descriptions say WHAT, never HOW encoded):

  | tool | success shape |
  |---|---|
  | `search_listings` | native dict (paginated) |
  | `get_permit_status` | native dict |
  | `export_compliance_snapshot` | JSON-encoded string |
  | `get_property_info` | MCP envelope (`json.loads(resp["content"][0]["text"])`) |
  | `get_utility_history` | Python-repr string (`ast.literal_eval`) |
  | `get_listing_details` | plain `key: value` text |

- **Error contract**: tools never raise. Every failure returns `{"status", "object": "error", "code", "message", "request_id"}` — a shape sharing NO keys with any success response. Not-found → `404 object_not_found` ("Could not find <entity> with ID: ..."); bad input → `400 validation_error` with Notion-style messages (`body.property_id should be a non-empty string, instead was 'undefined'.`). The old `{"error": ...}` success-keyed errors were removed.
- Negative paths smoke-tested: 404 on all four lookup tools, enum/type validation on `search_listings`, dict/None/int passed as string ids, malformed YYYY-MM month.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 4: scenario/goal, a pointer to the enforcement methodology + policy/configuration documents as the authoritative specification, the verbatim deliverable contract (file name, exact column list and order, evidence_summary content, sort key + tie-breaker — kept word for word), and the unchanged final-response requirement. Deleted: config-file navigation ("Begin by reviewing the YAML... a JSON file maps... a CSV provides baselines"), the violation-classification walkthrough, the risk-score formula narration, and the revenue-aggregation recipe. `data.py` change (additive only, fixed non-scaling document): new `enforcement_methodology.md` written to the workspace, containing scope (active listings only), the full violation classification rules (zoning_violation / no_permit / expired_permit, revoked-or-pending → no_permit), the risk-score modifiers (complaint counting across batch files, twelve-months-of-2025 utility averaging with baseline × sqft × spike threshold, per-extra-listing bonus, cap), highest-tier-downward action selection, and per-property revenue aggregation. SCALE blocks preserved per version; per-version `data.py` files differ only in `SCALE`.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| csv_structure | prompt (verbatim deliverable contract) |
| property_identification | enforcement_methodology.md (scope + classification) + zoning_map.json |
| violation_types | enforcement_methodology.md (classification rules incl. revoked/pending convention) |
| risk_scores | enforcement_methodology.md (modifier formulas, 2025-01..12 window) + enforcement_config.yaml (base scores, bonuses, thresholds, cap) + utility_baselines.csv + complaint batch files |
| recommended_actions | enforcement_methodology.md (highest-tier-downward rule) + enforcement_config.yaml (tier thresholds/actions) |
| response_summary | prompt (final paragraph, unchanged) |

### Verification

- `verify()` consumes the bulk export once, in memory, for classification/anomaly data; paginates `search_listings` (native dict); and cross-checks the top cases through the envelope, native, repr, and key:value tools. Reward **1.0 at v0 (24 tool calls)** and **1.0 at v3 (45 tool calls)**; tool-call floor ≥ 15 holds at v0.
- `env.py` and `prompt.md` byte-identical across v0–v3; no runtime artifacts left in any version directory.
