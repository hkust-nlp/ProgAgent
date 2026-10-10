## Task Topic

Cross-reference audit program checklists, prior year findings, current year general ledger entries, and client-provided support documents to verify all high-risk areas are tested, generating a coverage gap analysis for the audit manager.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 10                  |
| v1      | 60             | 20                  |
| v2      | 120            | 30                  |
| v3      | 240            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8× progression; workspace files follow base/base+N/base+2N/base+3N where N=10.

**Structural dimensions used:**

- **Information Scattering**: Risk scoring policy, materiality thresholds, and required procedure definitions live in workspace config files (YAML/JSON), while audit area details, checklist items, prior findings, and GL entries are only accessible through tool calls. Client support documents are workspace files in mixed formats (TXT, CSV, JSON, MD) that must be parsed individually. No single source contains enough information to complete the task.
- **Multi-Hop Reasoning**: The agent must follow a dependency chain of length 4+: (1) list areas via tool → (2) read risk scoring policy from workspace → (3) query prior findings and GL summaries per area via tools → (4) read materiality thresholds from workspace → (5) compute composite risk scores → (6) query checklists via tools → (7) read required procedures from workspace → (8) cross-reference to identify gaps. Additionally, support deficiency detection requires parsing all client support files and matching them back to high-risk areas.
- **Conditional Constraints**: Composite risk classification depends on multi-factor scoring involving inherent risk category, unremediated prior finding severity, GL materiality exceedance, and support document availability. Each factor's contribution is governed by workspace config parameters, not hard-coded rules.

## Harness Report

- v3 reward: 1.0 (total_score 100/100).
- Eval criteria count: 7 (output_format 10, high_risk_identification 20, procedure_gap_detection 20, unremediated_finding_gaps 15, support_deficiency_detection 15, materiality_gap_detection 10, executive_summary 10).
- Solver source-access: clean black-box solve. Solver wrote `/tmp/solve_audit_risk_coverage_validation.py` using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No step-6 escalation; `env.py`, `data.py`, `README.md`, and v0/v1/v2 contents were not consulted during Section 2.
- Section 1 (structural integrity): passed; `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3, and `data.py` differs only in the SCALE block. No stray runtime artifacts.
- Section 3 (env quality): coverage and completeness intact, ground truth derived from current `data.db`/workspace, no hard-coded counts. Step uses substring match on procedure names (tolerant but not over-permissive); no over-normalization.
- Section 4 (prompt quality): no title, no bold headers, no bulleted deliverable list, no leakage of tool or schema names; output filename and column schema are explicit and scale-invariant.
- Issues found and fixed: none. No edits were required to `v0/`.
- Blockers: none.
