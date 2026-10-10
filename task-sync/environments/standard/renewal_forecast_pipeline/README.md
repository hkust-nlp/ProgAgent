## Task Topic

Produce a quarterly contract renewal forecast by analyzing usage metrics from SaaS platforms, upcoming expiration dates, stakeholder feedback from CRM systems, and historical negotiation notes to prioritize the renewal pipeline and required actions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Structural dimensions used:

- **Information Scattering**: The five risk-score components come from two distinct source types. Usage decline and sentiment risk are derived from tool calls (usage metrics and stakeholder feedback endpoints), while strategic importance, competitive threat, and negotiation difficulty are found exclusively in workspace files (JSON client dossiers, CSV competitive analyses, and Markdown negotiation briefs). The action thresholds and discount caps live in separate configuration files. No single source is sufficient to compute the final forecast.
- **Multi-Hop Reasoning**: Producing the projected discount for a single contract requires a chain of at least four hops: retrieve contract details (tool) → look up client tier (tool) → compute risk score from five components spanning tools and workspace files → match tier and value range in the discount schedule (workspace CSV) → multiply max discount by risk ratio.
- **Conditional Constraints**: The recommended action depends on both the computed risk score and the client's tier, with different threshold bands per tier defined in the renewal policy JSON. The projected discount is conditional on the contract's annual value falling within a specific bracket for its tier.
- **Deliverable Constraints**: The output CSV enforces exact column names and order, two-decimal-place rounding, and rows sorted by priority rank with a contract-ID tie-breaker. The final response must summarize the top five renewals with specific fields.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (csv_structure 15, contract_count 15, risk_scores 20, priority_ranking 15, recommended_actions 15, projected_discounts 10, top5_summary 10).
- Source-access path: clean — solver written using only `v3/prompt.md` and `Task_Env(...).get_assistant_tools()`. No step-6 escalation needed.
- Issues found: none. Structural integrity (Section 1) holds: env.py and prompt.md are byte-identical across v0..v3; data.py differs only in the SCALE block (rows 50/100/200/400, files 8/16/24/32 matching the 1/2/4/8 and N/2N/3N pattern). data.py runs cleanly at v3 scale. Prompt quality (Section 4) is clean: no headings, no bulleted deliverables, no tool names or source data filenames leaked, scale-invariant wording. Step() coverage matches prompt requirements.
- Fixes applied: none.
