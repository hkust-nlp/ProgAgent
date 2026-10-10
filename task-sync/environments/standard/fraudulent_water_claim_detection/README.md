## Task Topic

Identify potentially fraudulent water damage claims by cross-referencing claimant policy details, historical weather data for the incident address, contractor repair estimates, and prior claims history to flag inconsistencies, outputting a prioritized investigation list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

The scaling workspace files are per-claim contractor estimate JSON documents stored in the `estimates/` subdirectory. Fixed (non-scaling) workspace files include the fraud detection configuration (YAML), the contractor registry (CSV), and the flood zone map (CSV).

**Structural dimensions used:**

- **Conditional Constraints**: Fraud indicators depend on thresholds and rules (precipitation/wind minimums, excess percentage caps, lookback windows, filing deadlines) defined in the workspace YAML configuration, applied across policy, claim, weather, and contractor data.
- **Information Scattering**: Claim and policy details come from tool calls; contractor license status lives in a workspace CSV; repair estimates are in per-claim JSON files; scoring weights and thresholds are in a YAML config. No single source is sufficient.
- **Multi-Hop Reasoning**: Each claim requires a chain of at least `list_claims → get_claim_details → get_policy_details → get_weather_data → read estimate file → cross-reference contractor registry → get_prior_claims → compute score`, a dependency chain of length ≥ 4.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (csv_format, claim_coverage, fraud_scores, flags_accuracy, sort_order, priority_levels, response_summary).
- Source-access: clean Section 2 pass after solver iteration. `env.py` was opened once at step-6 escalation to reconcile two solver bugs (see below). No edits were required to `prompt.md`, `env.py`, or `data.py`.
- Issues found: none in the env. Solver bugs only — initial solver used `relativedelta(months=...)` and the wrong prior-claim date field, which is a solver implementation choice, not an env defect. The env's repeat-claimant cutoff uses `30 * lookback_months` days against the `prior_claim_date` column, both of which are consistent between `step()` and the documented behavior. Once the solver was aligned, all criteria passed.
- Structural integrity: top-level dir contains only `README.md` and `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Blockers: none.
