## Task Topic

Generate a contract amendment impact report by cross-referencing master service agreement clauses, active change order requests, vendor compliance certifications, and project milestone payment schedules to identify non-compliant terms and required signatories.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 8                   |
| v1      | 60             | 16                  |
| v2      | 120            | 24                  |
| v3      | 240            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=8.

**Structural dimensions used:**

- **Conditional Constraints**: Non-compliance determination depends on multi-table business rules (cost vs. amendment threshold + certification expiry, schedule impact vs. priority-based limits, overdue payments + risk ratings, penalty flags + certification levels). Thresholds and parameters live in workspace configuration files (`compliance_rules.yaml`, `signatory_matrix.json`).
- **Information Scattering**: Task-critical fields are split across database tools (clauses, change orders, certifications, payments) and workspace files (risk ratings in JSON, penalty flags in TXT, prior amendment counts in YAML, adjustment data in CSV). Both sources must be consulted to evaluate every non-compliance condition.
- **Multi-Hop Reasoning**: Dependency chains of length ≥ 3, e.g., change order → linked clause → vendor certification check → compliance rules threshold → signatory matrix → escalation via amendment history.

## Harness Report

- v3 reward: 1.0 (total_score 105 / max_score 105)
- Number of eval criteria: 7 (report_structure, orders_identified, compliance_types, signatory_levels, summary_json, report_sorting, response_findings)
- Solver result: succeeded on the first attempt using only `v3/prompt.md` plus the public interface returned by `Task_Env.get_assistant_tools()`. `env.py` was not opened during Section 2; no escalation under step 6 was needed.
- Issues found and fixes applied: none. Section 1 structural integrity passed, Section 3 prompt-step alignment passed (every criterion maps to a stated requirement, ground truth is recomputed dynamically from `data.db`/workspace, no hardcoded counts), and Section 4 prompt.md quality passed (no heading/bold/lists, no tool names, scale-invariant wording, exact column/format specs).
