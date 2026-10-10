## Task Topic

Identifying root cause of application slowdowns requires cross-referencing network device SNMP trap logs, NetFlow session data, application performance monitoring (APM) traces, and recent change management tickets to pinpoint faulty network segments, outputting a prioritized remediation list with correlated evidence.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Critical data is split across multiple sources. SNMP trap severities and device identities come from tool queries, interface-level packet loss rates live only in workspace CSV files, SLA thresholds and scoring formulas are in workspace config files (YAML/JSON), and segment criticality definitions are in a separate JSON file. No single source contains enough information to solve the task.

- **Multi-Hop Reasoning**: The task requires dependency chains of length ≥ 3. For example: query SNMP traps to identify problematic devices → query NetFlow sessions on those devices to find traversing applications → query APM traces for those applications to check SLA breaches → look up tier-specific thresholds from config files → compute SLA impact factor. Similarly: identify correlated change tickets → apply correlation rules from config → determine bonus value → combine with severity score, criticality weight, and SLA factor into final priority.

- **Conditional Constraints**: Root cause classification depends on multi-source business rules: a device is classified as "Change-Induced Failure" only if it has both a rolled_back/failed change ticket AND critical/major traps; "Interface Degradation" requires both linkDown/interfaceError traps AND interface packet loss rate > 5% from workspace files; "Packet Loss" requires packetLoss traps AND packet loss rate > 2% from workspace files. Rules are applied in strict priority order.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (csv_format 15, device_identification 20, root_cause_classification 20, priority_scores 20, ranking_order 10, correlated_tickets 15)
- Solver source-access: clean black-box. The /tmp solver was written using only v3/prompt.md plus env.get_assistant_tools(). After the first run scored 0.84 with confident-correct logic, env.py was opened under the Section 2 step-6 escalation to diagnose the remaining mismatches.
- Issues found and fixes:
  1. CSV write location ambiguity: prompt didn't specify the directory and step expected `<workspace>/remediation_list.csv`. Updated v0/prompt.md to say "in your working directory" so agents place it under the working directory the env then inspects.
  2. Misleading classification wording: priority_formula.yaml referenced a non-existent `interface_error_rate` column. The actual env logic uses the per-interface `packet_loss_rate` for both Interface Degradation (>5.0) and Packet Loss (>2.0). Fixed the rule strings in v0/data.py and the prompt's interface paragraph to describe the per-interface packet_loss_rate lookup keyed by (device_id, interface_name).
  3. Non-deterministic ranking ground truth: env's tie-break only used `(-priority_score, segment_name)`, leaving order undefined among same-segment ties. Added device_hostname as a third sort key in env.py and updated the prompt to specify the alphabetic hostname tie-breaker.
  4. Change correlation drift from change_correlation_rules.md: env.py ignored the 72-hour window and treated `completed` (bonus 0) tickets as no match. Rewrote step 6 to enforce the 72h window before 2025-03-15 08:00:00 and accept any of {rolled_back, failed, in_progress, completed}, picking the highest bonus with most-recent scheduled_time tie-break, matching the markdown spec.
- Blockers: none.
