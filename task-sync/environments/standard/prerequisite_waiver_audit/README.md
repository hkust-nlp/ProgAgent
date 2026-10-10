## Task Topic

Audit prerequisite waivers for graduation clearance. Cross-reference student waiver petitions, course substitution logs, historical grade transcripts, and degree audit rule sets to identify non-compliant approvals, compiling the exceptions into a compliance review dossier.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Scaling ratios: rows grow at 2×/4×/8× of base; workspace files grow at base+N/base+2N/base+3N where N=8.

### Structural Dimensions

- **Conditional Constraints**: Compliance checks depend on cross-referencing policy thresholds (GPA minimums, authority hierarchy, processing time limits, credit equivalence floors) against data from multiple tables and workspace configuration files.
- **Information Scattering**: Violation detection requires combining data from the database (petitions, student profiles, degree rules, substitutions) with workspace files (compliance policy JSON, approver registry YAML). No single source contains enough information to determine compliance alone.
- **Multi-Hop Reasoning**: Checking authority compliance requires: petition → student profile (get program) → degree audit rule (get required authority) → approver registry file (get actual authority) → compare. This is a 4-hop dependency chain.

## Harness Report

- v3 solvability reward: 1.0 (100/100).
- Number of eval criteria: 6 (`dossier_file_exists`, `dossier_columns`, `petition_identification`, `violation_types`, `summary_statistics`, `summary_report`).
- Source-access: clean. Solver was written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`; no escalation to `env.py`/`data.py` was required.
- Section 1 structural integrity: PASS. Top-level holds only `README.md` + `v0..v3/`; each version dir holds only `data.py`/`env.py`/`prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Section 3 env quality: PASS. The 6 step criteria align with the prompt's deliverables; ground truth is recomputed from the live DB/workspace each run (scale-invariant).
- Section 4 prompt quality: PASS. No headings/bold/lists; computation rules in prose; no tool/source filenames leaked; deliverable filenames and column names explicit; wording uses "every"/"all" rather than absolute counts.
- Issues found: none. No fixes required.
