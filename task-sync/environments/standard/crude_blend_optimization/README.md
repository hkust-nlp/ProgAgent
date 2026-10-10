## Task Topic

Optimize crude oil blending by analyzing real-time crude assay data, storage tank levels, pipeline delivery schedules, and product demand forecasts to generate a daily blending schedule that maximizes high-value product yield.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

Structural dimensions used:

- **Information Scattering**: Crude quality properties are split between the database (API gravity, sulfur, pour point, cost) and workspace laboratory CSV files (mercaptan, salt, nickel, vanadium). Quality specifications and scheduling policies live exclusively in workspace configuration files (YAML, JSON, MD). Both tool queries and file reads are required to solve the task.
- **Conditional Constraints**: Eligibility of a crude batch for a particular product-tier combination depends on multiple quality thresholds drawn from both the database and lab reports. Premium tiers impose additional contaminant limits that standard tiers do not.
- **Deliverable Constraints**: Output files enforce exact column ordering, JSON-encoded component maps with two-decimal rounding, and a specific revenue format in the response text.
- **Multi-Hop Reasoning**: Demand → quality specs (workspace YAML) → batch properties (tool + lab CSV) → qualification check → unit assignment (tool) → volume/revenue calculation → schedule output.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (schedule_format, quality_report_format, demand_coverage, quality_compliance, volume_constraints, revenue_accuracy, response_summary)
- Source-access: clean — solver passed using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` and runtime artifacts (`data.db`, `workspace/`); no escalation to `env.py` was needed.
- Structural integrity: passed. Top level contains only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block. SCALE follows the prescribed ratios (rows 50/100/200/400 = ×1/2/4/8; files 10/20/30/40 = +0/N/2N/3N with N=10).
- Issues found: none. Prompt-step alignment, evaluation strictness, and scale invariance all checked out, and `prompt.md` formatting (no headings, no bullet lists, no tool/source filenames, scale-invariant wording) complies with harness rules.
- Fixes applied: none beyond final cleanup of generated artifacts (`data.db`, `workspace/`, `__pycache__/`) and the temporary solver at `/tmp/solve_crude_blend_optimization.py`.
