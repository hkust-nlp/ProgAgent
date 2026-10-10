## Task Topic

Identify missed pickups requiring compensation by analyzing GPS truck stop locations, resident service request tickets, bin lift arm sensor activation logs, and contractual service level agreements to output a validated refund list with calculated credit amounts.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios: rows follow 1×/2×/4×/8×; workspace files follow base/base+N/base+2N/base+3N where N = 10 (the v0 base).

### Structural Dimensions

- **Conditional Constraints**: Eligibility depends on multiple cross-referenced conditions — the scheduled date must match the zone's pickup days, the date must not be excused (exception code + advance notice from route logs), and GPS proximity/duration thresholds plus bin-lift success from the SLA configuration determine miss classification. Repeat-miss status adds another conditional multiplier.
- **Information Scattering**: SLA thresholds, compensation rates, and excused-date flags live in workspace files (YAML, CSV, JSON, and CSV route logs); service request details, resident coordinates, GPS stops, and bin-lift records are only reachable via tool calls. Both sources are required for every refund determination.
- **Multi-Hop Reasoning**: Each validated refund requires a chain of at least four hops: service request → resident info → zone config (workspace) → GPS stops (tool) → bin lifts (tool) → rate lookup (workspace) → prior-claims check (tool) → final credit computation.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (csv_exists, csv_columns, correct_request_ids, correct_miss_types, correct_credits, sort_order, action_summary)
- Source-access: clean run; escalated to step 6 once to inspect `step()` after re-reading the prompt revealed an underspecified `miss_type` token.
- Issues and fixes:
  - The `step()` function expects the exact strings `full_miss` and `partial_miss` for the `miss_type` column, but the prompt's natural prose ("partial miss" / "full miss") did not specify these tokens. This is over-strict matching for an unspecified format. Fixed by adding an explicit instruction in `v0/prompt.md` ("Use the exact string `full_miss` or `partial_miss` for the `miss_type` column") and re-propagating byte-identically to v1/v2/v3. With this clarification, the prompt is now unambiguous and `step()` no longer rejects formats that match the natural-language description.
