## Task Topic

Identify high-risk orders for manual fraud review. Cross-reference customer purchase history, IP geolocation mismatch flags, real-time card issuer decline codes, and shipping address verification scores to output a prioritized queue of suspicious orders with recommended verification steps.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 8                   |
| v1      | 200            | 16                  |
| v2      | 400            | 24                  |
| v3      | 800            | 32                  |

Structural dimensions used:

- **Information Scattering**: Customer fraud history (previous fraud counts, chargeback records, account age) lives exclusively in workspace CSV batch files, while per-order risk signals (IP geolocation checks, card issuer responses, address verification scores) are only accessible through tool calls. Transaction pattern flags (rapid ordering, unusual amounts, multiple addresses) are in separate workspace JSON batch files. Solving the task requires combining all three sources.
- **Multi-Hop Reasoning**: The agent must chain: list pending orders (tool) → retrieve IP/card/AVS signals per order (tools) → look up decline-code severity from a JSON reference file → look up AVS tier from a CSV reference file → read customer risk profiles from batch CSVs → read transaction patterns from batch JSONs → apply scoring weights from a YAML config → compute composite scores → map triggered conditions to verification actions from a Markdown procedures document → produce sorted output.
- **Conditional Constraints**: Risk classification depends on configurable thresholds (high ≥ 50, medium ≥ 30) and per-factor caps from the YAML config. Recommended verification actions are conditionally triggered by specific indicator values and severity thresholds defined in the procedures document.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (file_structure, order_ids, risk_levels, risk_scores, sort_order, recommended_actions, response_summary)
- Source-access: clean. The solver was written from `v3/prompt.md` plus `Task_Env.get_assistant_tools()` only; no escalation to `env.py` was required.
- Issues found: none. Structural integrity holds (only `SCALE` differs across versions; `env.py` and `prompt.md` byte-identical). Data generation succeeds at v3. Step function derives ground truth from current data with no hard-coded counts. Prompt has no headings, no lists for deliverables, no tool/file leaks (besides workspace artifact filenames, which are deliverables/output names), and is scale-invariant ("all pending orders").
- Fixes applied: none.
- Blockers: none.
