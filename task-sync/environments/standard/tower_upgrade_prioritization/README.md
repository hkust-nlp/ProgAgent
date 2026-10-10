## Task Topic

Identify cell towers requiring capacity upgrades by analyzing per-sector traffic volume trends, historical peak usage, adjacent tower handoff failure rates, and planned local construction permits, outputting a prioritized upgrade list with recommended new radio unit configurations.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 8                   |
| v1      | 50            | 16                  |
| v2      | 100           | 24                  |
| v3      | 200           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 8.

**Structural dimensions used:**

- **Information Scattering**: Tower utilization, handoff failure rates, and nearby construction permits come from tool calls against the database, while structural grades, power headroom, and radio-unit slot availability are spread across multi-format site assessment files in the workspace. Policy thresholds, scoring weights, and the radio-unit catalog are in separate configuration files. No single source is sufficient.
- **Multi-Hop Reasoning**: The agent must chain tower listing → per-tower utilization/handoff/permit queries → site assessment lookups → factor scoring with config-file weights → RU recommendation via catalog cross-referenced with band compatibility and form-factor constraints → final ranked output (dependency chain length ≥ 5).
- **Conditional Constraints**: Upgrade eligibility requires both a minimum number of triggered factors (from policy) and an acceptable structural grade (from workspace files). RU selection is constrained by frequency-band coverage and tower-class-dependent form-factor rules.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (output_file_format=10, eligible_towers=25, priority_scores=20, ranking_order=15, ru_recommendations=20, response_summary=10)
- Structural integrity: passed. Top-level contains README.md plus v0..v3; each version has only data.py/env.py/prompt.md; env.py and prompt.md byte-identical across versions; data.py differs only in the SCALE block (rows 25/50/100/200, files 8/16/24/32 — matches the 1x/2x/4x/8x and +0/N/2N/3N rule).
- Section 2 source-access: clean reads of v3/prompt.md and v3/workspace/* only; v0/env.py was opened once during step 6 escalation to confirm that the env intentionally retains eligible towers with no compatible radio unit (recommended_ru_model="NONE"), which the prompt also implies (eligibility is determined before RU recommendation). No edits were needed in env.py or prompt.md.
- Solver mistakes (not env issues), recorded for transparency: (1) initial .txt site-assessment parser used blank-line block splits instead of the actual `---` separators and lower-cased keys without removing parenthesized units, missing 40 towers; (2) initial RU-recommendation logic dropped towers with no qualifying RU instead of marking them "NONE". Once corrected, the solver matched ground truth exactly.
- prompt.md quality: no headings/bold/bulleted lists, no leaked tool/source filenames, scale-invariant phrasing throughout.
- Blockers: none.
