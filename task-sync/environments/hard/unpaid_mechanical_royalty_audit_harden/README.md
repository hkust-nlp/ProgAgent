## Task Topic

Identify unpaid mechanical royalties for streaming. Cross-reference ISRC codes from streaming platform reports, publisher and songwriter splits from registration databases, and historical payment ledgers to flag unmatched tracks, generating a discrepancy report for collection societies.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

Scaling ratios: rows grow as 1×/2×/4×/8×; workspace files grow as N/N+N/N+2N/N+3N where N=8.

Structural dimensions used:

- **Information Scattering**: Streaming platform data lives in workspace CSV files while registration splits and payment history are only accessible via tool calls. Royalty rate cards, territory commission tables, and reconciliation policy thresholds are each in separate workspace config files (YAML, CSV, JSON, MD). Solving the task requires combining all of these sources.
- **Multi-Hop Reasoning**: The dependency chain is at least five hops long — streaming CSV → rate card lookup → registration tool call → territory commission file → payment tool call → expected-vs-actual comparison.
- **Conditional Constraints**: Whether a track is flagged as UNDERPAID depends on the shortfall threshold from the policy file; SPLIT_ANOMALY detection depends on a percentage tolerance; commission rates vary by registration territory.
- **Deliverable Constraints**: The output CSV must follow an exact column order, specific sort keys (type then ISRC), two-decimal monetary precision, and prescribed semantics for each discrepancy type's amount fields.

## Harness Report

- v3 reward: 1.0 (100/100) on first solver attempt.
- Eval criteria: 6 — `report_format` (10), `unregistered_accuracy` (20), `unpaid_accuracy` (20), `underpaid_accuracy` (25, set+amount), `split_anomaly_accuracy` (10), `summary_accuracy` (15).
- Source-access: clean — solved using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no step-6 escalation.
- Structural integrity: passed. v0/v1/v2/v3 each contain only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the SCALE block.
- Section 3/4 review: prompt and step are well aligned (coverage, completeness, scale-invariance all hold). Step computes ground truth from current DB/workspace with no hard-coded counts. Prompt has no headings/bold/lists, no tool names, no absolute counts. No fixes required.
- Issues found: none requiring code changes.

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/unpaid_mechanical_royalty_audit`; `step()` ground truth, criteria, and weights are unchanged.

- **M5 unbounded bulk export**: new tool `export_reconciliation_ledger()` returns every catalogued track joined with its active registrations and all payment records as ONE JSON string, no pagination — ~18.1k tokens (72,433 chars) at v0 (survivable but expensive) up to ~204k tokens (816,513 chars) at v3 (echoing it natively into context is fatal under a ~70k-token response budget; it must be consumed inside the programmatic sandbox and filtered before printing). All paginated / per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (one stable form per tool; descriptions never reveal the encoding):

  | tool | success shape |
  |---|---|
  | `list_tracks` | native dict (unchanged) |
  | `get_account_info` | native dict |
  | `get_payment_history` | JSON-encoded string |
  | `export_reconciliation_ledger` | JSON-encoded string (M5) |
  | `get_registrations` | MCP envelope (`content[0].text` holds JSON) |
  | `lookup_track` | plain `key: value` text |
  | `search_payments` | Python-repr string (`json.loads` fails; needs `ast.literal_eval`) |

- **Error contract**: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` (JSON-string form for the JSON-string tools), sharing NO keys with any success shape. Not-found → `404 object_not_found` ("Could not find <entity> with ID: ..."); bad input → `400 validation_error` ("body.<field> should be a non-empty string/integer, instead was '...'"). Wrong-typed params reach validation instead of crashing (`Any = None` signatures).
- verify() rewritten to consume the new surface (bulk export parsed once in memory for payments; envelope/kv-text/JSON-string/repr/native parsing all exercised): reward **1.0 at v0** (181 tool calls) and **1.0 at v3** (1437 tool calls), all six criteria full marks.
- Negative-path smoke tests passed: nonexistent ISRC/entity → 404 error dict; non-string ISRC, missing param, non-string period, string page, boolean page → the layered `validation_error` messages above; JSON-string tools return their errors as JSON strings.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 5: scenario/goal (kept from source), a pointer to the processing notes + policy/configuration documents as the authoritative specification, and the verbatim deliverable contract (report columns/order, per-type amount semantics, "Unknown" fallback, two-decimal rounding, sort keys; the `summary.json` key contract; the final-response requirement). Deleted: tool hand-holding, sequencing scaffolds, per-file navigation, and the expected-net formula / category-definition paragraphs (all restated in workspace `processing_notes.md`).

`data.py` change (additive to the fixed, non-scaling `processing_notes.md` only; SCALE blocks preserved per version): added (1) the streaming-file naming convention (platform + period label) and the "every distinct ISRC appearing in any streaming report must be assessed" scope rule, and (2) the "a single ISRC may qualify under multiple categories and is reported once per applicable type" rule — both were previously stated only in the prompt.

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| report_format (10) | prompt (verbatim contract paragraph) |
| unregistered_accuracy (20) | processing_notes.md (UNREGISTERED definition + gross formula, scope + file-naming rules) + royalty_rates.yaml |
| unpaid_accuracy (20) | processing_notes.md (UNPAID definition, expected-net formula, per payee-period rounding) + royalty_rates.yaml + territory_commissions.csv |
| underpaid_accuracy (25) | processing_notes.md (UNDERPAID definition + formula) + reconciliation_policy.json (`shortfall_threshold_usd`) + prompt (aggregated expected/paid/shortfall column semantics) |
| split_anomaly_accuracy (10) | processing_notes.md (SPLIT_ANOMALY definition, multi-category rule) + reconciliation_policy.json (`split_tolerance_pct`) + prompt (100.00 / split-sum / 0.00 column semantics) |
| summary_accuracy (15) | prompt (verbatim `summary.json` key contract) |

v0 and v3 verify re-run after the M0 edits: reward 1.0.
