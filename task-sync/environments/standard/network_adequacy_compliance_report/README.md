## Task Topic

Validate network adequacy compliance by geocoding member addresses, mapping them to provider locations by specialty, and comparing against regulatory distance thresholds, generating a deficiency report for each service area.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Member plan types exist only in workspace roster CSV files, while member service-area assignments and geocoded coordinates are only available via tools. Provider credentials (board certification, expiry dates) are only in workspace JSON files, while provider office locations and network contract statuses are only accessible through tools. Solving the task requires merging data from both sources.

- **Conditional Constraints**: A provider counts toward a member's coverage only when four conditions hold simultaneously — board-certified with non-expired certification (checked against a reference date from a config file), accepting new patients, holding an active network contract matching the member's plan type, and located within the distance threshold for the specialty and area type. Thresholds and required coverage percentages come from workspace config files.

- **Multi-Hop Reasoning**: The dependency chain is: roster files → member IDs → tool (service area assignment) → tool (geocoding) → tool (provider search by specialty) → workspace credentials (filter eligible) → haversine distance computation → compliance threshold lookup → deficiency determination. This spans at least 4 hops across tools and files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (file_exists 10, correct_columns 10, correct_row_count 10, coverage_accuracy 30, compliance_determination 25, response_summary 15)
- Source-access: clean — solver written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; reached reward 1.0 without inspecting `env.py` or `data.py`. (Section 3 review of `env.py` performed afterward, as Section 3 requires.)
- Section 1 structural integrity: passed. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3, only `SCALE` differs in `data.py`. No stray `data.db`, `workspace/`, or `__pycache__/`.
- Section 3/4 review: prompt-step alignment is complete; no hidden criteria. `step` evaluates file existence, columns, row count, coverage_pct (1% tolerance), compliance flag, and the non-compliant summary. Ground truth recomputed from `data.db` + workspace each call (scale-invariant). Prompt is prose-only with no headings/bullets/scale-specific counts.
- Issues found and fixed: none. No edits to `v0/` were required.
- Blockers: none.
