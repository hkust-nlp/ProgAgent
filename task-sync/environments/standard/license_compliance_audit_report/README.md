## Task Topic

License compliance failures can block product releases. Analyze software composition analysis reports, approved OSS license lists, dependency version histories, and legal exception tickets to produce an actionable report of components requiring license review or replacement.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Only the `SCALE` dict in `data.py` differs across versions; `env.py` and `prompt.md` are identical.

### Structural Dimensions

- **Conditional Constraints**: Compliance determination depends on license approval tier (approved/restricted/denied), deployment environment (production and staging trigger review for restricted licenses), exception ticket status and expiry, and risk score thresholds — all drawn from workspace policy and configuration files.
- **Information Scattering**: Vulnerability counts and scanner confidence live exclusively in workspace SCA scan CSV files; deployment environments and project criticality are accessible only via tools; the approved license registry lives in a YAML workspace file; exception details come from tool queries. No single source suffices to determine compliance.
- **Multi-Hop Reasoning**: Determining the correct action for a component requires: reading policy thresholds (file) → enumerating project components (tool, paginated) → looking up license category and risk level (tool) → cross-referencing vulnerability data (file) → querying exception status (tool) → checking version history for recent license changes (tool) → computing risk score and classifying action.

## Harness Report

- **v3 reward:** 1.0 (100/100)
- **Eval criteria (7):** `report_exists` (10), `report_structure` (10), `flagged_components` (20), `compliance_status` (20), `risk_scores` (15), `action_required` (15), `response_summary` (10).
- **Structural integrity:** `diff` confirmed `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` dict (rows ×1/2/4/8, files +0/N/2N/3N with N=10).
- **Solvability:** Solved at v3 scale using only `prompt.md` and `Task_Env.get_assistant_tools()` (workspace policy/yaml/csv files plus tool-discovered project, license, exception, and version-history data). Solver placed under `/tmp/`, never inside the env directory.
- **Issues found and fixed (in `v0/env.py`, propagated to v1/v2/v3):**
  1. The license-change override in `_determine_compliance` only fired in a subset of branches (not when a denied component had a `pending`, `denied`, or `expired` exception ticket). The prompt requires the override to apply *regardless of current exception status* for any non-approved-license component. Fixed by short-circuiting on `has_recent_change` for the entire non-approved branch.
  2. The `exception_denied` branch always returned `replace` regardless of risk score, contradicting the prompt rule that the action for denied/no-exception cases depends on the risk score relative to the replacement threshold. Fixed to gate on `replace_threshold`, returning `obtain_exception` below it.
- **Cleanup:** Removed `data.db`, `workspace/`, and `__pycache__/` from each `v_n/`; removed temporary solver under `/tmp/`. Top-level directory contains exactly `README.md`, `v0/`, `v1/`, `v2/`, `v3/`.
