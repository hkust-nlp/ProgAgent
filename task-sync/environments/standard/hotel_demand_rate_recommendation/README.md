## Task Topic

Forecast hotel room demand by merging competitor rate feeds, local event calendars, flight arrival passenger volumes, and current property occupancy to recommend daily rate adjustments per room type.

## Version Overview

All four versions share identical `env.py` and `prompt.md`. Only the `SCALE` dict in `data.py` changes:

| Version | `rows_per_table` | `num_workspace_files` |
|---------|------------------:|-----------------------:|
| v0      |              100 |                    10 |
| v1      |              200 |                    20 |
| v2      |              400 |                    30 |
| v3      |              800 |                    40 |

`rows_per_table` scales at 1×/2×/4×/8×. `num_workspace_files` scales at N/N+N/N+2N/N+3N where N = 10 (the v0 base).

### Structural dimensions

- **Information Scattering**: Task-critical fields are split across database tools (occupancy, events, flight arrivals, demand history) and workspace files (competitor rate CSVs, origin-city conversion profiles, group-booking manifests, pricing-rule configs, seasonal factors, rate boundaries). Neither source alone suffices.
- **Multi-Hop Reasoning**: Multiple dependency chains of length ≥ 3. For example: retrieve flight arrivals via tool → look up each origin city's conversion rate from workspace JSON profiles → compute weighted flight demand → combine with four other signals using weights from the pricing-rules config → apply seasonal factor from another file → clamp to boundaries from yet another file.
- **Conditional Constraints**: Rate adjustments are clamped to configurable min/max bounds; recommended rates must fall within per-room-type floor/ceiling from a boundaries file; occupancy ratios are capped at 1.0 after adding group bookings; missing origin cities fall back to a default conversion rate.
- **Deliverable Constraints**: Precise output formats are required — CSV column names and sort order, JSON key structure, decimal precision (2 places for rates, 4 for adjustment percentages), and specific aggregate fields in the summary.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (csv_exists_and_columns 15, csv_row_count 10, rate_boundaries 15, rate_accuracy 25, summary_exists 10, summary_accuracy 15, response_insights 10).
- Source-access: clean — solver used only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`; no escalation to `env.py` was needed.
- Section 1 structural integrity: passed; `__pycache__/` directories were present in `v0/` and `v1/` and were removed. `env.py`/`prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` dict.
- Section 3/4 review: prompt-step coverage and completeness are sound; tolerances in `step()` are reasonable; prompt is prose-only with no tool-name leakage and uses scale-invariant wording.
- Blockers: none.
