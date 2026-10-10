## Task Topic

Analyze player spending patterns by correlating in-game purchase receipts, virtual currency transaction logs, player progression tiers, and limited-time event calendars to identify under-monetized player segments, generating a targeted promotion campaign list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

`rows_per_table` scales as 1×, 2×, 4×, 8× of the v0 base (80). `num_workspace_files` scales as base, base+N, base+2N, base+3N where N = 8 (the v0 base). Only the `SCALE` block in `data.py` differs across versions; `env.py` and `prompt.md` are byte-identical.

### Structural Dimensions

- **Information Scattering**: Player spending and engagement data live in the database (accessible only via tools), while survey responses (willingness, preferred game mode) and configuration parameters (tier thresholds, segment criteria, promotion catalog, campaign rules) are split across JSON, YAML, CSV, and Markdown files in the workspace. Solving the task requires both sources.
- **Conditional Constraints**: Under-monetized classification depends on a three-way filter — spending ratio below a threshold, engagement score above a minimum, and survey willingness at or above a floor — with parameters drawn from workspace config files. Promotion matching adds further conditions on tier, game mode, and gap ratio.
- **Multi-Hop Reasoning**: The dependency chain spans at least four hops — retrieve player tier via tool → look up expected spending from YAML config → compute gap ratio → match against promotion catalog conditions using survey game mode from JSON files → assign promotion and compute priority score.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (csv_exists 10, player_identification 25, spending_calculations 15, promotion_assignment 20, priority_scores 15, sort_order 5, campaign_summary 10)
- Structural integrity: passed (env.py and prompt.md byte-identical across v0..v3; data.py differs only in SCALE).
- Issue found: prompt.md did not specify rounding of engagement_score, but env.py rounds it to two decimals before computing priority_score. This caused tie-breaking divergence (priority_score off by 0.01 for borderline candidates).
- Fix: amended v0/prompt.md to instruct rounding of engagement_score to two decimal places, then re-propagated to v1/v2/v3 byte-identical. No env.py change required.
- Cleanup: removed runtime artifacts (data.db, workspace/, __pycache__) from all version directories.
