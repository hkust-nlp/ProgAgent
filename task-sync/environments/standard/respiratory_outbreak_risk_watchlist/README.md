## Task Topic

Identify cattle at high risk for respiratory outbreaks by correlating real-time barn environmental sensor data, individual animal vaccination histories, feedlot movement logs, and veterinary treatment records, generating a daily quarantine watchlist for the herd manager.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 10                  |
| v1      | 160            | 20                  |
| v2      | 320            | 30                  |
| v3      | 640            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10 (the v0 base).

### Structural Dimensions

- **Information Scattering**: Risk scoring requires combining environmental sensor data (via tools), vaccination/movement/treatment records (via tools), health observation symptom flags (workspace files in 4 formats: CSV, JSON, TXT, YAML), and scoring thresholds/protocols (workspace config files). No single source contains enough information to compute the composite risk score.
- **Conditional Constraints**: Quarantine eligibility depends on a composite score crossing a threshold, where each component has its own business rules — vaccine penalties vary by priority level (critical vs. high), environmental scores are proportional to the number of distinct breach types, and treatment relevance is filtered by diagnosis category and recency window.
- **Multi-Hop Reasoning**: Animal → pen → barn → sensor readings → breach detection → environmental score component (chain of length 4). Additionally: animal → vaccination history → protocol lookup → overdue/missing classification → penalty assignment.

## Harness Report

- v3 reward: 1.0 (100/100 across 6 eval criteria).
- Eval criteria: 6 (`csv_structure` 15, `watchlist_animals` 25, `risk_scores` 20, `sort_order` 10, `risk_factors` 15, `response_summary` 15).
- Source-access path: clean. Solver written from `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()` only; no escalation to `env.py` was needed.
- Section 1 (structural integrity): passed. Top-level holds `README.md` plus `v0..v3/`; each version contains only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; only the `SCALE` block differs in `data.py`.
- Section 2 (solvability): solver placed at `/tmp/solve_respiratory_outbreak_risk_watchlist.py` (cleaned up after use), submitted via `env.step` and scored 1.0 on the first run.
- Section 3-4 (env/prompt quality): step grading derives ground truth dynamically from current DB/workspace, all six criteria correspond to explicit prompt requirements, no over-normalization. Prompt is heading-free prose, scale-invariant wording (e.g. "every animal", "all of the daily health observation batch files"), and exposes no tool or source filenames; output filename `quarantine_watchlist.csv` is deliberately specified.
- Issues found and fixes: none.
- Blockers: none.
