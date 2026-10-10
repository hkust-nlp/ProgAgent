## Task Topic

Assess aggregate treaty exhaustion for catastrophe coverage. Cross-reference real-time industry loss indices, cedent's reported loss advices, treaty attachment and limit terms, and inuring reinsurance recoveries to determine remaining coverage, outputting a dashboard with active limit status per treaty.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 10                  |
| v1      | 50            | 20                  |
| v2      | 100           | 30                  |
| v3      | 200           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Treaty financial terms (type, attachment, limit) live in a workspace YAML file, while treaty metadata (name, cedent, currency, dates) is only accessible via tools. Loss development stages are stored in workspace cedent bulletin CSVs, while gross loss amounts come from tool calls. Disputed-event exclusions come from a workspace text file. Currency conversion rates and ILI trigger thresholds are in separate workspace JSON files.
- **Multi-Hop Reasoning**: The dependency chain is at least length 4: retrieve loss advices via tool → look up development stage in workspace bulletins → apply LDF from workspace CSV → convert currency using workspace JSON → apply treaty terms from workspace YAML → filter by treaty type (ILW requires ILI tool call + workspace threshold; CAT_XL requires per-occurrence retention from workspace) → compute erosion against attachment/limit.
- **Conditional Constraints**: Treaty-type-specific qualification filters determine which events count toward erosion: AGG_XL includes all non-disputed events, ILW requires the industry loss index to meet a per-treaty threshold, and CAT_XL requires individual net loss to exceed a per-occurrence retention. Only the latest (highest sequence number) loss advice per treaty-event pair is authoritative.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (`dashboard_structure`, `treaty_count`, `gross_incurred`, `inuring_recoveries`, `erosion`, `remaining_limit`, `status_labels`)
- Solver verification: succeeded purely from `v3/prompt.md` plus `Task_Env.get_assistant_tools()` output. `env.py` was opened only afterward (Section 3) for the env-quality review, never to debug the solver.

Issues found and fixes applied:

- The dashboard columns `gross_incurred_usd`, `inuring_recoveries_usd`, and `net_incurred_usd` were ambiguous in the original prompt: an honest reading of "compute per-event net developed losses, then apply the qualification filter, then sum" suggests the dashboard totals should reflect qualified events only, but `env.py`'s ground truth sums them across every non-disputed event (pre-qualification) and computes `net_incurred_usd` as the simple difference of those totals (no per-event flooring). The first solver pass got 0.863 because of this. Fix: clarified `v0/prompt.md` to state explicitly that `gross_incurred_usd` and `inuring_recoveries_usd` are sums across all non-disputed events before the qualification filter, that `net_incurred_usd` equals their difference, and that the qualification filter is used only when computing `erosion_usd`, `remaining_limit_usd`, `exhaustion_pct`, and `status`. Re-propagated to v1/v2/v3 (`prompt.md` byte-for-byte identical across versions). Solver then scored 1.0.

No `env.py` or `data.py` edits were required. Structural integrity (Section 1) and prompt quality (Section 4) checks passed clean.
