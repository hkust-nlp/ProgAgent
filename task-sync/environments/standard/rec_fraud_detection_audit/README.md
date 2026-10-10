## Task Topic

Flag potentially fraudulent REC transactions by cross-referencing generator accreditation certificates, market trade timestamps, meter data validation reports, and buyer sustainability claims to output an anomaly report for regulatory investigation.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

The task exercises the following structural dimensions:

- **Information Scattering**: Critical data is split across database tools (transactions, accreditation certificates, meter readings) and workspace files (meter validation statuses, buyer claims, reference price indices, trading rules, anomaly thresholds). Neither source alone suffices; the agent must combine both to detect all six anomaly types.

- **Multi-Hop Reasoning**: Several anomaly checks require dependency chains of length 3 or more. For example, detecting over-generation anomalies requires: (1) retrieving all transactions via paginated tool calls, (2) aggregating quantities per generator per vintage month, (3) retrieving the meter reading for each combination via a separate tool call, (4) loading the tolerance threshold from a workspace YAML config, and (5) comparing the aggregated total against the metered generation scaled by the tolerance. Double-count detection similarly chains: reading buyer claims from multiple YAML files, cross-referencing serials, then matching back to transactions via tool queries.

- **Conditional Constraints**: Each anomaly type has its own eligibility rule involving 2–3 fields across different sources. For instance, EXPIRED_CERT requires checking both the certificate expiry date and its status field against the transaction's trade date; PRICE_OUTLIER requires comparing the transaction price against a date-and-energy-type-specific reference from workspace files using a configurable standard-deviation multiplier.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (`report_file_exists`, `expired_cert_detection`, `over_generation_detection`, `off_hours_detection`, `failed_validation_detection`, `double_count_detection`, `precision`)
- Source-access: clean — Section 2 was solved using only `v3/prompt.md` plus the public `Task_Env.get_assistant_tools()` interface; no escalation to `env.py` was needed.
- Structural integrity: passed. Top-level contains only `README.md` and `v0..v3/`. Each version has only `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Issues found: none required code changes. The solver initially missed `DOUBLE_COUNT` recall because of a wrong YAML key guess; the canonical key is `claimed_rec_serials`, which is implicit in the prompt and discoverable from runtime artifacts. After correcting the solver, all criteria passed.
- Blockers: none.
