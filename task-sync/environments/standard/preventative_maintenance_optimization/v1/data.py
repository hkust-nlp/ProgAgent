"""
Preventative Maintenance Scheduling – Data Generator
Generates SQLite database and workspace files for the maintenance calendar task.
"""

import os
import sys
import json
import csv
import sqlite3
import argparse
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 16,
}

# ── deterministic seeding ──
random.seed(42)
np.random.seed(42)
Faker.seed(42)
fake = Faker()

CATEGORIES = [
    "HVAC", "Plumbing", "Electrical", "Elevator",
    "Fire Safety", "Roofing", "Generator", "Water Heater",
]

PROPERTY_TYPES = ["Residential", "Commercial", "Mixed-Use", "Industrial"]

SERVICE_HOURS = {
    "HVAC": 4.0,
    "Plumbing": 3.0,
    "Electrical": 3.5,
    "Elevator": 6.0,
    "Fire Safety": 2.5,
    "Roofing": 5.0,
    "Generator": 4.5,
    "Water Heater": 3.0,
}


# ─────────────────────────── schema ───────────────────────────

def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS buildings (
            building_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            address     TEXT NOT NULL,
            zone_id     INTEGER NOT NULL,
            num_units   INTEGER NOT NULL,
            property_type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS appliances (
            appliance_id  INTEGER PRIMARY KEY,
            building_id   INTEGER NOT NULL,
            name          TEXT NOT NULL,
            category      TEXT NOT NULL,
            install_date  TEXT NOT NULL,
            warranty_expiry TEXT NOT NULL,
            criticality   INTEGER NOT NULL,
            FOREIGN KEY (building_id) REFERENCES buildings(building_id)
        );
        CREATE TABLE IF NOT EXISTS work_orders (
            wo_id         INTEGER PRIMARY KEY,
            appliance_id  INTEGER NOT NULL,
            vendor_id     INTEGER NOT NULL,
            service_date  TEXT NOT NULL,
            cost          REAL NOT NULL,
            work_type     TEXT NOT NULL,
            notes         TEXT,
            FOREIGN KEY (appliance_id) REFERENCES appliances(appliance_id),
            FOREIGN KEY (vendor_id)    REFERENCES vendors(vendor_id)
        );
        CREATE TABLE IF NOT EXISTS tenant_requests (
            request_id   INTEGER PRIMARY KEY,
            building_id  INTEGER NOT NULL,
            category     TEXT NOT NULL,
            request_date TEXT NOT NULL,
            description  TEXT NOT NULL,
            urgency      TEXT NOT NULL,
            resolved     INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (building_id) REFERENCES buildings(building_id)
        );
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id        INTEGER PRIMARY KEY,
            name             TEXT NOT NULL,
            specialty        TEXT NOT NULL,
            base_hourly_rate REAL NOT NULL,
            reliability_score REAL NOT NULL,
            active           INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()


# ─────────────────────── data generators ──────────────────────

def generate_buildings(conn, n, num_zones):
    rows = []
    for i in range(1, n + 1):
        rows.append((
            i,
            f"Building {i:03d} - {fake.street_name()}",
            fake.address().replace("\n", ", "),
            ((i - 1) % num_zones) + 1,
            int(np.random.randint(5, 120)),
            str(np.random.choice(PROPERTY_TYPES)),
        ))
    conn.executemany("INSERT INTO buildings VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return [{"building_id": r[0], "zone_id": r[3]} for r in rows]


def generate_vendors(conn, n):
    rows = []
    for i in range(1, n + 1):
        cat = CATEGORIES[(i - 1) % len(CATEGORIES)]
        # guarantee at least one active vendor per category
        if i <= len(CATEGORIES):
            active = 1
        else:
            active = int(np.random.choice([0, 1], p=[0.2, 0.8]))
        rows.append((
            i,
            fake.company(),
            cat,
            round(float(np.random.uniform(40, 150)), 2),
            round(float(np.random.uniform(0.50, 1.00)), 2),
            active,
        ))
    conn.executemany("INSERT INTO vendors VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return [
        {"vendor_id": r[0], "specialty": r[2],
         "base_hourly_rate": r[3], "reliability_score": r[4], "active": r[5]}
        for r in rows
    ]


def generate_appliances(conn, n, building_ids):
    rows = []
    base_date = datetime(2019, 1, 1)
    for i in range(1, n + 1):
        bld = building_ids[(i - 1) % len(building_ids)]
        cat = str(np.random.choice(CATEGORIES))
        install = base_date + timedelta(days=int(np.random.randint(0, 2000)))
        warranty_years = int(np.random.choice([3, 5, 7, 10]))
        warranty_exp = install + timedelta(days=warranty_years * 365)
        crit = int(np.random.randint(1, 6))
        rows.append((
            i, bld, f"{cat} Unit {i}", cat,
            install.strftime("%Y-%m-%d"),
            warranty_exp.strftime("%Y-%m-%d"),
            crit,
        ))
    conn.executemany("INSERT INTO appliances VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return [{"appliance_id": r[0], "building_id": r[1], "category": r[3]}
            for r in rows]


def generate_work_orders(conn, n, appliance_ids, vendor_ids):
    work_types = ["preventive", "corrective", "emergency"]
    rows = []
    for i in range(1, n + 1):
        app_id = int(np.random.choice(appliance_ids))
        vid = int(np.random.choice(vendor_ids))
        service_date = datetime(2024, 1, 1) + timedelta(
            days=int(np.random.randint(0, 900))
        )
        cost = round(float(np.random.uniform(100, 2000)), 2)
        wtype = str(np.random.choice(work_types))
        rows.append((
            i, app_id, vid, service_date.strftime("%Y-%m-%d"),
            cost, wtype, fake.sentence(),
        ))
    conn.executemany("INSERT INTO work_orders VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_tenant_requests(conn, n, building_ids):
    urgencies = ["low", "medium", "high", "critical"]
    rows = []
    for i in range(1, n + 1):
        bld = int(np.random.choice(building_ids))
        cat = str(np.random.choice(CATEGORIES))
        req_date = datetime(2025, 1, 1) + timedelta(
            days=int(np.random.randint(0, 480))
        )
        rows.append((
            i, bld, cat, req_date.strftime("%Y-%m-%d"),
            fake.sentence(), str(np.random.choice(urgencies)),
            int(np.random.choice([0, 1], p=[0.4, 0.6])),
        ))
    conn.executemany(
        "INSERT INTO tenant_requests VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()


# ─────────────────────── workspace files ──────────────────────

def generate_workspace(conn, workspace, num_files, buildings, appliances, vendors):
    os.makedirs(workspace, exist_ok=True)

    num_zones = num_files
    bld_zone = {b["building_id"]: b["zone_id"] for b in buildings}

    # group appliances by zone through their building
    zone_apps = {}
    for app in appliances:
        z = bld_zone.get(app["building_id"], 1)
        zone_apps.setdefault(z, []).append(app)

    # ── scalable files: zone inspection reports ──
    for zone_id in range(1, num_zones + 1):
        apps = zone_apps.get(zone_id, [])
        rows = []
        for app in apps:
            condition = round(float(np.random.uniform(20, 95)), 1)
            insp_date = datetime(2026, 1, 15) + timedelta(
                days=int(np.random.randint(0, 120))
            )
            defects = int(np.random.randint(0, 8))
            rec = str(np.random.choice([
                "routine check", "minor repair needed",
                "major overhaul recommended", "replacement advised",
                "monitor closely",
            ]))
            rows.append([
                app["appliance_id"], app["building_id"],
                condition, insp_date.strftime("%Y-%m-%d"), defects, rec,
            ])
        filepath = os.path.join(workspace, f"zone_{zone_id}_inspections.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "appliance_id", "building_id", "condition_score",
                "last_inspected", "defects_found", "recommended_action",
            ])
            writer.writerows(rows)

    # ── fixed file 1: priority_weights.yaml ──
    import yaml
    priority_config = {
        "scoring": {
            "weights": {
                "warranty_urgency": 0.25,
                "condition_deficit": 0.20,
                "request_frequency": 0.20,
                "maintenance_gap": 0.20,
                "criticality": 0.15,
            },
            "normalization": {
                "warranty_warning_days": 180,
                "max_maintenance_gap_days": 365,
                "max_request_count": 10,
                "default_condition_score": 70,
            },
        },
        "target_quarter": "Q3",
        "target_year": 2026,
        "quarter_months": ["2026-07", "2026-08", "2026-09"],
        "quarter_start": "2026-07-01",
        "quarter_end": "2026-09-30",
        "scheduling": {
            "min_priority_score": 40.0,
        },
    }
    with open(os.path.join(workspace, "priority_weights.yaml"), "w") as f:
        yaml.dump(priority_config, f, default_flow_style=False, sort_keys=False)

    # ── fixed file 2: seasonal_vendor_rates.csv ──
    rate_rows = []
    for v in vendors:
        q1 = round(float(np.random.uniform(0.80, 1.30)), 2)
        q2 = round(float(np.random.uniform(0.80, 1.30)), 2)
        q3 = round(float(np.random.uniform(0.90, 1.50)), 2)
        q4 = round(float(np.random.uniform(0.80, 1.30)), 2)
        rate_rows.append([v["vendor_id"], q1, q2, q3, q4])
    with open(os.path.join(workspace, "seasonal_vendor_rates.csv"), "w",
              newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "vendor_id", "q1_multiplier", "q2_multiplier",
            "q3_multiplier", "q4_multiplier",
        ])
        writer.writerows(rate_rows)

    # ── fixed file 3: budget_constraints.json ──
    n = SCALE["rows_per_table"]
    scale_factor = max(1.0, n / 80.0)
    monthly_budget = round(15000.0 * scale_factor, 2)
    max_items = int(50 * scale_factor)
    budget = {
        "monthly_budget": {
            "2026-07": monthly_budget,
            "2026-08": monthly_budget,
            "2026-09": monthly_budget,
        },
        "max_items_per_month": max_items,
    }
    with open(os.path.join(workspace, "budget_constraints.json"), "w") as f:
        json.dump(budget, f, indent=2)

    # ── fixed file 4: category_service_hours.yaml ──
    with open(os.path.join(workspace, "category_service_hours.yaml"), "w") as f:
        yaml.dump(SERVICE_HOURS, f, default_flow_style=False, sort_keys=False)


# ──────────────────────────── main ────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    building_ids = list(range(1, n + 1))
    buildings = generate_buildings(conn, n, num_files)
    vendors = generate_vendors(conn, n)
    appliance_ids = list(range(1, n * 2 + 1))
    appliances = generate_appliances(conn, n * 2, building_ids)
    vendor_ids = list(range(1, n + 1))
    generate_work_orders(conn, n * 3, appliance_ids, vendor_ids)
    generate_tenant_requests(conn, n * 2, building_ids)

    generate_workspace(conn, args.workspace, num_files,
                       buildings, appliances, vendors)

    conn.close()
    print(f"Database written to {args.db_path}")
    print(f"Workspace written to {args.workspace}")
    print(f"  - {num_files} zone inspection files (scalable)")
    print(f"  - 4 fixed config files")
    print(f"  - {n} buildings, {n*2} appliances, {n*3} work orders, "
          f"{n*2} tenant requests, {n} vendors")


if __name__ == "__main__":
    main()
