"""
Warehouse replenishment optimization - data generation script.
Generates SQLite database and workspace files for pick-face stock analysis,
order-picking rates, dock schedules, and forklift telemetry.
"""

import argparse
import json
import math
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker
import yaml

# ── Scale parameters (v0 base) ──────────────────────────────────────
SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 20,
}

SEED = 42

# ── Structural constants (do not scale) ─────────────────────────────
NUM_ZONES = 8
NUM_FORKLIFTS = 16  # 2 per zone

ZONE_DEFS = [
    {"zone_id": "Z01", "zone_name": "Dry Goods A",            "zone_type": "ambient", "num_aisles": 6, "travel_factor": 1.00, "congestion_factor": 1.15},
    {"zone_id": "Z02", "zone_name": "Dry Goods B",            "zone_type": "ambient", "num_aisles": 5, "travel_factor": 1.10, "congestion_factor": 1.08},
    {"zone_id": "Z03", "zone_name": "Beverages",              "zone_type": "ambient", "num_aisles": 4, "travel_factor": 1.20, "congestion_factor": 1.22},
    {"zone_id": "Z04", "zone_name": "Snacks & Confectionery", "zone_type": "ambient", "num_aisles": 5, "travel_factor": 0.90, "congestion_factor": 1.05},
    {"zone_id": "Z05", "zone_name": "Chilled Dairy",          "zone_type": "chilled", "num_aisles": 3, "travel_factor": 1.30, "congestion_factor": 1.30},
    {"zone_id": "Z06", "zone_name": "Chilled Produce",        "zone_type": "chilled", "num_aisles": 3, "travel_factor": 1.40, "congestion_factor": 1.18},
    {"zone_id": "Z07", "zone_name": "Frozen Foods",           "zone_type": "frozen",  "num_aisles": 4, "travel_factor": 1.50, "congestion_factor": 1.35},
    {"zone_id": "Z08", "zone_name": "Frozen Speciality",      "zone_type": "frozen",  "num_aisles": 2, "travel_factor": 1.60, "congestion_factor": 1.40},
]

AMBIENT_CATEGORIES = ["Dry Goods", "Beverages", "Snacks", "Condiments", "Bakery", "Household"]
CHILLED_CATEGORIES = ["Dairy", "Produce", "Deli"]
FROZEN_CATEGORIES  = ["Frozen Meals", "Frozen Desserts", "Ice Cream"]
ALL_CATEGORIES = AMBIENT_CATEGORIES + CHILLED_CATEGORIES + FROZEN_CATEGORIES

CARRIERS = ["FastFreight", "ColdChain Express", "BulkHaul", "PrimeLogistics", "FreshLine"]


# ── Helpers ──────────────────────────────────────────────────────────

def _storage_type_for_category(cat: str) -> str:
    if cat in CHILLED_CATEGORIES:
        return "chilled"
    if cat in FROZEN_CATEGORIES:
        return "frozen"
    return "ambient"


def _zone_for_storage(storage_type: str, rng: random.Random) -> str:
    if storage_type == "ambient":
        return rng.choice(["Z01", "Z02", "Z03", "Z04"])
    if storage_type == "chilled":
        return rng.choice(["Z05", "Z06"])
    return rng.choice(["Z07", "Z08"])


# ── Table creation ───────────────────────────────────────────────────

def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sku_master (
            sku_id             TEXT PRIMARY KEY,
            sku_name           TEXT NOT NULL,
            category           TEXT NOT NULL,
            case_pack_qty      INTEGER NOT NULL,
            weight_per_case_kg REAL NOT NULL,
            storage_type       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pick_faces (
            pick_face_id    TEXT PRIMARY KEY,
            sku_id          TEXT NOT NULL,
            zone_id         TEXT NOT NULL,
            aisle           TEXT NOT NULL,
            position        INTEGER NOT NULL,
            current_qty     INTEGER NOT NULL,
            max_capacity    INTEGER NOT NULL,
            last_replenished TEXT NOT NULL,
            FOREIGN KEY (sku_id) REFERENCES sku_master(sku_id)
        );
        CREATE TABLE IF NOT EXISTS picking_rates (
            rate_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sku_id             TEXT NOT NULL,
            avg_units_per_hour REAL NOT NULL,
            peak_rate          REAL NOT NULL,
            off_peak_rate      REAL NOT NULL,
            FOREIGN KEY (sku_id) REFERENCES sku_master(sku_id)
        );
        CREATE TABLE IF NOT EXISTS dock_schedules (
            schedule_id    TEXT PRIMARY KEY,
            dock_id        TEXT NOT NULL,
            sku_id         TEXT NOT NULL,
            eta_hours      REAL NOT NULL,
            cases_expected INTEGER NOT NULL,
            carrier        TEXT NOT NULL,
            status         TEXT NOT NULL,
            priority_flag  INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (sku_id) REFERENCES sku_master(sku_id)
        );
        CREATE TABLE IF NOT EXISTS forklift_telemetry (
            record_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            forklift_id TEXT NOT NULL,
            zone_id     TEXT NOT NULL,
            battery_pct REAL NOT NULL,
            status      TEXT NOT NULL,
            operator_id TEXT,
            last_update TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Data generation ──────────────────────────────────────────────────

def generate_skus(n, rng, fake_inst):
    skus = []
    for i in range(n):
        cat = ALL_CATEGORIES[i % len(ALL_CATEGORIES)]
        st = _storage_type_for_category(cat)
        skus.append({
            "sku_id": f"SKU-{i+1:04d}",
            "sku_name": fake_inst.catch_phrase()[:40],
            "category": cat,
            "case_pack_qty": rng.choice([6, 8, 12, 16, 24]),
            "weight_per_case_kg": round(rng.uniform(2.0, 25.0), 1),
            "storage_type": st,
        })
    return skus


def generate_pick_faces(skus, n, rng):
    threshold_map = {"ambient": 0.30, "chilled": 0.40, "frozen": 0.50}
    pfs = []
    for i in range(n):
        sku = skus[i % len(skus)]
        zone_id = _zone_for_storage(sku["storage_type"], rng)
        max_cap = rng.choice([48, 60, 72, 96, 120, 144])
        thresh = threshold_map[sku["storage_type"]]

        if rng.random() < 0.4:
            current = rng.randint(1, max(1, int(max_cap * thresh * 0.9)))
        else:
            current = rng.randint(max(1, int(max_cap * thresh) + 1), int(max_cap * 0.95))

        day = rng.randint(13, 15)
        hour = rng.randint(0, 23)
        minute = rng.randint(0, 59)
        pfs.append({
            "pick_face_id": f"PF-{i+1:04d}",
            "sku_id": sku["sku_id"],
            "zone_id": zone_id,
            "aisle": f"{zone_id}-A{rng.randint(1, 6):02d}",
            "position": rng.randint(1, 20),
            "current_qty": current,
            "max_capacity": max_cap,
            "last_replenished": f"2024-03-{day:02d}T{hour:02d}:{minute:02d}:00",
        })
    return pfs


def generate_picking_rates(skus, n, rng):
    rates = []
    for i in range(n):
        sku = skus[i % len(skus)]
        avg = round(rng.uniform(5.0, 35.0), 1)
        rates.append({
            "sku_id": sku["sku_id"],
            "avg_units_per_hour": avg,
            "peak_rate": round(avg * rng.uniform(1.3, 1.8), 1),
            "off_peak_rate": round(avg * rng.uniform(0.3, 0.6), 1),
        })
    return rates


def generate_dock_schedules(skus, n, rng):
    schedules = []
    for i in range(n):
        sku = skus[rng.randint(0, len(skus) - 1)]
        status = rng.choices(
            ["scheduled", "in_transit", "arrived", "unloading"],
            weights=[0.4, 0.3, 0.15, 0.15],
        )[0]
        schedules.append({
            "schedule_id": f"DS-{i+1:04d}",
            "dock_id": f"DOCK-{rng.randint(1, 6):02d}",
            "sku_id": sku["sku_id"],
            "eta_hours": round(rng.uniform(0.5, 24.0), 1),
            "cases_expected": rng.randint(10, 100),
            "carrier": rng.choice(CARRIERS),
            "status": status,
            "priority_flag": 1 if rng.random() < 0.15 else 0,
        })
    return schedules


def generate_forklift_telemetry(n, rng):
    entries_per_fl = max(1, n // NUM_FORKLIFTS)
    remainder = n - entries_per_fl * NUM_FORKLIFTS
    records = []

    for fl_idx in range(NUM_FORKLIFTS):
        fl_id = f"FL-{fl_idx+1:03d}"
        home_zone = ZONE_DEFS[fl_idx % NUM_ZONES]["zone_id"]
        count = entries_per_fl + (1 if fl_idx < remainder else 0)

        for j in range(count):
            if j == count - 1:
                # Latest (current) snapshot
                status = rng.choices(["idle", "in_use", "charging"],
                                     weights=[0.5, 0.3, 0.2])[0]
                battery = round(rng.uniform(15, 100), 1) if status != "charging" \
                    else round(rng.uniform(5, 40), 1)
                ts = "2024-03-15T10:00:00"
            else:
                status = rng.choice(["idle", "in_use", "charging"])
                battery = round(rng.uniform(10, 100), 1)
                hour = rng.randint(0, 9)
                ts = f"2024-03-15T{hour:02d}:{rng.randint(0, 59):02d}:00"

            records.append({
                "forklift_id": fl_id,
                "zone_id": home_zone,
                "battery_pct": battery,
                "status": status,
                "operator_id": f"OP-{rng.randint(1, 30):03d}" if status == "in_use" else None,
                "last_update": ts,
            })
    return records


# ── Database insert ──────────────────────────────────────────────────

def insert_data(conn, skus, pick_faces, rates, dock_sched, fl_telemetry):
    c = conn.cursor()
    for s in skus:
        c.execute("INSERT INTO sku_master VALUES (?,?,?,?,?,?)",
                  (s["sku_id"], s["sku_name"], s["category"],
                   s["case_pack_qty"], s["weight_per_case_kg"], s["storage_type"]))
    for p in pick_faces:
        c.execute("INSERT INTO pick_faces VALUES (?,?,?,?,?,?,?,?)",
                  (p["pick_face_id"], p["sku_id"], p["zone_id"], p["aisle"],
                   p["position"], p["current_qty"], p["max_capacity"],
                   p["last_replenished"]))
    for r in rates:
        c.execute(
            "INSERT INTO picking_rates (sku_id,avg_units_per_hour,peak_rate,off_peak_rate) VALUES (?,?,?,?)",
            (r["sku_id"], r["avg_units_per_hour"], r["peak_rate"], r["off_peak_rate"]))
    for d in dock_sched:
        c.execute("INSERT INTO dock_schedules VALUES (?,?,?,?,?,?,?,?)",
                  (d["schedule_id"], d["dock_id"], d["sku_id"], d["eta_hours"],
                   d["cases_expected"], d["carrier"], d["status"], d["priority_flag"]))
    for f in fl_telemetry:
        c.execute(
            "INSERT INTO forklift_telemetry (forklift_id,zone_id,battery_pct,status,operator_id,last_update) VALUES (?,?,?,?,?,?)",
            (f["forklift_id"], f["zone_id"], f["battery_pct"], f["status"],
             f["operator_id"], f["last_update"]))
    conn.commit()


# ── Workspace generation ─────────────────────────────────────────────

def write_workspace(workspace, skus):
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed file 1: replenishment_policy.yaml ──
    policy = {
        "stock_thresholds": {
            "ambient": 30,
            "chilled": 40,
            "frozen": 50,
        },
        "priority_weights": {
            "urgency": 0.40,
            "demand": 0.30,
            "storage_penalty": 0.20,
            "dock_proximity": 0.10,
        },
        "storage_type_factors": {
            "ambient": 1.0,
            "chilled": 1.5,
            "frozen": 2.0,
        },
        "target_fill_pct": 85,
        "min_battery_pct": 20,
        "dock_threshold_hours": 4.0,
    }
    with open(os.path.join(workspace, "replenishment_policy.yaml"), "w") as fh:
        yaml.dump(policy, fh, default_flow_style=False, sort_keys=False)

    # ── Fixed file 2: time_standards.json ──
    time_std = {
        "proactive_time_per_case_min": 1.2,
        "reactive_time_per_case_min": 2.8,
        "base_travel_time_min": 4.0,
        "picker_idle_penalty_min": 8.0,
    }
    with open(os.path.join(workspace, "time_standards.json"), "w") as fh:
        json.dump(time_std, fh, indent=2)

    # ── Fixed file 3: zone_config.csv ──
    pd.DataFrame(ZONE_DEFS).to_csv(
        os.path.join(workspace, "zone_config.csv"), index=False)

    # ── Fixed file 4: forklift_roster.txt ──
    eff_rng = np.random.RandomState(SEED + 100)
    with open(os.path.join(workspace, "forklift_roster.txt"), "w") as fh:
        fh.write("# Forklift Roster - Efficiency Ratings\n")
        fh.write("# forklift_id | home_zone | efficiency_rating\n")
        for i in range(NUM_FORKLIFTS):
            fl_id = f"FL-{i+1:03d}"
            home_zone = ZONE_DEFS[i % NUM_ZONES]["zone_id"]
            eff = round(float(eff_rng.uniform(0.75, 1.0)), 2)
            fh.write(f"{fl_id} | {home_zone} | {eff}\n")

    # ── Scaling files: demand_adjustment CSVs ──
    n_files = SCALE["num_workspace_files"]
    n_skus = len(skus)
    skus_per_file = max(1, math.ceil(n_skus / n_files))

    dm_rng = np.random.RandomState(SEED + 200)
    for fidx in range(n_files):
        start = fidx * skus_per_file
        end = min(start + skus_per_file, n_skus)
        if start >= n_skus:
            start = fidx % n_skus
            end = start + 1
        rows = []
        for i in range(start, end):
            rows.append({
                "sku_id": skus[i]["sku_id"],
                "demand_multiplier": round(float(dm_rng.uniform(0.5, 2.0)), 2),
            })
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"demand_adjustment_{fidx+1:02d}.csv"),
            index=False)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Deterministic seeding
    rng = random.Random(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)
    fake_inst = Faker()
    Faker.seed(SEED)

    n = SCALE["rows_per_table"]

    # Database
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    skus = generate_skus(n, rng, fake_inst)
    pick_faces = generate_pick_faces(skus, n, rng)
    rates = generate_picking_rates(skus, n, rng)
    dock_sched = generate_dock_schedules(skus, n, rng)
    fl_telem = generate_forklift_telemetry(n, rng)

    insert_data(conn, skus, pick_faces, rates, dock_sched, fl_telem)
    conn.close()

    # Workspace
    write_workspace(args.workspace, skus)
    print(f"Data generated: {n} rows/table, {SCALE['num_workspace_files']} demand files")


if __name__ == "__main__":
    main()
