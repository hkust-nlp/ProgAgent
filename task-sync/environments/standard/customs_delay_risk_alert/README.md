## Task Topic

Identify shipments at high risk of customs delay by cross-referencing carrier advance manifests, real-time port congestion data, historical HS code inspection rates, and supplier compliance documentation, generating an alert list for proactive broker intervention.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=10.

**Structural dimensions used:**

- **Information Scattering**: Supplier compliance data lives exclusively in workspace JSON files while supplier names are only available via tool calls; carrier on-time rates come from DB tools while special-handling flags and documentation status come from workspace CSV manifests; port congestion indices come from DB tools while disruption delay factors come from workspace Markdown bulletins.
- **Conditional Constraints**: Risk scoring depends on configurable thresholds, bracket tables, tier mappings, and penalty rules all defined in workspace YAML/JSON config files. Alert eligibility, risk levels, and broker priorities are all threshold-driven.
- **Multi-Hop Reasoning**: Shipment → carrier tool → on-time rate → bracket scoring → plus manifest workspace file → special handling bonus → carrier raw score → weighted contribution → composite risk → trade lane bonus → final alert determination (chain length ≥ 4).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (alert_file_exists, correct_columns, shipment_identification, risk_score_accuracy, correct_sorting, primary_risk_factor, response_summary)
- Source-access: clean — solver derived from `v3/prompt.md` plus `get_assistant_tools()` only; no escalation to read `env.py` was needed.
- Structural integrity: confirmed. `env.py` and `prompt.md` byte-identical across v0..v3; only the SCALE block in `data.py` differs. SCALE values follow rows ×1/2/4/8 (100/200/400/800) and files +0/N/2N/3N with N=10 (10/20/30/40).
- Section 3 review: every scored criterion maps to an explicit prompt requirement; ground truth is computed dynamically from `data.db` and workspace files (no hard-coded counts), and scale invariance is preserved by the byte-for-byte `env.py` invariant.
- Section 4 review: `prompt.md` uses prose-only formatting with no headings, lists, tool names, source filenames, or absolute counts; deliverable filename and column schema are explicit.
- Issues found: none. No fixes were required.
- Blockers: none.
