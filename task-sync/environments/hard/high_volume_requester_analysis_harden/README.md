## Task Topic

Identify high-volume requesters and potential commercial data mining. Cross-reference requestor contact details, request metadata, document production logs, and fee waiver approvals to flag patterns of systematic extraction, generating a report for legal review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Critical fields are split across database tools and workspace files. Requestor primary emails live in the database, while alternate emails and cross-agency request counts are only available in workspace CSV profile batches. Document sensitivity ratings are only in workspace JSON production manifests. Scoring thresholds, commercial domain lists, department sensitivity levels, and category risk scores all reside in separate workspace configuration files of different formats.

- **Multi-Hop Reasoning**: The dependency chain is at least length 4: (1) read thresholds.yaml to learn the volume threshold → (2) paginate through all requests via tool calls to identify high-volume requestors → (3) for each high-volume requestor, retrieve fee waiver records and production summaries via tools, and cross-reference alternate emails from workspace profile CSVs against the commercial domain list from a workspace JSON file → (4) combine all six risk-score components using weights from the config to compute the final composite score and determine flag status.

- **Conditional Constraints**: Flagging depends on multi-table business rules: a requestor must first meet the volume threshold, then their composite risk score (computed from six components spanning database and workspace data) must meet or exceed the risk-score threshold. Additional flag reasons are conditional on sub-thresholds (fee waiver ratio > 50%, department spread >= cap, cross-agency count >= cap, commercial keyword presence in approved waiver reasons).

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 6 (`report_file_format`, `flagged_requestor_ids`, `risk_scores_accuracy`, `report_sort_order`, `commercial_waiver_language`, `action_summary`).
- Source-access: clean. Solver was authored using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` was required.
- Structural integrity: all four versions contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (rows_per_table: 80/160/320/640; num_workspace_files: 8/16/24/32).
- Issues found: none. No fixes were applied.
- Blockers: none.
- Re-verified 2026-07-03: structural checks, solvability at v3 (87 flagged requestors, reward=1.0, all 6 criteria passed), env/prompt quality, and artifact cleanup all passed without changes.

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/high_volume_requester_analysis`; `step()` and `_compute_ground_truth()` are byte-identical to SOURCE (scoring/ground truth unchanged).

- **M5 unbounded bulk export**: new tool `export_request_activity()` returns the entire joined request-activity dataset (one record per request with requestor name/email/organization/type + date_filed/status/category_id/department_id; `subject` deliberately excluded for size calibration) as ONE JSON string with no pagination — measured ~16.8k tokens at v0 (survivable but expensive) and ~135k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and filtered before printing). It is genuinely sufficient for the core filtering step (grouping requests by requestor, volume screening, department spread). All paginated / per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (per-tool map):
  | tool | success shape |
  |---|---|
  | `search_requestors` | native dict |
  | `search_requests` | native dict |
  | `get_departments` | native list |
  | `get_categories` | JSON-encoded string |
  | `export_request_activity` | JSON-encoded string (M5) |
  | `get_requestor_details` | plain `key: value` text |
  | `get_request_details` | MCP-style envelope |
  | `get_fee_waivers_by_requestor` | MCP-style envelope |
  | `get_requestor_production_summary` | Python-repr string (needs `ast.literal_eval`) |
- **Error contract**: tools never raise. Not-found → `{"status": 404, "object": "error", "code": "object_not_found", "message": "Could not find <entity> with ID: <id>.", "request_id": ...}`; wrong-typed params → `{"status": 400, "object": "error", "code": "validation_error", "message": "body.<param> should be an integer, instead was '<value>'.", ...}`. Error and success responses share no keys, so consumers must branch on shape.
- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 formula-narrating paragraphs to 4: scenario/goal, a pointer to the policy/configuration documents as the authoritative spec, the verbatim deliverable contract (filename, exact column list/order, sort key, four-decimal risk_score, field definitions), and the final-response requirement. `data.py` change (additive only, all SCALE blocks preserved per version): new fixed workspace document `risk_scoring_methodology.md` containing the high-volume screening rule, the six risk-component formulas (incl. missing-profile defaults), the composite score weighting/rounding and flag threshold, and the five flag-reason labels with their conditions plus alphabetical-sort/"; "-join formatting. The commercially-oriented waiver phrases and the >50% waiver-ratio rule were already in `fee_waiver_policy.md`.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| report_file_format | prompt (verbatim deliverable contract) |
| flagged_requestor_ids | risk_scoring_methodology.md (screening + components + flag threshold) + thresholds.yaml (numbers) + requestor_profile_batch_*.csv + production_manifest_batch_*.json |
| risk_scores_accuracy | risk_scoring_methodology.md (formulas, 4-dp rounding) + thresholds.yaml (weights/caps) |
| report_sort_order | prompt (verbatim deliverable contract) |
| commercial_waiver_language | fee_waiver_policy.md (phrases) + risk_scoring_methodology.md (label + case-insensitive match) |
| action_summary | prompt (final-response requirement) |

Verification: `verify()` == 1.0 at v0 (69 tool calls; ≥15 floor met) and v3 (540 tool calls); it consumes the bulk export once, in memory, and parses key:value text, MCP envelopes, and repr strings. Negative-path smoke tests passed for all 404/400 shapes (nonexistent IDs on text/envelope/repr tools; string, None, bool, and dict passed to integer params — all return recoverable `_error` responses, never raise). `env.py` and `prompt.md` byte-identical across v0–v3; per-version `data.py` differs only in `SCALE`. validate_envs: 4/4 passed.
