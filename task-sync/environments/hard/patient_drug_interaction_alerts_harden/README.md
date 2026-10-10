## Task Topic

Monitor patient safety by cross-referencing pharmacy dispensing records, electronic health records (EHR) for active diagnoses, known drug interaction databases, and lab test results to generate a daily alert list of patients requiring pharmacist intervention for potential adverse interactions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 8                   |
| v1      | 120            | 16                  |
| v2      | 240            | 24                  |
| v3      | 480            | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=8.

**Structural dimensions used:**

- **Information Scattering**: Drug interactions and lab results are in the database (accessible only via tools), while contraindication rules, alert thresholds, allergy records, ward assignments, and monitoring levels reside in workspace files across CSV, JSON, YAML, and Markdown formats. Solving the task requires combining both sources.
- **Conditional Constraints**: Alert inclusion depends on the patient's monitoring level (standard/enhanced/intensive), which determines which severity levels pass through to the final report. Thresholds for lab-based alerts are defined in workspace configuration files, not in the prompt.
- **Multi-Hop Reasoning**: Generating a lab alert requires: (1) retrieve patient medications via tool, (2) match medications against relevant-drug lists in the YAML threshold config, (3) retrieve patient lab results via tool, (4) compare values against threshold bands, (5) check patient monitoring level from ward roster CSV, (6) apply severity filtering. Drug-allergy alerts require cross-referencing tool-provided dispensing records with workspace allergy JSON files.

## Harness Report

- v3 reward: **1.0** (100/100). 534 total alerts generated (drug_interaction 420, contraindication 60, lab_alert 22, drug_allergy 32); severity breakdown: critical 103, major 112, moderate 36, minor 283; 85 distinct patients with at least one critical alert.
- Eval criteria: 7 — file_structure 10/10, drug_interaction_alerts 20/20, contraindication_alerts 20/20, lab_value_alerts 15/15, drug_allergy_alerts 15/15, sorting_and_format 10/10, response_summary 10/10.
- Section 1 (structural integrity): top-level contains exactly README.md + v0..v3; each vN contains exactly data.py / env.py / prompt.md; env.py and prompt.md are byte-identical across v0..v3; data.py differs only in the SCALE block (rows 60/120/240/480, workspace-files 8/16/24/32). No stale artifacts found.
- Section 2 (solvability at v3): standalone solver written to /tmp using only prompt.md and `Task_Env.get_assistant_tools()` (env.py not opened); achieved reward 1.0 on first attempt with all seven criteria passing.
- Section 3 (env quality): all step criteria correspond to explicit prompt requirements; ground truth computed live from DB and workspace files (no hard-coded counts or distributions). Alert matching keyed on (patient_id, alert_type, frozenset(drugs)) — description text not compared, which is appropriate since prompt.md does not mandate exact description wording for drug_allergy alerts. Column-order enforcement is present in the prompt but not in step (step checks presence only); this is a minor under-strictness that does not affect correctness in practice.
- Section 4 (prompt quality): no title, no bold headers, deliverables woven into prose, scale-invariant wording, no tool names or source-file names leaked, exact column names and sort order specified.
- Issues found: none. No edits required to data.py, env.py, or prompt.md.
- Cleanup: data.db, workspace/, __pycache__ removed from all four version directories; /tmp solver removed; top-level structure is README.md + v0/ v1/ v2/ v3/ only.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/patient_drug_interaction_alerts`; `step()`, `_compute_expected_alerts()` ground truth, and criterion weights are byte-for-byte unchanged.

### M2 — mixed return encodings (per-tool return-shape map)

| tool | success shape | error shape |
|---|---|---|
| `list_patients` | native dict, nested list object (`{"object": "list", "results", "has_more", "next_cursor"}`) | `_error` dict |
| `get_patient_profile` (new detail tool) | plain `key: value` text (flat record) | `_error` dict |
| `get_patient_medications` | JSON-encoded string of a nested list object | `json.dumps(_error(...))` string |
| `get_drug_interactions` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) | `_error` dict |
| `get_patient_diagnoses` | Python-repr string (single quotes; needs `ast.literal_eval`) | `_error` dict |
| `get_patient_lab_results` | native dict, nested list object | `_error` dict |

2/6 tools stay native (~33%). Descriptions state only WHAT each tool returns, never the encoding.

### M3 — deep-nested record structures

All list tools return Notion-style records: values live at `properties.<Prop>.title[0].plain_text` (display names, drug names, test names), `properties.<Prop>.select.name` (gender, severity, ICD codes, frequency, units), `properties.<Prop>.number.number → number` (lab values via `_number`), `properties.<Prop>.rich_text[0].plain_text` (first/last name, dose, prescriber, descriptions), `properties.Patient.relation[0].id` (foreign keys), and `properties.<Prop>.date.date.start` (dates). `list_patients` uses cursor pagination (`has_more`/`next_cursor`) instead of `total`/`total_pages`.

### Error contract

Tools never raise. Errors are `{"status", "object": "error", "code", "message", "request_id"}` — no keys shared with any tool's success payload fields. Not-found → `404 object_not_found` ("Could not find patient with ID: <id>."); bad input → `400 validation_error` ("body.patient_id should be an integer, instead was 'undefined'."). Unknown drug names in `get_drug_interactions` legitimately return an empty result list (there is no drug registry table), matching SOURCE behavior.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 7 route-narrating paragraphs to 5: scenario/goal, a pointer to the policy/reference documents as the authoritative specification, and the verbatim deliverable contract (filename + column order + name/field formats, sort order, final-response summary requirements). Deleted: per-system/per-file navigation (old ¶2), the four alert-category rule narration (old ¶3), and the monitoring-filter restatement (old ¶4, already stated in `severity_response_protocol.md`). `data.py` change (additive only, SCALE untouched, per-version files differ only in SCALE): new fixed workspace document `alert_generation_methodology.md` carrying the previously prompt-only rules — pair-once drug-interaction rule, contraindication matching, most-recent-lab-per-test convention, inclusive threshold boundaries with severest-band-wins and high/low tie resolution, per-relevant-drug lab-alert fan-out, always-critical drug-allergy rule — plus a cross-reference line in `severity_response_protocol.md`.

Completeness audit (`step()` criterion → info source):

| criterion | source |
|---|---|
| file_structure (file + columns) | prompt ¶3 (verbatim contract) |
| drug_interaction_alerts | `alert_generation_methodology.md` §1 + interaction lookup tool (severity/description from DB) |
| contraindication_alerts | `alert_generation_methodology.md` §2 + `contraindications.json` |
| lab_value_alerts | `alert_generation_methodology.md` §3 + `alert_thresholds.yaml` |
| drug_allergy_alerts | `alert_generation_methodology.md` §4 + `allergy_records_batch_*.json` |
| (monitoring-level exclusion, affects 2–5) | `severity_response_protocol.md` (Monitoring Level Alert Thresholds) + methodology §Monitoring-Level Filtering |
| sorting_and_format | prompt ¶4 (verbatim) + `severity_response_protocol.md` (Alert Prioritization) |
| response_summary | prompt ¶5 (verbatim) |

### Verification

- v3 (480 patients): `verify()` reward **1.0**, 2008 tool calls.
- v0 (60 patients): `verify()` reward **1.0**, 285 tool calls (≥ 15 floor).
- Negative-path smoke tests pass: 404 error dict for nonexistent patient on native/JSON-string/repr tools; `validation_error` for string/None/bool `patient_id`/`page` and non-string `drug_name`; repr success payloads fail `json.loads` and parse via `ast.literal_eval`; envelope tools require `json.loads(resp["content"][0]["text"])`.
- `diff v0/env.py v{1,2,3}/env.py` empty; `prompt.md` identical across versions; per-version `data.py` differ only in the `SCALE` block; no runtime artifacts left.
