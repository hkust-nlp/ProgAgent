"""
Menu Item Performance Audit - Data Generation Script
Generates database and workspace files for identifying underperforming menu items.
"""

import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 60,       # v0 base; v1 = 2×, v2 = 4×, v3 = 8×
    "num_workspace_files": 10,  # v0 base; v1 = +N, v2 = +2N, v3 = +3N (N = base)
}

# Seed everything
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

CATEGORIES = [
    "Appetizers", "Main Courses", "Pasta & Risotto",
    "Seafood", "Desserts", "Beverages", "Sides", "Salads"
]

INGREDIENT_POOL = [
    "chicken breast", "salmon fillet", "shrimp", "beef tenderloin", "pork loin",
    "pasta", "rice", "flour", "butter", "olive oil", "cream", "milk", "eggs",
    "tomatoes", "onions", "garlic", "bell peppers", "mushrooms", "spinach",
    "potatoes", "carrots", "broccoli", "zucchini", "avocado", "lemon",
    "parmesan cheese", "mozzarella", "cheddar cheese", "goat cheese",
    "basil", "thyme", "rosemary", "cilantro", "oregano",
    "sugar", "chocolate", "vanilla extract", "honey", "maple syrup",
    "bread", "tortilla", "balsamic vinegar", "soy sauce", "wine",
    "coconut milk", "pine nuts", "walnuts", "almonds", "sesame seeds"
]


def create_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            item_id INTEGER PRIMARY KEY,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            menu_price REAL NOT NULL,
            is_seasonal INTEGER DEFAULT 0,
            date_added TEXT NOT NULL,
            portion_size_oz REAL NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_mix (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            period TEXT NOT NULL,
            units_sold INTEGER NOT NULL,
            total_revenue REAL NOT NULL,
            discount_applied REAL DEFAULT 0,
            FOREIGN KEY (item_id) REFERENCES menu_items(item_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS item_ingredients (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            ingredient_name TEXT NOT NULL,
            quantity_per_serving REAL NOT NULL,
            unit TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES menu_items(item_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prep_time_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            date_logged TEXT NOT NULL,
            prep_minutes REAL NOT NULL,
            cook_minutes REAL NOT NULL,
            station TEXT NOT NULL,
            chef_id TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES menu_items(item_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_ratings (
            rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            rating_score REAL NOT NULL,
            review_text TEXT,
            date_reviewed TEXT NOT NULL,
            source TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES menu_items(item_id)
        )
    """)

    conn.commit()
    return conn


def generate_menu_items(conn, num_items):
    """Generate menu items spread across categories."""
    items = []
    item_names_used = set()

    all_names = {
        "Appetizers": ["Bruschetta", "Calamari", "Spring Rolls", "Stuffed Mushrooms",
                       "Soup du Jour", "Crab Cakes", "Hummus Platter", "Caprese Salad",
                       "Chicken Wings", "Shrimp Cocktail", "Cheese Board", "Edamame",
                       "Nachos Supreme", "Tuna Tartare", "Beef Carpaccio",
                       "Deviled Eggs", "Fried Pickles", "Garlic Bread", "Antipasto Platter",
                       "Spinach Dip", "Potato Skins", "Stuffed Peppers", "Prosciutto Wrap",
                       "Mini Quiche", "Ceviche Cup", "Bao Buns", "Tempura Veggies",
                       "Pita Chips Duo", "Smoked Salmon Bites", "Corn Fritters",
                       "Avocado Toast Bites", "Lobster Bisque Shot", "Goat Cheese Crostini",
                       "Coconut Shrimp Bites", "Duck Spring Rolls", "Wagyu Sliders",
                       "Tostada Trio", "Artichoke Dip", "Fried Calamari Rings", "Satay Skewers"],
        "Main Courses": ["Grilled Ribeye", "Herb Roasted Chicken", "Pan-Seared Salmon",
                         "Braised Short Ribs", "Duck Confit", "Lamb Chops", "Pork Belly",
                         "Filet Mignon", "Chicken Marsala", "Beef Bourguignon",
                         "Veal Piccata", "Roasted Halibut", "Stuffed Pork Loin",
                         "Coq au Vin", "Blackened Catfish", "Chicken Parmesan",
                         "Beef Wellington", "Osso Buco", "Rack of Lamb", "BBQ Brisket",
                         "Thai Basil Chicken", "Mongolian Beef", "Chicken Tikka Masala",
                         "Surf and Turf", "Prime Rib", "Cornish Game Hen", "Meatloaf Deluxe",
                         "Stuffed Chicken Breast", "Korean BBQ Plate", "Tandoori Platter",
                         "Slow Roasted Duck", "Venison Steak", "Wild Boar Ragu",
                         "Butter Chicken", "Jerk Chicken", "Lamb Shank", "Porchetta",
                         "Chicken Schnitzel", "Steak Frites", "Miso Salmon"],
        "Pasta & Risotto": ["Spaghetti Carbonara", "Fettuccine Alfredo", "Penne Arrabbiata",
                            "Mushroom Risotto", "Lobster Ravioli", "Truffle Mac & Cheese",
                            "Gnocchi Pesto", "Linguine Vongole", "Lasagna Bolognese",
                            "Cacio e Pepe", "Orecchiette Sausage", "Shrimp Scampi Pasta",
                            "Pappardelle Ragu", "Butternut Squash Risotto", "Baked Ziti",
                            "Rigatoni Vodka", "Tortellini Brodo", "Pesto Primavera",
                            "Seafood Linguine", "Wild Mushroom Pappardelle", "Carbonara Truffle",
                            "Crab Ravioli", "Spinach Ricotta Cannelloni", "Arrabiata Rigatoni",
                            "Saffron Risotto", "Pumpkin Ravioli", "Aglio e Olio",
                            "Bolognese Tagliatelle", "Four Cheese Penne", "Clam Linguine",
                            "Lobster Mac", "Squid Ink Pasta", "Primavera Fusilli",
                            "Lamb Ragu Pappardelle", "Truffle Risotto", "Burrata Ravioli",
                            "Short Rib Pappardelle", "Artichoke Risotto", "Prawn Linguine",
                            "Gorgonzola Gnocchi"],
        "Seafood": ["Grilled Swordfish", "Lobster Tail", "Seafood Paella",
                    "Fish and Chips", "Miso Glazed Cod", "Coconut Shrimp Curry",
                    "Ahi Tuna Steak", "Cioppino", "Crab Linguine",
                    "Sesame Crusted Tuna", "Clam Chowder Bowl", "Oysters Rockefeller",
                    "Mahi Mahi Tacos", "Scallop Risotto", "Steamed Mussels",
                    "Blackened Snapper", "Shrimp Po Boy", "Salmon Teriyaki",
                    "Crab Stuffed Flounder", "Grilled Octopus", "Tuna Poke Bowl",
                    "Baked Lobster", "Pan Seared Scallops", "Fish Tacos",
                    "Shrimp and Grits", "Bouillabaisse", "Crab Cake Dinner",
                    "Grilled Branzino", "Prawn Skewers", "Chilean Sea Bass",
                    "Monkfish Medallions", "Soft Shell Crab", "Crispy Skin Barramundi",
                    "Garlic Butter Prawns", "Smoked Trout Plate", "Ceviche Platter",
                    "Lobster Thermidor", "Seared Diver Scallops", "Coconut Fish Curry",
                    "King Crab Legs"],
        "Desserts": ["Tiramisu", "Creme Brulee", "Chocolate Lava Cake",
                     "New York Cheesecake", "Panna Cotta", "Apple Tart",
                     "Bananas Foster", "Affogato", "Key Lime Pie",
                     "Bread Pudding", "Molten Brownie", "Fruit Sorbet Trio",
                     "Pecan Pie", "Lemon Tart", "Coconut Cake",
                     "Churros", "Baklava", "Creme Caramel", "Cannoli",
                     "Profiteroles", "Sticky Toffee Pudding", "Pavlova",
                     "Chocolate Mousse", "Carrot Cake", "Red Velvet Cake",
                     "Mango Sticky Rice", "Souffle", "Opera Cake",
                     "Fruit Tart", "Gelato Flight", "Baked Alaska",
                     "Tres Leches", "Semifreddo", "Crepe Suzette",
                     "Chocolate Fondant", "Berry Crumble", "Pistachio Cake",
                     "Matcha Cake", "Passion Fruit Tart", "Dark Choc Truffle"],
        "Beverages": ["Espresso Martini", "Classic Mojito", "Craft Lemonade",
                      "Sparkling Water Infusion", "House Red Sangria", "Matcha Latte",
                      "Fresh Orange Juice", "Iced Chai", "Kombucha Flight",
                      "Hot Chocolate Deluxe", "Green Smoothie", "Berry Blast Shake",
                      "Ginger Beer Float", "Cold Brew Coffee", "Hibiscus Tea",
                      "Lavender Latte", "Mango Lassi", "Arnold Palmer",
                      "Mint Julep", "Aperol Spritz", "Pina Colada",
                      "Virgin Mojito", "Turmeric Tonic", "Chai Old Fashioned",
                      "Coconut Water", "Rose Lemonade", "Earl Grey Fizz",
                      "Cucumber Cooler", "Watermelon Agua Fresca", "Spiced Cider",
                      "Nitro Cold Brew", "Thai Iced Tea", "Horchata",
                      "Passion Fruit Spritzer", "Blueberry Smoothie", "Charcoal Latte",
                      "Golden Milk", "Beetroot Latte", "Elderflower Spritz", "Oat Milk Latte"],
        "Sides": ["Truffle Fries", "Roasted Vegetables", "Creamed Spinach",
                  "Garlic Mashed Potatoes", "Sauteed Asparagus", "Corn on the Cob",
                  "Sweet Potato Wedges", "Coleslaw", "Mac and Cheese",
                  "Grilled Corn Salad", "Brussels Sprouts", "Onion Rings",
                  "Rice Pilaf", "Baked Potato", "Polenta",
                  "Loaded Fries", "Steamed Broccoli", "Cauliflower Gratin",
                  "Herb Butter Corn", "Fried Plantains", "Edamame Beans",
                  "Quinoa Pilaf", "Roasted Beets", "Sauteed Kale",
                  "Parmesan Truffle Tots", "Grilled Zucchini", "Crispy Potatoes",
                  "Braised Greens", "Charred Broccolini", "Coconut Rice",
                  "Wild Rice Blend", "Butter Beans", "Roasted Cauliflower",
                  "Hasselback Potato", "Tempura Onion Rings", "Honey Glazed Carrots",
                  "Elote", "Creamy Polenta", "Garlic Green Beans", "Succotash"],
        "Salads": ["Caesar Salad", "Greek Salad", "Waldorf Salad",
                   "Cobb Salad", "Arugula and Pear", "Nicoise Salad",
                   "Asian Sesame Salad", "Kale and Quinoa", "Beet and Goat Cheese",
                   "Wedge Salad", "Caprese Salad Plate", "Taco Salad",
                   "Mediterranean Bowl", "Harvest Salad", "Spinach Strawberry",
                   "Fattoush", "Thai Papaya Salad", "Chopped Italian",
                   "Southwest Salad", "Panzanella", "Cucumber Dill Salad",
                   "Mango Avocado Salad", "Roasted Beet Salad", "Orzo Salad",
                   "Chickpea Salad", "Grilled Peach Salad", "Fennel Citrus Salad",
                   "Endive Walnut Salad", "Tabouleh", "Power Green Bowl",
                   "Shrimp Louie", "Grain Bowl", "Brussels Sprout Salad",
                   "Apple Walnut Salad", "Tuna Nicoise", "Grilled Halloumi Salad",
                   "Pomegranate Salad", "Radicchio Salad", "Warm Lentil Salad",
                   "Burrata Salad"],
    }

    items_per_cat = num_items // len(CATEGORIES)
    remainder = num_items % len(CATEGORIES)

    item_id = 1
    for cat_idx, cat in enumerate(CATEGORIES):
        cat_count = items_per_cat + (1 if cat_idx < remainder else 0)
        name_pool = all_names[cat]
        for i in range(cat_count):
            if i < len(name_pool):
                name = name_pool[i]
            else:
                name = f"{cat} Special #{i+1}"
            if name in item_names_used:
                name = f"{name} v2"
            item_names_used.add(name)

            price = round(random.uniform(8.0, 35.0), 2)
            if cat in ["Main Courses", "Seafood"]:
                price = round(random.uniform(18.0, 55.0), 2)
            elif cat in ["Desserts", "Beverages"]:
                price = round(random.uniform(5.0, 18.0), 2)
            elif cat == "Sides":
                price = round(random.uniform(4.0, 14.0), 2)

            is_seasonal = 1 if random.random() < 0.15 else 0
            date_added = fake.date_between(start_date="-3y", end_date="-30d").isoformat()
            portion_size = round(random.uniform(4.0, 24.0), 1)

            items.append((item_id, name, cat, price, is_seasonal, date_added, portion_size))
            item_id += 1

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO menu_items VALUES (?, ?, ?, ?, ?, ?, ?)", items
    )
    conn.commit()
    return items


def generate_sales_mix(conn, items, num_records_per_item):
    """Generate POS sales mix data across multiple periods."""
    periods = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]
    records = []
    for item_id, name, cat, price, *_ in items:
        num_periods = min(num_records_per_item, len(periods))
        selected_periods = random.sample(periods, num_periods)
        for period in selected_periods:
            base_units = random.randint(5, 200)
            units_sold = base_units
            revenue = round(units_sold * price * random.uniform(0.85, 1.0), 2)
            discount = round(random.uniform(0, 0.15) * revenue, 2) if random.random() < 0.3 else 0.0
            records.append((item_id, period, units_sold, revenue, discount))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO sales_mix (item_id, period, units_sold, total_revenue, discount_applied) VALUES (?, ?, ?, ?, ?)",
        records
    )
    conn.commit()
    return records


def generate_ingredients(conn, items):
    """Generate ingredient links for each menu item."""
    records = []
    units = ["oz", "g", "ml", "cups", "tbsp", "tsp", "pieces"]
    for item_id, name, cat, *_ in items:
        num_ingredients = random.randint(3, 8)
        chosen = random.sample(INGREDIENT_POOL, num_ingredients)
        for ing in chosen:
            qty = round(random.uniform(0.5, 12.0), 2)
            unit = random.choice(units)
            records.append((item_id, ing, qty, unit))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO item_ingredients (item_id, ingredient_name, quantity_per_serving, unit) VALUES (?, ?, ?, ?)",
        records
    )
    conn.commit()
    return records


def generate_prep_time_logs(conn, items, logs_per_item):
    """Generate kitchen prep time logs."""
    stations = ["Grill", "Saute", "Fry", "Prep", "Pastry", "Cold", "Expo"]
    chef_ids = [f"CHEF-{i:03d}" for i in range(1, 16)]
    records = []
    for item_id, name, cat, *_ in items:
        base_prep = random.uniform(3.0, 25.0)
        base_cook = random.uniform(5.0, 35.0)
        for _ in range(logs_per_item):
            date = fake.date_between(start_date="-6m", end_date="today").isoformat()
            prep = round(base_prep * random.uniform(0.7, 1.5), 1)
            cook = round(base_cook * random.uniform(0.7, 1.4), 1)
            station = random.choice(stations)
            chef = random.choice(chef_ids)
            records.append((item_id, date, prep, cook, station, chef))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO prep_time_logs (item_id, date_logged, prep_minutes, cook_minutes, station, chef_id) VALUES (?, ?, ?, ?, ?, ?)",
        records
    )
    conn.commit()
    return records


def generate_customer_ratings(conn, items, ratings_per_item):
    """Generate customer satisfaction ratings."""
    sources = ["Yelp", "Google", "Internal", "OpenTable", "TripAdvisor"]
    records = []
    for item_id, name, cat, *_ in items:
        base_rating = random.uniform(2.0, 5.0)
        for _ in range(ratings_per_item):
            score = round(max(1.0, min(5.0, base_rating + random.gauss(0, 0.6))), 1)
            review = fake.sentence(nb_words=random.randint(5, 20)) if random.random() < 0.6 else None
            date = fake.date_between(start_date="-12m", end_date="today").isoformat()
            source = random.choice(sources)
            records.append((item_id, score, review, date, source))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO customer_ratings (item_id, rating_score, review_text, date_reviewed, source) VALUES (?, ?, ?, ?, ?)",
        records
    )
    conn.commit()
    return records


def create_workspace(workspace, conn, items):
    """Generate workspace files with complementary data."""
    os.makedirs(workspace, exist_ok=True)

    num_files = SCALE["num_workspace_files"]
    num_items = len(items)

    # --- Fixed policy/config files (not counted in SCALE) ---

    # 1. Menu engineering criteria config (YAML)
    criteria_config = """# Menu Engineering Analysis Configuration
# Classification thresholds and scoring weights

classification:
  popularity_threshold_percentile: 50
  profitability_threshold_percentile: 50

scoring_weights:
  food_cost_pct: 0.25
  sales_volume: 0.20
  customer_satisfaction: 0.20
  prep_time_efficiency: 0.15
  revenue_contribution: 0.20

underperformance_thresholds:
  max_food_cost_pct: 35.0
  min_satisfaction_score: 3.2
  max_avg_prep_total_minutes: 30.0
  min_units_sold_per_quarter: 25

action_rules:
  removal_candidates:
    min_criteria_failed: 3
    must_fail:
      - food_cost_pct_exceeded
      - low_satisfaction
  revision_candidates:
    min_criteria_failed: 2
    exclude_if:
      - high_revenue_contribution

output_format:
  sort_primary: composite_score
  sort_direction: ascending
  tie_breaker: item_name_alphabetical
  decimal_places: 2
"""
    with open(os.path.join(workspace, "analysis_config.yaml"), "w") as f:
        f.write(criteria_config)

    # 2. Scoring methodology document (MD)
    methodology = """# Composite Score Calculation

Each menu item receives a composite score from 0 to 100 based on five dimensions. Lower scores indicate worse performance and higher priority for action.

## Dimensions

Food Cost Percentage Score: calculated as max(0, 100 - (actual_food_cost_pct / max_food_cost_pct) * 100). If the food cost percentage exceeds the threshold, this dimension scores 0.

Sales Volume Score: calculated as (item_units_sold_total / max_units_sold_across_all_items) * 100.

Customer Satisfaction Score: calculated as ((avg_rating - 1.0) / 4.0) * 100.

Prep Time Efficiency Score: calculated as max(0, 100 - (avg_total_prep_minutes / max_avg_prep_total_minutes) * 100). If avg total prep exceeds the threshold, this dimension scores 0.

Revenue Contribution Score: calculated as (item_total_revenue / max_revenue_across_all_items) * 100.

## Composite Formula

composite_score = (food_cost_score * weight_food_cost_pct) + (sales_score * weight_sales_volume) + (satisfaction_score * weight_customer_satisfaction) + (prep_score * weight_prep_time_efficiency) + (revenue_score * weight_revenue_contribution)

Round the composite score to 2 decimal places.

## Classification

Items are classified based on which thresholds they fail:
- Fails food_cost_pct_exceeded: actual food cost percentage > max_food_cost_pct threshold
- Fails low_satisfaction: average satisfaction score < min_satisfaction_score
- Fails slow_prep: average total prep+cook minutes > max_avg_prep_total_minutes
- Fails low_sales: total units sold across all periods < min_units_sold_per_quarter multiplied by the number of periods that item appears in

## Action Assignment

REMOVAL: meets removal_candidates criteria (fails at least min_criteria_failed thresholds AND must fail ALL items listed in must_fail)
REVISION: meets revision_candidates criteria (fails at least min_criteria_failed thresholds) but does NOT qualify as REMOVAL, UNLESS it has high revenue contribution (top 25 percent by total revenue across all items, in which case it is downgraded to MONITOR)
MONITOR: fails exactly 1 threshold, OR was downgraded from REVISION due to high revenue contribution
OK: fails no thresholds
"""
    with open(os.path.join(workspace, "scoring_methodology.md"), "w") as f:
        f.write(methodology)

    # --- Scalable data files (counted in SCALE) ---

    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT ingredient_name FROM item_ingredients")
    all_ingredients = [r[0] for r in cursor.fetchall()]

    # Assign costs to ingredients
    ingredient_costs = {}
    for ing in all_ingredients:
        cost_per_unit = round(random.uniform(0.5, 15.0), 2)
        ingredient_costs[ing] = cost_per_unit

    # Split ingredient costs across multiple CSV files
    num_cost_files = max(3, num_files // 3)
    chunk_size = max(1, len(all_ingredients) // num_cost_files)

    cost_file_count = 0
    for i in range(0, len(all_ingredients), chunk_size):
        if cost_file_count >= num_cost_files:
            # Remaining ingredients go in last file
            chunk = all_ingredients[i:]
            filepath = os.path.join(workspace, f"ingredient_costs_{cost_file_count}.csv")
            rows = []
            for ing in chunk:
                rows.append({"ingredient": ing, "cost_per_unit": ingredient_costs[ing],
                             "supplier": random.choice(["FreshFarms", "QualityMeats", "SeaHarvest", "OrganicPlus", "BulkWholesale"]),
                             "last_updated": fake.date_between(start_date="-60d", end_date="today").isoformat()})
            pd.DataFrame(rows).to_csv(filepath, index=False)
            break

        chunk = all_ingredients[i:i + chunk_size]
        filepath = os.path.join(workspace, f"ingredient_costs_{cost_file_count + 1}.csv")
        rows = []
        for ing in chunk:
            rows.append({"ingredient": ing, "cost_per_unit": ingredient_costs[ing],
                         "supplier": random.choice(["FreshFarms", "QualityMeats", "SeaHarvest", "OrganicPlus", "BulkWholesale"]),
                         "last_updated": fake.date_between(start_date="-60d", end_date="today").isoformat()})
        pd.DataFrame(rows).to_csv(filepath, index=False)
        cost_file_count += 1

    # Generate customer feedback summary files (JSON)
    num_feedback_files = max(3, num_files // 3)
    items_per_feedback = max(1, num_items // num_feedback_files)

    feedback_file_count = 0
    for i in range(0, num_items, items_per_feedback):
        if feedback_file_count >= num_feedback_files:
            break
        chunk_items = items[i:i + items_per_feedback]
        feedback_data = []
        for item_id, name, cat, *_ in chunk_items:
            complaints = random.randint(0, 15)
            compliments = random.randint(0, 20)
            return_rate_pct = round(random.uniform(0, 12.0), 1)
            feedback_data.append({
                "item_id": item_id,
                "item_name": name,
                "total_complaints_last_6mo": complaints,
                "total_compliments_last_6mo": compliments,
                "return_rate_pct": return_rate_pct,
                "common_issues": random.sample(
                    ["portion too small", "overcooked", "bland seasoning",
                     "too salty", "long wait time", "presentation poor",
                     "temperature issues", "inconsistent quality"],
                    k=random.randint(0, 3)
                )
            })
        filepath = os.path.join(workspace, f"feedback_summary_{feedback_file_count + 1}.json")
        with open(filepath, "w") as f:
            json.dump(feedback_data, f, indent=2)
        feedback_file_count += 1

    # Generate prep time analysis files (TXT)
    remaining_files = num_files - cost_file_count - feedback_file_count
    num_prep_files = max(2, remaining_files)
    items_per_prep = max(1, num_items // num_prep_files)

    prep_file_count = 0
    for i in range(0, num_items, items_per_prep):
        if prep_file_count >= num_prep_files:
            break
        chunk_items = items[i:i + items_per_prep]
        lines = ["KITCHEN PREP TIME ANALYSIS REPORT", "=" * 40, ""]
        for item_id, name, cat, *_ in chunk_items:
            waste_pct = round(random.uniform(1.0, 20.0), 1)
            complexity = random.choice(["Low", "Medium", "High", "Very High"])
            requires_special_equipment = random.choice(["Yes", "No"])
            lines.append(f"Item ID: {item_id} | {name}")
            lines.append(f"  Waste %: {waste_pct}")
            lines.append(f"  Complexity: {complexity}")
            lines.append(f"  Special Equipment: {requires_special_equipment}")
            lines.append("")
        filepath = os.path.join(workspace, f"prep_analysis_{prep_file_count + 1}.txt")
        with open(filepath, "w") as f:
            f.write("\n".join(lines))
        prep_file_count += 1

    # Fill remaining quota with promotion history files
    current_count = cost_file_count + feedback_file_count + prep_file_count
    extra_idx = 0
    while current_count < num_files:
        extra_idx += 1
        chunk_size_promo = max(1, num_items // (num_files - current_count + extra_idx))
        chunk_start = (extra_idx - 1) * chunk_size_promo
        chunk_end = min(num_items, chunk_start + chunk_size_promo)
        if chunk_start >= num_items:
            chunk_start = 0
            chunk_end = min(num_items, chunk_size_promo)
        chunk_items = items[chunk_start:chunk_end]
        promo_data = []
        for item_id, name, cat, *_ in chunk_items:
            promo_data.append({
                "item_id": item_id,
                "item_name": name,
                "last_promotion_date": fake.date_between(start_date="-12m", end_date="-1m").isoformat(),
                "promotion_lift_pct": round(random.uniform(-5.0, 40.0), 1),
                "paired_with": random.choice([None] + [it[1] for it in items[:8]])
            })
        filepath = os.path.join(workspace, f"promotion_history_{extra_idx}.json")
        with open(filepath, "w") as f:
            json.dump(promo_data, f, indent=2)
        current_count += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    conn = create_database(args.db_path)
    num_items = SCALE["rows_per_table"]

    items = generate_menu_items(conn, num_items)
    generate_sales_mix(conn, items, num_records_per_item=4)
    generate_ingredients(conn, items)
    generate_prep_time_logs(conn, items, logs_per_item=max(3, SCALE["rows_per_table"] // 15))
    generate_customer_ratings(conn, items, ratings_per_item=max(3, SCALE["rows_per_table"] // 12))

    conn.close()

    # Reopen for workspace generation
    conn = sqlite3.connect(args.db_path)
    create_workspace(args.workspace, conn, items)
    conn.close()

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace} with {len(os.listdir(args.workspace))} files")


if __name__ == "__main__":
    main()
