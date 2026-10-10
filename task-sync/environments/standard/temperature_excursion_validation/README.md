## Task Topic

Validate temperature excursion reports. Cross-reference temperature logger data from shipments, product-specific stability profiles, warehouse thermal mapping studies, and carrier incident reports to determine product viability and generate a disposition roster with recommended quarantine or release actions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task uses the following structural dimensions:

- **Conditional Constraints**: Disposition depends on multiple interacting business rules involving carrier certification status, incident severity levels, product stability tolerances, and warehouse thermal compliance. Thresholds and decision parameters are stored in workspace configuration files (excursion policy YAML, stability profile JSONs), not in the prompt.
- **Information Scattering**: Task-critical data is split across database tables (shipment records, temperature logs, product specs, incident reports) and workspace files (stability profiles, carrier certifications, thermal mapping studies, excursion policy). Neither source alone is sufficient to determine dispositions.
- **Multi-Hop Reasoning**: The dependency chain is: list pending shipments → get shipment details → get temperature log → get product info (temp range) → read stability profile (tolerance) → read carrier certifications → get incident reports → read thermal mappings → apply policy rules → produce disposition. This constitutes a chain of length 4+ with interleaved tool calls and file reads.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria: 7 (`roster_file_exists`, `correct_columns`, `correct_row_count`, `excursion_detection`, `disposition_accuracy`, `sort_order`, `response_summary`).
- Source-access: clean. Solver was written using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; `env.py` / `data.py` were not opened.
- Structural integrity: passed. v0..v3 contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block. Scaling follows rows ×1/2/4/8 (100/200/400/800) and files +0/N/2N/3N with N=10 (10/20/30/40).
- Issues found: none. v3 solver passed on first run; no edits to `v0/` were required.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from each version directory; deleted the temporary solver under `/tmp/`.
