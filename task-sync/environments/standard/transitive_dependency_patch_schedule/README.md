## Task Topic

Outdated transitive dependencies create hidden risks. Cross-reference SBOM component lists, vulnerability database feeds, library release notes, and production deployment manifests to generate a prioritized patch schedule for high-severity vulnerabilities in indirect dependencies.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Scaling ratios: rows_per_table follows 1×/2×/4×/8×; num_workspace_files follows base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across workspace files and tool calls. SBOM files provide dependency types and parent relationships; vulnerability CSV feeds provide CVE-to-component mappings and severity levels; configuration files provide prioritization formulas, severity weights, and service criticality tiers. Meanwhile, CVSS numeric scores, fix versions, and active production deployment status are only available through tool queries.

- **Multi-Hop Reasoning**: Determining whether a transitive dependency is deployed in production requires a dependency chain of length ≥ 3: read SBOM to identify transitive component → trace its parent component → query deployment tool to check if the parent's direct ancestor is actively deployed in a production service → cross-reference service criticality configuration to compute priority score.

- **Conditional Constraints**: Eligibility for the patch schedule depends on multiple conditions across different data sources: the component must be transitive (from SBOM), the vulnerability must be Critical or High severity (from CSV feeds), a fix version must exist (from tool query), and the component must be deployed in at least one active production service (from tool query). Prioritization thresholds and multipliers live in workspace configuration files.

## Harness Report

- **v3 reward**: 1.0 (100/100)
- **Eval criteria count**: 7 (output_file_format=10, cve_identification=20, patched_versions=15, affected_services=15, priority_scores=20, ranking_order=10, response_summary=10)
- **Source-access escalation**: not needed for solving — solver succeeded using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`. `env.py` was opened during Section 3 review only.
- **Issues found and fixed**: none. Structural integrity passed (`diff` clean for `env.py`/`prompt.md`; only `SCALE` differs in `data.py`). Prompt-step alignment is complete: every prompt requirement (CVE filter, transitive-only, fix-version-required, active-production filter, priority formula, sort order, CSV columns, decimal precision, semicolon-joined alphabetical services, summary content) maps to a scoring criterion, and `step` derives ground truth dynamically from the current DB/workspace. Prompt formatting is fully prose, scale-invariant, with no tool names or internal filenames.
- **Blockers**: none.
