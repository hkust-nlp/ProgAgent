"""
Data generation for competitor pricing intelligence task.
Generates database tables and workspace files for cross-referencing
daily web-scraped price lists, historical pricing, internal cost sheets,
and product catalog mappings to identify market share threats.
"""

import argparse
import os
import sqlite3
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

# Fix all seeds
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

CATEGORIES = [
    "Electronics", "Home Appliances", "Office Supplies",
    "Personal Care", "Kitchen", "Outdoor", "Automotive", "Sports"
]

REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America"]
CHANNELS = ["Online Marketplace", "Direct Retail", "Wholesale", "Hybrid"]


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        sku TEXT NOT NULL UNIQUE,
        brand TEXT NOT NULL,
        launch_date TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS competitors (
        competitor_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        region TEXT NOT NULL,
        channel TEXT NOT NULL,
        reliability_score REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS internal_costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL UNIQUE,
        unit_cost REAL NOT NULL,
        overhead_rate REAL NOT NULL,
        target_margin REAL NOT NULL,
        floor_price REAL NOT NULL,
        current_price REAL NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS catalog_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        competitor_id INTEGER NOT NULL,
        competitor_sku TEXT NOT NULL UNIQUE,
        competitor_product_name TEXT NOT NULL,
        match_confidence REAL NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(product_id),
        FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        competitor_id INTEGER NOT NULL,
        record_date TEXT NOT NULL,
        price REAL NOT NULL,
        source TEXT NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(product_id),
        FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
    )""")
    conn.commit()


def generate_products(conn, n):
    products = []
    used_names = set()
    for i in range(1, n + 1):
        cat = CATEGORIES[(i - 1) % len(CATEGORIES)]
        while True:
            w1 = fake.word().capitalize()
            w2 = fake.word().capitalize()
            name = f"{w1} {w2} {cat.split()[0][:4]}-{i}"
            if name not in used_names:
                used_names.add(name)
                break
        sku = f"INT-{i:05d}"
        brand = fake.company()
        launch_date = fake.date_between(
            start_date="-3y", end_date="-6m"
        ).isoformat()
        products.append((i, name, cat, sku, brand, launch_date))
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)
    conn.commit()
    return products


def generate_competitors(conn, n):
    competitors = []
    prefixes = []
    used_prefixes = set()
    suffixes = ["Retail", "Direct", "Market", "Store", "Shop",
                "Outlet", "Hub", "Plaza", "Trade", "Central"]
    for i in range(1, n + 1):
        name = fake.company() + " " + suffixes[(i - 1) % len(suffixes)]
        region = REGIONS[(i - 1) % len(REGIONS)]
        channel = CHANNELS[(i - 1) % len(CHANNELS)]
        reliability = round(random.uniform(0.50, 1.00), 2)
        competitors.append((i, name, region, channel, reliability))
        while True:
            prefix = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=3))
            if prefix not in used_prefixes:
                used_prefixes.add(prefix)
                prefixes.append(prefix)
                break
    conn.executemany("INSERT INTO competitors VALUES (?,?,?,?,?)", competitors)
    conn.commit()
    return competitors, prefixes


def generate_internal_costs(conn, products):
    costs = []
    cost_map = {}
    base_ranges = {
        "Electronics": (50, 500), "Home Appliances": (30, 300),
        "Office Supplies": (5, 80), "Personal Care": (3, 50),
        "Kitchen": (10, 150), "Outdoor": (20, 200),
        "Automotive": (15, 250), "Sports": (10, 180),
    }
    for prod in products:
        pid, cat = prod[0], prod[2]
        lo, hi = base_ranges.get(cat, (10, 100))
        unit_cost = round(random.uniform(lo, hi), 2)
        overhead_rate = round(random.uniform(0.08, 0.25), 2)
        target_margin = round(random.uniform(0.15, 0.40), 2)
        min_viable = unit_cost * (1 + overhead_rate)
        floor_price = round(min_viable * 1.05, 2)
        current_price = round(floor_price * (1 + target_margin), 2)
        costs.append((pid, unit_cost, overhead_rate, target_margin,
                       floor_price, current_price))
        cost_map[pid] = {
            "unit_cost": unit_cost, "overhead_rate": overhead_rate,
            "target_margin": target_margin, "floor_price": floor_price,
            "current_price": current_price,
        }
    conn.executemany(
        "INSERT INTO internal_costs "
        "(product_id,unit_cost,overhead_rate,target_margin,floor_price,"
        "current_price) VALUES (?,?,?,?,?,?)", costs)
    conn.commit()
    return cost_map


def generate_catalog_mappings(conn, products, competitors, prefixes,
                               n_mappings):
    mappings = []
    sku_counter = {}
    product_ids = [p[0] for p in products]
    competitor_ids = [c[0] for c in competitors]
    cid_to_idx = {c[0]: idx for idx, c in enumerate(competitors)}
    used_pairs = set()

    for _ in range(n_mappings):
        for _attempt in range(200):
            pid = random.choice(product_ids)
            cid = random.choice(competitor_ids)
            if (pid, cid) not in used_pairs:
                used_pairs.add((pid, cid))
                break
        else:
            continue

        idx = cid_to_idx[cid]
        prefix = prefixes[idx]
        sku_counter.setdefault(cid, 1000)
        sku_counter[cid] += 1
        comp_sku = f"{prefix}-{sku_counter[cid]}"

        prod_name = next(p[1] for p in products if p[0] == pid)
        variant = random.choice(["Pro", "Plus", "Series", "Edition",
                                  "Model", "V2", "Elite", "Basic",
                                  "Std", "Max"])
        comp_prod_name = prod_name.split("-")[0].strip() + " " + variant
        confidence = round(random.uniform(0.70, 0.99), 2)
        mappings.append((pid, cid, comp_sku, comp_prod_name, confidence))

    conn.executemany(
        "INSERT INTO catalog_mappings "
        "(product_id,competitor_id,competitor_sku,"
        "competitor_product_name,match_confidence) "
        "VALUES (?,?,?,?,?)", mappings)
    conn.commit()
    return mappings


def generate_price_history(conn, mappings, cost_map, n_history):
    history = []
    base_date = datetime(2024, 1, 15)
    n_map = len(mappings)

    for i in range(n_history):
        m = mappings[i % n_map]
        pid, cid = m[0], m[1]
        days_back = random.randint(1, 90)
        record_date = (base_date - timedelta(days=days_back)).isoformat()[:10]
        floor_price = cost_map[pid]["floor_price"]
        price = round(floor_price * random.uniform(0.75, 1.35), 2)
        source = random.choice(["web_scrape", "api_feed", "manual_entry"])
        history.append((pid, cid, record_date, price, source))

    conn.executemany(
        "INSERT INTO price_history "
        "(product_id,competitor_id,record_date,price,source) "
        "VALUES (?,?,?,?,?)", history)
    conn.commit()


def generate_workspace_files(workspace, products, competitors, prefixes,
                              mappings, cost_map):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]

    # ---- Scalable scraped-price CSV files ----
    mapped_cids = sorted(set(m[1] for m in mappings))
    random.shuffle(mapped_cids)
    n_comp = min(len(mapped_cids), max(4, n_files // 2))
    scraped_cids = mapped_cids[:n_comp]

    base_date = datetime(2024, 1, 15)
    file_assignments = []
    for i in range(n_files):
        cid = scraped_cids[i % n_comp]
        date_offset = i // n_comp
        scrape_date = (base_date - timedelta(days=date_offset)).isoformat()[:10]
        file_assignments.append((cid, scrape_date))

    for cid, scrape_date in file_assignments:
        comp_maps = [m for m in mappings if m[1] == cid]
        if not comp_maps:
            continue
        rows = []
        for m in comp_maps:
            pid, comp_sku, comp_prod_name = m[0], m[2], m[3]
            floor_price = cost_map[pid]["floor_price"]
            r = random.random()
            if r < 0.25:
                price = round(floor_price * random.uniform(0.68, 0.84), 2)
            elif r < 0.50:
                price = round(floor_price * random.uniform(0.90, 0.995), 2)
            elif r < 0.70:
                price = round(floor_price * random.uniform(1.00, 1.04), 2)
            else:
                price = round(floor_price * random.uniform(1.10, 1.40), 2)
            rows.append({
                "competitor_sku": comp_sku,
                "product_name": comp_prod_name,
                "listed_price": f"{price:.2f}",
                "currency": "USD",
                "scrape_timestamp": (
                    f"{scrape_date}T{random.randint(8,20):02d}:"
                    f"{random.randint(0,59):02d}:00"
                ),
            })
        # noise entries (unrecognised SKUs)
        for _ in range(random.randint(1, 3)):
            rows.append({
                "competitor_sku": f"UNK-{random.randint(10000,99999)}",
                "product_name": fake.bs().title(),
                "listed_price": f"{round(random.uniform(10, 500), 2):.2f}",
                "currency": "USD",
                "scrape_timestamp": (
                    f"{scrape_date}T{random.randint(8,20):02d}:"
                    f"{random.randint(0,59):02d}:00"
                ),
            })
        fname = f"scrape_competitor_{cid}_{scrape_date}.csv"
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, fname), index=False)

    # ---- Fixed configuration files (not scaled) ----

    # 1. alert_thresholds.json  — per-category thresholds
    thresholds = {}
    for cat in CATEGORIES:
        if cat in ("Electronics", "Automotive"):
            thresholds[cat] = {"critical_threshold_pct": 15,
                               "watch_threshold_pct": 5}
        elif cat in ("Home Appliances", "Kitchen"):
            thresholds[cat] = {"critical_threshold_pct": 10,
                               "watch_threshold_pct": 4}
        elif cat in ("Office Supplies", "Personal Care"):
            thresholds[cat] = {"critical_threshold_pct": 12,
                               "watch_threshold_pct": 5}
        else:
            thresholds[cat] = {"critical_threshold_pct": 10,
                               "watch_threshold_pct": 3}
    with open(os.path.join(workspace, "alert_thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=2)

    # 2. pricing_rules.yaml
    yaml_text = """\
alert_classification:
  critical:
    description: "Competitor price undercuts floor by more than the category critical threshold"
    condition: "price_gap_pct < -critical_threshold_pct"
    priority: 1
  warning:
    description: "Competitor price is below floor price but within the critical threshold"
    condition: "-critical_threshold_pct <= price_gap_pct < 0"
    priority: 2
  watch:
    description: "Competitor price is at or above floor but within the watch threshold"
    condition: "0 <= price_gap_pct < watch_threshold_pct"
    priority: 3

price_gap_formula: "(competitor_price - floor_price) / floor_price * 100"

dashboard_sort:
  primary: "priority ascending"
  secondary: "price_gap_pct ascending"

output_precision: 2
"""
    with open(os.path.join(workspace, "pricing_rules.yaml"), "w") as f:
        f.write(yaml_text)

    # 3. adjustment_policy.md
    policy = """\
# Price Adjustment Policy

When responding to competitive pricing threats the following adjustment
rules apply.

For products classified at the critical alert level, the recommended
price should be set to the competitor's latest scraped price multiplied
by 0.98 (i.e. two percent below the competitor). However, the
recommended price must never fall below the product's minimum viable
price, defined as unit_cost multiplied by (1 + overhead_rate).

For products at the warning alert level, the recommended price is
calculated as the simple average of the product's floor price and the
competitor's latest scraped price. The same minimum viable price floor
applies.

Products classified at the watch level do not require a price change.
The recommended price for watch-level entries equals the product's
current selling price.

All monetary values in the output must be rounded to exactly two
decimal places. The adjustment percentage is defined as
(recommended_price - current_price) / current_price * 100, also rounded
to two decimal places.
"""
    with open(os.path.join(workspace, "adjustment_policy.md"), "w") as f:
        f.write(policy)

    # 4. competitor_tiers.txt
    tiers = """\
Competitor Reliability Tiers
============================

Tier A (High Reliability): reliability_score >= 0.85
  Price data is considered highly accurate.
  Full weight in threat assessment.

Tier B (Medium Reliability): 0.70 <= reliability_score < 0.85
  Price data may contain minor inaccuracies.
  90 percent weight in threat assessment.

Tier C (Low Reliability): reliability_score < 0.70
  Price data should be treated with caution.
  Exclude from the final alert dashboard entirely.

Only alerts sourced from Tier A and Tier B competitors appear in the
dashboard. Tier C competitor entries must be omitted.
"""
    with open(os.path.join(workspace, "competitor_tiers.txt"), "w") as f:
        f.write(tiers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Re-seed for full reproducibility
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    global fake
    fake = Faker()
    Faker.seed(42)

    n = SCALE["rows_per_table"]

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    products = generate_products(conn, n)
    competitors, prefixes = generate_competitors(conn, n)
    cost_map = generate_internal_costs(conn, products)

    # catalog_mappings: ~2x base to ensure good product-competitor coverage
    n_mappings = max(n, n * 2)
    mappings = generate_catalog_mappings(conn, products, competitors,
                                          prefixes, n_mappings)

    # price_history: ~2x base for historical depth
    n_history = max(n, n * 2)
    generate_price_history(conn, mappings, cost_map, n_history)

    conn.close()

    generate_workspace_files(args.workspace, products, competitors,
                              prefixes, mappings, cost_map)

    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")
    print(f"Scale: rows_per_table={n}, "
          f"num_workspace_files={SCALE['num_workspace_files']}")


if __name__ == "__main__":
    main()
