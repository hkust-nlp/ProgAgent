## Task Topic

Flag high-risk claims for potential fraud. Correlate employee injury reports, medical treatment histories, witness statements, and claimant employment records to identify inconsistent narratives or patterns, generating a prioritized investigation list for the special investigations unit.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 60            | 10                  |
| v1      | 120           | 20                  |
| v2      | 240           | 30                  |
| v3      | 480           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10.

### Structural Dimensions

- **Information Scattering**: Fraud indicators require combining data from the SQL database (claim details, treatments, witness consistency ratings, employee records) with workspace files (adjuster credibility scores in JSON dossiers, provider billing anomaly scores in CSV audit reports, witness reliability ratings in TXT assessment files). No single source is sufficient.
- **Multi-Hop Reasoning**: Dependency chains of length ≥ 3 arise naturally — e.g., list claims → get medical treatments → look up provider ID in workspace audit CSV → apply anomaly threshold from YAML scoring rules → contribute to composite risk score.
- **Conditional Constraints**: Eight distinct fraud indicators each fire based on configurable thresholds (filing delay days, amount ceilings per injury type, anomaly score cutoffs, consistency/reliability thresholds, lookback windows, tenure thresholds, credibility floors), all defined in workspace config files rather than hard-coded.

## Harness Report

- **v3 reward:** 1.0 (100/100)
- **Eval criteria count:** 6 (investigation_list_format, recall_flagged_claims, risk_scores_accuracy, ranking_order, risk_summary_json, risk_level_accuracy)
- **Source-access:** Section 2 escalated to step 6 (read `v3/env.py` once to disambiguate two indicators after re-reading the prompt did not resolve the gap).
- **Issues and fixes:**
  - `prompt.md` said "evaluate every open claim" but the next sentence (and the env's ground-truth scorer) processes the entire claim set regardless of status. Replaced "every open claim" with "every claim" in `v0/prompt.md` and re-propagated byte-identically to v1/v2/v3.
- **Solver-side notes (no env/prompt changes required):** The prompt's "more than one claim within the lookback window" for `repeat_claimant` is interpreted by `step` as "any pair of injury dates within `lookback_months` of each other across the employee's full history", and `new_employee` requires non-negative tenure. These match the prompt's wording; no fix needed.
- **Blockers:** None.
