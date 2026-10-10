"""
Data generation script for competitor price monitoring task.
Generates database and workspace files for the price adjustment alert task.
"""

import os
import argparse
import sqlite3
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 32,
}

# ---------------------------------------------------------------------------
# Seed everything
# ---------------------------------------------------------------------------
fake = Faker()
Faker.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REFERENCE_DATE = datetime(2025, 3, 15)

CATEGORIES = ["Beauty & Health", "Electronics", "Home & Kitchen", "Office Supplies", "Sports & Outdoors"]

CATEGORY_ITEMS = {
    "Electronics": [
        "Speaker", "Headphones", "Charger", "Adapter", "Monitor", "Keyboard",
        "Mouse", "Webcam", "Microphone", "Tablet Stand", "Cable", "Power Bank",
        "Router", "Smart Plug", "LED Strip", "Flash Drive", "Card Reader",
        "Docking Station", "Surge Protector", "Wireless Earbuds",
    ],
    "Home & Kitchen": [
        "Blender", "Scale", "Toaster", "Mixer", "Pan", "Knife Set",
        "Cutting Board", "Container Set", "Timer", "Thermometer", "Grinder",
        "Peeler", "Spatula Set", "Colander", "Whisk", "Measuring Cup",
        "Can Opener", "Ice Tray", "Baking Sheet", "Dish Rack",
    ],
    "Sports & Outdoors": [
        "Water Bottle", "Yoga Mat", "Resistance Band", "Jump Rope",
        "Foam Roller", "Dumbbell", "Backpack", "Headlamp", "Compass",
        "Sunglasses", "Gloves", "Cap", "Towel", "Armband", "Whistle",
        "Knee Brace", "Sweatband", "Grip Trainer", "Ankle Weights", "Pull-Up Bar",
    ],
    "Beauty & Health": [
        "Moisturizer", "Serum", "Sunscreen", "Shampoo", "Conditioner",
        "Face Mask", "Lip Balm", "Deodorant", "Body Wash", "Hand Cream",
        "Hair Oil", "Toner", "Eye Cream", "Cleanser", "Scrub",
        "Nail Kit", "Brush Set", "Cotton Pads", "Hair Clip Set", "Mirror",
    ],
    "Office Supplies": [
        "Notebook", "Pen Set", "Stapler", "Tape Dispenser", "Desk Lamp",
        "Organizer", "Clipboard", "Calculator", "Paper Shredder", "Label Maker",
        "Binder", "Folder Set", "Whiteboard", "Marker Set", "Stamp",
        "Envelope Pack", "Sticky Notes", "Paper Tray", "Desk Pad", "Bookends",
    ],
}

MODIFIERS = [
    "Pro", "Elite", "Ultra", "Max", "Lite", "Mini", "Plus", "Essential",
    "Classic", "Advanced", "Basic", "Premium", "Deluxe", "Eco", "Smart",
    "Compact", "Turbo", "Flex", "Core", "Prime",
]

CATEGORY_PRICE_RANGE = {
    "Electronics": (15.0, 200.0),
    "Home & Kitchen": (10.0, 120.0),
    "Sports & Outdoors": (8.0, 90.0),
    "Beauty & Health": (5.0, 60.0),
    "Office Supplies": (4.0, 80.0),
}

CATEGORY_CODES = {
    "Electronics": "ELEC",
    "Home & Kitchen": "HOME",
    "Sports & Outdoors": "SPRT",
    "Beauty & Health": "BEAU",
    "Office Supplies": "OFFC",
}

COMPETITORS = [
    "PriceKing", "MegaMart", "ValueStore", "QuickShop",
    "BargainBox", "DealDirect", "ShopSmart", "MarketHub",
]

COMPETITOR_TIERS = {
    "PriceKing": "A",
    "MegaMart": "A",
    "ValueStore": "B",
    "QuickShop": "B",
    "BargainBox": "B",
    "DealDirect": "C",
    "ShopSmart": "C",
    "MarketHub": "A",
}

SUPPLIER_NAMES = [
    "GlobalSource Ltd", "PrimeParts Co", "DirectFactory Inc",
    "BulkTrade Corp", "QualityFirst Supply", "ValueChain Wholesale",
]

CATEGORY_MIN_MARGIN = {
    "Electronics": 18.0,
    "Home & Kitchen": 22.0,
    "Sports & Outdoors": 20.0,
    "Beauty & Health": 25.0,
    "Office Supplies": 15.0,
}

CATEGORY_ALLOW_PROMOTION = {
    "Electronics": True,
    "Home & Kitchen": True,
    "Sports & Outdoors": True,
    "Beauty & Health": False,
    "Office Supplies": True,
}

CATEGORY_PRIORITY = {
    "Electronics": 1,
    "Home & Kitchen": 2,
    "Sports & Outdoors": 3,
    "Beauty & Health": 4,
    "Office Supplies": 5,
}


def generate_products(n_products):
    """Generate product data."""
    products = []
    per_cat = n_products // len(CATEGORIES)
    remainder = n_products % len(CATEGORIES)

    product_id = 1
    for cat_idx, cat in enumerate(CATEGORIES):
        count = per_cat + (1 if cat_idx < remainder else 0)
        items = CATEGORY_ITEMS[cat]
        lo, hi = CATEGORY_PRICE_RANGE[cat]
        code = CATEGORY_CODES[cat]

        for i in range(count):
            item_name = items[i % len(items)]
            modifier = MODIFIERS[i % len(MODIFIERS)]
            name = f"{modifier} {item_name}"
            sku = f"{code}-{product_id:04d}"
            current_price = round(np.random.uniform(lo, hi), 2)
            list_price = round(current_price * np.random.uniform(1.0, 1.35), 2)
            status = "active" if np.random.random() < 0.88 else "discontinued"
            products.append({
                "id": product_id,
                "sku": sku,
                "name": name,
                "category": cat,
                "current_price": current_price,
                "list_price": list_price,
                "status": status,
            })
            product_id += 1

    return products


def generate_competitor_prices(products, n_days):
    """Generate competitor price observations over n_days."""
    rows = []
    row_id = 1
    for product in products:
        base_price = product["current_price"]
        for comp in COMPETITORS:
            # Each competitor covers ~75% of products
            if np.random.random() < 0.25:
                continue
            # Competitor price varies around our price
            comp_base = base_price * np.random.uniform(0.80, 1.15)
            for day_offset in range(n_days):
                date = REFERENCE_DATE - timedelta(days=n_days - 1 - day_offset)
                # Small daily fluctuation
                daily_price = round(comp_base * np.random.uniform(0.97, 1.03), 2)
                in_stock = 1 if np.random.random() < 0.85 else 0
                rows.append({
                    "id": row_id,
                    "product_id": product["id"],
                    "competitor_name": comp,
                    "scrape_date": date.strftime("%Y-%m-%d"),
                    "price": daily_price,
                    "in_stock": in_stock,
                })
                row_id += 1
    return rows


def generate_supplier_costs(products):
    """Generate supplier cost data. Each product has 1-3 suppliers."""
    rows = []
    row_id = 1
    for product in products:
        n_suppliers = np.random.choice([1, 2, 3], p=[0.2, 0.5, 0.3])
        chosen_suppliers = np.random.choice(SUPPLIER_NAMES, size=n_suppliers, replace=False)
        for supplier in chosen_suppliers:
            # Supplier cost is 40-75% of current price
            unit_cost = round(product["current_price"] * np.random.uniform(0.40, 0.75), 2)
            moq = int(np.random.choice([10, 25, 50, 100, 200]))
            lead_time = int(np.random.choice([3, 5, 7, 10, 14, 21]))
            valid_until = (REFERENCE_DATE + timedelta(days=np.random.randint(30, 180))).strftime("%Y-%m-%d")
            rows.append({
                "id": row_id,
                "product_id": product["id"],
                "supplier_name": supplier,
                "unit_cost": unit_cost,
                "moq": moq,
                "lead_time_days": lead_time,
                "valid_until": valid_until,
            })
            row_id += 1
    return rows


def generate_conversion_history(products, n_days=30):
    """Generate daily conversion metrics for each product."""
    rows = []
    row_id = 1
    for product in products:
        base_views = np.random.randint(50, 500)
        base_conv_rate = np.random.uniform(0.02, 0.12)
        # Decide trend: declining, stable, or improving
        trend_type = np.random.choice(["declining", "stable", "improving"], p=[0.35, 0.35, 0.30])
        for day_offset in range(n_days):
            date = REFERENCE_DATE - timedelta(days=n_days - 1 - day_offset)
            # Apply trend
            progress = day_offset / max(n_days - 1, 1)
            if trend_type == "declining":
                trend_mult = 1.0 - 0.3 * progress
            elif trend_type == "improving":
                trend_mult = 1.0 + 0.3 * progress
            else:
                trend_mult = 1.0

            views = max(10, int(base_views * trend_mult * np.random.uniform(0.8, 1.2)))
            conv_rate = max(0.005, base_conv_rate * trend_mult * np.random.uniform(0.85, 1.15))
            add_to_cart = max(1, int(views * conv_rate * np.random.uniform(1.5, 3.0)))
            purchases = max(0, int(views * conv_rate * np.random.uniform(0.8, 1.2)))
            revenue = round(purchases * product["current_price"] * np.random.uniform(0.9, 1.1), 2)

            rows.append({
                "id": row_id,
                "product_id": product["id"],
                "date": date.strftime("%Y-%m-%d"),
                "page_views": views,
                "add_to_cart": add_to_cart,
                "purchases": purchases,
                "revenue": revenue,
            })
            row_id += 1
    return rows


def create_database(db_path, products, competitor_prices, supplier_costs, conversion_history):
    """Create and populate the SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            sku TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            current_price REAL NOT NULL,
            list_price REAL NOT NULL,
            status TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS competitor_prices (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            competitor_name TEXT NOT NULL,
            scrape_date TEXT NOT NULL,
            price REAL NOT NULL,
            in_stock INTEGER NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS supplier_costs (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            supplier_name TEXT NOT NULL,
            unit_cost REAL NOT NULL,
            moq INTEGER NOT NULL,
            lead_time_days INTEGER NOT NULL,
            valid_until TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS conversion_history (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            page_views INTEGER NOT NULL,
            add_to_cart INTEGER NOT NULL,
            purchases INTEGER NOT NULL,
            revenue REAL NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    for p in products:
        c.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
            (p["id"], p["sku"], p["name"], p["category"],
             p["current_price"], p["list_price"], p["status"]),
        )

    for r in competitor_prices:
        c.execute(
            "INSERT INTO competitor_prices VALUES (?,?,?,?,?,?)",
            (r["id"], r["product_id"], r["competitor_name"],
             r["scrape_date"], r["price"], r["in_stock"]),
        )

    for r in supplier_costs:
        c.execute(
            "INSERT INTO supplier_costs VALUES (?,?,?,?,?,?,?)",
            (r["id"], r["product_id"], r["supplier_name"],
             r["unit_cost"], r["moq"], r["lead_time_days"], r["valid_until"]),
        )

    for r in conversion_history:
        c.execute(
            "INSERT INTO conversion_history VALUES (?,?,?,?,?,?,?)",
            (r["id"], r["product_id"], r["date"],
             r["page_views"], r["add_to_cart"], r["purchases"], r["revenue"]),
        )

    conn.commit()
    conn.close()


def generate_workspace_files(workspace, products, competitor_prices):
    """Generate workspace files: scaled scrape CSVs + fixed config files."""
    os.makedirs(workspace, exist_ok=True)

    n_scrape_files = SCALE["num_workspace_files"]

    # ---- Fixed config files ----

    # 1. pricing_policy.yaml
    policy = {
        "default_min_margin_pct": 20.0,
        "max_discount_pct": 30.0,
        "review_period_days": 7,
        "price_match_window_hours": 48,
        "conversion_decline_threshold": 0.10,
        "conversion_lookback_days": 14,
        "comparison_split_day": 7,
    }
    with open(os.path.join(workspace, "pricing_policy.yaml"), "w") as f:
        # Write YAML manually to avoid pyyaml dependency issues
        for k, v in policy.items():
            f.write(f"{k}: {v}\n")

    # 2. competitor_tiers.json
    with open(os.path.join(workspace, "competitor_tiers.json"), "w") as f:
        json.dump(COMPETITOR_TIERS, f, indent=2)

    # 3. category_config.csv
    with open(os.path.join(workspace, "category_config.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "min_margin_pct", "allow_promotion", "priority"])
        for cat in CATEGORIES:
            writer.writerow([
                cat,
                CATEGORY_MIN_MARGIN[cat],
                "yes" if CATEGORY_ALLOW_PROMOTION[cat] else "no",
                CATEGORY_PRIORITY[cat],
            ])

    # 4. promotion_rules.txt
    with open(os.path.join(workspace, "promotion_rules.txt"), "w") as f:
        f.write("Promotion Eligibility Rules\n")
        f.write("==========================\n\n")
        f.write("A product may be recommended for promotion only when ALL of the following hold:\n\n")
        f.write("1. The product status is active.\n")
        f.write("2. The product's category allows promotions (see category configuration).\n")
        f.write("3. At least one qualifying competitor offers a lower price that we cannot match\n")
        f.write("   without breaching the category minimum margin.\n")
        f.write("4. The product's conversion trend over the review period is declining.\n\n")
        f.write("A conversion trend is classified as follows, using the comparison split day\n")
        f.write("defined in the pricing policy. Compute the average daily purchases for the\n")
        f.write("recent window (the last comparison_split_day days of the lookback period) and\n")
        f.write("the earlier window (the first comparison_split_day days of the lookback period).\n")
        f.write("If the ratio recent_avg / earlier_avg is below (1 - conversion_decline_threshold),\n")
        f.write("the trend is 'declining'. If it exceeds (1 + conversion_decline_threshold), the\n")
        f.write("trend is 'improving'. Otherwise it is 'stable'.\n\n")
        f.write("When a promotion is recommended, the suggested mechanism is a temporary price\n")
        f.write("reduction not exceeding the max_discount_pct defined in the pricing policy.\n")

    # ---- Scaled scrape files ----
    # Build a lookup: (product_id, competitor, date) -> price row from DB
    price_lookup = {}
    for r in competitor_prices:
        key = (r["product_id"], r["competitor_name"], r["scrape_date"])
        price_lookup[key] = r

    product_map = {p["id"]: p for p in products}

    # Generate price flags deterministically
    rng = np.random.RandomState(42)

    for file_idx in range(n_scrape_files):
        date = REFERENCE_DATE - timedelta(days=n_scrape_files - 1 - file_idx)
        date_str = date.strftime("%Y-%m-%d")
        filename = f"daily_scrape_{date.strftime('%Y%m%d')}.csv"

        scrape_rows = []
        for product in products:
            for comp in COMPETITORS:
                key = (product["id"], comp, date_str)
                if key not in price_lookup:
                    continue
                # ~70% coverage in each scrape file
                if rng.random() < 0.30:
                    continue
                pr = price_lookup[key]
                # Assign price flag
                flag_roll = rng.random()
                if flag_roll < 0.08:
                    price_flag = "clearance"
                elif flag_roll < 0.14:
                    price_flag = "bundle"
                elif flag_roll < 0.18:
                    price_flag = "limited_time"
                else:
                    price_flag = "normal"

                notes = ""
                if price_flag == "clearance":
                    notes = "End-of-line clearance pricing"
                elif price_flag == "bundle":
                    notes = "Bundled with accessories"
                elif price_flag == "limited_time":
                    notes = "Flash sale or limited offer"

                scrape_rows.append({
                    "product_sku": product["sku"],
                    "competitor_name": comp,
                    "observed_price": pr["price"],
                    "in_stock": "yes" if pr["in_stock"] else "no",
                    "price_flag": price_flag,
                    "notes": notes,
                })

        with open(os.path.join(workspace, filename), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "product_sku", "competitor_name", "observed_price",
                "in_stock", "price_flag", "notes",
            ])
            writer.writeheader()
            for row in scrape_rows:
                writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_products = SCALE["rows_per_table"]
    n_scrape_days = SCALE["num_workspace_files"] + 6  # DB has a few extra days beyond scrape files

    products = generate_products(n_products)
    competitor_prices = generate_competitor_prices(products, n_scrape_days)
    supplier_costs = generate_supplier_costs(products)
    conversion_history = generate_conversion_history(products, n_days=30)

    create_database(args.db_path, products, competitor_prices, supplier_costs, conversion_history)
    generate_workspace_files(args.workspace, products, competitor_prices)

    print(f"Database created at {args.db_path}")
    print(f"  products: {len(products)}")
    print(f"  competitor_prices: {len(competitor_prices)}")
    print(f"  supplier_costs: {len(supplier_costs)}")
    print(f"  conversion_history: {len(conversion_history)}")
    print(f"Workspace files generated in {args.workspace}/")
    print(f"  Scrape files: {SCALE['num_workspace_files']}")
    print(f"  Config files: 4")


if __name__ == "__main__":
    main()
