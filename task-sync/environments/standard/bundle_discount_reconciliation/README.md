## Task Topic

Resolve billing discrepancies for bundled services by reconciling customer subscription plans, promotional discount eligibility logs, network usage records, and third-party content provider invoices, producing an adjustment report with root cause categorization.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

Structural dimensions used:

- **Information Scattering**: Actual billed amounts live in workspace batch files (CSV/JSON/TXT/YAML), while subscription details, usage records, discount eligibility, and provider invoices are only accessible through tools. Pricing tiers, bundle discount rules, and promotional offer details are in workspace configuration files. No single source contains enough information to identify or classify a discrepancy.
- **Multi-Hop Reasoning**: Identifying each discrepancy requires a chain of at least three steps: retrieve the customer's subscription tier and bundle type via tool → look up the corresponding rates and discount percentages from workspace config files → compute expected charges → compare against actual billing from workspace batch files → classify the root cause by isolating which component diverged.
- **Conditional Constraints**: Root cause classification depends on ordered evaluation of five conditions across different billing components, with the first matching condition taking priority. Promotional discount eligibility depends on date-window overlap and active/expired status.

## Harness Report

- **v3 reward:** 1.0 (100/100). Solver succeeded as a clean black-box run — only `v3/prompt.md` and `Task_Env(...).get_assistant_tools()` were consulted; `env.py`, `data.py`, `README.md`, and v0/v1/v2 sources were never read for solving. No step-6 escalation triggered.
- **Eval criteria:** 5 — `report_format` (15), `discrepancy_detection` (25), `root_cause_accuracy` (25), `adjustment_amounts` (20), `false_positive_rate` (15); total max 100. Counts/weights are byte-for-byte identical across v0..v3.
- **Section 1 (structural integrity):** Pass. Top-level holds only `README.md` + `v0..v3/`; each `v_n/` holds only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` byte-for-byte identical across versions; only the `SCALE` block in `data.py` differs (50/10, 100/20, 200/30, 400/40 — matches the 1/2/4/8 row and base+0/N/2N/3N file ratios).
- **Section 2 (solvability):** Solver reached reward 1.0; no env.py / prompt.md edits required.
- **Section 3/4 observations (non-blocking):** (a) `step()` does not parse the agent's final response, so the prompt's requirement to state total count, net adjustment, and per-cause breakdown in the response is unscored — only the CSV is checked. (b) `step()` does not verify the prompt-mandated CSV sort order (`customer_id`, then `billing_period`). (c) Promo-window check in `_compute_ground_truth` uses any-overlap (`eligible_from <= period-28 AND eligible_to >= period-01`); my solver used "first-of-month inside window" — both produced identical results on injected discrepancies, but the prompt wording "covers the billing period" is mildly ambiguous. None of these affected reward; left as-is to preserve the byte-for-byte invariant since v3 already passes at 1.0.
- **Blockers:** None.
