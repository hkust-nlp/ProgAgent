## Task Topic

Identify overdue inter-library loan materials by reconciling partner institution due dates, internal patron contact logs, shipment tracking records, and replacement cost databases to calculate fines and replacement liabilities, outputting a reconciliation report with recovery actions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Structural dimensions used:

- **Conditional Constraints**: Fine calculation depends on institution-specific agreement overrides (grace period, fine rate multiplier, max cap) sourced from workspace config files, with tiered daily rates from the fine policy. Replacement liability triggers only when adjusted days overdue exceeds a configurable threshold or the loan is lost, and the cost is modified by condition grade multipliers and insurance deductions.
- **Information Scattering**: Book condition grades live exclusively in workspace CSV files, insurance coverage in workspace JSON files, and patron do-not-contact flags in workspace text files, while loan records, patron details, book base costs, shipment tracking, and contact history are only accessible through tool calls. Both sources must be combined to compute correct fines, replacement costs, and recovery actions.
- **Multi-Hop Reasoning**: Computing a single loan's net replacement cost requires: Tool (get loan → book_id, institution_id) → Tool (get book → base_replacement_cost) → Workspace (condition report → grade → multiplier) → Workspace (insurance record → coverage, deductible) → Workspace (fine policy → threshold check) → calculation chain of length ≥ 4.

## Harness Report

- v3 reward: 1.0 (110 / 110)
- Eval criteria: 7 (report_structure, item_identification, fine_calculations, replacement_costs, recovery_actions, sort_order, response_summary)
- Source-access path: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No step-6 escalation; `env.py` was not opened.
- Structural integrity: passed. `v0/v1/v2/v3` each contained only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; only `SCALE` differs in `data.py`.
- Issues found: none. No edits required to `v0/` or any other version.
- Cleanup: removed `v3/data.db`, `v3/workspace/`, `v3/__pycache__/`, and the temporary solver at `/tmp/solve_inter_library_loan_reconciliation.py`.

