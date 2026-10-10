## Task Topic

Analyze customer dropped call complaints by cross-referencing network performance logs, cell tower maintenance schedules, 3rd-party signal strength maps, and subscriber location data to identify persistent coverage gaps, outputting a prioritized tower upgrade list.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

**Structural dimensions used:**

- **Information Scattering**: Complaint counts, network metrics, and maintenance records are available only through tool calls, while third-party signal survey measurements and device-level call drop reports live exclusively in workspace files (CSV and JSON). Scoring criteria, regional multipliers, and technology upgrade paths are in separate config files (YAML, JSON, CSV, TXT). No single source contains all information needed to score a tower.

- **Multi-Hop Reasoning**: The agent must chain data from multiple sources in sequence: complaint summary (tool) → qualification check (config thresholds) → tower details including coordinates (tool) → signal survey measurements near those coordinates (workspace CSV) → device signal readings by tower ID (workspace JSON) → weighted scoring with regional multipliers (workspace CSV) → maintenance discount check (tool) → final ranking with tier assignment and upgrade recommendation (workspace JSON config). This forms a dependency chain of length ≥ 4.

- **Conditional Constraints**: Tower qualification depends on meeting both a minimum complaint count and a minimum average severity threshold. The maintenance discount conditionally applies only when a tower has active or scheduled maintenance. Priority tier assignment depends on score thresholds. Primary issue determination requires comparing weighted contributions with alphabetical tie-breaking.

- **Deliverable Constraints**: The output CSV must have exact column names, priority scores rounded to exactly 2 decimal places, rows sorted by priority_score descending with tower_id ascending as tie-breaker, and ranks starting from 1. The final response must include specific summary statistics.

## Harness Report

- **v3 reward: 1.0 (100/100)**
- **Eval criteria: 7** — file_format (10 pts), qualifying_towers (20 pts), priority_scores (20 pts), ranking_order (15 pts), priority_tiers (15 pts), primary_issues (10 pts), recommended_upgrades (10 pts)

**Section 1 — Structural integrity:** passed. Top-level contains exactly README.md + v0..v3/. Each v_n/ contains exactly data.py, env.py, prompt.md. `diff v0/env.py vN/env.py` and `diff v0/prompt.md vN/prompt.md` all produce no output. data.py diffs only in the two SCALE lines: rows_per_table 100→200→400→800, num_workspace_files 10→20→30→40 (v0→v1→v2→v3). No stale databases, workspace dirs, or bytecode caches found.

**Section 2 — Solvability at v3:** `python data.py --db_path data.db --workspace workspace` generated 800 towers, 3200 complaints, 2400 network logs, 800 maintenance records, 40 workspace files without error. Solver written at /tmp/solve_dropped_call.py using only v3/prompt.md + get_assistant_tools() + direct reads of data.db and workspace files. Solver produced 287 qualifying towers; top tower TWR-0786 (New Wendy-Z89) with priority_score 90.89; tier breakdown: 23 critical, 45 high, 170 medium, 49 low. First solver run returned reward 1.0 — no escalation to env.py needed (step 6 not invoked during debugging; env.py read only for the Section 3 quality review).

**Section 3 — Env quality:** all 7 step criteria map to explicit prompt requirements; no hidden criteria. Ground truth re-derived from data.db + workspace at runtime (scale-invariant). Score tolerance is ±0.05 (float-safe). Tier and issue comparisons use `.strip().lower()` on agent output, matching lowercase ground-truth strings — not over-normalising. No hard-coded counts or regex patterns.

**Section 4 — prompt.md quality:** opens with prose (no title/heading). No bold section headers, no numbered/bulleted deliverable lists. No tool names or internal filenames (config files referenced as "configuration documents" / "technology upgrade paths configuration"). Output filename and exact column names specified. All wording is scale-invariant (no absolute row/tower counts).

**Issues found and fixed:** none. All checks passed on first pass; v0/ was not modified.

**Cleanup:** removed data.db, workspace/, and __pycache__/ from all four v_n/ directories. Solver file at /tmp/solve_dropped_call.py left in /tmp (outside task tree).

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/dropped_call_gap_analysis`; `step()`, `_compute_ground_truth()`, and all criterion weights are unchanged.

- **M5 unbounded bulk export**: new tool `export_complaint_dataset()` returns the entire complaint dataset (one record per complaint, joined with tower name, region, and technology) as ONE JSON string with no pagination — ~17.5k tokens at v0 (survivable but expensive) up to ~140k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and aggregated before printing). It is genuinely sufficient for the core qualification step (per-tower complaint count + unrounded average severity). The paginated `get_complaint_summary` and all per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (per-tool map, stable):
  - native dict: `list_towers`, `get_complaints_for_tower`, `get_subscriber_info` (3/8)
  - JSON-encoded string: `get_complaint_summary`, `export_complaint_dataset`
  - MCP envelope (`content[0].text` is JSON): `get_tower_details`
  - plain `key: value` text: `get_network_metrics`
  - Python-repr string (`ast.literal_eval`, not `json.loads`): `get_maintenance_records`
- **Error contract**: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` (JSON-string form for the two JSON-string tools) — no keys shared with any success shape. Not-found → 404 `object_not_found`; bad `page`/`tower_id`/`subscriber_id` types or values → 400 `validation_error`. Descriptions state what each tool returns, never how it is encoded.
- verify() rewritten to consume the new surface (bulk export once in memory; envelope/kv/repr parsing per tool): **reward 1.0 at v0 (106 tool calls) and v3 (862 tool calls)**. Negative-path smoke tests pass (404 dict errors, wrong-typed page/id, JSON-string error form, repr not json-parseable).

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 6 route-narrating paragraphs to 4: scenario/goal, a pointer to the scoring methodology + configuration documents as the authoritative specification, the verbatim deliverable contract (output filename, exact column list, two-decimal rounding, sort key + tie-breaker, rank definition, recommended-upgrade source — all preserved word for word), and the verbatim final-response requirement. Deleted: tool hand-holding (complaint summary endpoint walkthrough), per-file navigation ("A YAML file lays out... A CSV file provides..."), sequencing scaffolds, and formula restatements that are verifiably present in `upgrade_scoring_criteria.yaml` (dimension formulas incl. the 0.5-degree box, thresholds, discount rule, primary-issue rule, tier boundaries).

`data.py` change (additive only, SCALE blocks preserved per version): new fixed workspace document `upgrade_scoring_methodology.md` capturing the rules previously stated only in the prompt — the weighted-sum assembly of the four dimension scores, the regional priority multiplier application (with 1.0 default), maintenance-discount ordering, rounding, tier-assignment semantics on the rounded score, and the before-multiplier convention for the primary-issue comparison.

Completeness audit (step() criterion -> info source):
| criterion | source |
|---|---|
| file_format | prompt (verbatim contract); also `upgrade_scoring_criteria.yaml` output block |
| qualifying_towers | `upgrade_scoring_criteria.yaml` qualification_thresholds + `tower_classification_rules.txt` + `upgrade_scoring_methodology.md` (unrounded mean) |
| priority_scores | `upgrade_scoring_criteria.yaml` formulas/weights + `upgrade_scoring_methodology.md` (assembly, regional multiplier, discount, rounding) + `regional_budget_priorities.csv` |
| ranking_order | prompt (verbatim sort spec) |
| priority_tiers | `upgrade_scoring_criteria.yaml` priority_tiers + `upgrade_scoring_methodology.md` (tier semantics) |
| primary_issues | `upgrade_scoring_criteria.yaml` primary_issue_rule/mapping + `upgrade_scoring_methodology.md` (before-multiplier convention) |
| recommended_upgrades | `technology_upgrade_paths.json` + prompt (verbatim sentence) |
