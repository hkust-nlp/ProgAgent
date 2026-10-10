## Task Topic

Validate influencer post deliverables by analysing post timing, contracted engagement targets, audience location data, and historical bot-detection scores to flag non-compliant content and produce a payment adjustment file with supporting evidence.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8× of the v0 base (50). Workspace files follow base/base+N/base+2N/base+3N where N = 8 (the v0 base).

**Structural dimensions used:**

- **Conditional Constraints**: Compliance checks depend on multiple thresholds (bot score limits, engagement rate minimums, audience region percentages, posting hour windows) drawn from both contract records (via tools) and a YAML configuration file (in workspace). Penalty calculation follows layered rules from a payment terms document.
- **Information Scattering**: Audience location data lives exclusively in workspace JSON files, bot detection scores are only accessible through tool calls, contract thresholds come from tool queries, and penalty/threshold parameters reside in workspace configuration files. No single source is sufficient.
- **Multi-Hop Reasoning**: Contract → list posts (tool) → per-post bot report (tool) + audience geo lookup (file) + region mapping (config file) → violation assessment → penalty aggregation using payment terms (file) → adjusted payment computation.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (`flagged_posts_structure` 10 pts, `flagged_posts_accuracy` 25 pts, `payment_adjustments_recorded` 10 pts, `penalty_pct_accuracy` 20 pts, `adjusted_payment_accuracy` 20 pts, `action_summary` 15 pts)
- v3 solver outputs: 646 violation rows, 139 contracts penalized (of 139 pending), total deductions $876,929.69
- Source-access rule: clean — solver completed using only `v3/prompt.md` and `Task_Env.get_assistant_tools()` plus runtime DB/workspace inspection; no step-6 escalation needed.
- Issues found and fixed:
  - Section 1: structural integrity confirmed — top-level directory has exactly `README.md` + `v0/`–`v3/`; each `v_n/` has exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across all versions; only the `SCALE` block differs in `data.py` (rows_per_table: 50/100/200/400; num_workspace_files: 8/16/24/32). No artifacts present.
  - Section 2: `data.py` ran cleanly at v3; solver achieved reward 1.0 on first attempt.
  - Section 3: all step() criteria map 1-to-1 to prompt requirements; ground truth computed entirely from `data.db` + workspace (no hard-coded values); note that prompt specifies flagged_posts.csv sort order but step() uses F1 set comparison (intentional design — content accuracy is what matters for scoring).
  - Section 4: prompt.md passes all quality checks (no heading, no bold headers, no bulleted deliverable lists, scale-invariant phrasing, no internal filenames/tool names exposed, exact output column names specified).
- Fixes applied: none required.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/influencer_deliverable_payment_adjustment`. Ground truth (`_compute_ground_truth`) and criterion weights are unchanged; the only `step()` change is the sanctioned M4 conversion of the `payment_adjustments.csv` deliverable into a DB-state check (criteria 3–5 now read the `payment_adjustments` ledger table written by the new write tool, with identical comparisons and weights: 10/20/20).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 rule/route-narrating paragraphs to 5: scenario + goal, policy-document pointer, the verbatim `flagged_posts.csv` deliverable contract, the adjustment-recording requirement (M4 rewording of the old CSV paragraph), and the verbatim final-summary contract. Formulas/penalty rules were already fully specified in `payment_terms.md` + `compliance_rules.yaml`; the prompt-only boundary conventions (inclusive date window and hour window) and the audience/bot data-location pointers were moved into a new fixed workspace document `audit_methodology.md` (the only `data.py` change — additive, non-scaling, identical across versions; each version's `SCALE` block preserved).
- **M1 JSON-string parameter**: `list_contracts` takes a single `filter` parameter that must be a JSON-encoded string (`'{"status": "pending_review"}'`; supported properties: `status`, `influencer_id`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values returns recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_payment_adjustment(payload)` tool with a Notion-style nested body (`parent.type="adjustment_ledger"` + `parent.contract_id` string, `properties.Penalty` / `properties.AdjustedPayment` number properties, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.contract_id should be a non-empty string, instead was 'undefined'.` — followed by business checks (404 unknown contract, 400 non-pending contract). It writes `INSERT OR REPLACE` into a `payment_adjustments` table (idempotent per contract). Success responses (`{"object": "adjustment", ..., "created": true}`) share no keys with error responses.

Per-tool return-shape map (no M2 assigned — all success returns are native dicts):

| tool | success shape | error shape |
|---|---|---|
| list_contracts | `{contracts, page, page_size, total, total_pages}` | `_error` dict |
| get_contract_details | `{contract: {...}}` (wrapped: contract rows contain a `status` column, which would collide with the error shape) | `_error` dict |
| list_contract_posts | `{contract_id, posts, count}` (404 for unknown contract) | `_error` dict |
| get_bot_report | `{post_id, scans, count}` (404 for unknown post) | `_error` dict |
| get_influencer | `{influencer: {...}}` | `_error` dict |
| create_payment_adjustment | `{object: "adjustment", id, parent, properties, created}` deep echo | `_error` dict |

Error contract: tools never raise; every failure returns `{status, object: "error", code, message, request_id}` with codes `invalid_json` / `invalid_request` / `validation_error` (400) and `object_not_found` (404).

Completeness audit (step() criterion → info source):

| criterion | source |
|---|---|
| flagged_posts_structure (10) | prompt para 3 (verbatim contract: filename, columns, labels, sort) |
| flagged_posts_accuracy (25) | prompt para 1 (scope: pending review, four dimensions + post count) + `audit_methodology.md` (scope, per-post/per-type flagging, inclusive date/hour boundaries, audience-data location) + `payment_terms.md` (engagement formula, bot scan selection, audience-location comparison, shortfall definition) + `compliance_rules.yaml` (thresholds, region-country mapping) |
| payment_adjustments_recorded (10) | prompt para 4 ("record ... for every contract that is pending review, regardless of whether it received a penalty") + `audit_methodology.md` (Recording results) |
| penalty_pct_accuracy (20) | `payment_terms.md` (per-type once-per-contract penalties, per-missing-post accumulation, cap) + `compliance_rules.yaml` (penalty percentages, max cap) |
| adjusted_payment_accuracy (20) | `payment_terms.md` (adjusted payment formula, 2-dp rounding) + prompt para 4 (2-dp) |
| action_summary (15) | prompt para 5 (verbatim three-line format) |

Verification: `verify()` reward **1.0 at v3** (826 tool calls) and **1.0 at v0** (100 tool calls; ≥ 15 floor met). Negative-path smoke tests confirmed: M1 malformed JSON → `invalid_json` with `line 1 column 12 (char 11)`; dict-instead-of-string → serialize hint; M4 layered messages surface one at a time in order (body → parent → parent.type → parent.contract_id → properties → Penalty → Penalty.type → Penalty.number → AdjustedPayment → business 404/400); unknown-ID lookups → 404 `object_not_found` dicts. `env.py`/`prompt.md` byte-identical across v0–v3; `data.py` differs from SOURCE only by the additive `audit_methodology.md` block and across versions only in `SCALE`; no runtime artifacts left.
