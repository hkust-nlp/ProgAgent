## Task Topic

Optimize preventative maintenance scheduling. Analyze work order histories, appliance warranty expirations, seasonal vendor service rates, and tenant repair request frequencies to generate a prioritized quarterly maintenance calendar.

## Version Overview

All four versions share identical `env.py` and `prompt.md`. Only the `SCALE` block in `data.py` changes:

| Version | `rows_per_table` | `num_workspace_files` |
|---------|------------------|-----------------------|
| v0      | 80               | 8                     |
| v1      | 160              | 16                    |
| v2      | 320              | 24                    |
| v3      | 640              | 32                    |

Row scaling follows `v1 = 2×, v2 = 4×, v3 = 8×` the v0 base. Workspace file scaling follows `v1 = base + N, v2 = base + 2N, v3 = base + 3N` where `N = base = 8`. Each table's actual row count is a multiple of `rows_per_table` (buildings: 1×, appliances: 2×, work_orders: 3×, tenant_requests: 2×, vendors: 1×).

### Structural Dimensions

- **Information Scattering**: Appliance details, work order history, tenant requests, and vendor base rates live in the database (accessible only via tools), while inspection condition scores are split across zone-level CSV files in the workspace and seasonal vendor rate multipliers sit in a separate CSV. Priority scoring weights, budget caps, and service-hour estimates each reside in their own config files. Solving the task requires reading all of these sources and cross-referencing them.

- **Conditional Constraints**: Vendor eligibility depends on specialty matching and active status. Budget constraints cap both monthly spend and item count. A minimum priority-score threshold filters out low-priority appliances. Vendor selection tie-breaking applies a multi-key rule (lowest cost → highest reliability → lowest vendor ID).

- **Multi-Hop Reasoning**: The dependency chain is: appliance record (tool) → warranty expiry + criticality → condition score (workspace CSV) → tenant request count (tool, keyed on building + category) → last work order date (tool) → priority formula (workspace YAML weights) → vendor selection (tool for base rate + workspace CSV for seasonal multiplier + workspace YAML for service hours) → budget allocation (workspace JSON) → final calendar.

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria count**: 6 (file_structure 15, scheduled_items 25, priority_scores 20, vendor_and_cost 20, sorting 10, summary_stats 10)
- **Source-access**: clean for solver authoring (only `v3/prompt.md` read); `v3/env.py` was opened once under step-6 escalation to confirm the priority-score rounding semantics after an initial 0.998 run, but no fix was needed — the prompt already specifies two-decimal formatting and the env's `round(..., 2)` before tie-break sort matches that requirement.
- **Section 1**: Pass. `env.py` and `prompt.md` byte-identical across v0..v3; only `SCALE` differs in `data.py`. No stray runtime artifacts.
- **Section 2**: Pass at reward 1.0 with a fresh solver built solely from `prompt.md` + `get_assistant_tools()`.
- **Section 3 / 4**: Pass. Every step criterion has a corresponding prompt requirement and vice versa. Prompt has no headings, no bullets, no tool/file-internals leakage, and no scale-specific counts.
- **Issues found / fixes**: None. No edits were made to `v0/` or any propagated version.
- **Blockers**: None.
