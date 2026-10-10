## Task Topic

Monitor and reconcile daily catch logs against vessel quotas by cross-referencing electronic catch reports, species-specific quota certificates, port agent inspection records, and satellite AIS data, generating a discrepancy report for vessels exceeding allocated limits.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Total catch requires combining electronic catch reports (tool-only) with manual landing supplement CSVs (workspace-only). Zone restriction rules live in a YAML config file, while AIS zone-time data is in per-vessel JSON files, and actual catch-by-zone data must be queried via tools.
- **Conditional Constraints**: Discrepancy detection depends on seasonal adjustment factors (from YAML config) applied to quota allocations, a tolerance percentage threshold, and tiered classification of overages. Zone violations require cross-referencing zone-restricted species lists with AIS presence and catch records.
- **Multi-Hop Reasoning**: The dependency chain runs: list vessels (tool) → get species per vessel (tool) → get electronic catch totals (tool) + read manual landing CSVs (workspace) → get quota certificates (tool) → apply seasonal adjustments (workspace YAML) → compute effective quota and overage → classify tier (workspace YAML). Zone violations add another chain: read AIS zone summaries (workspace JSON) → check zone restrictions (workspace YAML) → query catch reports by zone (tool).

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria**: 6 (`report_file_format` 15, `correct_discrepancy_pairs` 25, `overage_accuracy` 20, `tier_accuracy` 15, `zone_violations` 15, `response_summary` 10)
- **Solver source-access**: step-6 escalation triggered. After honest re-reading of `v3/prompt.md`, the solver produced 253 discrepancies vs the env's expected 238; the 15-pair gap was exactly the (vessel, species) pairs whose catch came only from manual landing supplements (no electronic report). The prompt explicitly mandates "the quantities from both sources must be summed together to arrive at the true total catch", so the solver's reading was correct and `step()`'s ground truth was buggy.
- **Issues + fixes**:
  - `_compute_ground_truth` only iterated species via `SELECT DISTINCT species_code FROM catch_reports`, so vessel-species pairs that appeared only in `landing_supplement_*.csv` were silently dropped from the no-quota-certificate discrepancy check, contradicting the prompt's "combine two sources" rule. Fixed in `v0/env.py` by also unioning species keys from `landing_supplements`, then re-propagating to v1/v2/v3 (byte-for-byte invariant re-confirmed via `diff`).
- **Blockers**: none.
