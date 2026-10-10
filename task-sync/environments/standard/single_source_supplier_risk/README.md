## Task Topic

Monitor for single-source supplier risk by analyzing purchase order history, supplier financial health scores, geopolitical risk indices, and raw material inventory levels, outputting a prioritized mitigation list of critical components needing alternate suppliers.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Financial health scores, quality audit scores, and alternate supplier data live exclusively in workspace files (CSV, TXT, JSON, YAML), while purchase order history, inventory levels, and geopolitical risk indices are only accessible through tool calls. The agent must cross-reference both sources to compute composite risk scores.
- **Multi-Hop Reasoning**: The agent must follow a dependency chain of length ≥ 3: list components → query POs per component to identify single-source → get supplier details → get country risk → combine with file-based financial/quality data → compute weighted composite score → assign tier → look up recommended action based on tier and alternate qualification status.
- **Conditional Constraints**: Risk tier assignment depends on composite score thresholds from a config file, and recommended actions are determined by a two-dimensional lookup (risk tier × alternate supplier qualification status) defined in the scoring policy document.

## Harness Report

- v3 reward: 1.0 (100/100)
- Number of eval criteria: 7 (csv_structure 10, single_source_identification 20, composite_risk_scores 20, correct_sorting 10, risk_tier_assignment 15, response_total_count 10, response_top5 15)
- Source-access path: clean. Solver was written using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py` or `data.py` was required.
- Structural integrity: passed. `v0..v3` each contain only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Solvability: solver at `/tmp/solve_single_source_supplier_risk.py` (now removed) reached `reward == 1.0` on the v3 scale (800 components, 335 single-source).
- Env quality (Section 3): coverage and completeness aligned with the prompt; ground truth recomputed dynamically from `data.db` and workspace files (scale-invariant); composite-score tolerance of 0.5 is reasonable.
- Prompt quality (Section 4): prose-only, no headings/bullets, no tool-name leakage; only deliverable filename and well-known workspace file prefixes are mentioned.
- Issues found / fixes: none. No edits were necessary.
- Blockers: none.
- Cleanup: removed `data.db`, `workspace/`, `__pycache__/` from all version directories and removed the temporary solver script.
