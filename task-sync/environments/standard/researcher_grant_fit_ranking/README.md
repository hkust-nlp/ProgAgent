## Task Topic

Match researchers with open grant calls by scanning funding opportunity databases, parsing PI publication records, querying institutional research expenditure reports, and checking collaborator network graphs to output a ranked list of high-fit funding calls per researcher.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

The v0→v3 ratios follow the standard progression: rows scale at 2×, 4×, 8× the base; workspace files scale at base+N, base+2N, base+3N where N = base (8).

### Structural Dimensions

- **Information Scattering**: Task-critical data is split across database tables (accessed only through tools) and workspace files. Researcher profiles live in the database, but their supplementary keywords and certifications are only available in JSON dossier files. Institution tier classifications are in a CSV registry file, while eligibility rules per agency are in a separate JSON file. Scoring weights and thresholds reside in a YAML configuration. No single source is sufficient to determine eligibility or compute scores.

- **Multi-Hop Reasoning**: Determining whether a researcher is eligible for a grant requires a dependency chain of length ≥ 4: (1) query the researcher's institution_id via tool → (2) look up the institution's tier from the CSV registry → (3) read the agency's tier requirement from the eligibility rules JSON → (4) read the researcher's certifications from their dossier JSON → (5) query the department's expenditure via tool to check the funding ratio threshold. The scoring computation adds further hops through the field taxonomy, publication records, and collaborator networks.

- **Conditional Constraints**: Eligibility depends on business rules spanning multiple tables and files — career stage match, h-index threshold, institution tier vs. agency requirement, certification requirements, and minimum external funding ratio. Each rule draws on a different data source.

## Harness Report

- v3 reward: 1.0 (105/105)
- Eval criteria: 6 (output_format, pair_coverage, score_accuracy, rank_correctness, top_n_filtering, response_summary)
- Source-access: clean — solver succeeded using only `v3/prompt.md` plus `Task_Env.get_assistant_tools()`; no escalation to `env.py`/`data.py` was needed.
- Structural integrity: passed. Top-level holds only `README.md` and `v0/..v3/`; each version contains only `data.py`, `env.py`, `prompt.md`; `env.py` and `prompt.md` are byte-identical across versions; `data.py` differs only in the `SCALE` block.
- Issues found: none. No fixes were required.
- Blockers: none.
