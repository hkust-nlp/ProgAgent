## Task Topic

Identify prerequisite violation patterns. Analyze student academic transcripts, course prerequisite trees, registration attempt logs, and advisor override records to detect systemic gaps in prerequisite enforcement, outputting a violation report with recommended policy adjustments.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

The task scales from 80 students/courses/prerequisites (v0) up to 640 (v3). Workspace files (advisor override batches, student-advisor maps, audit logs, department capacity data, and prerequisite review notes) grow proportionally.

**Structural dimensions used:**

- **Information Scattering**: Violation detection requires cross-referencing tool-only data (student transcripts, course prerequisites, registration attempts) with workspace-only data (grade conversion table, enforcement policy, advisor override records, student-advisor assignments). Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The dependency chain is at least 3 hops deep: query prerequisites (Tool) -> query student transcript (Tool) -> read grade scale (File) -> compare grades -> read enforcement policy (File) -> classify severity -> read override records (File) -> determine override status.
- **Conditional Constraints**: Severity classification depends on two conditions evaluated together (violation type and whether the course is in the student's major), with thresholds for recommendations defined in a workspace policy file.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 8 (file_existence, csv_structure, violation_identification, severity_classification, override_status, recommendations_structure, recommendations_accuracy, response_summary)
- Source-access: clean (only `v3/prompt.md` read; tools discovered via `Task_Env.get_assistant_tools()`; no escalation to `env.py` needed)
- Structural integrity: passed; v0/v1/v2/v3 differ only in `SCALE` block of `data.py`; `env.py` and `prompt.md` byte-identical across versions
- Issues found: none. Solver succeeded on first run after correcting an internal mistake in the solver itself (registration table is named `registration_attempts`, not `registrations`); this was a solver bug, not an env bug, and required no source edits
- Blockers: none
