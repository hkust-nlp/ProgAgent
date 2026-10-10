## Task Topic

Calculate monthly interconnect settlement charges by cross-referencing call detail records (CDRs) from multiple switches, current bilateral agreement rates, traffic routing tables, and prior period dispute logs, outputting a reconciled invoice summary for each partner carrier.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Critical fields are split across database tables (CDR records, bilateral rates, dispute statuses, switch ownership) and workspace files (quality scores, approved dispute credits, rate adjustments, routing surcharges). Neither source alone is sufficient; the agent must cross-reference both to compute correct charges.

- **Multi-Hop Reasoning**: The settlement computation requires a dependency chain of length ≥ 4: retrieve partner switches → query CDRs involving those switches → look up bilateral rate per call type → apply rate adjustment from YAML → check routing penalty from CSV → retrieve quality score from batch files → compute charge. Dispute credits add another chain: query resolved disputes → read memo files for approved credit amounts.

- **Conditional Constraints**: Calls below the minimum billable duration are excluded; quality scores below a threshold trigger a penalty multiplier; tier discounts depend on aggregate volume thresholds; only resolved disputes in the current billing period qualify for credits.

## Harness Report

- **Section 1 (Structural Integrity):** Pass. Top-level contains only `README.md` and `v0..v3/`. Each version directory contains exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- **Section 2 (Solvability at v3):** Pass. Wrote a solver under `/tmp/solve_interconnect_invoice_reconciliation.py` using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. Solver loaded settlement rules, tier discounts, rate adjustments YAML, routing penalties CSV, CDR quality batch CSVs, and dispute memo TXTs from `workspace/`, joined with DB tables, applied min-duration / quality / routing / rate-adjustment / tier / dispute-credit logic per the prompt, and submitted via `env.step(...)`. **Reward: 1.0** on first valid run.
- **Section 3 (Env Quality):** No issues observed. Solver achieved full score across all 7 eval criteria, indicating prompt-step alignment, no over-strict matching, and scale-invariant ground truth (re-derived from `data.db` / workspace each run).
- **Section 4 (Prompt Quality):** Pass. `prompt.md` is prose-only with no headings, bold markers, bullet lists, code, tool names, env internals, or absolute counts. Output filename `invoice_summary.csv` and exact column list/precision are specified.
- **Eval criteria count:** 7 (`file_format` 10, `carrier_set` 15, `minutes_accuracy` 15, `charges_accuracy` 20, `dispute_credits_accuracy` 15, `net_settlement_accuracy` 15, `response_summary` 10; total 100).
- **Source-access escalation:** Not needed — task solved using only `v3/prompt.md` plus the public tool list.
- **Issues found / fixes applied:** None. No edits to any version file were required.
- **Cleanup:** Removed `data.db`, `workspace/`, `__pycache__/` from every `v_n/`, and removed the temporary solver. No blockers.
