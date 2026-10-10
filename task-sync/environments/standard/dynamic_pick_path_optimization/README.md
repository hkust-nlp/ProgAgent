## Task Topic

Optimize warehouse pick-path efficiency. Analyze daily order SKU assortments, real-time picker GPS location data, physical shelf zone mappings, and item weight/volume to generate a dynamic, route-optimized batch pick list for each warehouse associate.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Special handling designations (cold_chain, hazmat, fragile) are only available in workspace batch manifest CSVs, while order details, SKU specifications, and picker capacities are only accessible through tool calls. Picker certifications live in a separate workspace CSV. Solving the task requires cross-referencing all of these sources.
- **Multi-Hop Reasoning**: The solution requires a dependency chain of length 4+: pending orders (tool) -> order items (tool) -> SKU details including zone_id (tool) -> zone coordinates (workspace file) -> nearest-neighbor route computation.
- **Conditional Constraints**: Order assignment depends on multiple interacting conditions: picker certification status (workspace) must match order special handling (workspace), while picker remaining capacity (tool + policy file) must accommodate order weight/volume (computed from tool data).
- **Deliverable Constraints**: Output files require exact column ordering, two-decimal-place precision for weights and volumes, specific sort keys with tie-breakers (sequence -> shelf_position -> sku_id), and a fixed response format string.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 7 (pick_list_files_format=15, order_coverage=15, assignment_correctness=20, capacity_constraints=15, certification_constraints=15, route_optimization=10, batch_summary_response=10)
- Source-access escalation: clean — solver succeeded using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`; `env.py` was not opened during Section 2.
- Structural integrity: passed. `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block (rows 50/100/200/400, files 8/16/24/32), matching the ×1/2/4/8 and +0/N/2N/3N convention.
- Issues found: none. Section 3 (prompt-step alignment) and Section 4 (prompt formatting / scale-invariance / no tool-name leaks) both pass without edits.
- Fixes applied: none.
- Final cleanup: removed `data.db`, `workspace/`, and `__pycache__/` from every `v_n/`; removed the `/tmp/` solver.
