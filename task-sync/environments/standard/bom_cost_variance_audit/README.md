## Task Topic

Validate finished goods cost accuracy. Reconcile current raw material prices, approved vendor lists, labor routing standards, and actual production yield reports against the standard cost bill of materials, outputting a variance report for cost revision.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 20            | 8                   |
| v1      | 40            | 16                  |
| v2      | 80            | 24                  |
| v3      | 160           | 32                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Standard costs (BOM quantities, material standard prices, labor routing hours/rates) are accessible only through tool calls, while actual costs require reading workspace files — vendor quoted prices from JSON files, material handling surcharges from TXT files, actual labor hours from Markdown production summaries, and yield data from CSV reports. Threshold parameters live in a YAML configuration file and revision rules in a separate TXT policy file.
- **Multi-Hop Reasoning**: Determining the actual material price for a single BOM line requires a chain of at least length 3: query the BOM for material IDs → query approved vendors for each material → filter active/preferred vendors → look up the preferred vendor's quoted price in workspace JSON files → add the handling surcharge from workspace TXT files. The revision recommendation further chains yield rate computation and threshold lookups.
- **Conditional Constraints**: Flagging and revision decisions depend on multi-condition business rules involving variance thresholds, preferred-vendor fallback status, and yield rate floors, all parameterised in workspace configuration files.

## Harness Report

**v3 solver reward:** 1.0 (100/100)

**Eval criteria (7 total, 100 pts):**

| Criterion | Points | What it checks |
|---|---|---|
| `file_structure` | 15 | CSV exists (5), correct columns (5), rows sorted by descending abs(total_variance_pct) (5) |
| `all_products_present` | 10 | Every product in the DB has a row in the CSV |
| `material_cost_accuracy` | 20 | Standard/actual material cost and variance match ground truth (1% rel, ±$1 abs) |
| `labor_cost_accuracy` | 20 | Standard/actual labor cost and variance match ground truth (1% rel, ±$1 abs) |
| `yield_and_totals` | 15 | Yield rate, yield-adjusted total, total variance/pct match ground truth |
| `flags_and_revision` | 10 | `flag` and `revision_recommended` (YES/NO) match ground truth for every product |
| `action_revision_summary` | 10 | Final response mentions every product ID that has `revision_recommended = YES` |

**Issues found and fixed:**

1. **Runtime artifacts in v3/** (structural): `v3/data.db` and `v3/workspace/` were left over from a prior generation run. Removed.

2. **Sort order not enforced in `step()`** (env quality / completeness): `prompt.md` requires the CSV to be "sorted in descending order by the absolute value of total variance percentage", but the original `step()` never validated the row order. Fixed by redistributing the 15-pt `file_structure` criterion as: 5 pts for file existence + 5 pts for correct columns + 5 pts for non-increasing abs(total_variance_pct) order. Updated in `v0/env.py` and propagated byte-for-byte to `v1/`, `v2/`, `v3/`. Reward re-verified at 1.0 after fix.
