"""
Hotel Room Demand Forecasting — Data Generation Script
Generates database tables and workspace files for the rate-adjustment task.
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
from datetime import datetime, timedelta
from faker import Faker

# ============================================================
# SCALE — only this block differs across v0 / v1 / v2 / v3
# ============================================================
SCALE = {
    "rows_per_table": 200,       # v1 = 2× base
    "num_workspace_files": 20,   # v1 = base + N
}

# ============================================================
# Fixed domain constants (shared across all scales)
# ============================================================
REFERENCE_DATE = datetime(2025, 3, 1)
FORECAST_DAYS = 14
ROOM_TYPES = ["Deluxe", "Executive", "Family", "Standard", "Suite"]
EVENT_CATEGORIES = ["concert", "conference", "exhibition", "festival", "sports", "theater"]

BASE_RATES = {"Standard": 120, "Deluxe": 180, "Suite": 300, "Executive": 220, "Family": 160}
CAPACITIES = {"Standard": 80, "Deluxe": 50, "Suite": 20, "Executive": 35, "Family": 40}
FLOOR_RATES = {"Standard": 85, "Deluxe": 130, "Suite": 220, "Executive": 160, "Family": 110}
CEILING_RATES = {"Standard": 200, "Deluxe": 300, "Suite": 500, "Executive": 380, "Family": 270}


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows_per_table = SCALE["rows_per_table"]
    num_ws_files = SCALE["num_workspace_files"]

    # Derived sizing
    num_room_types = len(ROOM_TYPES)
    history_days = max(30, rows_per_table // num_room_types)
    total_days = history_days + FORECAST_DAYS

    history_start = REFERENCE_DATE - timedelta(days=history_days)

    all_dates = [
        (history_start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(total_days)
    ]
    history_dates = all_dates[:history_days]
    forecast_dates = [
        (REFERENCE_DATE + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(FORECAST_DAYS)
    ]

    # Scalable-file distribution
    num_competitors = max(1, math.ceil(num_ws_files * 0.4))
    num_origin_profiles = max(1, math.ceil(num_ws_files * 0.3))
    num_group_files = max(1, num_ws_files - num_competitors - num_origin_profiles)

    # Origin cities
    num_origin_cities = max(10, num_origin_profiles * 5)
    fake.unique.clear()
    origin_cities = sorted([fake.unique.city() for _ in range(num_origin_cities)])

    # ==================================================================
    # DATABASE
    # ==================================================================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # --- Table 1: occupancy_records ---
    cur.execute("""
        CREATE TABLE occupancy_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            record_date     TEXT    NOT NULL,
            room_type       TEXT    NOT NULL,
            rooms_occupied  INTEGER NOT NULL,
            rooms_available INTEGER NOT NULL
        )
    """)
    occ_rows = []
    for d in all_dates:
        dow = datetime.strptime(d, "%Y-%m-%d").weekday()
        for rt in ROOM_TYPES:
            cap = CAPACITIES[rt]
            base_occ = 0.55 + 0.15 * (dow >= 4)
            occ = float(np.clip(base_occ + np.random.normal(0, 0.12), 0.10, 0.95))
            occ_rows.append((d, rt, int(occ * cap), cap))
    cur.executemany(
        "INSERT INTO occupancy_records (record_date, room_type, rooms_occupied, rooms_available) VALUES (?,?,?,?)",
        occ_rows,
    )

    # --- Table 2: local_events ---
    cur.execute("""
        CREATE TABLE local_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date          TEXT    NOT NULL,
            event_name          TEXT    NOT NULL,
            category            TEXT    NOT NULL,
            expected_attendance INTEGER NOT NULL,
            venue               TEXT    NOT NULL
        )
    """)
    num_events = max(rows_per_table, len(all_dates) * 2)
    venues = [fake.company() + " Arena" for _ in range(8)]
    evt_rows = []
    for _ in range(num_events):
        d = random.choice(all_dates)
        cat = random.choice(EVENT_CATEGORIES)
        att = random.randint(200, 15000)
        name = fake.catch_phrase() + " " + cat.capitalize()
        venue = random.choice(venues)
        evt_rows.append((d, name, cat, att, venue))
    cur.executemany(
        "INSERT INTO local_events (event_date, event_name, category, expected_attendance, venue) VALUES (?,?,?,?,?)",
        evt_rows,
    )

    # --- Table 3: flight_arrivals ---
    cur.execute("""
        CREATE TABLE flight_arrivals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            arrival_date    TEXT    NOT NULL,
            flight_number   TEXT    NOT NULL,
            origin_city     TEXT    NOT NULL,
            passenger_count INTEGER NOT NULL,
            arrival_time    TEXT    NOT NULL
        )
    """)
    num_flights = max(rows_per_table, len(all_dates) * 3)
    airlines = ["AA", "UA", "DL", "SW", "BA", "LH", "AF", "EK"]
    flt_rows = []
    for _ in range(num_flights):
        d = random.choice(all_dates)
        al = random.choice(airlines)
        fnum = f"{al}{random.randint(100, 9999)}"
        orig = random.choice(origin_cities)
        pax = random.randint(50, 350)
        h = random.randint(6, 23)
        m = random.choice([0, 15, 30, 45])
        flt_rows.append((d, fnum, orig, pax, f"{h:02d}:{m:02d}"))
    cur.executemany(
        "INSERT INTO flight_arrivals (arrival_date, flight_number, origin_city, passenger_count, arrival_time) VALUES (?,?,?,?,?)",
        flt_rows,
    )

    # --- Table 4: demand_history ---
    cur.execute("""
        CREATE TABLE demand_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            record_date    TEXT    NOT NULL,
            room_type      TEXT    NOT NULL,
            bookings       INTEGER NOT NULL,
            cancellations  INTEGER NOT NULL,
            revenue        REAL    NOT NULL,
            avg_daily_rate REAL    NOT NULL
        )
    """)
    dem_rows = []
    for d in history_dates:
        for rt in ROOM_TYPES:
            cap = CAPACITIES[rt]
            base = BASE_RATES[rt]
            bk = random.randint(int(cap * 0.3), int(cap * 0.9))
            cancel = random.randint(0, max(1, bk // 5))
            adr = round(base * (1 + float(np.random.normal(0, 0.08))), 2)
            rev = round((bk - cancel) * adr, 2)
            dem_rows.append((d, rt, bk, cancel, rev, adr))
    cur.executemany(
        "INSERT INTO demand_history (record_date, room_type, bookings, cancellations, revenue, avg_daily_rate) VALUES (?,?,?,?,?,?)",
        dem_rows,
    )

    conn.commit()
    conn.close()

    # ==================================================================
    # WORKSPACE — Fixed configuration files (not counted toward SCALE)
    # ==================================================================

    # room_types.yaml
    room_cfg = {}
    for rt in ROOM_TYPES:
        room_cfg[rt] = {
            "base_rate": BASE_RATES[rt],
            "capacity": CAPACITIES[rt],
            "floor_rate": FLOOR_RATES[rt],
            "ceiling_rate": CEILING_RATES[rt],
        }
    with open(os.path.join(workspace, "room_types.yaml"), "w") as f:
        yaml.dump({"room_types": room_cfg}, f, default_flow_style=False)

    # pricing_rules.yaml
    pricing_rules = {
        "forecast": {
            "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
            "forecast_days": FORECAST_DAYS,
        },
        "demand_weights": {
            "occupancy": 0.30,
            "competitor": 0.20,
            "events": 0.15,
            "flights": 0.15,
            "demand_trend": 0.20,
        },
        "event_impact_factors": {
            "concert": 0.08,
            "conference": 0.06,
            "sports": 0.07,
            "festival": 0.10,
            "exhibition": 0.04,
            "theater": 0.05,
        },
        "occupancy_scoring": {
            "baseline": 0.50,
            "scale_factor": 2.0,
        },
        "flight_demand_divisor": 500,
        "demand_trend_recent_days": 7,
        "max_adjustment_pct": 0.30,
        "min_adjustment_pct": -0.20,
        "default_conversion_rate": 0.05,
    }
    with open(os.path.join(workspace, "pricing_rules.yaml"), "w") as f:
        yaml.dump(pricing_rules, f, default_flow_style=False)

    # seasonal_factors.json
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    seasonal = {}
    for month in months:
        m_idx = months.index(month) + 1
        if m_idx in [6, 7, 8, 12]:
            seasonal[month] = round(1.0 + random.uniform(0.10, 0.25), 2)
        elif m_idx in [1, 2, 11]:
            seasonal[month] = round(1.0 - random.uniform(0.05, 0.15), 2)
        else:
            seasonal[month] = round(1.0 + random.uniform(-0.05, 0.10), 2)
    with open(os.path.join(workspace, "seasonal_factors.json"), "w") as f:
        json.dump({"monthly_factors": seasonal}, f, indent=2)

    # rate_boundaries.csv
    bounds = [
        {"room_type": rt, "floor_rate": FLOOR_RATES[rt], "ceiling_rate": CEILING_RATES[rt]}
        for rt in ROOM_TYPES
    ]
    pd.DataFrame(bounds).to_csv(os.path.join(workspace, "rate_boundaries.csv"), index=False)

    # ==================================================================
    # WORKSPACE — Scalable data files (counted toward SCALE)
    # ==================================================================

    # ---- Competitor rate CSVs ----
    for i in range(num_competitors):
        rows = []
        for d in forecast_dates:
            for rt in ROOM_TYPES:
                base = BASE_RATES[rt]
                rate = round(base * (1 + float(np.random.uniform(-0.15, 0.25))), 2)
                rows.append({"date": d, "room_type": rt, "rate": rate})
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"competitor_{i + 1}_rates.csv"), index=False
        )

    # ---- Origin-profile JSONs ----
    cities_per_file = max(1, len(origin_cities) // num_origin_profiles)
    for i in range(num_origin_profiles):
        si = i * cities_per_file
        ei = len(origin_cities) if i == num_origin_profiles - 1 else si + cities_per_file
        profile = {}
        for city in origin_cities[si:ei]:
            profile[city] = {
                "conversion_rate": round(float(np.random.uniform(0.02, 0.12)), 4),
                "avg_stay_nights": random.randint(1, 4),
            }
        with open(os.path.join(workspace, f"origin_profile_{i + 1}.json"), "w") as f:
            json.dump(profile, f, indent=2)

    # ---- Group-booking CSVs ----
    for i in range(num_group_files):
        rows = []
        num_bookings = random.randint(5, 15)
        for _ in range(num_bookings):
            d = random.choice(forecast_dates)
            rt = random.choice(ROOM_TYPES)
            rooms = random.randint(2, 15)
            rows.append({"date": d, "room_type": rt, "num_rooms": rooms})
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"group_bookings_{i + 1}.csv"), index=False
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
