## Task Topic

Generate a weekly referee assignment roster by cross-referencing referee availability logs, their certification levels for different match types, historical team-referee conflict records, and venue locations to ensure compliant and conflict-free officiating for all fixtures.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 25            | 10                  |
| v1      | 50            | 20                  |
| v2      | 100           | 30                  |
| v3      | 200           | 40                  |

Scaling ratios: rows_per_table follows 1x/2x/4x/8x; num_workspace_files follows base/base+N/base+2N/base+3N where N=10 (base).

Structural dimensions used:

- **Conditional Constraints**: Referee eligibility depends on certification level vs. match type requirement (from workspace config), active conflict status (from DB), travel distance vs. maximum threshold (from workspace CSV), and per-referee weekly assignment caps.
- **Information Scattering**: Fixture details, referee profiles, certifications, and conflicts live in the database (tool-only access). Availability schedules, the travel distance matrix, and assignment policy rules reside in workspace files. Both sources are required to determine any single assignment.
- **Multi-Hop Reasoning**: For each fixture: retrieve fixture details (tool) -> look up venue city (tool) -> read travel matrix (file) -> check referee home city (tool) -> compare distance against policy threshold (file). Certification check requires: fixture match_type (tool) -> match_requirements.json (file) -> referee certifications (tool) -> numeric comparison.

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (`roster_file_exists`, `correct_columns`, `all_fixtures_present`, `fixture_metadata_accuracy`, `referee_assignment_accuracy`, `referee_name_accuracy`, `sort_order`)
- Source-access escalation: not needed. Solver succeeded using only `v3/prompt.md` + `Task_Env.get_assistant_tools()`.
- Structural integrity: PASS. `env.py` and `prompt.md` byte-identical across v0..v3; `data.py` differs only in the `SCALE` block.
- Issues found: none. No fixes required.
- Blockers: none.
