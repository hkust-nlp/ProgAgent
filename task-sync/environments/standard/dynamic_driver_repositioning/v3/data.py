#!/usr/bin/env python3
"""Data generation for driver dispatch optimization task."""

import argparse
import sqlite3
import os
import json
import random
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

# ── Constants ──
CURRENT_HOUR = 14
CATEGORIES = ["transit_hub", "commercial", "entertainment", "residential"]
PRIORITY_MULTIPLIERS = {
    "transit_hub": 1.5,
    "commercial": 1.3,
    "entertainment": 1.2,
    "residential": 1.0,
}
VEHICLE_TYPES = ["sedan", "suv", "van"]
RIDE_TYPES = ["standard", "premium", "shared"]


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]
    num_zones = max(10, rows // 8)

    zones = [f"Z{i+1:02d}" for i in range(num_zones)]
    zone_to_cat = {z: CATEGORIES[i % len(CATEGORIES)] for i, z in enumerate(zones)}

    # ═══════════════════════════════════════════
    # 1. Generate ride_requests
    # ═══════════════════════════════════════════
    requests_data = []
    for i in range(rows):
        request_id = f"R{i+1:04d}"
        passenger_name = fake.name()
        pickup_zone = zones[int(np.random.randint(0, len(zones)))]
        dropoff_candidates = [z for z in zones if z != pickup_zone]
        dropoff_zone = dropoff_candidates[int(np.random.randint(0, len(dropoff_candidates)))]
        hour = int(np.random.randint(13, 16))
        minute = int(np.random.randint(0, 60))
        request_time = f"2026-05-08 {hour:02d}:{minute:02d}"
        wait_tolerance = int(np.random.randint(5, 31))
        ride_type = str(np.random.choice(RIDE_TYPES, p=[0.50, 0.30, 0.20]))
        status = str(np.random.choice(["pending", "assigned", "completed"], p=[0.45, 0.25, 0.30]))
        passenger_rating = round(float(np.random.uniform(3.0, 5.0)), 1)
        requests_data.append({
            "request_id": request_id,
            "passenger_name": passenger_name,
            "pickup_zone": pickup_zone,
            "dropoff_zone": dropoff_zone,
            "request_time": request_time,
            "wait_tolerance_min": wait_tolerance,
            "ride_type": ride_type,
            "status": status,
            "passenger_rating": passenger_rating,
        })

    # ═══════════════════════════════════════════
    # 2. Generate drivers
    # ═══════════════════════════════════════════
    drivers_data = []
    for i in range(rows):
        driver_id = f"D{i+1:04d}"
        driver_name = fake.name()
        current_zone = zones[i % len(zones)]
        status = str(np.random.choice(
            ["available", "en_route", "busy", "offline"],
            p=[0.65, 0.10, 0.15, 0.10],
        ))
        vehicle_type = str(np.random.choice(VEHICLE_TYPES, p=[0.40, 0.30, 0.30]))
        driver_rating = round(float(np.random.uniform(3.5, 5.0)), 2)
        shift_end_hour = int(np.random.randint(16, 24))
        shift_end_time = f"2026-05-08 {shift_end_hour:02d}:00"
        completed_rides = int(np.random.randint(0, 20))
        drivers_data.append({
            "driver_id": driver_id,
            "driver_name": driver_name,
            "current_zone": current_zone,
            "status": status,
            "vehicle_type": vehicle_type,
            "driver_rating": driver_rating,
            "shift_end_time": shift_end_time,
            "completed_rides_today": completed_rides,
        })

    # ═══════════════════════════════════════════
    # 3. Generate demand_heatmap
    # ═══════════════════════════════════════════
    demand_data = []
    used_pairs = set()
    record_id = 0
    zone_demand_at_current = {}

    for z in zones:
        record_id += 1
        avg_req = int(np.random.randint(5, 50))
        peak_req = avg_req + int(np.random.randint(5, 20))
        avg_wait = round(float(np.random.uniform(2, 15)), 1)
        demand_data.append({
            "record_id": record_id,
            "zone_id": z,
            "hour": CURRENT_HOUR,
            "avg_requests": avg_req,
            "peak_requests": peak_req,
            "avg_wait_time_min": avg_wait,
        })
        zone_demand_at_current[z] = avg_req
        used_pairs.add((z, CURRENT_HOUR))

    other_hours = [h for h in range(6, 22) if h != CURRENT_HOUR]
    attempts = 0
    while len(demand_data) < rows and attempts < rows * 10:
        attempts += 1
        z = zones[int(np.random.randint(0, len(zones)))]
        h = int(other_hours[int(np.random.randint(0, len(other_hours)))])
        if (z, h) in used_pairs:
            continue
        used_pairs.add((z, h))
        record_id += 1
        avg_req = int(np.random.randint(5, 50))
        peak_req = avg_req + int(np.random.randint(5, 20))
        avg_wait = round(float(np.random.uniform(2, 15)), 1)
        demand_data.append({
            "record_id": record_id,
            "zone_id": z,
            "hour": h,
            "avg_requests": avg_req,
            "peak_requests": peak_req,
            "avg_wait_time_min": avg_wait,
        })

    # ═══════════════════════════════════════════
    # 4. Generate traffic_flow
    # ═══════════════════════════════════════════
    all_pairs = [(z1, z2) for z1 in zones for z2 in zones if z1 != z2]
    pair_list = list(all_pairs)
    np.random.shuffle(pair_list)

    traffic_data = []
    selected_pairs = pair_list[:min(rows, len(pair_list))]
    traffic_pair_set = set()

    for i, (z1, z2) in enumerate(selected_pairs):
        seg_id = i + 1
        normal_time = round(float(np.random.uniform(5, 25)), 1)
        congestion = round(float(np.random.uniform(1.0, 2.0)), 2)
        current_time = round(normal_time * congestion, 1)
        traffic_data.append({
            "segment_id": seg_id,
            "from_zone": z1,
            "to_zone": z2,
            "current_travel_min": current_time,
            "normal_travel_min": normal_time,
            "congestion_factor": congestion,
        })
        traffic_pair_set.add((z1, z2))

    while len(traffic_data) < rows:
        idx = int(np.random.randint(0, len(pair_list)))
        z1, z2 = pair_list[idx]
        if (z1, z2) in traffic_pair_set:
            continue
        traffic_pair_set.add((z1, z2))
        seg_id = len(traffic_data) + 1
        normal_time = round(float(np.random.uniform(5, 25)), 1)
        congestion = round(float(np.random.uniform(1.0, 2.0)), 2)
        current_time = round(normal_time * congestion, 1)
        traffic_data.append({
            "segment_id": seg_id,
            "from_zone": z1,
            "to_zone": z2,
            "current_travel_min": current_time,
            "normal_travel_min": normal_time,
            "congestion_factor": congestion,
        })

    # ═══════════════════════════════════════════
    # 5. Write database
    # ═══════════════════════════════════════════
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE ride_requests (
        request_id TEXT PRIMARY KEY,
        passenger_name TEXT,
        pickup_zone TEXT,
        dropoff_zone TEXT,
        request_time TEXT,
        wait_tolerance_min INTEGER,
        ride_type TEXT,
        status TEXT,
        passenger_rating REAL
    )""")
    for r in requests_data:
        c.execute(
            "INSERT INTO ride_requests VALUES (?,?,?,?,?,?,?,?,?)",
            (r["request_id"], r["passenger_name"], r["pickup_zone"],
             r["dropoff_zone"], r["request_time"], r["wait_tolerance_min"],
             r["ride_type"], r["status"], r["passenger_rating"]),
        )

    c.execute("""CREATE TABLE drivers (
        driver_id TEXT PRIMARY KEY,
        driver_name TEXT,
        current_zone TEXT,
        status TEXT,
        vehicle_type TEXT,
        driver_rating REAL,
        shift_end_time TEXT,
        completed_rides_today INTEGER
    )""")
    for d in drivers_data:
        c.execute(
            "INSERT INTO drivers VALUES (?,?,?,?,?,?,?,?)",
            (d["driver_id"], d["driver_name"], d["current_zone"],
             d["status"], d["vehicle_type"], d["driver_rating"],
             d["shift_end_time"], d["completed_rides_today"]),
        )

    c.execute("""CREATE TABLE demand_heatmap (
        record_id INTEGER PRIMARY KEY,
        zone_id TEXT,
        hour INTEGER,
        avg_requests INTEGER,
        peak_requests INTEGER,
        avg_wait_time_min REAL
    )""")
    for d in demand_data:
        c.execute(
            "INSERT INTO demand_heatmap VALUES (?,?,?,?,?,?)",
            (d["record_id"], d["zone_id"], d["hour"],
             d["avg_requests"], d["peak_requests"], d["avg_wait_time_min"]),
        )

    c.execute("""CREATE TABLE traffic_flow (
        segment_id INTEGER PRIMARY KEY,
        from_zone TEXT,
        to_zone TEXT,
        current_travel_min REAL,
        normal_travel_min REAL,
        congestion_factor REAL
    )""")
    for t in traffic_data:
        c.execute(
            "INSERT INTO traffic_flow VALUES (?,?,?,?,?,?)",
            (t["segment_id"], t["from_zone"], t["to_zone"],
             t["current_travel_min"], t["normal_travel_min"],
             t["congestion_factor"]),
        )

    conn.commit()
    conn.close()

    # ═══════════════════════════════════════════
    # 6. Generate workspace files
    # ═══════════════════════════════════════════
    _generate_workspace(
        workspace, zones, zone_to_cat, drivers_data, requests_data,
        zone_demand_at_current, traffic_data, traffic_pair_set, num_files, num_zones, rows,
    )


def _generate_workspace(workspace, zones, zone_to_cat, drivers_data, requests_data,
                        zone_demand_at_current, traffic_data, traffic_pair_set,
                        num_files, num_zones, rows):
    import yaml

    # ── Fixed policy files ──

    policy = {
        "weights": {
            "demand": 0.35,
            "urgency": 0.30,
            "zone_priority": 0.20,
            "passenger_rating": 0.15,
        },
        "normalization": {
            "max_wait_tolerance_cap": 30,
            "current_hour": CURRENT_HOUR,
        },
        "thresholds": {
            "oversupply_ratio": 1.5,
            "closure_penalty_factor": 3.0,
            "same_zone_pickup_min": 3,
            "default_travel_min": 20,
        },
        "output": {
            "priority_decimal_places": 4,
            "time_decimal_places": 1,
        },
    }
    with open(os.path.join(workspace, "dispatch_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    zone_cat_data = {}
    for z in zones:
        cat = zone_to_cat[z]
        zone_cat_data[z] = {
            "category": cat,
            "priority_multiplier": PRIORITY_MULTIPLIERS[cat],
        }
    with open(os.path.join(workspace, "zone_categories.json"), "w") as f:
        json.dump(zone_cat_data, f, indent=2)

    vehicle_rules = {
        "vehicle_matching": {
            "standard": ["sedan", "suv", "van"],
            "premium": ["sedan", "suv"],
            "shared": ["van", "sedan"],
        },
        "minimum_driver_rating": {
            "standard": 3.5,
            "premium": 4.2,
            "shared": 3.5,
        },
    }
    with open(os.path.join(workspace, "vehicle_rules.yaml"), "w") as f:
        yaml.dump(vehicle_rules, f, default_flow_style=False, sort_keys=False)

    # ── Scalable file counts ──
    files_per_type = num_files // 4
    remainder = num_files % 4
    type_counts = [files_per_type] * 4
    for i in range(remainder):
        type_counts[i] += 1
    n_demand_reports, n_traffic_bulletins, n_driver_shifts, n_demand_forecasts = type_counts

    # ── Surge events ──
    num_event_zones = max(3, num_zones // 3)
    event_zone_indices = sorted(
        np.random.choice(len(zones), size=num_event_zones, replace=False)
    )
    event_zones = [zones[int(i)] for i in event_zone_indices]

    event_descriptions = [
        "Concert at main arena", "Sports championship game", "Food festival",
        "Tech conference", "Holiday shopping rush", "University graduation",
        "Marathon route nearby", "Night market event", "Music festival",
        "Corporate event cluster", "Trade show", "Theater premiere",
        "Restaurant week rush", "Art gallery opening night", "Community fair",
        "Charity gala event", "Wedding season peak", "Airport delay spillover",
        "Convention center expo", "Street parade nearby",
    ]

    surge_factors = {}
    for i, z in enumerate(event_zones):
        surge_factors[z] = {
            "event": event_descriptions[i % len(event_descriptions)],
            "surge_factor": round(float(np.random.uniform(1.2, 2.0)), 1),
        }

    # ── Zone demand report MDs ──
    zones_per_report = max(1, math.ceil(len(zones) / n_demand_reports))
    for report_idx in range(n_demand_reports):
        start = report_idx * zones_per_report
        if report_idx == n_demand_reports - 1:
            batch_zones = zones[start:]
        else:
            batch_zones = zones[start:start + zones_per_report]

        lines = [f"## Zone Demand Adjustments - Report {report_idx + 1}\n"]
        lines.append(
            f"Current conditions as of 2026-05-08 {CURRENT_HOUR}:00. "
            "The table below lists each zone with its active event status and "
            "the corresponding surge factor to apply to the historical baseline demand.\n"
        )
        lines.append("| Zone | Active Event | Surge Factor |")
        lines.append("|------|-------------|--------------|")
        for z in batch_zones:
            if z in surge_factors:
                ev = surge_factors[z]["event"]
                sf = surge_factors[z]["surge_factor"]
            else:
                ev = "-"
                sf = 1.0
            lines.append(f"| {z} | {ev} | {sf} |")

        lines.append("\n### Operational Notes\n")
        has_events = False
        for z in batch_zones:
            if z in surge_factors:
                has_events = True
                lines.append(
                    f"- {z}: {surge_factors[z]['event']} is expected to drive elevated "
                    f"demand in the area. Additional driver allocation recommended to "
                    f"maintain acceptable wait times.\n"
                )
        if not has_events:
            lines.append(
                "- No significant events affecting demand in these zones at this time.\n"
            )

        filepath = os.path.join(workspace, f"zone_demand_report_{report_idx + 1:02d}.md")
        with open(filepath, "w") as f:
            f.write("\n".join(lines))

    # ── Closures ──
    num_closures = max(2, num_zones // 4)
    traffic_pairs_list = list(traffic_pair_set)
    np.random.shuffle(traffic_pairs_list)
    closure_pairs = traffic_pairs_list[:num_closures]

    closure_reasons = [
        "emergency water main repair", "accident investigation",
        "road construction", "gas leak emergency", "power line repair",
        "sinkhole mitigation", "bridge inspection", "utility maintenance",
        "fire department operations", "hazmat cleanup",
    ]

    # ── Traffic bulletin TXTs ──
    closures_per_bulletin = max(1, math.ceil(len(closure_pairs) / n_traffic_bulletins))
    for bulletin_idx in range(n_traffic_bulletins):
        start = bulletin_idx * closures_per_bulletin
        if bulletin_idx == n_traffic_bulletins - 1:
            batch_closures = closure_pairs[start:]
        else:
            batch_closures = closure_pairs[start:start + closures_per_bulletin]

        lines = [f"TRAFFIC BULLETIN #{bulletin_idx + 1}"]
        lines.append(f"Issued: 2026-05-08 {CURRENT_HOUR}:00\n")
        lines.append("Current road conditions and active closures follow.\n")

        if batch_closures:
            lines.append("ROAD CLOSURES:\n")
            for (z1, z2) in batch_closures:
                reason = closure_reasons[int(np.random.randint(0, len(closure_reasons)))]
                reopen = int(np.random.randint(18, 23))
                lines.append(
                    f"The route from Zone {z1} to Zone {z2} is currently CLOSED "
                    f"due to {reason}. Expect significant delays or full detour required."
                )
                lines.append(f"Estimated reopening: 2026-05-08 {reopen:02d}:00.\n")
        else:
            lines.append("No active road closures reported for this sector.\n")

        lines.append("GENERAL CONDITIONS:")
        lines.append("Moderate congestion observed across commercial zones during peak hours.")
        lines.append("Residential areas experiencing normal flow patterns.")
        lines.append(f"Transit hub zones showing elevated activity around hour {CURRENT_HOUR}.")

        filepath = os.path.join(workspace, f"traffic_bulletin_{bulletin_idx + 1:02d}.txt")
        with open(filepath, "w") as f:
            f.write("\n".join(lines))

    # ── Overtime flags ──
    available_drivers = [d for d in drivers_data if d["status"] == "available"]
    n_overtime = max(2, len(available_drivers) // 6)
    overtime_indices = sorted(
        np.random.choice(
            len(available_drivers),
            size=min(n_overtime, len(available_drivers)),
            replace=False,
        )
    )
    overtime_driver_ids = set(
        available_drivers[int(i)]["driver_id"] for i in overtime_indices
    )

    # ── Driver shift CSVs ──
    drivers_per_file = max(1, math.ceil(len(drivers_data) / n_driver_shifts))
    for shift_idx in range(n_driver_shifts):
        start = shift_idx * drivers_per_file
        if shift_idx == n_driver_shifts - 1:
            batch_drivers = drivers_data[start:]
        else:
            batch_drivers = drivers_data[start:start + drivers_per_file]

        csv_rows = []
        for d in batch_drivers:
            overtime = 1 if d["driver_id"] in overtime_driver_ids else 0
            if overtime:
                hours_worked = round(float(np.random.uniform(10, 14)), 1)
            else:
                hours_worked = round(float(np.random.uniform(2, 8)), 1)
            shift_start_h = max(6, CURRENT_HOUR - int(hours_worked))
            csv_rows.append({
                "driver_id": d["driver_id"],
                "shift_date": "2026-05-08",
                "shift_start": f"{shift_start_h:02d}:00",
                "shift_end": d["shift_end_time"].split(" ")[1],
                "hours_worked": hours_worked,
                "overtime_flag": overtime,
            })

        df = pd.DataFrame(csv_rows)
        filepath = os.path.join(workspace, f"driver_shift_{shift_idx + 1:02d}.csv")
        df.to_csv(filepath, index=False)

    # ── Demand forecast JSONs ──
    zones_per_forecast = max(1, math.ceil(len(zones) / n_demand_forecasts))
    for forecast_idx in range(n_demand_forecasts):
        start = forecast_idx * zones_per_forecast
        if forecast_idx == n_demand_forecasts - 1:
            batch_zones = zones[start:]
        else:
            batch_zones = zones[start:start + zones_per_forecast]

        forecast = {
            "forecast_period": f"2026-05-08 {CURRENT_HOUR}:00-{CURRENT_HOUR + 1}:00",
            "model_version": "v2.3.1",
            "zones": {},
        }
        for z in batch_zones:
            # Forecast represents expected ride requests in the next hour
            # scaled to be comparable with per-zone driver supply levels
            avg_drivers_per_zone = max(1, rows // (num_zones * 2))
            predicted = max(1, int(np.random.randint(1, avg_drivers_per_zone + 3)))
            forecast["zones"][z] = {
                "predicted_requests": int(predicted),
                "confidence": round(float(np.random.uniform(0.70, 0.95)), 2),
            }

        filepath = os.path.join(workspace, f"demand_forecast_{forecast_idx + 1:02d}.json")
        with open(filepath, "w") as f:
            json.dump(forecast, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
