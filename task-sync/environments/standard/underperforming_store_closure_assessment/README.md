## Task Topic

Evaluating underperforming stores for potential closure involves analyzing point-of-sale revenue trends, local competitor density shifts, lease renewal cost projections, and regional marketing spend efficiency to produce a prioritized closure list with estimated annual cost savings.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 10                  |
| v1      | 100            | 20                  |
| v2      | 200            | 30                  |
| v3      | 400            | 40                  |

Scaling ratios: rows grow as 1x/2x/4x/8x; workspace files grow as N/N+N/N+2N/N+3N where N=10.

### Structural Dimensions

- **Conditional Constraints**: Closure eligibility is determined by a composite score derived from four weighted factors, each with multi-tier thresholds. The lease cost score is further adjusted by landlord flexibility ratings using discount factors from the scoring policy.
- **Information Scattering**: Revenue trends, competitor data, and lease contracts are accessible only via tool calls. Operational costs and landlord flexibility scores exist only in workspace CSV files. Scoring parameters (weights, thresholds, tier boundaries) live in a YAML configuration file.
- **Multi-Hop Reasoning**: Computing the adjusted lease score requires: tool call (get lease details) → config file (determine base score tier) → workspace CSV (read flexibility score) → config file (apply flexibility discount factor). Computing estimated savings requires: tool call (revenue data) → compute trend → workspace CSV (operational costs) → tool call (proposed rent) → formula application.
- **Deliverable Constraints**: Output CSV must have exact column names and order, scores rounded to two decimal places, savings as whole numbers, rows sorted by composite score descending with store_id as tiebreaker, and ranks starting at one.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 6 (file_format=10, correct_candidates=25, ranking_order=15, individual_scores=20, savings_estimates=15, response_summary=15)
- Source-access: clean — Section 2 solved using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()`; no escalation to step-6 needed. `env.py` was inspected only as part of Section 3 env-quality review.
- Structural integrity: pass. `env.py` and `prompt.md` are byte-identical across v0..v3; only `SCALE` differs (rows 50/100/200/400 = 1x/2x/4x/8x; files 10/20/30/40 = N+0/N+N/N+2N/N+3N with N=10).
- Solver attempt 1 (reward 0.75): wrote all 400 stores into `closure_recommendations.csv`; `correct_candidates` expected only the 99 closure candidates. Re-reading prompt.md ("For every closure candidate, compute the estimated annual cost savings") confirmed the CSV is candidates-only. Fixed the solver (no env/prompt change required) and reached reward 1.0 on attempt 2.
- Env-quality and prompt-quality checks pass: prompt has no title/bold headers/bulleted deliverables; computation is described in prose; output filename is allowed; no tool names or source-data filenames leak; wording is scale-invariant; `step` derives ground truth dynamically from db/workspace and uses reasonable tolerances (score ±0.1, savings 5% or $1000).
- No code edits to `v0..v3` were necessary; runtime artifacts cleaned from all version directories.
