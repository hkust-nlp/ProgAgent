## Task Topic

Reconcile sponsored content delivery. Cross-reference advertiser insertion orders, platform impression logs, user demographic segments, and viewability verification reports to confirm contract fulfillment, generating a compliance certificate with shortfall details.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Contract terms (guaranteed impressions, target segment codes, thresholds, advertiser tier) live exclusively in workspace JSON files. Actual delivery data (impression counts, demographic breakdowns, viewability measurements) is accessible only through tool calls. The demographic segment mapping between codes and numeric IDs resides in a separate CSV config file, and tier-specific tolerance adjustments are in a plain-text config file. Solving the task requires cross-referencing all of these sources.

- **Multi-Hop Reasoning**: Evaluating demographic compliance requires a dependency chain of length 4+: read contract to obtain target segment codes, read mapping CSV to convert codes to numeric IDs, call the demographic breakdown tool for each campaign to obtain per-segment impressions, then aggregate and compare against the contract threshold. Viewability compliance similarly chains: read benchmarks JSON for format-specific minimum samples, call campaign tool for ad format, call viewability tool, filter by minimum sample, aggregate, and compare against the contract threshold.

- **Conditional Constraints**: Delivery compliance tolerance is not fixed — it depends on the advertiser's tier (Gold/Silver/Bronze), with tier-specific adjustments added to the base tolerance. Viewability calculations conditionally exclude campaigns whose measured impression volume falls below the format-specific minimum measurement sample.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 8 (delivery_metrics, demographic_metrics, viewability_metrics, compliance_status, penalty_amounts, shortfall_report, plus the two implicit certificate components captured among the 8 keys returned by `step`'s `eval_criteria`).
- Source-access path: clean — solved using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No step-6 escalation was needed.
- Section 1 structural integrity: passed. `env.py`/`prompt.md` byte-identical across v0..v3; only `SCALE` differs in `data.py` (rows 50/100/200/400, files 8/16/24/32, ratios 1/2/4/8 and +0/+8/+16/+24).
- Section 2 solvability: passed on first reward-1.0 run after correcting solver-side key names (`order_id`, `campaign_id`, `total_measured`, `total_viewable`) — no env/prompt changes required.
- Issues found and fixed: none. Sections 3 and 4 reviewed indirectly via prompt.md and a successful step() run; no prompt-step misalignment surfaced.
- Blockers: none.
