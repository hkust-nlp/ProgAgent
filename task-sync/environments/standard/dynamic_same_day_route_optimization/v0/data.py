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
    "rows_per_table": 50,
    "num_workspace_files": 8,
}

# ── Fixed domain constants ──────────────────────────────────────────────────

ZONE_DEFS = [
    {"zone_id": 1, "name": "Downtown",         "center_lat": 40.7128, "center_lng": -74.0060, "radius_km": 3.0, "type": "urban"},
    {"zone_id": 2, "name": "Midtown",           "center_lat": 40.7549, "center_lng": -73.9840, "radius_km": 2.5, "type": "urban"},
    {"zone_id": 3, "name": "Uptown",            "center_lat": 40.7831, "center_lng": -73.9712, "radius_km": 3.0, "type": "urban"},
    {"zone_id": 4, "name": "Brooklyn Heights",  "center_lat": 40.6782, "center_lng": -73.9442, "radius_km": 5.0, "type": "suburban"},
    {"zone_id": 5, "name": "Astoria",           "center_lat": 40.7282, "center_lng": -73.7949, "radius_km": 4.0, "type": "suburban"},
]

ADJACENCY = {
    1: [2, 4],
    2: [1, 3, 5],
    3: [2, 5],
    4: [1],
    5: [2, 3],
}

VEHICLE_SPECS = {
    "bicycle":     {"capacity_kg": 10,  "max_parcels": 5,  "speed_factor": 0.8},
    "motorcycle":  {"capacity_kg": 25,  "max_parcels": 8,  "speed_factor": 1.2},
    "sedan":       {"capacity_kg": 80,  "max_parcels": 15, "speed_factor": 1.0},
    "van":         {"capacity_kg": 200, "max_parcels": 40, "speed_factor": 0.9},
    "cargo_truck": {"capacity_kg": 500, "max_parcels": 80, "speed_factor": 0.7},
}

VEHICLE_COMPAT = {
    "bicycle":     ["STANDARD"],
    "motorcycle":  ["STANDARD", "FRAGILE"],
    "sedan":       ["STANDARD", "FRAGILE", "COLD_CHAIN"],
    "van":         ["STANDARD", "FRAGILE", "COLD_CHAIN", "HEAVY", "OVERSIZED"],
    "cargo_truck": ["STANDARD", "FRAGILE", "COLD_CHAIN", "HEAVY", "OVERSIZED", "HAZMAT"],
}

HANDLING_CODES   = ["STANDARD", "FRAGILE", "COLD_CHAIN", "HEAVY", "OVERSIZED", "HAZMAT"]
HANDLING_WEIGHTS = [0.40,       0.20,      0.10,         0.15,    0.10,        0.05]

CUSTOMER_TIERS = ["platinum", "gold", "silver", "bronze"]
TIER_WEIGHTS   = [0.10,       0.20,   0.30,     0.40]

PRIORITIES       = ["urgent", "high", "standard", "low"]
PRIORITY_WEIGHTS = [0.10,     0.25,   0.35,       0.30]

SLA_MATRIX = {
    ("platinum", "urgent"):   30,  ("platinum", "high"):   45,
    ("platinum", "standard"): 60,  ("platinum", "low"):    90,
    ("gold",    "urgent"):    45,  ("gold",    "high"):    60,
    ("gold",    "standard"):  90,  ("gold",    "low"):    120,
    ("silver",  "urgent"):    60,  ("silver",  "high"):    90,
    ("silver",  "standard"): 120,  ("silver",  "low"):    180,
    ("bronze",  "urgent"):    90,  ("bronze",  "high"):   120,
    ("bronze",  "standard"): 180,  ("bronze",  "low"):    240,
}

CROSS_ZONE_PENALTY_MINUTES = 5


# ── Data generation helpers ─────────────────────────────────────────────────

def _generate_couriers(n, fake, zone_ids):
    vtype_list    = list(VEHICLE_SPECS.keys())
    vtype_weights = [0.15, 0.25, 0.30, 0.20, 0.10]
    statuses      = ["available", "busy", "offline", "on_break"]
    status_wts    = [0.50, 0.25, 0.15, 0.10]

    rows = []
    for i in range(1, n + 1):
        vtype = np.random.choice(vtype_list, p=vtype_weights)
        specs = VEHICLE_SPECS[vtype]
        zone  = int(np.random.choice(zone_ids))
        zi    = next(z for z in ZONE_DEFS if z["zone_id"] == zone)
        lat   = round(float(zi["center_lat"] + np.random.uniform(-0.02, 0.02)), 6)
        lng   = round(float(zi["center_lng"] + np.random.uniform(-0.02, 0.02)), 6)
        status = np.random.choice(statuses, p=status_wts)

        if status == "busy":
            load_kg = round(float(np.random.uniform(0, specs["capacity_kg"] * 0.7)), 1)
            load_p  = int(np.random.uniform(0, specs["max_parcels"] * 0.5))
        else:
            load_kg = 0.0
            load_p  = 0

        shift_end_h = int(np.random.choice([17, 18, 19, 20, 21, 22]))
        rows.append((
            i, fake.name(), vtype, specs["capacity_kg"], specs["max_parcels"],
            lat, lng, zone, status, load_kg, load_p, f"{shift_end_h}:00"
        ))
    return rows


def _generate_customers(n, fake, zone_ids):
    rows = []
    for i in range(1, n + 1):
        tier = np.random.choice(CUSTOMER_TIERS, p=TIER_WEIGHTS)
        zone = int(np.random.choice(zone_ids))
        rows.append((i, fake.name(), tier, zone, fake.phone_number(), fake.street_address()))
    return rows


def _generate_orders(n, customers, zone_ids):
    statuses   = ["pending", "assigned", "in_transit", "delivered"]
    status_wts = [0.55, 0.15, 0.15, 0.15]
    rows = []
    for i in range(1, n + 1):
        cust_id = int(np.random.randint(1, len(customers) + 1))
        delivery_zone = customers[cust_id - 1][3]          # zone_id col
        pickup_zone   = int(np.random.choice(zone_ids))
        priority = np.random.choice(PRIORITIES, p=PRIORITY_WEIGHTS)
        status   = np.random.choice(statuses, p=status_wts)
        weight   = round(float(np.random.uniform(0.5, 30.0)), 1)
        parcels  = int(np.random.randint(1, 6))
        ws_h     = 13 + int(np.random.randint(0, 5))
        we_h     = ws_h + int(np.random.randint(1, 4))
        oh       = 8 + int(np.random.randint(0, 6))
        om       = int(np.random.randint(0, 60))
        rows.append((
            i, cust_id, pickup_zone, delivery_zone, weight, parcels,
            f"2026-04-19 {oh:02d}:{om:02d}",
            f"2026-04-19 {ws_h}:00",
            f"2026-04-19 {we_h}:00",
            priority, status,
        ))
    return rows


def _generate_traffic(n, zone_ids):
    """Generate traffic segments; pad with alternate routes to reach *n* rows."""
    rows = []
    seg = 1
    for fz in zone_ids:
        for tz in zone_ids:
            if fz == tz:
                bt = round(float(np.random.uniform(5, 15)), 1)
                d  = round(float(np.random.uniform(1, 5)), 1)
            elif tz in ADJACENCY.get(fz, []):
                bt = round(float(np.random.uniform(10, 25)), 1)
                d  = round(float(np.random.uniform(3, 10)), 1)
            else:
                bt = round(float(np.random.uniform(20, 45)), 1)
                d  = round(float(np.random.uniform(8, 20)), 1)
            cf = round(float(np.random.uniform(1.0, 2.5)), 2)
            rows.append((seg, fz, tz, "primary", d, bt, cf))
            seg += 1

    # pad with alternates
    while len(rows) < n:
        fz = int(np.random.choice(zone_ids))
        tz = int(np.random.choice(zone_ids))
        base = next(r for r in rows if r[1] == fz and r[2] == tz)
        vn   = sum(1 for r in rows if r[1] == fz and r[2] == tz)
        rows.append((
            seg, fz, tz, f"alternate_{vn}",
            round(float(base[4] * np.random.uniform(0.8, 1.3)), 1),
            round(float(base[5] * np.random.uniform(0.9, 1.2)), 1),
            round(float(np.random.uniform(1.0, 2.5)), 2),
        ))
        seg += 1
    return rows


# ── Workspace file generators ───────────────────────────────────────────────

def _write_zone_definitions(workspace):
    data = {
        "zones": ZONE_DEFS,
        "adjacency": {str(k): v for k, v in ADJACENCY.items()},
        "cross_zone_penalty_minutes": CROSS_ZONE_PENALTY_MINUTES,
    }
    with open(os.path.join(workspace, "zone_definitions.json"), "w") as f:
        json.dump(data, f, indent=2)


def _write_vehicle_compatibility(workspace):
    data = {
        "vehicle_compatibility": VEHICLE_COMPAT,
        "vehicle_specs": {k: dict(v) for k, v in VEHICLE_SPECS.items()},
    }
    with open(os.path.join(workspace, "vehicle_compatibility.yaml"), "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _write_sla_thresholds(workspace):
    with open(os.path.join(workspace, "sla_thresholds.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "priority", "max_delivery_minutes"])
        for (tier, prio), mins in sorted(SLA_MATRIX.items()):
            w.writerow([tier, prio, mins])


def _write_dispatch_policy(workspace):
    text = (
        "When generating the fifteen-minute assignment manifest, orders must be "
        "processed in descending urgency. Urgent orders take absolute precedence, "
        "followed by high-priority, then standard, and finally low-priority orders. "
        "Among orders at the same priority level, those whose delivery window opens "
        "earliest are handled first. If two orders share both priority and window "
        "start time, the one with the smaller order identifier is processed first.\n\n"
        "For each order the dispatcher should first look for a courier stationed in "
        "the same zone as the order's delivery destination. If no suitable same-zone "
        "courier is available — whether due to vehicle incompatibility, exhausted "
        "capacity, or simply no couriers present — the search expands to couriers in "
        "adjacent zones as defined in the zone adjacency configuration. Couriers from "
        "non-adjacent zones may only be considered when no same-zone or adjacent-zone "
        "courier can fulfill the order.\n\n"
        "When two or more couriers in the same preference tier qualify for an order, "
        "the courier with the greatest remaining weight capacity must be selected. "
        "This rule preserves couriers with tighter margins for smaller subsequent "
        "orders.\n\n"
        "A single courier may receive multiple order assignments within one manifest "
        "cycle provided the cumulative weight of all newly assigned orders plus the "
        "courier's existing on-board load does not exceed the vehicle's weight limit, "
        "and the cumulative parcel count plus current parcels stays within the "
        "vehicle's parcel capacity.\n\n"
        "If no courier in the entire fleet can serve a particular order — whether due "
        "to vehicle-handling incompatibility, exhausted capacity across all compatible "
        "vehicles, or any other constraint — that order must still appear in the "
        "manifest. Set its courier identifier to negative one and the courier name to "
        "UNASSIGNED, with the estimated delivery time also recorded as negative one. "
        "The SLA deadline column should still reflect the correct threshold for that "
        "order based on its customer tier and priority.\n\n"
        "Estimated delivery time for each assignment is computed as the current "
        "traffic-adjusted travel time from the courier's zone to the delivery zone, "
        "divided by the courier's vehicle speed factor, plus any cross-zone time "
        "penalty when the courier and delivery destination are in different zones. "
        "All estimated times are rounded to one decimal place."
    )
    with open(os.path.join(workspace, "dispatch_policy.md"), "w") as f:
        f.write(text)


def _write_order_handling_batches(workspace, order_rows, n_files):
    """Split handling details across *n_files* CSV batch files."""
    instructions_pool = [
        "", "", "", "", "",
        "Leave at front door",
        "Ring doorbell twice",
        "Call before delivery",
        "Deliver to back entrance",
        "Handle with care",
        "Keep upright",
        "Time-sensitive contents",
    ]
    pkg_map = {
        "STANDARD":   "box",
        "FRAGILE":    "cushioned_box",
        "COLD_CHAIN": "insulated_container",
        "HEAVY":      "reinforced_crate",
        "OVERSIZED":  "pallet",
        "HAZMAT":     "hazmat_container",
    }

    all_records = []
    for row in order_rows:
        oid      = row[0]
        priority = row[9]
        hcode    = np.random.choice(HANDLING_CODES, p=HANDLING_WEIGHTS)
        all_records.append({
            "order_id":             oid,
            "handling_code":        hcode,
            "package_type":         pkg_map[hcode],
            "fragile":              hcode in ("FRAGILE", "COLD_CHAIN"),
            "signature_required":   priority in ("urgent", "high"),
            "special_instructions": random.choice(instructions_pool),
        })

    # distribute evenly
    batch_size = len(all_records) // n_files
    remainder  = len(all_records) % n_files
    idx = 0
    fieldnames = ["order_id", "handling_code", "package_type",
                  "fragile", "signature_required", "special_instructions"]
    for i in range(n_files):
        sz    = batch_size + (1 if i < remainder else 0)
        batch = all_records[idx:idx + sz]
        idx  += sz
        path  = os.path.join(workspace, f"order_handling_batch_{i + 1:03d}.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(batch)


# ── Main ────────────────────────────────────────────────────────────────────

def main(db_path, workspace):
    Faker.seed(42)
    fake = Faker()
    np.random.seed(42)
    random.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]
    zone_ids = [z["zone_id"] for z in ZONE_DEFS]

    # Generate data
    couriers  = _generate_couriers(n_rows, fake, zone_ids)
    customers = _generate_customers(n_rows, fake, zone_ids)
    orders    = _generate_orders(n_rows, customers, zone_ids)
    traffic   = _generate_traffic(n_rows, zone_ids)

    # ── Create database ────────────────────────────────────────────────────
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE couriers (
        courier_id      INTEGER PRIMARY KEY,
        name            TEXT,
        vehicle_type    TEXT,
        capacity_kg     REAL,
        max_parcels     INTEGER,
        current_lat     REAL,
        current_lng     REAL,
        zone_id         INTEGER,
        status          TEXT,
        current_load_kg REAL,
        current_parcels INTEGER,
        shift_end       TEXT
    )""")

    c.execute("""CREATE TABLE customers (
        customer_id INTEGER PRIMARY KEY,
        name        TEXT,
        tier        TEXT,
        zone_id     INTEGER,
        phone       TEXT,
        address     TEXT
    )""")

    c.execute("""CREATE TABLE orders (
        order_id        INTEGER PRIMARY KEY,
        customer_id     INTEGER REFERENCES customers(customer_id),
        pickup_zone_id  INTEGER,
        delivery_zone_id INTEGER,
        weight_kg       REAL,
        parcel_count    INTEGER,
        order_placed    TEXT,
        window_start    TEXT,
        window_end      TEXT,
        priority        TEXT,
        status          TEXT
    )""")

    c.execute("""CREATE TABLE traffic_segments (
        segment_id      INTEGER PRIMARY KEY,
        from_zone_id    INTEGER,
        to_zone_id      INTEGER,
        route_name      TEXT,
        distance_km     REAL,
        base_time_min   REAL,
        congestion_factor REAL
    )""")

    c.executemany("INSERT INTO couriers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", couriers)
    c.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
    c.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?)", orders)
    c.executemany("INSERT INTO traffic_segments VALUES (?,?,?,?,?,?,?)", traffic)

    conn.commit()
    conn.close()

    # ── Generate workspace files ───────────────────────────────────────────
    _write_zone_definitions(workspace)
    _write_vehicle_compatibility(workspace)
    _write_sla_thresholds(workspace)
    _write_dispatch_policy(workspace)
    _write_order_handling_batches(workspace, orders, n_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
