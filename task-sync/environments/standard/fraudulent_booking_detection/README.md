## Task Topic

Identify high-risk reservation fraud by analyzing booking patterns, comparing guest identity document scans against blacklist databases, cross-referencing payment method histories, and assessing no-show records to produce a daily review list for the security team.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task exhibits the following structural dimensions:

- **Information Scattering**: Risk assessment requires combining data from tool queries (blacklist checks, payment method details, no-show counts) with workspace files (identity scan confidence from JSON batches, chargeback ratios from CSV transaction logs, rapid booking flags from TXT pattern summaries). No single source is sufficient.
- **Conditional Constraints**: Each risk factor activates only when its precondition meets a threshold defined in the YAML configuration file (e.g., fraud flag count >= minimum, scan confidence < floor, chargeback ratio >= threshold). The scoring cutoff, priority tiers, and all weight values are configuration-driven.
- **Multi-Hop Reasoning**: Evaluating a single reservation requires a chain of at least 4 hops: reservation -> guest identity -> blacklist check -> payment method -> transaction logs -> chargeback ratio computation, with additional branches for scan confidence and booking pattern lookups.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (`output_file_exists` 10 / `correct_columns` 10 / `correct_reservations` 25 / `correct_risk_scores` 20 / `correct_risk_factors` 15 / `correct_sorting` 10 / `response_summary` 10)
- Source-access: clean. Verified using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. No step-6 escalation needed; the one solver bug encountered (initially using `document_number` instead of the schema's `id_document_number` returned by `get_guest_info`) was fixable by inspecting the public tool's return payload, not env source.
- Issues found: none. Section 1 structural diff confirmed `env.py`/`prompt.md` byte-identical across v0..v3, only `SCALE` differs in `data.py`. Section 3 step coverage and completeness satisfied; no hardcoded scale assumptions. Section 4 prompt.md complies (no headings, no lists for deliverables, no leaked tool names, scale-invariant wording).
- Blockers: none.
