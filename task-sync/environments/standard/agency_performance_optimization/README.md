## Task Topic

Optimize recruitment agency spend by analyzing agency-submitted candidate profiles, interview-to-offer conversion rates, time-to-fill metrics, and final hire retention data to identify underperforming vendors, generating a vendor performance scorecard and renewal recommendations.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

At v0 the environment contains 50 agencies, 250 candidates, ~467 interviews, and ~132 hires across 10 monthly spend files. At v3 these grow to 400 agencies, 2000 candidates, ~3769 interviews, and ~1070 hires across 40 monthly spend files.

**Structural dimensions used:**

- **Information Scattering**: Financial spend data lives exclusively in workspace CSV files while candidate pipeline data (submissions, interviews, hires) is only accessible through tool calls. Both sources are required to compute cost-per-hire and the overall scorecard.
- **Conditional Constraints**: Tier assignment depends on overall score thresholds from a JSON config; renewal recommendations are governed by multi-condition rules (tier + retention_rate + conversion_rate) defined in a Markdown policy file.
- **Deliverable Constraints**: The output CSV has a fixed column order, specific numeric precision per field (4 decimal places for rates, 2 for costs, integer for days), and must be sorted by overall_score descending.
- **Multi-Hop Reasoning**: Tool calls retrieve candidate lists → hire records provide start dates and retention → workspace spend files provide cost data → config files supply normalization parameters and weights → tier thresholds determine classification → renewal rules produce recommendations (chain length ≥ 4).

## Harness Report

- **v3 reward:** 1.0
- **Number of eval criteria:** 7 (`scorecard_structure`, `conversion_rate`, `time_to_fill`, `retention_rate`, `cost_and_quality`, `overall_scoring`, `response_summary`)
- **Solver path:** Solved using only `v3/prompt.md` and `Task_Env.get_assistant_tools()` for the structural understanding. `env.py` was opened only under Section 2 step 6 to diagnose the response-summary tie issue (see below); `data.py` and the v0/v1/v2 sources were never inspected during solvability verification.

### Issues found and fixes

1. **Response-summary criterion was ambiguous under score ties.** At v3, 12 agencies tied at `overall_score == 0.0`, so the `bottom3_names` list (the last three after a stable score-only sort) was sensitive to dict-iteration order. A correct solver naming any three of those tied-zero agencies would only get partial credit.
   - **Fix in `v0/env.py`:** When ties exist at the top-3 / bottom-3 cutoff scores, the criterion now accepts any agency whose `overall_score` is at the cutoff. The check counts matches against the full tied candidate set and caps `top3_found` / `bot3_found` at 3.
   - **Propagation:** `v0/env.py` re-copied byte-for-byte to `v1/v2/v3`; `diff` confirms no other deltas. `data.py` and `prompt.md` were unchanged across the harness pass.

After the fix, the solver's submission scored `reward = 1.0` with all 7 eval criteria passing.
