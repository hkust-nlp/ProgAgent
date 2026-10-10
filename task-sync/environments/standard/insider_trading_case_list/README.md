## Task Topic

Detect potential insider trading by comparing employee trade pre-clearance logs, corporate event calendars, sensitive data access records, and unusual options volume alerts to generate a prioritized investigation case list for the compliance team.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Critical data is split across database tools (employees, pre-clearance logs, corporate events, access logs, options alerts) and workspace files (broker confirmations, compliance memos, employee holdings, market snapshots). Broker confirmations reveal unreported trades not present in the tool-accessible pre-clearance system, while compliance memos identify repeat offenders whose scores must be multiplied. The scoring parameters and output format live in workspace config files (YAML and JSON).

- **Multi-Hop Reasoning**: The analysis requires dependency chains of length ≥ 3. For example: query pre-clearance logs (Tool) → match against corporate events by ticker and date window (Tool) → check employee data access logs for MNPI access before the event (Tool) → read scoring rules from config (File) → apply repeat-offender multiplier from policy (File) → compute final risk score. Unreported trade detection requires: read broker confirmations (File) → compare against executed pre-clearance logs (Tool) → flag mismatches.

- **Conditional Constraints**: Case eligibility depends on multiple intersecting business rules: blackout window violations require date arithmetic across two tables, MNPI access requires a lookback window check, options correlation requires an absolute-difference window, and the repeat-offender multiplier conditionally amplifies the total score. Thresholds and multipliers are defined in workspace configuration files rather than the prompt.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (csv_file_valid, csv_columns_correct, case_count_correct, sort_order_correct, risk_scores_correct, flags_correct, response_summary)
- Source-access during solve: clean. Solver was written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No escalation to read `env.py`/`data.py` was needed.
- Structural integrity: passed. Top-level contains only `README.md` and `v0..v3/`. Each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (rows ×1/2/4/8 = 80/160/320/640; files +0/N/2N/3N with N=8 = 8/16/24/32).
- Issues found: none. No fixes were applied to `v0/`.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from every `v_n/`; removed `/tmp/solve_insider_trading_case_list.py`.
