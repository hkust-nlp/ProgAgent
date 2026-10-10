## Task Topic

Analyze donor engagement by cross-referencing campaign email open rates, recurring donation schedules, event attendance logs, and demographic segments to identify high-potential lapsed donors, generating a targeted re-engagement contact list with suggested ask amounts.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Scaling ratios: rows_per_table follows 1×, 2×, 4×, 8× of the v0 base (100). num_workspace_files follows base, base+N, base+2N, base+3N where N = base (10).

The task exercises the following structural dimensions:

- **Conditional Constraints**: Donor eligibility depends on a lapsed-threshold (months since last donation exceeding a policy-defined cutoff), a high-potential engagement score threshold (weighted combination of email open rate, event attendance rate, and giving history), and a do-not-contact exclusion flag — all governed by parameters in workspace configuration files.
- **Deliverable Constraints**: The output CSV has a fixed column order, engagement scores formatted to exactly four decimal places, ask amounts as whole numbers, and rows sorted by engagement score descending with donor ID as a tiebreaker.
- **Information Scattering**: Donor contact details and engagement metrics come from tool calls against the database, while do-not-contact flags, preferred contact methods, scoring weights, segment multipliers, and ask-amount recency tiers live in workspace files (YAML and JSON configs, JSON donor notes).
- **Multi-Hop Reasoning**: Policy config → compute cutoff date → find lapsed donors (tool) → per-donor engagement data (3 tool calls each) → apply scoring weights (config) → filter by threshold → read donor notes (workspace) for exclusions and contact preferences → compute ask amounts using segment tiers (config) + recency factors (config) → produce sorted output.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (`output_file_format`, `donor_identification`, `dnc_exclusion`, `engagement_scores`, `ask_amounts`, `response_summary`)
- Source-access: clean — solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`. `env.py` / `data.py` were not opened.
- Structural integrity: passed (top-level layout clean; v0/v1/v2/v3 each contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` byte-identical across versions; `data.py` differs only in the `SCALE` block).
- Issues found: none requiring source edits. The only solver-side stumble was a sort ordering subtlety — ties on the 4-decimal-formatted engagement score must be broken by ascending `donor_id` after formatting, not before. The prompt and `step()` already align on this; the solver was adjusted accordingly.
- Cleanup: removed `data.db`, `workspace/`, and `__pycache__/` from each `v_n/`; removed the temporary solver under `/tmp`.
- Blockers: none.
