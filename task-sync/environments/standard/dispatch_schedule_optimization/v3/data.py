import argparse
import sqlite3
import os
import json
import csv
import random
import datetime

import numpy as np
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

ZONES = [
    "North", "South", "East", "West", "Central",
    "Northeast", "Northwest", "Southeast", "Southwest", "Downtown",
]

SKILLS = [
    "HVAC", "Plumbing", "Electrical", "Appliance_Repair",
    "Roofing", "Carpentry", "Painting", "General_Maintenance",
]

CERT_LEVELS = ["junior", "senior", "expert"]

PARTS = [
    "compressor", "thermostat", "filter_unit", "pump_assembly", "valve_kit",
    "circuit_board", "motor", "fan_blade", "gasket_set", "relay_switch",
    "condenser_coil", "heat_exchanger", "pressure_gauge", "wiring_harness",
    "control_panel",
]

WAREHOUSES = [
    {"id": 1, "name": "Central Depot", "zone": "Central"},
    {"id": 2, "name": "North Hub", "zone": "North"},
    {"id": 3, "name": "South Hub", "zone": "South"},
    {"id": 4, "name": "East Distribution", "zone": "East"},
    {"id": 5, "name": "West Distribution", "zone": "West"},
]

CUSTOMER_TIERS = ["platinum", "gold", "silver", "bronze"]
TIER_WEIGHTS = [0.1, 0.25, 0.35, 0.3]
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

SPECIAL_INSTRUCTIONS = [
    "Customer prefers morning appointments",
    "Building requires security clearance",
    "Parking available on-site",
    "Contact customer 30 min before arrival",
    "Access through rear entrance only",
    "Customer requests senior technician if available",
    "High-rise unit requires extension equipment",
    "Elderly customer needs extra patience",
    "Commercial property with restricted hours",
    "Customer will not be present - use lockbox code",
    "",
    "",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    rng = np.random.default_rng(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(args.workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    # --- Generate travel matrix (symmetric, small diagonal) ---
    n_zones = len(ZONES)
    raw = rng.integers(20, 91, size=(n_zones, n_zones)).astype(int)
    travel_raw = (raw + raw.T) // 2
    for i in range(n_zones):
        travel_raw[i][i] = int(rng.integers(5, 16))

    travel_matrix = {}
    for i, z1 in enumerate(ZONES):
        travel_matrix[z1] = {}
        for j, z2 in enumerate(ZONES):
            travel_matrix[z1][z2] = int(travel_raw[i][j])

    # --- Create database ---
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    # Table 1: service_requests
    cur.execute("""
        CREATE TABLE service_requests (
            request_id INTEGER PRIMARY KEY,
            customer_name TEXT,
            zone TEXT,
            required_skill TEXT,
            priority_level INTEGER,
            estimated_duration_hours REAL,
            status TEXT,
            created_date TEXT
        )
    """)

    service_requests = []
    for i in range(1, rows + 1):
        sr = (
            i,
            fake.name(),
            random.choice(ZONES),
            random.choice(SKILLS),
            random.randint(1, 5),
            round(random.uniform(0.5, 4.0), 1),
            "pending",
            fake.date_between(
                start_date=datetime.date(2026, 4, 11),
                end_date=datetime.date(2026, 4, 25),
            ).isoformat(),
        )
        service_requests.append(sr)
        cur.execute("INSERT INTO service_requests VALUES (?,?,?,?,?,?,?,?)", sr)

    # Table 2: technicians
    cur.execute("""
        CREATE TABLE technicians (
            tech_id INTEGER PRIMARY KEY,
            name TEXT,
            home_zone TEXT,
            experience_years INTEGER,
            active INTEGER
        )
    """)

    technicians = []
    for i in range(1, rows + 1):
        tech = (
            i,
            fake.name(),
            random.choice(ZONES),
            random.randint(1, 20),
            1 if random.random() < 0.85 else 0,
        )
        technicians.append(tech)
        cur.execute("INSERT INTO technicians VALUES (?,?,?,?,?)", tech)

    # Table 3: technician_certifications
    cur.execute("""
        CREATE TABLE technician_certifications (
            cert_id INTEGER PRIMARY KEY,
            tech_id INTEGER,
            skill_name TEXT,
            cert_level TEXT,
            expiry_date TEXT,
            FOREIGN KEY (tech_id) REFERENCES technicians(tech_id)
        )
    """)

    cert_id = 1
    cert_count = 0
    for tech in technicians:
        num_certs = random.randint(1, 3)
        skills_chosen = random.sample(SKILLS, min(num_certs, len(SKILLS)))
        for skill in skills_chosen:
            expiry = fake.date_between(
                start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2027, 6, 30),
            ).isoformat()
            cur.execute(
                "INSERT INTO technician_certifications VALUES (?,?,?,?,?)",
                (cert_id, tech[0], skill, random.choice(CERT_LEVELS), expiry),
            )
            cert_id += 1
            cert_count += 1

    # Pad to reach rows if needed
    while cert_count < rows:
        tech = random.choice(technicians)
        skill = random.choice(SKILLS)
        expiry = fake.date_between(
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2027, 6, 30),
        ).isoformat()
        cur.execute(
            "INSERT INTO technician_certifications VALUES (?,?,?,?,?)",
            (cert_id, tech[0], skill, random.choice(CERT_LEVELS), expiry),
        )
        cert_id += 1
        cert_count += 1

    # Table 4: parts_inventory
    cur.execute("""
        CREATE TABLE parts_inventory (
            inv_id INTEGER PRIMARY KEY,
            part_id TEXT,
            warehouse_id INTEGER,
            quantity INTEGER,
            reorder_eta_days INTEGER
        )
    """)

    inv_id = 1
    inv_count = 0
    for part in PARTS:
        for wh in WAREHOUSES:
            cur.execute(
                "INSERT INTO parts_inventory VALUES (?,?,?,?,?)",
                (inv_id, part, wh["id"], random.randint(0, 25), random.randint(1, 7)),
            )
            inv_id += 1
            inv_count += 1

    while inv_count < rows:
        cur.execute(
            "INSERT INTO parts_inventory VALUES (?,?,?,?,?)",
            (
                inv_id,
                random.choice(PARTS),
                random.choice(WAREHOUSES)["id"],
                random.randint(0, 25),
                random.randint(1, 7),
            ),
        )
        inv_id += 1
        inv_count += 1

    # Table 5: service_parts_required
    cur.execute("""
        CREATE TABLE service_parts_required (
            id INTEGER PRIMARY KEY,
            request_id INTEGER,
            part_id TEXT,
            quantity_needed INTEGER,
            FOREIGN KEY (request_id) REFERENCES service_requests(request_id)
        )
    """)

    spr_id = 1
    spr_count = 0
    for sr in service_requests:
        num_parts = random.randint(1, 3)
        parts_chosen = random.sample(PARTS, num_parts)
        for part in parts_chosen:
            cur.execute(
                "INSERT INTO service_parts_required VALUES (?,?,?,?)",
                (spr_id, sr[0], part, random.randint(1, 3)),
            )
            spr_id += 1
            spr_count += 1

    while spr_count < rows:
        sr = random.choice(service_requests)
        cur.execute(
            "INSERT INTO service_parts_required VALUES (?,?,?,?)",
            (spr_id, sr[0], random.choice(PARTS), random.randint(1, 2)),
        )
        spr_id += 1
        spr_count += 1

    conn.commit()
    conn.close()

    # ============================================================
    # Workspace files
    # ============================================================

    # === Fixed config files (not counted in SCALE) ===

    # 1. travel_matrix.csv
    with open(os.path.join(args.workspace, "travel_matrix.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["from_zone"] + ZONES)
        for z in ZONES:
            writer.writerow([z] + [travel_matrix[z][z2] for z2 in ZONES])

    # 2. dispatch_policy.yaml
    policy = {
        "reference_date": "2026-04-25",
        "certification_requirements": {
            5: "expert",
            4: "senior",
            3: "junior",
            2: "junior",
            1: "junior",
        },
        "customer_tier_multiplier": {
            "platinum": 2.0,
            "gold": 1.5,
            "silver": 1.2,
            "bronze": 1.0,
        },
        "max_assignments_per_tech_per_day": 3,
        "max_weekly_assignments_per_tech": 12,
        "scheduling_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "certification_level_hierarchy": {
            "junior": 1,
            "senior": 2,
            "expert": 3,
        },
    }
    with open(os.path.join(args.workspace, "dispatch_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 3. cost_weights.json
    cost_weights = {
        "travel_time_weight": 2.0,
        "wait_time_weight": 5.0,
        "description": (
            "Total assignment cost for a (technician, warehouse) pair serving a request: "
            "travel_time_weight * (tech_travel_minutes + warehouse_travel_minutes) + "
            "wait_time_weight * part_wait_days * 60. "
            "Assign requests in descending order of effective priority. "
            "Effective priority = priority_level * customer_tier_multiplier * seasonal_demand_factor. "
            "For each request choose the eligible (technician, warehouse) pair with the lowest total cost. "
            "Break ties by technician ID ascending, then warehouse ID ascending."
        ),
    }
    with open(os.path.join(args.workspace, "cost_weights.json"), "w") as f:
        json.dump(cost_weights, f, indent=2)

    # 4. seasonal_demand.json
    seasonal = {}
    for z in ZONES:
        seasonal[z] = round(random.uniform(0.8, 1.5), 2)
    with open(os.path.join(args.workspace, "seasonal_demand.json"), "w") as f:
        json.dump(seasonal, f, indent=2)

    # 5. warehouse_directory.yaml
    wh_data = {}
    for wh in WAREHOUSES:
        wh_data[wh["id"]] = {"name": wh["name"], "zone": wh["zone"]}
    with open(os.path.join(args.workspace, "warehouse_directory.yaml"), "w") as f:
        yaml.dump(wh_data, f, default_flow_style=False, sort_keys=False)

    # === Scalable files: service_details_batch_N.csv ===
    supplements = []
    for sr in service_requests:
        supplements.append(
            {
                "request_id": sr[0],
                "customer_tier": random.choices(
                    CUSTOMER_TIERS, weights=TIER_WEIGHTS, k=1
                )[0],
                "preferred_day": random.choice(DAYS_OF_WEEK),
                "special_instructions": random.choice(SPECIAL_INSTRUCTIONS),
            }
        )

    batch_size = max(1, len(supplements) // num_files)
    for i in range(num_files):
        start = i * batch_size
        if i == num_files - 1:
            batch = supplements[start:]
        else:
            batch = supplements[start : start + batch_size]
        if not batch:
            continue
        fp = os.path.join(args.workspace, f"service_details_batch_{i + 1}.csv")
        with open(fp, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "request_id",
                    "customer_tier",
                    "preferred_day",
                    "special_instructions",
                ],
            )
            writer.writeheader()
            for row in batch:
                writer.writerow(row)

    print(f"Database: {args.db_path} ({rows} rows/table base)")
    print(
        f"Workspace: {args.workspace} ({num_files} batch files + 5 config files)"
    )


if __name__ == "__main__":
    main()
