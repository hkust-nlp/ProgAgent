## Task Topic

Optimize shift assignments by cross-referencing real-time machine maintenance logs, operator certification matrices, production line throughput targets, and historical absenteeism patterns to generate a daily staffing plan that minimizes downtime.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow N/N+N/N+2N/N+3N where N=8.

### Structural Dimensions

- **Conditional Constraints**: Assignment eligibility depends on certification level (with a stricter threshold for critical/high-priority lines), absence rate caps, and maintenance severity thresholds — all configured via workspace files rather than hard-coded.
- **Information Scattering**: Production targets and operator availability live exclusively in workspace CSV/JSON files, while machine details, certifications, maintenance logs, and absenteeism history are only accessible through tool calls. Solving the task requires merging both sources.
- **Multi-Hop Reasoning**: The dependency chain runs at least four hops deep: list production lines → retrieve line machines → check maintenance status to filter operational machines → fetch certifications and cross-reference with workspace availability and absence rates → apply ranking rules → assign.

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria**: 6 (`staffing_plan_format`, `correct_assignments`, `no_cert_violations`, `no_down_machine_assignments`, `coverage_summary`, `response_statistics`)
- **Section 1 structural integrity**: Pass. Top-level holds only `README.md` and `v0..v3/`; each version has exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; only the `SCALE` block differs in `data.py`.
- **Section 2 solvability**: Pass. Solver constructed using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`, with no escalation to `env.py` required. Submitted via `env.step(...)` and received reward 1.0 on first successful run.
- **Issues found and fixes**: None. The four versions hold together; prompt-step alignment is consistent and scale-invariant.
- **Blockers**: None.
