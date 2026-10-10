## Task Topic

Identify high-risk orders for manual fraud review. Cross-reference customer purchase history, IP geolocation mismatch flags, real-time card issuer decline codes, and shipping address verification scores to output a prioritized queue of suspicious orders with recommended verification steps.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 8                   |
| v1      | 200            | 16                  |
| v2      | 400            | 24                  |
| v3      | 800            | 32                  |

Structural dimensions used:

- **Information Scattering**: Customer fraud history (previous fraud counts, chargeback records, account age) lives exclusively in workspace CSV batch files, while per-order risk signals (IP geolocation checks, card issuer responses, address verification scores) are only accessible through tool calls. Transaction pattern flags (rapid ordering, unusual amounts, multiple addresses) are in separate workspace JSON batch files. Solving the task requires combining all three sources.
- **Multi-Hop Reasoning**: The agent must chain: list pending orders (tool) → retrieve IP/card/AVS signals per order (tools) → look up decline-code severity from a JSON reference file → look up AVS tier from a CSV reference file → read customer risk profiles from batch CSVs → read transaction patterns from batch JSONs → apply scoring weights from a YAML config → compute composite scores → map triggered conditions to verification actions from a Markdown procedures document → produce sorted output.
- **Conditional Constraints**: Risk classification depends on configurable thresholds (high ≥ 50, medium ≥ 30) and per-factor caps from the YAML config. Recommended verification actions are conditionally triggered by specific indicator values and severity thresholds defined in the procedures document.

## Harness Report

- v3 reward: 1.0 (110/110)
- Number of eval criteria: 8 (file_structure, order_ids, risk_levels, risk_scores, sort_order, recommended_actions, response_summary, review_cases_recorded)
- Source-access: clean. The solver was written from `v3/prompt.md` plus `Task_Env.get_assistant_tools()` only; no escalation to `env.py` was required.
- Structural integrity: PASS. Top-level contains exactly `README.md` + `v0/`…`v3/`. Each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-for-byte identical across v0…v3. Only the `SCALE` dict differs across `data.py` versions (v1=2×, v2=4×, v3=8× rows; workspace files +N, +2N, +3N).
- Solvability: PASS at reward 1.0. Initial solver attempt scored 0.818 (90/110) — the `ip_geolocation_checks` column is named `mismatch_flag` (not `country_mismatch`), causing the solver to silently skip all IP mismatch points and under-score 24 orders that should have reached the MEDIUM threshold. Fixed by correcting the column reference in the solver. The env and prompt were correct throughout; the issue was purely in the solver's wrong column name assumption.
- Env quality: PASS. All 8 step() criteria map to explicit prompt.md requirements. Ground truth is computed live from `data.db` + workspace; no hard-coded counts or data-distribution assumptions. Score tolerance is ±2 (integer rounding only). Action matching is exact. Summary check uses substring matching with "ORDER_ID: SCORE" format as specified in prompt.md.
- Prompt quality: PASS. No heading at top, no bold section headers, no bulleted/numbered deliverable lists, no tool names or env internals, scale-invariant ("Every order currently sitting in 'pending_review' status"), exact column sequence and output filename specified, scoring deferred to workspace documents.
- Fixes applied: none to env.py, prompt.md, or data.py.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/fraud_screening_order_queue`. Ground truth
(`_compute_ground_truth`) and the 7 original scoring criteria are byte-unchanged;
`step()` gains one DB-state criterion (`review_cases_recorded`, 10 pts, M4
write-tool conversion — SOURCE had no write tool).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 route-narrating
  paragraphs to 4: scenario/goal, a pointer to the policy/methodology/reference
  documents as the authoritative spec (plus the case-recording requirement),
  the verbatim deliverable contract (columns, sort keys, tie-breaker, integer
  scores, "; "-joined actions in procedures-document order), and the verbatim
  final-response requirement. `data.py` changes (additive only, SCALE untouched):
  new fixed `scoring_methodology.md` (five component formulas incl. proxy/VPN
  counts-once, inclusive AVS tier bounds, strict `<` new-account boundary,
  absent-code severity 0, missing-batch-record defaults, sum-then-cap, integer
  recording, HIGH/MEDIUM/LOW classification, queue membership); `fraud_review_policy.txt`
  gained a CASE RECORDING section naming queue ID `fraud-review` and requiring
  each queued order to be recorded with its risk level.
- **M1 JSON-string parameter**: `list_orders_by_status` replaced by
  `list_orders(filter, page, page_size)` where `filter` must be a JSON-encoded
  string (`'{"status": "pending_review"}'`; supported: status, shipping_country,
  currency). Malformed JSON returns `invalid_json` with line/column/char;
  passing an object instead of a string, unsupported keys, or wrong-typed
  values returns recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_review_case(payload)` with a
  Notion-style body (`parent.type='review_queue'` + `parent.queue_id`,
  `properties.Order.reference.order_id` reference, `properties.RiskLevel.select.name`
  select, optional `Note` rich_text). Validation is layered — one error per call,
  messages like `body.parent.queue_id should be a non-empty string, instead was
  'undefined'.` — followed by business checks (queue exists, order exists, order
  pending, level HIGH/MEDIUM). The write is an idempotent INSERT OR REPLACE into
  a `review_cases` table created on first use. Success responses
  (`{"object": "review_case", ..., "created": true}`) share no keys with errors.

Per-tool return-shape map (M2 not assigned — all success returns are native dicts):

| tool | success shape | error shape |
|---|---|---|
| list_orders | dict `{orders, total, page, page_size, total_pages}` | `_error` dict |
| get_order_details | flat dict (order row) | `_error` dict |
| get_ip_geolocation_check | flat dict | `_error` dict |
| get_card_transaction | flat dict | `_error` dict |
| get_address_verification | flat dict | `_error` dict |
| get_customer_profile | flat dict | `_error` dict |
| create_review_case | deep echo `{object, id, parent, properties, created}` | `_error` dict |

Error contract: tools never raise; every failure returns
`{status, object:"error", code, message, request_id}` — a key set disjoint from
every success shape. Not-found → `404 object_not_found`
("Could not find <entity> with ID: <id>."); bad input → `400 validation_error` /
`400 invalid_json` / `400 invalid_request`.

Completeness audit (step() criterion -> info source):

| criterion | source |
|---|---|
| file_structure | prompt (verbatim contract: filename + exact column sequence) |
| order_ids | scoring_methodology.md (classification + "only HIGH and MEDIUM enter the queue") over pending_review orders (prompt scenario) |
| risk_levels | scoring_methodology.md (threshold classification) + risk_scoring_config.yaml (thresholds) |
| risk_scores | scoring_methodology.md (component formulas, caps, sum-then-cap, integer) + risk_scoring_config.yaml / issuer_response_codes.json / avs_score_tiers.csv (values) |
| sort_order | prompt (verbatim: risk_score desc, order_id asc tie-break) |
| recommended_actions | verification_procedures.md (conditions + exact action strings) + prompt ("; " join, procedures-document order) |
| response_summary | prompt (verbatim final-response requirement incl. "ORDER_ID: SCORE" format) |
| review_cases_recorded | prompt ("recorded as a case ... in the queue designated by the review policy, together with its assessed risk level") + fraud_review_policy.txt CASE RECORDING (queue ID "fraud-review") |

Verify results: v0 reward 1.0 (104 tool calls), v3 reward 1.0 (916 tool calls).
Negative paths smoke-tested: M1 malformed JSON / dict-instead-of-string /
unsupported key / wrong-typed value; M4 layered messages one at a time from
missing body through innermost order_id, wrong queue -> 404, nonexistent order
-> 404, non-queue level -> validation_error.
