## Task Topic

Automatically route technical support tickets by parsing error codes from ticket descriptions, matching to product SKU from support portal logs, checking agent certification records, and analyzing current team queue depth to assign to the first available qualified engineer.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 12                  |
| v1      | 100           | 24                  |
| v2      | 200           | 36                  |
| v3      | 400           | 48                  |

Structural dimensions used:

- **Information Scattering**: Error codes are embedded in ticket description text files; the error-code-to-product-SKU mapping lives in portal log CSV files; product category is only available via the product lookup tool; routing rules and shift schedule are in separate JSON config files. No single source contains all the information needed to make a routing decision.
- **Multi-Hop Reasoning**: Ticket file → parse error code → portal log CSV → product SKU → tool: lookup product → category → config: severity-to-cert-level mapping → tool: engineer certifications → tool: queue depth → tool: assign ticket. This is a dependency chain of length 5+.
- **Conditional Constraints**: Assignment eligibility depends on severity-driven certification level requirements, shift-matching, active status, non-expired certifications, and queue capacity limits. Thresholds and rules live in workspace configuration files.

## Harness Report

- v3 solver reward: 1.0 (total_score 100/100).
- Eval criteria: 7 (`assignments_file_format` 10, `all_tickets_covered` 10, `error_codes_correct` 15, `product_mapping_correct` 15, `certification_valid` 20, `optimal_assignment` 20, `db_assignments_recorded` 10).
- Source-access: clean. Solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; `env.py` was opened in Section 3 for prompt-step alignment review only.
- Structural integrity: passed. `diff` confirmed `env.py`/`prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 50/100/200/400, files 12/24/36/48 — matches harness ratios with N=12).
- Prompt-step alignment: every criterion in `step()` maps to a prompt requirement; no hidden criteria; no over-normalization; ground truth derived dynamically from `data.db`/workspace.
- Prompt quality: no title/headings, no bullet lists, no tool names, scale-invariant wording, output filename and column order specified.
- Issues found and fixed: none. No edits to `v0/` or any version were required.
- Blockers: none.

## Hardening (M1 + M4)

Applied on top of `environments/standard/technical_ticket_assignment`; data.py, prompt.md, and step() scoring are unchanged (step criterion 7 still checks DB state).

- **M1 JSON-string parameter**: `list_engineers` takes a single `filter` parameter that must be a JSON-encoded string (`'{"shift": "morning", "is_active": true}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, or unsupported/wrongly-typed filter keys, returns recoverable API-style errors.
- **M4 nested write payload**: `assign_ticket` is replaced by `create_assignment(payload)` taking a Notion-style nested body (`parent.type/engineer_id` + `properties.Ticket.reference.ticket_id`, optional `Note` rich_text). Validation is layered — one error at a time, messages like `body.parent should be defined, instead was 'undefined'.` Success responses (`{"object": "assignment", ...}`) share no keys with error responses.
- verify() passes with reward 1.0 at v0 and v3 scales (271 tool calls at v3).

### M0 — de-proceduralized prompt (added 2026-07-02)

`prompt.md` rewritten from 6 route-narrating paragraphs to 3: scenario (tickets + error codes in ticket files, portal logs as authoritative error->product/severity mapping), a pointer to the escalation policy / routing configuration as the governing spec (with the one load-bearing hint that processing order matters because assignments change queue depths), and the verbatim deliverable contract + final-response requirement. `data.py` changes (additive only): `routing_rules.json` gained an `output_format` block (filename + columns); `escalation_policy.md` gained the certification-validity-vs-reference-date sentence and now points to the output format — the algorithm itself (eligibility, severity->cert map, processing order incl. P5/P1 semantics, tie-breakers, capacity rule) was already fully specified there.

Completeness audit (step() criterion -> info source):
| criterion | source |
|---|---|
| assignments_file_format | prompt (verbatim contract); also routing_rules.json output_format |
| all_tickets_covered | prompt ("route all pending tickets") + escalation_policy.md |
| error_codes_correct | ticket_*.txt files (discoverable) |
| product_mapping_correct | portal_log_*.csv + product lookup tool |
| certification_valid | escalation_policy.md + routing_rules.json severity map + shift_schedule.json reference_date |
| optimal_assignment | escalation_policy.md (order, selection metric, tie-breaker) |
| db_assignments_recorded | prompt ("record each assignment in the ticket system") |
v3 verify (unchanged) re-run after M0: reward 1.0.
