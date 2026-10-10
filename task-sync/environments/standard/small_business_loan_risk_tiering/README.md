## Task Topic

Assess small business loan applications by cross-referencing applicant bank transaction histories, industry-specific default rates, real-time collateral asset valuations, and existing lender exposure limits to generate a prioritized approval queue with risk-tiered credit limits.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 10                  |
| v1      | 60            | 20                  |
| v2      | 120           | 30                  |
| v3      | 240           | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Applicant financial profiles (credit score, revenue, debt, years in business) live in workspace JSON files, while application details, bank transactions, collateral valuations, and lender exposure data are only accessible via tool calls. Both sources are required to compute risk scores and eligibility.
- **Multi-Hop Reasoning**: Each application requires a dependency chain of length ≥ 4: list pending applications → get application details → read financial profile file → get transaction history → get collateral assets → get each asset's valuation → check lender exposure → read industry default rates → compute composite score → determine tier and credit limit.
- **Conditional Constraints**: Eligibility depends on five thresholds spanning three data sources (credit score from workspace files, DTI computed from workspace data, collateral coverage from tool calls, years in business from workspace, lender capacity from tool calls). Thresholds are defined in workspace configuration files.
- **Deliverable Constraints**: Output CSV has a fixed 9-column schema with exact column order, two-decimal formatting for numeric fields, specific sort order with tie-breaking rules, and prescribed values for decision/denial_reason fields.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 7 (output_file_format=10, correct_applications=15, eligibility_decisions=20, risk_scores=20, risk_tiers=10, credit_limits=15, priority_order=10).
- Source-access: escalated to step 6 once. After an honest re-read of `prompt.md` and `risk_config.yaml`, the natural value to write into the `risk_tier` column was either the tier key (`tier_1`) or the human-readable label (`Low Risk`), both of which appear in `risk_config.yaml`. `prompt.md` does not prescribe one over the other. The solver wrote labels and step rejected all 40, which is a step/prompt ambiguity bug rather than a solver bug.
- Issue + fix: `step()`'s risk-tier check accepted only the internal key (`tier_1`..`tier_4`). Fixed in `v0/env.py` by also accepting any tier label defined under `risk_config.yaml`'s `risk_tiers[*].label`. Re-propagated byte-identically to v1/v2/v3. Re-ran solver on v3 and obtained reward 1.0.
- Blockers: none.
