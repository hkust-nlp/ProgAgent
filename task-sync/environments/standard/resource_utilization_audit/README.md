## Task Topic

Audit emergency resource utilization by correlating dispatch radio transcripts, equipment maintenance logs, personnel certification databases, and incident outcome reports to produce a prioritized list of units requiring retraining or re-equipping.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N = 10 (base).

**Structural dimensions used:**

- **Information Scattering**: Scoring thresholds, penalty points, certification requirements, and protocol violation keywords reside in workspace configuration files (YAML, JSON, CSV). Personnel certifications, equipment conditions, dispatch timing, maintenance logs, and incident outcomes are only available through tool calls. Solving the task requires combining both sources.
- **Conditional Constraints**: Whether a unit is flagged depends on multi-table business rules — average response time exceeding a threshold, certification levels falling below role-specific requirements, equipment condition ratings below minimums, maintenance next-due dates preceding the audit date, and incident outcome ratings below thresholds.
- **Multi-Hop Reasoning**: Protocol violation attribution requires reading the policy (keywords) → scanning transcript files (matching keywords to unit names) → aggregating per-unit counts → applying penalty multipliers from the scoring matrix. Equipment maintenance status requires: get unit equipment → get maintenance history per equipment → compare latest next_due_date against audit date.

## Harness Report

- v3 reward: 1.0 (total_score 100 / max_score 100).
- Eval criteria count: 7 (`report_format`, `correct_units`, `retraining_scores`, `reequip_scores`, `correct_sorting`, `correct_actions`, `response_top5`).
- Source-access: Section 2 solved cleanly using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no step-6 escalation required.
- Section 1 (structural integrity): pass — top-level contains only `README.md` and `v0..v3/`; each version dir contains only `data.py`/`env.py`/`prompt.md`; `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block.
- Section 3 (env quality): every prompt requirement is covered by at least one criterion in `step`. Score derivation is fully data-driven (no hard-coded counts). Note: `step`'s violation attribution restricts matches to units listed in each transcript's `Dispatched Units:` header, which is stricter than the prompt's bare "same-line co-occurrence" rule; since `data.py` only injects keywords on lines containing dispatched units, both rules produce identical ground truth at all scales — no fix needed.
- Section 4 (prompt quality): prose-only, no headings/bold/lists, scale-invariant wording ("every unit", "all transcripts", "every distinct incident"), explicit column names and sort order, no tool/source-filename leakage.
- Issues found: none requiring code edits.
- Blockers: none.
