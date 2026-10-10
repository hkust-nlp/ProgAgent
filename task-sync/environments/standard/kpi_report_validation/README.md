## Task Topic

Validate quarterly portfolio company KPI reports by cross-referencing submitted financials, signed board deck figures, SaaS platform API data, and previous report baselines to flag material discrepancies, outputting an exception report for partner review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 15            | 10                  |
| v1      | 30            | 20                  |
| v2      | 60            | 30                  |
| v3      | 120           | 40                  |

Scaling ratios: rows_per_table follows 1x/2x/4x/8x; num_workspace_files follows base/base+N/base+2N/base+3N where N=10.

Structural dimensions used:

- **Conditional Constraints**: Severity classification depends on tolerance multiples, sector-specific materiality thresholds (from workspace CSV), and fund-level escalation policies (Fund III/IV escalate MEDIUM to HIGH). Tolerance types vary per metric (relative vs absolute).
- **Deliverable Constraints**: The exception report CSV enforces exact column order, specific reference_source enum values, discrepancy_pct rounded to two decimal places, and a multi-key sort (severity descending, then company name, metric name, reference source alphabetically). The response must include precisely formatted summary statistics.
- **Information Scattering**: Submitted metric values live in per-company JSON workspace files; SaaS platform data, board deck figures, and previous baselines are only accessible through tool calls; tolerance rules are in a YAML config; materiality thresholds are in a CSV; fund escalation policies are in a text file. Solving the task requires combining all sources.
- **Multi-Hop Reasoning**: Read submission file -> get company details (sector, fund) via tool -> look up sector materiality thresholds from CSV -> retrieve SaaS/board deck/baseline data via tools -> compute discrepancies using YAML tolerance rules -> classify severity -> apply fund escalation from policy file.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_format 10, board_deck_recall 20, saas_platform_recall 20, qoq_anomaly_recall 15, severity_accuracy 15, precision 10, summary_statistics 10)
- Source-access: clean for sections 1-2; env.py opened under step-6 escalation in section 2 to diagnose a severity-classification bug after the solver, written purely from prompt.md + get_assistant_tools(), reproducibly disagreed with step() on 8 rows.

Issues found and fixes:
- env.py: `_parse_escalation_funds` matched fund names by substring on each policy line, so `"Fund I"` was incorrectly detected inside `"Fund III"` / `"Fund IV"` lines. This made every fund (including Fund I and Fund II) escalate MEDIUM->HIGH, contradicting the policy file and the prompt. Fixed by matching the longest fund names first and stripping each match before checking shorter ones, so only `Fund III` and `Fund IV` end up in the escalation set. Patched in v0/env.py and propagated byte-identical to v1/v2/v3.

Sections 1, 3, 4 had no other issues; structural integrity, prompt-step alignment, and prompt formatting all pass.
