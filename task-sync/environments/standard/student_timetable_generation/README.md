## Task Topic

Balance student course requests against teacher availability. Analyze student elective preference surveys, teacher contracted periods and subject assignments, core course requirements, and maximum class size limits to generate a finalized student timetable for the semester.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 8                   |
| v1      | 50            | 16                  |
| v2      | 100           | 24                  |
| v3      | 200           | 32                  |

The v0→v3 scaling ratios follow the standard pattern: rows scale as 1×, 2×, 4×, 8× of the base, and workspace files scale as N, N+N, N+2N, N+3N where N is the v0 base count.

**Structural dimensions used:**

- **Information Scattering**: Student rosters, course catalogs, section details, and teacher-to-section assignments live in the database (accessible only through tools), while elective preference surveys, teacher contracted availability schedules, core curriculum requirements, and scheduling policy parameters reside in workspace files. Solving the task requires cross-referencing both sources — for example, determining whether a section is "active" requires joining the tool-provided teacher assignment with the workspace-provided teacher availability schedule.

- **Multi-Hop Reasoning**: Determining a valid section assignment requires a dependency chain of length ≥ 3: query course sections (tool) → look up assigned teacher for each section (tool) → cross-reference teacher availability in that time slot (workspace file) → check remaining capacity against class size limit (tool-provided max_capacity minus current enrollments) → apply scheduling policy tie-breaking rules (workspace config).

- **Conditional Constraints**: Section eligibility depends on multiple interacting rules: the teacher must be available in the section's time slot (teacher schedule file), the section must have remaining capacity (max_capacity from DB), the time slot must not conflict with the student's already-assigned courses, and core courses take precedence over electives. The scheduling policy file specifies the priority order (GPA-based) and tie-breaking rules for section selection.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_format=10, student_coverage=15, schedule_completeness=15, core_requirements=20, capacity_limits=15, teacher_availability=15, summary_statistics=10)
- Source-access: clean Section 2 (only v3/prompt.md read; tools discovered via get_assistant_tools(); env.py inspected only briefly during analysis after solver succeeded)
- Section 1 structural integrity: passed. Top-level holds README.md + v0..v3; each version has only data.py/env.py/prompt.md; env.py and prompt.md byte-identical across versions; data.py differs only in the SCALE dict (rows 25/50/100/200, files 8/16/24/32).
- Section 2 solvability: initial naive greedy core-placement reached only 0.9833 (core_requirements 550/600) because some students' three required cores conflict on time slots when picked in declaration order. Switching to most-constrained-first ordering with backtracking (the same strategy implied by "first assign all core courses") yielded reward 1.0. No code change required — the prompt's "first assign all core courses" wording fairly implies that assignments should successfully place every core when feasible.
- Section 3/4 quality: criteria all map to prompt requirements; no hidden criteria; step derives ground truth from data.db / workspace; prompt avoids tool names, headings, lists, and absolute counts.
- Issues fixed: none (no edits to v0/.. needed).
- Blockers: none.
