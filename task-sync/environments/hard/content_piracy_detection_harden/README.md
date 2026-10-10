## Task Topic

Detect content piracy by cross-referencing student subscription tiers, video streaming access logs, third-party site takedown notices, and course material download patterns, generating a prioritized takedown list for illegally distributed premium lectures.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 80            | 10                  |
| v1      | 160           | 20                  |
| v2      | 320           | 30                  |
| v3      | 640           | 40                  |

Rows scale at 2× per version step (v1=2×, v2=4×, v3=8× of base). Workspace files scale as base + k×N where N = base and k = version index.

### Structural Dimensions

- **Information Scattering**: Piracy signals are split across multiple sources — content fingerprints live in JSON scan reports and TXT DMCA complaint files, suspicious IPs sit in CSV watchlists, scoring parameters are in a YAML policy file, and student subscription tiers plus access/download logs are only reachable through tool calls. No single source is sufficient.

- **Multi-Hop Reasoning**: The dependency chain is at least length 4: read scan report fingerprint → look up lecture by hash (tool) → retrieve access logs for that lecture (tool) → look up each accessing student's tier (tool) → compare against tier-access rules (file) → compute weighted score using policy weights (file).

- **Conditional Constraints**: Whether an access event counts as "unauthorized" depends on the student's subscription tier, the lecture's access tier, and the tier-access rules mapping. The final inclusion/exclusion of a lecture on the takedown list depends on its computed score exceeding a configurable threshold.

## Harness Report

- v3 reward: 1.0 (110/110), achieved on first solver run via clean black-box (only `v3/prompt.md` + `get_assistant_tools()` consulted; no step-6 escalation needed).
- Eval criteria: 8 (file_format 10, lecture_ids 20, piracy_scores 20, ranking_order 15, priority_levels 10, unauthorized_counts 15, response_summary 10, external_urls 10).
- Structural integrity: clean. `env.py` and `prompt.md` byte-identical across v0..v3; only `SCALE` differs in `data.py`. No stale artifacts.
- Prompt quality: no headings/bullets, prose computation logic, scale-invariant phrasing, no tool/internal names leaked.
- Env quality: ground truth derived from current DB/workspace; no hardcoded counts. Criteria are scale-invariant.
- Issues found / fixed:
  - **Coverage gap (fixed):** `prompt.md` requires `external_urls` to be "sorted alphabetically" but the original `step()` had no criterion checking this. Added `external_urls` criterion (10 pts) in `v0/env.py` comparing each row's `external_urls` against the ground-truth semicolon-joined sorted URL string; propagated to v1/v2/v3. Solver confirmed at 1.0 post-fix (110/110).

## Hardening (M0 + M5 + M2)

Applied on top of `environments/standard/content_piracy_detection`; `step()` / `_compute_ground_truth()` scoring is byte-unchanged, and `data.py` changes are additive-policy-document only (each version's `SCALE` block preserved; per-version `data.py` files differ from each other only in `SCALE`).

- **M0 de-proceduralized prompt**: `prompt.md` rewritten from 8 route-narrating paragraphs to 4: scenario/goal, a pointer to the detection methodology + policy/configuration documents as the authoritative spec, the verbatim deliverable contract (column list and order, two-decimal `piracy_score`, semicolon-joined alphabetically-sorted `external_urls`, sort key + tie-breaker, rank numbering — kept word for word), and the verbatim four-line final-response requirement. All tool hand-holding ("use the available lookup tool", "retrieve its full record", sequencing scaffolds) and per-file navigation deleted. Prompt-only rules moved into a new non-scaling workspace document `detection_methodology.md` (added in `data.py`'s `generate_config_files`): evidence-source union across scan reports and DMCA notices, false-positive discard, watchlist "any IP regardless of threat level", the three signal definitions (including per-event unauthorized counting and *unique*-IP watchlist hits), the scoring formula with two-decimal rounding and min-score exclusion, and the at-or-above priority brackets.
- **M5 unbounded bulk export**: new tool `export_platform_activity()` returns every access-log event and every download event joined with the student's subscription tier, the lecture's access tier, and the event IP — as ONE JSON string, no pagination. Measured size: ~17.1k tokens at v0 (survivable but expensive), ~138k tokens at v3 (echoing it into context is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and filtered before printing). It is genuinely sufficient for the core counting step (unauthorized accesses + watchlist IP hits). All paginated / per-entity tools remain available as the safe alternative.
- **M2 mixed return shapes** (descriptions state what, never how it is encoded):

| tool | success shape |
|---|---|
| `list_students` | native dict |
| `get_lecture` | native dict |
| `get_lectures_for_course` | native dict |
| `query_access_logs` | JSON-encoded string |
| `export_platform_activity` | JSON-encoded string (M5) |
| `find_lecture_by_hash` | MCP envelope (`content[0].text` is JSON) |
| `query_downloads` | MCP envelope |
| `get_student` | plain `key: value` text |
| `get_course` | Python-repr string (`ast.literal_eval`, not `json.loads`) |

- **Error contract**: tools never raise. Failures return `{"status", "object": "error", "code", "message", "request_id"}` — no keys shared with any success shape (`query_access_logs` returns the JSON-string form of the same object). Not-found → `404 object_not_found` ("Could not find <entity> with ID: ..."); bad input → `400 validation_error` with Notion-style messages (`body.student_id should be an integer, instead was '...'`). Smoke-tested: 404s on lecture/course/student/hash lookups, wrong-typed ids/pages/hashes (including dict-valued params), zero page_size, and success/error key-disjointness.
- **verify()**: computation ported 1:1; consumption layer unwraps envelopes, parses JSON strings / repr strings / key:value text, consumes the bulk export once in memory, and cross-checks the export against the paginated tools on a sample lecture. Reward **1.0 at v0 (70 tool calls) and v3 (517 tool calls)**.

M0 completeness audit (`step()` criterion → where the required information now lives):

| criterion | source |
|---|---|
| file_format (10) | prompt para 3 (verbatim deliverable contract) |
| lecture_ids (20) | `detection_methodology.md` (evidence sources, fingerprint matching, false-positive discard, min-score exclusion) + `piracy_policy.yaml` (`min_piracy_score`) |
| piracy_scores (20) | `detection_methodology.md` (scoring formula + two-decimal rounding) + `piracy_policy.yaml` (weights, tier multipliers) |
| ranking_order (15) | prompt para 3 (sort by score desc, tie-break lecture id asc, ranks from one) |
| priority_levels (10) | `detection_methodology.md` (at-or-above brackets) + `piracy_policy.yaml` (thresholds, actions) |
| unauthorized_counts (15) | `detection_methodology.md` (signal 2, per-event counting) + `tier_access_rules.json` + `severity_guide.md` |
| response_summary (10) | prompt para 4 (verbatim four summary lines) |
| external_urls (10) | prompt para 3 (unique external URLs joined by semicolons, sorted alphabetically) |
