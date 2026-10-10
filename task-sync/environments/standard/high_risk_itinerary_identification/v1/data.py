import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker

try:
    import yaml
except ImportError:
    import json as yaml

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 16,
}

AIRPORTS = [
    "ATL", "ORD", "DFW", "DEN", "LAX", "JFK", "SFO", "SEA",
    "MIA", "BOS", "PHX", "IAH", "MSP", "DTW", "EWR",
]
HUB_AIRPORTS = ["ATL", "ORD", "DFW", "DEN", "JFK", "LAX"]
CARRIERS = ["AA", "UA", "DL", "WN", "B6", "NK", "AS", "F9"]
LOYALTY_TIERS = ["Platinum", "Gold", "Silver", "Basic"]
TRAVEL_DATE = "2026-04-22"

MIN_CONNECTION_TIMES = {
    "ATL": 75, "ORD": 90, "DFW": 70, "DEN": 65, "LAX": 85,
    "JFK": 90, "SFO": 80, "SEA": 60, "MIA": 75, "BOS": 70,
    "PHX": 55, "IAH": 80, "MSP": 60, "DTW": 65, "EWR": 85,
}

CARRIER_OTP = {
    "AA": 0.82, "UA": 0.78, "DL": 0.85, "WN": 0.72,
    "B6": 0.68, "NK": 0.65, "AS": 0.88, "F9": 0.62,
}


def minutes_to_time(m):
    m = int(m) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def generate_pnr(rng):
    chars = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    return "".join([chars[rng.randint(0, len(chars))] for _ in range(6)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    rng = np.random.RandomState(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(args.workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ---- Generate travelers ----
    travelers = []
    for i in range(n_rows):
        tier_idx = rng.choice(4, p=[0.10, 0.20, 0.30, 0.40])
        travelers.append({
            "traveler_id": f"T{i + 1:04d}",
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "loyalty_tier": LOYALTY_TIERS[tier_idx],
        })

    # ---- Generate bookings and segments ----
    bookings = []
    segments = []
    used_pnrs = set()
    seg_id = 0

    for i in range(n_rows):
        while True:
            pnr = generate_pnr(rng)
            if pnr not in used_pnrs:
                used_pnrs.add(pnr)
                break

        traveler = travelers[i % len(travelers)]
        n_legs = int(rng.choice([1, 2, 3], p=[0.35, 0.45, 0.20]))

        origin = AIRPORTS[rng.randint(0, len(AIRPORTS))]
        remaining = [a for a in AIRPORTS if a != origin]
        destination = remaining[rng.randint(0, len(remaining))]

        if n_legs == 1:
            route = [origin, destination]
        elif n_legs == 2:
            hubs = [a for a in HUB_AIRPORTS if a != origin and a != destination]
            if not hubs:
                hubs = [a for a in AIRPORTS if a != origin and a != destination]
            hub = hubs[rng.randint(0, len(hubs))]
            route = [origin, hub, destination]
        else:
            hubs = [a for a in HUB_AIRPORTS if a != origin and a != destination]
            if len(hubs) < 2:
                hubs = [a for a in AIRPORTS if a != origin and a != destination]
            idx = rng.permutation(len(hubs))[:2]
            route = [origin, hubs[idx[0]], hubs[idx[1]], destination]

        if n_legs == 1:
            dep_time = 360 + rng.randint(0, 480)
        elif n_legs == 2:
            dep_time = 360 + rng.randint(0, 360)
        else:
            dep_time = 360 + rng.randint(0, 180)

        booking_segments = []
        for leg in range(n_legs):
            if n_legs == 3:
                flight_dur = 60 + rng.randint(0, 120)
            else:
                flight_dur = 60 + rng.randint(0, 180)

            carrier = CARRIERS[rng.randint(0, len(CARRIERS))]
            flight_num = f"{carrier}{rng.randint(1000, 10000)}"
            arr_time = dep_time + flight_dur

            seg = {
                "segment_id": seg_id,
                "booking_id": i,
                "pnr": pnr,
                "leg_order": leg + 1,
                "flight_number": flight_num,
                "carrier_code": carrier,
                "origin": route[leg],
                "destination": route[leg + 1],
                "scheduled_departure": minutes_to_time(dep_time),
                "scheduled_arrival": minutes_to_time(arr_time),
            }
            segments.append(seg)
            booking_segments.append(seg)
            seg_id += 1

            if leg < n_legs - 1:
                conn_airport = route[leg + 1]
                min_conn = MIN_CONNECTION_TIMES.get(conn_airport, 60)
                if rng.random() < 0.30:
                    lo = max(20, min_conn - 30)
                    hi = min_conn + 15
                    if lo >= hi:
                        hi = lo + 1
                    layover = rng.randint(lo, hi)
                else:
                    lo = min_conn + 10
                    hi = min_conn + 60
                    if lo >= hi:
                        hi = lo + 1
                    layover = rng.randint(lo, hi)
                dep_time = arr_time + layover

        booking_date = fake.date_between_dates(
            date_start=pd.Timestamp("2026-03-22"),
            date_end=pd.Timestamp("2026-04-20"),
        ).isoformat()

        bookings.append({
            "booking_id": i,
            "pnr": pnr,
            "traveler_id": traveler["traveler_id"],
            "booking_date": booking_date,
            "status": "confirmed",
        })

    # ---- Generate flight statuses ----
    flight_statuses = []
    seen_flights = set()
    for seg in segments:
        fn = seg["flight_number"]
        if fn in seen_flights:
            continue
        seen_flights.add(fn)

        r = rng.random()
        if r < 0.05:
            status = "cancelled"
            delay = 0
            reason = ["weather", "mechanical", "crew_shortage"][rng.randint(0, 3)]
        elif r < 0.35:
            status = "delayed"
            delay = int(rng.exponential(40)) + 10
            reason = ["weather", "mechanical", "crew_scheduling",
                       "air_traffic", "late_aircraft"][rng.randint(0, 5)]
        else:
            status = "on_time"
            delay = 0
            reason = ""

        flight_statuses.append({
            "flight_number": fn,
            "flight_date": TRAVEL_DATE,
            "status": status,
            "delay_minutes": delay,
            "reason": reason,
        })

    while len(flight_statuses) < SCALE["rows_per_table"]:
        carrier = CARRIERS[rng.randint(0, len(CARRIERS))]
        fn = f"{carrier}{rng.randint(1000, 10000)}"
        if fn in seen_flights:
            continue
        seen_flights.add(fn)
        if rng.random() < 0.30:
            flight_statuses.append({
                "flight_number": fn, "flight_date": TRAVEL_DATE,
                "status": "delayed",
                "delay_minutes": int(rng.exponential(30)) + 5,
                "reason": "air_traffic",
            })
        else:
            flight_statuses.append({
                "flight_number": fn, "flight_date": TRAVEL_DATE,
                "status": "on_time", "delay_minutes": 0, "reason": "",
            })

    # ---- Generate alternative flights ----
    route_pairs = set()
    for seg in segments:
        route_pairs.add((seg["origin"], seg["destination"]))

    alternatives = []
    alt_id = 0
    for orig, dest in sorted(route_pairs):
        n_alts = rng.randint(2, 5)
        for _ in range(n_alts):
            carrier = CARRIERS[rng.randint(0, len(CARRIERS))]
            dep_min = 360 + rng.randint(0, 720)
            dur = 60 + rng.randint(0, 180)
            arr_min = dep_min + dur
            alternatives.append({
                "alt_id": alt_id,
                "origin": orig, "destination": dest,
                "carrier_code": carrier,
                "flight_number": f"{carrier}{rng.randint(1000, 10000)}",
                "departure_time": minutes_to_time(dep_min),
                "arrival_time": minutes_to_time(arr_min),
                "available_seats": int(rng.randint(0, 50)),
                "flight_date": TRAVEL_DATE,
            })
            alt_id += 1

    while len(alternatives) < SCALE["rows_per_table"]:
        orig = AIRPORTS[rng.randint(0, len(AIRPORTS))]
        dest_opts = [a for a in AIRPORTS if a != orig]
        dest = dest_opts[rng.randint(0, len(dest_opts))]
        carrier = CARRIERS[rng.randint(0, len(CARRIERS))]
        dep_min = 360 + rng.randint(0, 720)
        dur = 60 + rng.randint(0, 180)
        alternatives.append({
            "alt_id": alt_id, "origin": orig, "destination": dest,
            "carrier_code": carrier,
            "flight_number": f"{carrier}{rng.randint(1000, 10000)}",
            "departure_time": minutes_to_time(dep_min),
            "arrival_time": minutes_to_time(dep_min + dur),
            "available_seats": int(rng.randint(0, 50)),
            "flight_date": TRAVEL_DATE,
        })
        alt_id += 1

    # ---- Create database ----
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE travelers (
        traveler_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        loyalty_tier TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE bookings (
        booking_id INTEGER PRIMARY KEY,
        pnr TEXT UNIQUE NOT NULL,
        traveler_id TEXT NOT NULL,
        booking_date TEXT,
        status TEXT NOT NULL,
        FOREIGN KEY (traveler_id) REFERENCES travelers(traveler_id)
    )""")
    cur.execute("""CREATE TABLE segments (
        segment_id INTEGER PRIMARY KEY,
        booking_id INTEGER NOT NULL,
        pnr TEXT NOT NULL,
        leg_order INTEGER NOT NULL,
        flight_number TEXT NOT NULL,
        carrier_code TEXT NOT NULL,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        scheduled_departure TEXT NOT NULL,
        scheduled_arrival TEXT NOT NULL,
        FOREIGN KEY (booking_id) REFERENCES bookings(booking_id)
    )""")
    cur.execute("""CREATE TABLE flight_status (
        flight_number TEXT NOT NULL,
        flight_date TEXT NOT NULL,
        status TEXT NOT NULL,
        delay_minutes INTEGER DEFAULT 0,
        reason TEXT,
        PRIMARY KEY (flight_number, flight_date)
    )""")
    cur.execute("""CREATE TABLE alternative_flights (
        alt_id INTEGER PRIMARY KEY,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        carrier_code TEXT NOT NULL,
        flight_number TEXT NOT NULL,
        departure_time TEXT NOT NULL,
        arrival_time TEXT NOT NULL,
        available_seats INTEGER NOT NULL,
        flight_date TEXT NOT NULL
    )""")

    for t in travelers:
        cur.execute("INSERT INTO travelers VALUES (?,?,?,?,?)",
                    (t["traveler_id"], t["name"], t["email"], t["phone"], t["loyalty_tier"]))
    for b in bookings:
        cur.execute("INSERT INTO bookings VALUES (?,?,?,?,?)",
                    (b["booking_id"], b["pnr"], b["traveler_id"], b["booking_date"], b["status"]))
    for s in segments:
        cur.execute("INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (s["segment_id"], s["booking_id"], s["pnr"], s["leg_order"],
                     s["flight_number"], s["carrier_code"], s["origin"], s["destination"],
                     s["scheduled_departure"], s["scheduled_arrival"]))
    for fs in flight_statuses:
        cur.execute("INSERT OR IGNORE INTO flight_status VALUES (?,?,?,?,?)",
                    (fs["flight_number"], fs["flight_date"], fs["status"],
                     fs["delay_minutes"], fs["reason"]))
    for a in alternatives:
        cur.execute("INSERT INTO alternative_flights VALUES (?,?,?,?,?,?,?,?,?)",
                    (a["alt_id"], a["origin"], a["destination"], a["carrier_code"],
                     a["flight_number"], a["departure_time"], a["arrival_time"],
                     a["available_seats"], a["flight_date"]))

    conn.commit()
    conn.close()

    # ---- Create fixed workspace files ----
    _write_connection_rules(args.workspace)
    _write_risk_config(args.workspace)
    _write_rebooking_policy(args.workspace)

    # ---- Create scalable workspace files ----
    _write_passenger_supplements(args.workspace, bookings, rng, n_files)


def _write_connection_rules(workspace):
    data = {"minimum_connection_times": MIN_CONNECTION_TIMES}
    with open(os.path.join(workspace, "connection_rules.yaml"), "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def _write_risk_config(workspace):
    data = {
        "weights": {
            "connection_tightness": 35,
            "carrier_reliability": 25,
            "current_delay": 25,
        },
        "thresholds": {
            "high_risk_score": 50,
            "tight_connection_buffer_minutes": 30,
            "poor_otp_threshold": 0.75,
            "severe_delay_minutes": 60,
        },
        "vulnerability_factors": {
            "special_assistance": 1.3,
            "unaccompanied_minor": 1.5,
            "default": 1.0,
        },
        "carrier_otp": CARRIER_OTP,
    }
    with open(os.path.join(workspace, "risk_config.json"), "w") as f:
        json.dump(data, f, indent=2)


def _write_rebooking_policy(workspace):
    content = """\
Rebooking Priority Assignment Rules

Travelers flagged as high-risk are assigned a rebooking priority level from 1 (highest urgency) to 4.

Priority 1 is reserved for travelers whose computed risk score meets or exceeds 80 and who hold Platinum or Gold loyalty status. Priority 2 applies to travelers with a risk score of 80 or above but who hold Silver or Basic status. Priority 3 covers travelers with a risk score at or above 50 but below 80 who are Platinum or Gold members. Priority 4 encompasses all remaining high-risk travelers, those with scores from 50 up to but not including 80 holding Silver or Basic status.

When multiple travelers share the same priority level, they should be ordered by descending risk score. If risk scores are also tied, order alphabetically by traveler name in ascending order.

Only travelers with a final risk score of 50 or above should appear on the rebooking list.
"""
    with open(os.path.join(workspace, "rebooking_policy.md"), "w") as f:
        f.write(content)


def _write_passenger_supplements(workspace, bookings, rng, n_files):
    formats = ["json", "csv", "txt", "yaml"]

    supplements = []
    for b in bookings:
        sa = bool(rng.random() < 0.15)
        um = bool(not sa and rng.random() < 0.08)
        supplements.append({
            "pnr": b["pnr"],
            "special_assistance": sa,
            "unaccompanied_minor": um,
            "dietary_preference": ["none", "vegetarian", "vegan", "halal", "kosher"][rng.randint(0, 5)],
            "seat_preference": ["window", "aisle", "middle", "no_preference"][rng.randint(0, 4)],
        })

    # Distribute supplements evenly so that exactly n_files files are created
    # even when len(supplements) is not perfectly divisible
    for i in range(n_files):
        lo = i * len(supplements) // n_files
        hi = (i + 1) * len(supplements) // n_files
        batch = supplements[lo:hi]
        if not batch:
            # Ensure a file is still created with at least one record
            batch = [supplements[i % len(supplements)]]
        fmt = formats[i % len(formats)]
        fname = f"passenger_data_{i + 1:03d}.{fmt}"
        fpath = os.path.join(workspace, fname)

        if fmt == "json":
            with open(fpath, "w") as f:
                json.dump(batch, f, indent=2)

        elif fmt == "csv":
            with open(fpath, "w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["pnr", "special_assistance", "unaccompanied_minor",
                                "dietary_preference", "seat_preference"],
                )
                writer.writeheader()
                for item in batch:
                    writer.writerow({
                        "pnr": item["pnr"],
                        "special_assistance": str(item["special_assistance"]),
                        "unaccompanied_minor": str(item["unaccompanied_minor"]),
                        "dietary_preference": item["dietary_preference"],
                        "seat_preference": item["seat_preference"],
                    })

        elif fmt == "txt":
            with open(fpath, "w") as f:
                for item in batch:
                    f.write(f"PNR: {item['pnr']}\n")
                    f.write("Special Assistance: {}\n".format("Yes" if item["special_assistance"] else "No"))
                    f.write("Unaccompanied Minor: {}\n".format("Yes" if item["unaccompanied_minor"] else "No"))
                    f.write(f"Dietary Preference: {item['dietary_preference']}\n")
                    f.write(f"Seat Preference: {item['seat_preference']}\n")
                    f.write("---\n")

        elif fmt == "yaml":
            with open(fpath, "w") as f:
                yaml.dump(batch, f, default_flow_style=False)


if __name__ == "__main__":
    main()
