import argparse
import os
import sqlite3
import json
import yaml
import csv
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 120,
    "num_workspace_files": 24,
}

TARGET_DATE = "2026-04-25"
REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "Northwest"]
TIERS = ["firm", "interruptible", "spot"]
EQUIPMENT_TYPES = ["valve", "pump", "compressor"]
WEATHER_TYPES = ["clear", "rain", "snow", "wind", "ice_storm"]
PRIORITY_FLAGS = ["normal", "critical", "emergency"]

fake = Faker()
Faker.seed(42)
np.random.seed(42)


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS segments (
        segment_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        max_capacity_mmbtu REAL NOT NULL,
        region TEXT NOT NULL,
        diameter_inches REAL NOT NULL,
        length_miles REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS shippers (
        shipper_id TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        contract_tier TEXT NOT NULL,
        reliability_score REAL NOT NULL,
        contact_email TEXT NOT NULL,
        registration_date TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS reservations (
        reservation_id TEXT PRIMARY KEY,
        shipper_id TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        nominated_volume_mmbtu REAL NOT NULL,
        nomination_date TEXT NOT NULL,
        booking_date TEXT NOT NULL,
        status TEXT NOT NULL,
        priority_flag TEXT NOT NULL,
        FOREIGN KEY (shipper_id) REFERENCES shippers(shipper_id),
        FOREIGN KEY (segment_id) REFERENCES segments(segment_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS maintenance_events (
        event_id TEXT PRIMARY KEY,
        segment_id TEXT NOT NULL,
        equipment_type TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        capacity_reduction_pct REAL NOT NULL,
        description TEXT,
        FOREIGN KEY (segment_id) REFERENCES segments(segment_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS flow_volatility (
        record_id TEXT PRIMARY KEY,
        segment_id TEXT NOT NULL,
        period TEXT NOT NULL,
        mean_flow_mmbtu REAL NOT NULL,
        std_flow_mmbtu REAL NOT NULL,
        peak_flow_mmbtu REAL NOT NULL,
        volatility_index REAL NOT NULL,
        FOREIGN KEY (segment_id) REFERENCES segments(segment_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS weather_forecasts (
        forecast_id TEXT PRIMARY KEY,
        region TEXT NOT NULL,
        forecast_date TEXT NOT NULL,
        weather_type TEXT NOT NULL,
        severity INTEGER NOT NULL,
        wind_speed_mph REAL NOT NULL,
        temperature_f REAL NOT NULL,
        precipitation_inches REAL NOT NULL
    )""")
    conn.commit()


def generate_segments(n):
    segments = []
    for i in range(n):
        segments.append({
            "segment_id": f"SEG-{i+1:04d}",
            "name": f"{fake.city()}-{fake.city()} Lateral",
            "max_capacity_mmbtu": round(float(np.random.uniform(800, 4000)), 2),
            "region": REGIONS[i % len(REGIONS)],
            "diameter_inches": float(np.random.choice([12, 16, 20, 24, 30, 36])),
            "length_miles": round(float(np.random.uniform(15, 250)), 1),
        })
    return segments


def generate_shippers(n):
    shippers = []
    tier_probs = [0.4, 0.35, 0.25]
    for i in range(n):
        shippers.append({
            "shipper_id": f"SHP-{i+1:04d}",
            "company_name": fake.company(),
            "contract_tier": str(np.random.choice(TIERS, p=tier_probs)),
            "reliability_score": round(float(np.random.uniform(45, 100)), 1),
            "contact_email": fake.email(),
            "registration_date": fake.date_between(
                start_date="-5y", end_date="-1y"
            ).isoformat(),
        })
    return shippers


def generate_reservations(n, segments, shippers):
    reservations = []
    pending_count = 0
    for i in range(n):
        seg = segments[int(np.random.randint(0, len(segments)))]
        shp = shippers[int(np.random.randint(0, len(shippers)))]
        max_nom = seg["max_capacity_mmbtu"] * 0.35
        nominated = round(float(np.random.uniform(30, max(35, max_nom))), 2)
        # Ensure ~60% are pending
        if i < int(n * 0.6):
            status = "pending"
            pending_count += 1
        else:
            status = str(np.random.choice(["confirmed", "cancelled"]))
        # Priority flags: 70% normal, 20% critical, 10% emergency
        pf = str(np.random.choice(PRIORITY_FLAGS, p=[0.70, 0.20, 0.10]))
        reservations.append({
            "reservation_id": f"RES-{i+1:05d}",
            "shipper_id": shp["shipper_id"],
            "segment_id": seg["segment_id"],
            "nominated_volume_mmbtu": nominated,
            "nomination_date": TARGET_DATE,
            "booking_date": fake.date_between(
                start_date="-20d", end_date="-1d"
            ).isoformat(),
            "status": status,
            "priority_flag": pf,
        })
    return reservations


def generate_maintenance_events(n, segments):
    events = []
    for i in range(n):
        seg = segments[int(np.random.randint(0, len(segments)))]
        equip = str(np.random.choice(EQUIPMENT_TYPES))
        # About half overlap with TARGET_DATE
        if i % 2 == 0:
            start = fake.date_between(start_date="-10d", end_date="-2d").isoformat()
            end = fake.date_between(start_date="+1d", end_date="+15d").isoformat()
        else:
            start = fake.date_between(start_date="-60d", end_date="-30d").isoformat()
            end = fake.date_between(start_date="-29d", end_date="-5d").isoformat()
        reduction = round(float(np.random.uniform(3, 25)), 1)
        events.append({
            "event_id": f"MNT-{i+1:05d}",
            "segment_id": seg["segment_id"],
            "equipment_type": equip,
            "start_date": start,
            "end_date": end,
            "capacity_reduction_pct": reduction,
            "description": f"Scheduled {equip} maintenance on {seg['segment_id']}",
        })
    return events


def generate_flow_volatility(n, segments):
    records = []
    # Ensure every segment gets at least one record
    assigned = set()
    for i in range(n):
        if i < len(segments):
            seg = segments[i]
        else:
            seg = segments[int(np.random.randint(0, len(segments)))]
        assigned.add(seg["segment_id"])
        vol_idx = round(float(np.random.uniform(0.03, 0.50)), 4)
        mean_flow = round(float(np.random.uniform(200, seg["max_capacity_mmbtu"] * 0.8)), 2)
        std_flow = round(mean_flow * vol_idx, 2)
        peak_flow = round(mean_flow + 2 * std_flow, 2)
        records.append({
            "record_id": f"FLW-{i+1:05d}",
            "segment_id": seg["segment_id"],
            "period": "2026-Q1",
            "mean_flow_mmbtu": mean_flow,
            "std_flow_mmbtu": std_flow,
            "peak_flow_mmbtu": peak_flow,
            "volatility_index": vol_idx,
        })
    return records


def generate_weather_forecasts(n, regions):
    forecasts = []
    # Ensure every region has at least one forecast for TARGET_DATE
    for i in range(n):
        region = regions[i % len(regions)]
        if i < len(regions):
            fdate = TARGET_DATE
        else:
            fdate = fake.date_between(start_date="-5d", end_date="+5d").isoformat()
        severity = int(np.random.randint(1, 6))
        forecasts.append({
            "forecast_id": f"WX-{i+1:05d}",
            "region": region,
            "forecast_date": fdate,
            "weather_type": str(np.random.choice(WEATHER_TYPES)),
            "severity": severity,
            "wind_speed_mph": round(float(np.random.uniform(0, 80)), 1),
            "temperature_f": round(float(np.random.uniform(10, 95)), 1),
            "precipitation_inches": round(float(np.random.uniform(0, 5)), 2),
        })
    return forecasts


def write_db(conn, segments, shippers, reservations, maintenance, volatility, weather):
    pd.DataFrame(segments).to_sql("segments", conn, if_exists="replace", index=False)
    pd.DataFrame(shippers).to_sql("shippers", conn, if_exists="replace", index=False)
    pd.DataFrame(reservations).to_sql("reservations", conn, if_exists="replace", index=False)
    pd.DataFrame(maintenance).to_sql("maintenance_events", conn, if_exists="replace", index=False)
    pd.DataFrame(volatility).to_sql("flow_volatility", conn, if_exists="replace", index=False)
    pd.DataFrame(weather).to_sql("weather_forecasts", conn, if_exists="replace", index=False)


def write_workspace(workspace, segments, shippers, reservations, maintenance, volatility):
    os.makedirs(workspace, exist_ok=True)

    n_files = SCALE["num_workspace_files"]
    n_csv = max(1, n_files * 3 // 8)
    n_json = max(1, n_files * 2 // 8)
    n_yaml = max(1, n_files * 2 // 8)
    n_txt = max(1, n_files - n_csv - n_json - n_yaml)

    # --- Pending reservations ---
    pending = [r for r in reservations if r["status"] == "pending"]

    # --- 1. Reservation batch CSVs ---
    batch_size = max(1, len(pending) // n_csv)
    for idx in range(n_csv):
        start = idx * batch_size
        if idx == n_csv - 1:
            batch = pending[start:]
        else:
            batch = pending[start:start + batch_size]
        fpath = os.path.join(workspace, f"reservation_batch_{idx+1:03d}.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "reservation_id", "shipper_id", "segment_id",
                "nominated_volume_mmbtu", "nomination_date",
            ])
            writer.writeheader()
            for r in batch:
                writer.writerow({
                    "reservation_id": r["reservation_id"],
                    "shipper_id": r["shipper_id"],
                    "segment_id": r["segment_id"],
                    "nominated_volume_mmbtu": f"{r['nominated_volume_mmbtu']:.2f}",
                    "nomination_date": r["nomination_date"],
                })

    # --- 2. Priority flag JSONs ---
    pf_batch_size = max(1, len(pending) // n_json)
    for idx in range(n_json):
        start = idx * pf_batch_size
        if idx == n_json - 1:
            batch = pending[start:]
        else:
            batch = pending[start:start + pf_batch_size]
        data = {r["reservation_id"]: r["priority_flag"] for r in batch}
        fpath = os.path.join(workspace, f"priority_flags_{idx+1:03d}.json")
        with open(fpath, "w") as f:
            json.dump(data, f, indent=2)

    # --- 3. Equipment age factor YAMLs ---
    seg_ids = [s["segment_id"] for s in segments]
    np.random.shuffle(seg_ids)
    eq_batch_size = max(1, len(seg_ids) // n_yaml)
    for idx in range(n_yaml):
        start = idx * eq_batch_size
        if idx == n_yaml - 1:
            batch = seg_ids[start:]
        else:
            batch = seg_ids[start:start + eq_batch_size]
        data = {}
        for sid in batch:
            data[sid] = {
                "equipment_age_factor": round(float(np.random.uniform(1.0, 1.5)), 2),
            }
        fpath = os.path.join(workspace, f"equipment_factors_{idx+1:03d}.yaml")
        with open(fpath, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    # --- 4. Regulatory limit TXTs ---
    # ~30% of segments have regulatory limits
    reg_segments = [s for s in segments if np.random.random() < 0.3]
    reg_batch_size = max(1, len(reg_segments) // n_txt) if reg_segments else 1
    for idx in range(n_txt):
        fpath = os.path.join(workspace, f"regulatory_limits_{idx+1:03d}.txt")
        start = idx * reg_batch_size
        if idx == n_txt - 1:
            batch = reg_segments[start:]
        else:
            batch = reg_segments[start:start + reg_batch_size]
        with open(fpath, "w") as f:
            f.write("# Regulatory Capacity Limits\n")
            f.write("# Format: SEGMENT_ID | LIMIT_MMBTU\n")
            f.write("#" + "=" * 40 + "\n")
            for s in batch:
                limit = round(s["max_capacity_mmbtu"] * float(np.random.uniform(0.60, 0.90)), 2)
                f.write(f"{s['segment_id']} | {limit:.2f}\n")

    # --- Fixed config: allocation_policy.yaml ---
    policy = {
        "target_date": TARGET_DATE,
        "allocation_order": ["firm", "interruptible", "spot"],
        "tier_priority_rank": {"firm": 1, "interruptible": 2, "spot": 3},
        "priority_flag_rank": {"emergency": 0, "critical": 1, "normal": 2},
        "tiebreaker": "reliability_score",
        "tiebreaker_order": "descending",
        "final_tiebreaker": "reservation_id",
        "final_tiebreaker_order": "ascending",
        "volatility_thresholds": {
            "low_max": 0.15,
            "moderate_max": 0.30,
        },
        "volatility_safety_margins": {
            "low": 0.02,
            "moderate": 0.05,
            "high": 0.10,
        },
        "weather_severity_adjustments": {
            1: 0.00,
            2: 0.03,
            3: 0.07,
            4: 0.12,
            5: 0.20,
        },
        "maintenance_reduction_cap": 0.80,
        "capacity_rounding_decimals": 2,
    }
    with open(os.path.join(workspace, "allocation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]

    segments = generate_segments(n)
    shippers = generate_shippers(n)
    reservations = generate_reservations(n, segments, shippers)
    maintenance = generate_maintenance_events(n, segments)
    volatility = generate_flow_volatility(n, segments)
    weather = generate_weather_forecasts(n, REGIONS)

    write_db(conn, segments, shippers, reservations, maintenance, volatility, weather)
    conn.close()

    write_workspace(args.workspace, segments, shippers, reservations, maintenance, volatility)

    print(f"Database created at {args.db_path}")
    print(f"Workspace initialized at {args.workspace}")
    pending_count = sum(1 for r in reservations if r["status"] == "pending")
    print(f"Total reservations: {len(reservations)}, Pending: {pending_count}")


if __name__ == "__main__":
    main()
