## Task Topic

Cross-reference applicant biometric submissions, visa category quotas, embassy appointment backlogs, and document verification flags to identify stalled high-priority applications, generating a prioritized intervention list for case officers.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

The task exercises the following structural dimensions:

- **Conditional Constraints**: Whether an application is "stalled" depends on five independent conditions checked against thresholds stored in workspace configuration files (SLA multipliers, biometric expiry windows, document flag counts, appointment wait limits, quota utilization percentages). High-priority eligibility adds a second layer of conditional logic combining database fields with case-dossier attributes.
- **Information Scattering**: Applicant records live in the database (accessible only via tools), while escalation levels and sponsor tiers are spread across multi-format case dossier batch files in the workspace. Stall thresholds, scoring rules, and SLA standards each reside in separate config files. No single source is sufficient to solve the task.
- **Multi-Hop Reasoning**: The dependency chain runs at least four hops deep: search for active applicants (tool) → retrieve biometrics/documents/appointments per applicant (tools) → cross-reference with quota data (tool) → look up escalation level and sponsor tier from workspace dossier files → apply scoring formula from workspace config → determine recommended action from priority-ordered stall reasons.
- **Deliverable Constraints**: The output CSV has a fixed column order, semicolon-and-space-separated stall reasons, scores rounded to two decimal places, and a three-level sort key (priority_score DESC, days_stalled DESC, applicant_id ASC).

## Harness Report

- v3 reward: **1.0** (115/115)
- Eval criteria: 7 — output_file_format (15), stalled_identification (25), priority_score_accuracy (20), stall_reasons_accuracy (15), sorting_order (10), recommended_actions (15), db_interventions_recorded (15)
- Stalled high-priority applications found at v3: 262

Issues found and fixes: **none.** All five harness sections passed without modification.

- Section 1 (structural integrity): top-level contains exactly README.md + v0..v3/; each version contains exactly data.py, env.py, prompt.md; env.py and prompt.md are byte-for-byte identical across versions; data.py differs only in the two SCALE values. ✓
- Section 2 (solvability at v3): solver using only prompt.md + get_assistant_tools() + runtime artifacts achieved reward 1.0 on first attempt after adding the required create_intervention calls. Escalated to read env.py solely to learn the create_intervention method signature (permitted at step 6). All 7 criteria passed.
- Section 3 (env quality): all step() criteria map to explicit prompt requirements; ground truth derived dynamically from data.db (scale-invariant); stall-reason comparison is set-based (order-independent); no hard-coded counts or data-distribution assumptions. ✓
- Section 4 (prompt quality): no title/heading, no bold section headers, no bullet/numbered lists, column names woven inline, all wording scale-invariant ("all active visa applications", "every application"), no tool names or env internals exposed. ✓
- Section 5 (clean-up): data.db, workspace/, __pycache__/, and solver script removed from all version directories. ✓

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/stalled_application_triage`. Ground truth
(`_compute_ground_truth`) and the six original step() criteria are unchanged;
step() gained exactly one DB-state criterion (M4 exception, 15 pts, new max 115).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 route-narrating
  paragraphs to 5: scenario/goal, a pointer to the policy and configuration
  documents as the authoritative specification, the intervention-recording
  requirement (M4), the verbatim deliverable contract (columns, order,
  separator, sort keys), and the final-response requirement. The only `data.py`
  change is additive: `generate_workspace` now also writes a fixed
  (non-scaling) `triage_methodology.md` capturing every rule that previously
  lived only in the prompt — active-status definition, the five stall
  conditions with reason codes and strict/inclusive boundary conventions, the
  Q2 quota quarter, the high-priority filter (incl. missing-dossier defaults),
  the full scoring formula with rounding and fallback defaults, the
  recommended-action selection rule, and the recording requirement. Tables,
  row generation, seeds, and the per-version `SCALE` blocks are untouched.
- **M1 JSON-string parameter**: `search_applicants` collapses its four filters
  into a single `filter` parameter that must be a JSON-encoded string
  (`'{"status": "pending", "embassy_id": "EMB_001"}'`). Malformed JSON returns
  `invalid_json` with line/column/char position; passing an object instead of a
  string, unsupported keys, or wrong-typed/out-of-enum values return
  recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_intervention(payload)` tool taking a
  Notion-style nested body (`parent.type="embassy_queue"` + `parent.embassy_id`,
  `properties.Applicant.reference.applicant_id`, `properties.Action.select.name`,
  optional `Note` rich_text). Validation is layered — one error per call, e.g.
  `body.parent.embassy_id should be a non-empty string, instead was 'undefined'.`
  Business checks follow structural checks: unknown applicant → 404; filing to
  the wrong embassy queue → recoverable 400. The write is
  `INSERT OR REPLACE INTO intervention_requests` (table created lazily by the
  tool); step() criterion `db_interventions_recorded` scores F1 of recorded
  applicant IDs vs the ground-truth list.

Per-tool return-shape map (M2 not assigned — all success returns stay native
dicts; error paths return the `_error` dict, whose keys `{status, object, code,
message, request_id}` are disjoint from every tool's success keys):

| tool | success shape | error paths |
|---|---|---|
| search_applicants | dict `{results, total, page, page_size, total_pages}` | invalid_json / invalid_request / validation_error |
| get_applicant_details | dict (flat row) | 404 object_not_found |
| get_biometric_status | dict `{applicant_id, biometrics}` | — |
| get_document_flags | dict `{applicant_id, documents}` | — |
| get_appointment_history | dict `{applicant_id, appointments}` | — |
| get_visa_quota | dict (row + utilization_pct) | 404 object_not_found |
| list_embassies / list_visa_categories | dict | — |
| create_intervention | deep echo `{object, id, parent, properties, created}` | layered validation_error, 404, wrong-queue 400 |

Completeness audit (step() criterion → info source; verify() never reads the
prompt, so this audit is the sufficiency check):

| criterion | source |
|---|---|
| output_file_format (15) | prompt ¶4 (verbatim contract) |
| stalled_identification (25) | triage_methodology.md §1–3 + stall_criteria.json thresholds + visa_processing_standards.csv SLAs + priority_scoring_rules.yaml high_priority_conditions + case_dossier_batch_* files |
| priority_score_accuracy (20) | triage_methodology.md §4 formula + priority_scoring_rules.yaml values |
| stall_reasons_accuracy (15) | triage_methodology.md §2 reason codes + prompt ¶4 (separator format) |
| sorting_order (10) | prompt ¶4 (three-level sort key) |
| recommended_actions (15) | triage_methodology.md §5 + priority_scoring_rules.yaml action mapping / priority order |
| db_interventions_recorded (15) | prompt ¶3 + triage_methodology.md §6 |

Verify results after hardening: v0 reward 1.0 (263 tool calls, 115/115);
v3 reward 1.0 (1745 tool calls, 115/115). Negative-path smoke tests confirmed:
M1 malformed JSON (`invalid_json` with position), dict-where-string, unsupported
key, out-of-enum value; M4 layered errors surfacing one at a time (missing body
→ string body → missing parent → wrong parent.type → missing properties →
missing Applicant → missing Action), unknown applicant 404, wrong embassy queue
400; 404 error dicts on the lookup tools.
