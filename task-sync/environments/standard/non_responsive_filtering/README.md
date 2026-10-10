## Task Topic

Flag non-responsive documents in a large production by comparing custodian data maps, keyword search hit reports, date range filters, and opposing party's requests for production to output a validated set for exclusion, reducing review volume.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Structural dimensions used:

- **Conditional Constraints**: Exclusion follows a strict priority hierarchy (privileged > excluded_file_type > no_litigation_hold > no_rfp_match), with a protected-confidentiality exemption that overrides the no_rfp_match rule. Thresholds (keyword hit count, relevance weight, date buffer) live in workspace configuration files.
- **Information Scattering**: Custodian-RFP scope mappings are in CSV files, keyword relevance weights are in JSON files, custodian litigation hold status is in YAML files, document confidentiality levels are in Markdown tables, privilege log is a separate CSV, and document metadata plus keyword hits and RFP criteria are only accessible through tool calls.
- **Multi-Hop Reasoning**: Document → custodian_id (tool) → custodian_rfp_map (workspace CSV) → rfp_criteria (tool) → keyword hits (tool) → keyword_weight for topic (workspace JSON) → threshold comparison (workspace config) → exclusion decision.
- **Deliverable Constraints**: Output CSV has exact column names and sort order; summary JSON has prescribed keys; response must contain exact "EXCLUSION TOTAL: X/Y" text.

## Harness Report

- v3 reward: 1.0 (100/100) on first solver attempt.
- Eval criteria: 7 (csv_format=10, privileged_docs=15, excluded_file_types=10, no_litigation_hold=15, no_rfp_match=20, no_false_exclusions=15, summary_json=15).
- Source-access path: clean — solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`. No step-6 escalation; `env.py` was not consulted before reward 1.0.
- Section 1: byte-for-byte invariant on `env.py` and `prompt.md` across v0..v3 holds; `data.py` differs only in the `SCALE` block. Top-level layout contains only `README.md` and `v0..v3/`. No stale runtime artifacts.
- Section 3 / 4 review: prompt.md has no title, no bold headers, no bulleted deliverable lists, no tool/source-filename leakage, scale-invariant wording ("every", "all"), and explicit column/JSON-key naming. `step()` derives ground truth dynamically from `data.db` plus workspace files (no hard-coded counts), enforces required CSV columns and `doc_id` sort order, applies the same priority hierarchy as the prompt, and assigns partial credit per category without over-normalizing strings.
- Issues found: none. No fixes required.
- Blockers: none.
