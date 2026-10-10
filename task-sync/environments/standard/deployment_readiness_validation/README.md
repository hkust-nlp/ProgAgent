## Task Topic

Validate microservice deployment readiness by cross-referencing container image vulnerability scans, infrastructure resource quotas, dependency service health checks, and change request approvals to generate a go/no-go deployment manifest.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

The v0 base values are `base_rows = 50` and `base_files = 10` (N = 10). Rows scale as 1x/2x/4x/8x; workspace files scale as base/base+N/base+2N/base+3N.

**Structural dimensions used:**

- **Conditional Constraints**: Go/no-go eligibility depends on cross-referencing vulnerability severity counts, cumulative risk scores, resource utilization projections, dependency health ratios, and change request approval counts against thresholds defined in workspace policy files. A priority-level override imposes stricter vulnerability rules on critical-priority services.
- **Information Scattering**: Deployment resource requests (CPU, memory) live in workspace files across five formats (YAML, JSON, CSV, TXT, MD). Vulnerability scans, resource quotas, dependency health, and change request statuses are only accessible via tool calls. Policy thresholds and risk scoring tables are in separate workspace configuration files. Namespace reserved buffers are in yet another config file. Solving requires combining all of these sources.
- **Multi-Hop Reasoning**: For each service the agent must: read deployment request file → extract service ID and requested resources → call tool for service info (get priority) → call tool for vulnerabilities → apply risk scoring from workspace CSV → call tool for namespace quotas → add buffer from workspace JSON → call tool for dependencies → call tool for change requests → apply all policy rules from workspace YAML → produce decision. This is a dependency chain of length 5+ per service.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 6 (manifest_structure, go_nogo_decisions, vulnerability_risk_scores, per_service_checks, manifest_summary, response_service_decisions).
- Source-access during solvability check: clean (no env.py escalation needed; solver written from prompt.md + get_assistant_tools()).
- Section 1 (structural integrity): clean - byte-identical env.py / prompt.md across v0..v3; data.py differs only in SCALE.
- Section 2: solver wrote deployment_manifest.json with all GO/NO-GO decisions, four check fields, vulnerability risk scores, and a properly formatted final response; reached reward 1.0 on the first verified attempt (one initial Python error from misreading the wrapped tool return shape was solver-side and was corrected without inspecting env.py).
- Section 3 (env quality): step() criteria all map to explicit prompt requirements; ground truth derived dynamically from data.db / workspace; no hard-coded counts or scale assumptions; tolerance on vulnerability_risk_score (<0.1) is reasonable.
- Section 4 (prompt quality): no headings, no bulleted/numbered lists, computation described in prose, no tool names or env.py internals leaked, deliverable filename and field names explicit, scale-invariant wording ("every pending deployment request").
- No fixes were required.
