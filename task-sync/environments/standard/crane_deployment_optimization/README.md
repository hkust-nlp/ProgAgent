## Task Topic

Optimize yard crane deployment by correlating vessel stowage plans, real-time truck arrival manifests, container GPS positions, and crane maintenance logs to generate a prioritized worklist for crane operators, minimizing vessel turnaround time.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Container yard-block positions are split between the database (via tools) and GPS log CSV files in the workspace. Truck-waiting status must be determined from both the gate-system database and workspace truck-manifest CSVs. Crane availability requires checking both database maintenance logs and a workspace maintenance schedule. Stowage-plan discharge/load sequences exist only in workspace JSON files.
- **Conditional Constraints**: Crane assignment depends on zone matching (terminal layout), weight capacity (crane specs), and maintenance-window exclusion (buffer rule from priority rules). Urgency scoring applies tiered deadline thresholds, hazmat/reefer bonuses, and truck-waiting bonuses with cross-source validation.
- **Multi-Hop Reasoning**: Container → GPS log → detected block → zone map → eligible cranes → maintenance check → greedy assignment. Truck bonus requires: query DB truck status → read workspace manifests → cross-reference completed trucks → determine bonus eligibility.

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria** (6 total): worklist_structure (10), container_coverage (20), urgency_scoring (25), crane_validity (20), priority_ordering (10), summary_report (15).
- **Source-access**: Section 2 was completed cleanly using only `v3/prompt.md` plus the `Task_Env.get_assistant_tools()` interface. No step-6 escalation required; the solver achieved reward 1.0 on the first submission.
- **Structural integrity**: byte-identical `env.py` and `prompt.md` across v0/v1/v2/v3; `data.py` differs only in the `SCALE` block (rows 80/160/320/640, files 10/20/30/40). No stale databases, workspace folders, or bytecode caches.
- **Issues found**: none requiring fixes. Minor non-blocking observations: (a) `step()` does not separately validate the `estimated_total_hours` field of `summary_report.json` or the natural-language final response, but all required deliverables produced by a correct solver still earn full credit; (b) the env's sequence map is keyed by container_id (not by `(container_id, op_type)`), which is acceptable since each container belongs to one vessel and one operation type in the seeded data.
- **Blockers**: none.
