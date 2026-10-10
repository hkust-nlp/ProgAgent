## Task Topic

Orchestrate a canary release by analyzing real-time application performance metrics, synthetic transaction success rates, user session error logs, and feature flag distributions to produce a verified promotion or rollback decision report.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task uses the following structural dimensions:

- **Conditional Constraints**: Per-service decisions depend on tier-specific thresholds (critical/standard/experimental) read from workspace configuration files, with two override conditions (critical-severity errors and manual rollback flags) that supersede score-based decisions.
- **Information Scattering**: Baseline latency data lives in workspace CSV files, rollout targets in YAML files, override flags in TXT deployment notes, and scoring weights/thresholds in a YAML policy file — while real-time metrics, synthetic transactions, error logs, and feature flag statuses are only accessible via tool calls to the deployment system.
- **Multi-Hop Reasoning**: The agent must chain: list canary services → retrieve tier from service details → load tier-specific thresholds from config → query multiple metric types per service → cross-reference baselines from workspace files → compute scores → check error logs for critical entries → check deployment notes for manual overrides → apply decision rules → aggregate into overall decision.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (report_structure 10, service_decisions 25, score_accuracy 20, summary_file 15, response_overall_decision 10, response_rollback_list 10, override_handling 10).
- Solver source-access: clean black-box. Solver was authored from `v3/prompt.md` plus `Task_Env.get_assistant_tools()` only; `env.py`/`data.py` were not opened during Section 2.
- Issues found and fixes: none. Structural integrity, byte-for-byte env.py/prompt.md match across v0..v3, SCALE-only diff in data.py, and prompt/step alignment all verified clean.
