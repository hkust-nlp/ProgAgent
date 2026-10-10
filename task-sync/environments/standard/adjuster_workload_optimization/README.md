## Task Topic

Optimize independent adjuster assignment by analyzing incoming claim severity scores, adjuster specialty matrices, current caseload dashboards, and geographic territory maps to minimize average settlement time, generating a daily assignment schedule.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 30            | 8                   |
| v1      | 60            | 16                  |
| v2      | 120           | 24                  |
| v3      | 240           | 32                  |

Scaling ratios follow the standard progression: rows double each version (v1 = 2×, v2 = 4×, v3 = 8× base), workspace files grow by the base count N = 8 each version (v1 = base + N, v2 = base + 2N, v3 = base + 3N).

**Structural dimensions used:**

- **Conditional Constraints**: Adjuster eligibility depends on certification level meeting the severity-tier minimum (derived from a severity-tiers JSON and a certification-requirements CSV), proficiency exceeding the policy threshold, travel time within limits, and remaining capacity (accounting for both existing caseload and intra-batch assignments). Scoring bonuses apply conditionally: same-region bonus requires matching geographic regions, urgency multiplier triggers only when both the priority flag is urgent and territories match exactly, and the platinum bonus activates only for platinum-tier customers assigned to senior/expert adjusters.

- **Information Scattering**: Claim severity, type, and territory come exclusively from tool calls; claim priority flags and customer tiers come exclusively from workspace CSV files. Adjuster specialties and settlement history are tool-only; current caseload counts are workspace-only (JSON snapshots). Territory-to-region mappings exist only in workspace YAML files, while travel times between territories are only available via tools. The assignment policy weights and rules are split across a YAML config and a plain-text rules file.

- **Multi-Hop Reasoning**: Assigning a single claim requires: (1) retrieving the claim via tool → (2) looking up its severity tier from the JSON config → (3) checking certification requirements from the CSV → (4) fetching adjuster specialties via tool → (5) reading caseload from workspace JSON → (6) computing travel time via tool → (7) reading region from workspace YAML for the region bonus → (8) reading priority/customer tier from workspace CSV for conditional bonuses → (9) consulting settlement history via tool for the history scoring component. This chain of length ≥ 3 repeats for every claim–adjuster pair.

## Harness Report

- **v3 reward**: 1.0 (100/100).
- **Number of eval criteria**: 7 (`file_structure`, `assignment_count`, `pairings`, `certification_compliance`, `caseload_compliance`, `score_accuracy`, `response_summary`).
- **Solver path**: The solver succeeded using only `v3/prompt.md` plus `Task_Env(...).get_assistant_tools()` for the public interface. After an initial run scored 0.62 with 9 mismatched pairings and 99 mismatched scores, the harness escalated under Section 2 step 6 to inspect `v3/env.py`'s `step()`, since the prompt and rules read clearly and the solver matched them.
- **Issue found and fix**: The travel-time direction in `step()` (and the shared `_compute_assignments` helper) was indexed `claim_territory → base_territory`, while the prompt (and the `assignment_rules.txt` workspace file) explicitly state "the travel time from their base territory to the claim territory". Because the synthesized `travel_times` table is asymmetric (T_a→T_b ≠ T_b→T_a), the two directions yielded different scores. Fix: in `v0/env.py`, swapped the lookup order in `_compute_assignments` so the primary key is `travel_data[base_tid][ctid]` (with the reverse direction kept only as a defensive fallback). Re-propagated `env.py` byte-for-byte to `v1/v2/v3` and confirmed `diff` clean.
- **Post-fix verification**: Re-ran `data.py` at v3 scale, re-ran the solver — `reward == 1.0`, all 7 criteria pass.
- **Cleanup**: All `data.db`, `workspace/`, `__pycache__/` removed from each `v_n/`; `/tmp/solve_adjuster_workload_optimization.py` deleted.
