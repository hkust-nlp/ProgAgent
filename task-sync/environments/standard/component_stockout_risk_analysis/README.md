## Task Topic

Identify components at risk of stockout. Correlate active production orders, multi-level bill of materials, real-time inventory levels, and supplier lead times to flag parts with insufficient coverage, generating a prioritized procurement alert list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 40             | 8                   |
| v1      | 80             | 16                  |
| v2      | 160            | 24                  |
| v3      | 320            | 32                  |

The scaling ratios follow the standard progression: rows grow as 1×/2×/4×/8× of the v0 base, and workspace files grow as base/base+N/base+2N/base+3N where N = base (8).

**Structural dimensions used:**

- **Information Scattering**: Demand adjustment factors live in CSV files, supplier lead-time adjustments in JSON files, and reserved inventory quantities in semi-structured Markdown warehouse reports. Component details, BOM structure, inventory levels, and supplier mappings are only accessible through tool calls. Solving the task requires combining data from both sources.
- **Multi-Hop Reasoning**: The dependency chain is at least 3 hops deep — active production orders → product BOM (top-level children) → sub-assembly breakdown (second-level children) → inventory check → supplier lookup with file-based lead-time adjustments → priority score computation using policy weights from YAML config.
- **Conditional Constraints**: Priority scoring applies a weighted formula with four factors, tier assignment adds a criticality bonus before threshold comparison, and supplier selection follows a preferred-then-shortest-lead-time fallback rule. All parameters reside in workspace configuration files.

## Harness Report

**v3 solver reward:** 1.0 (100/100)

**Eval criteria (6 total):**

| Criterion | Max Score | Description |
|---|---|---|
| file_structure | 10 | `procurement_alerts.csv` exists in workspace with correct column order |
| component_identification | 25 | F1 score on the set of at-risk component IDs |
| numerical_accuracy | 25 | Per-component `total_demand`, `available_inventory`, `shortage_quantity` within 1% tolerance |
| priority_scoring | 20 | Per-component `priority_score` within 0.05 tolerance |
| sort_and_tiers | 10 | Sort order (descending by score) correct; tier labels correct for all components |
| response_summary | 10 | Final response contains correct total count, top-3 component IDs, and tier breakdown counts |

**Issues found and fixed:**

- Structural: stray empty `workspace/` directory found in `v3/` (left from a prior run) — removed.
- No edits to `env.py`, `prompt.md`, or `data.py` were required.

**Verification results:**

- Solvability: solver derived solely from `prompt.md` + `get_assistant_tools()` achieved reward=1.0 on first attempt; all 6 criteria scored full marks (177 at-risk components identified at v3 scale).
- Env quality: all 6 criteria correspond 1-to-1 to explicit prompt requirements; ground truth derived from live DB and workspace files (scale-invariant); BOM confirmed exactly 2 levels deep in generated data, consistent with `step()`'s non-recursive traversal.
- Prompt quality: no title, no bold headers, no numbered/bulleted lists, no tool names or internal filenames leaked, all output columns named explicitly, wording fully scale-invariant.
- Cleanup: removed `data.db` and `workspace/` from `v3/` after solvability run; no other artifacts found in v0..v3.
