## Task Topic

Audit emergency resource utilization by correlating dispatch radio transcripts, equipment maintenance logs, personnel certification databases, and incident outcome reports to produce a prioritized list of units requiring retraining or re-equipping.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N = 10 (base).

**Structural dimensions used:**

- **Information Scattering**: Scoring thresholds, penalty points, certification requirements, and protocol violation keywords reside in workspace configuration files (YAML, JSON, CSV). Personnel certifications, equipment conditions, dispatch timing, maintenance logs, and incident outcomes are only available through tool calls. Solving the task requires combining both sources.
- **Conditional Constraints**: Whether a unit is flagged depends on multi-table business rules — average response time exceeding a threshold, certification levels falling below role-specific requirements, equipment condition ratings below minimums, maintenance next-due dates preceding the audit date, and incident outcome ratings below thresholds.
- **Multi-Hop Reasoning**: Protocol violation attribution requires reading the policy (keywords) → scanning transcript files (matching keywords to unit names) → aggregating per-unit counts → applying penalty multipliers from the scoring matrix. Equipment maintenance status requires: get unit equipment → get maintenance history per equipment → compare latest next_due_date against audit date.

## Harness Report

- v3 reward: **1.0** (total_score 100 / max_score 100).
- Eval criteria count: **7** (`report_format`, `correct_units`, `retraining_scores`, `reequip_scores`, `correct_sorting`, `correct_actions`, `response_top5`).

**Section 1 — Structural integrity: PASS**
Top-level contains exactly `README.md` and `v0/`..`v3/`. Each version dir contains exactly `data.py`, `env.py`, `prompt.md` (no `data.db`, `workspace/`, `__pycache__`). `env.py` and `prompt.md` are byte-identical across v0..v3 (`diff` returns exit 0 for all pairs). `data.py` differs only in the `SCALE` block (rows_per_table: 50/100/200/400; num_workspace_files: 10/20/30/40).

**Section 2 — Solvability at v3: PASS**
Solver written using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. Initial attempt scored 0.95 (381/393 retraining scores wrong, sort off, response top-5 partially wrong). Root cause: plain substring test `unit_name in line` matched shorter names as substrings of longer ones — 139 such pairs exist (e.g. "E-1" matches "E-10", "E-11", "E-16", "E-101", …). Fix: switch violation attribution to `re.compile(r'\b' + re.escape(name) + r'\b')`. Second run: reward 1.0. No `env.py` inspection needed; no source edits required.

**Section 3 — Env quality: PASS**
Every criterion in `step()` maps to an explicit requirement in `prompt.md`. Ground truth is fully data-driven (no hard-coded counts). Score values are enforced as integers. Sort order (total_priority_score DESC, unit_id ASC) matches the prompt contract exactly. `_compute_ground_truth()` uses word-boundary regex for violation attribution, matching the fix the solver needed. No lines in generated data carry 2+ keywords, so the `break`-after-first-keyword behavior in `step()` is equivalent to counting all keywords.

**Section 4 — prompt.md quality: PASS**
No title or heading at the top. No bold section headers; body flows as natural prose. No numbered/bulleted deliverable lists — column names appear inline in a sentence. All computation logic expressed in natural language. No tool names, source filenames, or `env.py` internals exposed. Output file named explicitly (`priority_report.csv`) with all column names and order stated. Sort key and tie-breaker rule unambiguous. Wording is scale-invariant ("every unit", "every distinct incident", "all of its dispatches").

**Issues found and fixes applied:**
- None. The initial solver bug (substring matching) was a solver defect, not an environment or prompt defect. No edits to `data.py`, `env.py`, or `prompt.md` were needed.

**Blockers:** none.

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/resource_utilization_audit`; `step()` / `_compute_ground_truth()` scoring is unchanged (criteria and weights identical to SOURCE).

- **M5 unbounded bulk export**: new tool `export_dispatch_operations()` returns the entire dispatch-level operations dataset (one record per dispatch, joined with unit name/type, incident date/type/severity, and the incident outcome) as ONE JSON string with no pagination — measured **~17.6k tokens at v0** (survivable but expensive; 199 records) and **~134k tokens at v3** (1,516 records; echoing it into context is fatal under a ~70k response budget — it must be consumed inside the programmatic sandbox and filtered before printing). It is genuinely sufficient for the slow-response and poor-outcome checks. The paginated `get_unit_dispatches` and per-incident `get_incident_outcome` tools remain available as the safe alternative.
- **M2 mixed return shapes** (descriptions state WHAT, never HOW):
  | tool | success shape |
  |---|---|
  | `list_units` | native dict (unchanged) |
  | `get_unit_personnel` | native dict (unchanged) |
  | `get_unit_dispatches` | JSON-encoded string |
  | `export_dispatch_operations` | JSON-encoded string |
  | `get_unit_equipment` | MCP envelope (`json.loads(resp["content"][0]["text"])`) |
  | `get_maintenance_history` | Python-repr string (`ast.literal_eval`; `json.loads` fails) |
  | `get_incident_outcome` | plain `key: value` text (single flat record) |
- **Error contract**: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` (JSON-string form for the JSON-string tools) — sharing NO keys with any success shape. Not-found → `404 object_not_found` ("Could not find unit with ID: …"); bad/missing/wrong-typed input → `400 validation_error` ("body.unit_id should be a non-empty string, instead was 'undefined'."). SOURCE's `{"error": ...}` shape on `get_incident_outcome` is replaced by this contract.
- **verify()**: ports the SOURCE computation 1:1, consuming the bulk export once in memory, unwrapping envelopes, `json.loads`-ing JSON strings, `ast.literal_eval`-ing repr strings, and parsing key:value text (plus a one-shot cross-check of the export against `get_unit_dispatches`/`get_incident_outcome`). Reward **1.0 at v0** (206 tool calls, ≥15 floor) and **1.0 at v3** (100/100, 1,623 tool calls). Negative-path smoke tests pass for every tool: 404 dicts, layered 400 validation messages, shape disjointness, repr-vs-JSON parse behavior.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 4: scenario/goal, a pointer to the audit methodology + policy/configuration documents (and transcripts) as the authoritative specification, the verbatim deliverable contract (filename, exact column list and order, integer scores, sort key, tie-breaker — unchanged word for word from SOURCE), and the verbatim final-response requirement. Deleted route narration: per-file navigation of the three config files, tool hand-holding ("retrieve the roster through the listing tool", "available exclusively through the provided tools"), and sequencing scaffolds. `data.py` change (additive only; per-version `SCALE` blocks preserved): new fixed workspace document `audit_methodology.md` carrying the rules previously stated only in the prompt — all six deficiency computations (response-time averaging, certification expiry/underqualification with the basic<intermediate<advanced<specialist ordering, per-distinct-incident outcome rule, violation-count multiplication, latest-maintenance-record next-due rule, condition-rating rule), category aggregation, the total>0 inclusion rule, and the RETRAIN / RE-EQUIP / RETRAIN_AND_RE-EQUIP labels. (The summary print count of fixed config files was updated 3→4 to reflect the added document.)

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| report_format | prompt (verbatim deliverable contract) |
| correct_units | audit_methodology.md (six deficiency checks + total>0 inclusion) + audit_policy.yaml (audit_date, thresholds, keywords, attribution rule) + scoring_matrix.csv (penalties) + certification_requirements.json (required levels) |
| retraining_scores | audit_methodology.md (category aggregation) + audit_policy.yaml (retraining_factors) + scoring_matrix.csv |
| reequip_scores | audit_methodology.md (category aggregation) + audit_policy.yaml (reequip_factors) + scoring_matrix.csv |
| correct_sorting | prompt (verbatim contract: total_priority_score desc, unit_id asc tie-break) |
| correct_actions | audit_methodology.md (action-label rule) |
| response_top5 | prompt (final-response paragraph) |
