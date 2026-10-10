## Task Topic

Failed delivery analysis cross-references historical delivery attempt logs, customer-provided access instructions, driver performance metrics, package dimensions/weight, and neighborhood security data to generate a prioritized re-routing list for high-value parcels with specific handling instructions.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 80             | 8                   |
| v1      | 160            | 16                  |
| v2      | 320            | 24                  |
| v3      | 640            | 32                  |

Structural dimensions used:

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Package value, customer identity, driver certifications, and neighborhood security level come from tool calls, while supervisor urgency flags live in delivery log CSVs, customer gate codes and delivery preferences live in JSON files, neighborhood safe-delivery hours live in YAML bulletins, and driver vehicle types live in TXT report files. Solving the task requires combining both sources.
- **Multi-Hop Reasoning**: The driver recommendation chain has length ≥ 3: package handling code (tool) → required certification and vehicle type (handling_matrix.yaml) → active drivers with that certification (tool) → vehicle type match (driver_report TXT files) → select best by success rate.
- **Conditional Constraints**: Eligibility depends on multiple conditions across tables — declared value must meet the policy threshold, the package must have only failed attempts with no successful delivery, and the total attempt count must not exceed the maximum reroute limit. Priority scoring further combines four normalized components plus a conditional urgent-flag bonus.

## Harness Report

- v3 reward: 1.00
- Eval criteria: 7 (file_structure 10, eligible_packages 20, priority_scores 20, sort_order 10, driver_recommendations 15, special_instructions 15, response_summary 10)
- Source-access escalation: step-6 escalation used to inspect `env.py` after the solver returned 0.98 with a sort-order mismatch caused by an under-specified tiebreak.
- Issues and fixes:
  - The prompt instruction "the neighborhood involved in its most recent failed attempt" was ambiguous when two failed attempts share the latest date. The env's `step` deterministically picks the failed attempt with the lowest attempt identifier among the tied dates, but the prompt did not state this. Fixed `v0/prompt.md` to specify "breaking ties on the attempt date by choosing the failed attempt whose attempt identifier comes first alphabetically", and re-propagated to v1/v2/v3 byte-for-byte.
- Blockers: none.
