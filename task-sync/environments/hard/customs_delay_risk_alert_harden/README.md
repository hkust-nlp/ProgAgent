## Task Topic

Identify shipments at high risk of customs delay by cross-referencing carrier advance manifests, real-time port congestion data, historical HS code inspection rates, and supplier compliance documentation, generating an alert list for proactive broker intervention.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=10.

**Structural dimensions used:**

- **Information Scattering**: Supplier compliance data lives exclusively in workspace JSON files while supplier names are only available via tool calls; carrier on-time rates come from DB tools while special-handling flags and documentation status come from workspace CSV manifests; port congestion indices come from DB tools while disruption delay factors come from workspace Markdown bulletins.
- **Conditional Constraints**: Risk scoring depends on configurable thresholds, bracket tables, tier mappings, and penalty rules all defined in workspace YAML/JSON config files. Alert eligibility, risk levels, and broker priorities are all threshold-driven.
- **Multi-Hop Reasoning**: Shipment → carrier tool → on-time rate → bracket scoring → plus manifest workspace file → special handling bonus → carrier raw score → weighted contribution → composite risk → trade lane bonus → final alert determination (chain length ≥ 4).

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 8 — `broker_dispatch_recorded` (10 pts), `alert_file_exists` (10 pts), `correct_columns` (10 pts), `shipment_identification` (25 pts), `risk_score_accuracy` (20 pts), `correct_sorting` (10 pts), `primary_risk_factor` (15 pts), `response_summary` (10 pts)
- v3 outcome: 46 high-risk shipments identified; highest-risk shipment SHP-0307 with composite score 88.08; all 46 broker dispatches filed with correct priority.
- Source-access: clean — solver derived from `v3/prompt.md` plus `get_assistant_tools()` only; no escalation to read `env.py` was needed.
- Structural integrity: confirmed. `env.py` and `prompt.md` byte-identical across v0..v3; only the SCALE block in `data.py` differs. SCALE values follow rows ×1/2/4/8 (100/200/400/800) and files +0/N/2N/3N with N=10 (10/20/30/40).
- Section 3 review: all 8 scored criteria map to explicit prompt requirements; ground truth is computed dynamically from `data.db` and workspace files (no hard-coded counts); scale invariance is preserved by the byte-for-byte `env.py` invariant across v0..v3.
- Section 4 review: `prompt.md` uses prose-only formatting with no headings, lists, tool names, source filenames, or absolute counts; deliverable filename and all column names are explicit; scope language is scale-invariant.
- Issues found: none. No fixes were required.
- Blockers: none.

## Hardening (M0 + M4 + M5)

Applied on top of `environments/standard/customs_delay_risk_alert`. Ground truth (`_compute_ground_truth`, `_compute_shipment_risk`, `_build_alert`) and all original scoring criteria are unchanged; `step()` gains exactly one new DB-state criterion under the M4 no-write-tool exception.

- **M0 — de-proceduralized prompt**: `prompt.md` rewritten from 5 formula-narrating paragraphs to 4: scenario/goal + scope, a pointer to the risk methodology document and policy/configuration files as the authoritative specification, the broker-dispatch requirement (M4), and the verbatim deliverable contract (two-decimal rounding, exact column list and order, sort key + tie-breaker, final-response requirements — all preserved word for word). `data.py` change (additive only): new fixed workspace document `risk_methodology.md` containing every rule previously stated only in the prompt — assessment scope (the three active statuses), the four dimension formulas with per-dimension caps, defaults for missing compliance/manifest records, bracket-selection semantics, composite weighting + trade-lane bonus + cap + rounding, alert-threshold semantics, CRITICAL/URGENT classification, primary-risk-factor tie-break order, recommended-action mapping, and the dispatch policy (URGENT/HIGH values). Per-version `data.py` files differ only in their `SCALE` block (100/10, 200/20, 400/30, 800/40).
- **M4 — nested write payload**: new tool `create_broker_dispatch(payload)` — `parent` (`{"type": "shipment", "shipment_id": ...}`) + `properties` with a required `Priority` select property (`{"type": "select", "select": {"name": "URGENT"|"HIGH"}}`) and an optional `Note` rich_text property. Validation is layered, one Notion-style error per call (body → parent → parent.type → parent.shipment_id → properties → Priority → Priority.type → Priority.select → select.name → allowed values → Note shape), then business checks: unknown shipment → 404 `object_not_found`; non-active shipment → 400; duplicate dispatch → 400. The write is an INSERT into `broker_dispatches` (created on demand; `data.py` untouched). Success returns a deep echo (`{"object": "dispatch", "id", "parent", "properties", "created": true}`) sharing no keys with errors. `step()` scores `broker_dispatch_recorded` (10 pts): every ground-truth high-risk shipment must have a dispatch row whose priority equals its `broker_priority` (max score 100 → 110; all original criterion point values unchanged).
- **M5 — unbounded bulk export**: new parameterless tool `export_shipment_risk_profiles()` returns every shipment (all statuses) joined with destination/origin port, carrier, supplier, and HS-code attributes as ONE JSON string, no pagination. Measured size: **~72.4k chars ≈ 18.1k tokens at v0** (survivable but expensive) and **~580.6k chars ≈ 145.2k tokens at v3** (fatal if echoed natively into context; must be consumed inside the programmatic sandbox). It is genuinely sufficient for the core filtering step; the paginated `query_shipments` and all per-entity lookup tools remain available as the safe alternative.

Per-tool return-shape map:

| tool | success shape |
|---|---|
| query_shipments | native dict (paginated) |
| export_shipment_risk_profiles | JSON-encoded string (M5 bulk export) |
| get_port_congestion | native dict |
| get_carrier_info | native dict |
| get_hs_code_info | native dict |
| get_supplier_record | native dict |
| create_broker_dispatch | native dict (deep Notion-style echo) |

Error contract: tools never raise. Every failure returns `{"status", "object": "error", "code", "message", "request_id"}` — not-found → `404/object_not_found`, bad input → `400/validation_error`. Success and error responses share no keys.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| broker_dispatch_recorded | prompt para 3 (dispatch requirement) + risk_methodology.md "Broker dispatch policy" (URGENT/HIGH values) |
| alert_file_exists | prompt (verbatim deliverable contract) |
| correct_columns | prompt (verbatim deliverable contract) |
| shipment_identification | prompt para 1 (scope) + risk_methodology.md "Assessment scope"/"Alerting" + risk_scoring_config.yaml `alert_threshold` |
| risk_score_accuracy | risk_methodology.md (formulas, caps, weighting, rounding) + risk_scoring_config.yaml + inspection_override_rules.json + supplier_compliance_*.json + carrier_manifest_*.csv + port_advisory_*.md + trade_lane_risk_*.yaml |
| correct_sorting | prompt (verbatim deliverable contract) |
| primary_risk_factor | risk_methodology.md (greatest weighted contribution + tie-break sequence) |
| response_summary | prompt final paragraph (count + highest-risk shipment + score) |

Verification: verify() consumes the bulk export once, in memory, and files a nested dispatch payload per alert — reward **1.0 at v0** (26 tool calls, ≥15 floor met) and **1.0 at v3** (124 tool calls, 46 alerts). Negative-path smoke tests pass: all 11 layered M4 validation errors fire one at a time, string-body / dict-vs-string traps, 404s for shipment/port/carrier/HS/supplier lookups, duplicate-dispatch and cleared-shipment business errors, and query_shipments status/page validation. `env.py` and `prompt.md` are byte-identical across v0–v3.
