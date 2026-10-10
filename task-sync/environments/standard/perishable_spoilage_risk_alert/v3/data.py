"""
Data generation script for Perishable Goods Spoilage Risk task.
Generates SQLite database and workspace files for the task environment.
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 640,
    "num_workspace_files": 40,
}

# Fixed reference point for the simulation's "now"
REFERENCE_DATETIME = datetime(2025, 1, 15, 8, 0, 0)

CATEGORIES = {
    "Dairy": {
        "shelf_life_range": (5, 14),
        "subcategories": [
            "Whole Milk", "Skim Milk", "Cheddar Cheese", "Mozzarella",
            "Greek Yogurt", "Butter Stick", "Heavy Cream", "Cottage Cheese",
            "Sour Cream", "Cream Cheese",
        ],
        "temp_range": (1, 4),
    },
    "Produce": {
        "shelf_life_range": (3, 10),
        "subcategories": [
            "Spinach", "Kale Mix", "Strawberries", "Blueberries", "Mango",
            "Carrots", "Beets", "Basil", "Cilantro", "Avocado",
        ],
        "temp_range": (2, 6),
    },
    "Meat": {
        "shelf_life_range": (3, 7),
        "subcategories": [
            "Chicken Breast", "Ground Beef", "Pork Chop", "Lamb Leg",
            "Turkey Breast", "Beef Steak", "Pork Tenderloin", "Chicken Thigh",
            "Veal Cutlet", "Beef Ribs",
        ],
        "temp_range": (0, 2),
    },
    "Bakery": {
        "shelf_life_range": (2, 5),
        "subcategories": [
            "Sourdough Bread", "Croissant", "Chocolate Cake", "Dinner Rolls",
            "Blueberry Muffin", "Baguette", "Cinnamon Roll", "Rye Bread",
            "Brioche", "Scone",
        ],
        "temp_range": (18, 22),
    },
    "Seafood": {
        "shelf_life_range": (2, 5),
        "subcategories": [
            "Salmon Fillet", "Shrimp", "Smoked Salmon", "Tuna Steak",
            "Crab Cake", "Cod Fillet", "Lobster Tail", "Oysters",
            "Sea Bass", "Clams",
        ],
        "temp_range": (-1, 2),
    },
    "Deli": {
        "shelf_life_range": (5, 10),
        "subcategories": [
            "Ham Slices", "Turkey Slices", "Caesar Salad", "Hummus",
            "Fresh Fettuccine", "Guacamole", "Roast Beef Slices",
            "Pasta Salad", "Tzatziki", "Pesto",
        ],
        "temp_range": (1, 4),
    },
}

WAREHOUSE_DATA = [
    {"warehouse_id": "WH001", "name": "North Distribution Center", "location": "Newark, NJ", "zone": "Northeast", "capacity": 50000},
    {"warehouse_id": "WH002", "name": "South Regional Hub", "location": "Atlanta, GA", "zone": "Southeast", "capacity": 45000},
    {"warehouse_id": "WH003", "name": "Midwest Logistics Center", "location": "Chicago, IL", "zone": "Midwest", "capacity": 60000},
    {"warehouse_id": "WH004", "name": "West Coast Depot", "location": "Los Angeles, CA", "zone": "West", "capacity": 55000},
    {"warehouse_id": "WH005", "name": "Central Storage Facility", "location": "Dallas, TX", "zone": "South Central", "capacity": 40000},
]

CATEGORY_RISK_FACTORS = {
    "Seafood": 0.95,
    "Meat": 0.90,
    "Dairy": 0.75,
    "Produce": 0.70,
    "Deli": 0.65,
    "Bakery": 0.60,
}

ADJECTIVES = [
    "Premium", "Organic", "Farm Fresh", "Select", "Choice",
    "Natural", "Artisan", "Classic", "Gourmet", "Signature",
    "Heritage", "Golden", "Valley", "Sunrise", "Harvest",
    "Country", "Royal", "Prime", "Estate", "Garden",
]


def generate_products(n_products, rng, fake):
    """Generate product records."""
    products = []
    cat_names = list(CATEGORIES.keys())
    used_names = set()

    for i in range(n_products):
        cat = cat_names[i % len(cat_names)]
        cat_info = CATEGORIES[cat]
        subcat = cat_info["subcategories"][i % len(cat_info["subcategories"])]
        shelf_min, shelf_max = cat_info["shelf_life_range"]
        shelf_life = int(rng.integers(shelf_min, shelf_max + 1))

        # Generate unique product name
        adj_idx = (i // len(cat_names)) % len(ADJECTIVES)
        variant = (i // (len(cat_names) * len(ADJECTIVES))) + 1
        name = f"{ADJECTIVES[adj_idx]} {subcat}"
        if variant > 1:
            name += f" #{variant}"
        # Ensure uniqueness
        while name in used_names:
            variant += 1
            name = f"{ADJECTIVES[adj_idx]} {subcat} #{variant}"
        used_names.add(name)

        unit_price = round(float(rng.uniform(1.50, 28.00)), 2)
        temp_min, temp_max = cat_info["temp_range"]

        products.append({
            "product_id": f"PRD-{i + 1:04d}",
            "name": name,
            "category": cat,
            "subcategory": subcat,
            "unit_price": unit_price,
            "shelf_life_days": shelf_life,
            "storage_temp_min": temp_min,
            "storage_temp_max": temp_max,
        })

    return products


def generate_inventory_batches(products, n_batches, rng):
    """Generate inventory batch records with controlled expiry distribution."""
    batches = []
    warehouse_ids = [w["warehouse_id"] for w in WAREHOUSE_DATA]
    n_products = len(products)

    # Determine how many batches are at-risk (within 48 hours of expiry)
    n_at_risk = max(8, n_batches // 5)  # ~20%

    for i in range(n_batches):
        prod = products[i % n_products]
        wh = warehouse_ids[i % len(warehouse_ids)]
        shelf_life = prod["shelf_life_days"]
        quantity = int(rng.integers(20, 500))

        if i < n_at_risk:
            # At-risk batch: expires within 0-48 hours of reference
            hours_to_expiry = float(rng.uniform(1.0, 47.5))
            expiry_dt = REFERENCE_DATETIME + timedelta(hours=hours_to_expiry)
        elif i < n_at_risk + n_batches // 4:
            # Near-expiry but not at risk: 3-7 days out
            days_out = float(rng.uniform(3.0, 7.0))
            expiry_dt = REFERENCE_DATETIME + timedelta(days=days_out)
        else:
            # Safe: 7-30 days out
            days_out = float(rng.uniform(7.0, 30.0))
            expiry_dt = REFERENCE_DATETIME + timedelta(days=days_out)

        received_dt = expiry_dt - timedelta(days=shelf_life)

        batches.append({
            "batch_id": f"BAT-{i + 1:05d}",
            "product_id": prod["product_id"],
            "warehouse_id": wh,
            "quantity": quantity,
            "received_date": received_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "expiry_date": expiry_dt.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return batches


def generate_daily_sales(products, n_sales_records, rng):
    """Generate daily sales records for the past 7 days."""
    sales = []
    warehouse_ids = [w["warehouse_id"] for w in WAREHOUSE_DATA]
    n_products = len(products)

    # Generate sales for the past 7 days
    dates = [(REFERENCE_DATETIME - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(1, 8)]

    record_id = 0
    products_cycle = list(range(n_products))
    rng.shuffle(products_cycle)

    while record_id < n_sales_records:
        for prod_idx in products_cycle:
            if record_id >= n_sales_records:
                break
            prod = products[prod_idx]
            wh = warehouse_ids[record_id % len(warehouse_ids)]
            date = dates[record_id % len(dates)]
            # Sales velocity varies by category
            base_sales = int(rng.integers(2, 40))
            sales.append({
                "sale_id": f"SLE-{record_id + 1:06d}",
                "product_id": prod["product_id"],
                "warehouse_id": wh,
                "sale_date": date,
                "quantity_sold": base_sales,
            })
            record_id += 1

    return sales


def generate_promotions(products, n_promos, rng):
    """Generate promotion records, some overlapping with at-risk period."""
    promos = []
    n_products = len(products)
    promo_names = [
        "Flash Sale", "Weekend Deal", "Clearance Event", "Buy One Get One",
        "Manager Special", "Holiday Promo", "Loyalty Bonus", "Bundle Offer",
        "Seasonal Markdown", "Limited Time Offer",
    ]

    selected_products = rng.choice(n_products, size=min(n_promos, n_products), replace=False)

    for i in range(n_promos):
        prod_idx = int(selected_products[i % len(selected_products)])
        prod = products[prod_idx]
        # Some promotions start within the next 3 days (overlap with at-risk window)
        if i % 3 == 0:
            start_offset = float(rng.uniform(0, 3))
        else:
            start_offset = float(rng.uniform(3, 14))

        start_dt = REFERENCE_DATETIME + timedelta(days=start_offset)
        duration = int(rng.integers(2, 7))
        end_dt = start_dt + timedelta(days=duration)
        discount = int(rng.choice([10, 15, 20, 25, 30, 40, 50]))
        lift = round(float(rng.uniform(1.1, 2.5)), 2)

        promos.append({
            "promo_id": f"PRM-{i + 1:04d}",
            "product_id": prod["product_id"],
            "promo_name": promo_names[i % len(promo_names)],
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": end_dt.strftime("%Y-%m-%d"),
            "discount_pct": discount,
            "expected_sales_lift": lift,
        })

    return promos


def create_database(db_path, products, batches, sales, promotions):
    """Create SQLite database with all tables."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Products table
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            unit_price REAL NOT NULL,
            shelf_life_days INTEGER NOT NULL,
            storage_temp_min REAL NOT NULL,
            storage_temp_max REAL NOT NULL
        )
    """)

    # Warehouses table
    c.execute("""
        CREATE TABLE IF NOT EXISTS warehouses (
            warehouse_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            zone TEXT NOT NULL,
            capacity INTEGER NOT NULL
        )
    """)

    # Inventory batches table
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory_batches (
            batch_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            received_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
        )
    """)

    # Daily sales table
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_sales (
            sale_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sale_date TEXT NOT NULL,
            quantity_sold INTEGER NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
        )
    """)

    # Promotions table
    c.execute("""
        CREATE TABLE IF NOT EXISTS promotions (
            promo_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            promo_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            discount_pct INTEGER NOT NULL,
            expected_sales_lift REAL NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
    """)

    # Insert data
    for p in products:
        c.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
            (p["product_id"], p["name"], p["category"], p["subcategory"],
             p["unit_price"], p["shelf_life_days"], p["storage_temp_min"], p["storage_temp_max"]),
        )

    for w in WAREHOUSE_DATA:
        c.execute(
            "INSERT INTO warehouses VALUES (?,?,?,?,?)",
            (w["warehouse_id"], w["name"], w["location"], w["zone"], w["capacity"]),
        )

    for b in batches:
        c.execute(
            "INSERT INTO inventory_batches VALUES (?,?,?,?,?,?)",
            (b["batch_id"], b["product_id"], b["warehouse_id"],
             b["quantity"], b["received_date"], b["expiry_date"]),
        )

    for s in sales:
        c.execute(
            "INSERT INTO daily_sales VALUES (?,?,?,?,?)",
            (s["sale_id"], s["product_id"], s["warehouse_id"],
             s["sale_date"], s["quantity_sold"]),
        )

    for pr in promotions:
        c.execute(
            "INSERT INTO promotions VALUES (?,?,?,?,?,?,?)",
            (pr["promo_id"], pr["product_id"], pr["promo_name"],
             pr["start_date"], pr["end_date"], pr["discount_pct"], pr["expected_sales_lift"]),
        )

    conn.commit()
    conn.close()


def generate_supplement_data(products, rng, fake):
    """Generate supplementary product data (supplier info) for workspace files."""
    supplements = []
    for prod in products:
        supplements.append({
            "product_id": prod["product_id"],
            "supplier_name": fake.company(),
            "supplier_reliability": round(float(rng.uniform(0.55, 0.99)), 2),
            "unit_weight_kg": round(float(rng.uniform(0.1, 5.0)), 2),
        })
    return supplements


def write_supplement_csv(filepath, records):
    """Write supplement records as CSV."""
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "supplier_name", "supplier_reliability", "unit_weight_kg"])
        writer.writeheader()
        writer.writerows(records)


def write_supplement_json(filepath, records):
    """Write supplement records as JSON."""
    with open(filepath, "w") as f:
        json.dump(records, f, indent=2)


def write_supplement_yaml(filepath, records):
    """Write supplement records as YAML."""
    with open(filepath, "w") as f:
        yaml.dump({"product_supplements": records}, f, default_flow_style=False)


def write_supplement_txt(filepath, records):
    """Write supplement records as tab-separated text."""
    with open(filepath, "w") as f:
        f.write("product_id\tsupplier_name\tsupplier_reliability\tunit_weight_kg\n")
        for r in records:
            f.write(f"{r['product_id']}\t{r['supplier_name']}\t{r['supplier_reliability']}\t{r['unit_weight_kg']}\n")


def generate_workspace(workspace, products, rng, fake):
    """Generate all workspace files."""
    os.makedirs(workspace, exist_ok=True)

    # --- Fixed config files (not scaling) ---

    # config.yaml: reference datetime, priority weights, markdown tiers
    config = {
        "reference_datetime": REFERENCE_DATETIME.strftime("%Y-%m-%dT%H:%M:%S"),
        "priority_weights": {
            "urgency": 0.35,
            "overstock": 0.25,
            "category_risk": 0.20,
            "supplier_risk": 0.10,
            "promo_conflict": 0.10,
        },
        "markdown_tiers": [
            {"max_hours": 12, "markdown_pct": 50},
            {"max_hours": 24, "markdown_pct": 35},
            {"max_hours": 36, "markdown_pct": 25},
            {"max_hours": 48, "markdown_pct": 15},
        ],
        "overstock_threshold_days": 3.0,
    }
    with open(os.path.join(workspace, "config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # category_risk_factors.json
    with open(os.path.join(workspace, "category_risk_factors.json"), "w") as f:
        json.dump(CATEGORY_RISK_FACTORS, f, indent=2)

    # --- Scalable data files ---
    n_files = SCALE["num_workspace_files"]
    supplements = generate_supplement_data(products, rng, fake)

    # Split supplement data across files
    chunk_size = math.ceil(len(supplements) / n_files)
    format_writers = [
        ("csv", write_supplement_csv),
        ("json", write_supplement_json),
        ("yaml", write_supplement_yaml),
        ("txt", write_supplement_txt),
    ]

    for i in range(n_files):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, len(supplements))
        if start >= len(supplements):
            # More files than data chunks; wrap around
            start = start % len(supplements)
            end = min(start + chunk_size, len(supplements))
        chunk = supplements[start:end]

        fmt_ext, writer_fn = format_writers[i % len(format_writers)]
        filename = f"product_supplement_{i + 1:02d}.{fmt_ext}"
        writer_fn(os.path.join(workspace, filename), chunk)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Seed everything
    random.seed(42)
    np.random.seed(42)
    rng = np.random.default_rng(42)
    fake = Faker()
    Faker.seed(42)

    n_products = SCALE["rows_per_table"]
    n_batches = SCALE["rows_per_table"] * 2
    n_sales = SCALE["rows_per_table"] * 7  # ~7 days of records
    n_promos = SCALE["rows_per_table"] // 2

    products = generate_products(n_products, rng, fake)
    batches = generate_inventory_batches(products, n_batches, rng)
    sales = generate_daily_sales(products, n_sales, rng)
    promotions = generate_promotions(products, n_promos, rng)

    create_database(args.db_path, products, batches, sales, promotions)
    generate_workspace(args.workspace, products, rng, fake)

    print(f"Database created at {args.db_path}")
    print(f"  Products: {len(products)}")
    print(f"  Batches: {len(batches)}")
    print(f"  Sales records: {len(sales)}")
    print(f"  Promotions: {len(promotions)}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Scalable files: {SCALE['num_workspace_files']}")
    print(f"  Fixed config files: 2")


if __name__ == "__main__":
    main()
