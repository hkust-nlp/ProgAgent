## Task Topic

Triage of intermittent VoIP call drops involves correlating real-time packet loss metrics from network probes, SIP server error logs, endpoint firmware versions, and wireless access point client health scores to isolate degradation sources, producing a fault localization report for engineering teams.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 12                  |
| v1      | 160           | 24                  |
| v2      | 320           | 36                  |
| v3      | 640           | 48                  |

The scaling ratios are: rows v1=2×, v2=4×, v3=8× of v0 base; workspace files v1=base+N, v2=base+2N, v3=base+3N where N=12 (the v0 base).

**Structural dimensions used:**

- **Conditional Constraints**: Fault severity classification depends on multi-table conditions (packet loss thresholds crossed with SIP error codes, AP health scores, firmware buggy lists, and server load levels). Thresholds and firmware compatibility data live in workspace config files (thresholds.yaml, firmware_compatibility.json, severity_rules.md).
- **Information Scattering**: Endpoint fault classification requires correlating tool-retrieved data (probe metrics, SIP errors, endpoint info, AP details) with file-based data (threshold configs, firmware compatibility, probe snapshot CSVs, AP health report JSONs). Neither source alone is sufficient.
- **Multi-Hop Reasoning**: The dependency chain includes: list probes → get probe metrics per probe → get endpoint info per endpoint → get AP details per AP → cross-reference with firmware compatibility and threshold configs → classify severity and fault source.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria count: 6 (report_structure 15, endpoint_identification 25, severity_accuracy 20, fault_source_accuracy 20, response_summary 10, numeric_precision 10)
- Source access: clean (no step-6 escalation; only `v3/prompt.md` plus `get_assistant_tools()` were consulted to write the solver).
- Section 1 structural integrity: passed; `diff` confirmed `env.py` and `prompt.md` byte-identical across v0..v3, and only `SCALE` differs across `data.py`.
- Section 2 solvability: passed on first run. The solver computes per-source severity (only the rules whose semantics belong to that source per `severity_rules.md`), picks the highest severity, and tie-breaks `network > sip_server > wireless > firmware`. This matched `step()`'s ground-truth fault-source attribution for all 475 faulty endpoints.
- Issues found: none requiring code fixes. Runtime artifacts (`data.db`, `workspace/`, `__pycache__/`) and the temporary solver were removed during clean-up.
