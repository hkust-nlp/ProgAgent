## Task Topic

Detect content piracy by cross-referencing student subscription tiers, video streaming access logs, third-party site takedown notices, and course material download patterns, generating a prioritized takedown list for illegally distributed premium lectures.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Rows scale at 2× per version step (v1=2×, v2=4×, v3=8× of base). Workspace files scale as base + k×N where N = base and k = version index.

### Structural Dimensions

- **Information Scattering**: Piracy signals are split across multiple sources — content fingerprints live in JSON scan reports and TXT DMCA complaint files, suspicious IPs sit in CSV watchlists, scoring parameters are in a YAML policy file, and student subscription tiers plus access/download logs are only reachable through tool calls. No single source is sufficient.

- **Multi-Hop Reasoning**: The dependency chain is at least length 4: read scan report fingerprint → look up lecture by hash (tool) → retrieve access logs for that lecture (tool) → look up each accessing student's tier (tool) → compare against tier-access rules (file) → compute weighted score using policy weights (file).

- **Conditional Constraints**: Whether an access event counts as "unauthorized" depends on the student's subscription tier, the lecture's access tier, and the tier-access rules mapping. The final inclusion/exclusion of a lecture on the takedown list depends on its computed score exceeding a configurable threshold.

## Harness Report

- v3 reward: 1.0 (100/100), achieved on first solver run via clean black-box (only `v3/prompt.md` + `get_assistant_tools()` consulted; no step-6 escalation needed).
- Eval criteria: 7 (file_format 10, lecture_ids 20, piracy_scores 20, ranking_order 15, priority_levels 10, unauthorized_counts 15, response_summary 10).
- Structural integrity: clean. `env.py` and `prompt.md` byte-identical across v0..v3; only `SCALE` differs in `data.py`. No stale artifacts.
- Prompt quality: no headings/bullets, prose computation logic, scale-invariant phrasing, no tool/internal names leaked.
- Env quality: ground truth derived from current DB/workspace; no hardcoded counts. Column-order is checked as set (presence-only) which is slightly lenient vs. prompt's "exact order" wording but does not affect correctness — left unchanged.
- Issues found / fixed: none requiring source edits.
