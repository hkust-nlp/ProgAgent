## Task Topic

Optimize ad inventory pricing by analyzing fill rates. Process historical impression logs, listener geographic concentration, advertiser category performance, and seasonal sponsorship trends to recommend dynamic CPM adjustments, outputting a pricing schedule per show and region.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Difficulty scales only through data volume; `env.py` and `prompt.md` are shared unchanged across all four versions.

**Structural dimensions used:**

- **Information Scattering**: Campaign and impression data live in the database (accessed via tools), while listener geographic concentration profiles, category demand benchmarks, seasonal factors, and pricing adjustment rules are spread across workspace files in JSON, YAML, CSV, and Markdown formats. Both sources are required to compute the final pricing schedule.
- **Multi-Hop Reasoning**: The computation chain spans at least four hops: retrieve active campaigns (tool) to identify show-region pairs, then read geo profile files (workspace) for concentration shares, then call the revenue-by-category tool to find the dominant category, then look up the demand index from category benchmark files (workspace), and finally apply the formula from the policy document.
- **Deliverable Constraints**: The output CSV must use exact column names in a prescribed order, numeric values rounded to two decimal places, and rows sorted by show_id then region_id.

## Harness Report

- v3 reward: 1.0 (total_score 100 / 100).
- Number of eval criteria: 7 (file_exists, correct_columns, correct_row_count, correct_show_region_pairs, correct_fill_rates, correct_multipliers, correct_recommended_cpm).
- Solver outcome: succeeded on the first attempt using only `v3/prompt.md` and the public `Task_Env.get_assistant_tools()` interface. `env.py` was never opened during Section 2.
- Issues found and fixes: none — passed clean. Section 1 structural diff confirmed `env.py` and `prompt.md` are byte-for-byte identical across v0..v3 and only the SCALE dict differs in `data.py`. Section 3 alignment review found no hidden, missing, over-strict, or scale-dependent criteria. Section 4 found no formatting violations in `prompt.md`.

