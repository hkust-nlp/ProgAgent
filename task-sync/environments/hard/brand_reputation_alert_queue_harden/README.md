## Task Topic

Monitor brand reputation by scanning news headlines, measuring social media volume anomalies, categorising support ticket sentiment, and tracking executive communications to generate a prioritised alert queue for the communications team.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Scaling ratios: rows follow 1x / 2x / 4x / 8x; workspace files follow base / base+N / base+2N / base+3N where N = 8 (the v0 base).

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across workspace files and tool-accessible data. Brand monitoring tiers live in CSV files, historical social-media baselines in JSON files, ticket severity overrides in analyst-note TXT files, and executive watchlists in YAML files. Meanwhile, current social-media volumes, headline text, ticket content, and executive communication summaries are only available through tool calls. The agent must cross-reference both sources to compute each signal correctly.

- **Multi-Hop Reasoning**: The dependency chain for each brand's severity score is at least four hops long: (1) read tier from workspace CSV → (2) query social-media metrics via tool and compare against workspace baselines → (3) query headlines via tool and score with workspace sentiment keywords → (4) query ticket content via tool, classify sentiment, and adjust with workspace severity overrides → (5) query executive comms via tool and match spokespersons against workspace watchlist → (6) combine all signals using workspace priority matrix weights and scaling factors.

- **Conditional Constraints**: Alert inclusion depends on a configurable threshold from the priority matrix; severity scoring involves multiple conditional multipliers (tier multiplier, severity override multiplier, risk assessment multiplier) sourced from workspace configuration files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (alert_queue_format, correct_brands, correct_severity_scores, correct_ranking, correct_signal_values, brand_risk_summary, action_string)
- Solver source-access: required step-6 escalation. The black-box solver (using only v3/prompt.md plus get_assistant_tools()) produced a faithful answer but step() returned reward 0.67. After confirming the solver matched the prompt, env.py was opened.
- Issue: ticket-notes parser in `_read_workspace_configs` (and the parallel block in `verify`) used `content.split("===")`, which splits each `=== Brand: NAME (ID: N) ===` header into two pieces. The ID landed in one fragment and the severity in the next, so no overrides were ever extracted; every brand silently fell back to the "normal" multiplier (1.0), corrupting ground truth for ~95 ticket-negativity values and dropping 5 brands from the expected alert list.
- Fix: replaced both occurrences with a `re.compile(r"=== Brand:[^=]*?\(ID:\s*(\d+)\s*\)\s*===\s*(.*?)(?=(?:\n=== Brand:)|\Z)", re.DOTALL)` finder that captures each brand's full block, then runs the severity regex inside the captured body. Edit was made in v0/env.py and propagated byte-for-byte to v1/v2/v3.
- Other sections: structural integrity passed after removing stale `alert_queue.csv` and `brand_risk_summary.json` left under v3/; SCALE ratios verified (50/100/200/400 rows, 8/16/24/32 workspace files); prompt and env.py byte-identical across versions; prompt.md formatting and content rules satisfied.
- Solver re-run after fix: reward = 1.0.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/brand_reputation_alert_queue`. Ground truth (`_compute_ground_truth`) and criterion weights are unchanged; only the tool surface, the prompt (M0), and one deliverable's transport (M4) changed.

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 route-narrating paragraphs to 5: scenario/goal, a pointer to the methodology/configuration documents as the governing spec, the verbatim deliverable contract (threshold rule, sort keys/tie-breaker, `alert_queue.csv` columns and precision), the alert-filing requirement, and the verbatim final-response format. The signal formulas, keyword-matching semantics, override/tier/risk multipliers, defaults, and the combination procedure were prompt-only rules; they now live in a new fixed workspace document `alert_methodology.md` written by `data.py` (additive change only — tables, row generation, seeds, and per-version `SCALE` blocks untouched).
- **M1 JSON-string parameters**: `search_headlines` and `get_support_tickets` each take a single `filter` parameter that must be a JSON-encoded string (e.g. `'{"brand_id": 3, "status": "open"}'`). Supported keys: headlines — `brand_id` (required int), `category` (enum), `source` (string); tickets — `brand_id` (required int), `status` (enum), `customer_tier` (enum). Malformed JSON returns `invalid_json` with line/column/char; passing an object instead of a string, unsupported keys, and wrong-typed values return recoverable one-at-a-time API-style errors.
- **M4 nested write payload**: the `brand_risk_summary.json` file deliverable is converted to a write API. `file_alert(payload)` takes a Notion-style nested body (`parent.type="alert_queue"` + `parent.queue_id="reputation-alerts"`, `properties.Brand.reference.brand_id`, `properties.Severity.number`, optional `Note` rich_text) validated layer by layer, one error per call (`body.parent.queue_id should be a non-empty string, instead was 'undefined'.`). Business checks (queue exists, brand exists) return 404s. Success is an upsert into the `reputation_alerts` table and a deep echo (`{"object": "alert", ...}`) sharing no keys with errors. Step criterion 6 (`brand_risk_summary`, 10 pts) became `alert_register_db` (same 10 pts): the filed brand set must equal the expected alert set with severities within the same ±1.0 tolerance used for the CSV.

## Harness Report (Re-verification run)

- v3 reward: **1.0** (100/100) — first solver attempt, no fixes required
- Eval criteria count: 7 (`alert_queue_format` 10 pts, `correct_brands` 20 pts, `correct_severity_scores` 20 pts, `correct_ranking` 15 pts, `correct_signal_values` 15 pts, `alert_register_db` 10 pts, `action_string` 10 pts)

**Section 1 — Structural integrity:** passed. Top-level contains exactly `README.md` + `v0/`–`v3/`; each version directory contains exactly `data.py`, `env.py`, `prompt.md`; `diff v0/env.py vN/env.py` and `diff v0/prompt.md vN/prompt.md` return no output for N=1,2,3; `data.py` differs across versions only in the `SCALE` block (lines 15–16: `rows_per_table` 50/100/200/400, `num_workspace_files` 8/16/24/32). No stale databases, workspace directories, or bytecode caches found.

**Section 2 — Solvability at v3 scale:** `python data.py --db_path data.db --workspace workspace` ran without errors, producing a 400-row brands table, 8400-row social_media_metrics table, 1365-row news_headlines table, 1064-row support_tickets table, and 697-row executive_communications table, plus 32 workspace files. A black-box solver was written consulting only `v3/prompt.md` and `env.get_assistant_tools()`, reading runtime artifacts (`data.db`, `workspace/`) directly. The solver computed all four signals (social z-score, headline risk, ticket negativity, exec risk flag), combined them per the `alert_methodology.md` spec, wrote `alert_queue.csv`, filed all 192 alerts via `file_alert()`, and emitted the required final-response text. `env.step()` returned reward 1.0 on the first attempt.

**Section 3 — Env quality:** all criteria confirmed. Coverage: each of the 7 step criteria maps to an explicit prompt requirement. Completeness: all deliverables (CSV, platform filing, action string) are covered. No hard-coded row or file counts; `_compute_ground_truth` queries live DB and reads workspace files dynamically. Criteria weights are byte-identical across v0–v3.

**Section 4 — prompt.md quality:** passed. Opens with prose (no title or heading). No bold headers. Column list woven into a single sentence. No tool names or raw workspace filenames exposed (methodology documents referenced generically as "the methodology and configuration documents stored alongside the data"). Scale-invariant wording throughout ("every brand under monitoring", "any brand whose final severity score meets or exceeds"). Deliverable name (`alert_queue.csv`) and all column names specified exactly. Final-response format specified verbatim.

**Issues found and fixed:** none. Task was already in correct state from previous fix (ticket-notes block parser, documented in the Harness Report above).

**Cleanup:** removed `v3/data.db`, `v3/workspace/`, and `v3/__pycache__/` after verification; v0–v2 were already clean.

---

Per-tool surface map (no M2 — success returns stay native dicts):

| tool | params | success shape | error shape |
|---|---|---|---|
| list_brands | page, page_size | dict + total/has_more pagination | `_error` dict |
| get_brand_details | brand_id | flat dict | `_error` dict (404) |
| get_social_media_metrics | brand_id | dict with metrics list | `_error` dict (404) |
| search_headlines | **filter (JSON string)**, page, page_size | dict + total/has_more | `_error` dict |
| get_support_tickets | **filter (JSON string)**, page, page_size | dict + total/has_more | `_error` dict |
| get_ticket_content | ticket_id | flat dict | `_error` dict (404) |
| get_executive_comms | brand_id, page, page_size | dict + total/has_more | `_error` dict |
| get_comm_content | comm_id | flat dict | `_error` dict (404) |
| file_alert (new, M4) | payload (nested object) | deep echo `{"object": "alert", ...}` | `_error` dict |

Error contract: tools never raise; every failure returns `{"status", "object": "error", "code", "message", "request_id"}` — no keys shared with any success shape. Not-found → `404 object_not_found`; bad input → `400 validation_error` / `400 invalid_json` / `400 invalid_request`.

Completeness audit (step() criterion -> info source):
| criterion | source |
|---|---|
| alert_queue_format | prompt para 3 (verbatim contract) |
| correct_brands | alert_methodology.md (Alerting) + priority_matrix.json alert_threshold |
| correct_severity_scores | alert_methodology.md (four signals + combining) + priority_matrix.json + workspace tier/baseline/notes/watchlist files |
| correct_ranking | prompt para 3 (sort keys, tie-breaker — verbatim) + alert_methodology.md (Alerting) |
| correct_signal_values | alert_methodology.md (per-signal reported-value definitions) + prompt para 3 (rounding precision) |
| alert_register_db | prompt para 4 (filing requirement) |
| action_string | prompt para 5 (verbatim final-response format) |

Verification: `verify()` reward 1.0 at v0 (365 tool calls) and v3 (3034 tool calls). Negative-path smoke tests confirmed: malformed M1 JSON (`invalid_json` with position), dict-for-string, unsupported/wrong-typed filter keys, all M4 layers one at a time (body → parent → parent.type → queue_id → properties → Brand → reference → brand_id → Severity → number), 404s for nonexistent brand/ticket/comm/queue. `env.py`/`prompt.md` byte-identical across v0–v3; per-version `data.py` differs only in `SCALE`.
