## Task Topic

Optimize ad inventory pricing by analyzing fill rates. Process historical impression logs, listener geographic concentration, advertiser category performance, and seasonal sponsorship trends to recommend dynamic CPM adjustments, outputting a pricing schedule per show and region.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 100            | 10                  |
| v1      | 200            | 20                  |
| v2      | 400            | 30                  |
| v3      | 800            | 40                  |

Difficulty scales only through data volume; `env.py` and `prompt.md` are shared unchanged across all four versions.

**Structural dimensions used:**

- **Information Scattering**: Campaign and impression data live in the database (accessed via tools), while listener geographic concentration profiles, category demand benchmarks, seasonal factors, and pricing adjustment rules are spread across workspace files in JSON, YAML, CSV, and Markdown formats. Both sources are required to compute the final pricing schedule.
- **Multi-Hop Reasoning**: The computation chain spans at least four hops: retrieve active campaigns (tool) to identify show-region pairs, then read geo profile files (workspace) for concentration shares, then call the revenue-by-category tool to find the dominant category, then look up the demand index from category benchmark files (workspace), and finally apply the formula from the policy document.
- **Deliverable Constraints**: The output CSV must use exact column names in a prescribed order, numeric values rounded to two decimal places, and rows sorted by show_id then region_id.

## Harness Report

- v3 reward: 1.0 (total_score 100 / 100).
- Number of eval criteria: 7 (file_exists, correct_columns, correct_row_count, correct_show_region_pairs, correct_fill_rates, correct_multipliers, correct_recommended_cpm).
- Solver outcome: succeeded on the first attempt using only `v3/prompt.md` and the public `Task_Env.get_assistant_tools()` interface. `env.py` was never opened during Section 2.
- Issues found and fixes: none — passed clean. Section 1 structural diff confirmed `env.py` and `prompt.md` are byte-for-byte identical across v0..v3 and only the SCALE dict differs in `data.py`. Section 3 alignment review found no hidden, missing, over-strict, or scale-dependent criteria. Section 4 found no formatting violations in `prompt.md`.


## Hardening (M2 + M3)

Applied on top of `environments/standard/ad_inventory_pricing_optimization`; data.py, prompt.md, and step() scoring are unchanged.

- **M2 mixed return shapes**: `list_shows` / `list_active_campaigns` return native deep-nested list objects (`{"object": "list", "results": [...], "has_more", "next_cursor"}`); `get_show_details` returns a JSON-encoded string; `list_regions` / `get_region_details` return MCP-style envelopes (`{"meta", "content": [{"type": "text", "text": <json>}]}`); `get_advertiser_info` returns plain `key: value` text; `get_impression_stats` / `get_revenue_by_category` return Python-repr strings (single quotes, not JSON-parseable).
- **M3 deep nesting**: record fields live 3-4 levels deep in Notion-style property objects (`properties.Name.title[0].plain_text`, `properties.Genre.select.name`, `properties.Show.relation[0].id`). Success and error responses share no keys; errors are `{"status", "object": "error", "code", "message", "request_id"}`.
- verify() passes with reward 1.0 at v0 and v3 scales (815 tool calls at v3).

### M0 — de-proceduralized prompt (added 2026-07-02)

`prompt.md` rewritten from 9 route-narrating paragraphs to 3: scenario/goal, a pointer to the policy/configuration documents as the authoritative spec, and the verbatim deliverable contract (filename, column order, sorting). Removed: tool hand-holding, sequencing scaffolds, per-file navigation, and rule restatements that are discoverable in workspace documents. `data.py` change (additive only): `policy_overview.md` gained the half-open tier-boundary convention, the missing-region share=0 default, the missing-benchmark demand-index=1.0 default, and the rounding note — these were previously stated only in the prompt.

Completeness audit (step() criterion -> info source):
| criterion | source |
|---|---|
| file_exists / correct_columns | prompt (verbatim contract); also pricing_rules.yaml output_format |
| correct_row_count / correct_show_region_pairs | policy_overview.md (eligibility rule) |
| correct_fill_rates | impression stats tool + pricing_rules.yaml tiers + policy_overview.md boundary convention |
| correct_multipliers | pricing_rules.yaml tiers/brackets + policy_overview.md defaults + seasonal_factors.json |
| correct_recommended_cpm | policy_overview.md formula + rounding |
v3 verify (unchanged) re-run after M0: reward 1.0.
