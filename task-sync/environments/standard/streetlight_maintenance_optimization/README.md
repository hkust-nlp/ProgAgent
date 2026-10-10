## Task Topic

Optimize streetlight maintenance budget allocation. Correlate historical repair work orders, energy consumption data by zone, citizen complaint logs, and traffic accident reports to prioritize high-failure-rate or high-risk areas, producing a prioritized repair schedule and budget reallocation proposal.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Scoring weights, budget rules, and normalization parameters live in workspace config files (YAML, JSON, Markdown), while work order counts, complaint records, accident data, and streetlight install dates are only accessible through tool calls. Neither source alone is sufficient.
- **Multi-Hop Reasoning**: Computing a zone's composite risk score requires a dependency chain of length >= 3: read scoring config files -> query zone list -> for each zone, query work orders/complaints/accidents/energy/install dates -> normalize across all zones -> apply weights -> compute allocations with iterative capping -> assign tiers -> sort pending orders by composite score + severity + date.
- **Conditional Constraints**: Budget allocation respects min/max percentage bounds with iterative redistribution; tier assignment depends on configurable risk-score thresholds; failure rate calculation filters by severity level and reference year range.

## Harness Report

- v3 reward: 1.0 (100/100), achieved on the first solver attempt.
- Eval criteria: 6 (`repair_schedule_structure` 15, `repair_schedule_ordering` 20, `budget_proposal_structure` 15, `budget_allocations` 20, `risk_rankings_in_response` 15, `composite_risk_scores` 15).
- Source-access path: clean — only `v3/prompt.md` was read during Section 2; `env.py` was not opened until Section 3 review.
- Section 1 structural integrity: passed. Top level holds only `README.md` plus `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Section 3 env quality: every scored criterion maps to an explicit prompt requirement; ground truth is recomputed from the live `data.db` / workspace / configs with no hard-coded counts; tolerances (5% on allocations, ~95% on schedule ordering) are reasonable and scale-invariant.
- Section 4 prompt quality: no headings, no bold, no bulleted deliverables, no tool or source filenames leaked; output file names and column lists are explicit; wording is scale-invariant ("all pending and in-progress work orders", "every zone").
- Issues found and fixes applied: none.
- Blockers: none.
