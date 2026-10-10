## Task Topic

Optimize e-commerce flash sale pricing by correlating real-time website clickstreams, competitor price tracking data, warehouse inventory turnover rates, and customer segment lifetime value scores to adjust discount tiers, producing a validated pricing schedule for the campaign.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|---------------|---------------------|
| v0      | 50            | 8                   |
| v1      | 100           | 16                  |
| v2      | 200           | 24                  |
| v3      | 400           | 32                  |

The scalable workspace files are daily clickstream session logs (CSV). Fixed configuration files (campaign config YAML, discount tier definitions JSON, competitor reputation CSV, warehouse priority YAML, pricing policy MD) are produced independently and do not scale.

The task employs the following structural dimensions:

- **Information Scattering**: Critical parameters are distributed across workspace configuration files (YAML, JSON, CSV, MD) and database-backed tools. Clickstream engagement data lives in workspace CSV files while product details, competitor prices, inventory status, and customer segment LTV scores are accessible only through tools. The discount tier thresholds and scoring weights come from JSON/YAML config files, and the margin-enforcement formula is documented solely in a Markdown policy file.

- **Multi-Hop Reasoning**: Computing the final sale price for each product requires a dependency chain of length ≥ 4: daily clickstream CSVs → segment IDs from events → tool lookup for segment LTV scores → raw segment value → min-max normalization across eligible products → weighted composite score → tier mapping from JSON config → margin check using policy formula → capped discount and final price.

- **Conditional Constraints**: Product eligibility depends on category membership (from campaign config) and margin viability (cost-price-to-base-price ratio vs. the minimum margin threshold). Discount assignment involves a two-stage gating process: first mapping the composite score to a tier, then verifying the tier's discount against the margin floor and capping or excluding as needed.

## Harness Report

- v3 reward: **1.0 (110/110)**.
- Eval criteria: **8** — `output_file_format` (10), `eligible_products` (15), `composite_scores` (20), `discount_tiers` (15), `margin_enforcement` (15), `sort_order` (10), `response_summary` (15), `db_adjustments_recorded` (10).
- v3 schedule: 250 eligible products, 23 excluded by margin floor, **227 in schedule** (Gold: 4, Silver: 120, Bronze: 101, NoDiscount: 2). Average discount: 12.89%.
- Source-access: clean. Solver written from `v3/prompt.md` + `get_assistant_tools()` only; `env.py` and `data.py` were not opened until the Section 3 review.
- Structural integrity: top-level contains exactly `README.md` + `v0/`–`v3/`. Each version has exactly `data.py`, `env.py`, `prompt.md`. `env.py` and `prompt.md` are byte-identical across v0–v3; `data.py` differs only in the two-line `SCALE` block.
- Env quality: all 8 `step()` criteria correspond to explicit prompt requirements; ground truth is derived dynamically from DB/workspace with no hardcoded counts; weights and criteria count are invariant across versions.
- Prompt quality: no title/headings, no bold headers, no lists, no code blocks, no tool names or internal filenames, scale-invariant wording, unambiguous constraints.
- Issues found and fixed: **none**. All checks passed on the first run.

## Hardening (M0 + M1 + M4)

Applied on top of `environments/standard/ecommerce_flash_sale_pricing_adjustment`. Data generation (tables, rows, seeds, SCALE blocks), `_compute_ground_truth()`, and the original seven `step()` criteria are unchanged; `step()` gains only the M4 DB-state criterion `db_adjustments_recorded` (10 pts, max 100 → 110) because the SOURCE had no write tool.

- **M1 JSON-string parameters**: `list_products` takes a single `filter` parameter that must be a JSON-encoded string (supported properties: `category` string, `brand` string, `min_base_price` number); `get_competitor_prices` takes an `options` JSON-encoded string (`in_stock_only` boolean). Malformed JSON returns `invalid_json` with line/column/char position; passing an object instead of a string, unsupported keys, or wrongly-typed values returns recoverable API-style errors, one at a time.
- **M4 nested write payload**: new write tool `create_price_adjustment(payload)` taking a Notion-style nested body (`parent.type='flash_sale_campaign'` + `parent.campaign_id` matching the campaign name in `campaign_config.yaml`, `properties.Product.reference.product_id`, `properties.Discount.number` whole-number 0–100, optional `Note` rich_text). Validation is layered — one error per call, messages like `body.parent.campaign_id should be a non-empty string, instead was 'undefined'.` — followed by business checks (campaign exists 404, product exists 404). The write is `INSERT OR REPLACE` into a `price_adjustments` table (created on first write); `step()` criterion 8 checks each ground-truth product's recorded `discount_pct`.
- **Error contract**: tools never raise; every failure returns `{status, object:'error', code, message, request_id}`. Not-found → 404 `object_not_found` (also added to `get_product_details` / `get_competitor_prices` / `get_inventory_status` / `get_segment_details`, replacing the old `{"error": ...}` shape); bad input → 400 `validation_error` / `invalid_json` / `invalid_request`. Success responses share no keys with error responses apart from the discriminator `object` field (success shapes are unchanged native dicts; the M4 success is a deep echo `{"object": "price_adjustment", id, parent, properties, created}`).
- Per-tool return shapes: all query tools keep the SOURCE native-dict success shapes (`products`/`segments` + `total`/`has_more` pagination; `competitors`/`warehouses` wrappers); no M2 encodings applied.
- verify(): reward **1.0 at v0 (110/110, 133 tool calls)** and **1.0 at v3 (110/110, 1012 tool calls)**; negative-path suite exercised (malformed/mis-typed M1 filters, all 15+ layered M4 errors, 404s).

### M0 — de-proceduralized prompt

`prompt.md` rewritten from 10 route-narrating paragraphs to 5: scenario/goal (verbatim first paragraph), a pointer to the campaign configuration and policy documents as the authoritative specification, the recording requirement (M4), the verbatim deliverable contract, and the verbatim final-response requirement (extended with recording confirmation). All tool hand-holding, sequencing scaffolds, and per-file navigation removed. `data.py` change (additive only): `pricing_policy.md` gained Eligibility, Scoring Dimensions (data sources + event weights + all four formulas + zero conventions), Normalization and Composite Score, Tier Assignment and Discount Cap, and Sale Price sections; the original Normalization Edge Case and Margin Enforcement Formula sections survive verbatim below them.

Completeness audit (step() criterion → info source):
| criterion | source |
|---|---|
| output_file_format | prompt (verbatim deliverable contract: filename, columns, order, precision) |
| eligible_products | campaign_config.yaml `eligible_categories` + pricing_policy.md Eligibility |
| composite_scores | pricing_policy.md Scoring Dimensions + Normalization/Composite + Edge Case; weights in campaign_config.yaml |
| discount_tiers | discount_tiers.json (tier table + top-down note) + pricing_policy.md Tier Assignment |
| margin_enforcement | pricing_policy.md Sale Price + Margin Enforcement Formula; min_margin_pct/max_discount_pct in campaign_config.yaml |
| sort_order | prompt (verbatim contract: composite_score desc, product_id asc tie-break) |
| response_summary | prompt final paragraph (total count, per-tier counts, avg discount to 2 dp) |
| db_adjustments_recorded | prompt paragraph 3 ("recorded against the campaign in the pricing system"); campaign name discoverable in campaign_config.yaml |
