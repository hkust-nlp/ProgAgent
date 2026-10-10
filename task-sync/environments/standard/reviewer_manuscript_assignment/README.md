## Task Topic

Assigning manuscripts to reviewers requires matching manuscript keywords, reviewer publication histories, declared conflicts of interest, and past review quality scores to create an optimized and conflict-free reviewer assignment matrix for the editor.

## Version Overview

| Version | `rows_per_table` | `num_workspace_files` |
|---------|------------------|-----------------------|
| v0      | 20               | 10                    |
| v1      | 40               | 20                    |
| v2      | 80               | 30                    |
| v3      | 160              | 40                    |

Scaling follows the standard formula: rows grow as 1×/2×/4×/8× of the v0 base, and workspace files grow as base/base+N/base+2N/base+3N where N = base (10).

**Structural dimensions used:**

- **Information Scattering**: Manuscript keywords and reviewer expertise keywords live exclusively in workspace CSV/JSON files, while manuscript metadata (field, submission date), reviewer capacity limits, conflict-of-interest declarations, and historical review quality/timeliness scores are only available through tool calls. Solving the task requires combining both sources.
- **Conditional Constraints**: Reviewer eligibility depends on multiple cross-table conditions — absence of declared conflicts (conflicts_of_interest table vs. manuscripts), average historical quality score meeting a minimum threshold (review_history table + policy config file), and remaining round capacity (reviewers table, decremented during assignment).
- **Multi-Hop Reasoning**: The assignment score for each manuscript–reviewer pair requires a chain of at least three hops: (1) retrieve manuscript keywords from workspace files, (2) retrieve reviewer expertise keywords from workspace files, (3) compute Jaccard similarity, (4) retrieve historical quality/timeliness scores via tool call, (5) combine using weights from the YAML scoring rubric.
- **Deliverable Constraints**: The output CSV must have exact column names, exact column order, scores rounded to two decimal places, and rows sorted by submission date then manuscript ID.

## Harness Report

- v3 reward: 1.0 (total_score 100/100)
- Eval criteria: 6 — file_format (10), all_manuscripts_assigned (15), no_conflict_violations (20), capacity_respected (15), quality_threshold (15), assignment_quality (25).
- Source-access: clean (no step-6 escalation; only `v3/prompt.md` was read; tools discovered via `Task_Env.get_assistant_tools()`).
- Issues found: none. Structural diff (`env.py`/`prompt.md` byte-identical across versions; only `SCALE` differs in `data.py`) verified, no stale artifacts. Solver passed all 6 criteria on the first valid run after correcting an internal pagination bug in the harness solver itself (not an env defect).
- Blockers: none.
