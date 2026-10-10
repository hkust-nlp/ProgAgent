## Task Topic

Identify high-risk construction sites for proactive inspection. Cross-reference permit applications, contractor violation histories, geospatial zoning overlays, and citizen complaint logs to generate a weekly prioritized inspection list with risk scores.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 8                   |
| v1      | 120            | 16                  |
| v2      | 240            | 24                  |
| v3      | 480            | 32                  |

The scaling ratios follow the standard pattern: rows scale as 1×, 2×, 4×, 8×; workspace files scale as N, N+N, N+2N, N+3N where N=8. In addition to the scalable files, each version includes three fixed workspace files (risk configuration, zone hazard overlay, and inspection policy) that do not change with scale.

**Structural dimensions used:**

- **Conditional Constraints**: Risk scoring depends on multiple business rules involving cross-table lookups — license expiry status triggers penalties, unresolved violations receive a multiplier, recent violations earn a bonus, and escalated complaints contribute additional risk points. All thresholds and multipliers live in workspace configuration files.
- **Deliverable Constraints**: The output CSV requires exact column ordering, two-decimal-place risk scores, specific tier labels, semicolon-separated primary risk factors using exact configuration key names, and a defined multi-key sort order with tie-breaking rules.
- **Information Scattering**: Critical data is split between database tables (accessible only via tools) and workspace files. Violation records, contractor details, and complaint records come from tools; zone hazard metrics, site survey scores, contractor audit scores, and complaint escalation flags come exclusively from workspace files. Both sources are required to compute any single permit's risk score.
- **Multi-Hop Reasoning**: Computing a permit's risk score requires a dependency chain of length ≥ 3: search permits → get contractor → get violations → compute violation score, and separately: search permits → get zone ID → read zone hazard overlay → compute zone hazard score. The overall task requires combining results from multiple parallel chains through a weighted formula with additional license penalty logic.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (csv_file_structure, permit_count, risk_scores, ranking_order, risk_tiers, primary_risk_factors, response_top5_summary)
- Source-access path: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No escalation to `env.py` / `data.py` was required.
- Structural integrity: passed — top-level contains only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Data run: `v3/data.py` executes cleanly and produces `data.db` plus 35 workspace files (3 fixed + 32 scaled).
- Issues found: none. No edits required.
- Cleanup: removed all `data.db`, `workspace/`, and `__pycache__` artifacts, plus the temporary solver at `/tmp/solve_proactive_site_inspection_prioritization.py`.
