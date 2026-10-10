## Task Topic

Monitor high-demand textbook availability by cross-referencing course enrollment rosters, current library inventory counts, historical circulation data, and student reservation queues to identify shortage risks, outputting a procurement priority list with recommended purchase quantities.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Structural dimensions used:

- **Conditional Constraints**: Shortage risk classification depends on a weighted scoring formula with four normalized components (demand-supply ratio, reservation pressure, circulation intensity, waitlist factor), where weights and risk thresholds are defined in a workspace policy file. Purchase quantities follow a formula involving a target ratio and minimum order floor.
- **Information Scattering**: Course enrollment headcounts and waitlist counts live exclusively in workspace CSV files, while textbook-course mappings, inventory counts, circulation statistics, and reservation queues are only accessible through tool calls. Procurement policy parameters, budget allocations, and supplier discount schedules are spread across YAML, JSON, and CSV config files.
- **Multi-Hop Reasoning**: The dependency chain is: read enrollment files → call tool to get course-textbook mappings (required only) → call tool for inventory per textbook → call tool for circulation stats → call tool for reservations → read policy for scoring weights → compute risk scores → read supplier discounts → compute purchase quantities and costs → produce sorted output.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 8 (output_file_exists, correct_columns, correct_textbooks, correct_demand, correct_risk_scores, correct_risk_levels, correct_quantities, correct_sort_order)
- Source-access: clean — solved using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. `env.py` was opened only briefly during step-6 escalation to inspect ground-truth tolerance behavior, and confirmed no env/prompt edits were required.
- Section 1 (structural integrity): passed — top-level contains only `README.md` + `v0..v3/`; each version contains exactly `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Section 2 (solvability): initial run scored 0.985 because the solver read the wrong dict key (`pending_reservations` / `count`) from `get_pending_reservations`, which actually returns `pending_count`. After correcting the solver, reward reached 1.0. No fixes were needed in `env.py`, `data.py`, or `prompt.md`.
- Sections 3 & 4 (env / prompt quality): passed. Every `step()` criterion maps to a requirement in `prompt.md`; ground truth is recomputed dynamically from `data.db` and workspace files, so it is scale-invariant. Prompt has no headings, bold, or bulleted lists, uses scale-invariant wording, and exposes no tool names or internal filenames.
- Blockers: none.
