#!/usr/bin/env python3
"""Data generation for packaging material needs forecasting task."""
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
    "rows_per_table": 80,
    "num_workspace_files": 24,
}

SEED = 42
PLAN_TYPES = ["basic", "standard", "premium", "deluxe", "enterprise"]
REGIONS = ["northeast", "southeast", "midwest", "west", "southwest"]
MATERIAL_CATEGORIES = [
    "corrugated", "cushioning", "sealing", "labeling",
    "insert", "wrapping", "filler",
]
SIZE_CATEGORIES = ["small", "medium", "large", "extra-large"]

MATERIAL_BASES = {
    "corrugated": [
        "Shipping Box", "Mailer Box", "Corrugated Pad",
        "Corrugated Divider", "Corrugated Tray",
    ],
    "cushioning": [
        "Bubble Wrap Roll", "Foam Sheet Pack", "Air Pillow Set",
        "Foam Insert", "Padded Liner",
    ],
    "sealing": [
        "Packing Tape Roll", "Kraft Tape Roll", "Security Seal Kit",
        "Box Staple Pack", "Adhesive Strip Roll",
    ],
    "labeling": [
        "Shipping Label Sheet", "Barcode Sticker Roll", "Brand Label Pack",
        "Warning Label Set", "Return Label Pad",
    ],
    "insert": [
        "Thank-You Card Pack", "Product Guide Set", "Coupon Insert Bundle",
        "Feedback Card Pack", "Promo Flyer Set",
    ],
    "wrapping": [
        "Tissue Paper Pack", "Shrink Film Roll", "Stretch Wrap Roll",
        "Kraft Paper Roll", "Gift Wrap Sheet",
    ],
    "filler": [
        "Packing Peanuts Bag", "Crinkle Paper Bundle", "Void Fill Pack",
        "Paper Cushion Set", "Cornstarch Fill Box",
    ],
}
GRADES = ["Standard", "Premium", "Heavy-Duty", "Economy", "Compact", "Deluxe"]
UNITS_BY_CAT = {
    "corrugated": "piece", "cushioning": "roll", "sealing": "roll",
    "labeling": "sheet", "insert": "piece", "wrapping": "roll", "filler": "bag",
}


def _generate_material_pool():
    pool = []
    for cat in MATERIAL_CATEGORIES:
        for base in MATERIAL_BASES[cat]:
            for grade in GRADES:
                pool.append((f"{grade} {base}", cat, UNITS_BY_CAT[cat]))
    return pool


def create_database(db_path):
    fake = Faker()
    rows_per_table = SCALE["rows_per_table"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── 1. subscribers ───────────────────────────────────────────────
    num_subscribers = 3 * rows_per_table
    cur.execute("""
        CREATE TABLE subscribers (
            subscriber_id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            plan_type TEXT,
            region TEXT,
            status TEXT,
            start_date TEXT,
            monthly_spend REAL
        )
    """)
    for i in range(num_subscribers):
        name = fake.name()
        email = fake.email()
        plan_type = PLAN_TYPES[i % len(PLAN_TYPES)]
        region = REGIONS[i % len(REGIONS)]
        status = random.choices(
            ["active", "paused", "cancelled"], weights=[75, 15, 10], k=1
        )[0]
        start_date = fake.date_between(start_date="-3y", end_date="-1m").isoformat()
        monthly_spend = round(random.uniform(15, 120), 2)
        cur.execute(
            "INSERT INTO subscribers VALUES (?,?,?,?,?,?,?,?)",
            (i + 1, name, email, plan_type, region, status, start_date, monthly_spend),
        )

    # ── 2. materials ─────────────────────────────────────────────────
    num_materials = rows_per_table
    pool = _generate_material_pool()
    random.shuffle(pool)
    pool = pool[:num_materials]

    cur.execute("""
        CREATE TABLE materials (
            material_id INTEGER PRIMARY KEY,
            name TEXT,
            category TEXT,
            unit TEXT,
            unit_cost REAL,
            shelf_life_days INTEGER
        )
    """)
    material_costs = {}
    for i, (mname, cat, unit) in enumerate(pool):
        mid = i + 1
        unit_cost = round(random.uniform(0.50, 25.00), 2)
        shelf_life_days = random.choice([90, 180, 365, 730])
        material_costs[mid] = unit_cost
        cur.execute(
            "INSERT INTO materials VALUES (?,?,?,?,?,?)",
            (mid, mname, cat, unit, unit_cost, shelf_life_days),
        )

    # ── 3. suppliers ─────────────────────────────────────────────────
    num_suppliers = rows_per_table
    cur.execute("""
        CREATE TABLE suppliers (
            supplier_id INTEGER PRIMARY KEY,
            company_name TEXT,
            contact_email TEXT,
            region TEXT,
            reliability_score REAL,
            is_active INTEGER
        )
    """)
    supplier_ids = []
    for i in range(num_suppliers):
        sid = i + 1
        supplier_ids.append(sid)
        company_name = fake.company()
        contact_email = fake.company_email()
        region = REGIONS[i % len(REGIONS)]
        reliability_score = round(random.uniform(50, 100), 1)
        is_active = 1 if random.random() < 0.85 else 0
        cur.execute(
            "INSERT INTO suppliers VALUES (?,?,?,?,?,?)",
            (sid, company_name, contact_email, region, reliability_score, is_active),
        )

    # ── 4. supplier_materials ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE supplier_materials (
            id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            material_id INTEGER,
            lead_time_days INTEGER,
            min_order_qty INTEGER,
            price_per_unit REAL,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
            FOREIGN KEY (material_id) REFERENCES materials(material_id)
        )
    """)
    sm_id = 0
    sm_rows = []
    for mid in range(1, num_materials + 1):
        n_suppliers = random.randint(2, 4)
        chosen = random.sample(supplier_ids, n_suppliers)
        for sid in chosen:
            sm_id += 1
            lead_time = random.randint(7, 35)
            moq = random.choice([50, 100, 200, 500])
            ppu = round(material_costs[mid] * random.uniform(0.8, 1.3), 2)
            sm_rows.append((sm_id, sid, mid, lead_time, moq, ppu))
    # Pad if needed
    while len(sm_rows) < rows_per_table:
        sm_id += 1
        mid = random.randint(1, num_materials)
        sid = random.choice(supplier_ids)
        lead_time = random.randint(7, 35)
        moq = random.choice([50, 100, 200, 500])
        ppu = round(material_costs[mid] * random.uniform(0.8, 1.3), 2)
        sm_rows.append((sm_id, sid, mid, lead_time, moq, ppu))
    for row in sm_rows:
        cur.execute("INSERT INTO supplier_materials VALUES (?,?,?,?,?,?)", row)

    # ── 5. inventory ─────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY,
            material_id INTEGER,
            warehouse TEXT,
            quantity_on_hand INTEGER,
            reserved_quantity INTEGER,
            last_updated TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(material_id)
        )
    """)
    for i in range(num_materials):
        mid = i + 1
        warehouse = "Warehouse-A" if i % 2 == 0 else "Warehouse-B"
        qty_on_hand = random.randint(100, 5000)
        reserved_qty = random.randint(0, qty_on_hand // 4)
        last_updated = fake.date_between(start_date="-30d", end_date="today").isoformat()
        cur.execute(
            "INSERT INTO inventory VALUES (?,?,?,?,?,?)",
            (i + 1, mid, warehouse, qty_on_hand, reserved_qty, last_updated),
        )

    # ── 6. box_types ─────────────────────────────────────────────────
    num_box_types = rows_per_table
    combos = [(p, s) for p in PLAN_TYPES for s in SIZE_CATEGORIES]
    random.shuffle(combos)

    cur.execute("""
        CREATE TABLE box_types (
            box_type_id INTEGER PRIMARY KEY,
            name TEXT,
            plan_type TEXT,
            size_category TEXT
        )
    """)
    for i in range(num_box_types):
        idx = i % len(combos)
        plan, size = combos[idx]
        version_round = i // len(combos)
        bt_name = f"{plan.capitalize()} {size.capitalize()} Box"
        if version_round > 0:
            bt_name += f" V{version_round + 1}"
        cur.execute(
            "INSERT INTO box_types VALUES (?,?,?,?)",
            (i + 1, bt_name, plan, size),
        )

    # ── 7. assembly_bom ──────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE assembly_bom (
            id INTEGER PRIMARY KEY,
            box_type_id INTEGER,
            material_id INTEGER,
            quantity_per_box INTEGER,
            FOREIGN KEY (box_type_id) REFERENCES box_types(box_type_id),
            FOREIGN KEY (material_id) REFERENCES materials(material_id)
        )
    """)
    bom_id = 0
    material_id_list = list(range(1, num_materials + 1))
    for bt_id in range(1, num_box_types + 1):
        n_mats = random.randint(3, 6)
        chosen_mats = random.sample(material_id_list, n_mats)
        for mid in chosen_mats:
            bom_id += 1
            qty = random.randint(1, 8)
            cur.execute(
                "INSERT INTO assembly_bom VALUES (?,?,?,?)",
                (bom_id, bt_id, mid, qty),
            )

    # ── 8. assembly_schedule ─────────────────────────────────────────
    num_schedule = 2 * rows_per_table
    # Weekly Mondays in Q3 2026 (July 1 - Sep 30)
    from datetime import date, timedelta

    q3_start = date(2026, 7, 1)
    q3_end = date(2026, 9, 30)
    mondays = []
    d = q3_start
    while d <= q3_end:
        if d.weekday() == 0:  # Monday
            mondays.append(d)
        d += timedelta(days=1)

    cur.execute("""
        CREATE TABLE assembly_schedule (
            id INTEGER PRIMARY KEY,
            box_type_id INTEGER,
            scheduled_date TEXT,
            planned_quantity INTEGER,
            status TEXT,
            FOREIGN KEY (box_type_id) REFERENCES box_types(box_type_id)
        )
    """)
    for i in range(num_schedule):
        bt_id = random.randint(1, num_box_types)
        sched_date = random.choice(mondays).isoformat()
        planned_qty = random.randint(50, 500)
        status = random.choices(
            ["confirmed", "tentative"], weights=[80, 20], k=1
        )[0]
        cur.execute(
            "INSERT INTO assembly_schedule VALUES (?,?,?,?,?)",
            (i + 1, bt_id, sched_date, planned_qty, status),
        )

    conn.commit()
    conn.close()


def create_workspace(db_path, workspace_dir):
    os.makedirs(workspace_dir, exist_ok=True)

    nf = SCALE["num_workspace_files"]
    n_forecast = math.ceil(nf / 3)
    n_supplier = math.ceil((nf - n_forecast) / 2)
    n_inventory = nf - n_forecast - n_supplier

    conn = sqlite3.connect(db_path)

    # ── Forecast CSVs ────────────────────────────────────────────────
    all_combos = [(r, p) for r in REGIONS for p in PLAN_TYPES]  # 25 combos
    forecast_buckets = [[] for _ in range(n_forecast)]
    for idx, (region, plan) in enumerate(all_combos):
        growth_rate = round(random.uniform(2.0, 18.0), 1)
        forecast_buckets[idx % n_forecast].append(
            {"region": region, "plan_type": plan, "growth_rate_pct": growth_rate}
        )
    for i, bucket in enumerate(forecast_buckets):
        df = pd.DataFrame(bucket)
        df.to_csv(os.path.join(workspace_dir, f"growth_forecast_{i}.csv"), index=False)

    # ── Supplier term JSONs ──────────────────────────────────────────
    supplier_ids = [
        row[0]
        for row in conn.execute(
            "SELECT supplier_id FROM suppliers ORDER BY supplier_id"
        ).fetchall()
    ]
    supplier_buckets = [[] for _ in range(n_supplier)]
    for idx, sid in enumerate(supplier_ids):
        discount = round(random.uniform(0, 15), 1)
        terms = random.choice(["net-30", "net-45", "net-60", "prepaid"])
        supplier_buckets[idx % n_supplier].append(
            {"supplier_id": sid, "discount_pct": discount, "payment_terms": terms}
        )
    for i, bucket in enumerate(supplier_buckets):
        with open(os.path.join(workspace_dir, f"supplier_terms_{i}.json"), "w") as f:
            json.dump(bucket, f, indent=2)

    # ── Inventory adjustment YAMLs ───────────────────────────────────
    material_ids = [
        row[0]
        for row in conn.execute(
            "SELECT material_id FROM materials ORDER BY material_id"
        ).fetchall()
    ]
    inv_buckets = [[] for _ in range(n_inventory)]
    for idx, mid in enumerate(material_ids):
        damaged = random.randint(0, 50)
        expired = random.randint(0, 30)
        inv_buckets[idx % n_inventory].append(
            {
                "material_id": mid,
                "damaged_qty": damaged,
                "expired_qty": expired,
                "inspection_date": "2026-04-15",
            }
        )
    for i, bucket in enumerate(inv_buckets):
        data = {"adjustments": bucket}
        with open(
            os.path.join(workspace_dir, f"inventory_adjustment_{i}.yaml"), "w"
        ) as f:
            yaml.dump(data, f, default_flow_style=False)

    conn.close()

    # ── Fixed files ──────────────────────────────────────────────────
    # 1. procurement_policy.yaml
    policy = {
        "safety_stock_percentage": 15,
        "standard_buffer_days": 7,
        "priority_buffer_days": 14,
        "supplier_selection": {
            "min_reliability_score": 70,
            "preference": "lowest_effective_cost",
            "tiebreak": "shortest_lead_time",
        },
        "assembly_filter": "confirmed",
        "order_rounding": "round_up_to_moq",
    }
    with open(os.path.join(workspace_dir, "procurement_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False)

    # 2. quarter_config.json
    qconfig = {
        "current_date": "2026-04-21",
        "next_quarter": {
            "start": "2026-07-01",
            "end": "2026-09-30",
            "label": "Q3 2026",
        },
    }
    with open(os.path.join(workspace_dir, "quarter_config.json"), "w") as f:
        json.dump(qconfig, f, indent=2)

    # 3. material_priority_rules.md
    rules = """# Material Priority Classification

Materials in the following categories are classified as priority and require extended lead-time buffers when ordering:

- corrugated
- cushioning

All other material categories (sealing, labeling, insert, wrapping, filler) are classified as standard.

Priority materials use the priority_buffer_days value from the procurement policy, while standard materials use standard_buffer_days.
"""
    with open(os.path.join(workspace_dir, "material_priority_rules.md"), "w") as f:
        f.write(rules)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)

    create_database(args.db_path)
    create_workspace(args.db_path, args.workspace)


if __name__ == "__main__":
    main()
