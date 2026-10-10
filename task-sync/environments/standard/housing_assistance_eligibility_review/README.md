## Task Topic

Assess housing assistance eligibility changes by analyzing tenant income certifications, periodic utility bill submissions, property inspection reports, and regional fair market rent benchmarks, generating a case roster for benefit adjustment or termination.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 12                  |
| v1      | 160            | 24                  |
| v2      | 320            | 36                  |
| v3      | 640            | 48                  |

Structural dimensions used:

- **Information Scattering**: Task-critical fields are split across tools and workspace files. Tenant basic info, income certifications, inspection scores, and FMR values come from tool queries; current household sizes, utility compliance rates, AMI schedules, utility allowances, current benefit amounts, and inspection deficiency severities are only available in workspace files. Both sources are required to compute any single determination.
- **Multi-Hop Reasoning**: Each tenant's determination requires a chain of at least 4 hops: retrieve tenant record (tool) → look up current household size (workspace profile) → compute income limit from AMI (workspace schedule) × policy threshold (workspace policy) → compare against income (tool) → retrieve FMR (tool) + utility allowance (workspace) → compute revised benefit → compare with current benefit (workspace ledger) → apply determination rules.
- **Conditional Constraints**: Eligibility depends on layered business rules spanning income thresholds, utility compliance rates, inspection scores, critical deficiency flags, and benefit change thresholds—all parameterized in workspace policy files.

## Harness Report

- v3 reward: 1.0 (532 active tenants)
- Eval criteria: 7 (file_structure 10, tenant_coverage 10, income_limit_accuracy 20, compliance_accuracy 10, benefit_calculation 15, determination_accuracy 25, summary_response 10; total 100)
- Source-access: clean (solver written from `v3/prompt.md` + `get_assistant_tools()` only; no escalation to step 6 needed)
- Section 1 structural integrity: pass. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block; no stray runtime artifacts.
- Section 2 solvability: solver at `/tmp/solve_housing_assistance_eligibility_review.py` reached `reward == 1.0` on first valid run after correcting tool-response shape assumptions in the solver (no env edits required).
- Section 3 env-quality: criteria align with prompt requirements; ground truth derived from `data.db` + workspace; tolerances reasonable (income_limit/new_benefit ±1.0, compliance ±0.02) and not over-normalizing.
- Section 4 prompt-quality: no headings/bold/lists, no leakage of tool or source-data filenames, scale-invariant phrasing, deliverable filename and column list specified.
- Issues found: none requiring fixes.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from every `v_n/` and the temp solver.
