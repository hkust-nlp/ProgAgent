## Task Topic

Analyze patient screening logs, electronic health record eligibility flags, site investigator availability calendars, and historical enrollment rates to identify recruitment bottlenecks, generating a prioritized site intervention list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|-------------------|
| v0      | 100           | 10                |
| v1      | 200           | 20                |
| v2      | 400           | 30                |
| v3      | 800           | 40                |

Scaling ratios: rows v1=2x, v2=4x, v3=8x base; files v1=base+N, v2=base+2N, v3=base+3N where N=10.

The task exercises the following structural dimensions:

- **Information Scattering**: Per-site risk adjustment factors and custom enrollment targets are distributed across workspace files in five different formats (CSV, JSON, TXT, YAML, MD), while screening outcomes, eligibility results, enrollment history, and investigator details are only accessible through tool calls. Scoring thresholds, regional benchmarks, and intervention text live in separate fixed configuration files.

- **Multi-Hop Reasoning**: Computing each site's severity score requires a dependency chain of length 4+: (1) read scoring config for thresholds and weights, (2) read regional benchmarks for default targets, (3) read supplement files for risk adjustment and custom target overrides, (4) call tools for screening/eligibility/enrollment/investigator data, (5) combine all to compute bottleneck type and severity, (6) apply tier multiplier and risk adjustment, (7) rank across all sites.

- **Conditional Constraints**: Bottleneck classification depends on four threshold-based rules (screen failure rate, eligibility barrier index, enrollment ratio, investigator utilization/certification expiry), each involving data from different tables and workspace files. The enrollment target used for comparison depends conditionally on whether a custom target exists for that site.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (file_format=10, site_coverage=15, bottleneck_accuracy=20, severity_accuracy=20, ranking_accuracy=15, intervention_accuracy=10, response_summary=10)
- Source-access: clean. Solver was authored using only `v3/prompt.md` and the public `Task_Env.get_assistant_tools()` interface; no escalation to `env.py` was required during Section 2.
- Section 1 structural integrity: passed. `v0..v3` differ only in the `SCALE` block of `data.py`; `env.py` and `prompt.md` are byte-identical across versions.
- Sections 3 and 4 review: no issues found. Step criteria align with prompt requirements (coverage and completeness), enforce exact column order/names, use a reasonable ±0.5 numeric tolerance for severity given the prompt's 2-decimal rounding, derive ground truth from current `data.db`/workspace (no hard-coded counts), and `prompt.md` follows formatting rules (no headings/lists, prose-only, no tool/source-file leakage, scale-invariant wording).
- Issues and fixes: none. No edits were needed in `v0/` or any other version.
- Blockers: none.
