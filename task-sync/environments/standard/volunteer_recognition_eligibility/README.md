## Task Topic

Identify volunteers eligible for recognition awards by cross-referencing total hours logged, specialized training certifications completed, peer feedback scores, and event leadership roles held to produce a quarterly commendation list with award tier recommendations.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 10                  |
| v1      | 160            | 20                  |
| v2      | 320            | 30                  |
| v3      | 640            | 40                  |

The task exhibits the following structural dimensions:

- **Information Scattering**: Hours data lives exclusively in workspace CSV files, while certifications, peer feedback, and leadership roles are only accessible through tool calls. Award tier thresholds and specialized certification category definitions reside in separate workspace configuration files (YAML and JSON). Solving the task requires combining data from all these sources.
- **Conditional Constraints**: Eligibility depends on volunteer status and join date, and tier assignment requires simultaneously meeting thresholds across four dimensions (hours, specialized cert categories, average feedback, leadership count) as defined in the policy configuration file.
- **Multi-Hop Reasoning**: The agent must read the policy file to learn the evaluation quarter and thresholds, then read the specialization reference to know which cert categories count, then aggregate hours from multiple CSV files filtered by quarter dates, then query per-volunteer tools for certs/feedback/leadership, and finally cross-reference all four metrics against tier definitions to determine assignments.

## Harness Report

- **v3 reward:** 1.0 (100/100).
- **Eval criteria count:** 7 (`file_exists` 10, `correct_columns` 10, `correct_volunteer_ids` 20, `correct_tiers` 20, `correct_values` 15, `correct_sort_order` 10, `response_summary` 15).
- **Source-access during solvability check:** clean — solved using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`; no escalation to `env.py` was needed.
- **Section 1 (structural integrity):** passed. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; only the `SCALE` block in `data.py` differs (rows ×1/2/4/8 and files +0/N/2N/3N relative to v0).
- **Section 2 (solvability):** `data.py` ran cleanly at v3 scale (640 volunteers, 40 hours-log CSVs, 1280 certs, 1920 feedbacks, 1280 leaderships). The solver paginated `list_volunteers`, called `get_volunteer_details` / `get_certifications` / `get_peer_feedback` / `get_leadership_roles` per eligible volunteer, aggregated hours from the CSVs filtered to the policy quarter, applied the four-threshold tiering, and produced `workspace/commendation_list.csv` with the prescribed columns, formatting, and sort order. `env.step()` returned 1.0 on the first successful run.
- **Section 3 (env quality):** `step` covers each prompt requirement (file presence, columns, ID set, tier assignments, numeric values, sort order, response summary). Ground truth is recomputed from `data.db` + workspace; no hard-coded counts. Numeric tolerances (0.15 hours, 0.015 feedback) accommodate the prompt's stated 1-decimal / 2-decimal precision without over-relaxing.
- **Section 4 (prompt quality):** prose-only with no headings, bold sections, or bulleted deliverables; computation logic stated in natural language; column names and CSV filename specified explicitly; scale-invariant phrasing ("all of these files", "every eligible volunteer").
- **Issues found / fixes applied:** none. All checks passed without modification.
- **Cleanup:** `data.db`, `workspace/`, and `__pycache__/` removed from every `v_n/`; tmp solver removed.
