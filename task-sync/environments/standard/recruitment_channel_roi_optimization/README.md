## Task Topic

Optimize recruitment channel spend. Correlate candidate source (job boards, referrals, agencies), time-to-hire metrics, first-year retention rates, and role-specific hiring costs to produce a quarterly budget allocation plan with expected quality-of-hire KPIs.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Scaling: `rows_per_table` doubles each version (v1=2×, v2=4×, v3=8× of base). `num_workspace_files` increases linearly (v1=base+N, v2=base+2N, v3=base+3N where N=10). Four fixed configuration files (channel pricing, KPI formula, budget rules, quarterly targets) are produced at every scale and are not counted in `num_workspace_files`.

**Structural dimensions used:**

- **Information Scattering**: Quality-of-hire sub-scores require combining tool-returned metrics (retention rate, time-to-hire, internal cost) with workspace-file data (interview scores in CSVs, manager satisfaction in JSONs, onboarding completion in YAMLs). External channel fees come from a workspace YAML config, not from tools. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The budget allocation follows a dependency chain of length ≥ 4: tools → workspace configs → quality score computation → efficiency score → constrained budget allocation with redistribution → expected-hires derivation.
- **Conditional Constraints**: Per-source budget allocation is clamped between 8% and 35% of the total budget, with iterative redistribution among unconstrained sources.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (budget_file_structure, budget_amounts_accuracy, budget_total_constraint, kpi_file_structure, kpi_values_accuracy, response_summary)
- Source-access: clean — solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no escalation to `env.py` or `data.py` was required.
- Section 1 structural integrity: passed; `env.py` and `prompt.md` byte-identical across v0..v3, only the `SCALE` block differs in `data.py` (v1=2×/+N, v2=4×/+2N, v3=8×/+3N).
- Section 2 solvability: passed on first run with composite quality + iterative source-clamp budget allocation.
- Issues found: none. No fixes required.
- Blockers: none.
