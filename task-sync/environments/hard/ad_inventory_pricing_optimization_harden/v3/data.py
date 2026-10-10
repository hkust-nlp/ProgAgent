"""
Ad Inventory Pricing Optimization - Data Generation Script
Generates database and workspace files for analyzing fill rates and recommending
dynamic CPM adjustments per show and region.
"""

import argparse
import json
import os
import random
import sqlite3
import yaml
import numpy as np
import pandas as pd
from faker import Faker

# ─── All random seeds pinned to 42 ───
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

SCALE = {
    "rows_per_table": 800,        # v3 = 8x base
    "num_workspace_files": 40,    # v3 = base + 3N
}

# ─── Constants ───
GENRES = [
    "True Crime", "Comedy", "Business", "Technology", "Health & Wellness",
    "News & Politics", "Sports", "Education", "Entertainment", "Science",
    "Society & Culture", "Music", "Fiction", "History", "Self-Improvement"
]

AD_CATEGORIES = [
    "Technology", "Finance", "Health", "Retail", "Automotive",
    "Travel", "Food & Beverage", "Education", "Entertainment", "Insurance"
]

BUDGET_TIERS = ["platinum", "gold", "silver", "bronze"]

MARKET_TIERS = ["tier_1", "tier_2", "tier_3"]

COUNTRIES = ["US", "CA", "UK", "AU", "DE"]

QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

STATUS_OPTIONS = ["active", "completed", "paused"]


def create_database(db_path, workspace):
    """Create and populate the SQLite database."""
    R = SCALE["rows_per_table"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ─── Create tables ───
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS shows (
            show_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            genre TEXT NOT NULL,
            host TEXT NOT NULL,
            weekly_listeners INTEGER NOT NULL,
            launch_year INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS regions (
            region_id INTEGER PRIMARY KEY,
            region_name TEXT NOT NULL,
            country TEXT NOT NULL,
            market_tier TEXT NOT NULL,
            population INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS advertisers (
            advertiser_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            category TEXT NOT NULL,
            budget_tier TEXT NOT NULL,
            annual_budget REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id INTEGER PRIMARY KEY,
            advertiser_id INTEGER NOT NULL,
            show_id INTEGER NOT NULL,
            region_id INTEGER NOT NULL,
            quarter TEXT NOT NULL,
            base_cpm REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (advertiser_id) REFERENCES advertisers(advertiser_id),
            FOREIGN KEY (show_id) REFERENCES shows(show_id),
            FOREIGN KEY (region_id) REFERENCES regions(region_id)
        );

        CREATE TABLE IF NOT EXISTS impression_logs (
            log_id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            show_id INTEGER NOT NULL,
            region_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            available_slots INTEGER NOT NULL,
            filled_slots INTEGER NOT NULL,
            revenue REAL NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id),
            FOREIGN KEY (show_id) REFERENCES shows(show_id),
            FOREIGN KEY (region_id) REFERENCES regions(region_id)
        );
    """)

    # ─── Generate shows ───
    used_names = set()
    shows = []
    for i in range(1, R + 1):
        while True:
            name = fake.catch_phrase() + " " + random.choice(
                ["Podcast", "Show", "Cast", "Hour", "Daily", "Weekly"]
            )
            if name not in used_names:
                used_names.add(name)
                break
        genre = random.choice(GENRES)
        host = fake.name()
        weekly_listeners = random.randint(5000, 500000)
        launch_year = random.randint(2015, 2024)
        shows.append((i, name, genre, host, weekly_listeners, launch_year))

    cur.executemany("INSERT INTO shows VALUES (?, ?, ?, ?, ?, ?)", shows)

    # ─── Generate regions ───
    region_names_pool = []
    for country in COUNTRIES:
        for _ in range(R // len(COUNTRIES) + 5):
            region_names_pool.append((fake.city(), country))
    random.shuffle(region_names_pool)

    used_region_names = set()
    regions = []
    for i in range(1, R + 1):
        while True:
            if region_names_pool:
                rname, country = region_names_pool.pop()
            else:
                rname = fake.city()
                country = random.choice(COUNTRIES)
            full_name = f"{rname}, {country}"
            if full_name not in used_region_names:
                used_region_names.add(full_name)
                break
        market_tier = random.choices(MARKET_TIERS, weights=[0.2, 0.4, 0.4])[0]
        population = random.randint(50000, 5000000)
        regions.append((i, rname, country, market_tier, population))

    cur.executemany("INSERT INTO regions VALUES (?, ?, ?, ?, ?)", regions)

    # ─── Generate advertisers ───
    used_company = set()
    advertisers = []
    for i in range(1, R + 1):
        while True:
            cname = fake.company()
            if cname not in used_company:
                used_company.add(cname)
                break
        category = random.choice(AD_CATEGORIES)
        budget_tier = random.choices(BUDGET_TIERS, weights=[0.1, 0.25, 0.35, 0.3])[0]
        annual_budget = round(random.uniform(10000, 2000000), 2)
        advertisers.append((i, cname, category, budget_tier, annual_budget))

    cur.executemany("INSERT INTO advertisers VALUES (?, ?, ?, ?, ?)", advertisers)

    # ─── Generate campaigns ───
    # Use a subset of shows and regions for campaigns to keep pricing schedule manageable
    num_active_shows = max(15, R // 5)
    num_active_regions = max(8, R // 10)

    active_show_ids = sorted(random.sample(range(1, R + 1), min(num_active_shows, R)))
    active_region_ids = sorted(random.sample(range(1, R + 1), min(num_active_regions, R)))

    campaigns = []
    for i in range(1, R + 1):
        advertiser_id = random.randint(1, R)
        show_id = random.choice(active_show_ids)
        region_id = random.choice(active_region_ids)
        quarter = random.choice(QUARTERS)
        base_cpm = round(random.uniform(5.0, 45.0), 2)
        status = random.choices(STATUS_OPTIONS, weights=[0.4, 0.35, 0.25])[0]
        campaigns.append((i, advertiser_id, show_id, region_id, quarter, base_cpm, status))

    cur.executemany("INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?)", campaigns)

    # ─── Generate impression_logs ───
    active_campaign_ids = [c[0] for c in campaigns if c[6] == "active"]
    all_campaign_ids = [c[0] for c in campaigns]
    campaign_lookup = {c[0]: c for c in campaigns}

    impression_logs = []
    dates_pool = pd.date_range("2025-01-01", "2025-12-31", freq="D").strftime("%Y-%m-%d").tolist()

    for i in range(1, R + 1):
        if active_campaign_ids and random.random() < 0.7:
            cid = random.choice(active_campaign_ids)
        else:
            cid = random.choice(all_campaign_ids)

        camp = campaign_lookup[cid]
        show_id = camp[2]
        region_id = camp[3]
        log_date = random.choice(dates_pool)
        available_slots = random.randint(50, 500)
        fill_pct = np.clip(np.random.beta(3, 2) * 100, 10, 100) / 100.0
        filled_slots = int(available_slots * fill_pct)
        revenue = round(filled_slots * camp[5] / 1000.0, 2)
        impression_logs.append(
            (i, cid, show_id, region_id, log_date, available_slots, filled_slots, revenue)
        )

    cur.executemany(
        "INSERT INTO impression_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", impression_logs
    )

    conn.commit()
    conn.close()

    return shows, regions, advertisers, campaigns, impression_logs


def create_workspace(workspace, shows, regions, advertisers, campaigns, impression_logs):
    """Create workspace files."""
    os.makedirs(workspace, exist_ok=True)
    R = SCALE["rows_per_table"]
    N = SCALE["num_workspace_files"]

    # ─── Fixed config files (not scaled) ───

    # 1. pricing_rules.yaml - Core adjustment rules and thresholds
    pricing_rules = {
        "fill_rate_adjustments": {
            "high": {"min_rate": 0.85, "max_rate": 1.0, "multiplier": 1.30},
            "above_average": {"min_rate": 0.70, "max_rate": 0.85, "multiplier": 1.15},
            "average": {"min_rate": 0.50, "max_rate": 0.70, "multiplier": 1.00},
            "below_average": {"min_rate": 0.30, "max_rate": 0.50, "multiplier": 0.85},
            "low": {"min_rate": 0.0, "max_rate": 0.30, "multiplier": 0.70},
        },
        "geo_concentration_adjustments": {
            "dominant": {"min_share": 0.25, "max_share": 1.0, "multiplier": 1.20},
            "significant": {"min_share": 0.10, "max_share": 0.25, "multiplier": 1.05},
            "moderate": {"min_share": 0.05, "max_share": 0.10, "multiplier": 1.00},
            "minimal": {"min_share": 0.0, "max_share": 0.05, "multiplier": 0.90},
        },
        "output_format": {
            "decimal_places": 2,
            "sort_primary": "show_id",
            "sort_secondary": "region_id",
            "filename": "pricing_schedule.csv",
            "columns": [
                "show_id", "show_name", "region_id", "region_name",
                "current_cpm", "fill_rate", "fill_rate_multiplier",
                "geo_concentration", "geo_multiplier",
                "category", "category_factor",
                "seasonal_factor", "recommended_cpm", "adjustment_pct"
            ],
        },
    }
    with open(os.path.join(workspace, "pricing_rules.yaml"), "w") as f:
        yaml.dump(pricing_rules, f, default_flow_style=False, sort_keys=False)

    # 2. seasonal_factors.json - Quarterly seasonal multipliers
    seasonal_factors = {
        "description": "Seasonal demand multipliers by quarter for the upcoming pricing period",
        "target_quarter": "Q2",
        "factors": {"Q1": 0.90, "Q2": 1.10, "Q3": 1.05, "Q4": 1.25},
        "notes": "Q4 premium reflects holiday advertising surge; Q1 dip is post-holiday cooldown",
    }
    with open(os.path.join(workspace, "seasonal_factors.json"), "w") as f:
        json.dump(seasonal_factors, f, indent=2)

    # 3. policy_overview.md - Pricing policy document
    policy_md = """# Ad Inventory Pricing Policy

The dynamic pricing model adjusts base CPM rates using four multiplicative factors applied in sequence. The final recommended CPM for each show-region pair is calculated as:

    recommended_cpm = current_cpm x fill_rate_multiplier x geo_multiplier x category_factor x seasonal_factor

Where current_cpm is the average base_cpm across all active campaigns for that show-region pair.

The adjustment percentage should be computed as: ((recommended_cpm / current_cpm) - 1) * 100, expressed as a percentage value rounded to two decimal places.

Only show-region pairs that have at least one active campaign AND at least one impression log entry should appear in the final pricing schedule. Pairs missing either data source should be excluded.

When a show-region pair has campaigns from multiple advertiser categories, use the category with the highest total revenue across impression logs for that pair as the dominant category.

Tier boundaries are half-open: a value belongs to a tier when it is greater than or equal to the tier's minimum and strictly less than the tier's maximum. A value of exactly 1.0 belongs to the tier whose maximum is 1.0. This convention applies to both the fill rate tiers and the geographic concentration brackets.

If a region does not appear in a show's listener distribution profile, treat that show-region listener share as zero. If a dominant category is not present in the category demand benchmarks, use a demand index of 1.0.

The recommended CPM is rounded to two decimal places, as is every numeric column governed by the output format specification in the pricing rules file.
"""
    with open(os.path.join(workspace, "policy_overview.md"), "w") as f:
        f.write(policy_md)

    # ─── Scalable data files ───
    # Distribute N files across 4 formats:
    n_json = max(1, round(N * 0.40))
    n_csv = max(1, round(N * 0.25))
    n_yaml = max(1, round(N * 0.20))
    n_txt = N - n_json - n_csv - n_yaml
    if n_txt < 1:
        n_txt = 1
        n_json -= 1

    # --- JSON files: Show listener geographic profiles ---
    shows_per_file = max(1, len(shows) // n_json)
    for idx in range(n_json):
        start = idx * shows_per_file
        end = len(shows) if idx == n_json - 1 else (idx + 1) * shows_per_file
        batch_shows = shows[start:end]

        profiles = {}
        for show in batch_shows:
            show_id = show[0]
            show_name = show[1]

            num_regions_for_show = random.randint(3, min(12, len(regions)))
            chosen_regions = random.sample(regions, num_regions_for_show)

            weights = np.random.dirichlet(np.ones(num_regions_for_show) * 0.5)
            weights = sorted(weights, reverse=True)

            region_dist = {}
            for j, reg in enumerate(chosen_regions):
                region_dist[str(reg[0])] = {
                    "region_name": reg[1],
                    "listener_share": round(float(weights[j]), 4),
                }

            profiles[str(show_id)] = {
                "show_name": show_name,
                "listener_distribution": region_dist,
            }

        fname = f"show_geo_profile_batch_{idx + 1}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(profiles, f, indent=2)

    # --- CSV files: Monthly ad delivery summaries ---
    months = pd.date_range("2025-01-01", periods=12, freq="MS").strftime("%Y_%m").tolist()
    selected_months = (months * (n_csv // 12 + 1))[:n_csv]

    campaign_lookup = {c[0]: c for c in campaigns}

    for idx, month_str in enumerate(selected_months):
        rows = []
        month_prefix = month_str.replace("_", "-")
        month_logs = [il for il in impression_logs if il[4].startswith(month_prefix)]

        if not month_logs:
            sample_campaigns = random.sample(campaigns, min(15, len(campaigns)))
            for camp in sample_campaigns:
                rows.append(
                    {
                        "campaign_id": camp[0],
                        "show_id": camp[2],
                        "region_id": camp[3],
                        "month": month_str,
                        "avg_listen_through_rate": round(random.uniform(0.4, 0.95), 3),
                        "engagement_score": round(random.uniform(1.0, 10.0), 2),
                        "quality_rating": random.choice(["A", "B", "C", "D"]),
                        "listener_feedback_count": random.randint(0, 200),
                    }
                )
        else:
            for log in month_logs:
                camp = campaign_lookup.get(log[1])
                if camp:
                    rows.append(
                        {
                            "campaign_id": log[1],
                            "show_id": log[2],
                            "region_id": log[3],
                            "month": month_str,
                            "avg_listen_through_rate": round(random.uniform(0.4, 0.95), 3),
                            "engagement_score": round(random.uniform(1.0, 10.0), 2),
                            "quality_rating": random.choice(["A", "B", "C", "D"]),
                            "listener_feedback_count": random.randint(0, 200),
                        }
                    )

        df = pd.DataFrame(rows)
        fname = f"monthly_delivery_{month_str}.csv"
        df.to_csv(os.path.join(workspace, fname), index=False)

    # --- YAML files: Category demand benchmarks ---
    cats_per_file = max(1, len(AD_CATEGORIES) // n_yaml)
    for idx in range(n_yaml):
        start = idx * cats_per_file
        end = len(AD_CATEGORIES) if idx == n_yaml - 1 else (idx + 1) * cats_per_file
        batch_cats = AD_CATEGORIES[start:end]

        benchmarks = {}
        for cat in batch_cats:
            benchmarks[cat] = {
                "demand_index": round(random.uniform(0.75, 1.35), 2),
                "avg_fill_rate_benchmark": round(random.uniform(0.45, 0.90), 2),
                "yoy_growth_pct": round(random.uniform(-10, 25), 1),
                "competition_level": random.choice(["high", "medium", "low"]),
            }

        fname = f"category_demand_benchmark_{idx + 1}.yaml"
        with open(os.path.join(workspace, fname), "w") as f:
            yaml.dump(
                {"category_benchmarks": benchmarks}, f,
                default_flow_style=False, sort_keys=False,
            )

    # --- TXT files: Market analysis notes (distractor) ---
    for idx in range(n_txt):
        lines = [f"Market Analysis Notes - Report {idx + 1}", "=" * 40, ""]
        sample_regions = random.sample(regions, min(5, len(regions)))
        for reg in sample_regions:
            lines.append(f"Region: {reg[1]}, {reg[2]} (Tier: {reg[3]})")
            lines.append(f"  Population: {reg[4]:,}")
            lines.append(
                f"  Market outlook: {random.choice(['Growing', 'Stable', 'Declining', 'Emerging'])}"
            )
            lines.append(f"  Key advertisers: {', '.join(fake.company() for _ in range(3))}")
            lines.append(f"  Notes: {fake.paragraph(nb_sentences=2)}")
            lines.append("")

        fname = f"market_analysis_notes_{idx + 1}.txt"
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Generate ad inventory pricing data")
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()

    shows, regions, advertisers, campaigns, impression_logs = create_database(
        args.db_path, args.workspace
    )
    create_workspace(
        args.workspace, shows, regions, advertisers, campaigns, impression_logs
    )
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
