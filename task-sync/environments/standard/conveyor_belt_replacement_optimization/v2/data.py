"""
Data generation for conveyor belt replacement optimization task.
Generates SQLite database and workspace files with IoT sensor data,
component lifespan logs, production schedules, and supplier catalog.
"""

import argparse
import json
import os
import sqlite3
import random
import csv
import yaml

import numpy as np
import pandas as pd
from faker import Faker

# ── Scale parameters (only this block changes across v0→v3) ──────────────
SCALE = {
    "rows_per_table": 400,       # v2 = 4× base
    "num_workspace_files": 30,   # v2 = base + 2N (N=10)
}

# ── Deterministic seeds ──────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ─────────────────────────────────────────────────────
BELT_TYPES = ["heavy-duty-rubber", "steel-cord", "fabric-ply", "modular-plastic", "chevron-rubber"]
MANUFACTURERS = ["ContiTech", "Fenner Dunlop", "Bridgestone", "Habasit", "Ammeraal Beltech",
                 "Intralox", "Forbo", "Volta Belting", "Sparks Belting", "Bando Chemical"]
SHIFTS = ["morning", "afternoon", "night"]
PRODUCT_TYPES = ["automotive-parts", "electronics", "food-packaging", "chemicals", "raw-materials",
                 "consumer-goods", "pharmaceuticals", "textiles"]
FAILURE_MODES = ["surface-cracking", "edge-wear", "splice-failure", "belt-tracking",
                 "material-fatigue", "heat-damage", "chemical-degradation", "abrasion-wear"]
COMPONENT_TYPES = ["belt-surface", "belt-core", "splice-joint", "edge-seal", "tracking-guide"]

# Vibration thresholds (used in data gen to create realistic distributions)
WARNING_THRESHOLDS = {
    "heavy-duty-rubber": 7.5,
    "steel-cord": 6.0,
    "fabric-ply": 8.0,
    "modular-plastic": 5.5,
    "chevron-rubber": 7.0,
}
CRITICAL_THRESHOLDS = {
    "heavy-duty-rubber": 12.0,
    "steel-cord": 10.0,
    "fabric-ply": 13.0,
    "modular-plastic": 9.0,
    "chevron-rubber": 11.5,
}

# Average expected lifespans (hours) per belt type
EXPECTED_LIFESPANS = {
    "heavy-duty-rubber": 22000,
    "steel-cord": 30000,
    "fabric-ply": 18000,
    "modular-plastic": 15000,
    "chevron-rubber": 25000,
}

PLANNING_REF_DATE = "2025-07-01"


def create_tables(conn):
    """Create all database tables."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conveyor_belts (
            belt_id TEXT PRIMARY KEY,
            line_id TEXT NOT NULL,
            belt_type TEXT NOT NULL,
            manufacturer TEXT NOT NULL,
            install_date TEXT NOT NULL,
            operating_hours INTEGER NOT NULL,
            length_meters REAL NOT NULL,
            width_mm INTEGER NOT NULL,
            status TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vibration_readings (
            reading_id TEXT PRIMARY KEY,
            belt_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            rms_velocity_mm_s REAL NOT NULL,
            peak_acceleration_g REAL NOT NULL,
            dominant_freq_hz REAL NOT NULL,
            bearing_temp_c REAL NOT NULL,
            FOREIGN KEY (belt_id) REFERENCES conveyor_belts(belt_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS component_lifespan_logs (
            log_id TEXT PRIMARY KEY,
            belt_type TEXT NOT NULL,
            component_type TEXT NOT NULL,
            install_date TEXT NOT NULL,
            failure_date TEXT NOT NULL,
            hours_at_failure INTEGER NOT NULL,
            failure_mode TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS production_schedules (
            schedule_id TEXT PRIMARY KEY,
            line_id TEXT NOT NULL,
            date TEXT NOT NULL,
            shift TEXT NOT NULL,
            product_type TEXT NOT NULL,
            throughput_units_hr REAL NOT NULL,
            priority_level INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS supplier_catalog (
            catalog_id TEXT PRIMARY KEY,
            supplier_id TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            belt_type TEXT NOT NULL,
            lead_time_days INTEGER NOT NULL,
            unit_cost REAL NOT NULL,
            min_order_qty INTEGER NOT NULL,
            reliability_rating REAL NOT NULL
        )
    """)

    conn.commit()


def generate_belts(conn, n_rows):
    """Generate conveyor belt records."""
    num_lines = max(5, int(np.sqrt(n_rows)))
    belts_per_line = n_rows // num_lines
    extra = n_rows - num_lines * belts_per_line

    records = []
    belt_idx = 0
    for li in range(num_lines):
        line_id = f"LINE-{li + 1:02d}"
        count = belts_per_line + (1 if li < extra else 0)
        for _ in range(count):
            belt_idx += 1
            belt_id = f"BELT-{belt_idx:04d}"
            belt_type = random.choice(BELT_TYPES)
            manufacturer = random.choice(MANUFACTURERS)
            # Install dates between 2020 and 2025
            install_date = fake.date_between(
                start_date=pd.Timestamp("2020-01-01"),
                end_date=pd.Timestamp("2025-03-01")
            ).isoformat()
            days_since = (pd.Timestamp(PLANNING_REF_DATE) - pd.Timestamp(install_date)).days
            operating_hours = int(days_since * np.random.uniform(12, 20))
            length_meters = round(np.random.uniform(15.0, 120.0), 1)
            width_mm = random.choice([500, 650, 800, 1000, 1200, 1400, 1600])

            # Determine status based on operating hours relative to expected lifespan
            ratio = operating_hours / EXPECTED_LIFESPANS[belt_type]
            if ratio > 0.95:
                status = "critical"
            elif ratio > 0.7:
                status = "degraded"
            else:
                status = "active"

            records.append((belt_id, line_id, belt_type, manufacturer, install_date,
                            operating_hours, length_meters, width_mm, status))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO conveyor_belts VALUES (?,?,?,?,?,?,?,?,?)", records
    )
    conn.commit()
    return records


def generate_vibration_readings(conn, belts, n_rows):
    """Generate vibration sensor readings — one latest reading per belt."""
    records = []
    # We may have more rows than belts (extra readings) or fewer
    # Ensure at least n_rows readings
    belt_list = list(belts)

    # First pass: one reading per belt
    for i, (belt_id, _, belt_type, *_) in enumerate(belt_list):
        reading_id = f"VR-{i + 1:05d}"
        # Timestamp within the last 7 days before planning ref date
        days_ago = random.randint(0, 6)
        ts = pd.Timestamp(PLANNING_REF_DATE) - pd.Timedelta(days=days_ago)
        timestamp = ts.isoformat()

        warning = WARNING_THRESHOLDS[belt_type]
        critical = CRITICAL_THRESHOLDS[belt_type]

        # ~30% elevated, ~10% critical
        roll = random.random()
        if roll < 0.10:
            rms = round(np.random.uniform(critical, critical * 1.3), 2)
        elif roll < 0.30:
            rms = round(np.random.uniform(warning, critical), 2)
        else:
            rms = round(np.random.uniform(1.0, warning * 0.9), 2)

        peak = round(rms * np.random.uniform(1.2, 2.0), 2)
        freq = round(np.random.uniform(20.0, 500.0), 1)
        temp = round(np.random.uniform(35.0, 85.0), 1)

        records.append((reading_id, belt_id, timestamp, rms, peak, freq, temp))

    # If n_rows > len(belts), add extra historical readings for random belts
    idx = len(records)
    while len(records) < n_rows:
        idx += 1
        belt_id, _, belt_type, *_ = random.choice(belt_list)
        reading_id = f"VR-{idx:05d}"
        days_ago = random.randint(7, 30)
        ts = pd.Timestamp(PLANNING_REF_DATE) - pd.Timedelta(days=days_ago)
        timestamp = ts.isoformat()
        warning = WARNING_THRESHOLDS[belt_type]
        rms = round(np.random.uniform(1.0, warning * 1.1), 2)
        peak = round(rms * np.random.uniform(1.2, 2.0), 2)
        freq = round(np.random.uniform(20.0, 500.0), 1)
        temp = round(np.random.uniform(35.0, 85.0), 1)
        records.append((reading_id, belt_id, timestamp, rms, peak, freq, temp))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO vibration_readings VALUES (?,?,?,?,?,?,?)", records
    )
    conn.commit()


def generate_lifespan_logs(conn, n_rows):
    """Generate historical component lifespan/failure records."""
    records = []
    for i in range(n_rows):
        log_id = f"LS-{i + 1:05d}"
        belt_type = random.choice(BELT_TYPES)
        component_type = random.choice(COMPONENT_TYPES)
        expected = EXPECTED_LIFESPANS[belt_type]
        # Hours at failure: normally distributed around expected lifespan
        hours = max(1000, int(np.random.normal(expected, expected * 0.2)))
        install_date = fake.date_between(
            start_date=pd.Timestamp("2015-01-01"),
            end_date=pd.Timestamp("2022-01-01")
        ).isoformat()
        days_running = int(hours / np.random.uniform(14, 20))
        failure_date = (pd.Timestamp(install_date) + pd.Timedelta(days=days_running)).strftime("%Y-%m-%d")
        failure_mode = random.choice(FAILURE_MODES)
        records.append((log_id, belt_type, component_type, install_date, failure_date,
                         hours, failure_mode))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO component_lifespan_logs VALUES (?,?,?,?,?,?,?)", records
    )
    conn.commit()


def generate_production_schedules(conn, belts, n_rows):
    """Generate production schedule entries across lines and dates."""
    lines = sorted(set(b[1] for b in belts))
    # Generate dates covering July-August 2025
    all_dates = pd.date_range("2025-07-01", "2025-08-31", freq="D")

    records = []
    schedule_idx = 0
    # Distribute rows across lines and dates
    entries_per_line = n_rows // len(lines)
    extra = n_rows - entries_per_line * len(lines)

    for li, line_id in enumerate(lines):
        count = entries_per_line + (1 if li < extra else 0)
        # Pick random dates for this line
        selected_dates = sorted(np.random.choice(all_dates, size=min(count, len(all_dates)), replace=False))

        for di in range(count):
            schedule_idx += 1
            schedule_id = f"PS-{schedule_idx:05d}"
            date = pd.Timestamp(selected_dates[di % len(selected_dates)]).strftime("%Y-%m-%d")
            shift = random.choice(SHIFTS)
            product_type = random.choice(PRODUCT_TYPES)
            throughput = round(np.random.uniform(50.0, 500.0), 1)
            # Priority 1-5; lower = lower priority (easier to schedule maintenance)
            priority = random.choices([1, 2, 3, 4, 5], weights=[15, 20, 30, 25, 10])[0]
            records.append((schedule_id, line_id, date, shift, product_type,
                            throughput, priority))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO production_schedules VALUES (?,?,?,?,?,?,?)", records
    )
    conn.commit()
    return lines


def generate_supplier_catalog(conn, n_rows):
    """Generate supplier catalog entries."""
    # Distribute entries across belt types
    entries_per_type = n_rows // len(BELT_TYPES)
    extra = n_rows - entries_per_type * len(BELT_TYPES)

    records = []
    catalog_idx = 0
    supplier_idx = 0
    supplier_names_used = {}

    for ti, belt_type in enumerate(BELT_TYPES):
        count = entries_per_type + (1 if ti < extra else 0)
        for si in range(count):
            catalog_idx += 1
            supplier_idx += 1
            supplier_id = f"SUP-{supplier_idx:03d}"

            if supplier_id not in supplier_names_used:
                supplier_names_used[supplier_id] = fake.company()
            supplier_name = supplier_names_used[supplier_id]

            catalog_id = f"CAT-{catalog_idx:05d}"
            lead_time = random.randint(3, 35)
            # Cost varies by belt type
            base_costs = {
                "heavy-duty-rubber": 2500, "steel-cord": 4500, "fabric-ply": 1800,
                "modular-plastic": 1500, "chevron-rubber": 3200,
            }
            unit_cost = round(base_costs[belt_type] * np.random.uniform(0.7, 1.5), 2)
            min_order = random.choice([1, 2, 3, 5])
            reliability = round(np.random.uniform(3.0, 9.8), 1)

            records.append((catalog_id, supplier_id, supplier_name, belt_type,
                            lead_time, unit_cost, min_order, reliability))

    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO supplier_catalog VALUES (?,?,?,?,?,?,?,?)", records
    )
    conn.commit()


def generate_workspace_inspection_reports(workspace, belts, num_files):
    """Generate inspection report batch files (scalable data files)."""
    belt_list = list(belts)
    batch_size = max(1, len(belt_list) // num_files)

    inspectors = [fake.name() for _ in range(8)]

    for fi in range(num_files):
        start = fi * batch_size
        end = start + batch_size if fi < num_files - 1 else len(belt_list)
        batch_belts = belt_list[start:end]

        batch_data = []
        for belt_id, line_id, belt_type, *_ in batch_belts:
            # Visual wear score: correlated with status but adds new info
            status = _[-1]  # last field is status
            if status == "critical":
                wear_score = random.randint(6, 10)
            elif status == "degraded":
                wear_score = random.randint(4, 8)
            else:
                wear_score = random.randint(1, 6)

            condition_notes = []
            if wear_score >= 7:
                condition_notes.append(random.choice([
                    "Visible surface cracking on drive side",
                    "Edge fraying detected, replacement recommended",
                    "Multiple splice repairs visible",
                    "Significant rubber loss on carrying surface",
                    "Belt tracking misalignment causing edge wear",
                ]))
            if wear_score >= 5:
                condition_notes.append(random.choice([
                    "Minor surface wear within tolerance",
                    "Slight discoloration from heat exposure",
                    "Small nicks on belt edges",
                    "Carrying idlers showing wear marks on belt",
                ]))
            if not condition_notes:
                condition_notes.append("No significant issues observed")

            inspection_date = fake.date_between(
                start_date=pd.Timestamp("2025-05-01"),
                end_date=pd.Timestamp("2025-06-28")
            ).isoformat()

            batch_data.append({
                "belt_id": belt_id,
                "inspection_date": inspection_date,
                "visual_wear_score": wear_score,
                "condition_notes": "; ".join(condition_notes),
                "inspector": random.choice(inspectors),
            })

        filename = f"inspection_report_batch_{fi + 1:02d}.json"
        with open(os.path.join(workspace, filename), "w") as f:
            json.dump(batch_data, f, indent=2)


def generate_workspace_config_files(workspace):
    """Generate fixed policy/config workspace files."""

    # 1. maintenance_policy.yaml
    policy = {
        "vibration_thresholds": {
            bt: {"warning": WARNING_THRESHOLDS[bt], "critical": CRITICAL_THRESHOLDS[bt]}
            for bt in BELT_TYPES
        },
        "wear_threshold": 7,
        "safety_factor": 0.85,
        "maintenance_priority_threshold": 2,
        "urgency_rules": {
            "CRITICAL": "vibration rms_velocity exceeds the critical threshold for the belt type",
            "HIGH": "two or more replacement criteria are met",
            "MODERATE": "exactly one replacement criterion is met",
        },
        "replacement_criteria": [
            "vibration rms_velocity exceeds the warning threshold for the belt type",
            "visual wear score from inspection meets or exceeds the wear threshold",
            "operating hours exceed the average historical lifespan for the belt type multiplied by the safety factor",
        ],
        "scheduling_notes": "CRITICAL belts are scheduled at the earliest possible date regardless of production. HIGH and MODERATE belts must be scheduled on maintenance-eligible days where no shift on that line exceeds the maintenance priority threshold.",
    }
    with open(os.path.join(workspace, "maintenance_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. supplier_contracts.json
    contracts = {
        "preferred_suppliers": ["SUP-003", "SUP-007", "SUP-012", "SUP-018"],
        "preferred_discount_multiplier": 0.92,
        "selection_rule": "For each belt type, compute an adjusted score for each supplier as unit_cost multiplied by (1 minus reliability_rating divided by 10). For preferred suppliers, multiply the adjusted score by the preferred_discount_multiplier. Select the supplier with the lowest adjusted score. If scores are tied, choose the supplier with the shorter lead time. If still tied, choose the supplier with the lower supplier_id alphabetically.",
    }
    with open(os.path.join(workspace, "supplier_contracts.json"), "w") as f:
        json.dump(contracts, f, indent=2)

    # 3. cost_parameters.csv
    cost_rows = [
        {"belt_type": "heavy-duty-rubber", "labor_cost": 450.00, "estimated_downtime_hours": 6},
        {"belt_type": "steel-cord", "labor_cost": 680.00, "estimated_downtime_hours": 8},
        {"belt_type": "fabric-ply", "labor_cost": 320.00, "estimated_downtime_hours": 4},
        {"belt_type": "modular-plastic", "labor_cost": 280.00, "estimated_downtime_hours": 3},
        {"belt_type": "chevron-rubber", "labor_cost": 510.00, "estimated_downtime_hours": 5},
    ]
    with open(os.path.join(workspace, "cost_parameters.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["belt_type", "labor_cost", "estimated_downtime_hours"])
        writer.writeheader()
        writer.writerows(cost_rows)

    # 4. planning_horizon.txt
    with open(os.path.join(workspace, "planning_horizon.txt"), "w") as f:
        f.write("Planning Reference Date: 2025-07-01\n")
        f.write("Planning Window: 60 days\n")
        f.write("Scheduling Rule: The replacement date is the first maintenance-eligible day on or after the earliest possible date (reference date plus supplier lead time in days). For CRITICAL urgency belts, the replacement date equals the earliest possible date directly, ignoring production eligibility. If no maintenance-eligible day is found within the planning window for HIGH or MODERATE belts, schedule at the earliest possible date plus 30 days.\n")

    # 5. downtime_cost_rates.yaml
    downtime_rates = {
        "hourly_downtime_cost_by_priority": {
            1: 200.0,
            2: 350.0,
            3: 500.0,
            4: 750.0,
            5: 1200.0,
        },
        "note": "The production_impact_score for a scheduled replacement equals the sum of throughput_units_hr across all shifts on the replacement date for that production line. If no production is scheduled on that date, the impact score is 0.0. Round to one decimal place.",
    }
    with open(os.path.join(workspace, "downtime_cost_rates.yaml"), "w") as f:
        yaml.dump(downtime_rates, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Generate database tables
    belts = generate_belts(conn, n_rows)
    generate_vibration_readings(conn, belts, n_rows)
    generate_lifespan_logs(conn, n_rows)
    lines = generate_production_schedules(conn, belts, n_rows)
    generate_supplier_catalog(conn, n_rows)

    # Generate workspace files
    generate_workspace_inspection_reports(args.workspace, belts, n_files)
    generate_workspace_config_files(args.workspace)

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")
    print(f"  - {n_files} inspection report batches")
    print(f"  - 5 config/policy files")
    print(f"  - {n_rows} rows per table, {len(lines)} production lines")


if __name__ == "__main__":
    main()
