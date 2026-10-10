## Task Topic

A health authority updates clinical trial safety protocols. The process cross-references the new guidelines, active trial phase statuses, patient consent form versions, and site audit histories to produce a compliance action plan with prioritized protocol amendments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 8                   |
| v1      | 60             | 16                  |
| v2      | 120            | 24                  |
| v3      | 240            | 32                  |

The scaling ratios follow the standard progression: rows scale at 2x/4x/8x, and workspace files scale at base+N/base+2N/base+3N where N=8 (the v0 base).

**Structural dimensions used:**

- **Conditional Constraints**: Amendment type and deadline are determined by multi-factor business rules involving guideline severity, consent form status, site audit findings, and priority score brackets. Thresholds and scoring weights reside in workspace configuration files (severity_matrix.json, amendment_priority_rules.yaml, phase_requirements.csv).

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Trial metadata, consent records, and audit histories are only accessible via tools, while site risk scores (inspection reports), protocol deviation counts (trial dossiers), scoring parameters (severity matrix), and the new guidelines themselves are only available in workspace files. Solving the task requires combining both sources.

- **Multi-Hop Reasoning**: The priority score computation forms a dependency chain of length 4+: read new guideline → query matching active trials → for each trial, query consent forms and site audits → look up site inspection reports and trial dossiers from workspace → apply scoring matrix → determine amendment type via precedence rules → compute deadline from priority brackets.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 6 (action_plan_structure 15, trial_guideline_pairs 20, priority_scores 20, amendment_types 15, consent_update_report 15, sorting_and_deadlines 15).
- Solver source-access: clean black-box. Solved using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Section 1 structural integrity: passed; `env.py`/`prompt.md` byte-identical across v0..v3, only `SCALE` differs in `data.py`.
- Section 3/4 review: no issues found. Step criteria align with prompt deliverables, ground truth is computed dynamically from `data.db` and the workspace, and prompt wording is scale-invariant prose with no tool-name leakage.
- Issues + fixes: none.
- Blockers: none.
