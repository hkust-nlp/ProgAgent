## Task Topic

Optimize daily technician schedules by cross-referencing live vehicle GPS locations, real-time traffic data, job priority tiers, and parts inventory levels at service vans to minimize travel time and missed appointments, producing a validated route sequence for each technician.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 15            | 8                   |
| v1      | 30            | 16                  |
| v2      | 60            | 24                  |
| v3      | 120           | 32                  |

Scaling ratios follow the standard progression: rows scale as 1x/2x/4x/8x; workspace files scale as N/N+N/N+2N/N+3N where N=8.

At v0: 15 technicians, 30 jobs, 7 zones, 15 part types, 13 workspace files (8 scalable + 5 fixed config).
At v3: 120 technicians, 240 jobs, 14 zones, 120 part types, 37 workspace files (32 scalable + 5 fixed config).

### Structural Dimensions

- **Conditional Constraints**: Technician eligibility depends on skill level meeting job requirements, van parts inventory satisfying job needs (with substitution rules from a config file), and shift boundaries. Priority tier ordering is governed by a YAML configuration file.
- **Deliverable Constraints**: Output must be a CSV with exact column order, HH:MM time formatting, decimal-rounded travel minutes, and specific summary lines in the response.
- **Information Scattering**: GPS positions exist only in workspace CSV files; site access windows exist only in workspace JSON files; traffic conditions are only available via tool queries; road-condition multipliers and zone adjustments live in separate workspace config files. No single source suffices.
- **Multi-Hop Reasoning**: Determining actual travel time requires: reading GPS file (current zone) -> querying traffic tool (base time + congestion + road condition) -> reading scheduling_rules.json (road multiplier) -> reading travel_adjustments.csv (zone factor) -> computing the product. Scheduling each job further requires cross-referencing parts inventory (tool) against job requirements (tool) against substitution rules (workspace JSON).

## Harness Report

- v3 reward: 1.0 (100/100)
- Eval criteria: 7 (route_file_format, job_coverage, unique_assignment, skill_compliance, parts_compliance, time_compliance, priority_ordering)
- Source-access: clean — solver authored from `v3/prompt.md` plus `get_assistant_tools()` only; `env.py` opened post-solve for Section 3 review.
- Structural integrity: passed. `diff` confirms `env.py` and `prompt.md` are byte-identical across v0..v3; `data.py` differs only in the `SCALE` dict (rows 15/30/60/120, files 8/16/24/32).
- Solvability: solver at `/tmp/solve_dynamic_daily_routing.py` produced `route_plan.csv` (234 of 240 jobs scheduled, total travel 2731.9 min) and scored 1.0 on first submission.
- Env quality (Section 3): all 7 step criteria map back to prompt requirements; ground truth derives from current `data.db`/workspace (no hard-coded counts); thresholds (0.95) are reasonable; no over-normalization. Minor observation: the two required summary lines in the response are not separately graded by `step()`, but this is acceptable since the CSV is the substantive deliverable and the prompt's coverage requirement is captured by `job_coverage`.
- Prompt quality (Section 4): no title/heading, no bold or list formatting, scale-invariant wording, no tool names or DB filenames leaked, deliverable column names and time format spelled out.
- Issues found: none requiring fixes.
- Blockers: none.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/dynamic_daily_routing`; `data.py` changes are additive policy-document only, `step()` criteria 1-7 (ground truth, weights, thresholds) are byte-unchanged, and one DB-state criterion was appended under the M4 no-write-tool exception.

- **M1 JSON-string parameter**: `list_jobs` collapsed its three optional filters into a single `filter` parameter that must be a JSON-encoded string (`'{"status": "pending", "priority_tier": "P1"}'`; supported keys: `status`, `priority_tier`, `zone`). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values returns recoverable API-style errors, one at a time.
- **M4 nested write payload**: new `create_dispatch_record(payload)` tool taking a Notion-style nested body (`parent.type='technician_route'`/`parent.technician_id` + `properties.Job.reference.job_id`, optional `Note` rich_text). Validation is layered, one error per call (`body.parent.technician_id should be a non-empty string, instead was 'undefined'.`), then business checks (technician 404, job 404, job not pending, duplicate record). The write INSERTs into a `dispatch_assignments` table created by `Task_Env.__init__`. Since SOURCE had no write tool, the "commit each assignment via the write API" deliverable was added: `step()` gained criterion 8 `db_assignments_recorded` (10 pts, ≥0.95 threshold; max score now 110) checking each `route_plan.csv` assignment has a matching dispatch record; `prompt.md` gained one sentence stating the requirement. All other criteria and the CSV deliverable are unchanged.
- **Error contract**: tools never raise; every failure returns `{"status", "object": "error", "code", "message", "request_id"}`. Not-found lookups (`get_technician`, `get_job_details`, `get_travel_info`, and the M4 business checks) return `404 object_not_found`; bad input returns `400 validation_error` / `invalid_json` / `invalid_request`. Success responses share no keys with errors (the M4 success echo carries the prescribed `object` discriminator with value `dispatch_record`, never `error`); `get_technician`/`get_job_details` successes are wrapped as `{"technician": {...}}` / `{"job": {...}}` so the row's `status` column cannot collide with the error shape.

### Per-tool return-shape map

| tool | success shape | error shape |
|---|---|---|
| list_zones | native dict `{zones, count}` | — |
| list_technicians | native dict `{technicians, page, page_size, total}` | — |
| list_jobs (M1) | native dict `{jobs, page, page_size, total}` | `_error` dict |
| get_technician | native dict `{technician: {...}}` | `_error` 404 |
| get_job_details | native dict `{job: {...}}` | `_error` 404 |
| get_van_inventory | native dict `{van_id, parts}` | — |
| get_job_required_parts | native dict `{job_id, parts}` | — |
| get_travel_info | native dict (segment fields) | `_error` 404 |
| create_dispatch_record (M4) | deep echo `{object: "dispatch_record", id, parent, properties, created}` | `_error` dict, layered |

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 9 route-narrating paragraphs to 5: goal (kept verbatim), a single pointer to the methodology/policy/configuration documents as the authoritative specification, the verbatim `route_plan.csv` deliverable contract, the M4 dispatch-record sentence, and the verbatim two-summary-line response contract. Deleted route narration (tool hand-holding, per-file navigation, step sequencing). Business rules that lived only in the prompt (effective-window intersection, early-arrival wait semantics, completion-before-shift-end, eligibility bundle, parts-substitution semantics and sequential consumption, destination-zone adjustment default 1.0 and one-decimal rounding, GPS-tracked starting zone, unique assignment, per-route stop-ordering mirror rule) were moved into a new fixed workspace document `dispatch_methodology.md` generated by `data.py` (the only `data.py` change besides the fixed-config-count print; SCALE blocks preserved per version).

Completeness audit (step() criterion -> info source):

| criterion | source |
|---|---|
| route_file_format (10) | prompt (verbatim deliverable contract) |
| job_coverage (20) | prompt ("assign all pending service jobs") |
| unique_assignment (10) | dispatch_methodology.md ("assigned to at most one technician and appears at most once") |
| skill_compliance (15) | dispatch_methodology.md (eligibility) |
| parts_compliance (15) | dispatch_methodology.md (parts + sequential consumption) + part_substitutions.json |
| time_compliance (15) | dispatch_methodology.md (effective window, wait rule, shift end) + site_details_*.json |
| priority_ordering (15) | dispatch_methodology.md (stop sequencing) + priority_config.yaml (ordering_rule) |
| db_assignments_recorded (10) | prompt (dispatch-record commitment sentence) |

Supporting non-criterion rules: travel-time formula in scheduling_rules.json + dispatch_methodology.md; technician selection & tie-break in service_level_agreements.md + dispatch_methodology.md; job cap in scheduling_rules.json.

### Verify results

- v3: reward 1.0 (110/110), all 8 criteria passed.
- v0: reward 1.0 (110/110), 128 tool calls (floor: ≥15).
- Negative paths exercised: M1 malformed JSON (`invalid_json` with line/column/char), dict-instead-of-string, unsupported key, wrong-typed value; M4 layered messages one at a time (undefined body, string body, missing parent, wrong parent.type, missing technician_id, missing properties, missing Job, wrong Job.type, missing job_id), 404s for unknown technician/job, duplicate-record 400; lookup 404 error dicts share no keys with successes.
- Structural: `env.py`/`prompt.md` byte-identical across v0-v3; per-version `data.py` differ only in `SCALE`; no runtime artifacts.

## Harness Report — Verification Pass (2026-07-02)

### Structural Integrity (Section 1)

- Top-level contains exactly `README.md`, `v0/`, `v1/`, `v2/`, `v3/` — no stale artifacts. ✓
- Each `v_n/` contains exactly `data.py`, `env.py`, `prompt.md`. ✓
- `env.py` and `prompt.md` are byte-for-byte identical across v0..v3. ✓
- `data.py` differs across versions only in the `SCALE` dict (rows 15/30/60/120, workspace files 8/16/24/32). ✓

### Solvability at v3 (Section 2)

- `data.py` ran cleanly: 120 technicians, 240 jobs, 14 zones, 120 parts, 32 scalable + 6 fixed workspace files.
- Solver written using only `v3/prompt.md` + `get_assistant_tools()`.
- Solver result: 234 of 240 jobs scheduled (6 infeasible), total travel 2731.9 minutes.
- **v3 reward: 1.0 (120/120)** — all 9 criteria passed on first submission.

### Env Quality — Issues Found and Fixed (Section 3)

**Issue 1 — Summary text not evaluated (completeness gap)**

`step()` accepted `action: str` but never read it. `prompt.md` explicitly requires two summary lines (`Total Travel Time: X.X minutes` / `Jobs Scheduled: N out of M`), but no criterion checked them — an agent could omit them entirely and still score 1.0.

Fix: added criterion 9 `summary_text` (10 pts) to `step()`. It uses `re.search` to locate each required line in `action`, parses the numeric values, and compares against ground-truth totals derived from the parsed `route_plan.csv`. Also added `("summary_text", 10)` to the early-return fallback list.

**Issue 2 — priority_ordering missing within-tier window_end check**

Criterion 7 checked only that tier numbers were non-decreasing (`t1 <= t2`). `prompt.md` (via `dispatch_methodology.md`) further requires that within the same tier, stops are ordered by earliest customer window close. A plan that sorted same-tier jobs in the wrong window-end order would still pass.

Fix: when `t1 == t2`, now additionally compares `window_end` of the two jobs (`we1 <= we2`). Correct solutions unaffected — solver already sorts by `(tier_num, window_end)`.

**Post-fix eval criteria (9 total, max_score 120):**

| # | criterion | pts |
|---|---|---|
| 1 | route_file_format | 10 |
| 2 | job_coverage | 20 |
| 3 | unique_assignment | 10 |
| 4 | skill_compliance | 15 |
| 5 | parts_compliance | 15 |
| 6 | time_compliance | 15 |
| 7 | priority_ordering | 15 |
| 8 | db_assignments_recorded | 10 |
| 9 | summary_text | 10 |

`env.py` propagated to v1/v2/v3; `diff` confirmed byte-for-byte invariant.

### Prompt Quality (Section 4)

No issues found. Prompt opens with prose (no title), contains no bold headers or list formatting, uses scale-invariant language ("all pending", "every available"), mentions no tool names or source file names, specifies the deliverable (`route_plan.csv`) with exact column names and time format.

### Final Structure

```
./
├── README.md
├── v0/  (data.py, env.py, prompt.md)
├── v1/  (data.py, env.py, prompt.md)
├── v2/  (data.py, env.py, prompt.md)
└── v3/  (data.py, env.py, prompt.md)
```

No runtime artifacts (`data.db`, `workspace/`, `__pycache__`) remain.
