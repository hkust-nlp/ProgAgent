## Task Topic

Flag tax-inefficient rebalancing actions by cross-referencing proposed trades with lot-level cost basis records, client tax status, jurisdictional wash sale rules, and year-to-date capital gain reports to output an optimized, tax-aware execution schedule.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 8                   |
| v1      | 120           | 16                  |
| v2      | 240           | 24                  |
| v3      | 480           | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Proposed trades live exclusively in workspace CSV files, while client details, lot-level cost basis, YTD capital gains, and transaction history are only accessible through tool calls. Tax rates, wash sale rules, rebalancing policy thresholds, and filing-status gain-threshold multipliers are spread across four separate configuration files (JSON, YAML, and Markdown).
- **Multi-Hop Reasoning**: Determining the correct flag for a single trade requires a dependency chain of length >= 3. For example, to evaluate a sell trade the agent must read the trade from a CSV, retrieve the client's filing status via a tool call, look up the gain-threshold multiplier from a Markdown config file, query YTD capital gains via another tool call, fetch lot-level cost basis from a third tool call, obtain the current security price from a fourth tool call, read tax rates from a JSON config, and finally compute the combined tax impact and flag.
- **Conditional Constraints**: Flag assignment depends on multi-column business rules spanning the client table (tax_status, filing_status, jurisdiction), lot records (purchase_date, cost_basis), capital gains (realized_gain, holding_period, sale_date), and transaction history (txn_type, txn_date), with thresholds and multipliers drawn from workspace configuration files.

## Harness Report

- v3 reward: 1.0 (total_score 100/100)
- Number of eval criteria: 6 (schedule_file_format, flag_accuracy, lot_recommendation_accuracy, tax_impact_accuracy, execution_date_accuracy, response_summary)
- Source-access path: clean (solver passed using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no step-6 escalation needed)
- Section 1 structural integrity: passed; `env.py` and `prompt.md` are byte-identical across v0..v3, `data.py` differs only in the `SCALE` block (rows 60/120/240/480, files 8/16/24/32 — ratios 1/2/4/8 and +0/N/2N/3N with N=8)
- Section 3 prompt-step alignment: every scoring criterion maps to an explicit prompt deliverable (CSV format, flag selection, lot order, rounded tax impact, execution date, summary labels); ground truth is recomputed from `data.db`/workspace per call, so it remains scale-invariant. Tolerances (`max($1, 2%)` on tax, summary integer regex) are reasonable and not over-strict.
- Section 4 prompt quality: prose-only, no headings/lists, no source-data filenames or tool names leaked, no absolute counts; only deliverable filename (`execution_schedule.csv`) and column/label names are spelled out, as required.
- Issues found and fixes: none. No edits to `v0/` were required.
- Blockers: none.
