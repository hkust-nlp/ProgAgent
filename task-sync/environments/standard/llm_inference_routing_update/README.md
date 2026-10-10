## Task Topic

Route LLM inference requests cost-effectively by watching real-time API latency percentiles, comparing per-million-token prices, enforcing prompt-length thresholds, and tracking SLA violation incidents to update dynamic routing rules per model tier.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 10                  |
| v1      | 100           | 20                  |
| v2      | 200           | 30                  |
| v3      | 400           | 40                  |

Scaling ratios follow the standard progression: rows scale at 1x/2x/4x/8x and workspace files at base/base+N/base+2N/base+3N where N = base (10).

**Structural dimensions used:**

- **Conditional Constraints:** Action determination depends on cross-referencing latency percentiles against tier-specific SLA thresholds (from config), open incident counts and severity levels (from tool queries), and cost-effectiveness scores (from a formula combining tool data and workspace-only fields). The precedence chain deactivate > demote > flag_review > promote > maintain requires multi-condition evaluation.

- **Information Scattering:** Critical fields are deliberately split between tools and workspace files. Model pricing and latency percentiles come only from tools; quality benchmark scores, client satisfaction, estimated financial impact, and client preference lists come only from workspace files in four different formats (YAML, CSV, JSON, Markdown). Decision thresholds and formula weights live in three separate config files (YAML, JSON, CSV). No single source suffices.

- **Multi-Hop Reasoning:** The cost-effectiveness formula chains: read provider adjustment factor (CSV config) → look up model pricing (tool) → read quality score (YAML workspace) → read and average satisfaction across multiple window files (CSV workspace) → apply formula weights (JSON config) → compute score. The violation report similarly chains: identify violating models (tool latency + config thresholds) → parse incident detail files for impact dollars (Markdown) → cross-reference client preferences (JSON) → aggregate per-violator.

- **Deliverable Constraints:** Output CSV requires specific column names, sort order (tier alphabetical → priority ascending → model_id ascending), numeric formatting (2dp latency, 4dp cost score), and lowercase yes/no for compliance. The JSON report requires exact key names, a specific percentage string format, and descending-impact ordering of violators.

## Harness Report

- v3 reward: 1.0 (100/100).
- Eval criteria count: 6 (sla_compliance_identification 15, cost_effectiveness_scores 15, action_determination 20, routing_rule_updates 20, violation_report 15, response_summary 15).
- Source-access: clean. Solver used only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Section 1 structural integrity passed: `diff` confirmed `env.py` and `prompt.md` are byte-identical across v0..v3, and `data.py` differs only in the `SCALE` block (rows 50/100/200/400, files 10/20/30/40 — matching the 1x/2x/4x/8x and +0/+N/+2N/+3N invariant with N=10).
- Section 3/4 review found no issues: `step` derives ground truth from `data.db`/workspace at runtime, criteria align one-to-one with prompt deliverables, no hard-coded scale assumptions, no over-normalization. Prompt is prose-only, scale-invariant, no tool/source-filename leakage.
- Cleanup: removed all `data.db`, `workspace/`, `__pycache__/` artifacts from v0..v3 and the temporary solver.
- No fixes required.
