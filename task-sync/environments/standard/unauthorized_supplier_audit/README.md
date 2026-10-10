## Task Topic

Audit franchisee inventory for unauthorized supplier usage. Cross-reference purchase order invoices, approved vendor lists, central distribution center shipment records, and product quality complaints to flag procurement violations, generating a supplier compliance report with evidence.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=8.

Structural dimensions used:

- **Conditional Constraints**: Violation identification depends on cross-referencing purchase orders against regional approved vendor lists (with approval date windows), complaint thresholds from the compliance policy, and DC shipment matching. The audit scope file filters franchisees by status.
- **Information Scattering**: Approved vendor lists and DC shipment records live in workspace CSV/JSON files; purchase orders, supplier details, and quality complaints are only accessible via tool calls. Compliance thresholds and severity multipliers are in a YAML config file, and audit scope parameters are in a separate text file.
- **Multi-Hop Reasoning**: Franchisee region (tool) -> regional approved vendor CSV (file) -> supplier approval dates (file) -> purchase order dates (tool) -> violation determination. Similarly: supplier complaints (tool) -> complaint count vs threshold (file) -> severity multiplier lookup (file) -> severity score computation.

## Harness Report

- v3 reward: 1.0 (100/100) on first solver attempt.
- Eval criteria: 6 (report_format 10, violations_recall 25, violations_precision 20, severity_scores 15, sort_order 10, response_summary 20).
- Source-access: clean. Solver written using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; `env.py` was only inspected during Section 3 quality review (post-solve), no escalation needed.
- Structural integrity: pass. `diff` confirms `env.py`/`prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block.
- Prompt-step alignment: all 6 step criteria map directly to prompt requirements (CSV columns, violation enumeration, severity formula, sort order, response summary). Ground truth derived dynamically from `data.db`/workspace; no hardcoded counts.
- prompt.md quality: prose-only, no headings/bold/lists, no tool/source filenames leaked, scale-invariant wording.
- Issues found: none. No fixes required.
- Blockers: none.
