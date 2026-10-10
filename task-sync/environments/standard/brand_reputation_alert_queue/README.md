## Task Topic

Monitor brand reputation by scanning news headlines, measuring social media volume anomalies, categorising support ticket sentiment, and tracking executive communications to generate a prioritised alert queue for the communications team.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Scaling ratios: rows follow 1x / 2x / 4x / 8x; workspace files follow base / base+N / base+2N / base+3N where N = 8 (the v0 base).

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across workspace files and tool-accessible data. Brand monitoring tiers live in CSV files, historical social-media baselines in JSON files, ticket severity overrides in analyst-note TXT files, and executive watchlists in YAML files. Meanwhile, current social-media volumes, headline text, ticket content, and executive communication summaries are only available through tool calls. The agent must cross-reference both sources to compute each signal correctly.

- **Multi-Hop Reasoning**: The dependency chain for each brand's severity score is at least four hops long: (1) read tier from workspace CSV → (2) query social-media metrics via tool and compare against workspace baselines → (3) query headlines via tool and score with workspace sentiment keywords → (4) query ticket content via tool, classify sentiment, and adjust with workspace severity overrides → (5) query executive comms via tool and match spokespersons against workspace watchlist → (6) combine all signals using workspace priority matrix weights and scaling factors.

- **Conditional Constraints**: Alert inclusion depends on a configurable threshold from the priority matrix; severity scoring involves multiple conditional multipliers (tier multiplier, severity override multiplier, risk assessment multiplier) sourced from workspace configuration files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (alert_queue_format, correct_brands, correct_severity_scores, correct_ranking, correct_signal_values, brand_risk_summary, action_string)
- Solver source-access: required step-6 escalation. The black-box solver (using only v3/prompt.md plus get_assistant_tools()) produced a faithful answer but step() returned reward 0.67. After confirming the solver matched the prompt, env.py was opened.
- Issue: ticket-notes parser in `_read_workspace_configs` (and the parallel block in `verify`) used `content.split("===")`, which splits each `=== Brand: NAME (ID: N) ===` header into two pieces. The ID landed in one fragment and the severity in the next, so no overrides were ever extracted; every brand silently fell back to the "normal" multiplier (1.0), corrupting ground truth for ~95 ticket-negativity values and dropping 5 brands from the expected alert list.
- Fix: replaced both occurrences with a `re.compile(r"=== Brand:[^=]*?\(ID:\s*(\d+)\s*\)\s*===\s*(.*?)(?=(?:\n=== Brand:)|\Z)", re.DOTALL)` finder that captures each brand's full block, then runs the severity regex inside the captured body. Edit was made in v0/env.py and propagated byte-for-byte to v1/v2/v3.
- Other sections: structural integrity passed after removing stale `alert_queue.csv` and `brand_risk_summary.json` left under v3/; SCALE ratios verified (50/100/200/400 rows, 8/16/24/32 workspace files); prompt and env.py byte-identical across versions; prompt.md formatting and content rules satisfied.
- Solver re-run after fix: reward = 1.0.
