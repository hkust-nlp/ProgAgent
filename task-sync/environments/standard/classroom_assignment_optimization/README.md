## Task Topic

Optimize classroom and specialist room assignments. Cross-reference teacher subject certifications, class enrollment rosters, room capacity and equipment lists, and mandatory weekly instructional minutes to produce a conflict-free weekly room allocation schedule.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 12            | 8                   |
| v1      | 24            | 16                  |
| v2      | 48            | 24                  |
| v3      | 96            | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N = 8.

Structural dimensions used:

- **Information Scattering**: Room equipment details live in YAML workspace manifests while room capacity and type are only available via query tools. Teacher availability constraints are in CSV workspace files while teacher certifications require per-teacher tool calls. Instructional minute requirements are in a workspace CSV while class enrollments and subjects come from query tools.
- **Multi-Hop Reasoning**: Determining how many periods each class needs requires reading the instructional-minutes CSV and the scheduling-policy YAML (for period duration), then computing the ceiling of their ratio. Assigning a room requires looking up the class's subject, mapping it to required equipment via a JSON reference, then checking each candidate room's equipment manifest in YAML files, and finally verifying capacity from the query tools — a dependency chain of length 4+.
- **Conditional Constraints**: Room eligibility depends on equipment match, capacity threshold, and specialist-room exclusivity rules. Teacher scheduling is constrained by per-day and per-week period caps plus unavailability slots.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (schedule_file_valid 10, all_classes_covered 20, no_room_conflicts 15, no_teacher_conflicts 15, capacity_respected 15, equipment_satisfied 15, summary_response 10)
- Solver source-access: clean black-box. Solved using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; no escalation to `env.py` was required.
- Structural integrity: passed. `env.py` and `prompt.md` are byte-for-byte identical across v0..v3; `data.py` differs only in `SCALE` (rows 12/24/48/96; files 8/16/24/32 = N + 0/N/2N/3N).
- Issues found: none requiring fixes. Step scoring is intentionally lenient on a few prompt-mentioned constraints (teacher daily/weekly caps, unavailability, certification, sort order, best-fit room choice) — they are not separately scored, but a valid greedy solver that respects them produces full reward.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from each version directory and the `/tmp` solver file.
