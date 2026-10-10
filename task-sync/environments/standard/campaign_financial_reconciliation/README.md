## Task Topic

Reconcile fundraising totals by merging daily payment gateway deposits, in-kind donation appraisals, platform fee reports, and campaign-specific expense ledgers to produce a verified financial statement for each active campaign.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=10.

**Structural dimensions used:**

- **Information Scattering**: Financial data is split across database tables (gateway deposits, in-kind donations, approved expenses, fee waivers) and workspace files (manual deposit CSVs, appraisal certificate JSONs, fee statement YAMLs, expense supplement TXTs). Both sources are required to compute any single campaign's statement.

- **Multi-Hop Reasoning**: Computing adjusted in-kind values requires a 3+ hop chain: retrieve donation records via tool (base value, condition, category) -> check appraisal certificate files for certified overrides -> look up condition multipliers and category weights from reconciliation rules config -> compute adjusted total. Fee discrepancy checking requires: get campaign tier via tool -> look up tier rate from fee schedule config -> compute expected fees from total deposits (which themselves require merging tool + file data) -> compare against actual fees from fee statement files.

- **Conditional Constraints**: Only cleared gateway deposits count toward revenue; only approved expenses from the system are included; certified appraisal values override base values when present; fee discrepancy flagging is conditional on expected fees being nonzero and exceeding a configurable tolerance threshold.

## Harness Report

- **v3 reward:** 1.0 (110/110)
- **Eval criteria:** 8 (active_campaigns, gateway_deposits, manual_deposits, adjusted_in_kind, net_fees, total_expenses, discrepancy_report, summary_response)
- **Solver source-access:** Clean black-box. Solver written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No step-6 escalation; `env.py` was not opened until Section 3.
- **Section 1 (Structural Integrity):** Pass. Diff confirmed `env.py` and `prompt.md` byte-identical across v0-v3; `data.py` differs only in SCALE block. Row scaling 50/100/200/400 (1x/2x/4x/8x) and file scaling 10/20/30/40 (N+0/N/2N/3N) match the generate.md ratios.
- **Section 2 issues encountered (solver-side, not env bugs):**
  1. Initially wrote outputs to the env directory instead of `workspace/`; fixed by writing to `workspace/financial_statements.csv` and `workspace/discrepancy_report.txt`.
  2. Grand total mismatched expected by 0.04 due to summing full-precision `net_balance` values; fixed by summing the rounded per-campaign `net_balance` (which matches `step()`'s computation of `grand_total`).
- **Section 3 (Env Quality):** Pass. Coverage and completeness OK; ground truth derived dynamically from DB + workspace; no hard-coded counts; numeric tolerance of 0.015 is reasonable. Discrepancy report only validates campaign-id set membership (not strict line-format), which is acceptable leniency.
- **Section 4 (prompt.md Quality):** Pass. No headings, bold, or lists; computation in prose; output filenames and column names explicit; scale-invariant wording.
- **No source files modified.** No blockers.
