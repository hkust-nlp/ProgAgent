import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import yaml
from datetime import datetime, timedelta
from faker import Faker

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 20,
}

REFERENCE_DATE = datetime(2026, 3, 1)

STORAGE_CLASSES = {
    "frozen": (-25.0, -15.0),
    "cold_chain": (2.0, 8.0),
    "controlled_room_temp": (15.0, 25.0),
}

CATEGORIES = ["biologics", "vaccines", "small_molecule", "reagent", "diagnostic"]
CONTAINER_TYPES = ["refrigerated", "insulated", "passive_cooler"]
INCIDENT_TYPES = [
    "equipment_failure", "delay", "accident",
    "power_outage", "temperature_alarm", "door_seal_failure",
]
SEVERITIES = ["minor", "moderate", "major", "critical"]
SEVERITY_WEIGHTS = [40, 30, 20, 10]


def generate_products(n, fake):
    products = []
    for i in range(n):
        sc = random.choice(list(STORAGE_CLASSES.keys()))
        lo, hi = STORAGE_CLASSES[sc]
        products.append({
            "product_id": f"PROD-{i+1:04d}",
            "product_name": fake.catch_phrase(),
            "category": random.choice(CATEGORIES),
            "storage_class": sc,
            "min_temp": lo,
            "max_temp": hi,
            "unit_value": round(random.uniform(10, 5000), 2),
        })
    return products


def generate_carriers(n, fake):
    carriers = []
    for i in range(n):
        carriers.append({
            "carrier_id": f"CAR-{i+1:03d}",
            "carrier_name": fake.company(),
            "certified_cold_chain": random.random() < 0.75,
        })
    return carriers


def generate_warehouses(n, fake):
    warehouses = []
    for i in range(n):
        warehouses.append({
            "warehouse_id": f"WH-{i+1:03d}",
            "warehouse_name": f"{fake.city()} Distribution Center",
            "location": fake.city(),
        })
    return warehouses


def generate_shipments(n, products, carriers, warehouses, fake):
    status_pool = (["pending_review"] * 20
                   + ["released"] * 60
                   + ["quarantined"] * 20)
    shipments = []
    for i in range(n):
        product = random.choice(products)
        carrier = random.choice(carriers)
        origin = random.choice(warehouses)
        dest = random.choice([w for w in warehouses if w["warehouse_id"] != origin["warehouse_id"]])
        status = random.choice(status_pool)
        days_back = random.randint(10, 60)
        ship_date = (REFERENCE_DATE - timedelta(days=days_back)).date()
        transit_days = random.randint(1, 7)
        arrival_date = ship_date + timedelta(days=transit_days)
        shipments.append({
            "shipment_id": f"SHP-{i+1:04d}",
            "product_id": product["product_id"],
            "carrier_id": carrier["carrier_id"],
            "origin_warehouse_id": origin["warehouse_id"],
            "destination_warehouse_id": dest["warehouse_id"],
            "status": status,
            "ship_date": str(ship_date),
            "arrival_date": str(arrival_date),
            "container_type": random.choice(CONTAINER_TYPES),
            "lot_number": f"LOT-{fake.bothify('??###').upper()}",
            "quantity": random.randint(50, 5000),
        })
    return shipments


def generate_temperature_logs(shipments, products, cur):
    product_map = {p["product_id"]: p for p in products}
    for s in shipments:
        p = product_map[s["product_id"]]
        min_t, max_t = p["min_temp"], p["max_temp"]

        ship_dt = datetime.strptime(s["ship_date"], "%Y-%m-%d")
        arrival_dt = datetime.strptime(s["arrival_date"], "%Y-%m-%d")
        duration_hours = max(24.0, (arrival_dt - ship_dt).total_seconds() / 3600.0)

        n_readings = random.randint(10, 24)
        offsets = sorted([random.uniform(0, duration_hours) for _ in range(n_readings)])
        timestamps = [ship_dt + timedelta(hours=h) for h in offsets]

        # Determine if excursion occurs
        if s["status"] == "pending_review":
            has_excursion = random.random() < 0.70
        elif s["status"] == "quarantined":
            has_excursion = random.random() < 0.90
        else:
            has_excursion = random.random() < 0.10

        excursion_start = n_readings // 3
        excursion_end = 2 * n_readings // 3
        sensor = f"SENSOR-{random.randint(1, 5):02d}"

        for j, ts in enumerate(timestamps):
            if has_excursion and excursion_start <= j < excursion_end:
                deviation = random.uniform(1.0, 15.0)
                if random.random() < 0.5:
                    temp = max_t + deviation
                else:
                    temp = min_t - deviation
            else:
                temp = random.uniform(min_t + 0.5, max_t - 0.5)
            temp = round(temp, 2)
            cur.execute(
                "INSERT INTO temperature_logs (shipment_id, timestamp, temperature, sensor_id) "
                "VALUES (?,?,?,?)",
                (s["shipment_id"], ts.strftime("%Y-%m-%dT%H:%M:%S"), temp, sensor),
            )


def generate_incidents(n, shipments, carriers, fake, cur):
    for i in range(n):
        iid = f"INC-{i+1:04d}"
        if random.random() < 0.55:
            s = random.choice(shipments)
            sid = s["shipment_id"]
            cid = s["carrier_id"]
        else:
            sid = None
            cid = random.choice(carriers)["carrier_id"]

        inc_type = random.choice(INCIDENT_TYPES)
        sev = random.choices(SEVERITIES, weights=SEVERITY_WEIGHTS, k=1)[0]
        days_back = random.randint(5, 90)
        inc_date = str((REFERENCE_DATE - timedelta(days=days_back)).date())
        desc = f"{inc_type.replace('_', ' ').title()} reported: {fake.sentence()}"
        cur.execute(
            "INSERT INTO incidents VALUES (?,?,?,?,?,?,?)",
            (iid, sid, cid, inc_type, sev, inc_date, desc),
        )


# ---------------------------------------------------------------------------
# Workspace file generation
# ---------------------------------------------------------------------------

def write_excursion_policy(workspace):
    policy = {
        "excursion_duration_calculation": {
            "method": "proportional",
            "description": (
                "Duration equals the number of excursion readings divided by the "
                "total number of readings, multiplied by the monitoring span in "
                "minutes. The monitoring span is the elapsed time from the first "
                "to the last temperature reading recorded for the shipment."
            ),
            "rounding": "nearest_integer",
        },
        "max_deviation_calculation": {
            "method": "max_absolute_deviation_from_range",
            "description": (
                "For each reading outside the acceptable range, compute the "
                "absolute difference from the nearest boundary. The max deviation "
                "is the largest such value across all readings."
            ),
            "format": "two_decimal_places",
        },
        "disposition_rules": {
            "priority_order": [
                {
                    "rule": "no_excursion",
                    "condition": "No temperature readings fell outside the acceptable range",
                    "action": "RELEASE",
                    "reason": "No temperature excursion detected",
                },
                {
                    "rule": "carrier_not_certified",
                    "condition": (
                        "An excursion was detected and the carrier lacks cold chain certification"
                    ),
                    "action": "QUARANTINE",
                    "reason": "Carrier not cold chain certified",
                },
                {
                    "rule": "critical_incident",
                    "condition": (
                        "An excursion was detected and the shipment has a critical-severity incident"
                    ),
                    "action": "QUARANTINE",
                    "reason": "Critical incident reported",
                },
                {
                    "rule": "exceeds_stability",
                    "condition": (
                        "An excursion was detected and either the max deviation exceeds the "
                        "product stability profile max_allowed_deviation_celsius or the "
                        "excursion duration exceeds max_allowed_duration_minutes"
                    ),
                    "action": "QUARANTINE",
                    "reason": "Excursion exceeds stability tolerance",
                },
                {
                    "rule": "warehouse_noncompliant",
                    "condition": (
                        "An excursion was detected and any zone in the origin or destination "
                        "warehouse has a FAIL compliance status in the thermal mapping data"
                    ),
                    "action": "QUARANTINE",
                    "reason": "Warehouse thermal noncompliance",
                },
                {
                    "rule": "moderate_or_higher_incident",
                    "condition": (
                        "An excursion was detected and the highest incident severity for the "
                        "shipment is moderate, major, or critical"
                    ),
                    "action": "QUARANTINE",
                    "reason": "Incident severity moderate or higher",
                },
                {
                    "rule": "within_tolerance",
                    "condition": (
                        "An excursion was detected but none of the above quarantine conditions "
                        "apply"
                    ),
                    "action": "RELEASE",
                    "reason": "Excursion within stability tolerance",
                },
            ]
        },
    }
    with open(os.path.join(workspace, "excursion_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False, width=120)


def write_carrier_certifications(workspace, carriers):
    path = os.path.join(workspace, "carrier_certifications.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "carrier_id", "carrier_name", "cold_chain_certified",
            "certification_expiry", "last_audit_date",
        ])
        writer.writeheader()
        for c in carriers:
            days_to_expiry = random.randint(-30, 365)
            expiry = (REFERENCE_DATE + timedelta(days=days_to_expiry)).date()
            audit_back = random.randint(10, 180)
            audit = (REFERENCE_DATE - timedelta(days=audit_back)).date()
            writer.writerow({
                "carrier_id": c["carrier_id"],
                "carrier_name": c["carrier_name"],
                "cold_chain_certified": "yes" if c["certified_cold_chain"] else "no",
                "certification_expiry": str(expiry),
                "last_audit_date": str(audit),
            })


def write_storage_requirements(workspace):
    path = os.path.join(workspace, "storage_requirements.txt")
    lines = [
        "STORAGE CLASS TEMPERATURE REQUIREMENTS",
        "=" * 50,
        "",
    ]
    for sc, (lo, hi) in STORAGE_CLASSES.items():
        lines.append(f"{sc}: {lo}C to {hi}C")
    lines += [
        "",
        "Any temperature reading outside the specified range for",
        "the product's storage class constitutes a temperature excursion.",
        "Excursion severity and disposition are governed by the",
        "excursion policy configuration.",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_stability_profiles(workspace, products, n_files):
    n_per_file = max(1, len(products) // n_files)
    for batch_idx in range(n_files):
        start = batch_idx * n_per_file
        if batch_idx == n_files - 1:
            end = len(products)
        else:
            end = start + n_per_file
        batch = products[start:end]

        profiles = {}
        for p in batch:
            max_dev = round(random.uniform(1.0, 8.0), 1)
            max_dur = random.choice([15, 30, 45, 60, 90, 120, 180, 240])
            deg_rate = round(random.uniform(0.01, 0.50), 3)
            profiles[p["product_id"]] = {
                "product_name": p["product_name"],
                "storage_class": p["storage_class"],
                "nominal_range_celsius": {
                    "min": p["min_temp"],
                    "max": p["max_temp"],
                },
                "stability_tolerance": {
                    "max_allowed_deviation_celsius": max_dev,
                    "max_allowed_duration_minutes": max_dur,
                },
                "degradation_rate_per_degree_hour": deg_rate,
                "shelf_life_days": random.choice([90, 180, 365, 730]),
                "light_sensitive": random.choice([True, False]),
            }

        fname = f"stability_profiles_batch_{batch_idx+1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(profiles, f, indent=2)


def write_thermal_mappings(workspace, warehouses, n_files):
    n_per_file = max(1, len(warehouses) // n_files)
    zone_names = [
        "Cold Storage A", "Cold Storage B", "Freezer Unit",
        "Loading Dock", "Ambient Storage", "Receiving Bay",
        "Quarantine Area", "Packaging Area",
    ]
    for batch_idx in range(n_files):
        start = batch_idx * n_per_file
        if batch_idx == n_files - 1:
            end = len(warehouses)
        else:
            end = start + n_per_file
        batch = warehouses[start:end]

        fname = f"thermal_mapping_report_{batch_idx+1:03d}.csv"
        path = os.path.join(workspace, fname)
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "warehouse_id", "zone_id", "zone_name",
                "avg_temperature", "max_temperature", "min_temperature",
                "calibration_date", "compliance_status", "notes",
            ])
            writer.writeheader()
            for w in batch:
                n_zones = random.randint(3, 8)
                for z in range(n_zones):
                    compliant = random.random() < 0.80
                    base_temp = round(random.uniform(-25, 25), 1)
                    cal_back = random.randint(10, 365)
                    cal_date = str((REFERENCE_DATE - timedelta(days=cal_back)).date())
                    note = ""
                    if not compliant:
                        note = random.choice([
                            "Temperature variance exceeds threshold",
                            "Cooling unit intermittent failure detected",
                            "Door seal degradation noted",
                            "Insufficient airflow in zone",
                        ])
                    writer.writerow({
                        "warehouse_id": w["warehouse_id"],
                        "zone_id": f"{w['warehouse_id']}-Z{z+1:02d}",
                        "zone_name": zone_names[z % len(zone_names)],
                        "avg_temperature": base_temp,
                        "max_temperature": round(base_temp + random.uniform(1, 5), 1),
                        "min_temperature": round(base_temp - random.uniform(1, 5), 1),
                        "calibration_date": cal_date,
                        "compliance_status": "PASS" if compliant else "FAIL",
                        "notes": note,
                    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Reference data (not stored in DB; exposed via workspace files only)
    n_carriers = max(20, n_rows // 5)
    n_warehouses = max(15, n_rows // 7)

    products = generate_products(n_rows, fake)
    carriers = generate_carriers(n_carriers, fake)
    warehouses = generate_warehouses(n_warehouses, fake)

    # ---- DB tables ----

    cur.execute("""
        CREATE TABLE products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT,
            category TEXT,
            storage_class TEXT,
            min_temp REAL,
            max_temp REAL,
            unit_value REAL
        )
    """)
    for p in products:
        cur.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?)",
                    (p["product_id"], p["product_name"], p["category"],
                     p["storage_class"], p["min_temp"], p["max_temp"],
                     p["unit_value"]))

    cur.execute("""
        CREATE TABLE shipments (
            shipment_id TEXT PRIMARY KEY,
            product_id TEXT,
            carrier_id TEXT,
            origin_warehouse_id TEXT,
            destination_warehouse_id TEXT,
            status TEXT,
            ship_date TEXT,
            arrival_date TEXT,
            container_type TEXT,
            lot_number TEXT,
            quantity INTEGER,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
    """)
    shipments = generate_shipments(n_rows, products, carriers, warehouses, fake)
    for s in shipments:
        cur.execute("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(s.values()))

    cur.execute("""
        CREATE TABLE temperature_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id TEXT,
            timestamp TEXT,
            temperature REAL,
            sensor_id TEXT,
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
        )
    """)
    generate_temperature_logs(shipments, products, cur)

    cur.execute("""
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            shipment_id TEXT,
            carrier_id TEXT,
            incident_type TEXT,
            severity TEXT,
            incident_date TEXT,
            description TEXT,
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
        )
    """)
    generate_incidents(n_rows, shipments, carriers, fake, cur)

    conn.commit()
    conn.close()

    # ---- Workspace files ----

    # Fixed configuration files (not counted in SCALE)
    write_excursion_policy(workspace)
    write_carrier_certifications(workspace, carriers)
    write_storage_requirements(workspace)

    # Scalable data files
    n_stability = n_files // 2
    n_thermal = n_files - n_stability
    write_stability_profiles(workspace, products, n_stability)
    write_thermal_mappings(workspace, warehouses, n_thermal)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
