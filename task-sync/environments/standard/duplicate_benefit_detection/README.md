## Task Topic

Identify duplicate benefit applications by cross-referencing applicant identity documents, household composition records, prior application IDs, and income verification submissions, outputting a flagged case list for manual review to prevent overpayment.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N=10.

The task exhibits the following structural dimensions:

- **Information Scattering**: Duplicate detection requires combining data from database tools (applicant identity, household members, applications, income verifications) with workspace files (identity document numbers in JSON files, employer-verified income in TXT reports, detection rule thresholds in YAML configuration). No single source is sufficient.
- **Multi-Hop Reasoning**: The ADDRESS_INCOME_MATCH detection requires a dependency chain of length 4: list applicants via tool (address grouping) → read detection rules from workspace (tolerance threshold) → read income report files from workspace (employer-verified amounts) → query applications via tool (common program check) → compute and compare.
- **Conditional Constraints**: Each duplicate detection rule has its own enabling flag, confidence score, and threshold parameters (e.g., minimum shared household members, income tolerance percentage) read from the workspace configuration file.

## Harness Report

- v3 reward: 1.0 (120/120 across 10 eval criteria).
- Eval criteria (10): file_exists, correct_columns, ssn_match_detection, name_dob_match_detection, household_overlap_detection, id_doc_match_detection, address_income_match_detection, confidence_scores, programs_affected, summary_in_response.
- Section 1 structural integrity: passed. Top-level dir contains only README.md and v0..v3/. Each v_n/ holds exactly data.py, env.py, prompt.md. env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE block (rows ×1/2/4/8, files +0/N/2N/3N with N=10).
- Section 2 solvability: solver succeeded on first attempt using only v3/prompt.md and Task_Env.get_assistant_tools(); no escalation to env.py/data.py was required.
- Issues found: none. No fixes applied.
- Cleanup: removed runtime artifacts (data.db, workspace/, __pycache__/) from every v_n/ and deleted the temporary solver.
