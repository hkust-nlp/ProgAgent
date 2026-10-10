## Task Topic

Validate influencer post deliverables by analysing post timing, contracted engagement targets, audience location data, and historical bot-detection scores to flag non-compliant content and produce a payment adjustment file with supporting evidence.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8× of the v0 base (50). Workspace files follow base/base+N/base+2N/base+3N where N = 8 (the v0 base).

**Structural dimensions used:**

- **Conditional Constraints**: Compliance checks depend on multiple thresholds (bot score limits, engagement rate minimums, audience region percentages, posting hour windows) drawn from both contract records (via tools) and a YAML configuration file (in workspace). Penalty calculation follows layered rules from a payment terms document.
- **Information Scattering**: Audience location data lives exclusively in workspace JSON files, bot detection scores are only accessible through tool calls, contract thresholds come from tool queries, and penalty/threshold parameters reside in workspace configuration files. No single source is sufficient.
- **Multi-Hop Reasoning**: Contract → list posts (tool) → per-post bot report (tool) + audience geo lookup (file) + region mapping (config file) → violation assessment → penalty aggregation using payment terms (file) → adjusted payment computation.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (`flagged_posts_structure` 10, `flagged_posts_accuracy` 25, `payment_adjustments_structure` 10, `penalty_pct_accuracy` 20, `adjusted_payment_accuracy` 20, `action_summary` 15)
- Source-access rule: clean — solver completed using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no step-6 escalation needed.
- Issues found: none. Section 1 structural integrity passed (only `SCALE` differs across `v_n/data.py`; `env.py` and `prompt.md` byte-identical). Section 3 prompt-step alignment verified — all scored criteria correspond to prompt requirements, no hidden criteria, ground truth derived from `data.db`/workspace, no hard-coded scale assumptions. Section 4 prompt formatting clean (no headings, no bullets for deliverables, scale-invariant phrasing such as "every such contract", no tool/source filenames leaked).
- Fixes applied: none required.
- Blockers: none.
