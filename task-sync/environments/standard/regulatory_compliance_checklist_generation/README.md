## Task Topic

Ensuring regulatory compliance for a turbine overhaul involves cross-referencing historical emission logs, spare parts inventory levels, environmental permit conditions, and certified technician certifications to produce a pre-outage compliance checklist and gap report.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10 (the base count).

**Structural dimensions used:**

- **Conditional Constraints**: Emission compliance depends on exceedance counts against permit limits within a time window, parts availability requires cross-referencing on-hand stock with pending orders against a minimum multiplier, and technician eligibility requires matching certification type, level hierarchy, expiry validity, active status, and schedule availability.
- **Information Scattering**: Permit limits and emission readings come from tool calls (database), while pending parts orders live in workspace TXT files, technician availability windows are in workspace JSON files, and business rule thresholds/output format specs are in workspace YAML/JSON config files. No single source is sufficient.
- **Multi-Hop Reasoning**: Turbine → site_id → permits → emission logs → exceedance check (4-hop); Task → required parts → part availability + pending orders → shortage assessment (3-hop); Task → required cert → technician search → schedule check (3-hop).

## Harness Report

- v3 reward: 1.0 (100/100, first attempt) using only `prompt.md` + `get_assistant_tools()`.
- Eval criteria: 7 (`checklist_structure` 15, `checklist_turbine_coverage` 15, `emission_status_accuracy` 15, `parts_status_accuracy` 15, `technician_status_accuracy` 15, `gap_report_structure` 10, `gap_report_content` 15; total 100).
- Source-access: clean — `env.py` was not opened during Section 2 (no escalation needed). Step-3 review of `env.py` against `prompt.md` confirmed prompt-step alignment, scale invariance (ground truth derived dynamically from DB + workspace), and precise-but-not-over-strict matching.
- Section 1 structural integrity: passed (only `data.py` differs across versions, in `SCALE` block only).
- Section 4 prompt quality: passed (no headings/bullets/tool names/absolute counts; deliverable filenames and column specs sourced via `overhaul_policy.json`).
- Issues found / fixes: none. No edits required to `v0/` or any propagated copy.
- Cleanup: `data.db`, `workspace/`, `__pycache__/`, and tmp solver removed from all `v_n/`.
