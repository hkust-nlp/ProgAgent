## Task Topic

Identify shipments at risk of missing contractual delivery windows. Analyze real-time vessel AIS positions, port congestion reports from terminal operators, historical customs clearance times, and shipper-provided incoterms to generate a prioritized alert list with recommended contingency actions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The v0 base values are `rows_per_table = 100` and `num_workspace_files = 10` (N = 10). Scaling follows the standard ratios: rows scale at 2x/4x/8x; workspace files grow by +N/+2N/+3N.

**Structural Dimensions:**

- **Information Scattering:** Task-critical data is split across database tools and workspace files. Vessel ETAs come from tool queries, while route deviation delays, customs clearance multipliers, contract deadline extensions, and port advisory wait times live in JSON, CSV, YAML, and Markdown files across the workspace. Both sources are required to compute the correct expected arrival date.

- **Multi-Hop Reasoning:** The expected arrival calculation follows a dependency chain of length 4+: retrieve vessel ETA via tool, query port congestion via tool, query customs clearance stats via tool, then modify customs time using workspace multiplier files and priority upgrade amendments, add route deviation delays from workspace JSON logs, add port advisory extra wait from workspace Markdown bulletins, apply deadline extensions from workspace YAML amendments, and finally compare against the effective deadline to compute delay days.

- **Conditional Constraints:** Risk classification depends on delay thresholds from a workspace config file, and the recommended contingency action depends on both the risk level and the risk bearer (derived from the shipment's incoterm via a workspace YAML reference), creating a two-dimensional lookup into the contingency playbook.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (alerts_file_structure 10, at_risk_identification 25, risk_classification 20, delay_calculation 15, contingency_actions 15, sort_order 15)
- Source-access: clean (Section 2 solved using only v3/prompt.md + Task_Env.get_assistant_tools(); env.py / data.py not opened until Section 3)
- Structural integrity: passed - top-level contains only README.md and v0..v3; each version contains exactly data.py, env.py, prompt.md; env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE dict.
- Prompt-step alignment: every step() criterion maps to a prompt requirement; ground truth is recomputed from data.db / workspace / data.py with no hard-coded counts.
- Issues found: none. No fixes required.
- Blockers: none.
