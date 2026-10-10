## Task Topic

Flag high-risk rental applicants by cross-referencing credit score thresholds, national eviction database records, income-to-rent ratio calculations, and previous landlord reference patterns to generate a prioritized review queue with risk scores.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 40             | 8                   |
| v1      | 80             | 16                  |
| v2      | 160            | 24                  |
| v3      | 320            | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Applicant income data and property rent amounts live exclusively in workspace files (JSON and CSV), while credit reports, eviction records, and landlord references are only accessible through tool calls. Reference verification status is stored in workspace TXT files and must be cross-referenced with tool-returned reference IDs. Risk scoring parameters, tier thresholds, and eviction severity weights reside in workspace configuration files (YAML, CSV, MD).

- **Multi-Hop Reasoning**: Solving the task requires a dependency chain of length ≥ 3. For example, to compute the income-to-rent ratio sub-score: list applicants via tool → read the applicant's property_id → look up the monthly rent from workspace CSV files → read income from workspace JSON files → compute the ratio → apply the configured threshold from workspace YAML. Similarly, the reference sub-score requires: retrieve references via tool → match reference IDs against verification status in workspace TXT files → filter to verified only → compute ratings → apply penalties from configuration.

- **Conditional Constraints**: Risk scoring depends on multiple configurable thresholds (credit base threshold, income minimum ratio, eviction recency window, reference verification status) that are read from workspace configuration files rather than hard-coded. Tier assignment and review queue inclusion depend on the computed risk score crossing configured boundaries.

- **Deliverable Constraints**: The output CSV requires exact column ordering, specific rounding (2 decimal places for risk_score and income_to_rent_ratio), tie-breaking rules for both sorting (risk_score DESC then applicant_id ASC) and primary_flag assignment (alphabetical), and a prescribed format for missing data (N/A for avg_reference_rating when no verified references exist).

## Harness Report

- v3 reward: 1.0 (perfect score, 100/100).
- Eval criteria count: 6 (`file_format` 10, `applicant_set` 20, `risk_scores` 25, `sorting` 15, `risk_tiers` 15, `summary_response` 15).
- Solver source-access: clean black-box. The solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; `env.py`, `data.py`, and the v0/v1/v2 sources were not opened during Section 2. No step-6 escalation triggered.
- Section 1 structural integrity: passed. Top-level has only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block (rows 40/80/160/320 = 1x/2x/4x/8x; files 8/16/24/32 = base + 0/N/2N/3N with N=8).
- Section 3 / 4 review: prompt-step alignment is complete (every deliverable scored, no hidden criteria); `step` derives ground truth dynamically from `data.db` and workspace files (no hard-coded counts); prompt has no headings/bullets/tool-names/absolute counts.
- Issues found: none. No fixes required.
- Blockers: none.
