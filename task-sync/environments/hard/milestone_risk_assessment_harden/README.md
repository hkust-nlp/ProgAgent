## Task Topic

Flag high-risk project milestones by analyzing historical story point estimation accuracy, dependency mapping from Confluence, recent bug escape rates from QA, and team member churn data, generating a mitigation checklist for the next sprint planning session.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

**Structural dimensions used:**

- **Information Scattering**: Risk scoring requires combining tool-provided data (story points, bug phases, member statuses, dependency statuses) with workspace-only data (severity weights from Confluence docs, test coverage from QA CSVs, effective capacity from team JSON files) and configuration parameters (thresholds, normalization factors, weights from YAML/JSON config files).
- **Multi-Hop Reasoning**: Dependency chain of length ≥ 3: list milestones → get sprint history → get stories per sprint → compute estimation ratio; also: get team assignments → get each member's details → cross-reference with workspace capacity files → compute churn score.
- **Conditional Constraints**: Risk classification depends on configurable thresholds and multi-factor weighted scoring with dimension-specific normalization factors and coverage adjustment formulas.

## Harness Report

- v3 reward: 1.0 (110/110) after harness-verification pass
- Eval criteria count: 9 (csv_format, milestone_set, estimation_accuracy_scores, dependency_risk_scores, bug_escape_scores, team_churn_scores, overall_and_levels, mitigation_checklist, **final_response**)
- Source-access: clean — solver was authored using only `v3/prompt.md` and `Task_Env.get_assistant_tools()`; no escalation to `env.py` was needed.
- Section 1 structural integrity: passes — `v0..v3` differ only in the `SCALE` dict (rows_per_table 50/100/200/400, num_workspace_files 8/16/24/32); `env.py` and `prompt.md` are byte-identical across versions.
- Section 2 solvability: solver at `/tmp/solve_milestone_risk.py` produced `risk_assessment.csv` (136 rows at v3) + `mitigation_checklist.md` and submitted the `High-risk milestones: ...` final response, scoring `reward == 1.0` on first attempt with 7 HIGH-risk milestones identified.
- Section 3 env quality: one completeness gap found and fixed — `step()` accepted the `action` parameter but never read it, so the final-response requirement from `prompt.md` (`"High-risk milestones: <name>, ..."` prefix with names in descending risk order) was never evaluated. Added criterion `final_response` (10 pts, max_score now 110): checks exact prefix match and name order, gives partial credit for correct set in wrong order, checks "none"/"no high" phrasing when no HIGH milestones exist. Fix applied to `v0/env.py` and propagated byte-for-byte to `v1..v3`.
- Section 4 prompt quality: passes — no headings/bold/lists at top, no tool names or source-data filenames, scale-invariant phrasing throughout, output filenames and CSV column names explicit.
- Issues found and fixed: 1 — missing `final_response` criterion in `step()` (see Section 3 above).
- Blockers: none.

## Hardening (M0 + M2 + M3)

Applied on top of `environments/standard/milestone_risk_assessment`; `step()` scoring, `_compute_ground_truth()`, and all DB/scalable data generation are unchanged.

- **M2 mixed return shapes** (per-tool map):
  | tool | success shape | error shape |
  |---|---|---|
  | `list_milestones` | native deep-nested list object (`{"object": "list", "results", "has_more", "next_cursor"}`) | `_error` dict |
  | `get_stories_for_sprint` | native deep-nested list object, cursor pagination | `_error` dict |
  | `get_bugs_for_milestone` | native deep-nested list object, cursor pagination | `_error` dict |
  | `get_milestone_info` | JSON-encoded string of a nested record | `json.dumps(_error)` |
  | `get_dependencies` | JSON-encoded string of a nested list object | `json.dumps(_error)` |
  | `get_sprint_history` | MCP envelope (`{"meta", "content": [{"type": "text", "text": <json>}], "isError"}`) | `_error` dict |
  | `get_team_member` | plain `key: value` text | `_error` dict |
  | `get_team_assignments` | Python-repr string (single quotes; needs `ast.literal_eval`) | `_error` dict |
- **M3 deep nesting**: record fields live 3–4 levels deep in Notion-style property objects (`properties.Name.title[0].plain_text`, `properties.Status.select.name`, `properties.Assignee.relation[0].id`, `properties["Target Date"].date.start`). List tools use `has_more`/`next_cursor` cursor pagination instead of `total`/`total_pages`.
- **Error contract**: tools never raise. Not-found → `{"status": 404, "object": "error", "code": "object_not_found", "message", "request_id"}`; bad input → `400/validation_error` (e.g. `body.page should be an integer, instead was ''abc''.`). Errors share no keys with success payloads other than the spec-prescribed `"object"` discriminator on list-shaped successes.
- **verify()**: unwraps envelopes, `json.loads` / `ast.literal_eval` / key:value parsing, walks nested properties, follows cursor pagination. Reward **1.0 at v0 (241 tool calls) and v3 (1733 tool calls)**.

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 8 route-narrating paragraphs to 5: scenario/goal + scope, a pointer to the methodology/configuration documents as the authoritative spec, and the verbatim deliverable contract (CSV columns/rounding/sort, checklist structure, final-response format). Deleted: per-dimension formula walk-throughs and tool hand-holding ("retrieve the sprint history...", "look up the weight by dependency identifier..."). Those formulas were prompt-only rules, so (rule 4) they were moved into a new fixed workspace document `risk_methodology.md` written by `data.py` (`write_config_files`, additive only; per-version `data.py` files still differ only in `SCALE`).

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| csv_format | prompt ¶3 (verbatim contract: filename, columns) |
| milestone_set | prompt ¶1 + risk_methodology.md "Scope" (upcoming/in_progress) |
| estimation_accuracy_scores | risk_methodology.md §1 + risk_config.yaml normalization_factor |
| dependency_risk_scores | risk_methodology.md §2 + confluence_dep_*.md weights + risk_config.yaml blocking factor |
| bug_escape_scores | risk_methodology.md §3 + qa_report_*.csv coverage + risk_config.yaml escaped_phases/normalization |
| team_churn_scores | risk_methodology.md §4 + team_capacity_*.json + risk_config.yaml churn window/reference date |
| overall_and_levels | risk_methodology.md "Overall score and risk level" + scoring_weights.json + risk_config.yaml thresholds; rounding also in prompt ¶3 |
| mitigation_checklist | prompt ¶4 (verbatim contract) + risk_methodology.md "Mitigation actions" + risk_config.yaml mitigation_action_threshold |

Negative-path smoke tests (all pass): 404 error dicts on nonexistent milestone/sprint/member ids in each encoding (JSON-string, envelope, repr, key:value tools), `validation_error` on bad enum status, non-integer `page`, missing `sprint_id`, and dict-typed `page_size`; no tool raises.
