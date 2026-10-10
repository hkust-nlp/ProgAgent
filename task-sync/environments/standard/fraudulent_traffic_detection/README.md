## Task Topic

Identify fraudulent international call traffic by analyzing interconnect CDR patterns, destination country risk scores, real-time traffic volume spikes against historical baselines, and known fraudulent number databases, outputting an alert report with recommended route blocks.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Current traffic volumes are spread across multiple workspace snapshot files (JSON), while historical baselines, CDR records, country risk scores, and fraud number status are only accessible via tool calls. Detection thresholds, severity classification rules, and blocking policy are in separate workspace config files (YAML, JSON, Markdown). Solving the task requires reading all these sources and cross-referencing them.

- **Multi-Hop Reasoning**: The dependency chain is: read traffic snapshots → aggregate volumes per route/country → query historical baselines (tool) → compute spike ratios → query CDRs for spiking routes (tool, paginated) → check each callee against fraud DB (tool) → get country risk scores (tool) → apply classification rules (workspace config) → determine actions (workspace policy) → produce deliverables. This is a chain of length ≥ 5.

- **Conditional Constraints**: Alert severity classification depends on layered business rules combining spike ratio thresholds, country risk score minimums, and fraud call count minimums, with different logical operators (ALL vs ANY) at different severity tiers. The action mapping and report inclusion criteria add further conditional logic.

- **Deliverable Constraints**: The alert report CSV requires exact column order, specific numeric formatting (spike_ratio to 2 decimal places), sequential zero-padded alert IDs (ALT-NNN), and multi-key sorting (severity priority, then spike_ratio descending). The blocks JSON requires specific field names and the same ordering. The response must contain exact numeric counts.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (csv_format=10, route_identification=20, spike_ratio_accuracy=15, fraud_count_accuracy=15, severity_accuracy=15, blocks_report=15, response_summary=10).
- Section 1 structural integrity: passed. Top-level contains only README.md and v0..v3; each version contains only data.py/env.py/prompt.md; env.py and prompt.md are byte-identical across versions; data.py differs only in SCALE.
- Section 2 solvability: solver placed at /tmp/solve_fraudulent_traffic_detection.py used only v3/prompt.md and Task_Env.get_assistant_tools(); achieved reward 1.0 on first run. No escalation to env.py was required.
- Section 3 env quality: step() criteria all map to prompt requirements (CSV columns, spike-ratio precision, fraud counting per-occurrence, severity rules from classification config, blocks file contents, summary counts). Ground truth is recomputed from data.db and workspace each call, so criteria are scale-invariant.
- Section 4 prompt quality: no title/bold headers, deliverables described in prose, exact column/field names specified, no tool names or source filenames leaked, scale-invariant wording ("all available traffic snapshot files", "every such pair").
- Issues found and fixes: none. No edits needed in any version.
- Cleanup: removed data.db, workspace/, and __pycache__/ from all version directories; removed tmp solver.

