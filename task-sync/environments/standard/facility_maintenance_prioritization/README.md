## Task Topic

Identify and prioritize branch facility maintenance. Cross-reference equipment service logs, customer complaint tickets regarding ambient conditions, preventative maintenance schedules, and vendor contract response times to generate a ranked work order list for the quarter.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 12                  |
| v1      | 160            | 24                  |
| v2      | 320            | 36                  |
| v3      | 640            | 48                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=12.

### Structural Dimensions

- **Conditional Constraints**: Work order eligibility depends on cross-referencing three conditions across equipment, complaints, maintenance schedules, and service logs. Priority scoring involves multi-step conditional logic (severity scores, overdue multipliers, age bonuses, vendor penalties) with thresholds defined in workspace config files.
- **Information Scattering**: Critical data is split across CSV complaint batches, TXT service log summaries, YAML maintenance schedules, and JSON vendor reports in the workspace, complemented by equipment and branch details only accessible through tool calls.
- **Multi-Hop Reasoning**: Equipment → branch tier (tool) → tier multiplier (config); equipment type → specialty mapping (JSON file) → vendor search (tool) → response time check → penalty application. Chain length ≥ 4.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 8 (output_file_exists, correct_columns, correct_work_order_count, correct_equipment_set, priority_scores_correct, correct_ranking_order, vendor_assignments_correct, response_summary)
- Source access: clean — solver used only `v3/prompt.md` plus the public `Task_Env.get_assistant_tools()` interface and runtime artifacts (`data.db`, `workspace/`). No step-6 escalation needed.
- Issues found: none. Structural-integrity diffs were clean (env.py and prompt.md byte-identical across v0–v3; data.py differed only in the SCALE block). v3 solver passed all 8 criteria on the first run.
- Cleanup: removed `data.db`, `workspace/`, and `__pycache__/` from every `v_n/`; removed temp solver from `/tmp/`.
