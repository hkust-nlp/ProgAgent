## Task Topic

Audit disaster recovery readiness by synchronizing database replication lag metrics, storage snapshot schedules, DNS failover test logs, and regional health check histories across providers to generate a compliance gap document.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

The task uses the following structural dimensions:

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Actual metric values (replication lag, snapshot status, DNS results, health checks) are accessible only via tool calls, while per-service DR requirements (backup retention thresholds, designated failover regions, last drill dates) exist solely in workspace configuration files distributed across JSON, CSV, YAML, and TXT batch files. Compliance thresholds by tier and severity classification rules are in separate workspace policy files.

- **Multi-Hop Reasoning**: Several gap categories require dependency chains of length 3 or greater. For example, DR drill overdue detection requires reading the service's last drill date from a workspace batch file, obtaining the reference date from the policy JSON document, reading the tier's maximum allowed drill age from the thresholds YAML, and then computing and classifying the deviation via the severity matrix CSV. Similarly, retention shortfall requires cross-referencing snapshot tool data with workspace configuration files and threshold definitions.

- **Conditional Constraints**: Gap identification depends on tier-specific thresholds (platinum / gold / silver) defined in workspace configuration, with severity classification governed by a deviation-percentage matrix that maps continuous ranges to discrete severity levels per gap category.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (report_structure 10, gap_completeness 25, gap_precision 20, metric_accuracy 15, severity_accuracy 15, summary_response 15)
- Section 1 Structural Integrity: pass. Top-level contains only README.md + v0..v3. Each v_n contains exactly data.py/env.py/prompt.md. env.py and prompt.md are byte-identical across versions; data.py differs only in the SCALE block.
- Section 2 Solvability: pass on first solver run at v3 scale (800 services, 40 config batches). Solver used only v3/prompt.md plus get_assistant_tools(); no env.py/data.py reads were required.
- Section 3 Env Quality: not flagged. Step has 6 criteria, all aligned with deliverables in prompt.md (CSV report + 4-line summary). Scale-derived ground truth via current data.db / workspace.
- Section 4 prompt.md Quality: not flagged. No headings, lists, code, or tool/source-file names; deliverable filename and column order specified in prose; scale-invariant wording.
- Issues found and fixes: none.
