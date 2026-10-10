"""
Delivery Zone Optimization - Data Generator

Generates database tables and workspace files for a delivery zone
partitioning and assignment task.
"""
import argparse
import os
import sqlite3
import json
import csv
import math
import random

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

# ─── Constants ────────────────────────────────────────────────────────────────
REGIONS = ["Central", "East", "North", "South", "West"]
SHIFTS = ["morning", "afternoon", "evening"]
PRIORITIES = ["standard", "express", "urgent"]
VEHICLE_TYPES = ["van", "truck", "cargo_bike"]
CERT_LEVELS = ["basic", "advanced", "expert"]
TODAY = "2026-04-21"
TODAY_DOW = "Tuesday"


def seed_all(seed=42):
    random.seed(seed)
    np.random.seed(seed)


# ─── Database ─────────────────────────────────────────────────────────────────

def create_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            zone_id TEXT PRIMARY KEY,
            zone_name TEXT NOT NULL,
            region TEXT NOT NULL,
            area_sq_km REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS packages (
            package_id TEXT PRIMARY KEY,
            zone_id TEXT NOT NULL,
            weight_kg REAL NOT NULL,
            priority TEXT NOT NULL,
            delivery_window TEXT NOT NULL,
            created_date TEXT NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            driver_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            license_type TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            experience_years INTEGER NOT NULL,
            certification_level TEXT NOT NULL,
            max_daily_deliveries INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_id TEXT PRIMARY KEY,
            vehicle_type TEXT NOT NULL,
            max_load_kg REAL NOT NULL,
            max_volume_m3 REAL NOT NULL,
            fuel_type TEXT NOT NULL,
            operational_range_km REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS traffic_patterns (
            pattern_id TEXT PRIMARY KEY,
            zone_id TEXT NOT NULL,
            shift TEXT NOT NULL,
            day_of_week TEXT NOT NULL,
            congestion_index REAL NOT NULL,
            avg_speed_kmh REAL NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    conn.commit()


def generate_zones(conn):
    rpt = SCALE["rows_per_table"]
    fake = Faker()
    Faker.seed(42)
    zones = []
    for i in range(rpt):
        zid = f"Z{i + 1:03d}"
        region = REGIONS[i % len(REGIONS)]
        zname = f"{region} District {i + 1}"
        area = round(float(np.random.uniform(5.0, 50.0)), 2)
        lat = round(40.0 + float(np.random.uniform(0, 1.0)), 6)
        lng = round(-74.0 + float(np.random.uniform(0, 1.0)), 6)
        zones.append((zid, zname, region, area, lat, lng))
    conn.executemany("INSERT INTO zones VALUES (?,?,?,?,?,?)", zones)
    conn.commit()
    return zones


def generate_packages(conn, zones):
    rpt = SCALE["rows_per_table"]
    n_total = rpt * 5  # 5x base for packages
    zone_ids = [z[0] for z in zones]
    packages = []
    idx = 0

    # Guarantee every zone gets at least 2 packages for today
    for zid in zone_ids:
        for _ in range(2):
            idx += 1
            pid = f"PKG{idx:06d}"
            w = round(float(np.random.uniform(0.5, 30.0)), 2)
            pri = str(np.random.choice(PRIORITIES, p=[0.55, 0.30, 0.15]))
            win = str(np.random.choice(SHIFTS))
            packages.append((pid, zid, w, pri, win, TODAY))

    # Fill remaining randomly
    remaining = max(0, n_total - len(packages))
    dates = [TODAY, "2026-04-20", "2026-04-19"]
    for _ in range(remaining):
        idx += 1
        pid = f"PKG{idx:06d}"
        zid = str(np.random.choice(zone_ids))
        w = round(float(np.random.uniform(0.5, 30.0)), 2)
        pri = str(np.random.choice(PRIORITIES, p=[0.55, 0.30, 0.15]))
        win = str(np.random.choice(SHIFTS))
        dt = str(np.random.choice(dates, p=[0.60, 0.25, 0.15]))
        packages.append((pid, zid, w, pri, win, dt))

    conn.executemany("INSERT INTO packages VALUES (?,?,?,?,?,?)", packages)
    conn.commit()
    return packages


def generate_drivers(conn):
    rpt = SCALE["rows_per_table"]
    fake = Faker()
    Faker.seed(42)
    drivers = []
    for i in range(rpt):
        did = f"D{i + 1:03d}"
        name = fake.name()
        lic = str(np.random.choice(["A", "B", "C"]))
        shift = SHIFTS[i % len(SHIFTS)]
        exp = int(np.random.randint(1, 21))
        cert = str(np.random.choice(CERT_LEVELS, p=[0.50, 0.35, 0.15]))
        max_del = int(np.random.randint(20, 61))
        drivers.append((did, name, lic, shift, exp, cert, max_del))
    conn.executemany("INSERT INTO drivers VALUES (?,?,?,?,?,?,?)", drivers)
    conn.commit()
    return drivers


def generate_vehicles(conn):
    rpt = SCALE["rows_per_table"]
    vehicles = []
    for i in range(rpt):
        vid = f"V{i + 1:03d}"
        vtype = VEHICLE_TYPES[i % len(VEHICLE_TYPES)]
        if vtype == "van":
            ml = round(float(np.random.uniform(500, 1500)), 1)
            mv = round(float(np.random.uniform(5, 15)), 1)
            fuel = str(np.random.choice(["gasoline", "electric"]))
            opr = round(float(np.random.uniform(150, 300)), 1)
        elif vtype == "truck":
            ml = round(float(np.random.uniform(2000, 5000)), 1)
            mv = round(float(np.random.uniform(15, 40)), 1)
            fuel = str(np.random.choice(["diesel", "electric"]))
            opr = round(float(np.random.uniform(200, 500)), 1)
        else:  # cargo_bike
            ml = round(float(np.random.uniform(50, 200)), 1)
            mv = round(float(np.random.uniform(0.5, 3.0)), 1)
            fuel = "electric"
            opr = round(float(np.random.uniform(30, 80)), 1)
        vehicles.append((vid, vtype, ml, mv, fuel, opr))
    conn.executemany("INSERT INTO vehicles VALUES (?,?,?,?,?,?)", vehicles)
    conn.commit()
    return vehicles


def generate_traffic(conn, zones):
    days = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]
    patterns = []
    idx = 0
    for z in zones:
        zid = z[0]
        for shift in SHIFTS:
            for day in days:
                idx += 1
                tid = f"TP{idx:06d}"
                cong = round(float(np.random.uniform(0.05, 0.90)), 3)
                speed = round(float(np.random.uniform(15, 65)), 1)
                patterns.append((tid, zid, shift, day, cong, speed))
    conn.executemany(
        "INSERT INTO traffic_patterns VALUES (?,?,?,?,?,?)", patterns
    )
    conn.commit()
    return patterns


# ─── Workspace ────────────────────────────────────────────────────────────────

def generate_workspace(workspace, zones, packages, drivers, vehicles, traffic):
    n_files = SCALE["num_workspace_files"]

    # ── Fixed files ───────────────────────────────────────────────────────

    # 1. clustering_config.yaml
    config = {
        "max_zones_per_cluster": 5,
        "load_buffer_pct": 15,
        "priority_multiplier": {
            "standard": 1.0,
            "express": 1.5,
            "urgent": 2.5,
        },
        "certification_thresholds": {
            "urgent_pct_expert": 40,
            "express_urgent_pct_advanced": 60,
        },
        "shift_order": ["morning", "afternoon", "evening"],
        "target_date": TODAY,
    }
    with open(os.path.join(workspace, "clustering_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 2. vehicle_availability.csv  (~80 % available)
    veh_rows = []
    for v in vehicles:
        vid = v[0]
        avail = bool(np.random.random() < 0.80)
        note = (
            ""
            if avail
            else str(
                np.random.choice(
                    [
                        "scheduled maintenance",
                        "tire replacement",
                        "engine check",
                        "battery service",
                    ]
                )
            )
        )
        veh_rows.append(
            {"vehicle_id": vid, "available": str(avail), "maintenance_note": note}
        )
    with open(os.path.join(workspace, "vehicle_availability.csv"), "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["vehicle_id", "available", "maintenance_note"]
        )
        w.writeheader()
        w.writerows(veh_rows)

    # 3. priority_rules.md
    rules = (
        "Driver assignment for delivery clusters must account for the priority "
        "composition of packages within each zone. When a zone contains a "
        "proportion of urgent packages exceeding the expert certification "
        "threshold specified in the clustering configuration, any cluster "
        "containing that zone must be served by a driver holding expert-level "
        "certification. Likewise, if the combined proportion of express and "
        "urgent packages in any zone surpasses the advanced certification "
        "threshold, the assigned driver must hold at least advanced "
        "certification.\n\n"
        "Among all eligible drivers who satisfy the certification and shift "
        "requirements for a given cluster, the one with the highest "
        "performance score should be selected. If two eligible drivers share "
        "the same performance score, the driver whose identifier comes first "
        "in alphanumeric order takes precedence.\n\n"
        "Vehicles are selected using a best-fit approach: from all available "
        "vehicles whose maximum load capacity meets or exceeds the cluster's "
        "required capacity including the configured load buffer, choose the "
        "vehicle with the smallest maximum capacity to maximize fleet "
        "utilization. Ties in capacity are broken by selecting the vehicle "
        "with the alphanumerically earliest identifier.\n\n"
        "Zones with no packages on the delivery date should not appear in the "
        "assignment map.\n"
    )
    with open(os.path.join(workspace, "priority_rules.md"), "w") as f:
        f.write(rules)

    # ── Scalable files ────────────────────────────────────────────────────
    # Ratio 3 : 3 : 2  →  driver_performance : zone_forecast : traffic_bulletin
    n_dp = max(1, round(n_files * 3 / 8))
    n_zf = max(1, round(n_files * 3 / 8))
    n_tb = max(1, n_files - n_dp - n_zf)

    # ── Driver performance CSV files ──
    driver_ids = [d[0] for d in drivers]
    perf = {}
    for did in driver_ids:
        perf[did] = {
            "avg_delivery_time_min": round(float(np.random.uniform(15, 45)), 1),
            "success_rate": round(float(np.random.uniform(0.80, 0.99)), 2),
            "customer_rating": round(float(np.random.uniform(3.5, 5.0)), 1),
            "on_time_pct": round(float(np.random.uniform(0.75, 0.98)), 2),
            "performance_score": round(float(np.random.uniform(50, 99)), 1),
        }
    chunk_d = math.ceil(len(driver_ids) / n_dp)
    for fi in range(n_dp):
        start = fi * chunk_d
        end = min(start + chunk_d, len(driver_ids))
        subset = driver_ids[start:end]
        fname = f"driver_performance_{fi + 1}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(
                [
                    "driver_id",
                    "avg_delivery_time_min",
                    "success_rate",
                    "customer_rating",
                    "on_time_pct",
                    "performance_score",
                ]
            )
            for did in subset:
                s = perf[did]
                wr.writerow(
                    [
                        did,
                        s["avg_delivery_time_min"],
                        s["success_rate"],
                        s["customer_rating"],
                        s["on_time_pct"],
                        s["performance_score"],
                    ]
                )

    # ── Zone forecast JSON files ──
    zone_ids = [z[0] for z in zones]
    forecasts = {}
    for zid in zone_ids:
        forecasts[zid] = {
            "forecast_factor": round(float(np.random.uniform(0.80, 1.30)), 2),
            "trend": str(np.random.choice(["increasing", "stable", "decreasing"])),
        }
    chunk_z = math.ceil(len(zone_ids) / n_zf)
    for fi in range(n_zf):
        start = fi * chunk_z
        end = min(start + chunk_z, len(zone_ids))
        subset = zone_ids[start:end]
        data = [
            {
                "zone_id": zid,
                "forecast_factor": forecasts[zid]["forecast_factor"],
                "trend": forecasts[zid]["trend"],
            }
            for zid in subset
        ]
        fname = f"zone_forecast_{fi + 1}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(data, f, indent=2)

    # ── Traffic bulletin TXT files ──
    zone_shift_adj = {}
    for zid in zone_ids:
        for shift in SHIFTS:
            adj = round(float(np.random.uniform(-0.10, 0.15)), 2)
            zone_shift_adj[(zid, shift)] = adj
    all_entries = sorted(zone_shift_adj.items(), key=lambda x: (x[0][0], x[0][1]))
    chunk_t = math.ceil(len(all_entries) / n_tb)
    for fi in range(n_tb):
        start = fi * chunk_t
        end = min(start + chunk_t, len(all_entries))
        subset = all_entries[start:end]
        fname = f"traffic_bulletin_{fi + 1}.txt"
        lines = [
            f"=== TRAFFIC BULLETIN #{fi + 1} ===",
            f"Date: {TODAY}",
            f"Issued: 05:{30 + fi:02d}",
            "",
            "Real-time congestion adjustments based on current road conditions.",
            "",
        ]
        for (zid, shift), adj in subset:
            formatted = f"{adj:+.2f}"  # always includes sign
            lines.append(
                f"Zone {zid} | Shift: {shift} | Adjustment: {formatted}"
            )
        lines.append("")
        lines.append("End of bulletin.")
        with open(os.path.join(workspace, fname), "w") as f:
            f.write("\n".join(lines) + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    seed_all(42)
    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    zones = generate_zones(conn)
    packages = generate_packages(conn, zones)
    drivers = generate_drivers(conn)
    vehicles = generate_vehicles(conn)
    traffic = generate_traffic(conn, zones)

    conn.close()

    # Reset seed for workspace generation (ensures reproducibility
    # regardless of how many DB rows were generated above)
    seed_all(42 + 1000)
    generate_workspace(args.workspace, zones, packages, drivers, vehicles, traffic)


if __name__ == "__main__":
    main()
