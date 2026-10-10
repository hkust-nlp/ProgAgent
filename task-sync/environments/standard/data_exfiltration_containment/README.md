## Task Topic

Analyze a suspected data exfiltration event by correlating firewall egress logs, endpoint file access audit trails, user authentication timestamps, and data classification tags to identify the scope of compromised files and produce a containment report with affected asset lists.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task uses the following structural dimensions:

- **Information Scattering**: Task-critical fields are split across multiple sources. Malicious IP indicators live exclusively in workspace threat intelligence feed files (JSON), while firewall connection logs, file access audit trails, and authentication events are only accessible via tool calls to the database. Policy thresholds (off-hours window, bytes threshold, failed-auth limit, suspicious actions) reside in a YAML config file, the role-to-clearance mapping in a JSON file, and department risk scores in a CSV file. Solving the task requires reading all of these and cross-referencing them.

- **Conditional Constraints**: Identifying compromised users requires satisfying multiple conjunctive conditions spanning different tables and workspace files: (1) firewall egress to a malicious IP (from threat intel feeds minus the safe-destinations whitelist) with bytes above threshold during off-hours, AND (2) failed authentication count meeting or exceeding a policy-defined threshold. File access events are then filtered by suspicious action type and off-hours timing, with PUBLIC-classified files excluded.

- **Multi-Hop Reasoning**: The dependency chain is at least four hops deep: threat intel feeds → filtered malicious IPs → firewall log query → candidate users → auth event verification → confirmed compromised users → file access query → file metadata lookup → classification/clearance comparison → severity assignment → sorted containment report.

- **Deliverable Constraints**: Output format is tightly specified: the CSV must have exactly 13 named columns in a fixed order, rows sorted by a four-key composite (severity order, department risk score descending, user_id ascending, file_id ascending with timestamp tiebreaker), and the JSON summary must contain four keys with sorted lists and integer counts. The final response must include three exact-format summary lines.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 9 (report_format, report_rows, report_sort, assets_users, assets_files, assets_endpoints, response_users, response_total_files, response_severity)
- Source access: clean — solver was written using only `v3/prompt.md` and `Task_Env(...).get_assistant_tools()` plus runtime artifacts (`data.db`, `workspace/`); no escalation to `env.py`/`data.py` was needed.
- Issues found: none. Structural integrity passed (v0/v1/v2/v3 contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; only the `SCALE` block in `data.py` differs). Solver produced reward 1.0 on first attempt.
- Fixes applied: none.
