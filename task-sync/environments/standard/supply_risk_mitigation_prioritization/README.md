## Task Topic

Identify critical supply risks by cross-referencing supplier delivery performance history, geopolitical risk scores for source regions, raw material consumption forecasts, and alternate supplier qualification status to output a prioritized mitigation action list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 30             | 10                  |
| v1      | 60             | 20                  |
| v2      | 120            | 30                  |
| v3      | 240            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10.

### Structural Dimensions

- **Information Scattering**: Risk computation requires data from both tool calls (delivery records, region base risk, material criticality level, consumption forecasts, alternate supplier status) and workspace files (quality audit scores in CSVs, geopolitical intelligence in JSONs, demand adjustment factors in YAMLs, financial health data in TXTs). Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The material criticality component involves a dependency chain of length 4: query supplier details (tool) → get material criticality level (tool) → look up base score from criticality matrix (CSV config) → retrieve consumption forecasts (tool) → read demand adjustment factor (YAML file) → compute final material risk score.
- **Conditional Constraints**: Risk tier assignment depends on composite score thresholds defined in a workspace config file; mitigation actions are selected from a playbook based on the combination of tier and primary risk factor; the alternate-supplier risk score uses step-function thresholds based on the count of qualified alternates.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (file_structure 15, supplier_coverage 20, risk_score_accuracy 20, tier_and_factor 15, mitigation_actions 10, sorting_ranking 10, risk_summary 10)
- Source-access escalation: Step 6 used. Initial reward was 0.6 because env's delivery_risk formula `(late/total*60 + shortfall/total*40) * 100` saturates to 100 for any supplier with at least one late or short delivery, making the metric effectively binary and skewing the entire risk distribution. The natural reading of the prompt (no extra ×100) was checked first; after solver-side debugging failed to reach 1.0 the harness escalation rule permitted opening v3/env.py to inspect step().
- Issue and fix: Removed the spurious outer `* 100` from delivery_risk in `_compute_ground_truth` and `verify`, and rewrote the ambiguous prompt sentence ("equals the sum of two terms, each multiplied by 100") to the unambiguous "is the fraction ... multiplied by 60, plus the fraction ... multiplied by 40 (cap at 100)". Fix was applied in v0 and propagated byte-identical to v1/v2/v3; SCALE-only diff invariant verified via `diff`.
- Solvability re-confirmed at v3 scale: solver using only prompt.md + get_assistant_tools() achieves reward 1.0 across all seven criteria.
- No other issues: Sections 1, 3, 4 pass cleanly. Structural integrity holds (only data.py SCALE differs across versions). Step coverage matches every prompt deliverable; no hidden criteria. Prompt has no headings, lists, or tool/internal-file leaks; uses scale-invariant phrasing.
