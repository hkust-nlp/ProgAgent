"""
Water Distribution Leakage Detection - Data Generation Script
Generates database and workspace files for the leakage detection task.
"""

import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker


# ──────────────────── Scale Parameters ────────────────────
SCALE = {
    "rows_per_table": 120,       # v0 base; v1 = 2×, v2 = 4×, v3 = 8×
    "num_workspace_files": 10,   # v0 base; v1 = +N, v2 = +2N, v3 = +3N
}

# ──────────────────── Seed everything ────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ──────────────────── Derived counts ────────────────────
NUM_ZONES = max(SCALE["rows_per_table"] // 10, 8)
HOURS_MONITORED = 96  # 4 days of hourly data (>72h needed for consecutive check)
NUM_PIPES_BASE = SCALE["rows_per_table"]
NUM_WORK_ORDERS = SCALE["rows_per_table"]
NUM_PRESSURE_READINGS_PER_ZONE = HOURS_MONITORED
NUM_SCALABLE_FILES = SCALE["num_workspace_files"]

# Materials and properties
PIPE_MATERIALS = ["Cast Iron", "Ductile Iron", "PVC", "HDPE", "Steel", "Asbestos Cement", "Copper"]
WORK_ORDER_TYPES = ["Leak Repair", "Pipe Replacement", "Valve Maintenance", "Meter Calibration",
                    "Pressure Regulation", "Joint Sealing", "Flushing"]
WORK_ORDER_STATUSES = ["Open", "In Progress", "Completed", "Deferred"]
ZONE_PREFIXES = ["North", "South", "East", "West", "Central", "Upper", "Lower", "Inner", "Outer", "Mid"]
ZONE_SUFFIXES = ["Ridge", "Valley", "Heights", "Park", "Commons", "Crossing", "Springs", "Terrace", "Glen", "Meadow",
                 "Hills", "Creek", "Bluff", "Gate", "Bend", "Point", "Harbor", "Landing", "Hollow", "Grove"]


def generate_zone_names(n):
    names = set()
    while len(names) < n:
        names.add(f"{random.choice(ZONE_PREFIXES)} {random.choice(ZONE_SUFFIXES)}")
    return sorted(names)


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            zone_id INTEGER PRIMARY KEY,
            zone_name TEXT NOT NULL UNIQUE,
            district TEXT NOT NULL,
            area_sq_km REAL NOT NULL,
            population_served INTEGER NOT NULL,
            supply_source TEXT NOT NULL,
            commissioned_year INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS flow_readings (
            reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            inflow_m3 REAL NOT NULL,
            outflow_m3 REAL NOT NULL,
            billed_consumption_m3 REAL NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pressure_readings (
            reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            sensor_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            pressure_kpa REAL NOT NULL,
            anomaly_flag INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            pipe_id TEXT,
            created_date TEXT NOT NULL,
            completed_date TEXT,
            order_type TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            estimated_cost REAL,
            description TEXT,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    conn.commit()


def populate_zones(conn):
    districts = ["District A", "District B", "District C", "District D"]
    sources = ["Reservoir Alpha", "Reservoir Beta", "River Intake West", "River Intake East", "Groundwater Wells"]
    zone_names = generate_zone_names(NUM_ZONES)

    rows = []
    for i, name in enumerate(zone_names):
        rows.append((
            i + 1,
            name,
            districts[i % len(districts)],
            round(np.random.uniform(1.5, 12.0), 2),
            int(np.random.uniform(2000, 45000)),
            random.choice(sources),
            int(np.random.uniform(1960, 2015))
        ))
    conn.executemany(
        "INSERT INTO zones VALUES (?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return rows


def populate_flow_readings(conn, zones):
    """
    Generate hourly flow readings. Some zones will have persistent high leakage
    (>15% loss for >=72 consecutive hours).
    """
    # Decide which zones have persistent leakage
    n_leaky = max(3, NUM_ZONES // 4)
    leaky_zone_ids = sorted(random.sample(range(1, NUM_ZONES + 1), n_leaky))

    base_ts = pd.Timestamp("2025-03-10 00:00:00")
    rows = []

    for zone in zones:
        zone_id = zone[0]
        base_inflow = np.random.uniform(80, 300)  # m3/h base inflow

        for h in range(HOURS_MONITORED):
            ts = (base_ts + pd.Timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
            # Add some hourly variation
            hour_factor = 1.0 + 0.2 * np.sin(2 * np.pi * h / 24) + np.random.normal(0, 0.03)
            inflow = round(base_inflow * hour_factor, 2)

            if zone_id in leaky_zone_ids:
                # High leakage zone: loss 18-30%
                loss_pct = np.random.uniform(0.18, 0.30)
                # Make sure ALL 96 hours have high leakage (well above 72h)
                consumption_pct = np.random.uniform(0.35, 0.55)
                outflow_pct = 1.0 - loss_pct - consumption_pct
                if outflow_pct < 0.1:
                    outflow_pct = 0.1
                    consumption_pct = 1.0 - loss_pct - outflow_pct
            else:
                # Normal zone: loss 3-12%
                loss_pct = np.random.uniform(0.03, 0.12)
                consumption_pct = np.random.uniform(0.45, 0.65)
                outflow_pct = 1.0 - loss_pct - consumption_pct
                if outflow_pct < 0.1:
                    outflow_pct = 0.1
                    consumption_pct = 1.0 - loss_pct - outflow_pct

            outflow = round(inflow * outflow_pct, 2)
            consumption = round(inflow * consumption_pct, 2)
            rows.append((zone_id, ts, inflow, outflow, consumption))

    conn.executemany(
        "INSERT INTO flow_readings (zone_id, timestamp, inflow_m3, outflow_m3, billed_consumption_m3) VALUES (?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()
    return leaky_zone_ids


def populate_pressure_readings(conn, zones, leaky_zone_ids):
    base_ts = pd.Timestamp("2025-03-10 00:00:00")
    rows = []

    for zone in zones:
        zone_id = zone[0]
        base_pressure = np.random.uniform(280, 450)
        num_sensors = random.randint(2, 4)

        for s in range(num_sensors):
            sensor_id = f"PS-{zone_id:03d}-{s+1:02d}"
            for h in range(HOURS_MONITORED):
                ts = (base_ts + pd.Timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
                noise = np.random.normal(0, 8)
                pressure = round(base_pressure + noise, 2)

                # Leaky zones have more pressure anomalies
                if zone_id in leaky_zone_ids:
                    anomaly = 1 if (np.random.random() < 0.15 or pressure < base_pressure - 20) else 0
                else:
                    anomaly = 1 if np.random.random() < 0.03 else 0

                rows.append((zone_id, sensor_id, ts, pressure, anomaly))

    conn.executemany(
        "INSERT INTO pressure_readings (zone_id, sensor_id, timestamp, pressure_kpa, anomaly_flag) VALUES (?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()


def populate_work_orders(conn, zones):
    rows = []
    priorities = ["Low", "Medium", "High", "Critical"]

    for i in range(NUM_WORK_ORDERS):
        zone = random.choice(zones)
        zone_id = zone[0]
        created = fake.date_between(start_date="-2y", end_date="today")
        status = random.choice(WORK_ORDER_STATUSES)
        completed = None
        if status == "Completed":
            completed = fake.date_between(start_date=created, end_date="today")

        pipe_id = f"P-{zone_id:03d}-{random.randint(1, 50):04d}" if random.random() > 0.2 else None
        order_type = random.choice(WORK_ORDER_TYPES)
        priority = random.choice(priorities)
        cost = round(np.random.uniform(500, 50000), 2) if status in ["Completed", "In Progress"] else None

        rows.append((
            zone_id, pipe_id, str(created), str(completed) if completed else None,
            order_type, status, priority, cost,
            fake.sentence(nb_words=8)
        ))

    conn.executemany(
        "INSERT INTO work_orders (zone_id, pipe_id, created_date, completed_date, order_type, status, priority, estimated_cost, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()


def generate_pipe_inventory_files(workspace, zones):
    """Generate pipe inventory CSV files in workspace - these are the scalable files."""
    n_files = NUM_SCALABLE_FILES
    # Split: half pipe inventory CSVs, half maintenance logs
    n_pipe_files = max(n_files // 2, 1)
    n_maint_files = n_files - n_pipe_files

    # Distribute zones across pipe inventory files
    zone_ids = [z[0] for z in zones]
    zone_names_map = {z[0]: z[1] for z in zones}
    chunks = np.array_split(zone_ids, n_pipe_files)

    pipe_counter = 1
    for idx, chunk in enumerate(chunks):
        records = []
        for zid in chunk:
            n_pipes = random.randint(8, 25)
            for _ in range(n_pipes):
                pipe_id = f"P-{zid:03d}-{pipe_counter:04d}"
                pipe_counter += 1
                material = random.choice(PIPE_MATERIALS)
                install_year = random.randint(1955, 2020)
                diameter_mm = random.choice([100, 150, 200, 250, 300, 400, 500, 600])
                length_m = round(np.random.uniform(50, 2000), 1)
                condition_score = round(np.random.uniform(1.0, 10.0), 1)
                last_inspection = str(fake.date_between(start_date="-3y", end_date="today"))
                records.append({
                    "pipe_id": pipe_id,
                    "zone_id": int(zid),
                    "zone_name": zone_names_map[int(zid)],
                    "material": material,
                    "install_year": install_year,
                    "diameter_mm": diameter_mm,
                    "length_m": length_m,
                    "condition_score": condition_score,
                    "last_inspection_date": last_inspection
                })
        df = pd.DataFrame(records)
        df.to_csv(os.path.join(workspace, f"pipe_inventory_batch_{idx+1:03d}.csv"), index=False)

    # Generate maintenance log files
    for idx in range(n_maint_files):
        # Each maintenance log covers a subset of zones
        chunk = chunks[idx % len(chunks)]
        lines = []
        lines.append(f"MAINTENANCE LOG - Batch {idx+1}")
        lines.append(f"Report Period: 2024-01-01 to 2025-03-10")
        lines.append(f"Zones Covered: {', '.join(zone_names_map[int(z)] for z in chunk)}")
        lines.append("=" * 60)
        lines.append("")

        for zid in chunk:
            n_entries = random.randint(3, 8)
            lines.append(f"Zone: {zone_names_map[int(zid)]} (ID: {zid})")
            lines.append("-" * 40)
            for _ in range(n_entries):
                date = str(fake.date_between(start_date="-1y", end_date="today"))
                event_type = random.choice(["Leak detected", "Pipe burst", "Valve failure",
                                            "Pressure drop", "Meter malfunction", "Joint failure",
                                            "Corrosion found", "Scheduled inspection"])
                severity = random.choice(["Minor", "Moderate", "Severe"])
                lines.append(f"  [{date}] {event_type} - Severity: {severity}")
                lines.append(f"    Notes: {fake.sentence(nb_words=12)}")
            lines.append("")

        with open(os.path.join(workspace, f"maintenance_log_{idx+1:03d}.txt"), "w") as f:
            f.write("\n".join(lines))


def generate_config_files(workspace):
    """Generate fixed configuration files (not scaled)."""

    # 1. Leakage policy YAML
    policy = {
        "leakage_detection": {
            "loss_threshold_pct": 15.0,
            "consecutive_hours_required": 72,
            "monitoring_window_description": "Full available hourly dataset"
        },
        "priority_scoring": {
            "weights": {
                "avg_loss_rate": 0.30,
                "pipe_risk_score": 0.25,
                "pressure_anomaly_rate": 0.20,
                "open_work_orders_factor": 0.15,
                "population_impact": 0.10
            },
            "normalization": "min-max across flagged zones for each factor",
            "tie_breaking": "alphabetical by zone name ascending"
        },
        "repair_schedule": {
            "output_file": "repair_schedule.csv",
            "columns": [
                "priority_rank", "zone_id", "zone_name", "avg_loss_pct",
                "max_consecutive_hours_above_threshold", "pipe_risk_score",
                "pressure_anomaly_rate", "open_work_orders", "population_served",
                "composite_priority_score", "recommended_action"
            ],
            "recommended_actions": {
                "composite_score_gte_0.7": "Emergency Repair",
                "composite_score_gte_0.4": "Urgent Repair",
                "composite_score_lt_0.4": "Scheduled Maintenance"
            },
            "precision": "2 decimal places for all numeric fields"
        }
    }
    with open(os.path.join(workspace, "leakage_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. Material risk factors JSON
    risk_factors = {
        "material_risk_multipliers": {
            "Cast Iron": 1.8,
            "Asbestos Cement": 2.0,
            "Steel": 1.5,
            "Ductile Iron": 1.2,
            "PVC": 0.8,
            "HDPE": 0.6,
            "Copper": 1.0
        },
        "age_risk_formula": "For each pipe: age_factor = min((current_year - install_year) / 50, 2.0)",
        "condition_risk_formula": "condition_factor = (10 - condition_score) / 9.0",
        "pipe_risk_score_formula": "pipe_risk = mean of (material_multiplier * age_factor * condition_factor) across all pipes in zone",
        "current_year_for_calculation": 2025
    }
    with open(os.path.join(workspace, "material_risk_factors.json"), "w") as f:
        json.dump(risk_factors, f, indent=2)

    # 3. Zone district mapping CSV (supplementary info)
    # This just provides additional context not in DB
    district_info = pd.DataFrame({
        "district": ["District A", "District B", "District C", "District D"],
        "region": ["Northern Region", "Southern Region", "Eastern Region", "Western Region"],
        "water_authority": ["Metro Water Auth", "Metro Water Auth", "County Water Services", "County Water Services"],
        "emergency_contact": [fake.phone_number() for _ in range(4)]
    })
    district_info.to_csv(os.path.join(workspace, "district_contacts.csv"), index=False)


def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)

    # Create database
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    zones = populate_zones(conn)
    leaky_zone_ids = populate_flow_readings(conn, zones)
    populate_pressure_readings(conn, zones, leaky_zone_ids)
    populate_work_orders(conn, zones)
    conn.close()

    # Generate workspace files
    generate_pipe_inventory_files(workspace, zones)
    generate_config_files(workspace)

    print(f"Database created at: {db_path}")
    print(f"Workspace populated at: {workspace}")
    print(f"Total zones: {NUM_ZONES}")
    print(f"Leaky zones (IDs): {leaky_zone_ids}")
    print(f"Scalable files: {NUM_SCALABLE_FILES}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
