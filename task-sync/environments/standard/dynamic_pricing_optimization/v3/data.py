#!/usr/bin/env python3
"""Generate database and workspace for EV charger dynamic pricing task."""

import argparse
import sqlite3
import os
import json
import csv
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

REFERENCE_TIME = datetime(2026, 4, 22, 8, 0, 0)


def main(db_path: str, workspace: str):
    np.random.seed(42)
    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rpt = SCALE["rows_per_table"]
    nwf = SCALE["num_workspace_files"]

    # Derived counts — every DB table has >= rpt rows
    num_chargers = rpt
    num_stations = nwf
    num_zones = max(3, num_stations // 3)
    num_sessions = rpt
    num_reservations = rpt
    num_maintenance = rpt

    # ======================== GENERATE DATA ========================

    # --- Zones ---
    zone_ids = [f"ZONE-{chr(65 + i)}" for i in range(num_zones)]

    # --- Stations (workspace config, not in DB) ---
    stations = []
    for i in range(num_stations):
        stations.append({
            "station_id": f"STN-{i + 1:03d}",
            "station_name": fake.company()[:25].strip(),
            "zone_id": zone_ids[i % num_zones],
            "latitude": round(34.0 + float(rng.uniform(0, 0.1)), 6),
            "longitude": round(-118.3 + float(rng.uniform(0, 0.1)), 6),
        })

    # --- Chargers ---
    charger_types = ["Level2", "DCFC"]
    connector_map = {"Level2": ["J1772", "Type2"], "DCFC": ["CCS1", "CCS2", "CHAdeMO"]}
    power_map = {"Level2": [7.2, 11.0, 19.2], "DCFC": [50.0, 100.0, 150.0]}

    chargers = []
    for i in range(num_chargers):
        stn = stations[i % num_stations]
        ctype = charger_types[i % 2]
        is_active = 1 if rng.random() > 0.08 else 0
        chargers.append({
            "charger_id": f"CHG-{i + 1:04d}",
            "station_id": stn["station_id"],
            "zone_id": stn["zone_id"],
            "charger_type": ctype,
            "power_kw": float(rng.choice(power_map[ctype])),
            "connector_type": str(rng.choice(connector_map[ctype])),
            "is_active": is_active,
        })

    # Ensure at least 85 % active
    active_count = sum(c["is_active"] for c in chargers)
    min_active = int(0.85 * num_chargers)
    for c in chargers:
        if active_count >= min_active:
            break
        if not c["is_active"]:
            c["is_active"] = 1
            active_count += 1

    active_charger_ids = [c["charger_id"] for c in chargers if c["is_active"]]

    # --- Sessions ---
    sessions = []
    num_active = max(5, num_chargers // 5)
    active_used = set()
    for i in range(num_active):
        cid = active_charger_ids[i % len(active_charger_ids)]
        if cid in active_used:
            continue
        active_used.add(cid)
        start = REFERENCE_TIME - timedelta(hours=float(rng.uniform(0.5, 4.0)))
        end = REFERENCE_TIME + timedelta(hours=float(rng.uniform(0.5, 6.0)))
        sessions.append({
            "session_id": f"SES-{len(sessions) + 1:05d}",
            "charger_id": cid,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "expected_end_time": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "energy_kwh": round(float(rng.uniform(5, 60)), 2),
            "status": "active",
        })
    while len(sessions) < num_sessions:
        cid = str(rng.choice(active_charger_ids))
        start = REFERENCE_TIME - timedelta(hours=float(rng.uniform(4, 72)))
        dur = timedelta(hours=float(rng.uniform(0.5, 4)))
        end = start + dur
        sessions.append({
            "session_id": f"SES-{len(sessions) + 1:05d}",
            "charger_id": cid,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "expected_end_time": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "energy_kwh": round(float(rng.uniform(5, 80)), 2),
            "status": "completed",
        })

    # --- Reservations ---
    res_statuses = ["confirmed"] * 6 + ["pending"] * 2 + ["cancelled"] * 2
    reservations = []
    for i in range(num_reservations):
        cid = str(rng.choice(active_charger_ids))
        start_h = float(rng.uniform(0.5, 22.0))
        start = REFERENCE_TIME + timedelta(hours=start_h)
        dur = timedelta(hours=float(rng.uniform(0.5, 3.0)))
        end = min(start + dur, REFERENCE_TIME + timedelta(hours=24))
        reservations.append({
            "reservation_id": f"RES-{i + 1:05d}",
            "charger_id": cid,
            "reserved_start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "reserved_end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "user_id": f"USR-{rng.randint(1000, 9999)}",
            "status": str(rng.choice(res_statuses)),
        })

    # --- Maintenance ---
    maint_types = ["firmware_update", "hardware_repair", "inspection", "cleaning"]
    maint_priorities = ["critical", "routine", "low"]
    all_charger_ids = [c["charger_id"] for c in chargers]
    maintenance = []
    for i in range(num_maintenance):
        cid = str(rng.choice(all_charger_ids))
        if rng.random() < 0.4:
            start = REFERENCE_TIME + timedelta(hours=float(rng.uniform(-2, 20)))
            dur = timedelta(hours=float(rng.uniform(1, 5)))
            end = start + dur
            status = str(rng.choice(["scheduled", "in_progress"]))
        else:
            start = REFERENCE_TIME - timedelta(hours=float(rng.uniform(48, 200)))
            dur = timedelta(hours=float(rng.uniform(1, 4)))
            end = start + dur
            status = "completed"
        maintenance.append({
            "maintenance_id": f"MNT-{i + 1:04d}",
            "charger_id": cid,
            "scheduled_start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "scheduled_end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "maintenance_type": str(rng.choice(maint_types)),
            "priority": str(rng.choice(maint_priorities)),
            "status": status,
        })

    # --- Grid Forecasts (24 per zone => >= 72 rows at v0) ---
    grid_forecasts = []
    fid = 0
    for zone in zone_ids:
        for h in range(24):
            fid += 1
            hour_time = REFERENCE_TIME + timedelta(hours=h)
            clock_h = hour_time.hour
            base = 40 + 30 * np.sin(np.pi * max(0, clock_h - 6) / 12)
            demand_pct = float(np.clip(base + rng.normal(0, 8), 5, 98))
            renewable = float(np.clip(
                50 - 15 * abs(clock_h - 13) / 6 + rng.normal(0, 10), 5, 95
            ))
            grid_forecasts.append({
                "forecast_id": f"GF-{fid:05d}",
                "zone_id": zone,
                "forecast_hour": hour_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "predicted_demand_pct": round(demand_pct, 1),
                "supply_capacity_mw": round(float(rng.uniform(80, 150)), 1),
                "renewable_pct": round(renewable, 1),
            })

    # ======================== DATABASE ========================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE chargers (
        charger_id TEXT PRIMARY KEY,
        station_id TEXT NOT NULL,
        zone_id TEXT NOT NULL,
        charger_type TEXT NOT NULL,
        power_kw REAL NOT NULL,
        connector_type TEXT NOT NULL,
        is_active INTEGER NOT NULL
    )""")
    for c in chargers:
        cur.execute(
            "INSERT INTO chargers VALUES (?,?,?,?,?,?,?)",
            (c["charger_id"], c["station_id"], c["zone_id"],
             c["charger_type"], c["power_kw"], c["connector_type"],
             c["is_active"]),
        )

    cur.execute("""CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY,
        charger_id TEXT NOT NULL,
        start_time TEXT NOT NULL,
        expected_end_time TEXT NOT NULL,
        energy_kwh REAL NOT NULL,
        status TEXT NOT NULL
    )""")
    for s in sessions:
        cur.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
            (s["session_id"], s["charger_id"], s["start_time"],
             s["expected_end_time"], s["energy_kwh"], s["status"]),
        )

    cur.execute("""CREATE TABLE reservations (
        reservation_id TEXT PRIMARY KEY,
        charger_id TEXT NOT NULL,
        reserved_start TEXT NOT NULL,
        reserved_end TEXT NOT NULL,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL
    )""")
    for r in reservations:
        cur.execute(
            "INSERT INTO reservations VALUES (?,?,?,?,?,?)",
            (r["reservation_id"], r["charger_id"], r["reserved_start"],
             r["reserved_end"], r["user_id"], r["status"]),
        )

    cur.execute("""CREATE TABLE maintenance (
        maintenance_id TEXT PRIMARY KEY,
        charger_id TEXT NOT NULL,
        scheduled_start TEXT NOT NULL,
        scheduled_end TEXT NOT NULL,
        maintenance_type TEXT NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL
    )""")
    for m in maintenance:
        cur.execute(
            "INSERT INTO maintenance VALUES (?,?,?,?,?,?,?)",
            (m["maintenance_id"], m["charger_id"], m["scheduled_start"],
             m["scheduled_end"], m["maintenance_type"], m["priority"],
             m["status"]),
        )

    cur.execute("""CREATE TABLE grid_forecasts (
        forecast_id TEXT PRIMARY KEY,
        zone_id TEXT NOT NULL,
        forecast_hour TEXT NOT NULL,
        predicted_demand_pct REAL NOT NULL,
        supply_capacity_mw REAL NOT NULL,
        renewable_pct REAL NOT NULL
    )""")
    for gf in grid_forecasts:
        cur.execute(
            "INSERT INTO grid_forecasts VALUES (?,?,?,?,?,?)",
            (gf["forecast_id"], gf["zone_id"], gf["forecast_hour"],
             gf["predicted_demand_pct"], gf["supply_capacity_mw"],
             gf["renewable_pct"]),
        )

    conn.commit()
    conn.close()

    # ======================== WORKSPACE FILES ========================

    # --- Fixed: pricing_policy.yaml ---
    pricing_yaml = (
        'reference_time: "2026-04-22T08:00:00"\n'
        "base_rates:\n"
        "  Level2: 0.25\n"
        "  DCFC: 0.45\n"
        "peak_hours:\n"
        "  - 9\n"
        "  - 10\n"
        "  - 11\n"
        "  - 12\n"
        "  - 17\n"
        "  - 18\n"
        "  - 19\n"
        "  - 20\n"
        "peak_surcharge: 0.10\n"
        "off_peak_discount: 0.05\n"
        "utilization_thresholds:\n"
        "  high: 0.70\n"
        "  medium: 0.40\n"
        "utilization_surcharges:\n"
        "  high: 0.15\n"
        "  medium: 0.08\n"
        "  low: 0.00\n"
        "renewable_discount_threshold: 50.0\n"
        "renewable_discount: 0.03\n"
    )
    with open(os.path.join(workspace, "pricing_policy.yaml"), "w") as f:
        f.write(pricing_yaml)

    # --- Fixed: grid_tariff_tiers.json ---
    grid_tariff = {
        "tiers": [
            {"min_demand_pct": 0, "max_demand_pct": 30, "multiplier": 0.80},
            {"min_demand_pct": 30, "max_demand_pct": 50, "multiplier": 0.90},
            {"min_demand_pct": 50, "max_demand_pct": 70, "multiplier": 1.00},
            {"min_demand_pct": 70, "max_demand_pct": 85, "multiplier": 1.20},
            {"min_demand_pct": 85, "max_demand_pct": 100, "multiplier": 1.50},
        ]
    }
    with open(os.path.join(workspace, "grid_tariff_tiers.json"), "w") as f:
        json.dump(grid_tariff, f, indent=2)

    # --- Fixed: maintenance_impact_rules.json ---
    maint_rules = {
        "zone_capacity_reduction_surcharge": [
            {"min_reduction_pct": 0, "max_reduction_pct": 25, "surcharge": 0.00},
            {"min_reduction_pct": 25, "max_reduction_pct": 50, "surcharge": 0.05},
            {"min_reduction_pct": 50, "max_reduction_pct": 75, "surcharge": 0.12},
            {"min_reduction_pct": 75, "max_reduction_pct": 100, "surcharge": 0.20},
        ]
    }
    with open(os.path.join(workspace, "maintenance_impact_rules.json"), "w") as f:
        json.dump(maint_rules, f, indent=2)

    # --- Fixed: zone_station_map.csv ---
    with open(os.path.join(workspace, "zone_station_map.csv"), "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["station_id", "station_name", "zone_id", "latitude", "longitude"],
        )
        writer.writeheader()
        writer.writerows(stations)

    # --- Scalable: one usage-history CSV per station (count = num_workspace_files) ---
    for stn in stations:
        rows = []
        for hour in range(24):
            if 7 <= hour <= 9:
                base_util = 0.55
            elif 10 <= hour <= 16:
                base_util = 0.65
            elif 17 <= hour <= 20:
                base_util = 0.75
            elif 21 <= hour <= 23:
                base_util = 0.35
            else:
                base_util = 0.15
            util = float(np.clip(base_util + rng.normal(0, 0.12), 0.05, 0.95))
            rows.append({
                "clock_hour": hour,
                "avg_sessions": max(1, int(util * 8 + rng.normal(0, 1.5))),
                "avg_energy_kwh": round(float(rng.uniform(8, 45)), 1),
                "avg_utilization_rate": round(util, 3),
            })
        df = pd.DataFrame(rows)
        df.to_csv(
            os.path.join(workspace, f"station_{stn['station_id']}_usage.csv"),
            index=False,
        )

    print(f"DB  : {db_path} ({num_chargers} chargers, {num_sessions} sessions, "
          f"{num_reservations} reservations, {num_maintenance} maintenance, "
          f"{len(grid_forecasts)} forecasts)")
    print(f"Work: {workspace}/ — 4 fixed + {num_stations} station files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
