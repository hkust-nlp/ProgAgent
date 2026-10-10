"""
Crude Oil Blending Optimization - Data Generation Script

Generates a SQLite database and workspace files for a crude oil blending
scheduling task. The agent must analyze crude assay data, storage tank levels,
pipeline delivery schedules, and product demand forecasts to produce a daily
blending schedule that maximizes net revenue.
"""
import argparse
import json
import math
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 30,
}

TARGET_DATE = "2026-04-21"

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
CRUDE_GRADES = [
    "Arabian Light", "Arabian Heavy", "Bonny Light", "Brent Blend",
    "Dubai Fateh", "Forcados", "Kirkuk", "Kuwait Export", "Murban",
    "Oman Crude", "Saharan Blend", "Tapis", "Urals", "WTI Midland",
    "Mars Blend", "Basrah Light", "Escravos", "Qua Iboe", "Cabinda",
    "Ekofisk", "Forties Blend", "Oseberg", "Statfjord", "Daqing",
    "Shengli", "Girassol", "Nemba", "Azeri Light", "CPC Blend",
    "Vasconia", "Oriente", "Napo", "Mesa", "Hamaca", "Merey",
    "BCF-17", "Laguna", "Isthmus", "Olmeca", "Minas", "Cossack",
    "Kutubu", "Gippsland", "Bach Ho", "Su Tu Den", "Champion",
    "Seria Light", "Dulang", "Labuan", "Cinta",
]

SUPPLIERS = [
    "Saudi Aramco", "NNPC", "BP Trading", "Shell Trading",
    "ExxonMobil Trading", "Chevron Supply", "TotalEnergies Trading",
    "Lukoil Trading", "ADNOC Trading", "KPC", "Sonatrach",
    "Petronas Trading", "Sinopec Intl", "Pertamina Trading",
    "Pemex Intl", "Repsol Trading", "ENI Trading", "Equinor ASA",
    "CNOOC Trading", "Woodside Energy",
]

ORIGINS = [
    "Middle East", "West Africa", "North Sea", "Russia/CIS",
    "Southeast Asia", "North Africa", "Latin America",
    "Central Asia", "Australia", "East Asia",
]

PRODUCT_TYPES = ["naphtha", "gasoline", "kerosene", "diesel", "fuel_oil"]

PIPELINE_NAMES = [
    "Northern Gateway", "Southern Cross", "Coastal Express",
    "Midland Trunk", "Eastern Seaboard", "Gulf Stream",
    "Pacific Route", "Atlantic Way", "Continental Link",
    "Desert Pipeline", "Highland Pass", "Bayou Corridor",
    "Prairie Line", "Rocky Mountain", "Great Plains",
]

UNIT_PREFIXES = [
    "CDU", "VDU", "FCC", "HCU", "NHT",
    "CCR", "DHT", "VBU", "CKR", "ALK",
]


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------
def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS crude_batches (
            batch_id      INTEGER PRIMARY KEY,
            crude_name    TEXT    NOT NULL,
            supplier      TEXT    NOT NULL,
            origin_region TEXT    NOT NULL,
            api_gravity   REAL   NOT NULL,
            sulfur_pct    REAL   NOT NULL,
            pour_point_f  REAL   NOT NULL,
            cost_per_bbl  REAL   NOT NULL
        );

        CREATE TABLE IF NOT EXISTS storage_tanks (
            tank_id            INTEGER PRIMARY KEY,
            tank_label         TEXT    NOT NULL,
            batch_id           INTEGER NOT NULL,
            current_volume_bbl REAL    NOT NULL,
            capacity_bbl       REAL    NOT NULL,
            status             TEXT    NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES crude_batches(batch_id)
        );

        CREATE TABLE IF NOT EXISTS pipeline_deliveries (
            delivery_id     INTEGER PRIMARY KEY,
            batch_id        INTEGER NOT NULL,
            pipeline_name   TEXT    NOT NULL,
            scheduled_date  TEXT    NOT NULL,
            volume_bbl      REAL    NOT NULL,
            eta_hour        INTEGER NOT NULL,
            delivery_status TEXT    NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES crude_batches(batch_id)
        );

        CREATE TABLE IF NOT EXISTS product_demands (
            demand_id     INTEGER PRIMARY KEY,
            product_type  TEXT    NOT NULL,
            customer_name TEXT    NOT NULL,
            volume_bbl    REAL    NOT NULL,
            target_date   TEXT    NOT NULL,
            price_per_bbl REAL    NOT NULL,
            quality_tier  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blending_units (
            unit_id              INTEGER PRIMARY KEY,
            unit_name            TEXT    NOT NULL,
            product_type         TEXT    NOT NULL,
            max_throughput_bbl   REAL    NOT NULL,
            min_throughput_bbl   REAL    NOT NULL,
            operating_cost_per_bbl REAL  NOT NULL,
            status               TEXT    NOT NULL
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------
def generate_crude_batches(conn, n_rows):
    rows = []
    for i in range(1, n_rows + 1):
        crude_name = CRUDE_GRADES[i % len(CRUDE_GRADES)]
        supplier = random.choice(SUPPLIERS)
        origin = random.choice(ORIGINS)
        api = round(np.random.uniform(15.0, 45.0), 1)
        # Sulfur correlates inversely with API gravity
        base_s = max(0.03, (45.0 - api) / 15.0)
        sulfur = round(base_s * np.random.uniform(0.5, 1.5), 3)
        pour_point = round(np.random.uniform(-40.0, 90.0), 1)
        # Cost: lighter + sweeter crude is more expensive
        light_factor = (api - 15.0) / 30.0
        cost = round(40.0 + 25.0 * light_factor - 5.0 * sulfur
                      + np.random.uniform(-5.0, 5.0), 2)
        rows.append((i, crude_name, supplier, origin, api, sulfur,
                      pour_point, cost))
    conn.executemany(
        "INSERT INTO crude_batches VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return [r[0] for r in rows]


def generate_storage_tanks(conn, n_rows, batch_ids):
    rows = []
    status_pool = (["available"] * 60
                   + ["maintenance"] * 20
                   + ["reserved"] * 20)
    capacities = [50000, 75000, 100000, 150000, 200000]
    for i in range(1, n_rows + 1):
        label = f"TK-{100 + i:04d}"
        bid = random.choice(batch_ids)
        cap = float(random.choice(capacities))
        vol = round(np.random.uniform(0.10, 0.85) * cap, 0)
        status = random.choice(status_pool)
        rows.append((i, label, bid, vol, cap, status))
    conn.executemany(
        "INSERT INTO storage_tanks VALUES (?,?,?,?,?,?)", rows)
    conn.commit()


def generate_pipeline_deliveries(conn, n_rows, batch_ids):
    before_dates = ["2026-04-18", "2026-04-19", "2026-04-20"]
    after_dates = ["2026-04-22", "2026-04-23", "2026-04-24", "2026-04-25"]
    rows = []
    for i in range(1, n_rows + 1):
        bid = random.choice(batch_ids)
        pipe = random.choice(PIPELINE_NAMES)
        r = random.random()
        if r < 0.30:
            date = TARGET_DATE
        elif r < 0.50:
            date = random.choice(before_dates)
        else:
            date = random.choice(after_dates)
        volume = round(np.random.uniform(5000, 50000), 0)
        eta = random.randint(0, 23)
        if date <= TARGET_DATE:
            status = random.choices(
                ["confirmed", "tentative", "cancelled"],
                weights=[70, 20, 10])[0]
        else:
            status = random.choices(
                ["confirmed", "tentative"],
                weights=[60, 40])[0]
        rows.append((i, bid, pipe, date, volume, eta, status))
    conn.executemany(
        "INSERT INTO pipeline_deliveries VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_product_demands(conn, n_rows):
    fake = Faker()
    Faker.seed(42)
    other_dates = ["2026-04-20", "2026-04-22", "2026-04-23",
                   "2026-04-24", "2026-04-25"]
    price_ranges = {
        "naphtha":  (55.0, 85.0),
        "gasoline": (70.0, 110.0),
        "kerosene": (65.0, 100.0),
        "diesel":   (60.0, 95.0),
        "fuel_oil": (30.0, 55.0),
    }
    rows = []
    for i in range(1, n_rows + 1):
        ptype = PRODUCT_TYPES[i % len(PRODUCT_TYPES)]
        cust = fake.company()
        vol = round(np.random.uniform(2000, 30000), 0)
        if random.random() < 0.40:
            date = TARGET_DATE
        else:
            date = random.choice(other_dates)
        lo, hi = price_ranges[ptype]
        price = round(np.random.uniform(lo, hi), 2)
        tier = random.choices(["standard", "premium"],
                              weights=[60, 40])[0]
        rows.append((i, ptype, cust, vol, date, price, tier))
    conn.executemany(
        "INSERT INTO product_demands VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_blending_units(conn, n_rows):
    rows = []
    status_pool = (["online"] * 60
                   + ["offline"] * 25
                   + ["standby"] * 15)
    for i in range(1, n_rows + 1):
        prefix = UNIT_PREFIXES[i % len(UNIT_PREFIXES)]
        name = f"{prefix}-{i:03d}"
        ptype = PRODUCT_TYPES[i % len(PRODUCT_TYPES)]
        max_tp = round(np.random.uniform(20000, 80000), 0)
        min_tp = round(max_tp * np.random.uniform(0.20, 0.40), 0)
        op_cost = round(np.random.uniform(2.0, 8.0), 2)
        status = random.choice(status_pool)
        rows.append((i, name, ptype, max_tp, min_tp, op_cost, status))
    conn.executemany(
        "INSERT INTO blending_units VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------
def generate_workspace(workspace_dir, conn, n_files):
    os.makedirs(workspace_dir, exist_ok=True)
    cur = conn.cursor()

    # ---- Scalable files: crude lab analysis CSVs ----
    cur.execute("SELECT batch_id FROM crude_batches ORDER BY batch_id")
    all_ids = [r[0] for r in cur.fetchall()]
    per_file = max(1, math.ceil(len(all_ids) / n_files))

    for fi in range(n_files):
        start = fi * per_file
        subset = all_ids[start:start + per_file]
        if not subset:
            subset = [all_ids[-1]]
        lab_rows = []
        for bid in subset:
            lab_rows.append({
                "batch_id": bid,
                "mercaptan_ppm": round(np.random.uniform(1.0, 50.0), 1),
                "salt_ptb": round(np.random.uniform(0.5, 20.0), 1),
                "nickel_ppm": round(np.random.uniform(0.5, 40.0), 1),
                "vanadium_ppm": round(np.random.uniform(0.5, 80.0), 1),
                "hydrogen_sulfide_ppm": round(np.random.uniform(1.0, 100.0), 1),
            })
        pd.DataFrame(lab_rows).to_csv(
            os.path.join(workspace_dir, f"crude_lab_{fi + 1}.csv"),
            index=False)

    # ---- Fixed: quality_specs.yaml ----
    quality_specs = {
        "naphtha": {
            "standard": {
                "min_api_gravity": 35.0,
                "max_sulfur_pct": 0.50,
                "max_pour_point_f": 30.0,
            },
            "premium": {
                "min_api_gravity": 38.0,
                "max_sulfur_pct": 0.30,
                "max_pour_point_f": 20.0,
                "max_mercaptan_ppm": 20.0,
                "max_salt_ptb": 8.0,
            },
        },
        "gasoline": {
            "standard": {
                "min_api_gravity": 30.0,
                "max_sulfur_pct": 1.00,
                "max_pour_point_f": 50.0,
            },
            "premium": {
                "min_api_gravity": 33.0,
                "max_sulfur_pct": 0.60,
                "max_pour_point_f": 35.0,
                "max_mercaptan_ppm": 15.0,
                "max_salt_ptb": 5.0,
            },
        },
        "kerosene": {
            "standard": {
                "min_api_gravity": 28.0,
                "max_sulfur_pct": 1.50,
                "max_pour_point_f": 60.0,
            },
            "premium": {
                "min_api_gravity": 32.0,
                "max_sulfur_pct": 0.80,
                "max_pour_point_f": 40.0,
                "max_mercaptan_ppm": 10.0,
                "max_salt_ptb": 3.0,
            },
        },
        "diesel": {
            "standard": {
                "min_api_gravity": 22.0,
                "max_sulfur_pct": 2.00,
            },
            "premium": {
                "min_api_gravity": 26.0,
                "max_sulfur_pct": 1.20,
                "max_nickel_ppm": 8.0,
                "max_vanadium_ppm": 15.0,
            },
        },
        "fuel_oil": {
            "standard": {
                "min_api_gravity": 10.0,
                "max_sulfur_pct": 3.50,
            },
            "premium": {
                "min_api_gravity": 15.0,
                "max_sulfur_pct": 2.50,
                "max_nickel_ppm": 25.0,
                "max_vanadium_ppm": 50.0,
            },
        },
    }
    with open(os.path.join(workspace_dir, "quality_specs.yaml"), "w") as f:
        yaml.dump(quality_specs, f, default_flow_style=False, sort_keys=False)

    # ---- Fixed: blending_rules.json ----
    blending_rules = {
        "mixing_method": "volume_weighted_average",
        "processing_loss_pct": 5.0,
        "properties_to_check": [
            "api_gravity", "sulfur_pct", "pour_point_f",
            "mercaptan_ppm", "salt_ptb", "nickel_ppm", "vanadium_ppm"
        ],
        "notes": (
            "All blend properties are computed as volume-weighted averages "
            "of the individual crude batch properties. Processing loss is "
            "applied uniformly: product_volume = crude_input_volume * "
            "(1 - processing_loss_pct / 100)."
        ),
    }
    with open(os.path.join(workspace_dir, "blending_rules.json"), "w") as f:
        json.dump(blending_rules, f, indent=2)

    # ---- Fixed: scheduling_policy.md ----
    policy = """## Demand Processing Order

All product demands for the planning date shall be processed in strictly
descending order of price per barrel. When two demands share the same
price per barrel, they are processed in ascending order of demand
identifier.

## Blending Unit Assignment

For each demand, assign the first available blending unit that is capable
of producing the required product type. Units are considered in ascending
order of unit identifier. Only units whose status is "online" are
eligible. Each unit may be assigned to at most one demand in a single
daily schedule.

## Crude Feedstock Eligibility

Only crude oil that is physically accessible on the planning date may be
used. Accessible crude comes from two sources: storage tanks whose status
is "available", and pipeline deliveries whose status is "confirmed" and
whose scheduled date is on or before the planning date. Each such source
contributes the volume recorded in the database.

## Individual Batch Qualification

For a crude batch to be used in a blend for a particular product type
and quality tier, every quality property specified for that product-tier
combination must be satisfied by the batch individually. Properties from
the database (api_gravity, sulfur_pct, pour_point_f) and properties from
the laboratory analysis reports (mercaptan_ppm, salt_ptb, nickel_ppm,
vanadium_ppm) are both checked. A batch missing laboratory data for a
property required by the tier is disqualified for that tier.

For minimum thresholds the batch value must be greater than or equal to
the limit; for maximum thresholds the batch value must be less than or
equal to the limit.

## Crude Allocation Priority

Among all qualifying batches for a given demand, allocate crude in
ascending order of cost per barrel. Break ties by ascending batch
identifier. Draw from all available sources (tanks and deliveries)
for that batch, consuming tank volume first (in ascending tank
identifier order), then delivery volume (in ascending delivery
identifier order), before moving to the next batch.

## Volume Calculation

The crude input volume required to produce the demanded product volume
is: crude_input = demand_volume / (1 - processing_loss_pct / 100). Do
not exceed the maximum throughput of the assigned blending unit. If the
required crude input exceeds unit capacity, cap at unit capacity and
reduce product volume proportionally. If total available qualifying
crude is less than the required input, use all available qualifying
crude and record a partial fulfillment.

## Net Revenue

Net revenue for each schedule entry is:

  net_revenue = product_volume * price_per_bbl
              - crude_input_volume * weighted_avg_crude_cost
              - crude_input_volume * unit_operating_cost

where product_volume = crude_input_volume * (1 - processing_loss_pct / 100),
and weighted_avg_crude_cost is the volume-weighted average cost_per_bbl
of the crude batches consumed.
"""
    with open(os.path.join(workspace_dir, "scheduling_policy.md"), "w") as f:
        f.write(policy)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    batch_ids = generate_crude_batches(conn, n)
    generate_storage_tanks(conn, n, batch_ids)
    generate_pipeline_deliveries(conn, n, batch_ids)
    generate_product_demands(conn, n)
    generate_blending_units(conn, n)
    generate_workspace(args.workspace, conn, SCALE["num_workspace_files"])

    conn.close()


if __name__ == "__main__":
    main()
