## Task Topic

Identify erroneous roaming charges by correlating subscriber international roaming logs, partner carrier tariff agreements, real-time location data, and customer-reported dispute tickets, outputting a validated refund list with corrected billing line items.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Structural dimensions used by this task:

- **Information Scattering**: Location tracking data is available only in workspace JSON files, tariff rates are available only via tool calls, and billing-zone mappings are available only in a workspace configuration file. Charge reference codes needed for the output live exclusively in workspace CSV files. Solving the task requires cross-referencing all of these sources.
- **Multi-Hop Reasoning**: The dependency chain for rate-overcharge detection is: dispute ticket → roaming log (get visited country and carrier) → carrier-zone config file (map country to zone) → tariff-rate tool (get rates for carrier/zone/date) → compute correct amount → compare against billed amount using tolerance from billing-rules config.
- **Conditional Constraints**: Error detection thresholds (rate tolerance percentage, location time window, minimum refund amount) are defined in a workspace YAML configuration file, not in the prompt. The agent must read and apply these parameters correctly.
- **Deliverable Constraints**: The output CSV requires exact column names and order, specific error-type string values, two-decimal-place monetary formatting, and rows sorted by refund amount descending with ticket ID as tie-breaker.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_structure=10, ticket_identification=20, error_classification=15, refund_amounts=20, charge_references=10, sort_order=10, summary_response=15)
- Source-access: clean — solver passed using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. No step-6 escalation required.
- Section 1 structural integrity: PASS. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block.
- Section 3 prompt-step alignment: PASS. All scored criteria correspond to prompt requirements; `step` derives ground truth from a `ground_truth` table populated by `data.py`, so it scales with `SCALE`.
- Section 4 prompt formatting: PASS. No title/headings/bold/lists; computation in prose; no tool or source-data filenames leaked; deliverable column names and value formats specified explicitly; wording is scale-invariant ("every open or pending-review dispute").
- Issues found and fixes: none.
- Blockers: none.

