"""Data generation for the mis-sorted package detection task."""

import argparse
import csv
import json
import math
import os
import random
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}

# --------------- fixed constants (no randomness) ---------------
ZONES = ["A", "B", "C", "D", "E", "F"]
LANES = ["Lane-1", "Lane-2", "Lane-3", "Lane-4", "Lane-5", "Lane-6"]
ZONE_TO_LANE = dict(zip(ZONES, LANES))

# 30 five-digit postal-code prefixes, cycling through 6 zones
POSTAL_ZONE_MAP = {str(10000 + i): ZONES[i % len(ZONES)] for i in range(30)}

STATIONS = [f"STN-{i+1:03d}" for i in range(5)]
SHIPPING_CLASSES = ["standard", "express", "priority", "overnight"]
SCANNER_IDS = [f"SCN-{i+1:03d}" for i in range(8)]
SENSOR_IDS = [f"WGT-{i+1:03d}" for i in range(6)]
CUSTOMER_TIERS = ["standard", "premium", "enterprise"]
TIER_WEIGHTS = [0.6, 0.3, 0.1]
MISSORT_RATE = 0.18  # fraction of packages that are mis-sorted


def main(db_path: str, workspace: str):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_packages = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]
    postal_prefixes = list(POSTAL_ZONE_MAP.keys())

    # ================================================================
    # FIXED workspace files (generated first so random state is
    # identical across all SCALE values)
    # ================================================================

    # 1. zone_postal_mapping.json  (postal-code prefix -> zone)
    with open(os.path.join(workspace, "zone_postal_mapping.json"), "w") as fh:
        json.dump(POSTAL_ZONE_MAP, fh, indent=2)

    # 2. lane_zone_config.yaml  (zone -> correct sort lane)
    with open(os.path.join(workspace, "lane_zone_config.yaml"), "w") as fh:
        yaml.dump({"zone_to_lane": ZONE_TO_LANE}, fh, default_flow_style=False)

    # 3. cost_avoidance_rates.csv
    # fixed iteration order: SHIPPING_CLASSES x ZONES  -> 24 random calls
    cost_rate_rows = []
    for sc in SHIPPING_CLASSES:
        for z in ZONES:
            if sc == "overnight":
                base = round(random.uniform(15.0, 25.0), 2)
            elif sc == "priority":
                base = round(random.uniform(10.0, 18.0), 2)
            elif sc == "express":
                base = round(random.uniform(6.0, 12.0), 2)
            else:
                base = round(random.uniform(3.0, 8.0), 2)
            cost_rate_rows.append({"shipping_class": sc, "zone": z, "base_cost": base})

    with open(os.path.join(workspace, "cost_avoidance_rates.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["shipping_class", "zone", "base_cost"])
        w.writeheader()
        w.writerows(cost_rate_rows)

    # 4. sorting_policy.md
    with open(os.path.join(workspace, "sorting_policy.md"), "w") as fh:
        fh.write(
            "# Sorting Facility Policy Document\n\n"
            "## Cost Avoidance Calculation\n\n"
            "The cost avoidance for each mis-sorted package is computed as:\n\n"
            "    cost_avoidance = base_cost * tier_multiplier\n\n"
            "where base_cost comes from the cost avoidance rates file keyed by\n"
            "(shipping_class, destination_zone), and tier_multiplier is determined\n"
            "by the customer tier:\n\n"
            "- enterprise: 2.5\n"
            "- premium: 1.8\n"
            "- standard: 1.0\n\n"
            "Round every cost_avoidance value to exactly two decimal places.\n\n"
            "## Dimension Tolerance\n\n"
            "A dimension discrepancy is flagged when any single axis\n"
            "(length, width, or height) has an absolute difference greater than\n"
            "2.0 cm between the declared and scanned values.\n\n"
            "## Weight Tolerance\n\n"
            "A weight discrepancy is flagged when the absolute difference between\n"
            "declared weight and measured weight exceeds 0.5 kg.\n\n"
            "## Mis-Sort Definition\n\n"
            "A package is mis-sorted when its assigned sort lane does not match\n"
            "the correct lane for its destination postal code zone.  The correct\n"
            "lane is found by mapping the first five digits of the destination\n"
            "postal code to a zone, then mapping that zone to its designated lane.\n\n"
            "## Re-Sort List Ordering\n\n"
            "The daily re-sort list must be ordered by cost_avoidance descending.\n"
            "Ties are broken by package_id ascending.\n"
        )

    # ================================================================
    # SCALE-dependent data
    # ================================================================

    # --- workers ---
    num_workers = max(10, num_packages // 10)
    workers = []
    for i in range(num_workers):
        workers.append(
            {
                "worker_id": f"WRK-{i+1:04d}",
                "worker_name": fake.name(),
                "station_id": random.choice(STATIONS),
            }
        )

    # --- packages ---
    packages = []
    for i in range(num_packages):
        prefix = random.choice(postal_prefixes)
        postal_code = prefix + fake.numerify("##")
        zone = POSTAL_ZONE_MAP[prefix]
        correct_lane = ZONE_TO_LANE[zone]
        station = random.choice(STATIONS)
        shipping_class = random.choice(SHIPPING_CLASSES)

        length = round(random.uniform(10.0, 80.0), 1)
        width = round(random.uniform(10.0, 60.0), 1)
        height = round(random.uniform(5.0, 50.0), 1)
        weight = round(random.uniform(0.5, 30.0), 2)

        if random.random() < MISSORT_RATE:
            assigned_lane = random.choice([l for l in LANES if l != correct_lane])
        else:
            assigned_lane = correct_lane

        packages.append(
            {
                "package_id": f"PKG-{i+1:06d}",
                "tracking_number": fake.bothify("??########").upper(),
                "declared_weight": weight,
                "declared_length": length,
                "declared_width": width,
                "declared_height": height,
                "destination_postal_code": postal_code,
                "shipping_class": shipping_class,
                "station_id": station,
                "assigned_lane": assigned_lane,
            }
        )

    # --- dimension scans ---
    dimension_scans = []
    for i, pkg in enumerate(packages):
        dimension_scans.append(
            {
                "scan_id": f"DSC-{i+1:06d}",
                "package_id": pkg["package_id"],
                "scanned_length": round(pkg["declared_length"] + random.uniform(-2.5, 2.5), 1),
                "scanned_width": round(pkg["declared_width"] + random.uniform(-2.5, 2.5), 1),
                "scanned_height": round(pkg["declared_height"] + random.uniform(-2.5, 2.5), 1),
                "scanner_id": random.choice(SCANNER_IDS),
                "station_id": pkg["station_id"],
                "scan_time": fake.date_time_this_month().isoformat(),
            }
        )

    # --- weight readings ---
    weight_readings = []
    for i, pkg in enumerate(packages):
        weight_readings.append(
            {
                "reading_id": f"WRD-{i+1:06d}",
                "package_id": pkg["package_id"],
                "measured_weight": round(pkg["declared_weight"] + random.uniform(-0.7, 0.7), 2),
                "sensor_id": random.choice(SENSOR_IDS),
                "station_id": pkg["station_id"],
                "reading_time": fake.date_time_this_month().isoformat(),
            }
        )

    # --- sort assignments ---
    sort_assignments = []
    for i, pkg in enumerate(packages):
        worker = random.choice(workers)
        sort_assignments.append(
            {
                "assignment_id": f"ASN-{i+1:06d}",
                "package_id": pkg["package_id"],
                "assigned_lane": pkg["assigned_lane"],
                "worker_id": worker["worker_id"],
                "station_id": pkg["station_id"],
                "assignment_time": fake.date_time_this_month().isoformat(),
            }
        )

    # --- customer info (NOT stored in DB — workspace-only) ---
    customer_data = []
    for pkg in packages:
        tier = random.choices(CUSTOMER_TIERS, weights=TIER_WEIGHTS, k=1)[0]
        insurance = (
            round(random.uniform(50.0, 5000.0), 2)
            if tier != "standard"
            else round(random.uniform(0.0, 500.0), 2)
        )
        customer_data.append(
            {
                "package_id": pkg["package_id"],
                "customer_id": fake.bothify("CUST-####").upper(),
                "customer_tier": tier,
                "insurance_value": insurance,
                "fragile": random.choice([True, False]),
            }
        )

    # ================================================================
    # Database
    # ================================================================
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """CREATE TABLE IF NOT EXISTS packages (
            package_id            TEXT PRIMARY KEY,
            tracking_number       TEXT NOT NULL,
            declared_weight       REAL,
            declared_length       REAL,
            declared_width        REAL,
            declared_height       REAL,
            destination_postal_code TEXT,
            shipping_class        TEXT,
            station_id            TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS dimension_scans (
            scan_id       TEXT PRIMARY KEY,
            package_id    TEXT NOT NULL,
            scanned_length REAL,
            scanned_width  REAL,
            scanned_height REAL,
            scanner_id    TEXT,
            station_id    TEXT,
            scan_time     TEXT,
            FOREIGN KEY (package_id) REFERENCES packages(package_id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS weight_readings (
            reading_id     TEXT PRIMARY KEY,
            package_id     TEXT NOT NULL,
            measured_weight REAL,
            sensor_id      TEXT,
            station_id     TEXT,
            reading_time   TEXT,
            FOREIGN KEY (package_id) REFERENCES packages(package_id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS sort_assignments (
            assignment_id   TEXT PRIMARY KEY,
            package_id      TEXT NOT NULL,
            assigned_lane   TEXT,
            worker_id       TEXT,
            station_id      TEXT,
            assignment_time TEXT,
            FOREIGN KEY (package_id) REFERENCES packages(package_id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS workers (
            worker_id   TEXT PRIMARY KEY,
            worker_name TEXT,
            station_id  TEXT
        )"""
    )

    for pkg in packages:
        cur.execute(
            "INSERT INTO packages VALUES (?,?,?,?,?,?,?,?,?)",
            (
                pkg["package_id"], pkg["tracking_number"], pkg["declared_weight"],
                pkg["declared_length"], pkg["declared_width"], pkg["declared_height"],
                pkg["destination_postal_code"], pkg["shipping_class"], pkg["station_id"],
            ),
        )
    for s in dimension_scans:
        cur.execute(
            "INSERT INTO dimension_scans VALUES (?,?,?,?,?,?,?,?)",
            (s["scan_id"], s["package_id"], s["scanned_length"], s["scanned_width"],
             s["scanned_height"], s["scanner_id"], s["station_id"], s["scan_time"]),
        )
    for w in weight_readings:
        cur.execute(
            "INSERT INTO weight_readings VALUES (?,?,?,?,?,?)",
            (w["reading_id"], w["package_id"], w["measured_weight"],
             w["sensor_id"], w["station_id"], w["reading_time"]),
        )
    for sa in sort_assignments:
        cur.execute(
            "INSERT INTO sort_assignments VALUES (?,?,?,?,?,?)",
            (sa["assignment_id"], sa["package_id"], sa["assigned_lane"],
             sa["worker_id"], sa["station_id"], sa["assignment_time"]),
        )
    for wk in workers:
        cur.execute(
            "INSERT INTO workers VALUES (?,?,?)",
            (wk["worker_id"], wk["worker_name"], wk["station_id"]),
        )

    conn.commit()
    conn.close()

    # ================================================================
    # SCALABLE workspace files
    # ================================================================
    num_csv  = max(2, num_files * 4 // 10)
    num_json = max(1, num_files * 3 // 10)
    num_yaml = max(1, num_files * 2 // 10)
    num_txt  = max(1, num_files - num_csv - num_json - num_yaml)

    # --- CSV: shipment batch manifests (contain customer_tier — essential) ---
    pkgs_per_batch = math.ceil(len(packages) / num_csv)
    for i in range(num_csv):
        start = i * pkgs_per_batch
        end = min(start + pkgs_per_batch, len(packages))
        batch = customer_data[start:end]
        path = os.path.join(workspace, f"shipment_batch_{i+1:03d}.csv")
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["package_id", "customer_id", "customer_tier",
                            "insurance_value", "fragile"],
            )
            writer.writeheader()
            writer.writerows(batch)

    # --- JSON: scanner calibration reports ---
    for i in range(num_json):
        assigned = [SCANNER_IDS[j] for j in range(len(SCANNER_IDS)) if j % num_json == i]
        if not assigned:
            assigned = [SCANNER_IDS[i % len(SCANNER_IDS)]]
        cal = {}
        for scn in assigned:
            cal[scn] = {
                "calibration_date": fake.date_this_month().isoformat(),
                "status": random.choice(["calibrated", "needs_recalibration", "calibrated"]),
                "length_offset_cm": round(random.uniform(-0.5, 0.5), 2),
                "width_offset_cm": round(random.uniform(-0.5, 0.5), 2),
                "height_offset_cm": round(random.uniform(-0.3, 0.3), 2),
                "technician": fake.name(),
            }
        path = os.path.join(workspace, f"scanner_calibration_{i+1:03d}.json")
        with open(path, "w") as fh:
            json.dump(cal, fh, indent=2)

    # --- YAML: station operational logs ---
    for i in range(num_yaml):
        stn = STATIONS[i % len(STATIONS)]
        stn_count = sum(1 for p in packages if p["station_id"] == stn)
        log = {
            "station_id": stn,
            "report_date": fake.date_this_month().isoformat(),
            "shift_supervisor": fake.name(),
            "packages_processed": stn_count,
            "conveyor_status": random.choice(["operational", "degraded"]),
            "temperature_celsius": round(random.uniform(18.0, 28.0), 1),
            "notes": fake.sentence(nb_words=12),
            "incidents": [
                {"time": fake.time(), "description": fake.sentence(nb_words=8)}
                for _ in range(random.randint(0, 3))
            ],
        }
        path = os.path.join(workspace, f"station_log_{i+1:03d}.yaml")
        with open(path, "w") as fh:
            yaml.dump(log, fh, default_flow_style=False)

    # --- TXT: worker incident reports ---
    for i in range(num_txt):
        wk = workers[i % len(workers)]
        lines = [
            "Worker Incident Report",
            f"Worker: {wk['worker_name']} ({wk['worker_id']})",
            f"Station: {wk['station_id']}",
            f"Date: {fake.date_this_month().isoformat()}",
            "",
            "Summary:",
            fake.paragraph(nb_sentences=3),
            "",
            "Actions Taken:",
            fake.paragraph(nb_sentences=2),
        ]
        path = os.path.join(workspace, f"worker_incident_{i+1:03d}.txt")
        with open(path, "w") as fh:
            fh.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
