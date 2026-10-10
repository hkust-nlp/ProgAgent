import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 30,
}

# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
BREEDS = ["Angus", "Hereford", "Charolais", "Simmental", "Limousin"]

COMMODITY_DATA = [
    ("Corn",            "grain",      9.0,  3.20),
    ("Soybean Meal",    "protein",   47.5,  3.30),
    ("Barley",          "grain",     12.0,  3.00),
    ("Wheat Middlings", "byproduct", 17.5,  2.80),
    ("Alfalfa Hay",     "forage",    18.0,  2.20),
    ("Corn Silage",     "forage",     8.0,  2.30),
    ("Mineral Premix",  "supplement", 0.0,  0.00),
    ("Fat Supplement",  "supplement", 0.0,  6.50),
]

BASE_PRICES = {
    "Corn": 180, "Soybean Meal": 420, "Barley": 200,
    "Wheat Middlings": 160, "Alfalfa Hay": 250, "Corn Silage": 55,
    "Mineral Premix": 800, "Fat Supplement": 950,
}

SUPPLIERS = ["AgriCorp", "FeedFirst", "GrainMasters", "NutriStock", "PrairieSupply"]

BREED_PARAMS = {
    "Angus":     {"base_wt": 200, "adg": 1.40, "dmi_base": 2.80, "pen_wt": 250},
    "Hereford":  {"base_wt": 195, "adg": 1.30, "dmi_base": 2.90, "pen_wt": 240},
    "Charolais": {"base_wt": 220, "adg": 1.60, "dmi_base": 2.70, "pen_wt": 270},
    "Simmental": {"base_wt": 210, "adg": 1.50, "dmi_base": 2.75, "pen_wt": 260},
    "Limousin":  {"base_wt": 205, "adg": 1.45, "dmi_base": 2.85, "pen_wt": 255},
}

# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS pens (
        pen_id TEXT PRIMARY KEY,
        breed TEXT NOT NULL,
        num_animals INTEGER NOT NULL,
        avg_weight_kg REAL NOT NULL,
        age_weeks INTEGER NOT NULL,
        barn_id TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS feeder_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pen_id TEXT NOT NULL,
        commodity TEXT NOT NULL,
        log_date TEXT NOT NULL,
        quantity_kg REAL NOT NULL,
        waste_pct REAL NOT NULL,
        FOREIGN KEY (pen_id) REFERENCES pens(pen_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS growth_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        breed TEXT NOT NULL,
        age_week INTEGER NOT NULL,
        target_weight_kg REAL NOT NULL,
        target_adg_kg REAL NOT NULL,
        dmi_pct_bw REAL NOT NULL,
        min_protein_pct REAL NOT NULL,
        min_energy_mcal_kg REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS silo_inventory (
        silo_id TEXT PRIMARY KEY,
        commodity TEXT NOT NULL,
        current_stock_kg REAL NOT NULL,
        capacity_kg REAL NOT NULL,
        location TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS market_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commodity TEXT NOT NULL,
        price_date TEXT NOT NULL,
        price_per_ton REAL NOT NULL,
        supplier TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS commodities (
        name TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        protein_pct REAL NOT NULL,
        energy_mcal_kg REAL NOT NULL
    )""")
    conn.commit()

# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------

def generate_commodities(conn):
    conn.executemany("INSERT INTO commodities VALUES (?,?,?,?)", COMMODITY_DATA)
    conn.commit()


def generate_pens(conn):
    num_pens = SCALE["rows_per_table"]
    num_barns = max(3, num_pens // 10)
    rows = []
    for i in range(num_pens):
        pen_id = f"P{i+1:04d}"
        breed = BREEDS[i % len(BREEDS)]
        num_animals = random.randint(15, 40)
        age_weeks = random.randint(8, 35)
        base_wt = BREED_PARAMS[breed]["pen_wt"]
        avg_weight = round(base_wt + age_weeks * random.uniform(5.0, 8.0), 1)
        barn_id = f"B{(i % num_barns) + 1:03d}"
        rows.append((pen_id, breed, num_animals, avg_weight, age_weeks, barn_id))
    conn.executemany("INSERT INTO pens VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_feeder_logs(conn, pens):
    from datetime import date, timedelta
    base_date = date(2026, 4, 8)  # 14 days ending 2026-04-21
    feed_commodities = [c[0] for c in COMMODITY_DATA
                        if c[1] in ("grain", "forage", "protein")]
    rows = []
    for pen_id, breed, num_animals, avg_weight, age_weeks, barn_id in pens:
        pen_comms = random.sample(feed_commodities,
                                  random.randint(2, min(3, len(feed_commodities))))
        for day_offset in range(14):
            log_date = (base_date + timedelta(days=day_offset)).isoformat()
            for comm in pen_comms:
                qty = round(num_animals * random.uniform(1.5, 4.0), 1)
                waste = round(random.uniform(2.0, 15.0), 1)
                rows.append((pen_id, comm, log_date, qty, waste))
    conn.executemany(
        "INSERT INTO feeder_logs (pen_id, commodity, log_date, quantity_kg, waste_pct) "
        "VALUES (?,?,?,?,?)", rows)
    conn.commit()


def generate_growth_targets(conn):
    num_weeks = max(40, SCALE["rows_per_table"] // len(BREEDS) + 10)
    rows = []
    for breed in BREEDS:
        bp = BREED_PARAMS[breed]
        for week in range(1, num_weeks + 1):
            target_wt = round(bp["base_wt"] + week * bp["adg"] * 7, 1)
            adg = round(bp["adg"] + np.random.uniform(-0.05, 0.05), 3)
            dmi_pct = round(
                max(1.8, bp["dmi_base"] - week * 0.015
                    + np.random.uniform(-0.05, 0.05)), 2)
            protein_req = round(
                max(10.0, 16.0 - week * 0.12
                    + np.random.uniform(-0.3, 0.3)), 1)
            energy_req = round(2.5 + np.random.uniform(-0.15, 0.15), 2)
            rows.append((breed, week, target_wt, adg, dmi_pct,
                         protein_req, energy_req))
    conn.executemany(
        "INSERT INTO growth_targets "
        "(breed, age_week, target_weight_kg, target_adg_kg, "
        "dmi_pct_bw, min_protein_pct, min_energy_mcal_kg) "
        "VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_silo_inventory(conn):
    num_silos = SCALE["rows_per_table"]
    commodity_names = [c[0] for c in COMMODITY_DATA]
    locations = ["North Yard", "South Yard", "Central Mill",
                 "East Barn", "West Barn"]
    rows = []
    for i in range(num_silos):
        silo_id = f"S{i+1:04d}"
        commodity = commodity_names[i % len(commodity_names)]
        capacity = round(random.uniform(5000, 50000), 0)
        current = round(capacity * random.uniform(0.3, 0.9), 0)
        location = locations[i % len(locations)]
        rows.append((silo_id, commodity, current, capacity, location))
    conn.executemany("INSERT INTO silo_inventory VALUES (?,?,?,?,?)", rows)
    conn.commit()


def generate_market_prices(conn):
    from datetime import date, timedelta
    commodity_names = [c[0] for c in COMMODITY_DATA]
    num_days = max(14, SCALE["rows_per_table"] // len(commodity_names) + 1)
    base_date = date(2026, 4, 22) - timedelta(days=num_days - 1)
    rows = []
    for comm in commodity_names:
        bp = BASE_PRICES[comm]
        for d in range(num_days):
            price_date = (base_date + timedelta(days=d)).isoformat()
            price = round(bp * (1 + random.uniform(-0.08, 0.08)), 2)
            supplier = random.choice(SUPPLIERS)
            rows.append((comm, price_date, price, supplier))
    conn.executemany(
        "INSERT INTO market_prices (commodity, price_date, price_per_ton, supplier) "
        "VALUES (?,?,?,?)", rows)
    conn.commit()

# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def generate_workspace(workspace, conn):
    os.makedirs(workspace, exist_ok=True)
    _generate_condition_files(workspace, conn)
    _generate_config_files(workspace)


def _generate_condition_files(workspace, conn):
    """Scalable per-batch pen condition assessment CSVs."""
    num_files = SCALE["num_workspace_files"]
    all_pens = [r[0] for r in
                conn.execute("SELECT pen_id FROM pens ORDER BY pen_id").fetchall()]
    pens_per_file = len(all_pens) // num_files
    remainder = len(all_pens) % num_files

    flags_pool = ["green"] * 4 + ["yellow"] * 2 + ["red"]

    idx = 0
    for fi in range(num_files):
        count = pens_per_file + (1 if fi < remainder else 0)
        batch = all_pens[idx:idx + count]
        idx += count
        filepath = os.path.join(workspace, f"condition_batch_{fi+1:03d}.csv")
        with open(filepath, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "pen_id", "assessment_date", "body_condition_score",
                "health_flag", "actual_adg_kg", "notes"])
            for pid in batch:
                bcs = round(random.uniform(4.0, 8.5), 1)
                flag = random.choice(flags_pool)
                adg = round(random.uniform(0.8, 1.8), 2)
                note = fake.sentence(nb_words=6)
                writer.writerow([pid, "2026-04-21", bcs, flag, adg, note])


def _generate_config_files(workspace):
    """Fixed policy / config files (not counted in SCALE)."""

    # 1. formulation_rules.yaml
    rules = {
        "feeding_phases": {
            "growing": {
                "max_age_weeks": 20,
                "category_allocation": {
                    "forage":     0.45,
                    "grain":      0.30,
                    "protein":    0.15,
                    "byproduct":  0.07,
                    "supplement": 0.03,
                },
            },
            "finishing": {
                "min_age_weeks": 21,
                "category_allocation": {
                    "forage":     0.30,
                    "grain":      0.42,
                    "protein":    0.18,
                    "byproduct":  0.06,
                    "supplement": 0.04,
                },
            },
        },
        "supplement_split": {
            "Mineral Premix": 0.40,
            "Fat Supplement":  0.60,
        },
        "health_adjustments": {
            "green":  1.00,
            "yellow": 0.85,
            "red":    1.10,
        },
        "waste_rules": {
            "lookback_days":    7,
            "threshold_pct":    8.0,
            "reduction_factor": 1.5,
        },
        "commodity_categories": {
            "Corn":            "grain",
            "Barley":          "grain",
            "Soybean Meal":    "protein",
            "Wheat Middlings": "byproduct",
            "Alfalfa Hay":     "forage",
            "Corn Silage":     "forage",
            "Mineral Premix":  "supplement",
            "Fat Supplement":  "supplement",
        },
    }
    with open(os.path.join(workspace, "formulation_rules.yaml"), "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)

    # 2. cost_policy.json
    policy = {
        "weekly_budget_per_head_usd": 35.00,
        "preferred_suppliers": ["AgriCorp", "FeedFirst"],
        "price_ceiling_per_ton_usd": {
            "Corn": 220, "Soybean Meal": 500, "Barley": 250,
            "Wheat Middlings": 200, "Alfalfa Hay": 300,
            "Corn Silage": 80, "Mineral Premix": 1000,
            "Fat Supplement": 1200,
        },
        "inventory_safety_margin_pct": 10,
    }
    with open(os.path.join(workspace, "cost_policy.json"), "w") as f:
        json.dump(policy, f, indent=2)

    # 3. nutrient_reference.md
    with open(os.path.join(workspace, "nutrient_reference.md"), "w") as f:
        f.write(_NUTRIENT_REF)

    # 4. output_spec.txt
    with open(os.path.join(workspace, "output_spec.txt"), "w") as f:
        f.write(_OUTPUT_SPEC)

    # 5. ration_methodology.md
    with open(os.path.join(workspace, "ration_methodology.md"), "w") as f:
        f.write(_RATION_METHODOLOGY)


_NUTRIENT_REF = """\
# Nutrient Computation Reference

To compute the blended crude protein percentage of a ration, take the weighted
average of each ingredient's protein content, weighted by that ingredient's
share of total daily intake.

Blended CP (percent) equals the sum of each ingredient's fraction of the total
ration multiplied by that ingredient's protein percentage.

Similarly, blended metabolizable energy in Mcal per kg equals the weighted
average of each ingredient's energy density, weighted by the same fractions.

When the blended crude protein falls below the minimum requirement for the
pen's growth phase, increase the protein category allocation by two percentage
points and decrease the grain category allocation by two percentage points.
Repeat this adjustment until the crude protein requirement is met or the
protein category share reaches twenty-five percent.

When the blended metabolizable energy falls below the minimum requirement,
increase the grain category allocation by one percentage point and decrease
the forage category allocation by one percentage point. Repeat until the
energy requirement is met or the forage share drops to fifteen percent.

All per-category commodity selection should use the most recent available
market price (latest date with the lowest price among suppliers on that date).
Within a category that has multiple commodities, select the one with the lower
price per ton. If prices are identical, select the commodity whose name comes
first alphabetically.
"""

_OUTPUT_SPEC = """\
Output Specification for Weekly Ration Schedule

The weekly ration schedule must be saved as weekly_ration_schedule.csv with
the following columns in exact order:

pen_id, commodity, daily_quantity_kg, weekly_total_kg, daily_cost_usd

All numeric values must be rounded to exactly two decimal places.
Rows must be sorted by pen_id in ascending order, then by commodity in
ascending alphabetical order.
daily_quantity_kg is the amount in kilograms of that commodity to feed per
day for the entire pen (all animals combined).
weekly_total_kg equals daily_quantity_kg multiplied by seven.
daily_cost_usd equals daily_quantity_kg multiplied by the latest market price
per ton divided by one thousand.

Additionally, save an adjustment_report.json file containing:
- total_weekly_cost: sum of all weekly costs (each row's daily_cost_usd
  multiplied by seven), rounded to two decimal places
- num_pens_adjusted: count of pens where the health flag was not green or the
  average waste over the lookback period exceeded the threshold
- adjustments: a list of objects each with pen_id, adjustment_type (one of
  health, waste, or both), and a description string
"""

_RATION_METHODOLOGY = """\
# Weekly Ration Computation Methodology

This document is the authoritative procedure for computing each pen's weekly
ration. It is applied together with the formulation rules configuration, the
cost policy, the nutrient computation reference, and the output specification.

## Base intake

For every pen, the growth-target record matching the pen's breed and current
age in weeks supplies the expected dry-matter intake as a percentage of body
weight, the minimum crude protein requirement, and the minimum metabolizable
energy requirement. The base daily intake for each animal equals the pen's
average live weight multiplied by that percentage divided by one hundred. The
pen's total daily intake is that per-head figure multiplied by the number of
animals in the pen.

## Health adjustment

Each pen's most recent health and condition assessment carries a health flag.
The pen's intake must be scaled by the multiplier assigned to that flag in the
health adjustments section of the formulation rules. Pens flagged green use
the standard multiplier.

## Waste adjustment

For each pen, take the feeder consumption history over the most recent days
given by the lookback window in the formulation rules (counting back from the
pen's latest log date) and compute the average feed waste percentage across
all log entries in that window. If the average waste exceeds the configured
threshold, reduce the pen's total daily intake by the excess above the
threshold multiplied by the configured reduction factor divided by one
hundred. This waste reduction is applied as a multiplicative adjustment to the
intake already modified by the health multiplier.

## Category allocation and commodity selection

Each pen belongs to a feeding phase determined by its age in weeks relative to
the phase boundary in the formulation rules: pens at or below the growing
phase's maximum age week are in the growing phase, all older pens are in the
finishing phase. The pen's adjusted total daily intake is divided across
feed-commodity categories using the phase-specific category allocation table.

Within any category containing more than one commodity, select the commodity
with the lowest most-recent market price; ties are broken alphabetically by
commodity name (see the nutrient computation reference). For the supplement
category, do not select by price: split the category quantity between the
individual supplement commodities using the fractions prescribed in the
supplement split section of the formulation rules.

## Nutritional floors

After the initial allocation, verify that the blended crude protein and
metabolizable energy of the ration meet the pen's minimum requirements, and if
not, iteratively adjust category shares following the procedure in the
nutrient computation reference. Protein adjustments are applied first, then
energy adjustments.

## Inventory feasibility

The total weekly demand for each commodity, summed across all pens, must not
exceed the total silo stock available for that commodity after reserving the
inventory safety margin percentage defined in the cost policy.
"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    generate_commodities(conn)
    pens = generate_pens(conn)
    generate_feeder_logs(conn, pens)
    generate_growth_targets(conn)
    generate_silo_inventory(conn)
    generate_market_prices(conn)
    generate_workspace(args.workspace, conn)
    conn.close()
    print("Data generation complete.")


if __name__ == "__main__":
    main()
