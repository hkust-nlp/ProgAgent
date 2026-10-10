## Task Topic

Cross-reference supplier qualification certificates, past project performance scores, submitted bid pricing matrices, and mandatory sustainability criteria checklists to generate a ranked shortlist of compliant vendors for a municipal infrastructure tender.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 25             | 12                  |
| v1      | 50             | 24                  |
| v2      | 100            | 36                  |
| v3      | 200            | 48                  |

Structural dimensions used:

- **Conditional Constraints**: Disqualification depends on cross-checking certificates against tender requirements, sustainability responses against mandatory criteria definitions, performance averages against thresholds, debt ratios against limits, and establishment years against minimums — all thresholds sourced from workspace configuration files.
- **Information Scattering**: Financial health data lives exclusively in workspace CSV files, reliability ratings are embedded in prose within workspace text files, technical evaluation scores reside in workspace JSON files, while certificates, performance history, bid pricing, and sustainability responses are only accessible through tool calls. No single source suffices.
- **Multi-Hop Reasoning**: Tender specification → required certificate types → per-bidder certificate check → filter; scoring methodology weights → financial CSV data → normalized sub-components → weighted financial score; reference summary text → parsed reliability rating → blended performance dimension (tool-based average + file-based rating).

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 6 (output_file_format 15, qualified_vendor_set 20, score_accuracy 20, ranking_order 15, disqualification_report 15, response_summary 15).
- Solver source-access: clean black-box. The solver was written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`. No step-6 escalation: `env.py`, `data.py`, and `README.md` were not consulted during Section 2.
- Section 1 structural integrity: passed. `env.py` and `prompt.md` are byte-for-byte identical across v0..v3; `data.py` differs only in the SCALE block (rows 25/50/100/200, files 12/24/36/48 — matches the 1x/2x/4x/8x and N+0/N/2N/3N generate.md ratios).
- Section 3/4 review: prompt-step alignment is sound. Minor latent ambiguity: `prompt.md` says a vendor is disqualified if any required certificate they hold has expired status, while `step()` flags DQ-02 only when every instance of a required type is expired. The current data has no supplier with multiple instances of the same cert type, so both readings agree on this dataset; left unchanged. No hard-coded counts in step(); ground truth is derived dynamically from `data.db` and `workspace/`.
- Blockers: none.
