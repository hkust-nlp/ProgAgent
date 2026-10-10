## Task Topic

Selecting optimal sites for new retail outlets requires cross-referencing competitor proximity maps, local demographic census data, commercial real estate lease terms, and traffic flow analytics to generate a ranked shortlist of locations with projected first-year footfall.

## Version Overview

| Version | rows_per_table | num_workspace_files |
|---------|----------------|---------------------|
| v0      | 50             | 8                   |
| v1      | 100            | 16                  |
| v2      | 200            | 24                  |
| v3      | 400            | 32                  |

Scaling ratios: rows follow 1x/2x/4x/8x; workspace files follow base/base+N/base+2N/base+3N where N=8.

### Structural Dimensions

- **Information Scattering**: Task-critical fields are split across database tools and workspace files. Zone demographics, site details, lease terms, competitor locations, and traffic counts are only accessible via tool calls. Accessibility ratings (inspection reports), market saturation indices (market analysis reports), peak-hour multipliers (traffic sector reports), scoring weights, eligibility thresholds, footfall model coefficients, and category threat levels live exclusively in workspace files of various formats (JSON, YAML, CSV, Markdown, TXT).

- **Multi-Hop Reasoning**: The dependency chain spans at least four hops: read eligibility config files to determine thresholds, then query zones and filter by demographics, then retrieve sites per eligible zone and filter by area, then obtain lease terms and competitor counts to further filter, then gather traffic data and cross-reference workspace files for saturation/accessibility/peak-boost values, and finally apply the scoring and footfall formulas from configuration files to produce the ranked output.

- **Conditional Constraints**: Eligibility depends on cascading business rules across multiple tables and configuration thresholds (zone population and income filters, site area minimum, rent ceiling, competitor count cap within a geographic radius). The competition score is further modulated by category-specific threat levels and zone-level market saturation indices.

- **Deliverable Constraints**: The output CSV requires exact column order, composite scores formatted to two decimal places, footfall as integers, and a specific sort order (composite score descending, footfall descending, site_id ascending as tie-breaker).

## Harness Report

**v3 reward:** 1.0 (100/100)

**Eval criteria (7 total):**

| Criterion | Max | Description |
|---|---|---|
| output_file_format | 10 | site_rankings.csv exists with all required columns |
| eligible_sites | 20 | Jaccard similarity of qualifying site IDs vs ground truth |
| ranking_order | 20 | Kendall-tau pairwise concordance of ranked order |
| composite_scores | 15 | Per-site composite scores within 1% / 0.05 absolute |
| footfall_accuracy | 15 | Per-site footfall values within 5% of ground truth |
| top5_in_response | 10 | Top-5 site IDs or names present in final response |
| format_compliance | 10 | composite_score 2 d.p., projected_annual_footfall integer |

**Issues found and fixed:**

1. **Stale `workspace/` in v3** — A leftover `workspace/` directory was present in `v3/` from a prior run. Removed with `rm -rf v3/workspace`.

2. **Solver footfall tier bug (not an env bug)** — The initial solver mapped the competition-adjustment tiers in the wrong direction: `competition_adj_low` (1.20) was incorrectly applied to low competition-score sites (high competition) and `competition_adj_high` (0.75) to high competition-score sites. The env and prompt are consistent: `competition_adj_low` (1.20) is the "low-competition" boost applied when the competition score meets or exceeds the high threshold (≥ 70), and `competition_adj_high` (0.75) is the "high-competition" penalty applied when the score falls below the low threshold (< 40). After correcting the tier logic in the solver, all 7 criteria passed and reward reached 1.0.

No changes were made to `env.py`, `prompt.md`, or `data.py`.
