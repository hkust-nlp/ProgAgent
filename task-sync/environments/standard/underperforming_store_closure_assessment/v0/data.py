import argparse
import os
import sqlite3
import json
import csv
import math
import random

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}

SEED = 42

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
STORE_TYPES = ["Flagship", "Standard", "Outlet", "Express"]
CHANNELS = ["Digital", "Print", "TV", "Social Media", "Events"]

CITIES_BY_REGION = {
    "Northeast": [
        "New York", "Boston", "Philadelphia", "Hartford", "Providence",
        "Newark", "Pittsburgh", "Baltimore", "Albany", "Syracuse",
        "Stamford", "Trenton", "Worcester", "Manchester", "Portland ME",
    ],
    "Southeast": [
        "Atlanta", "Miami", "Charlotte", "Nashville", "Orlando",
        "Tampa", "Raleigh", "Jacksonville", "Richmond", "Memphis",
        "Savannah", "Charleston", "Birmingham", "Knoxville", "Greensboro",
    ],
    "Midwest": [
        "Chicago", "Detroit", "Minneapolis", "Columbus", "Indianapolis",
        "Milwaukee", "Cleveland", "St. Louis", "Kansas City", "Cincinnati",
        "Omaha", "Madison", "Des Moines", "Grand Rapids", "Dayton",
    ],
    "Southwest": [
        "Dallas", "Houston", "Phoenix", "San Antonio", "Austin",
        "Tucson", "El Paso", "Albuquerque", "Oklahoma City", "Tulsa",
        "Mesa", "Arlington", "Lubbock", "Scottsdale", "Plano",
    ],
    "West": [
        "Los Angeles", "San Francisco", "Seattle", "Denver", "Portland",
        "San Diego", "Sacramento", "Las Vegas", "Salt Lake City", "Honolulu",
        "Boise", "Reno", "Anchorage", "Spokane", "Fresno",
    ],
}


def main(db_path, workspace):
    random.seed(SEED)
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    os.makedirs(workspace, exist_ok=True)

    num_stores = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ---- Create tables ----
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS stores (
            store_id TEXT PRIMARY KEY,
            store_name TEXT NOT NULL,
            region TEXT NOT NULL,
            city TEXT NOT NULL,
            address TEXT,
            store_type TEXT,
            square_footage INTEGER,
            employee_count INTEGER,
            open_date TEXT
        );
        CREATE TABLE IF NOT EXISTS monthly_revenue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            gross_revenue REAL,
            net_revenue REAL,
            transaction_count INTEGER,
            avg_ticket REAL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );
        CREATE TABLE IF NOT EXISTS competitors (
            competitor_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            competitor_name TEXT,
            distance_km REAL,
            category TEXT,
            status TEXT,
            first_seen TEXT,
            last_seen TEXT,
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );
        CREATE TABLE IF NOT EXISTS lease_contracts (
            lease_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            monthly_rent REAL,
            lease_start TEXT,
            lease_end TEXT,
            proposed_renewal_rent REAL,
            renewal_term_years INTEGER,
            landlord TEXT,
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );
        CREATE TABLE IF NOT EXISTS marketing_spend (
            spend_id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            channel TEXT,
            spend_amount REAL,
            attributed_revenue REAL
        );
    """)

    # ======================================================================
    # Generate store data
    # ======================================================================
    stores = []
    for i in range(num_stores):
        region = REGIONS[i % len(REGIONS)]
        city_list = CITIES_BY_REGION[region]
        city = city_list[(i // len(REGIONS)) % len(city_list)]
        store_id = f"S{i + 1:04d}"
        store_name = f"{fake.company()} {city}"
        store_type = STORE_TYPES[i % len(STORE_TYPES)]
        sqft = random.randint(1500, 15000)
        employees = max(5, sqft // 500 + random.randint(-2, 5))
        open_year = random.randint(2010, 2022)
        open_date = (
            f"{open_year}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        )
        stores.append(
            {
                "store_id": store_id,
                "store_name": store_name,
                "region": region,
                "city": city,
                "address": fake.address().replace("\n", ", "),
                "store_type": store_type,
                "square_footage": sqft,
                "employee_count": employees,
                "open_date": open_date,
            }
        )

    cursor.executemany(
        "INSERT INTO stores VALUES "
        "(:store_id,:store_name,:region,:city,:address,"
        ":store_type,:square_footage,:employee_count,:open_date)",
        stores,
    )

    # ======================================================================
    # Generate monthly revenue (24 months: 2023-01 to 2024-12)
    # ======================================================================
    revenue_records = []
    for s in stores:
        sid = s["store_id"]
        sqft = s["square_footage"]
        base_rev = sqft * random.uniform(15, 45)

        r = random.random()
        if r < 0.35:
            m_change = random.uniform(-0.025, -0.005)
        elif r < 0.80:
            m_change = random.uniform(-0.003, 0.003)
        else:
            m_change = random.uniform(0.005, 0.02)

        for mo in range(24):
            year = 2023 + mo // 12
            month = mo % 12 + 1
            factor = 1 + m_change * mo
            seasonal = 1 + 0.1 * np.sin(2 * np.pi * (month - 1) / 12)
            noise = np.random.uniform(0.92, 1.08)
            gross = max(0.0, base_rev * factor * seasonal * noise)
            net = gross * random.uniform(0.82, 0.92)
            txn = max(1, int(gross / random.uniform(25, 75)))
            revenue_records.append(
                {
                    "store_id": sid,
                    "year": year,
                    "month": month,
                    "gross_revenue": round(gross, 2),
                    "net_revenue": round(net, 2),
                    "transaction_count": txn,
                    "avg_ticket": round(gross / txn, 2),
                }
            )

    cursor.executemany(
        "INSERT INTO monthly_revenue "
        "(store_id, year, month, gross_revenue, net_revenue, "
        "transaction_count, avg_ticket) "
        "VALUES (:store_id,:year,:month,:gross_revenue,:net_revenue,"
        ":transaction_count,:avg_ticket)",
        revenue_records,
    )

    # ======================================================================
    # Generate competitors
    # ======================================================================
    comp_records = []
    comp_id = 0
    categories = ["Direct", "Adjacent", "Online-Hybrid", "Discount"]
    for s in stores:
        sid = s["store_id"]
        n_comp = random.randint(2, 8)
        for _ in range(n_comp):
            comp_id += 1
            fs_year = random.choice([2019, 2020, 2021, 2022, 2023, 2024])
            fs_month = random.randint(1, 12)
            first_seen = f"{fs_year}-{fs_month:02d}-01"
            if random.random() < 0.12:
                status = "closed"
                cy = max(fs_year + 1, random.randint(2023, 2024))
                cm = random.randint(1, 12)
                last_seen = f"{min(cy, 2024)}-{cm:02d}-01"
            else:
                status = "active"
                last_seen = "2024-12-31"
            comp_records.append(
                {
                    "competitor_id": f"C{comp_id:05d}",
                    "store_id": sid,
                    "competitor_name": fake.company(),
                    "distance_km": round(random.uniform(0.1, 5.0), 2),
                    "category": random.choice(categories),
                    "status": status,
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                }
            )

    cursor.executemany(
        "INSERT INTO competitors VALUES "
        "(:competitor_id,:store_id,:competitor_name,:distance_km,"
        ":category,:status,:first_seen,:last_seen)",
        comp_records,
    )

    # ======================================================================
    # Generate lease contracts (one per store)
    # ======================================================================
    lease_records = []
    for s in stores:
        sid = s["store_id"]
        sqft = s["square_footage"]
        monthly_rent = round(sqft * random.uniform(2, 8), 2)
        start_year = random.randint(2019, 2022)
        term = random.choice([3, 5, 7])
        inc_pct = random.uniform(-0.05, 0.40)
        proposed = round(monthly_rent * (1 + inc_pct), 2)
        lease_records.append(
            {
                "lease_id": f"L{sid[1:]}",
                "store_id": sid,
                "monthly_rent": monthly_rent,
                "lease_start": f"{start_year}-01-01",
                "lease_end": f"{start_year + term}-01-01",
                "proposed_renewal_rent": proposed,
                "renewal_term_years": random.choice([3, 5]),
                "landlord": fake.company(),
            }
        )

    cursor.executemany(
        "INSERT INTO lease_contracts VALUES "
        "(:lease_id,:store_id,:monthly_rent,:lease_start,:lease_end,"
        ":proposed_renewal_rent,:renewal_term_years,:landlord)",
        lease_records,
    )

    # ======================================================================
    # Generate marketing spend
    # ======================================================================
    mkt_records = []
    for region in REGIONS:
        for year in [2023, 2024]:
            for month in range(1, 13):
                for channel in CHANNELS:
                    spend = round(random.uniform(5000, 50000), 2)
                    if region in ["Midwest", "Southwest"]:
                        roi_mult = random.uniform(1.5, 4.0)
                    else:
                        roi_mult = random.uniform(3.0, 8.0)
                    attributed = round(spend * roi_mult, 2)
                    mkt_records.append(
                        {
                            "region": region,
                            "year": year,
                            "month": month,
                            "channel": channel,
                            "spend_amount": spend,
                            "attributed_revenue": attributed,
                        }
                    )

    cursor.executemany(
        "INSERT INTO marketing_spend "
        "(region, year, month, channel, spend_amount, attributed_revenue) "
        "VALUES (:region,:year,:month,:channel,:spend_amount,:attributed_revenue)",
        mkt_records,
    )

    conn.commit()

    # ==================================================================
    # Workspace files
    # ==================================================================

    # ---- Fixed configuration files (not counted in SCALE) ----

    policy = {
        "scoring_weights": {
            "revenue_trend": 0.35,
            "competitor_pressure": 0.25,
            "lease_cost_impact": 0.20,
            "marketing_efficiency": 0.20,
        },
        "closure_threshold": 55.0,
        "tiebreaker": "store_id_ascending",
        "revenue_trend_config": {
            "comparison": "last_12_months_vs_previous_12_months",
            "metric": "net_revenue",
            "method": "percentage_change",
            "decline_score_mapping": {
                "severe_decline_threshold_pct": -15.0,
                "moderate_decline_threshold_pct": -5.0,
                "severe_score": 100,
                "moderate_score": 65,
                "mild_score": 35,
                "stable_or_growing_score": 10,
            },
        },
        "competitor_pressure_config": {
            "new_competitor_window_start": "2024-01-01",
            "density_radius_km": 3.0,
            "count_only_active": True,
            "scoring": {
                "high_pressure_min_new": 3,
                "high_pressure_score": 100,
                "medium_pressure_min_new": 1,
                "medium_pressure_score": 60,
                "low_pressure_score": 20,
            },
        },
        "lease_cost_config": {
            "increase_thresholds": {
                "high_increase_pct": 0.20,
                "moderate_increase_pct": 0.10,
            },
            "base_scores": {
                "high_increase_score": 100,
                "moderate_increase_score": 60,
                "low_increase_score": 20,
                "decrease_score": 5,
            },
            "flexibility_adjustment": {
                "high_flexibility_min": 7,
                "high_flexibility_discount": 0.30,
                "medium_flexibility_min": 4,
                "medium_flexibility_discount": 0.15,
            },
        },
        "marketing_efficiency_config": {
            "evaluation_year": 2024,
            "roi_thresholds": {
                "low_roi_max": 3.0,
                "medium_roi_max": 5.0,
            },
            "scores": {
                "low_roi_score": 100,
                "medium_roi_score": 55,
                "high_roi_score": 15,
            },
        },
        "savings_calculation": {
            "rent_basis": "proposed_renewal_rent",
            "annual_ops": "sum_of_monthly_costs_times_12",
            "projected_revenue": "last_12m_net_total_times_one_plus_trend_fraction",
            "formula": "annual_rent + annual_ops - projected_annual_net_revenue",
        },
    }

    with open(os.path.join(workspace, "closure_scoring_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    bench_rng = random.Random(SEED + 100)
    regional_benchmarks = {}
    for region in REGIONS:
        regional_benchmarks[region] = {
            "target_revenue_per_sqft_monthly": round(bench_rng.uniform(25, 40), 2),
            "acceptable_annual_decline_pct": -5.0,
            "min_acceptable_marketing_roi": 3.5,
        }

    with open(os.path.join(workspace, "regional_benchmarks.json"), "w") as f:
        json.dump(regional_benchmarks, f, indent=2)

    savings_guide = (
        "Estimated Annual Cost Savings Calculation\n"
        "==========================================\n"
        "\n"
        "For each store recommended for closure, the estimated annual cost\n"
        "savings is computed as follows:\n"
        "\n"
        "  Annual Rent = proposed monthly renewal rent x 12\n"
        "\n"
        "  Annual Operational Costs = (monthly utilities + monthly maintenance\n"
        "      + monthly insurance + monthly supplies + monthly miscellaneous) x 12\n"
        "\n"
        "  Projected Annual Net Revenue = total net revenue over the last\n"
        "      12 months x (1 + revenue_trend_percentage / 100)\n"
        "\n"
        "  where revenue_trend_percentage =\n"
        "      (sum of net revenue for months 2024-01 through 2024-12\n"
        "       minus sum of net revenue for months 2023-01 through 2023-12)\n"
        "      divided by sum of net revenue for months 2023-01 through 2023-12\n"
        "      multiplied by 100\n"
        "\n"
        "  Estimated Annual Savings = Annual Rent + Annual Operational Costs\n"
        "      - Projected Annual Net Revenue\n"
        "\n"
        "A positive value indicates net savings from closure. Round the final\n"
        "savings figure to the nearest whole number.\n"
    )

    with open(os.path.join(workspace, "savings_calculation_guide.txt"), "w") as f:
        f.write(savings_guide)

    # ---- Scalable data files ----
    # CSV files containing per-store operational costs and landlord flexibility
    ws_rng = random.Random(SEED + 200)

    store_ws_data = {}
    for s in stores:
        sid = s["store_id"]
        sqft = s["square_footage"]
        store_ws_data[sid] = {
            "monthly_utilities": round(sqft * ws_rng.uniform(0.5, 2.0), 2),
            "monthly_maintenance": round(sqft * ws_rng.uniform(0.3, 1.5), 2),
            "monthly_insurance": round(ws_rng.uniform(500, 3000), 2),
            "monthly_supplies": round(ws_rng.uniform(200, 2000), 2),
            "monthly_misc": round(ws_rng.uniform(100, 1000), 2),
            "landlord_flexibility_score": ws_rng.randint(1, 10),
        }

    store_ids = [s["store_id"] for s in stores]
    batch_size = math.ceil(num_stores / num_files)

    for fi in range(num_files):
        batch = store_ids[fi * batch_size : (fi + 1) * batch_size]
        if not batch:
            continue
        filepath = os.path.join(workspace, f"store_data_{fi + 1:03d}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "store_id",
                    "monthly_utilities",
                    "monthly_maintenance",
                    "monthly_insurance",
                    "monthly_supplies",
                    "monthly_misc",
                    "landlord_flexibility_score",
                ]
            )
            for sid in batch:
                d = store_ws_data[sid]
                writer.writerow(
                    [
                        sid,
                        d["monthly_utilities"],
                        d["monthly_maintenance"],
                        d["monthly_insurance"],
                        d["monthly_supplies"],
                        d["monthly_misc"],
                        d["landlord_flexibility_score"],
                    ]
                )

    conn.close()
    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")
    print(f"  - {num_stores} stores across {num_files} data files")
    print(f"  - 3 fixed config files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
