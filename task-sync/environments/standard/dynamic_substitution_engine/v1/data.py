"""
Data generation script for the Dynamic Substitution Engine task.
Generates a grocery product database, customer orders, inventory, and workspace files
for an out-of-stock substitution task.
"""

import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 160,      # v1 = 2× base
    "num_workspace_files": 16,  # v1 = base + N
}

# ── Deterministic seeds ─────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ────────────────────────────────────────────────────────
CATEGORIES = {
    "Dairy": ["Milk", "Cheese", "Yogurt", "Butter", "Cream"],
    "Bakery": ["Bread", "Rolls", "Pastries", "Tortillas", "Bagels"],
    "Beverages": ["Juice", "Soda", "Water", "Tea", "Coffee"],
    "Snacks": ["Chips", "Crackers", "Nuts", "Granola Bars", "Popcorn"],
    "Frozen": ["Ice Cream", "Frozen Vegetables", "Frozen Meals", "Frozen Pizza", "Frozen Fruit"],
    "Produce": ["Fruit", "Vegetables", "Herbs", "Salad Mix", "Mushrooms"],
    "Meat": ["Chicken", "Beef", "Pork", "Turkey", "Sausage"],
    "Pantry": ["Pasta", "Rice", "Canned Goods", "Cereal", "Condiments"],
}

BRANDS = [
    "NatureFirst", "GreenValley", "FarmFresh", "OrganicChoice", "PureBite",
    "DailyHarvest", "SunnyFields", "GoldenCrest", "HomeStyle", "PrimeSelect",
    "ValuePick", "EcoBasket", "FreshCo", "TrueNature", "HealthyWay",
    "SimplyGood", "BestBuy Groceries", "TopShelf", "LocalPride", "NutriWell",
]

DIETARY_TAGS = ["organic", "gluten-free", "vegan", "low-sodium", "sugar-free",
                "non-gmo", "kosher", "halal", "nut-free", "dairy-free"]

ALLERGENS = ["milk", "eggs", "peanuts", "tree_nuts", "wheat", "soy", "fish", "shellfish"]

PRICE_TIERS = ["budget", "standard", "premium"]


def create_tables(conn: sqlite3.Connection):
    """Create all database tables."""
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            brand TEXT NOT NULL,
            unit_price REAL NOT NULL,
            unit_size REAL NOT NULL,
            unit_type TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS nutritional_profiles (
            product_id INTEGER PRIMARY KEY,
            calories REAL,
            protein_g REAL,
            fat_g REAL,
            carbs_g REAL,
            fiber_g REAL,
            sugar_g REAL,
            sodium_mg REAL,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );

        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            price_sensitivity_tier TEXT NOT NULL,
            loyalty_score INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        CREATE TABLE IF NOT EXISTS order_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            is_out_of_stock INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );

        CREATE TABLE IF NOT EXISTS inventory (
            product_id INTEGER PRIMARY KEY,
            current_stock INTEGER NOT NULL,
            warehouse_section TEXT NOT NULL,
            last_restocked TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );
    """)
    conn.commit()


def generate_products(n: int) -> pd.DataFrame:
    """Generate product catalog."""
    rows = []
    unit_types = ["oz", "ml", "g", "ct", "lb"]
    for i in range(1, n + 1):
        cat = random.choice(list(CATEGORIES.keys()))
        subcat = random.choice(CATEGORIES[cat])
        brand = random.choice(BRANDS)
        price = round(random.uniform(1.5, 18.0), 2)
        size = round(random.choice([6, 8, 12, 16, 24, 32, 64, 100, 200, 500]), 1)
        utype = random.choice(unit_types)
        name = f"{brand} {subcat} {int(size)}{utype}"
        rows.append((i, name, cat, subcat, brand, price, size, utype))
    return pd.DataFrame(rows, columns=[
        "product_id", "name", "category", "subcategory", "brand",
        "unit_price", "unit_size", "unit_type"
    ])


def generate_nutritional(product_ids: list) -> pd.DataFrame:
    """Generate nutritional profiles for each product."""
    rows = []
    for pid in product_ids:
        rows.append((
            pid,
            round(random.uniform(50, 600), 1),   # calories
            round(random.uniform(0, 30), 1),      # protein
            round(random.uniform(0, 25), 1),      # fat
            round(random.uniform(0, 80), 1),      # carbs
            round(random.uniform(0, 12), 1),      # fiber
            round(random.uniform(0, 40), 1),      # sugar
            round(random.uniform(5, 1200), 1),    # sodium
        ))
    return pd.DataFrame(rows, columns=[
        "product_id", "calories", "protein_g", "fat_g", "carbs_g",
        "fiber_g", "sugar_g", "sodium_mg"
    ])


def generate_customers(n: int) -> pd.DataFrame:
    """Generate customer profiles."""
    rows = []
    for i in range(1, n + 1):
        rows.append((
            i,
            fake.name(),
            fake.email(),
            random.choice(PRICE_TIERS),
            random.randint(1, 100),
        ))
    return pd.DataFrame(rows, columns=[
        "customer_id", "name", "email", "price_sensitivity_tier", "loyalty_score"
    ])


def generate_orders_and_items(num_orders: int, num_products: int, num_customers: int):
    """Generate orders and order items, marking some items as out-of-stock."""
    order_rows = []
    item_rows = []
    # Ensure a meaningful fraction of orders have at least one OOS item.
    # We'll mark ~20 % of all items as OOS.
    oos_product_set = set(random.sample(range(1, num_products + 1),
                                        k=max(5, num_products // 5)))
    for oid in range(1, num_orders + 1):
        cid = random.randint(1, num_customers)
        odate = fake.date_between(start_date="-30d", end_date="today").isoformat()
        order_rows.append((oid, cid, odate, "pending"))

        n_items = random.randint(1, 5)
        picked = random.sample(range(1, num_products + 1), k=min(n_items, num_products))
        for pid in picked:
            qty = random.randint(1, 4)
            oos = 1 if pid in oos_product_set else 0
            item_rows.append((oid, pid, qty, oos))

    orders_df = pd.DataFrame(order_rows, columns=[
        "order_id", "customer_id", "order_date", "status"])
    items_df = pd.DataFrame(item_rows, columns=[
        "order_id", "product_id", "quantity", "is_out_of_stock"])
    return orders_df, items_df


def generate_inventory(product_ids: list, oos_set: set) -> pd.DataFrame:
    """Generate inventory; OOS products get stock = 0."""
    sections = ["A", "B", "C", "D", "E"]
    rows = []
    for pid in product_ids:
        stock = 0 if pid in oos_set else random.randint(5, 500)
        sec = random.choice(sections)
        restocked = fake.date_between(start_date="-14d", end_date="today").isoformat()
        rows.append((pid, stock, sec, restocked))
    return pd.DataFrame(rows, columns=[
        "product_id", "current_stock", "warehouse_section", "last_restocked"])


# ── Workspace file generators ───────────────────────────────────────────────

def write_substitution_policy(ws: str):
    """Fixed policy file — scoring weights and rules."""
    policy = {
        "scoring_weights": {
            "category_match": 25,
            "brand_affinity": 20,
            "nutritional_similarity": 20,
            "price_compatibility": 20,
            "inventory_availability": 15,
        },
        "rules": {
            "same_subcategory_bonus": 10,
            "max_substitutes_per_item": 3,
            "exclude_allergen_conflicts": True,
            "prefer_higher_loyalty_brands": True,
        },
        "nutritional_tolerance_pct": {
            "calories": 25,
            "protein_g": 30,
            "fat_g": 30,
            "carbs_g": 25,
            "fiber_g": 40,
            "sugar_g": 30,
            "sodium_mg": 25,
        },
    }
    with open(os.path.join(ws, "substitution_policy.yaml"), "w") as f:
        # Write as YAML manually (no pyyaml dependency)
        _write_yaml(f, policy)


def _write_yaml(f, obj, indent=0):
    """Minimal YAML writer (no external dependency)."""
    prefix = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict,)):
                f.write(f"{prefix}{k}:\n")
                _write_yaml(f, v, indent + 1)
            elif isinstance(v, (list,)):
                f.write(f"{prefix}{k}:\n")
                for item in v:
                    f.write(f"{prefix}  - {item}\n")
            else:
                if isinstance(v, bool):
                    f.write(f"{prefix}{k}: {'true' if v else 'false'}\n")
                else:
                    f.write(f"{prefix}{k}: {v}\n")
    elif isinstance(obj, list):
        for item in obj:
            f.write(f"{prefix}- {item}\n")


def write_brand_affinity(ws: str, brands_used: list):
    """Fixed file — brand-to-brand affinity matrix (CSV)."""
    n = len(brands_used)
    # Symmetric matrix with self-affinity = 100
    mat = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(n):
            if i == j:
                mat[i][j] = 100
            else:
                # Deterministic from seed
                mat[i][j] = random.randint(10, 90)
    df = pd.DataFrame(mat, index=brands_used, columns=brands_used)
    df.index.name = "brand"
    df.to_csv(os.path.join(ws, "brand_affinity_matrix.csv"))


def write_price_sensitivity_tiers(ws: str):
    """Fixed file — tier definitions."""
    tiers = {
        "budget": {
            "max_price_increase_pct": 5,
            "prefer_lower_price": True,
            "description": "Very price-conscious; substitutes must stay within 5% of original price."
        },
        "standard": {
            "max_price_increase_pct": 15,
            "prefer_lower_price": False,
            "description": "Moderate flexibility; up to 15% price increase acceptable."
        },
        "premium": {
            "max_price_increase_pct": 30,
            "prefer_lower_price": False,
            "description": "Quality-first; up to 30% price increase acceptable for better quality."
        }
    }
    with open(os.path.join(ws, "price_sensitivity_tiers.json"), "w") as f:
        json.dump(tiers, f, indent=2)


def write_category_hierarchy(ws: str):
    """Fixed file — category/subcategory tree with cross-substitution rules."""
    hierarchy = {}
    for cat, subs in CATEGORIES.items():
        hierarchy[cat] = {
            "subcategories": subs,
            "cross_substitution_allowed": True,
            "priority_order": subs,  # preference order within category
        }
    with open(os.path.join(ws, "category_hierarchy.yaml"), "w") as f:
        _write_yaml(f, hierarchy)


def write_product_spec_files(ws: str, products_df: pd.DataFrame, nutritional_df: pd.DataFrame,
                             num_files: int):
    """Scalable files — product specification sheets split across files.

    Each file covers a slice of products and contains dietary tags,
    allergen warnings, quality scores, and sourcing info that are NOT in the DB.
    """
    specs_dir = os.path.join(ws, "product_specs")
    os.makedirs(specs_dir, exist_ok=True)

    pids = list(products_df["product_id"])
    chunk_size = max(1, len(pids) // num_files)
    chunks = [pids[i:i + chunk_size] for i in range(0, len(pids), chunk_size)]
    # Merge small remainder into last chunk if needed
    if len(chunks) > num_files:
        chunks[-2].extend(chunks[-1])
        chunks = chunks[:-1]

    formats = ["json", "csv", "yaml", "txt"]
    for idx, chunk in enumerate(chunks):
        fmt = formats[idx % len(formats)]
        records = []
        for pid in chunk:
            n_tags = random.randint(0, 3)
            tags = random.sample(DIETARY_TAGS, k=n_tags)
            n_allergens = random.randint(0, 2)
            aller = random.sample(ALLERGENS, k=n_allergens)
            quality = round(random.uniform(3.0, 5.0), 2)
            sourcing = random.choice(["domestic", "imported", "local_farm", "mixed"])
            records.append({
                "product_id": int(pid),
                "dietary_tags": tags,
                "allergens": aller,
                "quality_score": quality,
                "sourcing": sourcing,
            })

        fname = f"product_specs_batch_{idx + 1}"
        if fmt == "json":
            with open(os.path.join(specs_dir, f"{fname}.json"), "w") as f:
                json.dump(records, f, indent=2)
        elif fmt == "csv":
            df = pd.DataFrame(records)
            df["dietary_tags"] = df["dietary_tags"].apply(lambda x: "|".join(x))
            df["allergens"] = df["allergens"].apply(lambda x: "|".join(x))
            df.to_csv(os.path.join(specs_dir, f"{fname}.csv"), index=False)
        elif fmt == "yaml":
            with open(os.path.join(specs_dir, f"{fname}.yaml"), "w") as f:
                for rec in records:
                    f.write(f"- product_id: {rec['product_id']}\n")
                    f.write(f"  dietary_tags: [{', '.join(rec['dietary_tags'])}]\n")
                    f.write(f"  allergens: [{', '.join(rec['allergens'])}]\n")
                    f.write(f"  quality_score: {rec['quality_score']}\n")
                    f.write(f"  sourcing: {rec['sourcing']}\n")
        elif fmt == "txt":
            with open(os.path.join(specs_dir, f"{fname}.txt"), "w") as f:
                for rec in records:
                    f.write(f"PRODUCT_ID={rec['product_id']}\n")
                    f.write(f"DIETARY_TAGS={','.join(rec['dietary_tags'])}\n")
                    f.write(f"ALLERGENS={','.join(rec['allergens'])}\n")
                    f.write(f"QUALITY_SCORE={rec['quality_score']}\n")
                    f.write(f"SOURCING={rec['sourcing']}\n")
                    f.write("---\n")


def write_customer_brand_preferences(ws: str, customers_df: pd.DataFrame):
    """Fixed file — customer preferred-brand list (JSON)."""
    prefs = {}
    for _, row in customers_df.iterrows():
        cid = int(row["customer_id"])
        n_brands = random.randint(1, 4)
        prefs[str(cid)] = {
            "preferred_brands": random.sample(BRANDS, k=n_brands),
            "avoid_allergens": random.sample(ALLERGENS, k=random.randint(0, 2)),
        }
    with open(os.path.join(ws, "customer_brand_preferences.json"), "w") as f:
        json.dump(prefs, f, indent=2)


def write_order_notes_files(ws: str, orders_df: pd.DataFrame, num_files: int):
    """Scalable files — order-level special notes from customers.

    Contains substitution preferences that are ONLY available here.
    """
    notes_dir = os.path.join(ws, "order_notes")
    os.makedirs(notes_dir, exist_ok=True)

    oids = list(orders_df["order_id"])
    chunk_size = max(1, len(oids) // num_files)
    chunks = [oids[i:i + chunk_size] for i in range(0, len(oids), chunk_size)]
    if len(chunks) > num_files:
        chunks[-2].extend(chunks[-1])
        chunks = chunks[:-1]

    formats = ["json", "md", "csv", "txt"]
    for idx, chunk in enumerate(chunks):
        fmt = formats[idx % len(formats)]
        records = []
        for oid in chunk:
            allow = random.choice([True, True, True, False])  # 75% allow substitution
            note = ""
            if allow:
                note = random.choice([
                    "Please substitute with same brand if possible.",
                    "Any substitute is fine.",
                    "Prefer organic alternatives.",
                    "Only substitute within same subcategory.",
                    "Substitute with lower-priced option preferred.",
                    "No substitutions for allergen-sensitive items.",
                    "Prefer domestic sourcing for substitutes.",
                    "Accept any substitute, prioritize availability.",
                ])
            records.append({
                "order_id": int(oid),
                "allow_substitution": allow,
                "substitution_note": note,
            })

        fname = f"order_notes_batch_{idx + 1}"
        if fmt == "json":
            with open(os.path.join(notes_dir, f"{fname}.json"), "w") as f:
                json.dump(records, f, indent=2)
        elif fmt == "md":
            with open(os.path.join(notes_dir, f"{fname}.md"), "w") as f:
                for rec in records:
                    f.write(f"## Order {rec['order_id']}\n")
                    f.write(f"- Allow substitution: {'Yes' if rec['allow_substitution'] else 'No'}\n")
                    if rec["substitution_note"]:
                        f.write(f"- Note: {rec['substitution_note']}\n")
                    f.write("\n")
        elif fmt == "csv":
            df = pd.DataFrame(records)
            df.to_csv(os.path.join(notes_dir, f"{fname}.csv"), index=False)
        elif fmt == "txt":
            with open(os.path.join(notes_dir, f"{fname}.txt"), "w") as f:
                for rec in records:
                    f.write(f"ORDER_ID={rec['order_id']}\n")
                    f.write(f"ALLOW_SUBSTITUTION={'yes' if rec['allow_substitution'] else 'no'}\n")
                    f.write(f"NOTE={rec['substitution_note']}\n")
                    f.write("---\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    n_products = SCALE["rows_per_table"]
    n_customers = max(20, SCALE["rows_per_table"] // 4)
    n_orders = SCALE["rows_per_table"]
    n_spec_files = SCALE["num_workspace_files"] // 2  # half for product specs
    n_note_files = SCALE["num_workspace_files"] - n_spec_files  # half for order notes

    # Generate data
    products_df = generate_products(n_products)
    nutritional_df = generate_nutritional(list(products_df["product_id"]))
    customers_df = generate_customers(n_customers)

    # Determine OOS products from order items generation
    oos_set = set(random.sample(range(1, n_products + 1), k=max(5, n_products // 5)))
    orders_df, items_df = generate_orders_and_items(n_orders, n_products, n_customers)
    # Sync OOS flags in items with the oos_set
    items_df["is_out_of_stock"] = items_df["product_id"].apply(lambda x: 1 if x in oos_set else 0)

    inventory_df = generate_inventory(list(products_df["product_id"]), oos_set)

    # Write database
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    products_df.to_sql("products", conn, if_exists="replace", index=False)
    nutritional_df.to_sql("nutritional_profiles", conn, if_exists="replace", index=False)
    customers_df.to_sql("customers", conn, if_exists="replace", index=False)
    orders_df.to_sql("orders", conn, if_exists="replace", index=False)
    items_df.to_sql("order_items", conn, if_exists="replace", index=False)
    inventory_df.to_sql("inventory", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    # Write fixed workspace files
    write_substitution_policy(args.workspace)
    write_brand_affinity(args.workspace, sorted(set(products_df["brand"])))
    write_price_sensitivity_tiers(args.workspace)
    write_category_hierarchy(args.workspace)
    write_customer_brand_preferences(args.workspace, customers_df)

    # Write scalable workspace files
    write_product_spec_files(args.workspace, products_df, nutritional_df, n_spec_files)
    write_order_notes_files(args.workspace, orders_df, n_note_files)


if __name__ == "__main__":
    main()
