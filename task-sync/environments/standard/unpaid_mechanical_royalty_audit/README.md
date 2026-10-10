## Task Topic

Identify unpaid mechanical royalties for streaming. Cross-reference ISRC codes from streaming platform reports, publisher and songwriter splits from registration databases, and historical payment ledgers to flag unmatched tracks, generating a discrepancy report for collection societies.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

Scaling ratios: rows grow as 1×/2×/4×/8×; workspace files grow as N/N+N/N+2N/N+3N where N=8.

Structural dimensions used:

- **Information Scattering**: Streaming platform data lives in workspace CSV files while registration splits and payment history are only accessible via tool calls. Royalty rate cards, territory commission tables, and reconciliation policy thresholds are each in separate workspace config files (YAML, CSV, JSON, MD). Solving the task requires combining all of these sources.
- **Multi-Hop Reasoning**: The dependency chain is at least five hops long — streaming CSV → rate card lookup → registration tool call → territory commission file → payment tool call → expected-vs-actual comparison.
- **Conditional Constraints**: Whether a track is flagged as UNDERPAID depends on the shortfall threshold from the policy file; SPLIT_ANOMALY detection depends on a percentage tolerance; commission rates vary by registration territory.
- **Deliverable Constraints**: The output CSV must follow an exact column order, specific sort keys (type then ISRC), two-decimal monetary precision, and prescribed semantics for each discrepancy type's amount fields.

## Harness Report

- v3 reward: 1.0 (100/100) on first solver attempt.
- Eval criteria: 6 — `report_format` (10), `unregistered_accuracy` (20), `unpaid_accuracy` (20), `underpaid_accuracy` (25, set+amount), `split_anomaly_accuracy` (10), `summary_accuracy` (15).
- Source-access: clean — solved using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no step-6 escalation.
- Structural integrity: passed. v0/v1/v2/v3 each contain only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the SCALE block.
- Section 3/4 review: prompt and step are well aligned (coverage, completeness, scale-invariance all hold). Step computes ground truth from current DB/workspace with no hard-coded counts. Prompt has no headings/bold/lists, no tool names, no absolute counts. No fixes required.
- Issues found: none requiring code changes.
