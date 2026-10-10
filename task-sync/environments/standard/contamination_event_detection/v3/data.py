import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 800,
    "num_workspace_files": 40,
}

# ── Deterministic seeding ──────────────────────────────────────────────
fake = Faker()
Faker.seed(42)
np.random.seed(42)

# ── Constants ──────────────────────────────────────────────────────────
REFERENCE_DATE = datetime(2026, 3, 15)
DATE_RANGE_START = datetime(2026, 1, 1)

WAREHOUSES = [
    {"warehouse_id": "WH-001", "name": "North Valley Storage", "location": "Sacramento, CA", "capacity_tons": 5000},
    {"warehouse_id": "WH-002", "name": "Central Plains Depot", "location": "Des Moines, IA", "capacity_tons": 8000},
    {"warehouse_id": "WH-003", "name": "Southeast Hub", "location": "Atlanta, GA", "capacity_tons": 6000},
]

ZONE_SUFFIXES = ["A", "B", "C", "D"]

CROP_TYPES = ["Corn", "Soybean", "Wheat", "Rice", "Sunflower", "Barley", "Sorghum", "Cotton"]
VARIETIES = {
    "Corn": ["Pioneer P1197", "DeKalb DKC62-08", "Golden Harvest G10L31"],
    "Soybean": ["Asgrow AG36X6", "Pioneer P22T41E", "Stine 38EA02"],
    "Wheat": ["SY Monument", "WestBred WB4303", "Limagrain LCS Chrome"],
    "Rice": ["CL153", "Jupiter", "Titan"],
    "Sunflower": ["Mycogen 8H449", "Pioneer P64HE139", "Syngenta NK Durango"],
    "Barley": ["Hockett", "CDC Copeland", "Odyssey"],
    "Sorghum": ["Pioneer 84P80", "DeKalb DKS37-07", "Alta Seeds AF7401"],
    "Cotton": ["Deltapine DP1646", "Phytogen PHY340W3FE", "Stoneville ST5471"],
}
GRADES = ["Certified", "Foundation", "Registered", "Commercial"]
SEED_TREATMENTS = ["Cruiser Maxx", "Poncho/VOTiVO", "Acceleron", "EverGol Energy", "Rancona Apex", "Gaucho XT"]

# crop-specific temperature / humidity thresholds (used for config file)
CROP_THRESHOLDS = {
    "Corn":      {"max_temperature": 25.0, "max_humidity": 65.0},
    "Soybean":   {"max_temperature": 23.0, "max_humidity": 60.0},
    "Wheat":     {"max_temperature": 20.0, "max_humidity": 55.0},
    "Rice":      {"max_temperature": 22.0, "max_humidity": 70.0},
    "Sunflower": {"max_temperature": 24.0, "max_humidity": 60.0},
    "Barley":    {"max_temperature": 18.0, "max_humidity": 55.0},
    "Sorghum":   {"max_temperature": 26.0, "max_humidity": 65.0},
    "Cotton":    {"max_temperature": 25.0, "max_humidity": 60.0},
}

PEST_TYPES = ["Fumigation", "Bait Station", "Residual Spray", "Fogging", "Heat Treatment"]
CHEMICALS = ["Phosphine", "Deltamethrin", "Malathion", "Pyriproxyfen", "Spinosad", "Diatomaceous Earth"]

INSPECTORS = ["Dr. R. Nakamura", "Dr. S. Petrov", "Dr. L. Okafor", "Dr. M. Rivera", "Dr. A. Chang"]
PESTS_FOUND = ["None", "Sitophilus oryzae", "Rhyzopertha dominica", "Tribolium castaneum",
               "Plodia interpunctella", "Ephestia elutella", "Cryptolestes ferrugineus"]
DISEASES_FOUND = ["None", "Aspergillus flavus", "Fusarium graminearum", "Penicillium spp.",
                  "Alternaria alternata", "Cladosporium spp."]

MOVEMENT_REASONS = ["Consolidation", "Pest avoidance", "Regrade", "Space optimization",
                    "Temperature management", "Shipment staging", "Inspection access"]


def build_zones():
    zones = []
    for wh in WAREHOUSES:
        for suffix in ZONE_SUFFIXES:
            zones.append({
                "zone_id": f"{wh['warehouse_id']}-{suffix}",
                "warehouse_id": wh["warehouse_id"],
                "zone_name": f"Zone {suffix}",
                "zone_type": np.random.choice(["Cold Storage", "Ambient", "Controlled Atmosphere", "Dry Storage"]),
                "capacity_tons": int(wh["capacity_tons"] / len(ZONE_SUFFIXES)),
            })
    return zones


def generate_seed_lots(n_lots, zones):
    lots = []
    for i in range(n_lots):
        crop = np.random.choice(CROP_TYPES)
        zone = zones[np.random.randint(len(zones))]
        arrival = DATE_RANGE_START - timedelta(days=int(np.random.randint(30, 180)))
        lots.append({
            "lot_id": f"LOT-{i+1:04d}",
            "crop_type": crop,
            "variety": np.random.choice(VARIETIES[crop]),
            "quantity_kg": int(np.random.randint(500, 15000)),
            "grade": np.random.choice(GRADES),
            "arrival_date": arrival.strftime("%Y-%m-%d"),
            "current_warehouse_id": zone["warehouse_id"],
            "current_zone_id": zone["zone_id"],
            "status": np.random.choice(["Active", "Pending Release", "Under Review"], p=[0.7, 0.2, 0.1]),
            "seed_treatment": np.random.choice(SEED_TREATMENTS),
            "germination_rate": round(float(np.random.uniform(85, 99)), 1),
            "origin_farm": fake.company() + " Farms",
        })
    return lots


def generate_sensor_logs(n_logs, zones):
    """Generate sensor readings. Inject anomalies in specific zones."""
    logs = []
    n_days = (REFERENCE_DATE - DATE_RANGE_START).days
    # zones that will have anomalies (deterministic based on index)
    anomaly_zone_ids = set()
    for idx in [1, 5, 9]:  # WH-001-B, WH-002-B, WH-003-B
        if idx < len(zones):
            anomaly_zone_ids.add(zones[idx]["zone_id"])
    # Also add WH-001-D and WH-003-C for variety
    for idx in [3, 10]:
        if idx < len(zones):
            anomaly_zone_ids.add(zones[idx]["zone_id"])

    for i in range(n_logs):
        zone = zones[i % len(zones)]
        day_offset = int(np.random.randint(0, n_days))
        ts = DATE_RANGE_START + timedelta(days=day_offset, hours=int(np.random.randint(0, 24)),
                                          minutes=int(np.random.randint(0, 60)))

        # Base readings
        base_temp = float(np.random.normal(18, 3))
        base_hum = float(np.random.normal(55, 8))

        # Inject anomalies for specific zones on certain days
        if zone["zone_id"] in anomaly_zone_ids and day_offset % 7 < 3:
            # Spike temperature or humidity
            if i % 3 == 0:
                base_temp += float(np.random.uniform(8, 15))
            if i % 3 != 2:
                base_hum += float(np.random.uniform(10, 25))

        logs.append({
            "log_id": i + 1,
            "warehouse_id": zone["warehouse_id"],
            "zone_id": zone["zone_id"],
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "temperature": round(base_temp, 2),
            "humidity": round(min(base_hum, 99.0), 2),
            "co2_ppm": round(float(np.random.normal(400, 50)), 1),
        })
    return logs


def generate_lot_movements(n_movements, lots, zones):
    movements = []
    zone_ids = [z["zone_id"] for z in zones]
    zone_wh_map = {z["zone_id"]: z["warehouse_id"] for z in zones}

    for i in range(n_movements):
        lot = lots[i % len(lots)]
        from_zone = np.random.choice(zone_ids)
        # Move within same warehouse or across
        if np.random.random() < 0.7:
            same_wh_zones = [z for z in zone_ids if zone_wh_map[z] == zone_wh_map[from_zone] and z != from_zone]
            to_zone = np.random.choice(same_wh_zones) if same_wh_zones else np.random.choice(zone_ids)
        else:
            to_zone = np.random.choice(zone_ids)

        move_date = DATE_RANGE_START + timedelta(days=int(np.random.randint(0, (REFERENCE_DATE - DATE_RANGE_START).days)))
        movements.append({
            "movement_id": i + 1,
            "lot_id": lot["lot_id"],
            "from_warehouse_id": zone_wh_map[from_zone],
            "from_zone_id": from_zone,
            "to_warehouse_id": zone_wh_map[to_zone],
            "to_zone_id": to_zone,
            "move_date": move_date.strftime("%Y-%m-%d"),
            "handler": fake.name(),
            "reason": np.random.choice(MOVEMENT_REASONS),
        })
    return movements


def generate_pest_treatments(n_treatments, zones):
    treatments = []
    for i in range(n_treatments):
        zone = zones[i % len(zones)]
        apply_date = DATE_RANGE_START + timedelta(days=int(np.random.randint(0, 60)))
        # Some treatments will be overdue (next_due before reference date with enough margin)
        if i % 5 == 0:
            next_due = apply_date + timedelta(days=int(np.random.randint(14, 30)))
        else:
            next_due = apply_date + timedelta(days=int(np.random.randint(60, 120)))

        treatments.append({
            "treatment_id": i + 1,
            "warehouse_id": zone["warehouse_id"],
            "zone_id": zone["zone_id"],
            "treatment_type": np.random.choice(PEST_TYPES),
            "chemical_used": np.random.choice(CHEMICALS),
            "date_applied": apply_date.strftime("%Y-%m-%d"),
            "next_due_date": next_due.strftime("%Y-%m-%d"),
            "effectiveness_pct": round(float(np.random.uniform(60, 100)), 1),
        })
    return treatments


def generate_phytosanitary_inspections(n_inspections, lots):
    inspections = []
    for i in range(n_inspections):
        lot = lots[i % len(lots)]
        insp_date = DATE_RANGE_START + timedelta(days=int(np.random.randint(0, (REFERENCE_DATE - DATE_RANGE_START).days)))

        pest = np.random.choice(PESTS_FOUND, p=[0.55, 0.1, 0.08, 0.07, 0.07, 0.07, 0.06])
        disease = np.random.choice(DISEASES_FOUND, p=[0.5, 0.12, 0.1, 0.1, 0.1, 0.08])

        if pest == "None" and disease == "None":
            severity = "None"
            result = "PASS"
        elif pest != "None" and disease != "None":
            severity = np.random.choice(["High", "Critical"], p=[0.4, 0.6])
            result = "FAIL"
        else:
            severity = np.random.choice(["Low", "Medium", "High"], p=[0.3, 0.4, 0.3])
            result = np.random.choice(["PASS", "CONDITIONAL", "FAIL"], p=[0.2, 0.4, 0.4])

        inspections.append({
            "inspection_id": i + 1,
            "lot_id": lot["lot_id"],
            "inspection_date": insp_date.strftime("%Y-%m-%d"),
            "inspector": np.random.choice(INSPECTORS),
            "pest_detected": pest,
            "disease_detected": disease,
            "severity": severity,
            "result_status": result,
        })
    return inspections


# ── Database ──────────────────────────────────────────────────────────

def init_db(db_path, zones, lots, sensor_logs, movements, treatments, inspections):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS warehouses")
    c.execute("DROP TABLE IF EXISTS zones")
    c.execute("DROP TABLE IF EXISTS seed_lots")
    c.execute("DROP TABLE IF EXISTS sensor_logs")
    c.execute("DROP TABLE IF EXISTS lot_movements")
    c.execute("DROP TABLE IF EXISTS pest_treatments")
    c.execute("DROP TABLE IF EXISTS phytosanitary_inspections")

    c.execute("""CREATE TABLE warehouses (
        warehouse_id TEXT PRIMARY KEY, name TEXT, location TEXT, capacity_tons INTEGER)""")
    for wh in WAREHOUSES:
        c.execute("INSERT INTO warehouses VALUES (?,?,?,?)",
                  (wh["warehouse_id"], wh["name"], wh["location"], wh["capacity_tons"]))

    c.execute("""CREATE TABLE zones (
        zone_id TEXT PRIMARY KEY, warehouse_id TEXT, zone_name TEXT, zone_type TEXT, capacity_tons INTEGER,
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id))""")
    for z in zones:
        c.execute("INSERT INTO zones VALUES (?,?,?,?,?)",
                  (z["zone_id"], z["warehouse_id"], z["zone_name"], z["zone_type"], z["capacity_tons"]))

    c.execute("""CREATE TABLE seed_lots (
        lot_id TEXT PRIMARY KEY, crop_type TEXT, variety TEXT, quantity_kg INTEGER,
        grade TEXT, arrival_date TEXT, current_warehouse_id TEXT, current_zone_id TEXT,
        status TEXT, seed_treatment TEXT, germination_rate REAL, origin_farm TEXT,
        FOREIGN KEY (current_warehouse_id) REFERENCES warehouses(warehouse_id),
        FOREIGN KEY (current_zone_id) REFERENCES zones(zone_id))""")
    for lot in lots:
        c.execute("INSERT INTO seed_lots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (lot["lot_id"], lot["crop_type"], lot["variety"], lot["quantity_kg"],
                   lot["grade"], lot["arrival_date"], lot["current_warehouse_id"],
                   lot["current_zone_id"], lot["status"], lot["seed_treatment"],
                   lot["germination_rate"], lot["origin_farm"]))

    c.execute("""CREATE TABLE sensor_logs (
        log_id INTEGER PRIMARY KEY, warehouse_id TEXT, zone_id TEXT,
        timestamp TEXT, temperature REAL, humidity REAL, co2_ppm REAL,
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id),
        FOREIGN KEY (zone_id) REFERENCES zones(zone_id))""")
    for sl in sensor_logs:
        c.execute("INSERT INTO sensor_logs VALUES (?,?,?,?,?,?,?)",
                  (sl["log_id"], sl["warehouse_id"], sl["zone_id"], sl["timestamp"],
                   sl["temperature"], sl["humidity"], sl["co2_ppm"]))

    c.execute("""CREATE TABLE lot_movements (
        movement_id INTEGER PRIMARY KEY, lot_id TEXT,
        from_warehouse_id TEXT, from_zone_id TEXT,
        to_warehouse_id TEXT, to_zone_id TEXT,
        move_date TEXT, handler TEXT, reason TEXT,
        FOREIGN KEY (lot_id) REFERENCES seed_lots(lot_id))""")
    for m in movements:
        c.execute("INSERT INTO lot_movements VALUES (?,?,?,?,?,?,?,?,?)",
                  (m["movement_id"], m["lot_id"], m["from_warehouse_id"], m["from_zone_id"],
                   m["to_warehouse_id"], m["to_zone_id"], m["move_date"],
                   m["handler"], m["reason"]))

    c.execute("""CREATE TABLE pest_treatments (
        treatment_id INTEGER PRIMARY KEY, warehouse_id TEXT, zone_id TEXT,
        treatment_type TEXT, chemical_used TEXT, date_applied TEXT,
        next_due_date TEXT, effectiveness_pct REAL,
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id),
        FOREIGN KEY (zone_id) REFERENCES zones(zone_id))""")
    for t in treatments:
        c.execute("INSERT INTO pest_treatments VALUES (?,?,?,?,?,?,?,?)",
                  (t["treatment_id"], t["warehouse_id"], t["zone_id"], t["treatment_type"],
                   t["chemical_used"], t["date_applied"], t["next_due_date"], t["effectiveness_pct"]))

    c.execute("""CREATE TABLE phytosanitary_inspections (
        inspection_id INTEGER PRIMARY KEY, lot_id TEXT,
        inspection_date TEXT, inspector TEXT,
        pest_detected TEXT, disease_detected TEXT,
        severity TEXT, result_status TEXT,
        FOREIGN KEY (lot_id) REFERENCES seed_lots(lot_id))""")
    for insp in inspections:
        c.execute("INSERT INTO phytosanitary_inspections VALUES (?,?,?,?,?,?,?,?)",
                  (insp["inspection_id"], insp["lot_id"], insp["inspection_date"],
                   insp["inspector"], insp["pest_detected"], insp["disease_detected"],
                   insp["severity"], insp["result_status"]))

    conn.commit()
    conn.close()


# ── Workspace ─────────────────────────────────────────────────────────

def build_zone_adjacency():
    """Zones within a warehouse are arranged A-B-C-D linearly."""
    adj = []
    for wh in WAREHOUSES:
        for i, s1 in enumerate(ZONE_SUFFIXES):
            for j, s2 in enumerate(ZONE_SUFFIXES):
                if abs(i - j) == 1:
                    adj.append({
                        "zone_id": f"{wh['warehouse_id']}-{s1}",
                        "adjacent_zone_id": f"{wh['warehouse_id']}-{s2}",
                        "warehouse_id": wh["warehouse_id"],
                    })
    return adj


def write_config_files(workspace):
    """Write fixed config / policy files (not counted in SCALE)."""
    # contamination_thresholds.yaml
    import yaml
    thresholds = {"crop_thresholds": CROP_THRESHOLDS}
    with open(os.path.join(workspace, "contamination_thresholds.yaml"), "w") as f:
        yaml.dump(thresholds, f, default_flow_style=False, sort_keys=False)

    # quarantine_rules.json
    rules = {
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "risk_weights": {
            "SENSOR_EXCEEDANCE": 30,
            "ADJACENT_CONTAMINATION": 25,
            "OVERDUE_TREATMENT": 20,
            "MOVEMENT_EXPOSURE": 25,
        },
        "action_thresholds": [
            {"min_score": 50, "action": "IMMEDIATE_QUARANTINE"},
            {"min_score": 25, "action": "ENHANCED_MONITORING"},
            {"min_score": 1, "action": "STANDARD_REVIEW"},
        ],
        "overdue_grace_days": 7,
    }
    with open(os.path.join(workspace, "quarantine_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)

    # zone_adjacency.csv
    adj = build_zone_adjacency()
    with open(os.path.join(workspace, "zone_adjacency.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["zone_id", "adjacent_zone_id", "warehouse_id"])
        w.writeheader()
        w.writerows(adj)

    # pest_treatment_protocols.md
    with open(os.path.join(workspace, "pest_treatment_protocols.md"), "w") as f:
        f.write("Pest Treatment Protocol Reference\n\n")
        f.write("A zone is considered to have an overdue pest treatment when the most recent\n")
        f.write("treatment record for that zone has a next_due_date earlier than the reference\n")
        f.write("date minus the overdue_grace_days specified in quarantine_rules.json.\n\n")
        f.write("When multiple treatments exist for a zone, only the one with the latest\n")
        f.write("date_applied is considered current. Earlier treatments are historical.\n\n")
        f.write("Overdue treatments affect ALL lots currently stored in the zone, regardless\n")
        f.write("of their crop type or grade.\n")


def write_sensor_report_files(workspace, sensor_logs, n_files):
    """Write daily sensor summary CSVs split across n_files."""
    df = pd.DataFrame(sensor_logs)
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    # Group by warehouse
    wh_ids = sorted(df["warehouse_id"].unique())
    files_per_wh = max(1, n_files // len(wh_ids))
    remainder = n_files - files_per_wh * len(wh_ids)

    file_idx = 0
    for wh_i, wh_id in enumerate(wh_ids):
        wh_df = df[df["warehouse_id"] == wh_id]
        all_dates = sorted(wh_df["date"].unique())
        n_this_wh = files_per_wh + (1 if wh_i < remainder else 0)

        if len(all_dates) == 0:
            continue

        chunk_size = max(1, math.ceil(len(all_dates) / n_this_wh))
        for ci in range(n_this_wh):
            chunk_dates = all_dates[ci * chunk_size: (ci + 1) * chunk_size]
            if not chunk_dates:
                continue
            chunk_df = wh_df[wh_df["date"].isin(chunk_dates)]
            daily = chunk_df.groupby(["date", "zone_id"]).agg(
                avg_temperature=("temperature", "mean"),
                min_temperature=("temperature", "min"),
                max_temperature=("temperature", "max"),
                avg_humidity=("humidity", "mean"),
                min_humidity=("humidity", "min"),
                max_humidity=("humidity", "max"),
                reading_count=("log_id", "count"),
            ).reset_index()
            daily = daily.round(2)
            # Anomaly flag: max_temp > 28 or max_humidity > 75 (absolute thresholds)
            daily["anomaly_detected"] = ((daily["max_temperature"] > 28) | (daily["max_humidity"] > 75)).astype(int)

            fname = f"sensor_report_{wh_id}_part{ci+1}.csv"
            daily.to_csv(os.path.join(workspace, fname), index=False)
            file_idx += 1


def write_lot_manifest_files(workspace, lots, n_files):
    """Write lot manifests split into n_files batches as JSON."""
    chunk_size = max(1, math.ceil(len(lots) / n_files))
    for i in range(n_files):
        chunk = lots[i * chunk_size: (i + 1) * chunk_size]
        if not chunk:
            continue
        # Manifests contain lot metadata but NOT current location
        manifest = []
        for lot in chunk:
            manifest.append({
                "lot_id": lot["lot_id"],
                "crop_type": lot["crop_type"],
                "variety": lot["variety"],
                "quantity_kg": lot["quantity_kg"],
                "grade": lot["grade"],
                "arrival_date": lot["arrival_date"],
                "origin_farm": lot["origin_farm"],
                "seed_treatment": lot["seed_treatment"],
                "germination_rate": lot["germination_rate"],
            })
        fname = f"lot_manifest_batch_{i+1}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(manifest, f, indent=2)


def write_movement_log_files(workspace, movements, n_files):
    """Write movement logs split by month as CSV."""
    df = pd.DataFrame(movements)
    df["move_date_dt"] = pd.to_datetime(df["move_date"])
    df = df.sort_values("move_date_dt")

    chunk_size = max(1, math.ceil(len(df) / n_files))
    for i in range(n_files):
        chunk = df.iloc[i * chunk_size: (i + 1) * chunk_size]
        if chunk.empty:
            continue
        out = chunk[["movement_id", "lot_id", "from_warehouse_id", "from_zone_id",
                      "to_warehouse_id", "to_zone_id", "move_date", "handler", "reason"]]
        fname = f"movement_log_part_{i+1}.csv"
        out.to_csv(os.path.join(workspace, fname), index=False)


def build_workspace(workspace, lots, sensor_logs, movements):
    os.makedirs(workspace, exist_ok=True)

    n = SCALE["num_workspace_files"]
    n_sensor = n * 3 // 10
    n_manifest = n * 4 // 10
    n_movement = n - n_sensor - n_manifest

    write_config_files(workspace)
    write_sensor_report_files(workspace, sensor_logs, n_sensor)
    write_lot_manifest_files(workspace, lots, n_manifest)
    write_movement_log_files(workspace, movements, n_movement)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    zones = build_zones()
    n = SCALE["rows_per_table"]

    lots = generate_seed_lots(n, zones)
    sensor_logs = generate_sensor_logs(n, zones)
    movements = generate_lot_movements(n, lots, zones)
    treatments = generate_pest_treatments(n, zones)
    inspections = generate_phytosanitary_inspections(n, lots)

    init_db(args.db_path, zones, lots, sensor_logs, movements, treatments, inspections)
    build_workspace(args.workspace, lots, sensor_logs, movements)

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Seed lots: {len(lots)}")
    print(f"  Sensor logs: {len(sensor_logs)}")
    print(f"  Movements: {len(movements)}")
    print(f"  Treatments: {len(treatments)}")
    print(f"  Inspections: {len(inspections)}")


if __name__ == "__main__":
    main()
