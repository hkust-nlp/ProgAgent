## Task Topic

Verify manuscript originality by comparing submission full-text against open-access repositories, preprint servers, citation matching scores, and retraction watchlists to flag potential plagiarism cases for editorial review.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

The task uses these structural dimensions:

- **Information Scattering**: Scoring weights and thresholds live in YAML/JSON configuration files; declared-source lists are embedded in per-manuscript submission text files; similarity scores and retraction watchlist data are only accessible via tool calls. No single source contains all the information needed to compute a risk score.
- **Multi-Hop Reasoning**: The dependency chain spans at least four steps: read scoring config (file) → retrieve manuscript metadata (tool) → read declared sources from submission file (file) → query similarity matches (tool) → check retraction watchlist per author (tool) → apply discipline adjustment (file) → compute final score.
- **Conditional Constraints**: Flagging depends on a composite score that combines weighted similarity components, a declared-source discount factor, discipline-specific multipliers, and additive retraction penalties with per-author deduplication by highest severity.
- **Deliverable Constraints**: The CSV requires a fixed column order, four-decimal-place scores, and manuscript-ID ascending sort. The JSON array demands a specific nested structure and a multi-key sort (score descending, date ascending, ID ascending for ties).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 6 (report_structure, risk_score_accuracy, flag_status_correctness, flagged_cases_completeness, flagged_cases_ordering, response_summary)
- Source-access: clean — solver used only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`. No escalation to `env.py` was needed.
- Structural integrity: confirmed. `env.py` and `prompt.md` are byte-identical across v0/v1/v2/v3; `data.py` differs only in the `SCALE` block (rows ×1/2/4/8, files +0/N/2N/3N).
- Issues found: none. Task is solvable, deliverables match prompt, scoring is scale-invariant.
- Cleanup: all `data.db`, `workspace/`, `__pycache__/` removed from every version directory; tmp solver deleted.
