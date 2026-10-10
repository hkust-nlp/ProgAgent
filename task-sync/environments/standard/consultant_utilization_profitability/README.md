## Task Topic

Analyze consultant utilization and project profitability. Correlate timesheet entries, project budget allocations, individual skill matrices, and client billing rates to identify underutilized resources and over-servicing, generating a reallocation proposal with forecasted margin impact.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 40            | 10                  |
| v1      | 80            | 20                  |
| v2      | 160           | 30                  |
| v3      | 320           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Billing rates live exclusively in workspace YAML files (tier-based defaults and client-specific negotiated overrides), while consultant hourly costs and client billing tiers are only accessible through tool calls. Capacity target hours come from workspace CSVs, project skill requirements from workspace JSONs. No single source provides all data needed for any computation.

- **Multi-Hop Reasoning**: Computing a single project's margin requires: (1) retrieve timesheet entries via tool → (2) get each consultant's role and hourly cost via tool → (3) get the project's client_id via tool → (4) get the client's billing tier via tool → (5) check workspace rate card files for custom rates → (6) fall back to workspace tier rate schedule if standard → (7) aggregate and compute. The reallocation proposal adds further hops through skill matching across tools and workspace requirement files.

- **Conditional Constraints**: Reallocation eligibility depends on multiple interacting rules: utilization status (threshold from config), skill proficiency (minimum from project requirement files), concurrent project cap (from policy file), projected utilization ceiling (compound calculation involving current hours, proposed hours, and available hours), and weekly hour cap—all sourced from different workspace files.

## Harness Report

- **v3 reward:** 1.0 (100/100)
- **Eval criteria count:** 8 (`utilization_report_format`, `utilization_rates`, `utilization_status`, `profitability_format`, `profitability_margins`, `overservicing_flags`, `reallocation_proposal`, `margin_improvement_stated`)
- **Solver source-access:** clean black-box — solver was written using only `v3/prompt.md` plus the public tool catalog from `Task_Env.get_assistant_tools()`. No need to open `env.py` or `data.py`.
- **Issues found:** none. Structural integrity passed (env.py and prompt.md byte-for-byte identical across v0..v3; data.py differs only in SCALE: rows 40/80/160/320 = ×1/2/4/8, files 10/20/30/40 = +0/N/2N/3N). Prompt is prose-only, scale-invariant, no tool names. Step is scale-invariant, derives ground truth from data.db + workspace, no hidden criteria, tolerances reasonable.
- **Fixes applied:** none.
