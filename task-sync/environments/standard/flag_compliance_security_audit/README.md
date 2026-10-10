## Task Topic

Audit enterprise feature flag compliance and security. Cross-reference flag targeting rules, employee Active Directory groups, change management tickets, and audit logs to identify unauthorized or non-compliant flag configurations, generating a remediation roster for security review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The scaling follows the standard ratios: rows grow as 1×, 2×, 4×, 8× of the v0 base; workspace files grow as base, base+N, base+2N, base+3N where N = base (8).

**Structural dimensions used:**

- **Conditional Constraints**: Five distinct violation types each depend on cross-referencing 2–3 tables/columns against policy thresholds stored in workspace configuration files (clearance levels per environment, targeting group membership with exemptions, maintenance-window schedules, sensitive-service designation with security-approval requirements).
- **Information Scattering**: Targeting rules live exclusively in workspace JSON batch files, compliance thresholds in YAML/CSV/MD workspace configs, while employee records, change tickets, and audit logs are only accessible through tools. Solving any single violation type requires reading from both sources.
- **Multi-Hop Reasoning**: The sensitive-service approval check requires: workspace CSV (is the service sensitive?) → tool (retrieve the flag's approved change tickets) → tool (look up each ticket approver's AD group memberships) → determine whether any approver belongs to the Security group. The out-of-window check requires: workspace YAML (parse maintenance windows) → tool (retrieve audit logs with modification actions) → datetime arithmetic against the policy windows.

## Harness Report

- v3 reward: 1.0 (100/100) on first solver run.
- Eval criteria: 7 (`roster_file_format`, `clearance_violations`, `targeting_violations`, `missing_ticket_violations`, `out_of_window_violations`, `sensitive_service_violations`, `response_summary`).
- Section 1 structural integrity: clean. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 80/160/320/640, files 8/16/24/32).
- Section 2 solvability: solved at v3 scale using only `prompt.md` + `Task_Env.get_assistant_tools()`. No step-6 escalation required; `env.py` was not read during solving.
- Section 3/4: prompt-step alignment verified via 100% reward; prompt is prose-only with no headings/lists/tool-name leaks; deliverable columns, sort order, and exact violation labels enforced by `step`.
- Issues found: none. No fixes were required.
- Blockers: none.
