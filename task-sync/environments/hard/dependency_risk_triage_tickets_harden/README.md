## Task Topic

Triage open-source dependency risks by scanning dependabot alerts, checking production deployment manifests, pulling exploit maturity scores from threat intelligence, and looking up service ownership to assign prioritised remediation tickets with SLA deadlines.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Scaling follows the fixed ratios: rows grow as 1×/2×/4×/8× of the v0 base, and workspace files grow as base/base+N/base+2N/base+3N where N = base (8).

### Structural dimensions

- **Information Scattering**: Dependabot alerts and threat-intelligence data are only accessible through tool calls, while production deployment manifests, SLA policies, priority-scoring weights, known exceptions, and the remediation playbook live exclusively in workspace files. Solving the task requires cross-referencing both sources.
- **Conditional Constraints**: Multiple filtering rules gate ticket creation — packages in the known-exceptions list are excluded, alert–service pairs with existing in-progress or completed remediation history are skipped, and only deployments running a version strictly less than the patched version qualify.
- **Multi-Hop Reasoning**: The dependency chain spans at least four hops: list open alerts → get alert detail (CVE, patched version) → read deployment manifests (match package & compare versions) → query threat intel (exploit maturity) → look up service owner (tier) → read config files (compute priority & SLA).
- **Deliverable Constraints**: The output CSV has a fixed 13-column schema, a prescribed sort order with two-level tie-breaking, and sequentially assigned ticket IDs; the response summary must state exact counts per SLA tier.

## Harness Report

- v3 reward: 1.0 (perfect score, 110/110).
- Eval criteria: 8 (`file_structure`, `ticket_coverage`, `no_false_positives`, `priority_scores`, `sla_assignment`, `sort_order`, `response_summary`, `db_tickets_recorded`).
- v3 ticket totals: 42 tickets — P0-Critical: 0, P1-High: 7, P2-Medium: 13, P3-Low: 22.
- Section 1 structural integrity: passed. Top-level holds only `README.md` + `v0..v3/`. Each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (rows 30/60/120/240, files 8/16/24/32).
- Section 2 solvability: solver written from `v3/prompt.md` + `get_assistant_tools()` only; no escalation to `env.py` was needed. `env.step` returned reward 1.0 on first run (42 tickets filed).
- Section 3 env quality — one issue found and fixed: the `file_structure` check used `all(c in reader.fieldnames ...)` (membership only) instead of `list(reader.fieldnames) == required_cols` (exact order). `prompt.md` explicitly says "exactly these columns in this order", so `step` must enforce column order. Fixed in `v0/env.py` and propagated to `v1..v3`. Reward re-confirmed 1.0 after fix.
- Section 4 prompt quality: passed. No headings, no bold section labels, no bulleted deliverable lists, no tool names or source filenames, no absolute counts, column names explicit, wording scale-invariant throughout.
- Cleanup: removed runtime `data.db`, `workspace/`, and `__pycache__` from v3; solver script removed from task root.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/dependency_risk_triage_tickets`. Ground truth (`_compute_ground_truth`) and the original 7 scoring criteria are unchanged; per the M4 no-write-tool conversion rule, `step()` gains one DB-state criterion (`db_tickets_recorded`, 10 pts, max_score now 110 with reward normalized by max) and `prompt.md` gains one recording sentence.

- **M1 JSON-string parameter**: `list_open_alerts` takes a single `filter` parameter that must be a JSON-encoded string (`'{"severity": "high", "package_name": "lodash"}'`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrong-typed values returns recoverable API-style errors. `page`/`page_size` are leniently coerced and validated.
- **M4 nested write payload**: new write tool `create_triage_ticket(payload)` taking a Notion-style nested body (`parent.type="team_queue"` + `parent.team_name`, `properties.Exposure.reference.{alert_id,service_name}`, optional `Note` rich_text). Validation is layered — one error at a time, messages like `body.parent.team_name should be a non-empty string, instead was 'undefined'.` Business checks (alert exists/open, service exists, team queue exists, duplicate pair) follow structural validation. It writes to a new `triage_tickets` table (created lazily); success responses (`{"object": "triage_ticket", ...}`) share no keys with error responses.

Per-tool return-shape map (no M2 assigned — success shapes stay native dicts):

| tool | success shape | error shape |
|---|---|---|
| list_open_alerts | native dict `{alerts, page, page_size, total_alerts, total_pages}` | `_error` dict |
| get_alert_detail | native dict `{"alert": {...}}` (wrapped so success shares no keys with errors — the alert row itself has a `status` column) | `_error` dict |
| query_threat_intel | native flat dict | `_error` dict |
| get_service_owner | native flat dict | `_error` dict |
| get_remediation_history | native dict `{alert_id, history}` | `_error` dict |
| create_triage_ticket | deep echo `{object, id, parent, properties, created}` | `_error` dict |

Error contract: tools never raise; every failure returns `{"status", "object": "error", "code", "message", "request_id"}` — no key overlaps with any success shape. Not-found → 404 `object_not_found` ("Could not find <entity> with ID: <id>."); bad input → 400 `validation_error` / `invalid_json` / `invalid_request`.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 6 route-narrating paragraphs to 5: scenario/goal (manifests mentioned as data, not as a navigation step), a pointer to the remediation playbook + policy/configuration documents as the governing spec, the ticket-recording requirement (M4), and the verbatim deliverable contract + final-response paragraphs (unchanged word for word). Deleted route narration: "Start by collecting every open alert...", per-tool hand-holding ("retrieve its complete details", "enrich each by querying for the CVE", "look up service ownership"), and per-file navigation. Deleted business-rule restatements verified discoverable: version comparison + semver (playbook "Version Comparison"), exceptions exclusion (playbook "Exception Handling" + exceptions-file header), duplicate prevention incl. in_progress/completed statuses (playbook "Duplicate Prevention"), priority formula (priority_config.yaml `formula` key + new playbook section).

`data.py` changes (additive only, fixed non-scaling policy doc): `remediation_playbook.md` gained two sections — "Prioritisation and SLA Assignment" (priority = product of the three configured weights; exploit maturity from the threat-intel feed; team/tier/on-call from the service-ownership registry; SLA = first tier whose min threshold the score meets or exceeds, scanning from the highest threshold downward — this SLA scanning rule was previously prompt-only) and "Ticket Filing" (one ticket per qualifying exposure, filed against the owning team's queue). `SCALE` blocks preserved per version; per-version `data.py` files differ only in `SCALE`.

Completeness audit (step() criterion -> info source):

| criterion | source |
|---|---|
| file_structure | prompt (verbatim deliverable contract: filename + 13 columns in order) |
| ticket_coverage | prompt ("full triage of every currently open dependency alert", "every qualifying alert-and-service exposure becomes exactly one remediation ticket") + playbook Version Comparison |
| no_false_positives | playbook Version Comparison / Duplicate Prevention / Exception Handling + known_exceptions.txt |
| priority_scores | priority_config.yaml (weights + formula) + playbook Prioritisation section (which value feeds each weight) |
| sla_assignment | sla_policy.yaml (tiers) + playbook Prioritisation and SLA Assignment (scan rule) |
| sort_order | prompt (verbatim contract: sort keys, tie-breakers, TKT-NNNN assignment after sorting) |
| response_summary | prompt (verbatim final-response paragraph) |
| db_tickets_recorded | prompt ("record each ticket in the ticketing system, filed against the queue of the team that owns the affected service") + playbook Ticket Filing |

### Verification

- v3: `verify()` reward 1.0 (110/110), 287 tool calls. v0: reward 1.0, 42 tool calls (≥ 15 floor).
- Negative-path smoke tests all pass: malformed M1 filter JSON → `invalid_json` with line/column/char; dict-instead-of-string filter → serialize hint; unsupported filter key and wrong-typed severity → `validation_error`; JSON-array filter → `invalid_request`; M4 layered errors surface one at a time (body → parent → parent.type → team_name → properties → Exposure → Exposure.type → reference → alert_id integer → service_name → Note shape); nonexistent alert/CVE/service → 404 `object_not_found`; duplicate pair filing → 400 `validation_error`.
- `diff v0/env.py v{1,2,3}/env.py` empty; `prompt.md` identical across versions; no runtime artifacts left.
