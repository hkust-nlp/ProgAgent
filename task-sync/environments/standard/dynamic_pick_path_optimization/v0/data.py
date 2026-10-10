"""Warehouse pick-path optimization task -- data generation."""

import argparse
import csv
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 50,       # v0 base; v1 = 2x, v2 = 4x, v3 = 8x
    "num_workspace_files": 8,   # v0 base; v1 = +N, v2 = +2N, v3 = +3N  (N = base)
}


def main(db_path: str, workspace: str) -> None:
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ── ZONES ─────────────────────────────────────────────────────────
    grid_cols = max(10, int(np.ceil(np.sqrt(n))))
    zones = []
    for i in range(n):
        col = i % grid_cols
        row_idx = i // grid_cols
        zones.append((
            f"Z{i + 1:03d}",
            f"Aisle-{col + 1}-Sec-{row_idx + 1}",
            col + 1,
            row_idx + 1,
            round(col * 5.0, 1),
            round(row_idx * 8.0, 1),
        ))

    c.execute("""CREATE TABLE zones (
        zone_id      TEXT PRIMARY KEY,
        zone_name    TEXT,
        aisle        INTEGER,
        section      INTEGER,
        x_coord      REAL,
        y_coord      REAL
    )""")
    c.executemany("INSERT INTO zones VALUES (?,?,?,?,?,?)", zones)

    # ── SKUS ──────────────────────────────────────────────────────────
    categories = [
        "electronics", "grocery", "clothing", "hardware",
        "household", "toys", "sports", "pharmacy",
    ]
    skus = []
    for i in range(n):
        skus.append((
            f"SKU{i + 1:04d}",
            fake.word().capitalize() + " " + fake.word().capitalize(),
            categories[i % len(categories)],
            round(float(np.random.uniform(0.1, 10.0)), 2),
            round(float(np.random.uniform(0.05, 6.0)), 2),
            zones[i % len(zones)][0],
            f"S{np.random.randint(1, 21):02d}",
            int(np.random.random() < 0.15),
        ))

    c.execute("""CREATE TABLE skus (
        sku_id         TEXT PRIMARY KEY,
        sku_name       TEXT,
        category       TEXT,
        weight_kg      REAL,
        volume_liters  REAL,
        zone_id        TEXT,
        shelf_position TEXT,
        is_fragile     INTEGER,
        FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
    )""")
    c.executemany("INSERT INTO skus VALUES (?,?,?,?,?,?,?,?)", skus)

    # ── ORDERS ────────────────────────────────────────────────────────
    priorities = ["standard", "express", "urgent"]
    n_pending = int(n * 0.4)
    n_inprogress = int(n * 0.3)
    orders = []
    for i in range(n):
        if i < n_pending:
            status = "pending"
        elif i < n_pending + n_inprogress:
            status = "in_progress"
        else:
            status = "completed"
        orders.append((
            f"ORD{i + 1:04d}",
            f"CUST{np.random.randint(1, 200):04d}",
            fake.date_between(start_date="-7d", end_date="today").isoformat(),
            str(np.random.choice(priorities, p=[0.5, 0.3, 0.2])),
            status,
        ))

    c.execute("""CREATE TABLE orders (
        order_id    TEXT PRIMARY KEY,
        customer_id TEXT,
        order_date  TEXT,
        priority    TEXT,
        status      TEXT
    )""")
    c.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", orders)

    # ── ORDER_ITEMS ───────────────────────────────────────────────────
    order_items = []
    item_id = 1
    for order in orders:
        n_items = int(np.random.randint(2, 5))
        chosen = np.random.choice(len(skus), size=min(n_items, len(skus)), replace=False)
        for si in chosen:
            order_items.append((
                item_id,
                order[0],
                skus[int(si)][0],
                int(np.random.randint(1, 4)),
            ))
            item_id += 1

    c.execute("""CREATE TABLE order_items (
        item_id   INTEGER PRIMARY KEY,
        order_id  TEXT,
        sku_id    TEXT,
        quantity  INTEGER,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (sku_id)   REFERENCES skus(sku_id)
    )""")
    c.executemany("INSERT INTO order_items VALUES (?,?,?,?)", order_items)

    # ── PICKERS ───────────────────────────────────────────────────────
    shift_labels = ["morning", "afternoon", "night"]
    pickers = []
    for i in range(n):
        shift = shift_labels[i % 3]
        is_active = 1 if (i % 7 == 0) else 0
        pickers.append((
            f"P{i + 1:03d}",
            fake.name(),
            shift,
            round(float(np.random.uniform(100, 200)), 1),
            round(float(np.random.uniform(120, 250)), 1),
            zones[int(np.random.randint(0, len(zones)))][0],
            is_active,
        ))

    c.execute("""CREATE TABLE pickers (
        picker_id       TEXT PRIMARY KEY,
        name            TEXT,
        shift           TEXT,
        max_weight_kg   REAL,
        max_volume_liters REAL,
        current_zone_id TEXT,
        is_active       INTEGER,
        FOREIGN KEY (current_zone_id) REFERENCES zones(zone_id)
    )""")
    c.executemany("INSERT INTO pickers VALUES (?,?,?,?,?,?,?)", pickers)

    conn.commit()
    conn.close()

    # ── WORKSPACE: Fixed configuration files ──────────────────────────

    # zone_map.json  (coordinates + names only)
    zone_map = {}
    for z in zones:
        zone_map[z[0]] = {"zone_name": z[1], "x_coord": z[4], "y_coord": z[5]}
    with open(os.path.join(workspace, "zone_map.json"), "w") as f:
        json.dump(zone_map, f, indent=2)

    # picking_policy.yaml
    policy = {
        "max_batch_weight_kg": 150.0,
        "max_batch_volume_liters": 180.0,
        "max_items_per_batch": 40,
        "priority_order": ["urgent", "express", "standard"],
        "assignment_rule": "most_remaining_weight_capacity",
        "assignment_tie_break": "picker_id_ascending",
        "route_method": "nearest_neighbor_manhattan",
        "route_start": "picker_current_zone",
        "route_tie_break": "zone_id_ascending",
    }
    with open(os.path.join(workspace, "picking_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # picker_certifications.csv
    cert_rows = []
    for p in pickers:
        cert_rows.append([
            p[0],
            int(np.random.random() < 0.4),
            int(np.random.random() < 0.3),
        ])
    with open(os.path.join(workspace, "picker_certifications.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["picker_id", "cold_chain_certified", "hazmat_certified"])
        w.writerows(cert_rows)

    # cart_specifications.yaml
    cart = {
        "cart_type": "standard_warehouse",
        "num_shelves": 3,
        "per_shelf_weight_limit_kg": 50.0,
        "total_weight_limit_kg": 150.0,
        "total_volume_limit_liters": 200.0,
    }
    with open(os.path.join(workspace, "cart_specifications.yaml"), "w") as f:
        yaml.dump(cart, f, default_flow_style=False, sort_keys=False)

    # ── WORKSPACE: Scalable order-batch manifest files ────────────────
    handling_types = ["none", "fragile", "cold_chain", "hazmat"]
    time_windows = ["06:00-09:00", "09:00-12:00", "12:00-15:00", "15:00-18:00"]

    order_manifest = []
    for o in orders:
        h = str(np.random.choice(handling_types, p=[0.50, 0.20, 0.15, 0.15]))
        tw = str(np.random.choice(time_windows))
        notes = ""
        if h == "fragile":
            notes = "Handle with care, do not stack heavy items on top"
        elif h == "cold_chain":
            notes = "Keep below 4C during transit, use insulated container"
        elif h == "hazmat":
            notes = "Follow hazmat handling protocol, certified personnel only"
        order_manifest.append([o[0], tw, h, notes])

    per_file = len(order_manifest) // n_files
    remainder = len(order_manifest) % n_files
    idx = 0
    for fi in range(n_files):
        count = per_file + (1 if fi < remainder else 0)
        batch = order_manifest[idx:idx + count]
        idx += count
        with open(os.path.join(workspace, f"order_batch_{fi + 1:03d}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["order_id", "time_window", "special_handling", "handling_notes"])
            w.writerows(batch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
