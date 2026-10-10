## Task Topic

Analyze pilot duty time compliance and fatigue risk by correlating crew pairing schedules, actual flight logs, crew rest period declarations, and regulatory duty time limits to generate a non-compliance report with recommended roster adjustments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 8                   |
| v1      | 50            | 16                  |
| v2      | 100           | 24                  |
| v3      | 200           | 32                  |

The v0 base values are `base_rows = 25` and `base_files = 8` (N = 8). Rows scale as 1×, 2×, 4×, 8× of the base; workspace files scale as base, base + N, base + 2N, base + 3N.

### Structural Dimensions

- **Conditional Constraints**: FDP limits vary by report-time window (early/normal/late), duty-type rules determine which pairings count toward FDP checks versus cumulative limits (with different multipliers), and severity classification follows tiered thresholds from workspace config files.
- **Information Scattering**: Regulatory thresholds, fatigue-risk weights, and severity rules live in workspace configuration files (YAML/JSON). Prior-period duty hours are spread across multiple CSV segments. Schedule amendments that modify pairing release times are distributed across JSON batch files. Current operational data (pairings, flights, rest declarations) is only reachable via tool calls. Solving the task requires combining all of these sources.
- **Multi-Hop Reasoning**: Rolling 7-day/28-day cumulative checks require reading prior-period hours from workspace CSVs → querying January pairings via tools → applying amendments from workspace JSON → computing duty durations with multipliers from config → aggregating across the date window. This constitutes a dependency chain of length ≥ 4.

## Harness Report

- v3 reward: 1.0
- Eval criteria: 7 (report_format 10, fdp_violations 20, rest_violations 15, cumulative_violations 15, fatigue_assessment 20, roster_adjustments 10, summary_response 10; total 100)
- Source-access escalation: Section 6 escalation was used once. After the solver matched 0/54 expected rest violations despite a careful prompt re-read, `v3/env.py` was opened to inspect `step()`. The mismatch was a prompt ambiguity, not a `step()` bug: the prompt's "Rest of {X}h between {CODE1} and {CODE2}…" wording specifies the `details` text but does not say which pairing's code goes in the `pairing_code` column. `step()` keys rest rows on the earlier pairing.
- Issue and fix: clarified the prompt to state that the rest-violation `pairing_code` column holds the earlier (first) pairing of the affected pair. Edit applied to `v0/prompt.md` and re-propagated byte-identically to `v1/v2/v3`.
- Re-verification: solver achieved reward 1.0 on v3 after the prompt clarification (FDP 144/144, rest 54/54, cumulative 1/1).
- Structural integrity: top-level contains only `README.md` and `v0..v3/`; each version has only `data.py/env.py/prompt.md`; `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows ×1/×2/×4/×8, files +0/+8/+16/+24, N=8).
- Blockers: none.
