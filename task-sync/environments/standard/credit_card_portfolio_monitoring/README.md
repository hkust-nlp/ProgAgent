## Task Topic

Identify high-risk credit card accounts by analyzing transaction patterns for cash advances, recent credit bureau score changes, minimum payment history, and macroeconomic delinquency trends to produce a list for proactive credit limit reduction.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=8.

Structural dimensions used:

- **Conditional Constraints**: Accounts must be active and not enrolled in a hardship program; risk factor triggering depends on configured thresholds; tier-based multipliers modify raw scores; risk level boundaries determine reduction rates.
- **Deliverable Constraints**: Output CSV requires exact column order, risk_score rounded to two decimal places, integer limits, descending score sort with account_id tiebreaker, and a specific primary risk factor selection rule.
- **Information Scattering**: Scoring weights, thresholds, and DTI bonuses live in a YAML config; tier multipliers and reduction rates in JSON; floor/rounding rules in a Markdown policy; regional adjustments in a separate JSON; debt-to-income ratios and hardship flags in scalable CSV supplements; all account, transaction, credit bureau, payment, and delinquency data are accessible only through tools.
- **Multi-Hop Reasoning**: Tool (list accounts) → File (risk thresholds) → Tool (get transactions) → compute cash advance ratio → Tool (credit bureau) → compute decline → Tool (payment history) → compute streak → Tool (regional delinquency) → File (regional adjustments) → apply formula → File (supplement CSVs) → DTI bonus + hardship filter → File (tier config) → multiply → File (policy) → compute limit → write output.

## Harness Report

- v3 final reward: 1.0 (100/100).
- Eval criteria: 9 (file_exists 10, correct_columns 10, correct_account_set 15, correct_risk_scores 15, correct_risk_levels 10, correct_recommended_limits 10, correct_primary_factors 10, correct_sorting 10, response_summary 10).
- Source-access: clean run for sections 1, 4, 5; section 2 escalated to step 6.2 (read v3/env.py) to disambiguate after a 0.89 first-pass reward.
- Issue 1: DTI bonus boundary handling. The prompt's "tiered schedule" wording does not specify whether the moderate/high thresholds use strict greater-than or greater-or-equal. env.py applies strict `>`, so a solver that read `>=` from "moderate_threshold/high_threshold" would diverge on edge accounts. Fix: this is acceptable as written (env is internally consistent — every other factor also uses strict `>`); no source change needed, but solvers must follow env's `>` convention. Documented here so future evaluations are aware of the ambiguity.
- Issue 2: Credit-score baseline picked via `timedelta(days=eval_months*30)` (180 days) rather than calendar months. With monthly bureau reports the nearest-record selection is identical in practice; no fix needed.
- Issue 3: Cash-advance ratio uses all transactions in env, while prompt mentions "evaluation period". Generated transactions per account already span ~6 months, so the two interpretations agree on this dataset; no fix needed.
- No env.py / prompt.md / data.py edits were required; byte-for-byte invariance across v0..v3 preserved.
- Blockers: none.
