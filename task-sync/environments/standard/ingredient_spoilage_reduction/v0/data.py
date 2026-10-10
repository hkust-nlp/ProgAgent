"""
Data generation for ingredient spoilage reduction task.
Generates a SQLite database and workspace files for kitchen inventory management.
"""

import argparse
import os
import sqlite3
import json
import csv
import random
import math
import yaml

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 8,
}

REFERENCE_DATE = pd.Timestamp("2025-01-15")

# ---------------------------------------------------------------------------
# Ingredient pools
# ---------------------------------------------------------------------------
CATEGORY_INGREDIENTS = {
    "produce": [
        "Roma Tomatoes", "Iceberg Lettuce", "Baby Carrots", "Yellow Onions",
        "Red Bell Peppers", "Baby Spinach", "English Cucumbers", "Broccoli Crowns",
        "White Mushrooms", "Zucchini", "Celery Stalks", "Garlic Bulbs",
        "Russet Potatoes", "Sweet Potatoes", "Hass Avocados", "Fresh Lemons",
        "Fresh Limes", "Mixed Herbs", "Curly Kale", "Green Cabbage",
    ],
    "dairy": [
        "Whole Milk", "Heavy Cream", "Unsalted Butter", "Sharp Cheddar",
        "Fresh Mozzarella", "Parmesan Wedge", "Sour Cream", "Greek Yogurt",
        "Cream Cheese", "Gouda Slices",
    ],
    "meat": [
        "Chicken Breast", "Ground Beef 80-20", "Pork Tenderloin", "Smoked Bacon",
        "Lamb Loin Chops", "Turkey Breast", "Italian Sausage", "Veal Cutlets",
        "Duck Breast", "Beef Ribeye",
    ],
    "seafood": [
        "Atlantic Salmon", "Tiger Shrimp", "Ahi Tuna Steak", "Pacific Cod",
        "Sea Scallops", "PEI Mussels", "Maine Lobster Tail", "Jumbo Lump Crab",
        "Whole Squid", "Red Snapper",
    ],
    "bakery": [
        "Sourdough Loaf", "Butter Croissants", "French Baguette", "Dinner Rolls",
        "Flour Tortillas", "Pita Rounds", "Ciabatta Bread", "Brioche Buns",
        "Focaccia Slab", "Rye Bread",
    ],
    "condiments": [
        "Extra Virgin Olive Oil", "Soy Sauce", "Balsamic Vinegar", "Sriracha Sauce",
        "Dijon Mustard", "Ketchup", "Worcestershire Sauce", "Fish Sauce",
        "Toasted Sesame Oil", "Mayonnaise",
    ],
    "frozen": [
        "Frozen Sweet Peas", "Frozen Corn Kernels", "Vanilla Ice Cream Base",
        "Frozen Mixed Berries", "Frozen Puff Pastry", "Frozen Raw Shrimp",
        "Frozen Chopped Spinach", "Frozen French Fries", "Mango Sorbet Mix",
        "Frozen Beef Stock",
    ],
    "dry_goods": [
        "All-Purpose Flour", "Granulated Sugar", "Jasmine Rice", "Penne Pasta",
        "Dried Black Beans", "Cornstarch", "Baking Powder", "Kosher Salt",
        "Ground Black Pepper", "Dried Oregano",
    ],
}

SHELF_LIFE = {
    "produce": (3, 10), "dairy": (5, 21), "meat": (3, 7), "seafood": (2, 5),
    "bakery": (2, 7), "condiments": (60, 180), "frozen": (30, 180), "dry_goods": (90, 365),
}

STORAGE_TEMP = {
    "produce": (1.0, 4.0), "dairy": (1.0, 4.0), "meat": (-2.0, 2.0),
    "seafood": (-2.0, 1.0), "bakery": (15.0, 25.0), "condiments": (15.0, 25.0),
    "frozen": (-25.0, -15.0), "dry_goods": (15.0, 25.0),
}

FRIDGE_ZONES = {
    "FRIDGE-A": {"label": "Main Cooler", "target_temp": 2.5, "categories": ["produce", "dairy"]},
    "FRIDGE-B": {"label": "Meat Locker", "target_temp": 0.0, "categories": ["meat", "seafood"]},
    "FREEZER-C": {"label": "Walk-in Freezer", "target_temp": -20.0, "categories": ["frozen"]},
    "PANTRY-D": {"label": "Dry Pantry", "target_temp": 20.0, "categories": ["bakery", "condiments", "dry_goods"]},
}

CATEGORY_TO_FRIDGE = {}
for fid, info in FRIDGE_ZONES.items():
    for cat in info["categories"]:
        CATEGORY_TO_FRIDGE[cat] = fid

RECIPE_POOL = [
    "Grilled Chicken Caesar Salad", "Classic Beef Burger", "Pan-Seared Salmon",
    "Margherita Pizza", "Shrimp Scampi Linguine", "Mushroom Risotto",
    "Pork Schnitzel", "Fish and Chips", "Thai Green Curry", "Lamb Tagine",
    "Lobster Bisque", "Duck Confit", "Tuna Tartare", "Eggs Benedict",
    "French Onion Soup", "Beef Stroganoff", "Chicken Tikka Masala",
    "Pasta Carbonara", "Vegetable Stir Fry", "Crab Cakes",
    "Spinach and Feta Quiche", "BBQ Pulled Pork Sandwich", "Clam Chowder",
    "Seared Scallops", "Ratatouille", "Veal Piccata", "Tom Yum Soup",
    "Beef Tacos", "Grilled Vegetable Platter", "Tiramisu",
]

SUPPLIERS = [
    "FreshFarm Produce Co.", "Valley Dairy Direct", "PrimeCut Meats",
    "OceanHarvest Seafood", "Golden Grain Bakery", "Pacific Provisions",
    "Alpine Foods Inc.", "Sunrise Organics", "Metro Food Distributors",
    "Heritage Supply Co.",
]

WASTE_REASONS = ["expired", "temperature_damage", "overstock", "quality_decline", "contamination"]


def create_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit TEXT NOT NULL,
            shelf_life_days INTEGER NOT NULL,
            min_storage_temp REAL NOT NULL,
            max_storage_temp REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplier_deliveries (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL,
            supplier_name TEXT NOT NULL,
            delivery_date TEXT NOT NULL,
            batch_code TEXT NOT NULL UNIQUE,
            quantity REAL NOT NULL,
            unit_cost REAL NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        );
        CREATE TABLE IF NOT EXISTS fridge_temp_logs (
            id INTEGER PRIMARY KEY,
            fridge_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            temperature_c REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS waste_logs (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL,
            waste_date TEXT NOT NULL,
            quantity_wasted REAL NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        );
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INTEGER PRIMARY KEY,
            recipe_name TEXT NOT NULL,
            ingredient_id INTEGER NOT NULL,
            quantity_per_serving REAL NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        );
    """)


def generate_ingredients(n_rows):
    ingredients = []
    ing_id = 1
    cats = list(CATEGORY_INGREDIENTS.keys())
    per_cat = max(n_rows // len(cats), 2)

    for cat in cats:
        pool = CATEGORY_INGREDIENTS[cat]
        count = min(per_cat, len(pool))
        for i in range(count):
            if ing_id > n_rows:
                break
            sl, sh = SHELF_LIFE[cat]
            tl, th = STORAGE_TEMP[cat]
            unit_choices = {"produce": ["kg", "bunches"], "dairy": ["liters", "kg"],
                           "meat": ["kg"], "seafood": ["kg"], "bakery": ["units"],
                           "condiments": ["liters", "bottles"], "frozen": ["kg"],
                           "dry_goods": ["kg"]}
            ingredients.append({
                "id": ing_id,
                "name": pool[i],
                "category": cat,
                "unit": random.choice(unit_choices.get(cat, ["kg"])),
                "shelf_life_days": random.randint(sl, sh),
                "min_storage_temp": tl,
                "max_storage_temp": th,
            })
            ing_id += 1
        if ing_id > n_rows:
            break

    # Fill remaining by cycling
    all_pools = [(cat, name) for cat in cats for name in CATEGORY_INGREDIENTS[cat]]
    idx = 0
    while len(ingredients) < n_rows:
        cat, base_name = all_pools[idx % len(all_pools)]
        name = f"{base_name} #{len(ingredients)+1}"
        sl, sh = SHELF_LIFE[cat]
        tl, th = STORAGE_TEMP[cat]
        ingredients.append({
            "id": ing_id,
            "name": name,
            "category": cat,
            "unit": random.choice(["kg", "units", "liters"]),
            "shelf_life_days": random.randint(sl, sh),
            "min_storage_temp": tl,
            "max_storage_temp": th,
        })
        ing_id += 1
        idx += 1

    return ingredients


def generate_deliveries(ingredients, n_rows):
    deliveries = []
    del_id = 1
    ref = REFERENCE_DATE

    # Ensure at least one delivery per perishable ingredient
    perishable_cats = ["produce", "dairy", "meat", "seafood", "bakery"]
    perishable = [i for i in ingredients if i["category"] in perishable_cats]
    others = [i for i in ingredients if i["category"] not in perishable_cats]

    # Assign deliveries to perishable first
    for ing in perishable:
        if del_id > n_rows:
            break
        days_ago = random.randint(1, min(ing["shelf_life_days"] + 3, 30))
        dd = ref - pd.Timedelta(days=days_ago)
        deliveries.append({
            "id": del_id,
            "ingredient_id": ing["id"],
            "supplier_name": random.choice(SUPPLIERS),
            "delivery_date": dd.strftime("%Y-%m-%d"),
            "batch_code": f"BCH-{del_id:05d}",
            "quantity": round(random.uniform(2.0, 30.0), 1),
            "unit_cost": round(random.uniform(1.5, 25.0), 2),
        })
        del_id += 1

    # Fill remaining with random ingredients (can include duplicates = multiple batches)
    all_ings = ingredients
    while len(deliveries) < n_rows:
        ing = random.choice(all_ings)
        days_ago = random.randint(1, 30)
        dd = ref - pd.Timedelta(days=days_ago)
        deliveries.append({
            "id": del_id,
            "ingredient_id": ing["id"],
            "supplier_name": random.choice(SUPPLIERS),
            "delivery_date": dd.strftime("%Y-%m-%d"),
            "batch_code": f"BCH-{del_id:05d}",
            "quantity": round(random.uniform(2.0, 30.0), 1),
            "unit_cost": round(random.uniform(1.5, 25.0), 2),
        })
        del_id += 1

    return deliveries


def generate_temp_logs(n_rows):
    logs = []
    log_id = 1
    ref = REFERENCE_DATE
    fridge_ids = list(FRIDGE_ZONES.keys())

    # Distribute logs across fridges and dates (past 7 days, multiple readings/day)
    days_back = 7
    readings_per_fridge_per_day = max(1, n_rows // (len(fridge_ids) * days_back))

    for fid in fridge_ids:
        target = FRIDGE_ZONES[fid]["target_temp"]
        for d in range(days_back):
            date = ref - pd.Timedelta(days=d)
            for r in range(readings_per_fridge_per_day):
                if log_id > n_rows:
                    break
                hour = random.randint(0, 23)
                minute = random.randint(0, 59)
                ts = date.replace(hour=hour, minute=minute, second=0)

                # Normal temp with occasional spikes
                if random.random() < 0.15:  # 15% chance of spike
                    temp = target + random.uniform(1.5, 4.0)
                else:
                    temp = target + random.gauss(0, 0.5)

                logs.append({
                    "id": log_id,
                    "fridge_id": fid,
                    "recorded_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "temperature_c": round(temp, 1),
                })
                log_id += 1
            if log_id > n_rows:
                break
        if log_id > n_rows:
            break

    # Fill remaining
    while len(logs) < n_rows:
        fid = random.choice(fridge_ids)
        target = FRIDGE_ZONES[fid]["target_temp"]
        d = random.randint(0, days_back - 1)
        date = ref - pd.Timedelta(days=d)
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        ts = date.replace(hour=hour, minute=minute, second=0)
        if random.random() < 0.15:
            temp = target + random.uniform(1.5, 4.0)
        else:
            temp = target + random.gauss(0, 0.5)
        logs.append({
            "id": log_id,
            "fridge_id": fid,
            "recorded_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "temperature_c": round(temp, 1),
        })
        log_id += 1

    return logs


def generate_waste_logs(ingredients, n_rows):
    logs = []
    log_id = 1
    ref = REFERENCE_DATE
    perishable_cats = ["produce", "dairy", "meat", "seafood", "bakery"]
    perishable = [i for i in ingredients if i["category"] in perishable_cats]

    for _ in range(n_rows):
        ing = random.choice(perishable if random.random() < 0.8 else ingredients)
        days_ago = random.randint(1, 30)
        wd = ref - pd.Timedelta(days=days_ago)
        logs.append({
            "id": log_id,
            "ingredient_id": ing["id"],
            "waste_date": wd.strftime("%Y-%m-%d"),
            "quantity_wasted": round(random.uniform(0.1, 5.0), 2),
            "reason": random.choice(WASTE_REASONS),
        })
        log_id += 1

    return logs


def generate_recipe_ingredients(ingredients, n_rows):
    records = []
    rec_id = 1
    n_recipes = min(len(RECIPE_POOL), max(8, n_rows // 5))
    recipes = RECIPE_POOL[:n_recipes]

    for recipe in recipes:
        # Each recipe uses 3-6 ingredients
        n_ings = random.randint(3, min(6, len(ingredients)))
        chosen = random.sample(ingredients, n_ings)
        for ing in chosen:
            if rec_id > n_rows:
                break
            records.append({
                "id": rec_id,
                "recipe_name": recipe,
                "ingredient_id": ing["id"],
                "quantity_per_serving": round(random.uniform(0.02, 0.5), 3),
            })
            rec_id += 1
        if rec_id > n_rows:
            break

    # Fill remaining
    while len(records) < n_rows:
        recipe = random.choice(recipes)
        ing = random.choice(ingredients)
        records.append({
            "id": rec_id,
            "recipe_name": recipe,
            "ingredient_id": ing["id"],
            "quantity_per_serving": round(random.uniform(0.02, 0.5), 3),
        })
        rec_id += 1

    return records


# ---------------------------------------------------------------------------
# Workspace file generators
# ---------------------------------------------------------------------------

def write_spoilage_config(workspace):
    """Fixed config file: scoring parameters and thresholds."""
    config = {
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "scoring": {
            "temp_penalty_coefficient": 1.5,
            "condition_flag_penalty_days": 2,
            "waste_rate_multiplier": 1.5,
        },
        "action_thresholds": {
            "DISCARD": {"max_effective_remaining": 0},
            "USE_IMMEDIATELY": {"max_effective_remaining": 1},
            "USE_SOON": {"max_effective_remaining": 3},
            "MONITOR": {"max_effective_remaining": 999},
        },
        "priority_score_formula": (
            "spoilage_risk_score = (1 / max(effective_remaining_days, 0.1)) "
            "* (1 + historical_waste_rate * waste_rate_multiplier)"
        ),
        "effective_remaining_formula": (
            "effective_remaining_days = shelf_life_days - days_since_delivery "
            "- temp_penalty - condition_penalty"
        ),
        "temp_penalty_formula": (
            "temp_penalty = max(0, avg_fridge_temp_3d - max_storage_temp) "
            "* temp_penalty_coefficient"
        ),
        "historical_waste_rate_formula": (
            "historical_waste_rate = total_wasted_qty_30d / total_delivered_qty_30d "
            "for the same ingredient (0 if no deliveries)"
        ),
    }
    path = os.path.join(workspace, "spoilage_config.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def write_fridge_layout(workspace):
    """Fixed config file: fridge zone information."""
    layout = {}
    for fid, info in FRIDGE_ZONES.items():
        layout[fid] = {
            "label": info["label"],
            "target_temperature_c": info["target_temp"],
            "assigned_categories": info["categories"],
        }
    path = os.path.join(workspace, "fridge_layout.json")
    with open(path, "w") as f:
        json.dump(layout, f, indent=2)


def write_kitchen_rules(workspace):
    """Fixed policy document."""
    content = """# Kitchen Inventory Management Rules

All kitchen staff must follow First-In-First-Out (FIFO) rotation for every ingredient category without exception.

When the recommended action for a batch is DISCARD, the item must be removed from storage immediately and logged in the daily waste sheet before the next service begins.

Batches flagged as USE_IMMEDIATELY must be incorporated into the current day's menu or prep list. The head chef must be notified if any USE_IMMEDIATELY items cannot be used within the shift.

USE_SOON items should be moved to the front of their respective storage zone and highlighted on the prep whiteboard for the next two service periods.

Temperature excursions above the maximum storage threshold for any fridge zone must be reported to the facilities team. Any ingredient stored in an affected zone during the excursion period receives reduced effective shelf life as defined in the spoilage configuration.

Delivery condition flags noted in supplier delivery reports (such as warm arrival, damaged packaging, or delayed transit) result in a fixed penalty applied to the effective remaining shelf life of the affected batch, per the spoilage configuration parameters.

The priority score is computed per batch, not per ingredient. If multiple batches of the same ingredient are in stock, each batch is scored and ranked independently.

The historical waste rate for an ingredient is calculated over a rolling 30-day window using all waste log entries and all delivery quantities for that ingredient within the window.
"""
    path = os.path.join(workspace, "kitchen_rules.md")
    with open(path, "w") as f:
        f.write(content)


def write_menu_plans(workspace, recipe_ingredients_records, ingredients, n_files):
    """Scaled: upcoming menu plans as CSV files."""
    recipes_used = list(set(r["recipe_name"] for r in recipe_ingredients_records))
    ref = REFERENCE_DATE

    for fi in range(n_files):
        plan_date = ref + pd.Timedelta(days=fi + 1)
        date_str = plan_date.strftime("%Y-%m-%d")
        n_items = random.randint(4, min(8, len(recipes_used)))
        chosen = random.sample(recipes_used, n_items)
        rows = []
        for recipe in chosen:
            servings = random.randint(10, 60)
            meal_period = random.choice(["lunch", "dinner", "brunch"])
            rows.append({
                "date": date_str,
                "recipe_name": recipe,
                "planned_servings": servings,
                "meal_period": meal_period,
            })
        path = os.path.join(workspace, f"menu_plan_day{fi+1}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "recipe_name", "planned_servings", "meal_period"])
            writer.writeheader()
            writer.writerows(rows)


def write_delivery_notes(workspace, deliveries, n_files):
    """Scaled: supplier delivery observation notes as TXT files."""
    # Select some batches to flag with condition issues
    flagged_batches = set()
    batches_per_file = max(2, len(deliveries) // (n_files * 3))

    for fi in range(n_files):
        start = fi * batches_per_file
        end = min(start + batches_per_file, len(deliveries))
        subset = deliveries[start:end]
        lines = []
        lines.append(f"Delivery Inspection Report - Page {fi+1}")
        lines.append(f"Inspector: Kitchen Receiving Staff")
        lines.append(f"=" * 50)
        lines.append("")

        for d in subset:
            flag = random.random() < 0.25  # 25% chance of condition flag
            lines.append(f"Batch: {d['batch_code']}")
            lines.append(f"  Supplier: {d['supplier_name']}")
            lines.append(f"  Date: {d['delivery_date']}")
            lines.append(f"  Quantity: {d['quantity']}")
            if flag:
                issue = random.choice([
                    "CONDITION FLAG: Arrived above recommended temperature range.",
                    "CONDITION FLAG: Packaging showed signs of damage during transit.",
                    "CONDITION FLAG: Delivery delayed by 3+ hours, cold chain uncertain.",
                ])
                lines.append(f"  {issue}")
                flagged_batches.add(d["batch_code"])
            else:
                lines.append(f"  Status: Received in good condition.")
            lines.append("")

        path = os.path.join(workspace, f"delivery_notes_{fi+1}.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines))

    return flagged_batches


def write_current_stock(workspace, deliveries, ingredients, flagged_batches, n_files):
    """Scaled: current inventory snapshot JSON files."""
    ing_map = {i["id"]: i for i in ingredients}

    # Determine which deliveries are still in stock (recent enough, perishable first)
    perishable_cats = ["produce", "dairy", "meat", "seafood", "bakery"]
    in_stock = []

    for d in deliveries:
        ing = ing_map[d["ingredient_id"]]
        days_since = (REFERENCE_DATE - pd.Timestamp(d["delivery_date"])).days
        # Keep in stock if within shelf life + small buffer, or non-perishable
        if ing["category"] in perishable_cats:
            if days_since <= ing["shelf_life_days"] + 2:
                remaining_qty = round(d["quantity"] * random.uniform(0.2, 0.9), 1)
                fridge = CATEGORY_TO_FRIDGE.get(ing["category"], "PANTRY-D")
                in_stock.append({
                    "ingredient_id": d["ingredient_id"],
                    "batch_code": d["batch_code"],
                    "fridge_id": fridge,
                    "quantity_on_hand": remaining_qty,
                    "unit": ing["unit"],
                })
        else:
            if random.random() < 0.4:  # Not all non-perishables are in stock files
                remaining_qty = round(d["quantity"] * random.uniform(0.3, 0.95), 1)
                fridge = CATEGORY_TO_FRIDGE.get(ing["category"], "PANTRY-D")
                in_stock.append({
                    "ingredient_id": d["ingredient_id"],
                    "batch_code": d["batch_code"],
                    "fridge_id": fridge,
                    "quantity_on_hand": remaining_qty,
                    "unit": ing["unit"],
                })

    # Split across files
    random.shuffle(in_stock)
    per_file = max(1, len(in_stock) // n_files)
    for fi in range(n_files):
        start = fi * per_file
        if fi == n_files - 1:
            chunk = in_stock[start:]
        else:
            chunk = in_stock[start:start + per_file]
        path = os.path.join(workspace, f"current_stock_{fi+1}.json")
        with open(path, "w") as f:
            json.dump(chunk, f, indent=2)


def write_waste_reports(workspace, waste_logs, ingredients, n_files):
    """Scaled: weekly waste analysis markdown reports."""
    ing_map = {i["id"]: i for i in ingredients}
    ref = REFERENCE_DATE

    logs_per_file = max(1, len(waste_logs) // n_files)
    for fi in range(n_files):
        start = fi * logs_per_file
        if fi == n_files - 1:
            chunk = waste_logs[start:]
        else:
            chunk = waste_logs[start:start + logs_per_file]

        # Aggregate by reason
        reason_totals = {}
        for w in chunk:
            r = w["reason"]
            reason_totals[r] = reason_totals.get(r, 0) + w["quantity_wasted"]

        week_start = ref - pd.Timedelta(days=30 - fi * 7)
        week_end = week_start + pd.Timedelta(days=6)

        lines = [
            f"# Waste Analysis Report - Period {fi+1}",
            f"Coverage: {week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}",
            "",
            "## Waste by Reason",
            "",
        ]
        for reason, total in sorted(reason_totals.items(), key=lambda x: -x[1]):
            lines.append(f"- {reason}: {total:.2f} units")
        lines.append("")
        lines.append("## Detailed Entries")
        lines.append("")
        lines.append("| Ingredient | Date | Qty Wasted | Reason |")
        lines.append("|---|---|---|---|")
        for w in chunk:
            iname = ing_map.get(w["ingredient_id"], {}).get("name", f"ID-{w['ingredient_id']}")
            lines.append(f"| {iname} | {w['waste_date']} | {w['quantity_wasted']:.2f} | {w['reason']} |")
        lines.append("")

        path = os.path.join(workspace, f"waste_report_{fi+1}.md")
        with open(path, "w") as f:
            f.write("\n".join(lines))


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    fake.seed_instance(42)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Distribute scaled files across types
    n_menu = max(2, n_files // 3)
    n_notes = max(2, n_files // 4)
    n_stock = max(2, n_files // 4)
    n_waste_reports = max(1, n_files - n_menu - n_notes - n_stock)

    # Generate data
    ingredients = generate_ingredients(n_rows)
    deliveries = generate_deliveries(ingredients, n_rows)
    temp_logs = generate_temp_logs(n_rows)
    waste_logs_data = generate_waste_logs(ingredients, n_rows)
    recipe_ings = generate_recipe_ingredients(ingredients, n_rows)

    # Create database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    create_tables(cursor)

    for ing in ingredients:
        cursor.execute(
            "INSERT INTO ingredients VALUES (?,?,?,?,?,?,?)",
            (ing["id"], ing["name"], ing["category"], ing["unit"],
             ing["shelf_life_days"], ing["min_storage_temp"], ing["max_storage_temp"])
        )

    for d in deliveries:
        cursor.execute(
            "INSERT INTO supplier_deliveries VALUES (?,?,?,?,?,?,?)",
            (d["id"], d["ingredient_id"], d["supplier_name"],
             d["delivery_date"], d["batch_code"], d["quantity"], d["unit_cost"])
        )

    for t in temp_logs:
        cursor.execute(
            "INSERT INTO fridge_temp_logs VALUES (?,?,?,?)",
            (t["id"], t["fridge_id"], t["recorded_at"], t["temperature_c"])
        )

    for w in waste_logs_data:
        cursor.execute(
            "INSERT INTO waste_logs VALUES (?,?,?,?,?)",
            (w["id"], w["ingredient_id"], w["waste_date"],
             w["quantity_wasted"], w["reason"])
        )

    for r in recipe_ings:
        cursor.execute(
            "INSERT INTO recipe_ingredients VALUES (?,?,?,?)",
            (r["id"], r["recipe_name"], r["ingredient_id"],
             r["quantity_per_serving"])
        )

    conn.commit()
    conn.close()

    # Write fixed workspace files
    write_spoilage_config(workspace)
    write_fridge_layout(workspace)
    write_kitchen_rules(workspace)

    # Write scaled workspace files
    write_menu_plans(workspace, recipe_ings, ingredients, n_menu)
    flagged = write_delivery_notes(workspace, deliveries, n_notes)
    write_current_stock(workspace, deliveries, ingredients, flagged, n_stock)
    write_waste_reports(workspace, waste_logs_data, ingredients, n_waste_reports)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
