#!/usr/bin/env python3
"""Data generation for fuel theft / unauthorized vehicle usage detection task."""

import argparse
import sqlite3
import os
import json
import csv
import math
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta
from collections import defaultdict

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 20,
}

# ---------- Constants ----------
NUM_DEPOTS = 8
VEHICLE_TYPES = ["sedan", "SUV", "truck", "van", "pickup"]
START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2025, 1, 31)
NUM_DAYS = 31

TYPE_SPECS = {
    "sedan":  {"tank_capacity_liters": 55,  "expected_efficiency_km_per_liter": 12},
    "SUV":    {"tank_capacity_liters": 70,  "expected_efficiency_km_per_liter": 9},
    "truck":  {"tank_capacity_liters": 100, "expected_efficiency_km_per_liter": 6},
    "van":    {"tank_capacity_liters": 80,  "expected_efficiency_km_per_liter": 8},
    "pickup": {"tank_capacity_liters": 75,  "expected_efficiency_km_per_liter": 7},
}

DEPOT_BASE_COORDS = [
    (34.052, -118.243),
    (34.145, -118.395),
    (33.998, -118.098),
    (33.905, -118.302),
    (34.198, -118.148),
    (34.108, -118.005),
    (33.952, -118.498),
    (34.248, -118.348),
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    rng = np.random.default_rng(42)

    os.makedirs(workspace, exist_ok=True)

    # ---- Derived counts ----
    n_v = SCALE["rows_per_table"]
    n_ft = SCALE["rows_per_table"] * 3
    n_gps_base = SCALE["rows_per_table"] * 6
    n_sh = SCALE["rows_per_table"] * 4
    n_files = SCALE["num_workspace_files"]

    # ================================================================
    # 1.  DEPOTS (fixed, written to workspace)
    # ================================================================
    depots = []
    geofence_radii = [2.5, 3.0, 2.0, 3.5, 2.8, 2.2, 3.2, 2.7]
    depot_names_suffix = [
        "Central", "West", "East", "South", "North",
        "Pasadena", "Harbor", "Valley",
    ]
    for i, (lat, lon) in enumerate(DEPOT_BASE_COORDS):
        depots.append({
            "depot_id": i + 1,
            "name": f"Depot {depot_names_suffix[i]}",
            "latitude": lat,
            "longitude": lon,
            "geofence_radius_km": geofence_radii[i],
        })

    # ================================================================
    # 2.  VEHICLES
    # ================================================================
    vehicles = []
    for i in range(n_v):
        vtype = VEHICLE_TYPES[i % len(VEHICLE_TYPES)]
        depot = depots[i % NUM_DEPOTS]
        plate = f"FLT-{i + 1:04d}"
        vehicles.append({
            "vehicle_id": i + 1,
            "plate_number": plate,
            "vehicle_type": vtype,
            "assigned_driver": fake.name(),
            "depot_id": depot["depot_id"],
        })

    # ================================================================
    # 3.  DRIVER SHIFTS  (no duplicate vehicle+date)
    # ================================================================
    shifts = []
    used_shift_keys = set()
    shift_counter = 0
    attempts = 0
    while shift_counter < n_sh and attempts < n_sh * 10:
        attempts += 1
        vid = int(rng.integers(1, n_v + 1))
        day = int(rng.integers(0, NUM_DAYS))
        key = (vid, day)
        if key in used_shift_keys:
            continue
        used_shift_keys.add(key)
        date_str = (START_DATE + timedelta(days=day)).strftime("%Y-%m-%d")
        start_h = int(rng.choice([6, 7, 8]))
        end_h = start_h + int(rng.choice([8, 9, 10]))
        shift_counter += 1
        shifts.append({
            "shift_id": shift_counter,
            "vehicle_id": vid,
            "driver_name": vehicles[vid - 1]["assigned_driver"],
            "shift_date": date_str,
            "start_hour": start_h,
            "end_hour": end_h,
        })
    shift_lookup = {
        (s["vehicle_id"], s["shift_date"]): (s["start_hour"], s["end_hour"])
        for s in shifts
    }

    # ================================================================
    # 4.  MAINTENANCE SCHEDULES (workspace CSVs)
    # ================================================================
    n_maint = max(20, n_v * 3 // 5)
    maintenance_records = []
    maint_keys = set()
    maint_counter = 0
    maint_types = ["oil_change", "tire_rotation", "brake_inspection",
                   "engine_check", "transmission_service"]
    attempts = 0
    while maint_counter < n_maint and attempts < n_maint * 10:
        attempts += 1
        vid = int(rng.integers(1, n_v + 1))
        day = int(rng.integers(0, NUM_DAYS))
        key = (vid, day)
        if key in maint_keys:
            continue
        maint_keys.add(key)
        start_hour = int(rng.integers(8, 14))
        duration = int(rng.integers(3, 8))
        start_dt = START_DATE + timedelta(days=day, hours=start_hour)
        end_dt = start_dt + timedelta(hours=duration)
        maint_counter += 1
        maintenance_records.append({
            "maintenance_id": maint_counter,
            "vehicle_id": vid,
            "start_datetime": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "end_datetime": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "maintenance_type": str(rng.choice(maint_types)),
            "facility": f"Service Center {fake.last_name()}",
        })

    maint_by_vehicle = defaultdict(list)
    for m in maintenance_records:
        maint_by_vehicle[m["vehicle_id"]].append(
            (datetime.strptime(m["start_datetime"], "%Y-%m-%d %H:%M:%S"),
             datetime.strptime(m["end_datetime"],   "%Y-%m-%d %H:%M:%S"))
        )

    # ================================================================
    # 5.  OVERTIME APPROVALS (workspace fleet daily reports)
    # ================================================================
    n_overtime = max(5, n_v // 8)
    overtime_by_date = defaultdict(list)
    overtime_set = set()
    ot_counter = 0
    attempts = 0
    while ot_counter < n_overtime and attempts < n_overtime * 20:
        attempts += 1
        vid = int(rng.integers(1, n_v + 1))
        day = int(rng.integers(0, NUM_DAYS))
        date_str = (START_DATE + timedelta(days=day)).strftime("%Y-%m-%d")
        skey = (vid, date_str)
        if skey not in shift_lookup:
            continue
        _, end_h = shift_lookup[skey]
        ot_start = end_h
        ot_end = min(end_h + int(rng.integers(2, 5)), 23)
        if ot_start >= ot_end:
            continue
        # avoid duplicates
        if any(o["vehicle_id"] == vid for o in overtime_by_date[date_str]):
            continue
        ot_counter += 1
        overtime_by_date[date_str].append({
            "vehicle_id": vid,
            "start_hour": ot_start,
            "end_hour": ot_end,
            "reason": str(rng.choice(["Late delivery", "Emergency service",
                                       "Extended route", "Client request"])),
        })
        for h in range(ot_start, ot_end):
            overtime_set.add((vid, date_str, h))

    # ================================================================
    # 6.  ANOMALY INDICES
    # ================================================================
    n_offgeofence = max(5, n_ft // 20)
    offgeofence_idx = set(int(x) for x in rng.choice(n_ft, size=n_offgeofence, replace=False))

    remaining = [i for i in range(n_ft) if i not in offgeofence_idx]
    n_overcap = max(4, n_ft // 30)
    overcap_idx = set(int(x) for x in rng.choice(remaining, size=n_overcap, replace=False))

    n_receipts_total = n_ft * 2 // 3
    receipt_tx_indices = sorted(int(x) for x in rng.choice(n_ft, size=n_receipts_total, replace=False))
    n_mismatch = max(4, n_receipts_total // 25)
    mismatch_positions = set(int(x) for x in rng.choice(n_receipts_total, size=n_mismatch, replace=False))

    n_maint_anom = max(4, len(maintenance_records) // 5)
    maint_anom_idx = set(int(x) for x in rng.choice(
        len(maintenance_records),
        size=min(n_maint_anom, len(maintenance_records)),
        replace=False))

    n_afterhours_anom = max(6, n_v // 6)

    # ================================================================
    # 7.  FUEL TRANSACTIONS
    # ================================================================
    stations = [f"{fake.company()} Fuel" for _ in range(20)]
    fuel_transactions = []
    for i in range(n_ft):
        vid = (i % n_v) + 1
        vehicle = vehicles[vid - 1]
        depot = depots[vehicle["depot_id"] - 1]
        day_off = int(rng.integers(0, NUM_DAYS))
        hour = int(rng.integers(6, 20))
        minute = int(rng.integers(0, 60))
        ts = START_DATE + timedelta(days=day_off, hours=hour, minutes=minute)
        tank_cap = TYPE_SPECS[vehicle["vehicle_type"]]["tank_capacity_liters"]

        if i in offgeofence_idx:
            angle = float(rng.uniform(0, 2 * math.pi))
            dist_deg = float(rng.uniform(0.5, 1.2))
            lat = depot["latitude"] + dist_deg * math.cos(angle)
            lon = depot["longitude"] + dist_deg * math.sin(angle)
            liters = round(float(rng.uniform(10, tank_cap * 0.8)), 1)
        elif i in overcap_idx:
            lat = depot["latitude"] + float(rng.uniform(-0.01, 0.01))
            lon = depot["longitude"] + float(rng.uniform(-0.01, 0.01))
            liters = round(float(tank_cap * rng.uniform(1.1, 1.85)), 1)
        else:
            lat = depot["latitude"] + float(rng.uniform(-0.015, 0.015))
            lon = depot["longitude"] + float(rng.uniform(-0.015, 0.015))
            liters = round(float(rng.uniform(8, tank_cap * 0.7)), 1)

        cost = round(float(liters * rng.uniform(1.15, 1.75)), 2)
        fuel_transactions.append({
            "transaction_id": i + 1,
            "vehicle_id": vid,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "liters": liters,
            "cost": cost,
            "station_name": str(rng.choice(stations)),
        })

    # ================================================================
    # 8.  GPS EVENTS
    # ================================================================
    gps_events = []
    gps_id = 0

    # 8a. Normal GPS events (during shift)
    n_normal_gps = n_gps_base - n_afterhours_anom * 2 - len(maint_anom_idx) * 2 - n_overtime * 2
    n_normal_gps = max(n_normal_gps, n_gps_base // 2)
    for i in range(n_normal_gps):
        vid = (i % n_v) + 1
        vehicle = vehicles[vid - 1]
        depot = depots[vehicle["depot_id"] - 1]
        day_off = int(rng.integers(0, NUM_DAYS))
        date = START_DATE + timedelta(days=day_off)
        date_str = date.strftime("%Y-%m-%d")
        skey = (vid, date_str)
        if skey in shift_lookup:
            sh, eh = shift_lookup[skey]
        else:
            sh, eh = 8, 17
        hour = int(rng.integers(sh, max(sh + 1, eh)))
        minute = int(rng.integers(0, 60))
        ts = date + timedelta(hours=hour, minutes=minute)
        lat = depot["latitude"] + float(rng.uniform(-0.05, 0.05))
        lon = depot["longitude"] + float(rng.uniform(-0.05, 0.05))
        speed = round(float(rng.uniform(0, 80)), 1)
        ignition = 1 if speed > 0 else int(rng.integers(0, 2))
        gps_id += 1
        gps_events.append({
            "event_id": gps_id,
            "vehicle_id": vid,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "speed_kmh": speed,
            "ignition_on": ignition,
        })

    # 8b. After-hours ignition (TRUE anomalies, not covered by overtime)
    ah_counter = 0
    ah_attempts = 0
    while ah_counter < n_afterhours_anom and ah_attempts < n_afterhours_anom * 50:
        ah_attempts += 1
        vid = int(rng.integers(1, n_v + 1))
        day_off = int(rng.integers(0, NUM_DAYS))
        date = START_DATE + timedelta(days=day_off)
        date_str = date.strftime("%Y-%m-%d")
        skey = (vid, date_str)
        if skey not in shift_lookup:
            continue
        sh, eh = shift_lookup[skey]
        if rng.random() < 0.5 and eh < 24:
            hour = int(rng.integers(max(eh, 18), 24))
        elif sh > 0:
            hour = int(rng.integers(0, min(sh, 6)))
        else:
            continue
        if (vid, date_str, hour) in overtime_set:
            continue
        minute = int(rng.integers(0, 60))
        ts = date + timedelta(hours=hour, minutes=minute)
        depot = depots[vehicles[vid - 1]["depot_id"] - 1]
        lat = depot["latitude"] + float(rng.uniform(-0.03, 0.03))
        lon = depot["longitude"] + float(rng.uniform(-0.03, 0.03))
        speed = round(float(rng.uniform(5, 60)), 1)
        gps_id += 1
        gps_events.append({
            "event_id": gps_id,
            "vehicle_id": vid,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "speed_kmh": speed,
            "ignition_on": 1,
        })
        ah_counter += 1

    # 8c. After-hours GPS events COVERED by overtime (not anomalies)
    for date_str, ots in overtime_by_date.items():
        for ot in ots:
            vid = ot["vehicle_id"]
            depot = depots[vehicles[vid - 1]["depot_id"] - 1]
            for _ in range(2):
                hour = int(rng.integers(
                    ot["start_hour"],
                    max(ot["start_hour"] + 1, ot["end_hour"])))
                minute = int(rng.integers(0, 60))
                dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(
                    hours=hour, minutes=minute)
                lat = depot["latitude"] + float(rng.uniform(-0.03, 0.03))
                lon = depot["longitude"] + float(rng.uniform(-0.03, 0.03))
                speed = round(float(rng.uniform(10, 50)), 1)
                gps_id += 1
                gps_events.append({
                    "event_id": gps_id,
                    "vehicle_id": vid,
                    "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "latitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "speed_kmh": speed,
                    "ignition_on": 1,
                })

    # 8d. Maintenance movement anomalies
    for idx in sorted(maint_anom_idx):
        rec = maintenance_records[idx]
        vid = rec["vehicle_id"]
        depot = depots[vehicles[vid - 1]["depot_id"] - 1]
        s_dt = datetime.strptime(rec["start_datetime"], "%Y-%m-%d %H:%M:%S")
        e_dt = datetime.strptime(rec["end_datetime"],   "%Y-%m-%d %H:%M:%S")
        delta_sec = (e_dt - s_dt).total_seconds()
        for _ in range(2):
            offset = float(rng.uniform(0.1, 0.9)) * delta_sec
            ts = s_dt + timedelta(seconds=offset)
            lat = depot["latitude"] + float(rng.uniform(-0.02, 0.02))
            lon = depot["longitude"] + float(rng.uniform(-0.02, 0.02))
            speed = round(float(rng.uniform(10, 80)), 1)
            gps_id += 1
            gps_events.append({
                "event_id": gps_id,
                "vehicle_id": vid,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "speed_kmh": speed,
                "ignition_on": 1,
            })

    # ================================================================
    # 9.  PRIOR INCIDENTS (workspace MDs)
    # ================================================================
    n_prior = max(5, n_v // 8)
    incident_vids = sorted(set(
        int(x) + 1
        for x in rng.choice(n_v, size=n_prior, replace=False)
    ))
    prior_incidents = []
    inc_types = ["unauthorized_usage", "fuel_discrepancy",
                 "route_deviation", "after_hours_operation"]
    inc_resolutions = ["warning_issued", "suspended_3_days",
                       "investigation_closed", "driver_reassigned"]
    for vid in incident_vids:
        v = vehicles[vid - 1]
        inc_month = int(rng.integers(7, 13))
        inc_day = int(rng.integers(1, 29))
        prior_incidents.append({
            "vehicle_id": vid,
            "plate_number": v["plate_number"],
            "date": f"2024-{inc_month:02d}-{inc_day:02d}",
            "type": str(rng.choice(inc_types)),
            "resolution": str(rng.choice(inc_resolutions)),
        })

    # ================================================================
    # 10. FUEL RECEIPTS (workspace TXTs)
    # ================================================================
    fuel_receipts = []
    for pos, tx_idx in enumerate(receipt_tx_indices):
        tx = fuel_transactions[tx_idx]
        if pos in mismatch_positions:
            diff = float(rng.uniform(6, 25))
            if rng.random() < 0.5:
                pump_amt = round(tx["liters"] + diff, 1)
            else:
                pump_amt = round(max(1.0, tx["liters"] - diff), 1)
        else:
            pump_amt = tx["liters"]
        fuel_receipts.append({
            "transaction_id": tx["transaction_id"],
            "vehicle_id": tx["vehicle_id"],
            "date": tx["timestamp"],
            "station": tx["station_name"],
            "pump_amount_liters": pump_amt,
            "odometer_km": int(rng.integers(10000, 200000)),
        })

    # ================================================================
    # 11. WRITE DATABASE
    # ================================================================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE vehicles (
        vehicle_id   INTEGER PRIMARY KEY,
        plate_number TEXT NOT NULL,
        vehicle_type TEXT NOT NULL,
        assigned_driver TEXT NOT NULL,
        depot_id     INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE fuel_transactions (
        transaction_id INTEGER PRIMARY KEY,
        vehicle_id     INTEGER NOT NULL,
        timestamp      TEXT NOT NULL,
        latitude       REAL NOT NULL,
        longitude      REAL NOT NULL,
        liters         REAL NOT NULL,
        cost           REAL NOT NULL,
        station_name   TEXT NOT NULL,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
    )""")
    c.execute("""CREATE TABLE gps_events (
        event_id    INTEGER PRIMARY KEY,
        vehicle_id  INTEGER NOT NULL,
        timestamp   TEXT NOT NULL,
        latitude    REAL NOT NULL,
        longitude   REAL NOT NULL,
        speed_kmh   REAL NOT NULL,
        ignition_on INTEGER NOT NULL,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
    )""")
    c.execute("""CREATE TABLE driver_shifts (
        shift_id    INTEGER PRIMARY KEY,
        vehicle_id  INTEGER NOT NULL,
        driver_name TEXT NOT NULL,
        shift_date  TEXT NOT NULL,
        start_hour  INTEGER NOT NULL,
        end_hour    INTEGER NOT NULL,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
    )""")

    for v in vehicles:
        c.execute("INSERT INTO vehicles VALUES (?,?,?,?,?)",
                  (v["vehicle_id"], v["plate_number"], v["vehicle_type"],
                   v["assigned_driver"], v["depot_id"]))
    for ft in fuel_transactions:
        c.execute("INSERT INTO fuel_transactions VALUES (?,?,?,?,?,?,?,?)",
                  (ft["transaction_id"], ft["vehicle_id"], ft["timestamp"],
                   ft["latitude"], ft["longitude"], ft["liters"],
                   ft["cost"], ft["station_name"]))
    for ge in gps_events:
        c.execute("INSERT INTO gps_events VALUES (?,?,?,?,?,?,?)",
                  (ge["event_id"], ge["vehicle_id"], ge["timestamp"],
                   ge["latitude"], ge["longitude"], ge["speed_kmh"],
                   ge["ignition_on"]))
    for s in shifts:
        c.execute("INSERT INTO driver_shifts VALUES (?,?,?,?,?,?)",
                  (s["shift_id"], s["vehicle_id"], s["driver_name"],
                   s["shift_date"], s["start_hour"], s["end_hour"]))

    conn.commit()
    conn.close()

    # ================================================================
    # 12. WRITE WORKSPACE FILES
    # ================================================================

    # --- Fixed files ---
    with open(os.path.join(workspace, "depot_geofences.json"), "w") as f:
        json.dump({"depots": depots}, f, indent=2)

    thresholds = {
        "off_geofence_fueling": {
            "distance_threshold_km": 5.0,
            "severity_high_distance_km": 50.0
        },
        "overcapacity_fueling": {
            "threshold_pct": 105,
            "severity_high_pct": 150
        },
        "maintenance_movement": {
            "speed_threshold_kmh": 5.0,
            "severity_high_speed_kmh": 30.0
        },
        "after_hours_ignition": {
            "severity_high_hour_start": 0,
            "severity_high_hour_end": 5
        },
        "fuel_receipt_mismatch": {
            "threshold_liters": 5.0,
            "severity_high_liters": 20.0
        },
        "prior_incident_severity_upgrade": True
    }
    with open(os.path.join(workspace, "anomaly_thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=2)

    with open(os.path.join(workspace, "vehicle_type_specs.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["vehicle_type", "tank_capacity_liters",
                         "expected_efficiency_km_per_liter"])
        for vt, sp in TYPE_SPECS.items():
            writer.writerow([vt, sp["tank_capacity_liters"],
                             sp["expected_efficiency_km_per_liter"]])

    # --- Scaling files ---
    n_maint_files   = max(2, n_files * 3 // 10)
    n_fleet_files   = max(2, n_files * 3 // 10)
    n_receipt_files = max(2, n_files * 2 // 10)
    n_incident_files = n_files - n_maint_files - n_fleet_files - n_receipt_files
    if n_incident_files < 1:
        n_incident_files = 1
        n_maint_files = n_files - n_fleet_files - n_receipt_files - n_incident_files

    # Maintenance schedule CSVs
    for fi in range(n_maint_files):
        lo = fi * len(maintenance_records) // n_maint_files
        hi = (fi + 1) * len(maintenance_records) // n_maint_files
        chunk = maintenance_records[lo:hi]
        fname = f"maintenance_schedule_{fi + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "maintenance_id", "vehicle_id", "start_datetime",
                "end_datetime", "maintenance_type", "facility"])
            writer.writeheader()
            for rec in chunk:
                writer.writerow(rec)

    # Fleet daily reports (JSON) with overtime approvals
    days_per_file = max(1, NUM_DAYS // n_fleet_files)
    for fi in range(n_fleet_files):
        start_day = fi * days_per_file
        end_day = min((fi + 1) * days_per_file, NUM_DAYS)
        if fi == n_fleet_files - 1:
            end_day = NUM_DAYS
        report = {
            "period": {
                "start": (START_DATE + timedelta(days=start_day)).strftime("%Y-%m-%d"),
                "end":   (START_DATE + timedelta(days=max(0, end_day - 1))).strftime("%Y-%m-%d"),
            },
            "daily_records": [],
        }
        for d in range(start_day, end_day):
            date = START_DATE + timedelta(days=d)
            date_str = date.strftime("%Y-%m-%d")
            daily = {
                "date": date_str,
                "approved_overtime": overtime_by_date.get(date_str, []),
            }
            report["daily_records"].append(daily)
        fname = f"fleet_daily_report_{fi + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(report, f, indent=2)

    # Fuel receipt TXTs
    receipts_per_file = max(1, len(fuel_receipts) // n_receipt_files)
    for fi in range(n_receipt_files):
        if fi == n_receipt_files - 1:
            chunk = fuel_receipts[fi * receipts_per_file:]
        else:
            chunk = fuel_receipts[fi * receipts_per_file:(fi + 1) * receipts_per_file]
        fname = f"fuel_receipts_batch_{fi + 1:03d}.txt"
        with open(os.path.join(workspace, fname), "w") as f:
            for r in chunk:
                f.write(f"FUEL RECEIPT #{r['transaction_id']:05d}\n")
                f.write(f"Date: {r['date']}\n")
                f.write(f"Vehicle ID: {r['vehicle_id']}\n")
                f.write(f"Station: {r['station']}\n")
                f.write(f"Pump Amount: {r['pump_amount_liters']} L\n")
                f.write(f"Odometer: {r['odometer_km']} km\n")
                f.write("---\n")

    # Incident history MDs
    incidents_per_file = max(1, len(prior_incidents) // n_incident_files)
    for fi in range(n_incident_files):
        if fi == n_incident_files - 1:
            chunk = prior_incidents[fi * incidents_per_file:]
        else:
            chunk = prior_incidents[fi * incidents_per_file:(fi + 1) * incidents_per_file]
        fname = f"incident_history_{fi + 1:03d}.md"
        with open(os.path.join(workspace, fname), "w") as f:
            f.write(f"# Prior Incident Records - Batch {fi + 1}\n\n")
            for inc in chunk:
                f.write(f"## Vehicle {inc['vehicle_id']} ({inc['plate_number']})\n")
                f.write(f"- Date: {inc['date']}\n")
                f.write(f"- Type: {inc['type']}\n")
                f.write(f"- Resolution: {inc['resolution']}\n\n")

    print(f"Database written to {db_path}")
    print(f"  vehicles:          {len(vehicles)}")
    print(f"  fuel_transactions: {len(fuel_transactions)}")
    print(f"  gps_events:        {len(gps_events)}")
    print(f"  driver_shifts:     {len(shifts)}")
    print(f"Workspace written to {workspace}/")
    wf_count = n_maint_files + n_fleet_files + n_receipt_files + n_incident_files
    print(f"  Fixed files:   3")
    print(f"  Scaling files: {wf_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
