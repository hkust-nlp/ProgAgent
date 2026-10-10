## Task Topic

Optimize driver allocation to reduce passenger wait times. Cross-reference real-time ride requests, active driver locations and statuses, historical demand heatmaps, and current traffic flow data to generate a dispatch priority list with recommended repositioning instructions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

The task uses the following structural dimensions:

- **Information Scattering**: Computing the correct priority score requires combining historical demand baselines from the database (via tool calls) with surge factors parsed from Markdown zone-demand reports, zone priority multipliers from a JSON configuration file, and passenger ratings from the ride-request tool. Driver eligibility is split between tool-reported status/vehicle type and overtime flags embedded in CSV shift logs. Estimated pickup times blend tool-sourced traffic data with road-closure information found only in unstructured text bulletins.

- **Multi-Hop Reasoning**: The dispatch pipeline forms a dependency chain of depth >= 3: read the YAML dispatch policy to learn the current operational hour and scoring weights -> call the zone-demand tool at that hour to retrieve baseline demand -> parse Markdown reports for surge factors and multiply -> normalize across all pending requests -> compute priority scores -> sort requests -> for each request, filter drivers through vehicle-matching rules (YAML), overtime flags (CSV), and minimum-rating thresholds (YAML) -> query traffic tool for travel times -> apply closure penalties (text bulletins) -> assign the optimal driver greedily.

- **Conditional Constraints**: Driver eligibility depends on vehicle-type matching rules and minimum-rating thresholds (both from the vehicle-rules YAML file), overtime status (from driver-shift CSVs), and availability status (from the tool). Repositioning triggers only when a zone's supply-to-demand ratio exceeds the oversupply threshold defined in the dispatch policy.

- **Deliverable Constraints**: Output CSVs require exact column names and ordering; priority scores and travel times must be rounded to policy-specified decimal places; the summary line in the final response must follow a prescribed format with exact counts and averages.

## Harness Report

**v3 solver reward:** 1.0 (100/100)

**Eval criteria (7 total, all equal across v0–v3):**

| Criterion | Max pts | Notes |
|---|---|---|
| dispatch_file_format | 10 | Exact column list on dispatch_priority.csv |
| dispatch_coverage | 15 | Set-equality of assigned request IDs vs ground truth |
| priority_scores | 20 | ≥95% scores within ±0.01 of ground truth |
| driver_eligibility | 15 | ≥90% driver assignments match ground truth |
| pickup_times | 15 | ≥90% pickup times within ±0.5 min of ground truth |
| repositioning_plan | 15 | Driver ID + target zone match, combined ratio ≥0.80 |
| response_summary | 10 | All 4 SUMMARY fields correct (avg pickup ±0.2 tolerance) |

**Issues found and fixed:** none. All four sections passed on first run with no changes required to any source file.
