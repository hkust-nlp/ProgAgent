## Task Topic

Detect patterns of upcoding by analyzing procedure code frequencies, provider specialty registries, patient demographic data, and historical claim denial rates to generate a prioritized provider audit list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

Structural dimensions used:

- **Conditional Constraints**: Provider flagging depends on composite risk scores derived from five weighted factors (frequency deviation, out-of-scope billing rate, denial rate deviation from peer group average, historical adjustment rate, demographic anomaly rate), each with thresholds and weights defined in workspace configuration files. Peer group membership, specialty authorization scope, and age-range boundaries for demographic anomaly detection all originate from separate workspace files.
- **Information Scattering**: Critical data is distributed across multiple file types (YAML config, JSON scope map, CSV benchmarks split across files, CSV provider supplements split across files, CSV historical adjustments split across files) and database tools (provider roster, claims, procedure details, denial statistics). No single source is sufficient; the agent must consolidate all of them.
- **Multi-Hop Reasoning**: Computing the denial rate deviation requires: listing providers → reading supplement files for peer group assignments → calling denial stats tool per provider → aggregating by peer group → computing per-provider deviation. Computing frequency deviation requires: getting claims per provider → looking up procedure category per code → computing distributions → comparing against regional benchmarks from files.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_structure 10, flagged_providers 20, composite_scores 20, priority_assignments 15, sorting_order 10, score_components 15, response_summary 10)
- Source-access: clean (no step-6 escalation; solver succeeded using only `v3/prompt.md` + `get_assistant_tools()`).
- Structural integrity: passed. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in `SCALE`.
- Issues found: none. Prompt prose, env step logic, and scale-invariant ground-truth computation all align.
- Solver bugs encountered (not env issues): merging patient age from `patients` table and using `complexity_level`/`Denied` casing — purely solver-side.
