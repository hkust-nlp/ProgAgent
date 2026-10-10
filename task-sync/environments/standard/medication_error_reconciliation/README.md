## Task Topic

Reduce medication dispensing errors by cross-referencing electronic medication administration records (eMAR), pharmacy dispensation logs, nurse shift assignments, and patient allergy databases to flag mismatches, generating a daily reconciliation report for pharmacist review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Medication drug class information lives only in the workspace formulary (not returned by the medication tool), patient allergies are only accessible via tool calls, prescribed doses are only in workspace batch CSV files, and nurse shift data is only queryable through tools. Solving any single error check requires combining data from multiple heterogeneous sources.

- **Multi-Hop Reasoning**: Allergy conflict detection requires a 4-hop chain: retrieve eMAR record (tool) → look up drug class in formulary (workspace file) → retrieve patient allergies (tool) → compare and flag. Dosage mismatch detection similarly chains: eMAR record (tool) → dispensation record (tool) → prescribed dose (workspace file) → tolerance threshold (workspace config) → compute deviation.

- **Conditional Constraints**: Error flagging depends on per-drug-class tolerance thresholds (from workspace YAML config), allergy severity mappings, and nurse shift coverage rules (ward match + time window). These multi-condition checks span 2–3 data sources each.

- **Deliverable Constraints**: Output requires exact column ordering, specific error type labels, severity-then-ID sorting, and a structured JSON summary with precise field names and counts.

## Harness Report

- v3 reward: 1.0 (total_score 100/100)
- Eval criteria: 6 (allergy_conflict 20, dosage_mismatch 20, unauthorized_admin 15, missing_dispensation 15, dose_deviation 15, report_format 15)
- Source-access: clean — solver succeeded on first attempt using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No step-6 escalation into `env.py`/`data.py` was required.
- Structural integrity: pass. `diff` showed `env.py` and `prompt.md` byte-identical across v0..v3, and `data.py` differs only in the `SCALE` block (rows ×1/2/4/8 = 80/160/320/640; files +0/N/2N/3N = 8/16/24/32 with N=8).
- Section 3 (env quality): pass. step's six criteria correspond directly to prompt requirements with no hidden checks; ground truth is computed from current DB/workspace, no hard-coded counts.
- Section 4 (prompt quality): pass. No headings, bold, lists, code, tool names, or absolute counts; deliverable filenames and column orders specified explicitly.
- Issues found: none. No fixes applied.
- Blockers: none.
