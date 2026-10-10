## Task Topic

Optimize short-term cash reserves by forecasting weekly outflows. Synthesize payroll schedules, vendor payment calendars, upcoming tax liabilities, and historical expense variance to project daily cash positions, producing a weekly funding recommendation for the operating account.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 8                   |
| v1      | 120            | 16                  |
| v2      | 240            | 24                  |
| v3      | 480            | 32                  |

Scaling ratios: rows follow 1x / 2x / 4x / 8x; workspace files follow base / base+N / base+2N / base+3N where N = 8 (base).

### Structural Dimensions

- **Information Scattering**: Outflow data (payroll, vendor, tax schedules) lives exclusively in the database behind tool calls, while inflow history, variance-adjustment factors, day-of-week weights, and cash-management policy thresholds live exclusively in workspace files. Both sources are mandatory to project daily cash positions.
- **Multi-Hop Reasoning**: Computing each day's operating expense requires a chain of length 4: retrieve expense history per department (tool) -> compute per-category daily averages -> read variance-adjustment factors (workspace JSON) -> apply day-of-week weight (workspace TXT). The funding recommendation adds another hop: compare projected balances against policy thresholds (workspace YAML) -> select funding tier.
- **Conditional Constraints**: Payroll eligibility depends on pay frequency and schedule fields (weekly vs. biweekly with anchor-date modular arithmetic vs. monthly day-of-month match). Vendor inclusion depends on active status and frequency-specific date logic (quarterly vendors pay only in Q1 months). Funding-tier selection is conditioned on the recommended amount.

## Harness Report

- **v3 reward:** 1.0 (100/100)
- **Eval criteria:** 7 (`projections_structure`, `payroll_accuracy`, `vendor_accuracy`, `tax_accuracy`, `operating_expense_accuracy`, `closing_balance_accuracy`, `funding_recommendation`)
- **Source-access:** clean (only `v3/prompt.md` read; tool surface discovered via `Task_Env(...).get_assistant_tools()`; no step-6 escalation needed)
- **Section 1 (Structural Integrity):** Pass. Top-level contains exactly `README.md` + `v0..v3`; each version has only `data.py / env.py / prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (60/120/240/480 rows; 8/16/24/32 files).
- **Section 2 (Solvability at v3):** Pass. Solver at `/tmp/solve_weekly_cash_position_forecast.py` constructed `Task_Env`, fetched account balance, payroll, vendors, taxes, and expense history through the tool surface, parsed the workspace config files (forecast_parameters.txt, cash_policy.yaml, variance_adjustments.json, weekly_inflows_*.csv), produced `daily_projections.csv` and `funding_recommendation.json` under `workspace/`, and submitted via `env.step` for reward 1.0.
- **Section 3/4 (Quality):** Prompt has no headings, bold labels, lists, code, tool names, source filenames, or absolute counts; deliverable filenames and column orderings are explicit; scale-invariant phrasing throughout. Step rewarded all 7 criteria with no partial-credit drift.
- **Issues found / fixes:** None. Solver iteration only required adapting to tool return type (JSON-encoded strings) on the solver side; no source changes needed.
- **Blockers:** None.

