## Task Topic

Analyze customer dropped call complaints by cross-referencing network performance logs, cell tower maintenance schedules, 3rd-party signal strength maps, and subscriber location data to identify persistent coverage gaps, outputting a prioritized tower upgrade list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Complaint counts, network metrics, and maintenance records are available only through tool calls, while third-party signal survey measurements and device-level call drop reports live exclusively in workspace files (CSV and JSON). Scoring criteria, regional multipliers, and technology upgrade paths are in separate config files (YAML, JSON, CSV, TXT). No single source contains all information needed to score a tower.

- **Multi-Hop Reasoning**: The agent must chain data from multiple sources in sequence: complaint summary (tool) → qualification check (config thresholds) → tower details including coordinates (tool) → signal survey measurements near those coordinates (workspace CSV) → device signal readings by tower ID (workspace JSON) → weighted scoring with regional multipliers (workspace CSV) → maintenance discount check (tool) → final ranking with tier assignment and upgrade recommendation (workspace JSON config). This forms a dependency chain of length ≥ 4.

- **Conditional Constraints**: Tower qualification depends on meeting both a minimum complaint count and a minimum average severity threshold. The maintenance discount conditionally applies only when a tower has active or scheduled maintenance. Priority tier assignment depends on score thresholds. Primary issue determination requires comparing weighted contributions with alphabetical tie-breaking.

- **Deliverable Constraints**: The output CSV must have exact column names, priority scores rounded to exactly 2 decimal places, rows sorted by priority_score descending with tower_id ascending as tie-breaker, and ranks starting from 1. The final response must include specific summary statistics.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_format, qualifying_towers, priority_scores, ranking_order, priority_tiers, primary_issues, recommended_upgrades)
- Section 1 (structural integrity): clean. Top-level holds only README.md and v0..v3/. Each v_n/ contains exactly data.py, env.py, prompt.md. env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE block (rows_per_table 100/200/400/800, num_workspace_files 10/20/30/40 for v0/v1/v2/v3 — matches x1/x2/x4/x8 row and +0/N/2N/3N file rule).
- Section 2 (solvability): solver at /tmp/solve_dropped_call_gap_analysis.py used only v3/prompt.md plus get_assistant_tools(); reward = 1.0 on first successful run. No env.py/data.py escalation needed (step 6 not invoked).
- Section 3/4 (env & prompt quality): all 7 step criteria correspond to explicit prompt requirements; ground truth is computed from data.db/workspace at runtime (scale-invariant); prompt.md is in prose with no headings, lists, tool names, or absolute counts.
- Issues found and fixes: none. All checks passed without modification to v0/.
- Cleanup: removed runtime artifacts (data.db, workspace/, __pycache__/) from every v_n/; removed solver from /tmp.
