## Task Topic

Validate network adequacy compliance by geocoding member addresses, mapping them to provider locations by specialty, and comparing against regulatory distance thresholds, generating a deficiency report for each service area.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 100           | 10                  |
| v1      | 200           | 20                  |
| v2      | 400           | 30                  |
| v3      | 800           | 40                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=10.

### Structural Dimensions

- **Information Scattering**: Member plan types exist only in workspace roster CSV files, while member service-area assignments and geocoded coordinates are only available via tools. Provider credentials (board certification, expiry dates) are only in workspace JSON files, while provider office locations and network contract statuses are only accessible through tools. Solving the task requires merging data from both sources.

- **Conditional Constraints**: A provider counts toward a member's coverage only when four conditions hold simultaneously — board-certified with non-expired certification (checked against a reference date from a config file), accepting new patients, holding an active network contract matching the member's plan type, and located within the distance threshold for the specialty and area type. Thresholds and required coverage percentages come from workspace config files.

- **Multi-Hop Reasoning**: The dependency chain is: roster files → member IDs → tool (service area assignment) → tool (geocoding) → tool (provider search by specialty) → workspace credentials (filter eligible) → haversine distance computation → compliance threshold lookup → deficiency determination. This spans at least 4 hops across tools and files.

## Harness Report

**v3 reward: 1.0 (100/100)**

**Eval criteria (6 total, 100 pts):**
- `file_exists` — 10 pts: `deficiency_report.csv` present in workspace
- `correct_columns` — 10 pts: all 12 columns in exact specified order
- `correct_row_count` — 10 pts: one row per (service_area × specialty) pair
- `coverage_accuracy` — 30 pts: per-row `coverage_pct` within 1 pp of ground truth
- `compliance_determination` — 25 pts: per-row `compliant` flag correct
- `response_summary` — 15 pts: every non-compliant pair named in final response

**Issues found and fixed:**

1. **Runtime artifacts in v0/ and v3/**: `data.db`, `workspace/`, and `__pycache__/` were present in both v0/ and v3/. Removed.

2. **v1/ and v2/ had stale pre-hardening `env.py`**: After the M1+M3+M5 hardening was applied to v0/, only v3/ was updated; v1/ and v2/ still held the original base env.py (32 KB vs. the hardened 46 KB). Propagated `v0/env.py` → `v1/env.py`, `v2/env.py`.

3. **v1/, v2/, v3/ had stale pre-hardening `prompt.md`**: The original 3 955-byte prompt contained step-by-step procedural instructions and explicit tool-workflow guidance that was removed during hardening (the hardened v0 prompt, 2 184 bytes, defers all spec details to workspace reference files and omits workflow prescriptions). Propagated `v0/prompt.md` → `v1/prompt.md`, `v2/prompt.md`, `v3/prompt.md`.

After all fixes, `diff v0/env.py vN/env.py` and `diff v0/prompt.md vN/prompt.md` return no output for N ∈ {1,2,3}; only the `SCALE` dict differs across `data.py` versions.

**Env quality notes:** Ground truth in `step()` is fully recomputed from `data.db` + workspace files on every call (scale-invariant). All 6 criteria correspond directly to prompt-stated requirements; no hidden criteria. The ±1 pp tolerance on `coverage_pct` is intentional to absorb floating-point rounding variation. Prompt is pure prose with no title, bold headers, bullets, or hard-coded counts.

## Hardening (M0 + M1 + M3 + M5)

Applied on top of `environments/standard/network_adequacy_compliance_report`. Task logic, the underlying data, and `step()` scoring are unchanged — across versions only the `SCALE` dict in `data.py` differs (v0 100 rows / 10 workspace files → v3 800 rows / 40 files). The tool surface was re-skinned (M1 + M3 + M5) and the prompt was de-proceduralized (M0); the eligibility/coverage methodology it defers to lives in the `data.py`-authored workspace doc `eligibility_rules.md` (data content otherwise unchanged).

- **M5 unbounded bulk export**: new tool `export_network_directory()` returns the entire joined provider directory — one record per office location across all specialties and areas, each carrying provider identity, `credential_type`, patient-acceptance, and full network-contract history (plan type, status, effective/termination dates) — as one `json.dumps` string (`{"record_count", "records":[...]}`) with no pagination. Measured raw size: **77,567 chars ≈ 19k tokens at v0**, up to **615,565 chars ≈ 154k tokens at v3**. Echoing it into context at v3 is fatal under a ~70k response budget; it must be consumed inside the programmatic sandbox and reduced (e.g. to each provider's active-plan set) before anything is printed. Paginated / per-entity tools (`query_members`, `search_providers`, `geocode_members`) remain available.
- **M1 JSON-string filter**: `query_members` and `search_providers` collapse their filters into one `filter` param typed as a JSON-encoded string (e.g. `filter='{"specialty_id": 4}'`), parsed by `_parse_json_string_param`. Malformed JSON → `invalid_json` with `line N column M (char P)`; a JSON scalar/array instead of an object → `invalid_request`; unsupported keys and wrong-typed values → `validation_error`, one error at a time. `search_providers` requires `specialty_id`; an unknown id → 404 `object_not_found`.
- **M3 deep-nested records**: `list_service_areas`, `query_members`, and `search_providers` return Notion-style `{"object":"list","results":[{"object":...,"id":...,"properties":{...}}],"has_more":...,"next_cursor":...}` with cursor pagination (`next_cursor` = next page number, `PAGE_SIZE` = 20). Read display text at `properties.<Prop>.title[0].plain_text` (or `rich_text[0].plain_text`), categories at `select.name`, foreign keys at `relation[0].id`, coordinates at `number`, `Accepting New Patients` at `checkbox`, and contracted plans at `multi_select[].name`.
- **M2 mixed return shapes**: **not applied** — encodings are consistent per tool, not deliberately mixed. The three list tools return native M3 list dicts; `list_specialties` and `geocode_members` return native Python lists of flat dicts; only `export_network_directory` returns a JSON string (that string is M5, not M2). An `_envelope()` MCP-style helper (`content[0].text` / `isError`) is defined but wired to no tool, and `repr()` appears only inside error-message text. Errors are `{"status","object":"error","code","message","request_id"}` (via `_error`); the four keys `status`/`code`/`message`/`request_id` are error-exclusive, so an error is always unambiguously detectable (success list wrappers carry `object:"list"`, errors carry `object:"error"`).
- verify() passes with **reward 1.0 (100/100) at both v0 (24 tool calls) and v3 (148 tool calls)**; it consumes the bulk export exactly once, in memory — deriving each provider's active-plan set and discarding the raw string rather than echoing it.

### M0 — de-proceduralized prompt

The prompt is a goal + deliverable contract (produce `deficiency_report.csv` with 12 named columns; enumerate every non-compliant pair) and prescribes no tool workflow — it defers every spec detail to the workspace reference docs `data.py` writes. Each `step()` criterion still resolves to a complete, present information source:

| step() criterion (pts) | Information source |
|---|---|
| `file_exists` (10) | Prompt ¶3 — "produce a file named `deficiency_report.csv`" |
| `correct_columns` (10) | Prompt ¶3 — lists all 12 columns in exact order, plus 2-decimal rounding and `YES`/`NO` encoding |
| `correct_row_count` (10) | Prompt ¶3 — "one row for each combination of service area and specialty" |
| `coverage_accuracy` (30) | Prompt ¶2 defers to docs → `eligibility_rules.md` (4 eligibility conditions, closest-location rule, coverage-% formula) + `distance_thresholds.yaml` (per-specialty × urban/suburban/rural miles) + `compliance_standards.json` (`reference_date` for cert-expiry check); member `plan_type` from `member_roster_*.csv`, credentials from `provider_cred_*.json` |
| `compliance_determination` (25) | `compliance_standards.json` (`required_coverage_pct`) + rule "compliant when coverage ≥ requirement" (`eligibility_rules.md` / Prompt ¶3) |
| `response_summary` (15) | Prompt ¶4 — name every non-compliant area/specialty pair with achieved and required coverage |

Every criterion maps to a prompt paragraph or a named workspace doc; no task-solving detail was left stranded only in the removed procedural text.
