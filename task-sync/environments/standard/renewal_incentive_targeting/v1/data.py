"""
Data generation script for lease renewal incentive task.
Usage: python data.py --db_path data.db --workspace workspace
"""

import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 16,
}

REFERENCE_DATE = "2026-04-20"

ALL_NEIGHBORHOODS = [
    "Oakwood", "Riverside", "Downtown", "Maple Heights", "Cedar Park",
    "Lakeview", "Hillcrest", "Sunset Valley", "Pine Ridge", "Elm Grove",
    "Brookside", "Fairview", "Meadowbrook", "Stonebridge", "Willow Creek",
    "Ashford", "Brighton", "Clearwater", "Deerfield", "Eastgate",
    "Foxwood", "Glendale", "Harbor Point", "Ivory Hills", "Jefferson Park",
    "Kingston", "Laurel Springs", "Millstone", "Northgate", "Orchard Lane",
    "Pinehurst", "Quail Ridge",
]

PROPERTY_TYPES = ["apartment", "townhouse", "condo", "duplex"]
SEVERITY_LEVELS = ["minor", "moderate", "major", "severe"]
MAINTENANCE_CATEGORIES = [
    "plumbing", "electrical", "hvac", "appliance",
    "structural", "pest_control", "landscaping", "general",
]
BEDROOM_RENT_BASE = {1: 900, 2: 1300, 3: 1700, 4: 2300}
FILE_FORMATS = ["csv", "json", "txt", "md"]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def create_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS properties (
            property_id INTEGER PRIMARY KEY,
            address TEXT,
            neighborhood TEXT,
            bedrooms INTEGER,
            sqft INTEGER,
            property_type TEXT,
            year_built INTEGER
        );
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            property_id INTEGER,
            unit TEXT,
            lease_start_date TEXT,
            lease_end_date TEXT,
            monthly_rent REAL,
            FOREIGN KEY (property_id) REFERENCES properties(property_id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
            due_date TEXT,
            paid_date TEXT,
            amount_due REAL,
            amount_paid REAL,
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
        );
        CREATE TABLE IF NOT EXISTS maintenance_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
            property_id INTEGER,
            request_date TEXT,
            category TEXT,
            description TEXT,
            status TEXT,
            resolved_date TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
            FOREIGN KEY (property_id) REFERENCES properties(property_id)
        );
        CREATE TABLE IF NOT EXISTS damage_incidents (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
            property_id INTEGER,
            incident_date TEXT,
            severity TEXT,
            description TEXT,
            repair_cost REAL,
            tenant_responsible INTEGER,
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
            FOREIGN KEY (property_id) REFERENCES properties(property_id)
        );
    """)


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------

def generate_properties(n, neighborhoods, fake):
    props = []
    for i in range(n):
        props.append({
            "property_id": i + 1,
            "address": fake.street_address(),
            "neighborhood": neighborhoods[i % len(neighborhoods)],
            "bedrooms": int(np.random.choice([1, 2, 3, 4], p=[0.2, 0.4, 0.3, 0.1])),
            "sqft": int(np.random.randint(5, 25)) * 100,
            "property_type": PROPERTY_TYPES[i % len(PROPERTY_TYPES)],
            "year_built": int(np.random.randint(1970, 2024)),
        })
    return props


def generate_tenants(n, properties, ref_date, fake):
    tenants = []
    for i in range(n):
        prop = properties[i % len(properties)]
        lease_months = int(np.random.choice([6, 12, 18, 24]))
        # ~40 % of tenants have leases expiring within 90 days
        if np.random.random() < 0.40:
            lease_end = ref_date + timedelta(days=int(np.random.randint(1, 91)))
        else:
            lease_end = ref_date + timedelta(days=int(np.random.randint(91, 366)))
        lease_start = lease_end - timedelta(days=lease_months * 30)

        base_rent = BEDROOM_RENT_BASE[prop["bedrooms"]]
        monthly_rent = round(base_rent * np.random.uniform(0.85, 1.15), 2)

        tenants.append({
            "tenant_id": i + 1,
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "property_id": prop["property_id"],
            "unit": f"{np.random.randint(1, 10)}{chr(65 + np.random.randint(0, 4))}",
            "lease_start_date": lease_start.strftime("%Y-%m-%d"),
            "lease_end_date": lease_end.strftime("%Y-%m-%d"),
            "monthly_rent": monthly_rent,
        })
    return tenants


def generate_payments(tenants, ref_date):
    payments = []
    for t in tenants:
        lease_start = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
        cur = lease_start.replace(day=1)
        while cur < ref_date:
            delay = int(np.random.choice(
                [0, 0, 0, 1, 2, 3, 5, 7, 10, 15, 20, 30],
                p=[0.35, 0.15, 0.10, 0.08, 0.06, 0.06, 0.05, 0.05, 0.04, 0.03, 0.02, 0.01],
            ))
            payments.append({
                "tenant_id": t["tenant_id"],
                "due_date": cur.strftime("%Y-%m-%d"),
                "paid_date": (cur + timedelta(days=delay)).strftime("%Y-%m-%d"),
                "amount_due": t["monthly_rent"],
                "amount_paid": t["monthly_rent"],
            })
            cur = (cur + timedelta(days=32)).replace(day=1)
    return payments


def generate_maintenance(tenants, ref_date, fake, min_count):
    records = []
    for t in tenants:
        ls = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
        span = (ref_date - ls).days
        if span <= 0:
            continue
        n_req = int(np.random.choice([0, 1, 2, 3, 4, 5], p=[0.10, 0.20, 0.25, 0.20, 0.15, 0.10]))
        for _ in range(n_req):
            rd = ls + timedelta(days=int(np.random.randint(1, max(2, span))))
            resolved = np.random.random() < 0.85
            records.append({
                "tenant_id": t["tenant_id"],
                "property_id": t["property_id"],
                "request_date": rd.strftime("%Y-%m-%d"),
                "category": str(np.random.choice(MAINTENANCE_CATEGORIES)),
                "description": fake.sentence(),
                "status": "resolved" if resolved else str(np.random.choice(["open", "in_progress"])),
                "resolved_date": (rd + timedelta(days=int(np.random.randint(1, 15)))).strftime("%Y-%m-%d") if resolved else None,
            })
    while len(records) < min_count:
        t = tenants[int(np.random.randint(0, len(tenants)))]
        ls = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
        span = (ref_date - ls).days
        if span <= 0:
            continue
        rd = ls + timedelta(days=int(np.random.randint(1, max(2, span))))
        records.append({
            "tenant_id": t["tenant_id"],
            "property_id": t["property_id"],
            "request_date": rd.strftime("%Y-%m-%d"),
            "category": str(np.random.choice(MAINTENANCE_CATEGORIES)),
            "description": fake.sentence(),
            "status": str(np.random.choice(["resolved", "open", "in_progress"])),
            "resolved_date": (rd + timedelta(days=int(np.random.randint(1, 15)))).strftime("%Y-%m-%d"),
        })
    return records


def generate_damage_incidents(tenants, ref_date, fake, min_count):
    incidents = []
    for t in tenants:
        ls = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
        span = (ref_date - ls).days
        if span <= 0:
            continue
        if np.random.random() < 0.65:
            n_inc = int(np.random.choice([1, 2, 3], p=[0.50, 0.35, 0.15]))
            for _ in range(n_inc):
                d = ls + timedelta(days=int(np.random.randint(1, max(2, span))))
                sev = str(np.random.choice(SEVERITY_LEVELS, p=[0.35, 0.30, 0.20, 0.15]))
                base_cost = {"minor": 50, "moderate": 150, "major": 400, "severe": 800}[sev]
                incidents.append({
                    "tenant_id": t["tenant_id"],
                    "property_id": t["property_id"],
                    "incident_date": d.strftime("%Y-%m-%d"),
                    "severity": sev,
                    "description": fake.sentence(),
                    "repair_cost": round(base_cost * np.random.uniform(0.7, 1.5), 2),
                    "tenant_responsible": int(np.random.random() < 0.40),
                })
    while len(incidents) < min_count:
        t = tenants[int(np.random.randint(0, len(tenants)))]
        ls = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
        span = (ref_date - ls).days
        if span <= 0:
            continue
        d = ls + timedelta(days=int(np.random.randint(1, max(2, span))))
        sev = str(np.random.choice(SEVERITY_LEVELS))
        base_cost = {"minor": 50, "moderate": 150, "major": 400, "severe": 800}[sev]
        incidents.append({
            "tenant_id": t["tenant_id"],
            "property_id": t["property_id"],
            "incident_date": d.strftime("%Y-%m-%d"),
            "severity": sev,
            "description": fake.sentence(),
            "repair_cost": round(base_cost * np.random.uniform(0.7, 1.5), 2),
            "tenant_responsible": int(np.random.random() < 0.40),
        })
    return incidents


# ---------------------------------------------------------------------------
# Workspace file writers
# ---------------------------------------------------------------------------

def write_market_csv(path, listings):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "address", "bedrooms", "sqft", "monthly_rent", "property_type", "listed_date"])
        w.writeheader()
        w.writerows(listings)


def write_market_json(path, listings):
    with open(path, "w") as f:
        json.dump(listings, f, indent=2)


def write_market_txt(path, listings):
    cols = ["listing_id", "address", "bedrooms", "sqft", "monthly_rent", "property_type", "listed_date"]
    with open(path, "w") as f:
        f.write(" | ".join(cols) + "\n")
        f.write("-" * 100 + "\n")
        for row in listings:
            f.write(" | ".join(str(row[c]) for c in cols) + "\n")


def write_market_md(path, listings):
    cols = ["listing_id", "address", "bedrooms", "sqft", "monthly_rent", "property_type", "listed_date"]
    with open(path, "w") as f:
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("| " + " | ".join(["---"] * len(cols)) + " |\n")
        for row in listings:
            f.write("| " + " | ".join(str(row[c]) for c in cols) + " |\n")


def generate_market_reports(neighborhoods, workspace, fake):
    """Generate one market-comparable report per neighborhood (scalable files)."""
    premiums = {}
    for nb in neighborhoods:
        premiums[nb] = float(np.random.uniform(0.80, 1.30))

    writers = {
        "csv": write_market_csv,
        "json": write_market_json,
        "txt": write_market_txt,
        "md": write_market_md,
    }

    for i, nb in enumerate(neighborhoods):
        fmt = FILE_FORMATS[i % len(FILE_FORMATS)]
        listings = []
        for bedrooms in [1, 2, 3, 4]:
            n_for_br = int(np.random.randint(2, 5))
            for _ in range(n_for_br):
                base_rent = BEDROOM_RENT_BASE[bedrooms]
                rent = round(base_rent * premiums[nb] * np.random.uniform(0.90, 1.10), 2)
                sqft = int(np.random.randint(3 + bedrooms * 2, 5 + bedrooms * 4)) * 100
                listings.append({
                    "listing_id": f"MKT-{nb[:3].upper()}-{len(listings)+1:03d}",
                    "address": fake.street_address(),
                    "bedrooms": bedrooms,
                    "sqft": sqft,
                    "monthly_rent": rent,
                    "property_type": str(np.random.choice(PROPERTY_TYPES)),
                    "listed_date": (datetime(2026, 1, 1) + timedelta(days=int(np.random.randint(0, 110)))).strftime("%Y-%m-%d"),
                })

        filename = f"market_{nb.lower().replace(' ', '_')}.{fmt}"
        writers[fmt](os.path.join(workspace, filename), listings)


def generate_fixed_workspace_files(workspace):
    """Generate policy / config files that do NOT scale with SCALE."""

    # 1. renewal_policy.yaml
    policy = {
        "reference_date": REFERENCE_DATE,
        "lease_expiry_window_days": 90,
        "eligibility": {
            "min_payment_score": 0.70,
            "max_maintenance_frequency": 8.0,
            "max_damage_cost_weighted": 800.0,
        },
        "scoring": {
            "payment_weight": 0.50,
            "maintenance_weight": 0.25,
            "damage_weight": 0.25,
        },
        "market_adjustment": {
            "rent_above_market_threshold": 1.05,
            "extra_discount_pct": 3,
        },
    }
    with open(os.path.join(workspace, "renewal_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. discount_tiers.csv
    tiers = [
        {"tier": "platinum", "min_score": 0.85, "max_score": 1.00, "discount_pct": 12, "lease_term_months": 24},
        {"tier": "gold", "min_score": 0.70, "max_score": 0.85, "discount_pct": 8, "lease_term_months": 18},
        {"tier": "silver", "min_score": 0.55, "max_score": 0.70, "discount_pct": 5, "lease_term_months": 12},
        {"tier": "bronze", "min_score": 0.00, "max_score": 0.55, "discount_pct": 3, "lease_term_months": 12},
    ]
    with open(os.path.join(workspace, "discount_tiers.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tier", "min_score", "max_score", "discount_pct", "lease_term_months"])
        w.writeheader()
        w.writerows(tiers)

    # 3. severity_weights.json
    weights = {
        "minor": 0.25,
        "moderate": 0.50,
        "major": 0.75,
        "severe": 1.00,
    }
    with open(os.path.join(workspace, "severity_weights.json"), "w") as f:
        json.dump(weights, f, indent=2)


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def insert_properties(cursor, props):
    for p in props:
        cursor.execute(
            "INSERT INTO properties VALUES (?,?,?,?,?,?,?)",
            (p["property_id"], p["address"], p["neighborhood"],
             p["bedrooms"], p["sqft"], p["property_type"], p["year_built"]),
        )


def insert_tenants(cursor, tenants):
    for t in tenants:
        cursor.execute(
            "INSERT INTO tenants VALUES (?,?,?,?,?,?,?,?,?)",
            (t["tenant_id"], t["name"], t["email"], t["phone"],
             t["property_id"], t["unit"], t["lease_start_date"],
             t["lease_end_date"], t["monthly_rent"]),
        )


def insert_payments(cursor, payments):
    for p in payments:
        cursor.execute(
            "INSERT INTO payments (tenant_id, due_date, paid_date, amount_due, amount_paid) VALUES (?,?,?,?,?)",
            (p["tenant_id"], p["due_date"], p["paid_date"], p["amount_due"], p["amount_paid"]),
        )


def insert_maintenance(cursor, records):
    for r in records:
        cursor.execute(
            "INSERT INTO maintenance_requests (tenant_id, property_id, request_date, category, description, status, resolved_date) VALUES (?,?,?,?,?,?,?)",
            (r["tenant_id"], r["property_id"], r["request_date"], r["category"],
             r["description"], r["status"], r["resolved_date"]),
        )


def insert_damage(cursor, incidents):
    for inc in incidents:
        cursor.execute(
            "INSERT INTO damage_incidents (tenant_id, property_id, incident_date, severity, description, repair_cost, tenant_responsible) VALUES (?,?,?,?,?,?,?)",
            (inc["tenant_id"], inc["property_id"], inc["incident_date"], inc["severity"],
             inc["description"], inc["repair_cost"], inc["tenant_responsible"]),
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    ref_date = datetime.strptime(REFERENCE_DATE, "%Y-%m-%d")

    n_tenants = SCALE["rows_per_table"]
    n_properties = SCALE["rows_per_table"]
    n_neighborhoods = SCALE["num_workspace_files"]
    neighborhoods = ALL_NEIGHBORHOODS[:n_neighborhoods]

    # --- generate data ---
    properties = generate_properties(n_properties, neighborhoods, fake)
    tenants = generate_tenants(n_tenants, properties, ref_date, fake)
    payments = generate_payments(tenants, ref_date)
    maint = generate_maintenance(tenants, ref_date, fake, min_count=SCALE["rows_per_table"])
    damage = generate_damage_incidents(tenants, ref_date, fake, min_count=SCALE["rows_per_table"])

    # --- write to database ---
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    create_tables(cur)
    insert_properties(cur, properties)
    insert_tenants(cur, tenants)
    insert_payments(cur, payments)
    insert_maintenance(cur, maint)
    insert_damage(cur, damage)
    conn.commit()
    conn.close()

    # --- workspace: fixed config files ---
    generate_fixed_workspace_files(workspace)

    # --- workspace: scalable market reports ---
    np.random.seed(1042)
    Faker.seed(1042)
    fake2 = Faker()
    generate_market_reports(neighborhoods, workspace, fake2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
