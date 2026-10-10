## Task Topic

Validate certified seed lot purity for regulatory compliance. Cross-reference field harvest logs, lab germination test results, parent seed stock certificates, and government inspection records to confirm traceability, generating a compliance certificate for accepted lots.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Certification eligibility depends on crop-specific thresholds (germination rate, moisture, purity, vigor score, harvest weather limits) stored in a YAML config file, plus parent certificate validity rules (status, expiry vs harvest date, crop/variety match, generation chain).
- **Information Scattering**: Germination test data and inspection records come from database tools, while vigor scores are in workspace JSON files and field weather conditions are in workspace CSV files. Compliance thresholds and traceability rules live in workspace config files.
- **Multi-Hop Reasoning**: Lot → parent_lot_id → parent certificate → validate generation/expiry/crop/variety match; Lot → field_id → field condition CSV → compare against crop-specific weather thresholds from YAML config.

## Harness Report

- **v3 reward:** 1.0 (100/100)
- **Eval criteria:** 6 (accepted_lots_correct, certificate_numbers_correct, rejected_lots_correct, rejection_reasons_accurate, certificate_columns_correct, response_summary_counts)
- **Source access:** Clean — solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. No step-6 escalation needed; no `env.py` / `data.py` reads.
- **Section 1 (Structural Integrity):** Pass. Top-level holds only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` byte-identical across versions; `data.py` differs only in the `SCALE` block (rows 50/100/200/400; files 10/20/30/40, matching +N pattern with N=10).
- **Section 2 (Solvability):** Pass on first solver run. Solver computes pending lots from DB, evaluates parent cert / germination / vigor / field condition / inspection criteria against the YAML thresholds, writes `compliance_certificates.csv` and `rejection_report.csv` to `workspace/`, and submits the summary string. 134 pending lots → 22 certified, 112 rejected.
- **Section 3 (Env Quality):** No issues observed via `info["eval_criteria"]`; all 6 criteria scored as expected with the byte-identical `env.py` across v0..v3 ensuring scale invariance.
- **Section 4 (Prompt Quality):** Prompt is flowing prose with no headings, no bold section headers, no bulleted deliverables, no absolute counts, and no tool/source-file names leaked. Output filenames (`compliance_certificates.csv`, `rejection_report.csv`) are explicitly specified, as are columns and sort order.
- **Issues found / fixes:** None.
- **Blockers:** None.
