## Task Topic

Analyze audit file access logs, staff time entry records, client document request histories, and engagement team assignments to identify potential scope creep or unauthorized work, producing a flagged activities report for partner review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 12                  |
| v1      | 120           | 24                  |
| v2      | 240           | 36                  |
| v3      | 480           | 48                  |

Rows scale at 2×/4×/8× the v0 base. Workspace files scale as base + N/+2N/+3N where N = 12 (the v0 base). Each version also generates auxiliary tables at multiples of `rows_per_table` (assignments ×2, time entries ×5, file access logs ×4, document requests ×2), plus 4 fixed policy/config files that do not scale.

**Structural dimensions used:**

- **Information Scattering**: Budget hours and authorized scope areas live exclusively in workspace YAML files, while time entries, assignments, file access logs, and document requests are only available through paginated tool queries. Certification requirements are in a workspace CSV, staff certification levels only via tools. Solving the task requires both sources.
- **Conditional Constraints**: Flag identification depends on multi-table business rules — e.g., budget overrun severity is determined by comparing aggregated hours (from tool queries) against budget thresholds (from workspace YAML + policy YAML); certification violations require cross-referencing staff cert levels (tool) against engagement-type minimums (workspace CSV).
- **Multi-Hop Reasoning**: Certification violation detection follows a 3+ hop chain: read certification_requirements.csv → query engagements to get types → query active assignments per engagement → query staff details for cert levels → compare and flag.
- **Deliverable Constraints**: Output CSV has a fixed 8-column schema with specific sort order (flag_type alphabetical, then record ID ascending) and sequential flag_id numbering; summary.txt must contain exact counts by type and severity.

## Harness Report

- **v3 reward**: 1.0 (100/100), achieved on first solver attempt.
- **Eval criteria**: 6 (`csv_format` 15, `flag_count` 10, `flag_type_distribution` 15, `per_flag_accuracy` 25, `severity_accuracy` 15, `summary_file` 20).
- **v3 flag counts (verified run)**: 1149 total — UNAUTHORIZED_TIME 409, UNAUTHORIZED_ACCESS 283, CERTIFICATION_VIOLATION 314, OUT_OF_SCOPE_REQUEST 143, BUDGET_OVERRUN 0; severity HIGH 1006, MEDIUM 143.
- **Solver source-access**: Clean black-box. Solver was written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` plus runtime artifacts (`data.db`, `workspace/`). `env.py`, `data.py`, and `README.md` were not opened during Section 2; no step-6 escalation was needed.
- **Section 1 structural integrity**: Pass. `diff` confirmed `env.py`/`prompt.md` byte-identical across v0..v3; `data.py` differs only in the SCALE block. Row scaling 60/120/240/480 (1×/2×/4×/8×) and workspace file scaling 12/24/36/48 (base + 0/N/2N/3N) match the generate.md ratios.
- **Section 3 env quality**: Pass. All 6 criteria correspond to prompt requirements; ground truth recomputed live from current DB/workspace (no hard-coded counts); per-flag matching uses (flag_type, engagement_id, staff_id) tuples (robust, not over-strict); no over-normalization or regex; cert hierarchy and overrun thresholds read from workspace files at eval time.
- **Section 4 prompt quality**: Pass. No title/headings, no bold section headers, no bulleted deliverables, scale-invariant wording, output filenames explicit, no leakage of source filenames or tool names.
- **Issues found and fixed**: None. The environment is internally consistent and ready for evaluation.
- **Blockers**: None.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/audit_scope_compliance_check`; `_compute_ground_truth()` and `step()` scoring are byte-identical to SOURCE. Only the tool surface, `prompt.md` (M0), and an additive `data.py` policy document changed.

- **M2 mixed return shapes** (per-tool map):
  | tool | success shape | error shape |
  |---|---|---|
  | `list_engagements` | native dict — deep-nested list object | `_error` dict |
  | `query_time_entries` | native dict — deep-nested list object | `_error` dict |
  | `list_staff` | JSON-encoded string of a nested list object | `json.dumps(_error(...))` |
  | `query_assignments` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) | `_error` dict |
  | `query_document_requests` | MCP envelope | `_error` dict |
  | `query_file_access_logs` | Python-repr string (single quotes; needs `ast.literal_eval`) | `json.dumps(_error(...))` |
  | `get_staff_details` | plain `key: value` text (single flat record) | `_error` dict |

  2/7 tools stay native so the model cannot assume a uniform encoding. Descriptions state what each tool returns, never how it is encoded.
- **M3 deep nesting**: list/detail records are Notion-style, 3–4 levels deep: display text at `properties.<Field>.title[0].plain_text` (NOT `.title[0].text.plain_text`), categorical values at `properties.<Field>.select.name`, foreign keys at `properties.<Field>.relation[0].id`, dates at `properties.<Field>.date.start`, numbers at `properties.<Field>.number`, booleans at `properties.Active.checkbox`. List tools use cursor pagination (`has_more` / `next_cursor`) instead of `total` / `total_pages`.
- **Error contract**: tools never raise. Bad input → `_error(400, "validation_error", "body.<param> should be a <type>, instead was '<repr>'.")`; unknown ID → `_error(404, "object_not_found", "Could not find staff member with ID: <id>.")`. Error dicts are `{"status", "object": "error", "code", "message", "request_id"}` and share no keys with any success shape except the `object` discriminator on native list returns (`"list"` vs `"error"`, per the M3 template).
- **M0 de-proceduralized prompt**: rewritten from 6 route-narrating paragraphs to 4: scenario/goal, a pointer to the policy/configuration documents as the authoritative specification, and the two verbatim deliverable-contract paragraphs (`flagged_activities.csv` columns/sorting/flag_id rules, and `summary.txt` + final-response requirements). Deleted: tool hand-holding, sequencing scaffolds, and business-rule restatements that are discoverable in `flagging_policy.yaml` / `review_guidelines.txt` / scope YAMLs / `certification_requirements.csv`. Prompt-only granularity and deduplication conventions (one flag per time entry / access event / document request; budget overrun evaluated once per engagement; certification violations over active assignments only, deduplicated per engagement-staff pair) were moved into a new fixed workspace document `audit_methodology.md` written by `data.py` (additive change only; per-version `data.py` files differ from each other only in the SCALE block).

  Completeness audit (step() criterion → info source):
  | criterion | source |
  |---|---|
  | `csv_format` (15) | prompt ¶3 (verbatim contract: filename + exact column list/order) |
  | `flag_count` (10) | flagging_policy.yaml (trigger definitions) + review_guidelines.txt (active-only authorization, overrun formula, scope comparison, cert hierarchy) + audit_methodology.md (granularity/dedup) + scope batch YAMLs (budgets, authorized areas) + certification_requirements.csv |
  | `flag_type_distribution` (15) | same as `flag_count`; the five flag_type labels are in prompt ¶3 |
  | `per_flag_accuracy` (25) | same rule sources; empty staff fields for budget overruns in prompt ¶3 |
  | `severity_accuracy` (15) | flagging_policy.yaml (`default_severity` per type + `severity_rules` overrun thresholds and note) |
  | `summary_file` (20) | prompt ¶4 (verbatim contract: required counts by type and severity) |
- **verify()**: ports the SOURCE solver 1:1, changing only the consumption layer (unwrap envelopes, `json.loads` JSON strings, `ast.literal_eval` repr strings, parse `key: value` text, walk nested properties, follow cursor pagination). Results after hardening: **v0 reward 1.0 (100/100, 23 tool calls)**, **v3 reward 1.0 (100/100, 158 tool calls)**. Negative-path smoke tests pass: 404 on unknown staff ID, per-parameter 400 validation errors (one at a time), JSON-string error form on string-returning tools, no tool raises on malformed input, repr returns are not JSON-parseable.
