## Task Topic

Identifying athletes at high risk of overtraining requires analyzing daily wellness survey scores, GPS training load metrics, sleep tracker data, and historical injury logs to flag individuals with cumulative fatigue spikes, generating a prioritized rest protocol list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

The v0 base values are `rows_per_table = 50` and `num_workspace_files = 10` (N = 10). Subsequent versions scale as: v1 = 2x rows / +N files, v2 = 4x rows / +2N files, v3 = 8x rows / +3N files.

### Structural Dimensions

- **Information Scattering**: Team roster data lives exclusively in a workspace CSV file while athlete profiles, wellness surveys, GPS load, sleep metrics, and injury logs are only accessible through tool queries. Session-level RPE training data is distributed across per-day workspace CSV files. Configuration parameters (risk thresholds, fatigue weights, body-region multipliers) reside in workspace YAML/JSON/CSV files. Solving the task requires cross-referencing all of these sources.

- **Multi-Hop Reasoning**: Computing each athlete's fatigue score involves a dependency chain of length >= 3: read config files (thresholds, weights, multipliers) -> query tools for wellness/GPS/sleep/injury data per athlete -> read workspace session CSVs for RPE loads -> combine session loads with GPS loads to compute ACWR -> apply body-region multipliers to injury records -> compute weighted composite score -> classify risk level -> assign protocol -> sort and rank.

- **Conditional Constraints**: Risk classification depends on composite score thresholds from the YAML config, protocol assignment depends on risk level, and injury burden calculation depends on recency-based factors and body-region multipliers from a separate CSV file.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (`file_exists` 10, `correct_columns` 10, `correct_athletes` 20, `correct_scores` 20, `correct_risk_protocols` 15, `correct_ranking` 10, `risk_summary_json` 15).
- Source-access: clean. Solver written from `v3/prompt.md` plus `Task_Env.get_assistant_tools()` only; no step-6 escalation needed.
- Section 1 structure: passed (top-level has only `README.md` and `v0..v3/`; each version has only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` byte-identical across versions; only `data.py` differs).
- Section 3/4 review: prompt-step alignment is full (every deliverable scored, no hidden criteria); step derives ground truth from current data with no hard-coded counts; prompt.md uses prose only (no headings, bold, or bullet lists), avoids tool/source-data filenames, and uses scale-invariant wording.
- Issues found: none. No fixes propagated.
- Blockers: none.

