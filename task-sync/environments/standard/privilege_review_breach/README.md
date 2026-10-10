## Task Topic

Identify privileged documents inadvertently produced in litigation by cross-referencing attorney-client email metadata, privilege log entries, opposing counsel's production index, and internal employee role directories to output a clawback request list with specific bates numbers.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Production batch manifests live in workspace CSV files, while employee roles, email participant details, and privilege log entries are only accessible through tool calls. Solving the task requires combining data from both sources.
- **Multi-Hop Reasoning**: The dependency chain is at least four hops long: production manifest entry (workspace) -> email details lookup (tool) -> participant employee IDs -> employee role lookup (tool) -> privilege log check (tool) -> apply eligibility rules from config files (workspace) -> output.
- **Conditional Constraints**: Clawback eligibility depends on multiple business rules drawn from two configuration files: triggering roles, eligible privilege statuses, eligible privilege types, and a production date cutoff.
- **Deliverable Constraints**: The output CSV requires exact column names in a fixed order, ascending lexicographic sort by Bates number, and the final response must state the total count and list every qualifying Bates number.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (clawback_file_exists, correct_columns, recall, precision, correct_privilege_types, correct_sort_order, response_summary)
- Section 1 structural integrity: pass. Top-level contains only README.md + v0..v3; each version has exactly data.py/env.py/prompt.md; env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE block.
- Section 2 solvability: pass on first attempt using only v3/prompt.md and Task_Env.get_assistant_tools(). No env.py/data.py inspection was required.
- Section 3/4 quality: no issues observed; criteria are scale-invariant (derived at runtime from data.db / config files), prompt.md uses prose without lists/tool names/absolute counts, and column/sort requirements are explicit.
- Issues found: none. No fixes required.
- Cleanup: removed all data.db, workspace/, __pycache__ artifacts and the temporary solver.
