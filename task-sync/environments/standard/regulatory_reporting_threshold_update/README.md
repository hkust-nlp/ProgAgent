## Task Topic

A new financial regulation modifies reporting thresholds. The system cross-references the regulatory text, client account transaction histories, previous report filings, and jurisdictional rule mappings to generate a list of impacted clients requiring updated disclosures.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 8                   |
| v1      | 160           | 16                  |
| v2      | 320           | 24                  |
| v3      | 640           | 32                  |

Scaling ratios: rows_per_table follows 1×/2×/4×/8×; num_workspace_files follows base/base+N/base+2N/base+3N where N=8.

### Structural Dimensions

- **Conditional Constraints**: Impact eligibility depends on cross-referencing regulation clauses (transaction type × jurisdiction × client type), transaction totals exceeding new thresholds, and previous report filings matching old thresholds. Exemptions are evaluated through a multi-condition policy combining risk rating, compliance tier, AML flag, and registration date.
- **Information Scattering**: Client risk ratings, compliance tiers, and AML flags reside exclusively in workspace portfolio JSON files, while transaction histories, previous reports, and regulation clauses are accessible only through tool calls. Both sources must be combined to determine impact and exemption status.
- **Deliverable Constraints**: Output CSV requires exact column order, 2-decimal-place formatting, specific multi-key sorting (priority descending, gap amount descending, client ID ascending), and precise column definitions.
- **Multi-Hop Reasoning**: Tool (list active clients) → Tool (get transactions per client) → Tool (lookup regulation clause for txn_type/jurisdiction/client_type) → Tool (get previous reports) → File (portfolio data for exemption check) → File (priority matrix for classification) → compute and write output.

## Harness Report

- v3 reward: 1.0 (110/110)
- Eval criteria: 8 (csv_file_exists, correct_columns, correct_client_count, correct_client_ids, correct_amounts, correct_priorities, correct_sorting, response_impacted_count)
- Source-access: clean — solved via prompt.md + get_assistant_tools() only; no escalation to env.py needed for solving (env.py was inspected only to confirm Section 3 alignment after solver completion)
- Structural integrity: passed; v0/v1/v2/v3 env.py and prompt.md byte-identical, data.py differs only in SCALE block
- Issues found: none. Initial solver mis-implemented the registration-date exemption (treated it as a 90-day window before the effective date); the prompt explicitly states "registered on or after 2024-04-02", and env.py applies that same rule, so the wording is unambiguous. Fix was in the solver only.
- Blockers: none
