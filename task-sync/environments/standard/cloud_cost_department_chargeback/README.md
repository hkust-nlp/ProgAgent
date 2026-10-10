## Task Topic

Reconcile multi-cloud infrastructure spend by joining daily billing exports, resource tag compliance reports, reserved-instance utilisation logs, and cost-centre budget tables to produce a per-department showback and chargeback report.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Difficulty scales only through data volume; `env.py` and `prompt.md` are identical across all four versions.

**Structural dimensions used:**

- **Information Scattering** — Billing base costs live in the database (queried via tools), while negotiated discounts, volume credits, and support-tier surcharges reside in daily CSV files in the workspace. Account-to-department mappings are only available in a workspace JSON file. The agent must join data from both sources to compute adjusted costs.
- **Multi-Hop Reasoning** — Solving the task requires at least a four-hop chain: query billing records (tool) → read adjustment files (workspace) → look up account-to-department mapping (workspace JSON) → query tag compliance (tool) → read chargeback policy (workspace YAML) → compute final chargeback. Budget variance adds another hop through cost-centre budget queries filtered by a billing period read from a text file.
- **Conditional Constraints** — Tag-compliance surcharges apply only to non-compliant resources; RI underutilisation penalties apply only when daily utilisation falls below a threshold specified in the policy file. Shared-services allocation uses headcount-proportional weighting.
- **Deliverable Constraints** — Four CSV output files have strictly specified column names, sort orders, and two-decimal-place rounding. The final response requires three labelled lines with exact formatting.

## Harness Report

- v3 reward: 1.0 (100/100) on first solver attempt.
- Eval criteria: 7 (showback_report 20, chargeback_report 20, ri_savings_report 15, budget_variance 15, total_adjusted_spend 10, top_department 10, over_budget_departments 10).
- Solver source-access: clean black-box (only `v3/prompt.md` + `get_assistant_tools()` consulted; no step-6 escalation needed).
- Structural integrity: all `diff` checks passed for env.py and prompt.md byte-for-byte across v0..v3; only SCALE differs in data.py. One pre-existing `v0/__pycache__` was removed during cleanup.
- Issues found: none. Section 3/4 review confirmed prompt-step alignment, scale invariance, and prose formatting compliance.
