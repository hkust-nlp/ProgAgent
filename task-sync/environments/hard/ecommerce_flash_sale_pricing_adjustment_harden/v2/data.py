"""
Data generation for e-commerce flash sale pricing task.
Generates a SQLite database and workspace files for the task environment.
"""

import os
import json
import csv
import sqlite3
import argparse
import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 200,      # v2 = 4x base
    "num_workspace_files": 24,  # v2 = base + 2N (N = 8)
}

CATEGORIES = [
    "Electronics", "Home & Kitchen", "Sports", "Fashion",
    "Beauty", "Books", "Toys", "Automotive",
]

COMPETITORS = ["MegaMart", "ShopNow", "ValueStore", "PrimeDeal", "QuickBuy"]

WAREHOUSES = ["WH-EAST", "WH-WEST", "WH-CENTRAL"]

COMPETITOR_REPUTATION = {
    "MegaMart": 0.85,
    "ShopNow": 0.70,
    "ValueStore": 0.90,
    "PrimeDeal": 1.00,
    "QuickBuy": 0.75,
}

WAREHOUSE_PRIORITY = {
    "WH-EAST": {"name": "East Coast Hub", "priority_weight": 1.0},
    "WH-WEST": {"name": "West Coast Hub", "priority_weight": 0.8},
    "WH-CENTRAL": {"name": "Central Hub", "priority_weight": 0.9},
}

ELIGIBLE_CATEGORIES = ["Electronics", "Home & Kitchen", "Sports", "Fashion", "Beauty"]


def create_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            base_price REAL NOT NULL,
            cost_price REAL NOT NULL,
            brand TEXT NOT NULL,
            supplier TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS competitor_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            competitor_name TEXT NOT NULL,
            competitor_price REAL NOT NULL,
            price_timestamp TEXT NOT NULL,
            in_stock INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            current_stock INTEGER NOT NULL,
            monthly_units_sold INTEGER NOT NULL,
            last_restock_date TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_segments (
            segment_id TEXT PRIMARY KEY,
            segment_name TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            avg_ltv_score REAL NOT NULL,
            avg_order_value REAL NOT NULL,
            churn_risk REAL NOT NULL
        )
    """)


def generate_products(cursor, fake, num_products):
    products = []
    for i in range(num_products):
        pid = f"P{i+1:04d}"
        category = CATEGORIES[i % len(CATEGORIES)]
        base_price = round(float(np.random.uniform(15, 500)), 2)
        margin_ratio = float(np.random.uniform(0.10, 0.55))
        cost_price = round(base_price * (1 - margin_ratio), 2)
        product = {
            "product_id": pid,
            "product_name": fake.catch_phrase(),
            "category": category,
            "base_price": base_price,
            "cost_price": cost_price,
            "brand": fake.company(),
            "supplier": fake.company(),
        }
        products.append(product)
        cursor.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
            (product["product_id"], product["product_name"], product["category"],
             product["base_price"], product["cost_price"], product["brand"],
             product["supplier"]),
        )
    return products


def generate_segments(cursor, fake, num_segments):
    descriptors = [
        "Budget", "Premium", "Casual", "Loyal", "New",
        "Returning", "Seasonal", "Impulse", "Value", "Elite",
    ]
    interests = [
        "Tech", "Home", "Fashion", "Sports", "Beauty",
        "General", "Outdoor", "Lifestyle", "Trendy", "Classic",
    ]
    segments = []
    for i in range(num_segments):
        sid = f"SEG{i+1:03d}"
        desc = descriptors[i % len(descriptors)]
        area = interests[i % len(interests)]
        segment = {
            "segment_id": sid,
            "segment_name": f"{desc} {area} Shoppers",
            "member_count": int(np.random.randint(500, 50000)),
            "avg_ltv_score": round(float(np.random.uniform(50, 950)), 2),
            "avg_order_value": round(float(np.random.uniform(20, 300)), 2),
            "churn_risk": round(float(np.random.uniform(0.05, 0.85)), 4),
        }
        segments.append(segment)
        cursor.execute(
            "INSERT INTO customer_segments VALUES (?,?,?,?,?,?)",
            (segment["segment_id"], segment["segment_name"],
             segment["member_count"], segment["avg_ltv_score"],
             segment["avg_order_value"], segment["churn_risk"]),
        )
    return segments


def generate_competitor_prices(cursor, fake, products):
    rows = []
    for p in products:
        num_comps = int(np.random.randint(2, len(COMPETITORS) + 1))
        chosen = list(np.random.choice(COMPETITORS, size=num_comps, replace=False))
        for comp in chosen:
            variation = float(np.random.uniform(-0.25, 0.15))
            comp_price = round(p["base_price"] * (1 + variation), 2)
            in_stock = int(np.random.random() > 0.15)
            ts = fake.date_time_between(start_date="-7d", end_date="now").isoformat()
            row = {
                "product_id": p["product_id"],
                "competitor_name": comp,
                "competitor_price": comp_price,
                "price_timestamp": ts,
                "in_stock": in_stock,
            }
            rows.append(row)
            cursor.execute(
                "INSERT INTO competitor_prices "
                "(product_id, competitor_name, competitor_price, price_timestamp, in_stock) "
                "VALUES (?,?,?,?,?)",
                (row["product_id"], row["competitor_name"],
                 row["competitor_price"], row["price_timestamp"],
                 row["in_stock"]),
            )
    return rows


def generate_inventory(cursor, fake, products):
    rows = []
    for p in products:
        num_wh = int(np.random.randint(1, len(WAREHOUSES) + 1))
        chosen = list(np.random.choice(WAREHOUSES, size=num_wh, replace=False))
        for wh in chosen:
            row = {
                "product_id": p["product_id"],
                "warehouse_id": wh,
                "current_stock": int(np.random.randint(10, 2000)),
                "monthly_units_sold": int(np.random.randint(5, 500)),
                "last_restock_date": fake.date_between(
                    start_date="-60d", end_date="today"
                ).isoformat(),
            }
            rows.append(row)
            cursor.execute(
                "INSERT INTO inventory "
                "(product_id, warehouse_id, current_stock, monthly_units_sold, last_restock_date) "
                "VALUES (?,?,?,?,?)",
                (row["product_id"], row["warehouse_id"],
                 row["current_stock"], row["monthly_units_sold"],
                 row["last_restock_date"]),
            )
    return rows


def generate_workspace_files(workspace, products, segments, num_clickstream_files, fake):
    # ---- Fixed configuration files ----

    # 1. campaign_config.yaml
    campaign_config = {
        "campaign_name": "Summer Flash Sale 2026",
        "eligible_categories": list(ELIGIBLE_CATEGORIES),
        "min_margin_pct": 15.0,
        "max_discount_pct": 45.0,
        "scoring_weights": {
            "engagement": 0.30,
            "price_competitiveness": 0.25,
            "inventory_urgency": 0.25,
            "segment_value": 0.20,
        },
    }
    with open(os.path.join(workspace, "campaign_config.yaml"), "w") as f:
        yaml.dump(campaign_config, f, default_flow_style=False, sort_keys=False)

    # 2. discount_tiers.json
    discount_tiers = {
        "tiers": [
            {"tier_name": "Platinum", "min_score": 75.0, "base_discount_pct": 40},
            {"tier_name": "Gold", "min_score": 55.0, "base_discount_pct": 30},
            {"tier_name": "Silver", "min_score": 35.0, "base_discount_pct": 20},
            {"tier_name": "Bronze", "min_score": 15.0, "base_discount_pct": 10},
            {"tier_name": "NoDiscount", "min_score": 0.0, "base_discount_pct": 0},
        ],
        "note": "Tiers are evaluated top-down; a product falls into the first tier whose min_score it meets or exceeds.",
    }
    with open(os.path.join(workspace, "discount_tiers.json"), "w") as f:
        json.dump(discount_tiers, f, indent=2)

    # 3. competitor_reputation.csv
    with open(os.path.join(workspace, "competitor_reputation.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["competitor_name", "reputation_weight"])
        writer.writeheader()
        for name, weight in COMPETITOR_REPUTATION.items():
            writer.writerow({"competitor_name": name, "reputation_weight": weight})

    # 4. warehouse_config.yaml
    warehouse_config = {"warehouses": {}}
    for wid, info in WAREHOUSE_PRIORITY.items():
        warehouse_config["warehouses"][wid] = {
            "name": info["name"],
            "priority_weight": info["priority_weight"],
        }
    with open(os.path.join(workspace, "warehouse_config.yaml"), "w") as f:
        yaml.dump(warehouse_config, f, default_flow_style=False, sort_keys=False)

    # 5. pricing_policy.md
    pricing_policy = """## Eligibility

A product is eligible for the flash sale only if its category appears in the
eligible_categories list of the campaign configuration. Every eligible product
that survives margin enforcement (see below) must appear in the pricing
schedule, including products that land in the zero-discount tier.

## Scoring Dimensions

Four raw values are computed for every eligible product.

1. Engagement. Source: the daily clickstream session logs
   (clickstream_day_NN.csv). Aggregate events across all available day files
   for each product, weighting each event type as follows: page_view = 1,
   click = 2, add_to_cart = 3, purchase = 5. The sum of weighted events is the
   raw engagement value. A product with no clickstream events has a raw
   engagement of zero.

2. Price competitiveness. Consider only competitor price entries where the
   competitor has the product in stock. Weight each such price by the
   competitor's reputation weight (competitor_reputation.csv) and compute the
   weighted average competitor price as sum(price x weight) / sum(weight).
   The raw price competitiveness value is
   (base_price - weighted_average) / base_price x 100. If no competitor
   carries the product in stock, the raw value is zero.

3. Inventory urgency. For every warehouse entry holding the product, days of
   supply = current_stock / (monthly_units_sold / 30). The raw inventory
   urgency value is the weighted average of days of supply across all
   warehouses holding the product, using each warehouse's priority weight
   from the warehouse configuration.

4. Segment value. For every clickstream event tied to a product, look up the
   average lifetime value score of the customer segment that produced the
   event. The raw segment value is the arithmetic mean of those scores across
   all of the product's clickstream events. A product with no clickstream
   events has a raw segment value of zero.

## Normalization and Composite Score

Normalize each dimension independently to a 0-100 scale using min-max scaling
across the eligible product set: within each dimension the product with the
lowest raw value receives 0 and the one with the highest receives 100 (see the
edge case below). The composite score is the weighted sum of the four
normalized sub-scores, applying the scoring_weights from the campaign
configuration.

## Tier Assignment and Discount Cap

Evaluate the tier definitions from the tier table top to bottom and assign
the first tier whose min_score the product's composite score meets or
exceeds. The product's initial discount percentage is that tier's
base_discount_pct. The max_discount_pct from the campaign configuration is an
absolute cap that no product's discount may exceed.

## Sale Price

The sale price is base_price x (1 - discount_pct / 100), rounded to two
decimal places. If the sale price at the assigned discount falls below the
margin floor defined below, reduce the discount to the largest whole-number
percentage that keeps the sale price at or above the floor; if even a
one-percent discount would violate the floor, exclude the product from the
schedule entirely.

## Normalization Edge Case

When all eligible products share the same raw value in any scoring dimension, min-max normalization is undefined. In that case assign a normalized score of 50.0 to every product in that dimension.

## Margin Enforcement Formula

A product's sale price must satisfy the minimum-margin constraint:

    sale_price >= cost_price / (1 - min_margin_pct / 100)

where min_margin_pct is specified in the campaign configuration. This guarantees that the gross margin percentage (sale_price - cost_price) / sale_price never drops below the threshold.

To find the maximum permissible discount percentage for a given product:

    max_discount = floor( (1 - cost_price / (base_price * (1 - min_margin_pct / 100))) * 100 )

If max_discount is less than 1 the product cannot participate in the sale at any discount level and must be excluded from the schedule.
"""
    with open(os.path.join(workspace, "pricing_policy.md"), "w") as f:
        f.write(pricing_policy)

    # ---- Scalable clickstream files ----
    num_products = len(products)
    num_segments = len(segments)
    product_ids = [p["product_id"] for p in products]
    segment_ids = [s["segment_id"] for s in segments]

    event_types = ["page_view", "click", "add_to_cart", "purchase"]
    event_probs = [0.45, 0.30, 0.15, 0.10]

    events_per_file = max(80, num_products * 2)

    for day_idx in range(num_clickstream_files):
        day_num = day_idx + 1
        rows = []
        for _ in range(events_per_file):
            pid = product_ids[int(np.random.randint(0, num_products))]
            seg = segment_ids[int(np.random.randint(0, num_segments))]
            event = str(np.random.choice(event_types, p=event_probs))
            ts = fake.date_time_between(
                start_date=f"-{num_clickstream_files + 1 - day_idx}d",
                end_date=f"-{num_clickstream_files - day_idx}d",
            ).isoformat()
            session_id = fake.uuid4()[:8]
            rows.append({
                "session_id": session_id,
                "product_id": pid,
                "customer_segment_id": seg,
                "event_type": event,
                "timestamp": ts,
            })
        df = pd.DataFrame(rows)
        df.to_csv(
            os.path.join(workspace, f"clickstream_day_{day_num:02d}.csv"),
            index=False,
        )


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    create_tables(cursor)

    num_products = SCALE["rows_per_table"]
    num_segments = SCALE["rows_per_table"]
    num_clickstream_files = SCALE["num_workspace_files"]

    products = generate_products(cursor, fake, num_products)
    segments = generate_segments(cursor, fake, num_segments)
    generate_competitor_prices(cursor, fake, products)
    generate_inventory(cursor, fake, products)

    conn.commit()
    conn.close()

    generate_workspace_files(workspace, products, segments, num_clickstream_files, fake)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
