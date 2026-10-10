## Task Topic

Identify REC portfolios at risk of failing annual compliance obligations by analyzing certificate vintage dates, upcoming regulatory submission deadlines, historical purchase contracts, and real-time grid injection data to generate a prioritized procurement list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 60             | 8                   |
| v1      | 120            | 16                  |
| v2      | 240            | 24                  |
| v3      | 480            | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=8.

The task exercises the following structural dimensions:

- **Information Scattering**: Critical compliance data is split across the database (accessed via tools) and workspace files. Certificate statuses may be overridden by YAML files, contract amounts may be amended in TXT files, injection verification flags may be overridden in JSON files, and portfolio target adjustments live in CSV files. No single source is sufficient.
- **Multi-Hop Reasoning**: The dependency chain is at least 3 hops deep: portfolio details (tool) -> certificates (tool) -> facility IDs -> injection records (tool) + injection overrides (workspace file) -> verified uncredited generation. Similarly, contract tool results must be cross-referenced with text-file amendments before deadline filtering.
- **Conditional Constraints**: Eligibility depends on multiple business rules spanning tables and config files: vintage year eligibility, certificate status (with workspace overrides), technology credit multipliers, delivery status filtering, deadline date comparisons, and shortfall thresholds.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (csv_format=10, portfolio_ids=20, shortfall_values=20, priority_and_sort=15, compliance_summary=20, response_text=15)
- Structural integrity: passed. v0/v1/v2/v3 each contain only data.py/env.py/prompt.md; env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE block.
- Solvability: solved at v3 scale on the first try using only prompt.md and get_assistant_tools(); env.py was not opened during Section 2.
- Issues found: none. Section 3 (prompt-step alignment, scale invariance) and Section 4 (prompt.md formatting and content) pass without modifications.
- Cleanup: removed v3/data.db, v3/workspace/, all __pycache__, and the temporary solver.
