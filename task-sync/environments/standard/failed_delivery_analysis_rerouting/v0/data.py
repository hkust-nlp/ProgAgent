"""
Data generation for failed delivery rerouting analysis task.
Generates database tables and workspace files.
"""
import argparse
import os
import sqlite3
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 8,
}

# Fixed seeds
fake = Faker()
Faker.seed(42)
np.random.seed(42)

# --- Constants ---
HANDLING_CODES = ["FRAG", "HAZ", "OVER", "COLD", "STD"]
HANDLING_PROBS = [0.20, 0.10, 0.15, 0.10, 0.45]
FAILURE_REASONS = [
    "no_access", "customer_absent", "security_concern",
    "incorrect_address", "weather", "package_damaged", "vehicle_issue"
]
SECURITY_LEVELS = ["critical", "high", "medium", "low"]
SECURITY_PROBS = [0.10, 0.25, 0.40, 0.25]
ALL_CERTIFICATIONS = [
    "fragile_certified", "hazmat_certified", "oversized_certified",
    "cold_chain_certified", "standard"
]
VEHICLE_TYPES = ["enclosed_van", "refrigerated_truck", "flatbed", "motorcycle", "standard_truck"]
PRIORITY_TIERS = ["platinum", "gold", "silver", "bronze"]
ACCESS_TYPES = ["open", "gated", "buzzer", "key_required", "doorman"]
ACCOUNT_TYPES = ["business", "residential", "government"]
DELIVERY_SPOTS = [
    "front porch", "back door", "reception desk", "mail room",
    "garage side door", "building lobby", "side gate", "loading dock"
]
SUPERVISOR_FLAGS = ["normal", "urgent", "review"]
WEATHER_CONDITIONS = [
    "clear", "light_rain", "heavy_rain", "snow",
    "fog", "windy", "overcast", "thunderstorm"
]
AVAILABILITY_STATUSES = ["full_time", "part_time", "on_call"]
ZONE_CODES = [f"Z{i:02d}" for i in range(1, 21)]
NEIGHBORHOOD_SUFFIXES = [
    "Heights", "Park", "Village", "Square", "District",
    "Commons", "Crossing", "Glen", "Terrace", "Meadows"
]


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        phone TEXT NOT NULL,
        priority_tier TEXT NOT NULL,
        account_type TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS packages (
        package_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        weight_kg REAL NOT NULL,
        length_cm REAL NOT NULL,
        width_cm REAL NOT NULL,
        height_cm REAL NOT NULL,
        declared_value REAL NOT NULL,
        handling_code TEXT NOT NULL,
        description TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS drivers (
        driver_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        success_rate REAL NOT NULL,
        avg_delivery_time_min REAL NOT NULL,
        total_deliveries INTEGER NOT NULL,
        certifications TEXT NOT NULL,
        active_status INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS neighborhoods (
        neighborhood_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        security_level TEXT NOT NULL,
        avg_crime_index REAL NOT NULL,
        gated_community INTEGER NOT NULL,
        access_type TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS delivery_attempts (
        attempt_id TEXT PRIMARY KEY,
        package_id TEXT NOT NULL,
        driver_id TEXT NOT NULL,
        neighborhood_id TEXT NOT NULL,
        attempt_date TEXT NOT NULL,
        status TEXT NOT NULL,
        failure_reason TEXT,
        notes TEXT,
        FOREIGN KEY (package_id) REFERENCES packages(package_id),
        FOREIGN KEY (driver_id) REFERENCES drivers(driver_id),
        FOREIGN KEY (neighborhood_id) REFERENCES neighborhoods(neighborhood_id)
    )""")
    conn.commit()


def generate_customers(n):
    rows = []
    for i in range(n):
        rows.append({
            "customer_id": f"C{i+1:04d}",
            "name": fake.name(),
            "address": fake.address().replace("\n", ", "),
            "phone": fake.phone_number(),
            "priority_tier": str(np.random.choice(PRIORITY_TIERS, p=[0.10, 0.20, 0.40, 0.30])),
            "account_type": str(np.random.choice(ACCOUNT_TYPES, p=[0.30, 0.60, 0.10])),
        })
    return rows


def generate_packages(n, customer_ids):
    rows = []
    for i in range(n):
        if np.random.random() < 0.50:
            value = round(float(np.random.uniform(200, 2000)), 2)
        else:
            value = round(float(np.random.uniform(20, 199.99)), 2)
        rows.append({
            "package_id": f"PKG{i+1:05d}",
            "customer_id": str(np.random.choice(customer_ids)),
            "weight_kg": round(float(np.random.uniform(0.5, 50.0)), 2),
            "length_cm": round(float(np.random.uniform(10, 150)), 1),
            "width_cm": round(float(np.random.uniform(10, 100)), 1),
            "height_cm": round(float(np.random.uniform(5, 80)), 1),
            "declared_value": value,
            "handling_code": str(np.random.choice(HANDLING_CODES, p=HANDLING_PROBS)),
            "description": fake.sentence(nb_words=6),
        })
    return rows


def generate_drivers(n):
    rows = []
    for i in range(n):
        num_certs = int(np.random.randint(1, 4))
        certs = list(np.random.choice(
            [c for c in ALL_CERTIFICATIONS if c != "standard"],
            size=min(num_certs, 4), replace=False
        ))
        certs.append("standard")
        rows.append({
            "driver_id": f"D{i+1:04d}",
            "name": fake.name(),
            "success_rate": round(float(np.random.uniform(0.60, 0.99)), 4),
            "avg_delivery_time_min": round(float(np.random.uniform(10, 60)), 1),
            "total_deliveries": int(np.random.randint(50, 5000)),
            "certifications": ",".join(sorted(certs)),
            "active_status": int(np.random.choice([0, 1], p=[0.15, 0.85])),
        })
    return rows


def generate_neighborhoods(n):
    rows = []
    used_names = set()
    for i in range(n):
        while True:
            name = fake.city() + " " + str(np.random.choice(NEIGHBORHOOD_SUFFIXES))
            if name not in used_names:
                used_names.add(name)
                break
        rows.append({
            "neighborhood_id": f"N{i+1:04d}",
            "name": name,
            "zone_code": str(np.random.choice(ZONE_CODES)),
            "security_level": str(np.random.choice(SECURITY_LEVELS, p=SECURITY_PROBS)),
            "avg_crime_index": round(float(np.random.uniform(0.1, 9.5)), 2),
            "gated_community": int(np.random.choice([0, 1], p=[0.70, 0.30])),
            "access_type": str(np.random.choice(ACCESS_TYPES)),
        })
    return rows


def generate_delivery_attempts(packages, driver_ids, neighborhood_ids):
    """Generate delivery attempts with controlled outcome distribution."""
    n_pkgs = len(packages)
    indices = list(range(n_pkgs))
    np.random.shuffle(indices)

    n_all_failed = int(n_pkgs * 0.40)
    n_mixed = int(n_pkgs * 0.30)

    all_failed_idx = set(indices[:n_all_failed])
    mixed_idx = set(indices[n_all_failed:n_all_failed + n_mixed])

    attempts = []
    att_counter = 0

    for idx, pkg in enumerate(packages):
        pid = pkg["package_id"]
        if idx in all_failed_idx:
            n_att = int(np.random.randint(1, 5))
            for _ in range(n_att):
                att_counter += 1
                attempts.append({
                    "attempt_id": f"ATT{att_counter:06d}",
                    "package_id": pid,
                    "driver_id": str(np.random.choice(driver_ids)),
                    "neighborhood_id": str(np.random.choice(neighborhood_ids)),
                    "attempt_date": fake.date_between(
                        start_date="-90d", end_date="today"
                    ).isoformat(),
                    "status": "failed",
                    "failure_reason": str(np.random.choice(FAILURE_REASONS)),
                    "notes": fake.sentence(nb_words=8),
                })
        elif idx in mixed_idx:
            n_failed = int(np.random.randint(1, 4))
            for _ in range(n_failed):
                att_counter += 1
                attempts.append({
                    "attempt_id": f"ATT{att_counter:06d}",
                    "package_id": pid,
                    "driver_id": str(np.random.choice(driver_ids)),
                    "neighborhood_id": str(np.random.choice(neighborhood_ids)),
                    "attempt_date": fake.date_between(
                        start_date="-90d", end_date="-10d"
                    ).isoformat(),
                    "status": "failed",
                    "failure_reason": str(np.random.choice(FAILURE_REASONS)),
                    "notes": fake.sentence(nb_words=8),
                })
            att_counter += 1
            attempts.append({
                "attempt_id": f"ATT{att_counter:06d}",
                "package_id": pid,
                "driver_id": str(np.random.choice(driver_ids)),
                "neighborhood_id": str(np.random.choice(neighborhood_ids)),
                "attempt_date": fake.date_between(
                    start_date="-9d", end_date="today"
                ).isoformat(),
                "status": "success",
                "failure_reason": None,
                "notes": "",
            })
        else:
            att_counter += 1
            attempts.append({
                "attempt_id": f"ATT{att_counter:06d}",
                "package_id": pid,
                "driver_id": str(np.random.choice(driver_ids)),
                "neighborhood_id": str(np.random.choice(neighborhood_ids)),
                "attempt_date": fake.date_between(
                    start_date="-30d", end_date="today"
                ).isoformat(),
                "status": "success",
                "failure_reason": None,
                "notes": "",
            })

    return attempts


def insert_rows(conn, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ",".join(["?"] * len(cols))
    col_str = ",".join(cols)
    conn.executemany(
        f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows]
    )
    conn.commit()


# ---- Workspace file generators ----

def generate_delivery_log_files(attempts, n_files, workspace):
    """delivery_log_batch_*.csv: supervisor flags and weather not in DB."""
    chunk_size = math.ceil(len(attempts) / max(n_files, 1))
    for fi in range(n_files):
        chunk = attempts[fi * chunk_size:(fi + 1) * chunk_size]
        filepath = os.path.join(workspace, f"delivery_log_batch_{fi+1}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "attempt_id", "gps_lat", "gps_lon", "time_of_attempt",
                "weather_detail", "supervisor_priority_flag"
            ])
            writer.writeheader()
            for att in chunk:
                writer.writerow({
                    "attempt_id": att["attempt_id"],
                    "gps_lat": round(float(np.random.uniform(25.0, 48.0)), 6),
                    "gps_lon": round(float(np.random.uniform(-125.0, -70.0)), 6),
                    "time_of_attempt": f"{np.random.randint(6, 21):02d}:"
                                       f"{np.random.choice(['00','15','30','45'])}",
                    "weather_detail": str(np.random.choice(WEATHER_CONDITIONS)),
                    "supervisor_priority_flag": str(np.random.choice(
                        SUPERVISOR_FLAGS, p=[0.65, 0.20, 0.15]
                    )),
                })


def generate_customer_access_files(customers, n_files, workspace):
    """customer_access_*.json: gate codes and delivery preferences not in DB."""
    chunk_size = math.ceil(len(customers) / max(n_files, 1))
    for fi in range(n_files):
        chunk = customers[fi * chunk_size:(fi + 1) * chunk_size]
        records = []
        for cust in chunk:
            starts = sorted(
                np.random.choice(range(7, 18),
                                 size=int(np.random.randint(1, 4)),
                                 replace=False).tolist()
            )
            time_windows = [f"{h:02d}:00-{h+2:02d}:00" for h in starts]
            records.append({
                "customer_id": cust["customer_id"],
                "gate_code": (str(np.random.randint(1000, 9999))
                              if np.random.random() < 0.4 else ""),
                "buzzer_info": (f"Unit {np.random.randint(1, 30)}"
                                f"{np.random.choice(['A','B','C',''])}"
                                if np.random.random() < 0.35 else ""),
                "preferred_delivery_spot": str(np.random.choice(DELIVERY_SPOTS)),
                "delivery_notes": fake.sentence(nb_words=8),
                "available_time_windows": time_windows,
            })
        filepath = os.path.join(workspace, f"customer_access_{fi+1}.json")
        with open(filepath, "w") as f:
            json.dump(records, f, indent=2)


def generate_neighborhood_bulletin_files(neighborhoods, n_files, workspace):
    """neighborhood_bulletin_*.yaml: safe delivery hours not in DB."""
    chunk_size = math.ceil(len(neighborhoods) / max(n_files, 1))
    for fi in range(n_files):
        chunk = neighborhoods[fi * chunk_size:(fi + 1) * chunk_size]
        filepath = os.path.join(workspace, f"neighborhood_bulletin_{fi+1}.yaml")
        with open(filepath, "w") as f:
            for nb in chunk:
                start_h = int(np.random.choice([6, 7, 8, 9]))
                end_h = int(np.random.choice([17, 18, 19, 20]))
                f.write(f"- neighborhood_id: \"{nb['neighborhood_id']}\"\n")
                f.write(f"  bulletin_date: \"{fake.date_between(start_date='-30d', end_date='today').isoformat()}\"\n")
                f.write(f"  recent_incidents: {int(np.random.randint(0, 15))}\n")
                f.write(f"  patrol_coverage: \"{start_h:02d}:00-{end_h:02d}:00\"\n")
                f.write(f"  safe_delivery_hours: \"{start_h:02d}:00-{end_h:02d}:00\"\n")
                f.write(f"  risk_advisory: \"{fake.sentence(nb_words=10)}\"\n")


def generate_driver_report_files(drivers, n_files, workspace):
    """driver_report_*.txt: vehicle type and capacity not in DB."""
    chunk_size = math.ceil(len(drivers) / max(n_files, 1))
    for fi in range(n_files):
        chunk = drivers[fi * chunk_size:(fi + 1) * chunk_size]
        filepath = os.path.join(workspace, f"driver_report_{fi+1}.txt")
        with open(filepath, "w") as f:
            for drv in chunk:
                certs = drv["certifications"].split(",")
                if "cold_chain_certified" in certs:
                    vtype = str(np.random.choice(["refrigerated_truck", "enclosed_van"]))
                elif "oversized_certified" in certs:
                    vtype = str(np.random.choice(["flatbed", "standard_truck"]))
                elif "fragile_certified" in certs:
                    vtype = str(np.random.choice(["enclosed_van", "standard_truck"]))
                elif "hazmat_certified" in certs:
                    vtype = str(np.random.choice(["standard_truck", "enclosed_van"]))
                else:
                    vtype = str(np.random.choice(VEHICLE_TYPES))
                zones = sorted(list(np.random.choice(
                    ZONE_CODES,
                    size=int(np.random.randint(2, 7)),
                    replace=False
                )))
                f.write("=== DRIVER REPORT ===\n")
                f.write(f"Driver ID: {drv['driver_id']}\n")
                f.write(f"Vehicle Type: {vtype}\n")
                f.write(f"Max Load (kg): {round(float(np.random.uniform(100, 2000)), 1)}\n")
                f.write(f"Service Area Zones: {', '.join(zones)}\n")
                f.write(f"Availability: {str(np.random.choice(AVAILABILITY_STATUSES))}\n")
                f.write("========================\n\n")


def generate_fixed_config_files(workspace):
    """Generate policy/config files that don't scale."""
    policy = {
        "high_value_threshold": 200.00,
        "max_reroute_attempts": 5,
        "priority_weights": {
            "declared_value": 0.35,
            "failed_attempts": 0.25,
            "security_risk": 0.20,
            "handling_complexity": 0.20
        },
        "security_risk_scores": {
            "critical": 1.0,
            "high": 0.75,
            "medium": 0.5,
            "low": 0.25
        },
        "handling_complexity_scores": {
            "HAZ": 1.0,
            "COLD": 0.85,
            "OVER": 0.70,
            "FRAG": 0.60,
            "STD": 0.20
        },
        "urgent_flag_bonus": 0.15,
        "value_normalization_cap": 1000.0,
        "attempts_normalization_cap": 5
    }
    with open(os.path.join(workspace, "rerouting_policy.json"), "w") as f:
        json.dump(policy, f, indent=2)

    matrix_content = """handling_codes:
  FRAG:
    description: "Fragile - handle with extreme care"
    required_certification: "fragile_certified"
    required_vehicle_type: "enclosed_van"
    handling_note: "Fragile item - no stacking, upright only"
  HAZ:
    description: "Hazardous materials"
    required_certification: "hazmat_certified"
    required_vehicle_type: "standard_truck"
    handling_note: "Hazmat protocols required - maintain safe distance from heat sources"
  OVER:
    description: "Oversized package"
    required_certification: "oversized_certified"
    required_vehicle_type: "flatbed"
    handling_note: "Oversized - requires two-person lift, secure with straps"
  COLD:
    description: "Cold chain - temperature sensitive"
    required_certification: "cold_chain_certified"
    required_vehicle_type: "refrigerated_truck"
    handling_note: "Temperature sensitive - maintain below 8C, deliver within 4 hours"
  STD:
    description: "Standard handling"
    required_certification: "standard"
    required_vehicle_type: "standard_truck"
    handling_note: "Standard handling procedures apply"
"""
    with open(os.path.join(workspace, "handling_matrix.yaml"), "w") as f:
        f.write(matrix_content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]
    files_per_type = n_files // 4

    customers = generate_customers(n)
    customer_ids = [c["customer_id"] for c in customers]

    packages = generate_packages(n, customer_ids)

    drivers = generate_drivers(n)
    driver_ids = [d["driver_id"] for d in drivers]

    neighborhoods = generate_neighborhoods(n)
    neighborhood_ids = [nb["neighborhood_id"] for nb in neighborhoods]

    attempts = generate_delivery_attempts(packages, driver_ids, neighborhood_ids)

    # Create DB
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_rows(conn, "customers", customers)
    insert_rows(conn, "packages", packages)
    insert_rows(conn, "drivers", drivers)
    insert_rows(conn, "neighborhoods", neighborhoods)
    insert_rows(conn, "delivery_attempts", attempts)
    conn.close()

    # Generate workspace files
    generate_delivery_log_files(attempts, files_per_type, args.workspace)
    generate_customer_access_files(customers, files_per_type, args.workspace)
    generate_neighborhood_bulletin_files(neighborhoods, files_per_type, args.workspace)
    generate_driver_report_files(drivers, files_per_type, args.workspace)
    generate_fixed_config_files(args.workspace)

    print(f"Database created at {args.db_path}")
    print(f"Workspace files generated in {args.workspace}")
    print(f"  Tables: customers({n}), packages({n}), drivers({n}), "
          f"neighborhoods({n}), delivery_attempts({len(attempts)})")
    print(f"  Scalable files: {n_files} ({files_per_type} per type)")
    print(f"  Fixed config files: 2 (rerouting_policy.json, handling_matrix.yaml)")


if __name__ == "__main__":
    main()
