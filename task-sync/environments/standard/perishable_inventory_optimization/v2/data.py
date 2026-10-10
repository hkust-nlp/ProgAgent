"""
Data generation for Perishable Ingredient Ordering Optimization task.
Generates a SQLite database and workspace files for multi-store inventory management.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 120,       # v2 = 4× base
    "num_workspace_files": 24,   # v2 = base + 2N (8 + 16)
}

# ── Seeds ────────────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Ingredient generation helpers ────────────────────────────────────────────
CATEGORIES = ["dairy", "produce", "meat", "seafood", "bakery", "deli"]

BASE_INGREDIENTS = {
    "dairy": [
        "whole milk", "skim milk", "heavy cream", "sour cream", "plain yogurt",
        "greek yogurt", "cheddar cheese", "mozzarella cheese", "parmesan cheese",
        "cream cheese", "cottage cheese", "buttermilk", "whipping cream",
        "gouda cheese", "brie cheese", "ricotta cheese", "feta cheese",
        "half and half", "almond milk", "oat milk", "coconut yogurt",
        "provolone cheese", "swiss cheese", "blue cheese", "mascarpone",
        "clotted cream", "kefir", "eggnog", "chocolate milk", "condensed milk",
        "evaporated milk", "goat cheese", "pepper jack cheese", "colby cheese",
        "muenster cheese", "havarti cheese", "gruyere cheese", "camembert cheese",
        "stilton cheese", "manchego cheese",
    ],
    "produce": [
        "romaine lettuce", "iceberg lettuce", "baby spinach", "kale", "arugula",
        "tomatoes", "cherry tomatoes", "red onions", "yellow onions", "bell peppers",
        "jalapenos", "cucumbers", "carrots", "celery", "broccoli",
        "cauliflower", "zucchini", "mushrooms", "avocados", "lemons",
        "limes", "fresh basil", "fresh cilantro", "fresh parsley", "green onions",
        "radishes", "beets", "sweet potatoes", "asparagus", "green beans",
        "snap peas", "corn on cob", "eggplant", "artichokes", "fennel",
        "turnips", "rutabaga", "bok choy", "watercress", "endive",
    ],
    "meat": [
        "chicken breast", "chicken thighs", "ground beef", "beef sirloin", "pork chops",
        "pork tenderloin", "bacon strips", "italian sausage", "ground turkey", "turkey breast",
        "lamb chops", "veal cutlets", "beef ribeye", "flank steak", "pork ribs",
        "chicken wings", "duck breast", "ground pork", "beef brisket", "ham slices",
        "salami", "prosciutto", "chorizo", "bratwurst", "beef short ribs",
        "pork belly", "rack of lamb", "cornish hen", "quail", "venison steak",
        "bison burger", "elk steak", "rabbit loin", "oxtail", "beef tongue",
        "pork shoulder", "chicken drumsticks", "turkey legs", "ground lamb", "beef tenderloin",
    ],
    "seafood": [
        "atlantic salmon", "tuna steaks", "jumbo shrimp", "sea scallops", "cod fillets",
        "tilapia fillets", "mahi mahi", "swordfish steaks", "crab meat", "lobster tails",
        "mussels", "clams", "oysters", "calamari", "octopus",
        "halibut fillets", "red snapper", "grouper fillets", "catfish fillets", "sardines",
        "anchovies", "trout fillets", "arctic char", "barramundi", "branzino",
        "dover sole", "monkfish", "wahoo", "yellowtail", "sea bass",
        "crawfish", "langoustines", "king crab legs", "snow crab", "soft shell crab",
        "smoked salmon", "eel", "mackerel", "herring", "perch fillets",
    ],
    "bakery": [
        "sourdough bread", "baguettes", "ciabatta rolls", "croissants", "brioche buns",
        "whole wheat bread", "rye bread", "dinner rolls", "pita bread", "naan bread",
        "focaccia", "bagels", "english muffins", "tortillas", "corn bread",
        "danish pastries", "cinnamon rolls", "muffins", "scones", "challah bread",
        "pumpernickel bread", "multigrain bread", "pretzel rolls", "kaiser rolls", "hamburger buns",
        "hot dog buns", "french bread", "olive bread", "rosemary bread", "potato bread",
        "flatbread", "lavash", "chapati", "injera", "crumpets",
        "pain au chocolat", "sticky buns", "monkey bread", "parker house rolls", "biscuits",
    ],
    "deli": [
        "roast turkey breast", "honey ham", "roast beef", "pastrami", "corned beef",
        "pepperoni", "mortadella", "capicola", "smoked turkey", "black forest ham",
        "chicken salad", "tuna salad", "egg salad", "potato salad", "coleslaw",
        "hummus", "guacamole", "pimento cheese", "olive tapenade", "bruschetta mix",
        "fresh pasta", "ravioli", "tortellini", "gnocchi", "pierogies",
        "quiche lorraine", "spinach quiche", "meat pie", "empanadas", "spring rolls",
        "sushi rolls", "poke bowl mix", "ceviche", "carpaccio", "beef tartare",
        "liverwurst", "head cheese", "pate", "rillettes", "terrine",
    ],
}

SHELF_LIFE = {
    "dairy": (3, 14),
    "produce": (2, 10),
    "meat": (2, 7),
    "seafood": (1, 5),
    "bakery": (1, 5),
    "deli": (2, 7),
}

STORAGE_TEMP = {
    "dairy": (1, 4),
    "produce": (2, 7),
    "meat": (-2, 2),
    "seafood": (-2, 1),
    "bakery": (15, 22),
    "deli": (0, 4),
}

UNITS = {
    "dairy": "liters",
    "produce": "kg",
    "meat": "kg",
    "seafood": "kg",
    "bakery": "units",
    "deli": "kg",
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

STORE_TYPES = ["urban", "suburban", "rural", "express", "warehouse"]

US_STATES = [
    ("New York", "NY"), ("California", "CA"), ("Texas", "TX"), ("Florida", "FL"),
    ("Illinois", "IL"), ("Pennsylvania", "PA"), ("Ohio", "OH"), ("Georgia", "GA"),
    ("North Carolina", "NC"), ("Michigan", "MI"), ("New Jersey", "NJ"),
    ("Virginia", "VA"), ("Washington", "WA"), ("Arizona", "AZ"), ("Massachusetts", "MA"),
    ("Tennessee", "TN"), ("Indiana", "IN"), ("Missouri", "MO"), ("Maryland", "MD"),
    ("Wisconsin", "WI"), ("Colorado", "CO"), ("Minnesota", "MN"), ("South Carolina", "SC"),
    ("Alabama", "AL"), ("Louisiana", "LA"), ("Kentucky", "KY"), ("Oregon", "OR"),
    ("Oklahoma", "OK"), ("Connecticut", "CT"), ("Utah", "UT"),
]


def generate_ingredients(n):
    """Generate n unique ingredient records across categories."""
    ingredients = []
    per_cat = max(n // len(CATEGORIES), 1)
    remainder = n - per_cat * len(CATEGORIES)
    counts = {cat: per_cat for cat in CATEGORIES}
    for i, cat in enumerate(CATEGORIES):
        if i < remainder:
            counts[cat] += 1

    ing_id = 1
    for cat in CATEGORIES:
        available = list(BASE_INGREDIENTS[cat])
        random.shuffle(available)
        for j in range(counts[cat]):
            name = available[j % len(available)]
            if j >= len(available):
                name = f"{name} #{j // len(available) + 1}"
            sl_min, sl_max = SHELF_LIFE[cat]
            shelf_life = random.randint(sl_min, sl_max)
            st_min, st_max = STORAGE_TEMP[cat]
            storage_temp = round(random.uniform(st_min, st_max), 1)
            base_price = round(random.uniform(1.5, 25.0), 2)
            ingredients.append({
                "ingredient_id": ing_id,
                "name": name,
                "category": cat,
                "unit": UNITS[cat],
                "base_price": base_price,
                "shelf_life_days": shelf_life,
                "storage_temp_c": storage_temp,
            })
            ing_id += 1
    return ingredients


def generate_stores(n):
    """Generate n unique store records."""
    stores = []
    cities_used = set()
    for i in range(1, n + 1):
        city = fake.city()
        while city in cities_used:
            city = fake.city()
        cities_used.add(city)
        state_name, state_code = random.choice(US_STATES)
        store_type = random.choice(STORE_TYPES)
        stores.append({
            "store_id": i,
            "name": f"FreshMart #{i:04d}",
            "city": city,
            "state": state_code,
            "store_type": store_type,
            "daily_capacity_kg": round(random.uniform(500, 3000), 0),
        })
    return stores


def generate_suppliers(n):
    """Generate n unique supplier records."""
    suppliers = []
    regions = ["Northeast", "Southeast", "Midwest", "Southwest", "West", "Northwest"]
    for i in range(1, n + 1):
        suppliers.append({
            "supplier_id": i,
            "name": fake.company(),
            "contact_email": fake.company_email(),
            "region": random.choice(regions),
            "lead_time_days": random.randint(1, 5),
            "min_order_value": round(random.choice([50, 100, 150, 200, 250, 300]), 2),
        })
    return suppliers


def build_database(db_path, stores, ingredients, suppliers):
    """Create SQLite database with all tables and data."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ── Create tables ────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            store_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            ingredient_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit TEXT NOT NULL,
            base_price REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            sale_date TEXT NOT NULL,
            qty_sold REAL NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            inv_id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            current_qty REAL NOT NULL,
            last_restock_date TEXT NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            contact_email TEXT NOT NULL,
            region TEXT NOT NULL,
            lead_time_days INTEGER NOT NULL,
            min_order_value REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS supplier_catalog (
            catalog_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            unit_cost REAL NOT NULL,
            pack_size REAL NOT NULL,
            is_available INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS waste_logs (
            waste_id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            qty_wasted REAL NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    # ── Insert stores ────────────────────────────────────────────────────
    for s in stores:
        c.execute(
            "INSERT INTO stores (store_id, name, city, state) VALUES (?, ?, ?, ?)",
            (s["store_id"], s["name"], s["city"], s["state"]),
        )

    # ── Insert ingredients (DB gets basic fields only) ───────────────────
    for ing in ingredients:
        c.execute(
            "INSERT INTO ingredients (ingredient_id, name, category, unit, base_price) VALUES (?, ?, ?, ?, ?)",
            (ing["ingredient_id"], ing["name"], ing["category"], ing["unit"], ing["base_price"]),
        )

    # ── Insert suppliers ─────────────────────────────────────────────────
    for sup in suppliers:
        c.execute(
            "INSERT INTO suppliers VALUES (?, ?, ?, ?, ?, ?)",
            (sup["supplier_id"], sup["name"], sup["contact_email"],
             sup["region"], sup["lead_time_days"], sup["min_order_value"]),
        )

    # ── Generate supplier catalog ────────────────────────────────────────
    # Each supplier carries 40-60% of ingredients
    ingredient_ids = [ing["ingredient_id"] for ing in ingredients]
    for sup in suppliers:
        n_carry = random.randint(
            max(1, int(len(ingredient_ids) * 0.4)),
            max(2, int(len(ingredient_ids) * 0.6)),
        )
        carried = random.sample(ingredient_ids, min(n_carry, len(ingredient_ids)))
        for iid in carried:
            base = next(ing["base_price"] for ing in ingredients if ing["ingredient_id"] == iid)
            # Supplier cost is 60-90% of base price
            unit_cost = round(base * random.uniform(0.6, 0.9), 2)
            pack_size = random.choice([1, 2, 5, 10, 12, 20, 24, 25])
            is_avail = 1 if random.random() > 0.05 else 0  # 5% unavailable
            c.execute(
                "INSERT INTO supplier_catalog (supplier_id, ingredient_id, unit_cost, pack_size, is_available) VALUES (?, ?, ?, ?, ?)",
                (sup["supplier_id"], iid, unit_cost, pack_size, is_avail),
            )

    # ── Generate daily sales ─────────────────────────────────────────────
    # 14 days of sales history
    end_date = datetime(2025, 6, 15)
    dates = [(end_date - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(14)]
    dates.reverse()

    # Each store sells 60-80% of ingredients on any given day
    store_ids = [s["store_id"] for s in stores]
    for sid in store_ids:
        # Determine which ingredients this store regularly carries (~70%)
        n_carried = max(5, int(len(ingredient_ids) * random.uniform(0.6, 0.8)))
        store_ingredients = sorted(random.sample(ingredient_ids, min(n_carried, len(ingredient_ids))))
        for date_str in dates:
            # On each day, 70-90% of carried ingredients have sales
            daily_sold = random.sample(
                store_ingredients,
                max(1, int(len(store_ingredients) * random.uniform(0.7, 0.9))),
            )
            for iid in daily_sold:
                qty = round(random.uniform(0.5, 50.0), 1)
                c.execute(
                    "INSERT INTO daily_sales (store_id, ingredient_id, sale_date, qty_sold) VALUES (?, ?, ?, ?)",
                    (sid, iid, date_str, qty),
                )

    # ── Generate inventory ───────────────────────────────────────────────
    # Current inventory for each store-ingredient pair that the store carries
    for sid in store_ids:
        c.execute("SELECT DISTINCT ingredient_id FROM daily_sales WHERE store_id = ?", (sid,))
        sold_ings = [row[0] for row in c.fetchall()]
        for iid in sold_ings:
            # Current qty: 0-40 units (some deliberately low to create urgency)
            current_qty = round(random.uniform(0, 40.0), 1)
            # Last restock 1-7 days ago
            restock_date = (end_date - timedelta(days=random.randint(1, 7))).strftime("%Y-%m-%d")
            c.execute(
                "INSERT INTO inventory (store_id, ingredient_id, current_qty, last_restock_date) VALUES (?, ?, ?, ?)",
                (sid, iid, current_qty, restock_date),
            )

    # ── Generate waste logs ──────────────────────────────────────────────
    # 4 weeks of waste data
    week_starts = [
        (end_date - timedelta(weeks=w, days=end_date.weekday())).strftime("%Y-%m-%d")
        for w in range(1, 5)
    ]
    for sid in store_ids:
        c.execute("SELECT DISTINCT ingredient_id FROM daily_sales WHERE store_id = ?", (sid,))
        sold_ings = [row[0] for row in c.fetchall()]
        for ws in week_starts:
            # 30-50% of ingredients have waste each week
            wasted = random.sample(
                sold_ings, max(1, int(len(sold_ings) * random.uniform(0.3, 0.5)))
            )
            for iid in wasted:
                qty_wasted = round(random.uniform(0.1, 15.0), 1)
                c.execute(
                    "INSERT INTO waste_logs (store_id, ingredient_id, week_start, qty_wasted) VALUES (?, ?, ?, ?)",
                    (sid, iid, ws, qty_wasted),
                )

    conn.commit()
    conn.close()


def build_workspace(workspace, stores, ingredients, suppliers):
    """Generate workspace files."""
    os.makedirs(workspace, exist_ok=True)

    n_stores = len(stores)
    n_ingredients = len(ingredients)
    n_scalable = SCALE["num_workspace_files"]

    # Split scalable files: half store configs, half ingredient specs
    n_store_files = n_scalable // 2
    n_ingredient_files = n_scalable - n_store_files

    # ── Scalable: store config files (JSON) ──────────────────────────────
    stores_per_file = max(1, (n_stores + n_store_files - 1) // n_store_files)
    for fidx in range(n_store_files):
        start = fidx * stores_per_file
        end = min(start + stores_per_file, n_stores)
        if start >= n_stores:
            break
        chunk = stores[start:end]
        configs = []
        for s in chunk:
            # Assign 2-3 delivery days per store
            n_delivery_days = random.randint(2, 3)
            delivery_days = sorted(
                random.sample(WEEKDAYS, n_delivery_days),
                key=lambda d: WEEKDAYS.index(d),
            )
            configs.append({
                "store_id": s["store_id"],
                "store_type": s["store_type"],
                "daily_capacity_kg": s["daily_capacity_kg"],
                "delivery_days": delivery_days,
            })
        filepath = os.path.join(workspace, f"store_config_zone_{fidx + 1}.json")
        with open(filepath, "w") as f:
            json.dump(configs, f, indent=2)

    # ── Scalable: ingredient spec files (CSV) ────────────────────────────
    ings_per_file = max(1, (n_ingredients + n_ingredient_files - 1) // n_ingredient_files)
    for fidx in range(n_ingredient_files):
        start = fidx * ings_per_file
        end = min(start + ings_per_file, n_ingredients)
        if start >= n_ingredients:
            break
        chunk = ingredients[start:end]
        rows = []
        for ing in chunk:
            waste_threshold = round(random.uniform(0.05, 0.30), 2)
            reorder_multiplier = round(random.uniform(0.7, 1.3), 2)
            rows.append({
                "ingredient_id": ing["ingredient_id"],
                "ingredient_name": ing["name"],
                "category": ing["category"],
                "shelf_life_days": ing["shelf_life_days"],
                "storage_temp_c": ing["storage_temp_c"],
                "waste_threshold_pct": waste_threshold,
                "reorder_multiplier": reorder_multiplier,
            })
        df = pd.DataFrame(rows)
        filepath = os.path.join(workspace, f"ingredient_specs_batch_{fidx + 1}.csv")
        df.to_csv(filepath, index=False)

    # ── Fixed: ordering_policy.yaml ──────────────────────────────────────
    policy = {
        "safety_stock_days": 2,
        "waste_reduction_factor": 0.25,
        "order_window_default_days": 7,
        "min_order_value_usd": 50.0,
        "priority_thresholds": {
            "critical": 1.0,
            "high": 2.0,
            "medium": 4.0,
        },
        "rounding_rule": "round_up_to_pack_size",
    }
    with open(os.path.join(workspace, "ordering_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # ── Fixed: supplier_ratings.csv ──────────────────────────────────────
    ratings_rows = []
    for sup in suppliers:
        ratings_rows.append({
            "supplier_id": sup["supplier_id"],
            "supplier_name": sup["name"],
            "reliability_score": round(random.uniform(0.60, 0.99), 2),
            "quality_rating": round(random.uniform(3.0, 5.0), 1),
        })
    pd.DataFrame(ratings_rows).to_csv(
        os.path.join(workspace, "supplier_ratings.csv"), index=False
    )

    # ── Fixed: category_handling_rules.txt ────────────────────────────────
    rules_text = """Category Handling Rules for Perishable Inventory
================================================

Each ingredient category has specific handling requirements that affect
ordering decisions. These rules apply across all store locations.

DAIRY: Items must be stored between 1-4 degrees Celsius. Orders arriving
above temperature threshold must be rejected. Dairy items approaching
50% of shelf life remaining should be marked for priority sale.

PRODUCE: Fresh produce requires humidity-controlled storage between 2-7
degrees Celsius. Leafy greens have the shortest viable window. Orders
should account for 10% transit loss on produce items.

MEAT: Cold chain must be maintained at -2 to 2 degrees Celsius. Meat
items cannot be refrozen once thawed. Ground products expire faster
than whole cuts. Orders must respect pack size strictly.

SEAFOOD: Most critical category with storage at -2 to 1 degrees Celsius.
Seafood items with shelf life under 3 days should only be ordered for
confirmed demand. Never order more than 3 days supply of fresh seafood.

BAKERY: Ambient storage at 15-22 degrees Celsius. Bakery items have the
fastest turnover. Day-old items should be discounted, not reordered.
Baked goods cannot carry safety stock beyond 1 day.

DELI: Prepared items stored at 0-4 degrees Celsius. Deli items have
moderate shelf life. Cross-contamination rules apply to slicing
equipment. Batch sizes affect minimum order quantities.
"""
    with open(os.path.join(workspace, "category_handling_rules.txt"), "w") as f:
        f.write(rules_text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]

    # Generate entities
    stores = generate_stores(n_rows)
    ingredients = generate_ingredients(n_rows)
    suppliers = generate_suppliers(n_rows)

    # Build database
    build_database(args.db_path, stores, ingredients, suppliers)

    # Build workspace
    build_workspace(args.workspace, stores, ingredients, suppliers)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Stores: {len(stores)}")
    print(f"  Ingredients: {len(ingredients)}")
    print(f"  Suppliers: {len(suppliers)}")
    print(f"  Workspace files: {len(os.listdir(args.workspace))}")


if __name__ == "__main__":
    main()
