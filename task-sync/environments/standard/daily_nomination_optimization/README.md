## Task Topic

Optimize daily gas nominations by cross-referencing shipper contract volumes, real-time pipeline sensor pressure/flow data, compressor station fuel consumption logs, and downstream customer forecasted demand to identify constrained segments and calculate optimal hourly flow adjustments, outputting a dispatch instruction set.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 40            | 10                  |
| v1      | 80            | 20                  |
| v2      | 160           | 30                  |
| v3      | 320           | 40                  |

The v0 base values are `rows_per_table = 40` and `num_workspace_files = 10` (N = 10). Subsequent versions scale as: v1 = 2× rows, +N files; v2 = 4× rows, +2N files; v3 = 8× rows, +3N files.

**Structural dimensions used:**

- **Information Scattering**: Segment capacities and pressure limits live in workspace YAML files, shipper priority tiers and hourly profiles live in workspace JSON files, and customer minimum delivery obligations live in workspace CSV files. Meanwhile, the actual nomination volumes, real-time sensor readings, compressor fuel consumption logs, and demand forecasts are only accessible through tool calls to the database. Solving the task requires combining data from both sources.

- **Multi-Hop Reasoning**: The agent must chain multiple lookups: retrieve a shipper's nominations (Tool) → look up that shipper's hourly profile from contract files (File) → compute the hourly volume per segment → retrieve sensor pressure for that segment-hour (Tool) → look up segment pressure limits from spec files (File) → determine effective capacity → compare against total nominations to identify constraints → look up customer delivery obligations (File) → apply curtailment rules from the operational rules file (File) → allocate curtailment across shippers by priority order. This forms a dependency chain of length ≥ 4.

- **Conditional Constraints**: Curtailment logic depends on pressure-based capacity reduction (overpressure → 0.85× capacity, underpressure → 0.90×), priority-tier-based curtailment ordering (tier 5 first through tier 1 last with alphabetical tie-breaking), and customer protection rules that cap maximum allowable curtailment.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (dispatch_instructions_format=10, constrained_identification=20, effective_capacity_values=15, curtailment_volumes=15, curtailment_allocations=15, fuel_cost_summary=10, response_summary=15)
- Source-access: clean — solver succeeded on first attempt using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()` (no step-6 escalation).
- Section 1 structural integrity: passed. `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` block; SCALE follows rows ×1/2/4/8 and files +0/N/2N/3N (N=10).
- Section 3 prompt-step alignment: passed. All 7 criteria correspond to prompt requirements; ground truth is recomputed from `data.db` + workspace files (scale-invariant); tolerances (±0.5 row-level, ±1.0 totals) are reasonable.
- Section 4 prompt quality: passed. Pure prose with no headings/bullets/lists, no tool/internal names, scale-invariant wording, explicit column specs and final-response format.
- Issues found and fixed: none.
- Blockers: none.
