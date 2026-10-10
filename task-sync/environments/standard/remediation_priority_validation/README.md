## Task Topic

Prioritize post-breach remediation by cross-referencing vulnerability scan results, asset criticality scores, active threat intelligence feeds on exploited CVEs, and patch deployment status to generate a validated action list for immediate system patching.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The v0 base values are `rows_per_table = 50` and `num_workspace_files = 8` (N = 8). Scaling follows the fixed ratios: v1 = 2× rows / +N files, v2 = 4× rows / +2N files, v3 = 8× rows / +3N files.

**Structural dimensions used:**

- **Information Scattering**: Asset criticality scores are only available in workspace CSV files (split across multiple batch files), while vulnerability scan results, threat intelligence, and patch deployment status are only accessible through tools. The remediation policy (multiplier tables, tier thresholds, SLA windows) lives in a workspace YAML file, and network zone risk multipliers in a workspace JSON file. No single source contains all the data needed to compute the priority score for a finding.

- **Multi-Hop Reasoning**: Computing each item's priority score requires a dependency chain of length ≥ 3: paginated scan results (Tool) → threat intel per CVE (Tool) → patch status per asset (Tool) → criticality from workspace CSV → multiplier lookups from policy YAML + zone JSON → priority score computation → tier assignment.

- **Conditional Constraints**: Inclusion/exclusion depends on patch deployment status (only "deployed" is excluded; pending/failed/scheduled/not_available/absent are included). The threat multiplier requires a two-key lookup combining the actively-exploited flag with exploit maturity. Priority tier assignment uses cascading threshold rules from the policy file.

- **Deliverable Constraints**: The output CSV has a fixed 13-column schema with exact column order, 2-decimal-place precision for priority scores, and a three-key sort order (priority_score desc → cvss_score desc → asset_id asc). The response summary must follow a precise multi-line format with tier breakdown and per-item listing.

## Harness Report

- v3 reward: 1.0 (total_score 100/100)
- Eval criteria: 6 (csv_structure 10pts, row_count 15pts, priority_scores 25pts, sorting_ranking 15pts, tier_action_sla 15pts, action_summary 20pts)
- Source-access path: clean — solver in `/tmp/solve_remediation_priority_validation.py` succeeded using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`. No step-6 escalation; `env.py` was only opened for Sections 3-4 quality review after Section 2 had already passed.
- Structural integrity: all four versions contain only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across v0-v3; `data.py` differs only in the `SCALE` block. SCALE follows the prescribed ratios (rows 50/100/200/400 = 1×/2×/4×/8×; files 8/16/24/32 = N+0/+N/+2N/+3N with N=8).
- Issues found: none. Prompt-step alignment, evaluation strictness, and scale invariance all check out. `prompt.md` adheres to formatting rules (no top heading, no bold section headers, no bullets/numbered lists, computation logic in prose, scale-invariant wording, no internal tool/file names leaked).
- Cleanup: removed runtime `data.db`, `workspace/`, `__pycache__/` from every `v_n/` and deleted the temporary solver.
