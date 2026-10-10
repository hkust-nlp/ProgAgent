## Task Topic

Validate contracted sponsorship asset delivery during events. Correlate sponsor entitlement agreements, broadcast camera angle logs, in-stadium digital signage schedules, and social media monitoring feeds to confirm delivered impressions, outputting a compliance report detailing any shortfalls for billing adjustments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Structural dimensions used:

- **Information Scattering**: Delivery data is split across the database (broadcast logs, signage schedules, social media feeds accessed via tools) and workspace files (venue visibility factors in JSON reports, social media verification status in CSV batches, platform weights in a CSV, and compliance thresholds in YAML). No single source contains enough to compute the compliance result alone.
- **Multi-Hop Reasoning**: Social media impressions require a chain of length 4: retrieve feed entries via tool → look up platform weight from CSV → look up verification status from batch CSV files → apply verification policy factor. Signage impressions require: retrieve schedule records via tool → identify venue from event → look up visibility factor from venue report JSON → multiply. Billing adjustments add another hop: compute shortfall percentage → look up band multiplier → apply penalty rate.
- **Conditional Constraints**: Compliance thresholds vary by sponsor tier (platinum 95%, gold 90%, silver 85%, bronze 80%). Billing adjustment multipliers depend on shortfall percentage bands. Unverified social media posts count at 50% of their weighted value.

## Harness Report

- v3 reward: 1.0 (100/100 across 6 criteria)
- Eval criteria (6): report_file_structure (15), report_row_count (10), delivered_impressions_accuracy (25), compliance_status_accuracy (15), billing_adjustment_accuracy (20), response_summary_stats (15)
- Source-access escalation: triggered Section 2 step 6 (opened v3/env.py) after solver matched prompt but reward stayed at 0.933.
- Issue 1 (step vs prompt mismatch on billing): prompt states "If the entitlement is compliant or has no shortfall, the billing adjustment is zero," but `_compute_ground_truth` and `verify` always applied the band-multiplier formula even for compliant entitlements with delivered<contracted. Fix: zero out `billing_adjustment` whenever `compliant or shortfall_impressions == 0` in both `_compute_ground_truth` and `verify`. Edited in v0/env.py and re-propagated to v1/v2/v3.
- Issue 2 (response summary brittle to float drift): criterion 6 required the literal `f"{total_billing:.2f}"` substring in the agent action, but per-row rounded billing sums drift by ~$0.01 vs the ground-truth aggregate, rejecting otherwise correct responses. Fix: parse numbers from the action with regex and accept any value within $1.0 of the ground-truth total. Edited in v0/env.py and re-propagated.
- Structural cleanup: removed a stray `v0/__pycache__/`. Final `diff v0/{env.py,prompt.md} v_n/...` is empty for n=1,2,3; only `data.py` differs in the SCALE block.
- Blockers: none.
