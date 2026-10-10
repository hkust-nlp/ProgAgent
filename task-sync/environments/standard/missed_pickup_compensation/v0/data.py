"""
Data generation script for missed pickup compensation task.
Generates a SQLite database and workspace files simulating a municipal
waste-collection operation with GPS tracking, bin-lift sensors, service
requests, and contractual SLAs.
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
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 100,        # v0 base; v1 = 2×, v2 = 4×, v3 = 8×
    "num_workspace_files": 10,    # v0 base; v1 = +N, v2 = +2N, v3 = +3N
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in metres between two lat/lon points."""
    R = 6_371_000
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) *
         (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 2 * R * math.asin(math.sqrt(a))


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def main(db_path: str, workspace: str):
    # ------------------------------------------------------------------
    # Seeds
    # ------------------------------------------------------------------
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ------------------------------------------------------------------
    # 1. Zone / Truck configuration
    # ------------------------------------------------------------------
    n_zones = 5
    zone_ids = [f"Z{str(i + 1).zfill(3)}" for i in range(n_zones)]
    truck_ids = [f"T{str(i + 1).zfill(3)}" for i in range(n_zones)]
    service_tiers = ["basic", "standard", "premium"]
    tier_weights = [0.40, 0.35, 0.25]

    base_lat, base_lon = 33.7500, -84.3900
    pickup_day_pairs = [
        ["Monday", "Thursday"],
        ["Tuesday", "Friday"],
        ["Wednesday", "Saturday"],
        ["Monday", "Friday"],
        ["Tuesday", "Thursday"],
    ]

    zone_configs = {}
    for i, zid in enumerate(zone_ids):
        zone_configs[zid] = {
            "zone_id": zid,
            "assigned_truck": truck_ids[i],
            "center_latitude": round(base_lat + i * 0.025, 6),
            "center_longitude": round(base_lon - i * 0.020, 6),
            "pickup_days": pickup_day_pairs[i],
            "proximity_threshold_m": 150,
        }

    # ------------------------------------------------------------------
    # 2. Operational date range  (one route-log file per day)
    # ------------------------------------------------------------------
    start_date = datetime(2026, 3, 16)  # a Monday
    operational_dates = [start_date + timedelta(days=d) for d in range(n_files)]

    # ------------------------------------------------------------------
    # 3. Residents
    # ------------------------------------------------------------------
    residents = []
    for i in range(n_rows):
        zid = zone_ids[i % n_zones]
        zc = zone_configs[zid]
        lat = round(zc["center_latitude"] + np.random.uniform(-0.008, 0.008), 6)
        lon = round(zc["center_longitude"] + np.random.uniform(-0.008, 0.008), 6)
        tier = np.random.choice(service_tiers, p=tier_weights)
        residents.append({
            "resident_id": f"R{str(i + 1).zfill(5)}",
            "name": fake.name(),
            "address": fake.street_address(),
            "latitude": lat,
            "longitude": lon,
            "zone_id": zid,
            "service_tier": str(tier),
            "bin_id": f"BIN{str(i + 1).zfill(5)}",
        })

    # ------------------------------------------------------------------
    # 4. Decide pickup events and misses
    # ------------------------------------------------------------------
    # For each (date, zone) that is a scheduled pickup day, decide per-resident
    # whether the pickup succeeds, is a full miss, or a partial miss.
    # Store decisions for later GPS / bin-lift generation.
    pickup_events = []  # list of dicts
    zone_date_excused = {}  # (zone_id, date_str) -> bool

    # Pre-decide which zone-dates have exceptions (excused)
    for dt in operational_dates:
        day_name = DAY_NAMES[dt.weekday()]
        for zid in zone_ids:
            if day_name in zone_configs[zid]["pickup_days"]:
                # ~12% chance of exception
                is_excused = (random.random() < 0.12)
                advance_notice = is_excused and (random.random() < 0.7)
                exc_type = random.choice(["weather", "mechanical"]) if is_excused else "none"
                zone_date_excused[(zid, dt.strftime("%Y-%m-%d"))] = {
                    "excused": is_excused and advance_notice,
                    "exception_code": exc_type,
                    "advance_notice": advance_notice,
                }

    zone_residents = {}
    for r in residents:
        zone_residents.setdefault(r["zone_id"], []).append(r)

    for dt in operational_dates:
        day_name = DAY_NAMES[dt.weekday()]
        for zid in zone_ids:
            if day_name not in zone_configs[zid]["pickup_days"]:
                continue
            date_str = dt.strftime("%Y-%m-%d")
            exc_info = zone_date_excused.get((zid, date_str), {})
            is_excused = exc_info.get("excused", False)
            truck_id = zone_configs[zid]["assigned_truck"]

            for r in zone_residents.get(zid, []):
                if is_excused:
                    # Truck didn't run at all
                    outcome = "excused_miss"
                else:
                    roll = random.random()
                    if roll < 0.15:
                        outcome = "full_miss"      # no GPS stop, no bin lift
                    elif roll < 0.25:
                        outcome = "partial_miss"   # GPS stop but bin lift failed
                    else:
                        outcome = "success"
                pickup_events.append({
                    "resident_id": r["resident_id"],
                    "bin_id": r["bin_id"],
                    "zone_id": zid,
                    "truck_id": truck_id,
                    "date": date_str,
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "outcome": outcome,
                })

    # ------------------------------------------------------------------
    # 5. GPS stops
    # ------------------------------------------------------------------
    gps_stops = []
    stop_counter = 0
    for ev in pickup_events:
        if ev["outcome"] in ("full_miss", "excused_miss"):
            continue  # no GPS stop near this address
        stop_counter += 1
        # Place stop near resident address (within ~50m)
        jitter_lat = np.random.uniform(-0.0004, 0.0004)
        jitter_lon = np.random.uniform(-0.0004, 0.0004)
        dt = datetime.strptime(ev["date"], "%Y-%m-%d")
        hour = random.randint(6, 14)
        minute = random.randint(0, 59)
        stop_time = dt.replace(hour=hour, minute=minute, second=random.randint(0, 59))
        duration = random.randint(15, 120) if ev["outcome"] == "success" else random.randint(5, 25)
        gps_stops.append({
            "stop_id": f"GPS{str(stop_counter).zfill(6)}",
            "truck_id": ev["truck_id"],
            "latitude": round(ev["latitude"] + jitter_lat, 6),
            "longitude": round(ev["longitude"] + jitter_lon, 6),
            "stop_time": stop_time.strftime("%Y-%m-%d %H:%M:%S"),
            "stop_duration_sec": duration,
        })

    # Ensure gps_stops has at least n_rows entries by adding extra in-transit stops
    while len(gps_stops) < n_rows:
        stop_counter += 1
        zid = random.choice(zone_ids)
        zc = zone_configs[zid]
        dt = random.choice(operational_dates)
        hour = random.randint(6, 15)
        stop_time = dt.replace(hour=hour, minute=random.randint(0, 59),
                               second=random.randint(0, 59))
        gps_stops.append({
            "stop_id": f"GPS{str(stop_counter).zfill(6)}",
            "truck_id": zc["assigned_truck"],
            "latitude": round(zc["center_latitude"] + np.random.uniform(-0.015, 0.015), 6),
            "longitude": round(zc["center_longitude"] + np.random.uniform(-0.015, 0.015), 6),
            "stop_time": stop_time.strftime("%Y-%m-%d %H:%M:%S"),
            "stop_duration_sec": random.randint(5, 300),
        })

    # ------------------------------------------------------------------
    # 6. Bin lifts
    # ------------------------------------------------------------------
    bin_lifts = []
    lift_counter = 0
    for ev in pickup_events:
        if ev["outcome"] in ("full_miss", "excused_miss"):
            continue  # no lift at all
        lift_counter += 1
        dt = datetime.strptime(ev["date"], "%Y-%m-%d")
        hour = random.randint(6, 14)
        lift_time = dt.replace(hour=hour, minute=random.randint(0, 59),
                               second=random.randint(0, 59))
        successful = (ev["outcome"] == "success")
        weight = round(random.uniform(2.0, 35.0), 1) if successful else 0.0
        bin_lifts.append({
            "lift_id": f"LFT{str(lift_counter).zfill(6)}",
            "truck_id": ev["truck_id"],
            "bin_id": ev["bin_id"],
            "lift_time": lift_time.strftime("%Y-%m-%d %H:%M:%S"),
            "lift_successful": successful,
            "weight_kg": weight,
        })

    # Pad bin_lifts to n_rows with extra random entries if needed
    while len(bin_lifts) < n_rows:
        lift_counter += 1
        r = random.choice(residents)
        dt = random.choice(operational_dates)
        lift_time = dt.replace(hour=random.randint(6, 14), minute=random.randint(0, 59),
                               second=random.randint(0, 59))
        bin_lifts.append({
            "lift_id": f"LFT{str(lift_counter).zfill(6)}",
            "truck_id": zone_configs[r["zone_id"]]["assigned_truck"],
            "bin_id": r["bin_id"],
            "lift_time": lift_time.strftime("%Y-%m-%d %H:%M:%S"),
            "lift_successful": True,
            "weight_kg": round(random.uniform(2.0, 35.0), 1),
        })

    # ------------------------------------------------------------------
    # 7. Service requests
    # ------------------------------------------------------------------
    # Collect actual misses (full_miss and partial_miss on non-excused dates)
    actual_misses = [ev for ev in pickup_events
                     if ev["outcome"] in ("full_miss", "partial_miss")]
    # Also collect excused misses (for false-positive complaints)
    excused_misses = [ev for ev in pickup_events if ev["outcome"] == "excused_miss"]
    successes = [ev for ev in pickup_events if ev["outcome"] == "success"]

    service_requests = []
    req_counter = 0

    # Category A: missed_pickup + pending_review for actual misses
    miss_sample_size = min(int(n_rows * 0.25), len(actual_misses))
    chosen_actual = random.sample(actual_misses, miss_sample_size)
    for ev in chosen_actual:
        req_counter += 1
        sched = datetime.strptime(ev["date"], "%Y-%m-%d")
        reported = sched + timedelta(days=random.randint(0, 2))
        service_requests.append({
            "request_id": f"SR{str(req_counter).zfill(5)}",
            "resident_id": ev["resident_id"],
            "request_type": "missed_pickup",
            "reported_date": reported.strftime("%Y-%m-%d"),
            "scheduled_pickup_date": ev["date"],
            "description": fake.sentence(nb_words=8),
            "status": "pending_review",
        })

    # Category B: missed_pickup + pending_review for excused misses (should NOT be compensated)
    excused_sample_size = min(max(3, int(n_rows * 0.04)), len(excused_misses))
    if excused_misses:
        chosen_excused = random.sample(excused_misses, min(excused_sample_size, len(excused_misses)))
        for ev in chosen_excused:
            req_counter += 1
            sched = datetime.strptime(ev["date"], "%Y-%m-%d")
            reported = sched + timedelta(days=random.randint(0, 2))
            service_requests.append({
                "request_id": f"SR{str(req_counter).zfill(5)}",
                "resident_id": ev["resident_id"],
                "request_type": "missed_pickup",
                "reported_date": reported.strftime("%Y-%m-%d"),
                "scheduled_pickup_date": ev["date"],
                "description": fake.sentence(nb_words=8),
                "status": "pending_review",
            })

    # Category C: missed_pickup + pending_review for successes (false complaints)
    false_sample_size = min(max(2, int(n_rows * 0.03)), len(successes))
    chosen_false = random.sample(successes, false_sample_size)
    for ev in chosen_false:
        req_counter += 1
        sched = datetime.strptime(ev["date"], "%Y-%m-%d")
        reported = sched + timedelta(days=random.randint(0, 3))
        service_requests.append({
            "request_id": f"SR{str(req_counter).zfill(5)}",
            "resident_id": ev["resident_id"],
            "request_type": "missed_pickup",
            "reported_date": reported.strftime("%Y-%m-%d"),
            "scheduled_pickup_date": ev["date"],
            "description": fake.sentence(nb_words=8),
            "status": "pending_review",
        })

    # Category D: resolved/rejected missed_pickup (historical – used for repeat-miss checks)
    hist_sample = min(int(n_rows * 0.10), len(actual_misses))
    hist_events = random.sample(actual_misses, hist_sample)
    for ev in hist_events:
        req_counter += 1
        sched = datetime.strptime(ev["date"], "%Y-%m-%d")
        reported = sched + timedelta(days=random.randint(0, 2))
        service_requests.append({
            "request_id": f"SR{str(req_counter).zfill(5)}",
            "resident_id": ev["resident_id"],
            "request_type": "missed_pickup",
            "reported_date": reported.strftime("%Y-%m-%d"),
            "scheduled_pickup_date": ev["date"],
            "description": fake.sentence(nb_words=8),
            "status": random.choice(["resolved", "resolved", "rejected"]),
        })

    # Category E: other request types to fill up to n_rows
    other_types = ["damaged_bin", "schedule_inquiry", "extra_pickup", "bin_replacement"]
    while len(service_requests) < n_rows:
        req_counter += 1
        r = random.choice(residents)
        dt = random.choice(operational_dates)
        reported = dt + timedelta(days=random.randint(0, 5))
        service_requests.append({
            "request_id": f"SR{str(req_counter).zfill(5)}",
            "resident_id": r["resident_id"],
            "request_type": random.choice(other_types),
            "reported_date": reported.strftime("%Y-%m-%d"),
            "scheduled_pickup_date": dt.strftime("%Y-%m-%d"),
            "description": fake.sentence(nb_words=8),
            "status": random.choice(["pending_review", "resolved", "rejected"]),
        })

    # Shuffle to avoid ordering bias
    random.shuffle(service_requests)

    # ------------------------------------------------------------------
    # 8. Write database
    # ------------------------------------------------------------------
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS residents (
        resident_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        zone_id TEXT NOT NULL,
        service_tier TEXT NOT NULL,
        bin_id TEXT NOT NULL UNIQUE
    )""")
    for r in residents:
        cur.execute("INSERT INTO residents VALUES (?,?,?,?,?,?,?,?)",
                    (r["resident_id"], r["name"], r["address"],
                     r["latitude"], r["longitude"], r["zone_id"],
                     r["service_tier"], r["bin_id"]))

    cur.execute("""CREATE TABLE IF NOT EXISTS service_requests (
        request_id TEXT PRIMARY KEY,
        resident_id TEXT NOT NULL,
        request_type TEXT NOT NULL,
        reported_date TEXT NOT NULL,
        scheduled_pickup_date TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL,
        FOREIGN KEY (resident_id) REFERENCES residents(resident_id)
    )""")
    for sr in service_requests:
        cur.execute("INSERT INTO service_requests VALUES (?,?,?,?,?,?,?)",
                    (sr["request_id"], sr["resident_id"], sr["request_type"],
                     sr["reported_date"], sr["scheduled_pickup_date"],
                     sr["description"], sr["status"]))

    cur.execute("""CREATE TABLE IF NOT EXISTS gps_stops (
        stop_id TEXT PRIMARY KEY,
        truck_id TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        stop_time TEXT NOT NULL,
        stop_duration_sec INTEGER NOT NULL
    )""")
    for g in gps_stops:
        cur.execute("INSERT INTO gps_stops VALUES (?,?,?,?,?,?)",
                    (g["stop_id"], g["truck_id"], g["latitude"],
                     g["longitude"], g["stop_time"], g["stop_duration_sec"]))

    cur.execute("""CREATE TABLE IF NOT EXISTS bin_lifts (
        lift_id TEXT PRIMARY KEY,
        truck_id TEXT NOT NULL,
        bin_id TEXT NOT NULL,
        lift_time TEXT NOT NULL,
        lift_successful INTEGER NOT NULL,
        weight_kg REAL NOT NULL,
        FOREIGN KEY (bin_id) REFERENCES residents(bin_id)
    )""")
    for bl in bin_lifts:
        cur.execute("INSERT INTO bin_lifts VALUES (?,?,?,?,?,?)",
                    (bl["lift_id"], bl["truck_id"], bl["bin_id"],
                     bl["lift_time"], 1 if bl["lift_successful"] else 0,
                     bl["weight_kg"]))

    conn.commit()
    conn.close()

    # ------------------------------------------------------------------
    # 9. Fixed workspace files (not counted in SCALE)
    # ------------------------------------------------------------------

    # 9a. zone_boundaries.json
    zone_boundary_data = {}
    for zid, zc in zone_configs.items():
        zone_boundary_data[zid] = {
            "zone_id": zid,
            "assigned_truck": zc["assigned_truck"],
            "center_latitude": zc["center_latitude"],
            "center_longitude": zc["center_longitude"],
            "pickup_days": zc["pickup_days"],
        }
    with open(os.path.join(workspace, "zone_boundaries.json"), "w") as f:
        json.dump(zone_boundary_data, f, indent=2)

    # 9b. sla_terms.yaml
    sla_terms = {
        "service_tiers": {
            "basic": {
                "max_response_days": 7,
                "proximity_threshold_m": 150,
                "min_stop_duration_sec": 10,
                "pickup_window_start": "06:00",
                "pickup_window_end": "18:00",
            },
            "standard": {
                "max_response_days": 5,
                "proximity_threshold_m": 150,
                "min_stop_duration_sec": 10,
                "pickup_window_start": "06:00",
                "pickup_window_end": "18:00",
            },
            "premium": {
                "max_response_days": 3,
                "proximity_threshold_m": 150,
                "min_stop_duration_sec": 10,
                "pickup_window_start": "06:00",
                "pickup_window_end": "18:00",
            },
        },
        "general": {
            "excused_exception_codes": ["weather", "mechanical"],
            "advance_notice_required": True,
        }
    }
    with open(os.path.join(workspace, "sla_terms.yaml"), "w") as f:
        yaml.dump(sla_terms, f, default_flow_style=False, sort_keys=False)

    # 9c. compensation_rates.csv
    comp_rows = [
        {"service_tier": "basic", "base_credit": 5.00, "partial_miss_rate": 0.50,
         "full_miss_rate": 1.00, "repeat_miss_multiplier": 1.50},
        {"service_tier": "standard", "base_credit": 8.50, "partial_miss_rate": 0.50,
         "full_miss_rate": 1.00, "repeat_miss_multiplier": 1.50},
        {"service_tier": "premium", "base_credit": 15.00, "partial_miss_rate": 0.50,
         "full_miss_rate": 1.00, "repeat_miss_multiplier": 1.50},
    ]
    with open(os.path.join(workspace, "compensation_rates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["service_tier", "base_credit",
                                          "partial_miss_rate", "full_miss_rate",
                                          "repeat_miss_multiplier"])
        w.writeheader()
        w.writerows(comp_rows)

    # 9d. compensation_policy.md
    policy_text = """# Missed Pickup Compensation Policy

## Eligibility

A service request qualifies for compensation when ALL of the following hold:

1. The request type is "missed_pickup" and the current status is "pending_review".
2. The scheduled pickup date falls on a day the resident's zone is scheduled
   for collection (per zone boundary pickup-day configuration).
3. The date is NOT excused. A date is excused when the route log for that date
   shows an exception code of "weather" or "mechanical" for the resident's zone
   AND advance notice was given (advance_notice = true).
4. Verification of the miss via sensor data:
   - **Full miss**: No GPS truck stop within the proximity threshold of the
     resident's address on the scheduled date, OR no stop met the minimum
     duration requirement. In addition, no successful bin lift was recorded for
     the resident's bin on that date.
   - **Partial miss**: A GPS truck stop occurred within the proximity threshold
     with sufficient duration, but the bin lift sensor recorded an unsuccessful
     lift (lift_successful = false) or no lift at all for that bin on that date.
   - If GPS data confirms a stop near the address with sufficient duration AND
     a successful bin lift is recorded, the complaint is **invalid** (no
     compensation).

## Credit Calculation

1. Look up the resident's service tier in the compensation rates schedule.
2. Multiply the base_credit by the applicable miss rate:
   - full_miss_rate for a full miss
   - partial_miss_rate for a partial miss
3. Determine repeat-miss status: if the same resident has at least one other
   service request of type "missed_pickup" with status "resolved" whose
   scheduled_pickup_date falls within 30 calendar days before the current
   request's scheduled_pickup_date, apply the repeat_miss_multiplier.
4. The final credit is: base_credit × miss_rate × (repeat_miss_multiplier if
   repeat, else 1.0). Round to two decimal places.

## Output Requirements

Produce a CSV file named `refund_list.csv` with the following columns in order:
request_id, resident_id, resident_name, zone_id, service_tier,
scheduled_pickup_date, miss_type, base_credit, final_credit

Sort the CSV by request_id in ascending order. Include a header row.

Also state in your final response the total number of validated refund entries
and the total credit amount (sum of final_credit), formatted to two decimal
places.
"""
    with open(os.path.join(workspace, "compensation_policy.md"), "w") as f:
        f.write(policy_text)

    # ------------------------------------------------------------------
    # 10. Scaling workspace files  (route logs)
    # ------------------------------------------------------------------
    for idx, dt in enumerate(operational_dates):
        date_str = dt.strftime("%Y-%m-%d")
        day_name = DAY_NAMES[dt.weekday()]
        rows = []
        for zid in zone_ids:
            if day_name in zone_configs[zid]["pickup_days"]:
                exc = zone_date_excused.get((zid, date_str),
                                            {"excused": False,
                                             "exception_code": "none",
                                             "advance_notice": False})
                n_sched = len(zone_residents.get(zid, []))
                if exc["exception_code"] != "none":
                    completed = 0
                    route_status = "cancelled"
                else:
                    # Count successes + partial misses (truck ran)
                    completed = sum(
                        1 for ev in pickup_events
                        if ev["zone_id"] == zid and ev["date"] == date_str
                        and ev["outcome"] in ("success", "partial_miss")
                    )
                    route_status = "completed" if completed == n_sched else "partial"
                rows.append({
                    "date": date_str,
                    "truck_id": zone_configs[zid]["assigned_truck"],
                    "zone_id": zid,
                    "scheduled_stops": n_sched,
                    "completed_stops": completed,
                    "route_status": route_status,
                    "exception_code": exc["exception_code"],
                    "advance_notice": str(exc["advance_notice"]).lower(),
                })
            else:
                # Zone not scheduled on this day – still log it as not_scheduled
                rows.append({
                    "date": date_str,
                    "truck_id": zone_configs[zid]["assigned_truck"],
                    "zone_id": zid,
                    "scheduled_stops": 0,
                    "completed_stops": 0,
                    "route_status": "not_scheduled",
                    "exception_code": "none",
                    "advance_notice": "false",
                })

        fname = f"route_log_{date_str}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "date", "truck_id", "zone_id", "scheduled_stops",
                "completed_stops", "route_status", "exception_code",
                "advance_notice"])
            w.writeheader()
            w.writerows(rows)

    print(f"Database written to {db_path}")
    print(f"Workspace created at {workspace}/")
    print(f"  - {len(residents)} residents")
    print(f"  - {len(service_requests)} service requests")
    print(f"  - {len(gps_stops)} GPS stops")
    print(f"  - {len(bin_lifts)} bin lifts")
    print(f"  - {n_files} route log files + 4 fixed config files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
