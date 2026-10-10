## Task Topic

Detect fraudulent virtual item trading by cross-referencing player account histories, peer-to-peer marketplace listings, item rarity databases, and sudden wealth influx alerts, producing a daily report of suspicious accounts for manual review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Session logs (IP addresses), account flags (prior violations), and item price snapshots live exclusively in workspace files, while player profiles, marketplace listings, item details, and wealth alerts are accessible only through tool calls. Fraud scoring rules, rarity tier configurations, and region risk multipliers reside in separate config files. All three sources must be combined to compute the final score.
- **Multi-Hop Reasoning**: Computing the price-anomaly factor requires a chain of length 4: retrieve the player's marketplace listings (tool) -> for each listing retrieve the item details (tool) -> look up the item's recent price snapshots in workspace CSV files -> compare the listing price against the anomaly multiplier times the averaged market reference price.
- **Conditional Constraints**: Suspicious-account classification depends on a configurable threshold, and the recommendation tier (block / restrict / investigate) is determined by multiplier thresholds applied to the fraud score. Account-age bonuses, trade-frequency triggers, and multi-IP checks each gate on their own threshold parameters read from a YAML config file.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 8 (`report_structure` 15, `account_identification` 20, `alert_type_accuracy` 5, `fraud_scores` 15, `evidence_accuracy` 5, `recommendations` 15, `sorting` 10, `response_summary` 15).
- Section 1 structural integrity: passed. Top-level contains only `README.md` and `v0..v3/`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the SCALE block (rows 100/200/400/800, files 10/20/30/40).
- Section 2 solvability: passed. Solver constructed from `v3/prompt.md` + `Task_Env.get_assistant_tools()` only; reward 1.0 on first submit (138 reviewed, 72 suspicious: block=15, restrict=16, investigate=41). `env.py`/`data.py` not opened during solving.
- Issue found: the original 6-criterion `step()` did not validate the **values** of the `alert_type` or `primary_evidence` columns — only their names. An agent could insert arbitrary strings in those columns and still receive full credit. Fix: added two criteria (`alert_type_accuracy` 5 pts, `evidence_accuracy` 5 pts) and reduced `account_identification` from 25 to 20 pts and `fraud_scores` from 20 to 15 pts; total max_score remains 100. Both new criteria pass at reward=1.0. Fix applied to `v0/env.py` and propagated byte-for-byte to `v1..v3/`.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from `v3/`; removed the task-root `solve.py` generated during verification.
- Blockers: none.

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/fraudulent_trading_detection`; ground truth (`_compute_ground_truth`) and `step()` scoring are unchanged. `data.py` changes are additive only (one fixed policy document); per-version `data.py` files differ from each other only in the SCALE block.

- **M5 unbounded bulk export**: new tool `export_trading_activity()` returns every player profile, item record, marketplace listing, and wealth alert as ONE JSON string with no pagination. Measured `len(raw)//4`: **~15.6k tokens at v0** (survivable but expensive; ≤20k bound holds), ~31k at v1, ~63k at v2, **~126k tokens at v3** (echoing it natively into context is fatal under a ~70k response budget; ≥100k bound holds). It is genuinely sufficient for the DB-side core of the task (pending alerts, profiles, listings, item levels/base values) and is intended to be consumed inside the programmatic sandbox with only a filtered summary printed. All paginated / per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (descriptions state content, never encoding):

  | tool | success shape |
  |---|---|
  | `get_wealth_alerts` | native dict (paginated) |
  | `get_player_listings` | native dict (paginated) |
  | `get_player_profile` | plain `key: value` text |
  | `get_item_details` | Python-repr string (`ast.literal_eval`; `json.loads` fails) |
  | `get_player_transactions` | MCP envelope (`json.loads(resp["content"][0]["text"])`, payload key `transactions`) |
  | `export_trading_activity` | one JSON-encoded string |

- **Error contract**: tools never raise. Every failure returns `{"status", "object": "error", "code", "message", "request_id"}` — sharing no keys with any success shape. Not-found → `404 object_not_found` ("Could not find <entity> with ID: <id>."); bad enum / wrong-typed / missing / out-of-range integer params → `400 validation_error` with Notion-style messages (`body.page should be an integer, instead was ''1''.`). All int params are typed `Any = None` so malformed inputs reach validation instead of crashing (bools are rejected as integers).
- **Negative-path smoke tests** (all pass at v0): 404 on nonexistent player/item; bad `review_status` enum; string/list/float/bool/None where integers are required; `page_size=0`; success/error key disjointness; no tool raises on garbage input.
- **verify()**: reward **1.0 at v0 (77 tool calls)** and **1.0 at v3 (562 tool calls)**. It pulls the bulk export once and filters it in memory (listings/items core), pages pending alerts via the native tool, kv-parses profiles, `ast.literal_eval`s item details, and unwraps the transactions envelope.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 9 route-narrating paragraphs to 4: scenario/goal, a pointer to the fraud scoring methodology document + configuration files as the authoritative specification, the verbatim deliverable contract (file name, exact column list and order, sort key, tie-breaker, suspicious-only row filter, `alert_type` definition — kept word for word from SOURCE), and the verbatim final-response requirement. All formula/threshold narration was removed from the prompt; since those rules were prompt-only in SOURCE (fraud_rules.yaml holds numbers, not procedures), they were moved into a new fixed workspace document `fraud_scoring_methodology.md` written by `data.py` (the only data.py change): review scope, severity ranking and base-score/alert-type selection, all seven factor computations with strict-inequality boundary conventions, snapshot-averaging reference price with base-value fallback, region multiplier + 1.0 default + one-decimal rounding, suspicion threshold, recommendation tiers, and the primary-evidence rule including the canonical factor identifiers (`new_account_bonus`, `high_frequency_trading`, `price_anomaly`, `level_mismatch`, `multi_ip_sessions`, `wealth_influx_severity`, `prior_flags`, `alert_base`) — the last of which was not fully discoverable even in the SOURCE prompt.

Completeness audit (step() criterion → info source):

| criterion | pts | source |
|---|---|---|
| report_structure | 15 | prompt ¶3 (verbatim contract: filename, columns, order) |
| account_identification | 20 | fraud_scoring_methodology.md (scope, factors, suspicion rule) + fraud_rules.yaml (weights/thresholds/base scores) + region_risk.csv + session/flag/snapshot workspace files |
| alert_type_accuracy | 5 | fraud_scoring_methodology.md ("Base score and alert type" section: alert_type = type of highest-severity pending alert) |
| fraud_scores | 15 | fraud_scoring_methodology.md (factor formulas, region multiplier, one-decimal rounding) + fraud_rules.yaml numbers |
| evidence_accuracy | 5 | fraud_scoring_methodology.md ("Primary evidence" section + canonical identifiers) |
| recommendations | 15 | fraud_scoring_methodology.md (tier rule) + fraud_rules.yaml recommendation_tiers |
| sorting | 10 | prompt ¶3 (verbatim: fraud_score desc, player_id asc) |
| response_summary | 15 | prompt ¶4 (verbatim: totals + tier breakdown) |

Every criterion is traceable to the prompt or a named workspace document; nothing is reachable only from `env.py` source. v0/v3 verify re-run after harness-session fixes: reward 1.0.
