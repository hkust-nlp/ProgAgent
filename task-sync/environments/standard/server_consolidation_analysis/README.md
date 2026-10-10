## Task Topic

Identify underutilized servers for consolidation by analyzing 90-day CPU utilization logs, power consumption meters, virtualization host capacity matrices, and active service dependency maps, outputting a decommissioning schedule with migration priorities.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Server rated power capacity is only available in workspace CSV files, while actual CPU utilization and power consumption readings are only accessible through tool queries. Service-to-server mappings come from tools, but service-to-service dependency graphs live in workspace JSON files. The consolidation thresholds and scoring parameters reside in a YAML configuration file. No single source contains enough information to complete the task.

- **Multi-Hop Reasoning**: The solution requires a dependency chain of length ≥ 3: list servers via tool → get CPU stats via tool → cross-reference rated power from workspace spec files → apply thresholds from workspace policy YAML → look up services via tool → count inbound dependencies from workspace dependency JSONs → compute priority score using policy weights → assign phase and calculate savings using datacenter config JSON.

- **Conditional Constraints**: A server qualifies as underutilized only when two conditions are jointly satisfied (avg CPU below threshold AND avg power below rated × factor), and only for active-status servers. Migration priority scoring depends on service criticality tiers, dependency counts, and VM host status, each contributing different weights.

## Harness Report

- v3 reward: 1.0
- Number of eval criteria: 6 (server_identification 20, utilization_values 15, priority_scores 20, annual_savings 15, format_and_sorting 15, response_summary 15)
- Source-access: clean — solver completed using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. Step-6 escalation to read `env.py` was used briefly to confirm the format-checking logic after a partial-credit run; no edits to `env.py` or `prompt.md` were needed.
- Issues found: none. Structural integrity (Section 1) verified via `diff` — `env.py` and `prompt.md` are byte-identical across v0..v3, and `data.py` differs only in the `SCALE` block. Prompt-step alignment, scale invariance, and prompt formatting (no headings, no bullets, no tool names, scale-invariant wording) all pass.
- Blockers: none.
