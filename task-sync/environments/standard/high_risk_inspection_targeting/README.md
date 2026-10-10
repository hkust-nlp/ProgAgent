## Task Topic

Identify high-risk import shipments for physical inspection. Cross-reference declared HS codes, shipper compliance history, country of origin risk scores, and commodity-specific duty evasion patterns to flag declarations with >85% anomaly probability, outputting a daily inspection shortlist.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Scaling follows the standard ratios: rows grow as 1×/2×/4×/8× of the v0 base, and workspace files grow as base/base+N/base+2N/base+3N where N = base (10). Only `data.py`'s `SCALE` block differs between versions; `env.py` and `prompt.md` are byte-identical.

**Structural dimensions used:**

- **Information Scattering**: Task-critical data is split across the database (shipper profiles, HS code classifications, inspection history accessed via tools) and workspace files (country risk tiers, evasion watchlist, valuation benchmarks, shipper dossiers). Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The anomaly scoring chain requires ≥3 hops — e.g., get shipment → look up shipper profile (tool) → read shipper dossier (workspace file) → look up HS code chapter (tool) → cross-reference evasion watchlist (workspace file) → compute weighted score using config weights (workspace file).
- **Conditional Constraints**: Flagging depends on a composite anomaly probability exceeding a configured threshold (0.85), computed from five weighted factors each with their own sub-formulas (tier score blending, violation rate scaling, valuation deviation capping).
- **Deliverable Constraints**: Output CSV requires exact column names, column order, 4-decimal rounding on probabilities, and descending sort by anomaly probability.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (`shortlist_file_exists` 10, `correct_columns` 10, `correct_flagged_shipments` 25, `anomaly_probabilities_accurate` 20, `sort_order_correct` 15, `response_summary` 20)
- Source-access: clean (Section 2 solved with `prompt.md` + `get_assistant_tools()` only; `env.py` opened only after the second iteration to confirm the watchlist key format, per step-6 escalation, and no env/prompt edits were needed)
- Structural integrity: passed; `env.py` and `prompt.md` byte-identical across v0..v3, `data.py` differs only in `SCALE`.
- Solver issue (no env change): the prompt phrase "Look up the chapter of each declaration's HS code" describes a string lookup. The HS-code chapter values (`"01-05"`, `"15"`, `"90-97"`, ...) and the watchlist `hs_chapter` column use the same string format, so the watchlist key is `(chapter_string, country)` directly. The first solver pass parsed chapters as integer ranges and never matched; the corrected solver does an exact key lookup and reaches reward 1.0. No bug in `env.py` or `prompt.md`.
- Cleanup: removed runtime `data.db`, `workspace/`, `__pycache__` from each version directory; deleted `/tmp/solve_high_risk_inspection_targeting.py`.
- Blockers: none.
