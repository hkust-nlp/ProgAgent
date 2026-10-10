## Task Topic

Analyze clinical trial safety by correlating patient-reported adverse events, concomitant medication logs, pharmacokinetic sampling data, and trial protocol phase rules to produce a weekly report flagging participant cohorts for potential unanticipated drug-drug interaction signals.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 8                   |
| v1      | 120           | 16                  |
| v2      | 240           | 24                  |
| v3      | 480           | 32                  |

Structural dimensions used:

- **Information Scattering**: Critical data is split across database tools (participant medications, adverse events, PK concentrations) and workspace files (DDI reference pairs, phase-specific thresholds, PK reference ranges, dose adjustment records). Neither source alone is sufficient to determine flagged entries.
- **Multi-Hop Reasoning**: Flagging requires a dependency chain of length >= 4: retrieve participant medications via tool, cross-reference with DDI pairs from workspace CSV, apply dose adjustments from site report files to compute effective doses, then check AE severity (tool) against phase thresholds (workspace YAML) and PK concentrations (tool) against reference ranges (workspace JSON) with phase-specific multipliers.
- **Conditional Constraints**: Eligibility depends on multiple interacting rules: DDI pair must be active (both drugs taken in the week with effective dose >= minimum), risk level may be elevated by dose adjustments, and flagging requires either AE severity or PK deviation to exceed phase-dependent thresholds.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 7 (`report_file_structure` 10, `flagged_entries_accuracy` 25, `risk_and_reason_accuracy` 15, `pk_deviation_accuracy` 15, `cohort_flags_structure` 10, `cohort_flag_accuracy` 15, `response_summary` 10).
- Solver source-access: clean black-box. Solver authored using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` or `data.py` was needed. `reward == 1.0` on first run.
- Issues found and fixes: stale `v1/__pycache__` removed before structural diff; no edits required to `v0/` (env.py, prompt.md, data.py, prompt.md byte-identical across v1-v3, only SCALE differs). Section 3 and Section 4 quality checks passed without modification.

