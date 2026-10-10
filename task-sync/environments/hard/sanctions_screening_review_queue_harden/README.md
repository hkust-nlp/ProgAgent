## Task Topic

Screen new customer registrations against sanctions lists by checking identity attributes against OFAC, EU, and UN consolidated records, tracing cross-border payment intermediaries, and reviewing ultimate-beneficial-ownership structures to flag positive matches for compliance review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 40            | 8                   |
| v1      | 80            | 16                  |
| v2      | 160           | 24                  |
| v3      | 320           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8× progression; workspace files follow base/base+N/base+2N/base+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Customer aliases exist only in workspace JSON files (not in the database). PEP status of beneficial owners is recorded exclusively in workspace YAML declaration files. Payment purposes and beneficiary details appear only in workspace CSV transaction logs. Screening thresholds and scoring weights live in a workspace configuration file. The agent must combine tool-returned database records with file-sourced attributes to complete the screening.

- **Multi-Hop Reasoning**: The task requires dependency chains of length 3 or more. For example: read UBO declaration YAML to find a PEP beneficial owner → retrieve that owner's nationality from the UBO database record via tool → look up the nationality's country risk tier from the workspace CSV → determine whether the PEP-in-high-risk-country flag applies. Similarly: read customer alias from workspace JSON → search alias against sanctions lists via tool → record the matched sanctions entry ID and raise the alias_match flag.

- **Conditional Constraints**: Flagging decisions depend on multiple configurable thresholds read from workspace files: name similarity threshold, UBO ownership percentage floor for screening eligibility, country risk tier cutoff, risk score weight per flag type, and priority classification breakpoints. All must be applied exactly as configured.

- **Deliverable Constraints**: The output CSV requires exact column names, semicolon-separated flag reasons in alphabetical order, semicolon-separated sanctions IDs in ascending order, specific sort order (risk score descending, customer ID ascending for ties), and boolean formatting for the flagged column.

## Harness Report

- v3 reward: **1.0** (110/110)
- Eval criteria count: 8 — file_format (10 pts), customer_completeness (15 pts), flagged_accuracy (25 pts), risk_score_accuracy (15 pts), flag_reasons (15 pts), sanctions_ids (10 pts), review_priority (10 pts), review_cases_recorded (10 pts)
- Section 1 structural integrity: passed — `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` dict (rows_per_table and num_workspace_files); no stale artifacts in any version directory.
- Section 2 solvability: solver achieved reward=1.0 at v3 scale (320 customers, 799 intermediaries, 440 UBO records) using only `prompt.md` + `Task_Env.get_assistant_tools()` + runtime artifacts (`data.db`, `workspace/`). No edits to `env.py` or `prompt.md` were required. Two solver bugs were found and fixed during development (wrong key for pagination response — `"customers"` not `"results"` — and tool return shapes needing dict-key extraction rather than direct iteration); both were solver-side issues, not env bugs.
- Section 3 quality: all 8 step() criteria correspond to explicit prompt.md requirements; ground truth is derived dynamically from `data.db` and `workspace/` (no hard-coded counts); criteria weights are the same across v0..v3 (enforced by the byte-for-byte env.py invariant). Noted: sort order (risk_score desc, customer_id asc) and the final-response summary text are required by prompt.md but not separately graded — the CSV content criteria cover the essential correctness, making the sort and summary checkable by inspection.
- Section 4 prompt.md quality: prose-only (no bold headers, no bullet lists), scale-invariant wording ("all customer registrations currently pending review", "every screened customer"), no tool names or internal file paths leaked, exact column names and output filename specified.
- Issues fixed: none — no changes to `env.py`, `prompt.md`, or `data.py` were needed.

## Hardening (M0 + M1 + M4)

Source: `environments/standard/sanctions_screening_review_queue`. Data, business logic, ground truth, and the CSV deliverable are unchanged; only the tool surface, the prompt, and `verify()` were re-skinned. `data.py` is byte-identical to SOURCE in all four versions.

### Mutators applied

- **M0 — de-proceduralized prompt.** The SOURCE prompt narrated the full screening route (which lookups to run, in what order, which files hold which rule). The rewritten prompt states only the scenario/goal, a pointer to the workspace policy/configuration documents as the authoritative methodology, the verbatim deliverable contract, and the final-response requirement. All deleted rule sentences were verified discoverable in `workspace/compliance_policy.txt` (§1–§7) and `screening_config.yaml`.
- **M1 — JSON-encoded string parameters.** `search_sanctions` now takes a single required `request` parameter (JSON-encoded string; properties `query` required, `list_source` optional). `list_pending_customers` gains an optional `filter` parameter (JSON-encoded string; properties `customer_type`, `nationality`). Malformed JSON returns `invalid_json` with line/column/char; a dict passed instead of a string returns `invalid_request`; unsupported keys and wrong-typed values return `validation_error`, one error per call.
- **M4 — nested write payload.** New tool `create_review_case(payload)` with `parent` (`{"type": "review_queue", "customer_id": ...}`) + `properties` (required `Priority` select property; optional `RiskScore` number and `Note` rich_text). Validation is layered, one error per call, with Notion-style messages (`body.parent.customer_id should be a non-empty string, instead was 'undefined'.`), then business checks (`404 object_not_found` for unknown customers). Success returns a deep echo (`object: "review_case"`, `created: true`) sharing no keys with errors. The write is `INSERT OR REPLACE` into a new `screening_review_cases` table (created by the tool; `data.py` untouched). Per the M4 no-write-tool exception, the "review case per customer" deliverable was added: `step()` gains one DB-state criterion (`review_cases_recorded`, 10 pts; max score 100 → 110, all other criteria unchanged) and the prompt's deliverable paragraph gains one sentence.

### Per-tool surface map

| Tool | Params | Return shape (success) | Errors |
|---|---|---|---|
| `list_pending_customers` | `page`, `page_size` ints + `filter` JSON-string (M1) | native dict, paginated | `_error` dict |
| `get_customer_details` | plain string | native dict | `_error` dict (404) |
| `search_sanctions` | single `request` JSON-string (M1) | native dict `{query, matches}` | `_error` dict |
| `get_sanctions_entry` | plain string | native dict | `_error` dict (404) |
| `get_payment_intermediaries` | plain string | native dict | `_error` dict |
| `get_ubo_structure` | plain string | native dict | `_error` dict |
| `get_country_risk` | plain string | native dict (unknown country → default tier 2, as SOURCE) | `_error` dict |
| `create_review_case` | nested `payload` object (M4) | deep echo `{object, id, parent, properties, created}` | `_error` dict, layered |

Error contract: tools never raise; every failure returns `{status, object: "error", code, message, request_id}` — no key overlap with any success shape. Codes: `invalid_json`, `invalid_request`, `validation_error`, `object_not_found`.

### M0 completeness audit (step() criterion → information source)

| step() criterion | Where the required information lives |
|---|---|
| `file_format` (10) | Prompt ¶3: file name and exact column list (verbatim from SOURCE) |
| `customer_completeness` (15) | Prompt ¶1 ("all customer registrations currently pending review") + ¶3 ("one row per customer"); policy §1/§7 |
| `flagged_accuracy` (25) | Policy §2–§4 (which checks flag), config weights (score > 0 ⇔ flagged); prompt ¶3 `True`/`False` format |
| `risk_score_accuracy` (15) | Policy §5 (sum of per-flag-type weights, each once) + `screening_config.yaml` `risk_score_weights` |
| `flag_reasons` (15) | Policy §5 lists the six exact flag-type codes; §2–§4 define when each applies; prompt ¶3 alphabetical `;` format |
| `sanctions_ids` (10) | Policy §2 (record matched entry identifiers) + §3/§4; prompt ¶3 ascending `;` format |
| `review_priority` (10) | Policy §6 (CRITICAL/HIGH/MEDIUM/LOW/CLEAR breakpoint rules) + config `priority_thresholds` |
| `review_cases_recorded` (10) | Prompt ¶3 final sentence (file a review case per screened customer with its priority) |

Thresholds (`name_match_threshold`, `ubo_ownership_screening_threshold`, `country_risk_tier_flag_threshold`) live in `screening_config.yaml`, referenced by policy §2–§4. No rule is reachable only from `env.py` source.

### Verification results

- v3: `verify()` reward **1.0** (110/110), 2809 tool calls — envelope-free but fully hardened path (JSON-string requests for every sanctions search, nested payload per review case).
- v0: `verify()` reward **1.0** (110/110), 353 tool calls (≥ 15 floor).
- Negative-path smoke tests passed: malformed M1 JSON → `invalid_json` with line/column/char; dict-for-string → `invalid_request`; missing `query` / unsupported key / bad enum → `validation_error`; M4 layered errors surface one at a time (body → parent → parent.type → parent.customer_id → properties → Priority → Priority.type → select → name → allowed values) then business `404 object_not_found`; nonexistent customer/entry lookups → `404` error dict; non-integer `page` → `validation_error` (no raise).
- `diff v0/env.py v{1,2,3}/env.py` and `diff v0/prompt.md v{1,2,3}/prompt.md` empty; `data.py` byte-identical to SOURCE per version; no runtime artifacts left.
