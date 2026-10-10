## Task Topic

Validate driver incentive payouts for peak-hour rides. Cross-reference trip completion logs, surge pricing zone timestamps, driver online session records, and promotional campaign terms to flag ineligible claims, outputting an adjusted payout report with discrepancy reasons.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Structural dimensions used by this task:

- **Conditional Constraints**: Eligibility depends on multiple interacting business rules across campaigns, trips, sessions, and driver ratings. Thresholds (minimum rating, minimum trips, minimum online hours, zone tier eligibility, peak-hours-only flag, per-driver payout cap) are defined in campaign records and workspace configuration files.
- **Information Scattering**: Driver daily ratings live exclusively in workspace CSV log files, zone tier mappings in a workspace CSV, peak-hour definitions in a workspace JSON config, and payout calculation rules in a workspace YAML policy file. Trip details, surge records, session data, and campaign terms are only accessible through tool calls. Solving the task requires both sources.
- **Multi-Hop Reasoning**: Validating a single claim requires a chain of at least 4 hops: retrieve claim -> fetch trip details -> look up zone tier from workspace -> fetch surge records for that zone/date -> fetch campaign info -> fetch driver sessions -> read daily logs for driver rating -> compute adjusted amount with tier multiplier and surge multiplier -> enforce per-driver cap across all approved claims for that campaign.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (`report_file_exists` 10, `correct_columns` 10, `correct_row_count` 10, `eligibility_accuracy` 25, `adjusted_amount_accuracy` 25, `discrepancy_reasons_accuracy` 10, `action_summary` 10)
- Source-access: clean — solved using only `v3/prompt.md` + `Task_Env(...).get_assistant_tools()`; no escalation to `env.py`/`data.py` was needed.
- Structural integrity: passed. Top-level has only `README.md` + `v0..v3/`. Each `v_n/` contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; only the `SCALE` block in `data.py` differs (rows 100/200/400/800, files 10/20/30/40).
- Issues found: none. Prompt-step alignment is complete, no hidden criteria, ground truth is derived dynamically from DB + workspace, and no scale-dependent constants are present in `step`. Prompt formatting is prose-only with no tool names, no bullet lists for deliverables, explicit reason codes, and scale-invariant wording.
- Blockers: none.
