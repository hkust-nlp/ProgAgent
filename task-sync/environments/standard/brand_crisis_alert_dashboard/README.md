## Task Topic

Identify emerging brand crises by correlating real-time social media post volume, sentiment scores from comment analysis, influencer account verification flags, and product mention metadata, outputting a prioritized alert dashboard for PR teams.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Only the `SCALE` dict in `data.py` differs across versions; `env.py` and `prompt.md` are identical.

**Structural dimensions used:**

- **Information Scattering**: Post volume data and brand tier classifications live in workspace CSV/YAML files, while sentiment scores, influencer verification flags, and product mention metadata are accessible only through tool calls. Both sources must be combined to determine crisis status and compute scores.
- **Multi-Hop Reasoning**: The agent must chain workspace file reads (monitoring reports + baselines to compute spike ratios) through tool calls (sentiment, product mentions, influencer posts, then influencer verification lookups) before applying the scoring formula from a config file and the tier multiplier from another file — a dependency chain of length ≥ 4.
- **Conditional Constraints**: A brand qualifies for the dashboard only when three independent conditions are simultaneously met (spike ratio, sentiment threshold, and critical mention count), each sourced from different data channels, with thresholds defined in a workspace YAML config.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (dashboard_structure 15, brand_identification 25, crisis_scores 20, priority_ranking 15, alert_levels 10, response_summary 15)
- Solver source-access: clean black-box. The solver was written using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`; no step-6 escalation was needed and `env.py` was not opened until Section 3.
- Issues found and fixed:
  - A stale `v3/crisis_dashboard.csv` was present at the top of the version directory. Removed.
- No other issues. Structural integrity, byte-for-byte invariants on `env.py`/`prompt.md`, and the SCALE 1/2/4/8 (rows) and base+0/N/2N/3N (files) ratios all hold.
