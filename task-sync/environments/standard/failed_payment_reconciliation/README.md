## Task Topic

Identify and reconcile failed high-value cross-border payments. Analyze SWIFT message status codes, nostro account statements, correspondent bank fee schedules, and customer transaction logs to pinpoint failures, outputting a reconciliation file with root causes and required manual intervention steps.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Structural dimensions used:

- **Information Scattering**: Task-critical fields are split across workspace files (nostro statement CSVs for reconciliation flags, customer batch JSONs for urgency levels, SWIFT status code JSON for root cause categories, fee corridor YAML for expected fee computation, escalation procedures MD for intervention text) and tool calls (payment details, SWIFT message trails, correspondent bank active status, fee records, nostro entries).
- **Multi-Hop Reasoning**: The dependency chain is at least length 3: query failed payments via tool → retrieve SWIFT trail via tool to get rejection code → look up code category in workspace JSON → check bank active status via tool to potentially override root cause → read nostro CSVs for impact classification → read customer batch JSONs for urgency → apply priority rules from workspace YAML.
- **Conditional Constraints**: Priority determination depends on a cascade of business rules (bank inactive → CRITICAL; insufficient funds → CRITICAL; customer urgency CRITICAL → CRITICAL; amount ≥ 2× threshold → HIGH; urgency URGENT → HIGH; fee discrepancy > 20% → HIGH; else MEDIUM) drawn from workspace configuration, with first-match-wins semantics.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (payment_identification 20, root_cause_accuracy 25, fee_calculation 15, nostro_impact 15, manual_intervention 15, format_and_sorting 10)
- Source-access path: clean — solver succeeded on the first run using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no step-6 escalation needed.
- Structural integrity: PASS. Top-level contains only `README.md` and `v0/..v3/`. Each version has only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Env quality: PASS. All 6 step criteria correspond to explicit prompt requirements; ground truth is computed dynamically from `data.db` + workspace, so it scales across v0..v3.
- Prompt quality: PASS. Prose-only, no headers/lists for deliverables, scale-invariant wording ("all payments whose status is FAILED"), no tool/source-file names leaked, output filename and exact column order specified.
- Issues found and fixed: none.
- Blockers: none.
