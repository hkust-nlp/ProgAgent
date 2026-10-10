## Task Topic

Analyze historical bid patterns, current market material price indices, competing vendor financial stability reports, and internal budget forecasts to produce a risk-adjusted cost benchmark for an upcoming public IT procurement.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 40             | 12                  |
| v1      | 80             | 24                  |
| v2      | 160            | 36                  |
| v3      | 320            | 48                  |

**Structural dimensions used:**

- **Information Scattering**: Vendor operational risk ratings exist only in workspace dossier files (.md), past delivery scores only in performance data files (.csv), and forecast adjustment factors only in a market forecast config file (.json). Financial ratios, historical bids, and price indices are only accessible via tool calls. Solving the task requires cross-referencing all of these sources.
- **Multi-Hop Reasoning**: The dependency chain is: list vendors → query financials → apply eligibility filters → read workspace dossiers and performance files for risk inputs → query historical bids → query price indices → read forecast adjustments → compute composite risk scores → derive risk premiums → calculate risk-adjusted costs → compute category medians against budget allocations.
- **Conditional Constraints**: Vendor eligibility depends on simultaneously satisfying five criteria (active status, credit score, current ratio, debt-to-asset ratio, years in business) drawn from both tool data and a workspace config file.
- **Deliverable Constraints**: Strict output formatting including exact column order, sort keys with tie-breakers, decimal precision (2 for monetary, 4 for factors/scores), required response patterns for total cost and risk rating.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (benchmark_report_structure, benchmark_report_values, benchmark_report_sorting, category_summary_structure, category_summary_values, response_total_cost, response_risk_rating)
- Source-access: clean — solver used only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Structural integrity: top-level and v_n directories contained only the required files; `env.py` and `prompt.md` were byte-identical across v0-v3; only `SCALE` differed in `data.py`.
- Issues found: none. No fixes required.
- Blockers: none.
