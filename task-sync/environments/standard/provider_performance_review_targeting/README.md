## Task Topic

Identify high-cost, low-satisfaction providers by analyzing claim adjudication records, member satisfaction survey scores, in-network fee schedules, and referral patterns, producing a targeted review list for contract renegotiation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Scaling ratios: rows grow at 1×/2×/4×/8×; workspace files grow at N/N+N/N+2N/N+3N where N=8.

### Structural Dimensions

- **Information Scattering**: Cost calculation requires joining tool-provided claim data (paid amounts, service codes) with workspace CSV files (cost adjustment factors), workspace JSON (tier multipliers), and workspace CSV (specialty benchmarks). Satisfaction scoring joins tool-provided overall ratings with workspace JSON dimension scores and workspace YAML weights. Referral leakage joins tool-provided in-network flags with workspace TXT urgency annotations.

- **Multi-Hop Reasoning**: The cost ratio computation follows a chain of length 4+: list providers (tool) → retrieve claims per provider (tool) → look up base fee rate per service code (tool) → read tier multiplier (workspace JSON) and cost adjustment factor (workspace CSV) → compute expected cost → compare with specialty benchmark (workspace CSV) → determine high-cost flag. Satisfaction requires a similar chain through tool surveys, workspace dimension scores, and workspace weights.

- **Conditional Constraints**: Provider eligibility depends on minimum approved claim count, exclusion list membership, and the simultaneous presence of both high-cost and low-satisfaction conditions. Referral leakage excludes high-urgency referrals from the denominator.

- **Deliverable Constraints**: Output CSV has prescribed column names, column order, decimal precision (4 places for ratios/scores, 2 for satisfaction), boolean formatting, and a two-key sort (composite score descending, provider ID ascending as tiebreaker).

## Harness Report

- v3 reward: 1.0 (100/100) on first solver attempt.
- Eval criteria: 7 (file_structure 10, provider_set 25, cost_ratios 15, satisfaction_scores 15, leakage_rates 10, composite_and_sort 15, high_leakage_flag 10).
- Source-access: clean — solver was written using only `v3/prompt.md` and `Task_Env(...).get_assistant_tools()`. `env.py` was not consulted to debug the solver; it was only inspected for Section 3 quality review after reward 1.0.
- Section 1 issue: a stale `v0/__pycache__/` directory was present at start. Fixed by removing it during final cleanup.
- Section 2 issues: none — solver achieved reward 1.0 on the first run.
- Section 3 / 4 issues: none requiring fixes. `step` derives ground truth from data.db + workspace and matches all prompt requirements. The summary text response (top-3 listing) is not separately scored, but the same information is present and validated in the required CSV, which all v0–v3 versions evaluate identically by byte-for-byte invariant.
- Blockers: none.
