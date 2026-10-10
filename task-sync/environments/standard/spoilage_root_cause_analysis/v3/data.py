import argparse
import sqlite3
import os
import json
import csv
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 480,
    "num_workspace_files": 32,
}

# ── Constants ──────────────────────────────────────────────────────────
CROP_TYPES = [
    "spinach", "kale", "romaine_lettuce",
    "arugula", "swiss_chard", "butter_lettuce",
]
FARM_NAMES = [
    "Green Valley Farm", "Sunrise Organics", "River Bend Produce",
    "Hilltop Gardens", "Fresh Fields Co", "Valley View Ranch",
    "Meadow Creek Farm", "Oak Ridge Farms",
]
WAREHOUSE_IDS = ["WH01", "WH02", "WH03", "WH04", "WH05"]
ZONES = ["A", "B", "C", "D"]
VEHICLE_IDS = [f"V{i:02d}" for i in range(1, 13)]
DEFECT_OPTIONS = [
    "wilting", "discoloration", "sliminess",
    "off_odor", "mold", "leaf_browning",
]

SPOILAGE_FRACTION = 0.20
ROOT_CAUSES = [
    "transport_temperature_excursion",
    "warehouse_humidity_violation",
    "delayed_precooling",
    "adverse_field_conditions",
]

CROP_THRESHOLDS = {
    "spinach": {
        "max_transport_temp_c": 4.0,
        "max_warehouse_humidity_pct": 95.0,
        "max_precool_delay_hours": 2.0,
        "max_field_temp_c": 30.0,
        "max_rainfall_mm": 20.0,
    },
    "kale": {
        "max_transport_temp_c": 4.5,
        "max_warehouse_humidity_pct": 95.0,
        "max_precool_delay_hours": 2.5,
        "max_field_temp_c": 32.0,
        "max_rainfall_mm": 25.0,
    },
    "romaine_lettuce": {
        "max_transport_temp_c": 3.5,
        "max_warehouse_humidity_pct": 96.0,
        "max_precool_delay_hours": 1.5,
        "max_field_temp_c": 28.0,
        "max_rainfall_mm": 15.0,
    },
    "arugula": {
        "max_transport_temp_c": 3.0,
        "max_warehouse_humidity_pct": 94.0,
        "max_precool_delay_hours": 1.5,
        "max_field_temp_c": 28.0,
        "max_rainfall_mm": 18.0,
    },
    "swiss_chard": {
        "max_transport_temp_c": 5.0,
        "max_warehouse_humidity_pct": 96.0,
        "max_precool_delay_hours": 3.0,
        "max_field_temp_c": 33.0,
        "max_rainfall_mm": 25.0,
    },
    "butter_lettuce": {
        "max_transport_temp_c": 3.0,
        "max_warehouse_humidity_pct": 93.0,
        "max_precool_delay_hours": 1.5,
        "max_field_temp_c": 27.0,
        "max_rainfall_mm": 15.0,
    },
}

SPOILAGE_SEVERITY = [
    (0, 5, "none", "A"),
    (5, 15, "minor", "B"),
    (15, 30, "moderate", "C"),
    (30, 50, "major", "D"),
    (50, 100, "critical", "F"),
]


def _grade_for_spoilage(pct):
    for lo, hi, _sev, grade in SPOILAGE_SEVERITY:
        if lo <= pct < hi:
            return grade
    return "F"


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    num_batches = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── Create tables ──────────────────────────────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS batches (
        batch_id TEXT PRIMARY KEY,
        crop_type TEXT NOT NULL,
        farm_origin TEXT NOT NULL,
        harvest_datetime TEXT NOT NULL,
        quantity_kg REAL NOT NULL,
        initial_temp_c REAL NOT NULL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS transport_legs (
        leg_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        vehicle_id TEXT NOT NULL,
        departure_time TEXT NOT NULL,
        arrival_time TEXT NOT NULL,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS temp_readings (
        reading_id TEXT PRIMARY KEY,
        leg_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        temperature_c REAL NOT NULL,
        sensor_position TEXT NOT NULL,
        FOREIGN KEY (leg_id) REFERENCES transport_legs(leg_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS warehouse_records (
        record_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        warehouse_id TEXT NOT NULL,
        zone TEXT NOT NULL,
        check_datetime TEXT NOT NULL,
        humidity_pct REAL NOT NULL,
        temperature_c REAL NOT NULL,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS inspections (
        inspection_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        inspection_date TEXT NOT NULL,
        inspector_id TEXT NOT NULL,
        spoilage_pct REAL NOT NULL,
        defect_types TEXT NOT NULL,
        overall_grade TEXT NOT NULL,
        notes TEXT,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS field_conditions (
        batch_id TEXT PRIMARY KEY,
        harvest_date TEXT NOT NULL,
        harvest_time TEXT NOT NULL,
        farm TEXT NOT NULL,
        field_temperature_c REAL NOT NULL,
        rainfall_last_24h_mm REAL NOT NULL,
        soil_moisture_pct REAL NOT NULL,
        wind_speed_kmh REAL NOT NULL,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
    )""")

    # ── Decide which batches are spoiled & why ─────────────────────────
    num_spoiled = max(4, int(num_batches * SPOILAGE_FRACTION))
    spoiled_indices = sorted(
        np.random.choice(num_batches, num_spoiled, replace=False).tolist()
    )
    spoiled_cause = {}
    for i, idx in enumerate(spoiled_indices):
        spoiled_cause[idx] = ROOT_CAUSES[i % len(ROOT_CAUSES)]

    base_date = datetime(2025, 6, 1, 6, 0, 0)

    # ── Generate batches ───────────────────────────────────────────────
    batches = []
    for i in range(num_batches):
        harvest_dt = base_date + timedelta(
            hours=int(np.random.randint(0, 24 * 30)),
            minutes=int(np.random.randint(0, 60)),
        )
        batches.append({
            "batch_id": f"B{i+1:04d}",
            "crop_type": CROP_TYPES[i % len(CROP_TYPES)],
            "farm_origin": FARM_NAMES[i % len(FARM_NAMES)],
            "harvest_datetime": harvest_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "quantity_kg": round(float(np.random.uniform(50, 500)), 1),
            "initial_temp_c": round(float(np.random.uniform(18, 28)), 1),
        })

    for b in batches:
        cur.execute(
            "INSERT INTO batches VALUES (?,?,?,?,?,?)",
            (b["batch_id"], b["crop_type"], b["farm_origin"],
             b["harvest_datetime"], b["quantity_kg"], b["initial_temp_c"]),
        )

    # ── Generate transport legs & temp readings ────────────────────────
    leg_counter = 0
    reading_counter = 0
    all_legs = []
    all_readings = []

    for i, b in enumerate(batches):
        harvest_dt = datetime.strptime(b["harvest_datetime"], "%Y-%m-%d %H:%M:%S")
        vehicle = VEHICLE_IDS[i % len(VEHICLE_IDS)]
        num_legs = 1 if np.random.random() < 0.7 else 2
        current_time = harvest_dt + timedelta(hours=float(np.random.uniform(0.5, 1.5)))

        cause = spoiled_cause.get(i)
        crop_thresh = CROP_THRESHOLDS[b["crop_type"]]

        for leg_num in range(num_legs):
            leg_counter += 1
            leg_id = f"L{leg_counter:04d}"
            dep_time = current_time
            transit_h = float(np.random.uniform(1, 4))
            arr_time = dep_time + timedelta(hours=transit_h)

            origin = (
                b["farm_origin"]
                if leg_num == 0
                else f"Transfer Hub {int(np.random.randint(1, 5))}"
            )
            destination = (
                WAREHOUSE_IDS[i % len(WAREHOUSE_IDS)]
                if leg_num == num_legs - 1
                else f"Transfer Hub {int(np.random.randint(1, 5))}"
            )

            all_legs.append({
                "leg_id": leg_id,
                "batch_id": b["batch_id"],
                "vehicle_id": vehicle,
                "departure_time": dep_time.strftime("%Y-%m-%d %H:%M:%S"),
                "arrival_time": arr_time.strftime("%Y-%m-%d %H:%M:%S"),
                "origin": origin,
                "destination": destination,
            })

            num_rd = int(np.random.randint(3, 7))
            for r in range(num_rd):
                reading_counter += 1
                frac = r / max(num_rd - 1, 1)
                t = dep_time + timedelta(hours=transit_h * frac)
                sensor = ["front", "middle", "rear"][r % 3]

                if cause == "transport_temperature_excursion" and r >= num_rd // 2:
                    temp = round(
                        crop_thresh["max_transport_temp_c"]
                        + float(np.random.uniform(1.0, 5.0)),
                        1,
                    )
                else:
                    temp = round(
                        float(
                            np.random.uniform(
                                0.5,
                                crop_thresh["max_transport_temp_c"] - 0.5,
                            )
                        ),
                        1,
                    )

                all_readings.append({
                    "reading_id": f"R{reading_counter:05d}",
                    "leg_id": leg_id,
                    "timestamp": t.strftime("%Y-%m-%d %H:%M:%S"),
                    "temperature_c": temp,
                    "sensor_position": sensor,
                })

            current_time = arr_time + timedelta(
                minutes=int(np.random.randint(10, 30))
            )

    for tl in all_legs:
        cur.execute(
            "INSERT INTO transport_legs VALUES (?,?,?,?,?,?,?)",
            (
                tl["leg_id"], tl["batch_id"], tl["vehicle_id"],
                tl["departure_time"], tl["arrival_time"],
                tl["origin"], tl["destination"],
            ),
        )
    for tr in all_readings:
        cur.execute(
            "INSERT INTO temp_readings VALUES (?,?,?,?,?)",
            (
                tr["reading_id"], tr["leg_id"], tr["timestamp"],
                tr["temperature_c"], tr["sensor_position"],
            ),
        )

    # ── Generate warehouse records ─────────────────────────────────────
    wh_counter = 0
    all_wh = []

    for i, b in enumerate(batches):
        harvest_dt = datetime.strptime(b["harvest_datetime"], "%Y-%m-%d %H:%M:%S")
        cause = spoiled_cause.get(i)
        crop_thresh = CROP_THRESHOLDS[b["crop_type"]]
        wh_id = WAREHOUSE_IDS[i % len(WAREHOUSE_IDS)]
        zone = ZONES[i % len(ZONES)]

        if cause == "delayed_precooling":
            delay_h = crop_thresh["max_precool_delay_hours"] + float(
                np.random.uniform(1.0, 4.0)
            )
        else:
            delay_h = float(
                np.random.uniform(0.3, crop_thresh["max_precool_delay_hours"] - 0.3)
            )

        first_check = harvest_dt + timedelta(hours=delay_h)
        num_checks = int(np.random.randint(2, 5))

        for c in range(num_checks):
            wh_counter += 1
            check_time = first_check + timedelta(
                hours=c * float(np.random.uniform(2, 6))
            )

            if cause == "warehouse_humidity_violation":
                hum = round(
                    crop_thresh["max_warehouse_humidity_pct"]
                    + float(np.random.uniform(1.0, 5.0)),
                    1,
                )
            else:
                hum = round(
                    float(
                        np.random.uniform(
                            75.0,
                            crop_thresh["max_warehouse_humidity_pct"] - 1.0,
                        )
                    ),
                    1,
                )

            wh_temp = round(float(np.random.uniform(1.0, 4.0)), 1)

            all_wh.append({
                "record_id": f"WR{wh_counter:05d}",
                "batch_id": b["batch_id"],
                "warehouse_id": wh_id,
                "zone": zone,
                "check_datetime": check_time.strftime("%Y-%m-%d %H:%M:%S"),
                "humidity_pct": hum,
                "temperature_c": wh_temp,
            })

    for wr in all_wh:
        cur.execute(
            "INSERT INTO warehouse_records VALUES (?,?,?,?,?,?,?)",
            (
                wr["record_id"], wr["batch_id"], wr["warehouse_id"],
                wr["zone"], wr["check_datetime"],
                wr["humidity_pct"], wr["temperature_c"],
            ),
        )

    # ── Generate inspections ───────────────────────────────────────────
    all_insp = []
    for i, b in enumerate(batches):
        harvest_dt = datetime.strptime(b["harvest_datetime"], "%Y-%m-%d %H:%M:%S")
        insp_date = (
            harvest_dt + timedelta(days=int(np.random.randint(2, 5)))
        ).strftime("%Y-%m-%d")
        inspector = f"INS{int(np.random.randint(1, 8)):02d}"

        if i in spoiled_cause:
            spoilage = round(float(np.random.uniform(8, 60)), 1)
            n_def = int(np.random.randint(2, 5))
            defects = ", ".join(
                np.random.choice(DEFECT_OPTIONS, n_def, replace=False).tolist()
            )
        else:
            spoilage = round(float(np.random.uniform(0, 4.5)), 1)
            n_def = int(np.random.randint(0, 2))
            defects = (
                ", ".join(
                    np.random.choice(DEFECT_OPTIONS, n_def, replace=False).tolist()
                )
                if n_def > 0
                else "none"
            )

        grade = _grade_for_spoilage(spoilage)
        notes = fake.sentence(nb_words=8)

        all_insp.append({
            "inspection_id": f"QI{i+1:04d}",
            "batch_id": b["batch_id"],
            "inspection_date": insp_date,
            "inspector_id": inspector,
            "spoilage_pct": spoilage,
            "defect_types": defects,
            "overall_grade": grade,
            "notes": notes,
        })

    for ins in all_insp:
        cur.execute(
            "INSERT INTO inspections VALUES (?,?,?,?,?,?,?,?)",
            (
                ins["inspection_id"], ins["batch_id"], ins["inspection_date"],
                ins["inspector_id"], ins["spoilage_pct"], ins["defect_types"],
                ins["overall_grade"], ins["notes"],
            ),
        )

    # ── Generate field conditions (DB + workspace CSVs) ────────────────
    all_fc = []
    for i, b in enumerate(batches):
        harvest_dt = datetime.strptime(b["harvest_datetime"], "%Y-%m-%d %H:%M:%S")
        cause = spoiled_cause.get(i)
        crop_thresh = CROP_THRESHOLDS[b["crop_type"]]

        if cause == "adverse_field_conditions":
            if np.random.random() < 0.5:
                field_temp = round(
                    crop_thresh["max_field_temp_c"]
                    + float(np.random.uniform(1.0, 5.0)),
                    1,
                )
                rainfall = round(
                    float(np.random.uniform(0, crop_thresh["max_rainfall_mm"] - 3)),
                    1,
                )
            else:
                field_temp = round(
                    float(np.random.uniform(18, crop_thresh["max_field_temp_c"] - 2)),
                    1,
                )
                rainfall = round(
                    crop_thresh["max_rainfall_mm"]
                    + float(np.random.uniform(2.0, 15.0)),
                    1,
                )
        else:
            field_temp = round(
                float(np.random.uniform(15, crop_thresh["max_field_temp_c"] - 2)),
                1,
            )
            rainfall = round(
                float(np.random.uniform(0, crop_thresh["max_rainfall_mm"] - 3)),
                1,
            )

        soil = round(float(np.random.uniform(20, 60)), 1)
        wind = round(float(np.random.uniform(0, 25)), 1)

        all_fc.append({
            "batch_id": b["batch_id"],
            "harvest_date": harvest_dt.strftime("%Y-%m-%d"),
            "harvest_time": harvest_dt.strftime("%H:%M"),
            "farm": b["farm_origin"],
            "field_temperature_c": field_temp,
            "rainfall_last_24h_mm": rainfall,
            "soil_moisture_pct": soil,
            "wind_speed_kmh": wind,
        })

    for fc in all_fc:
        cur.execute(
            "INSERT INTO field_conditions VALUES (?,?,?,?,?,?,?,?)",
            (
                fc["batch_id"], fc["harvest_date"], fc["harvest_time"],
                fc["farm"], fc["field_temperature_c"],
                fc["rainfall_last_24h_mm"], fc["soil_moisture_pct"],
                fc["wind_speed_kmh"],
            ),
        )

    conn.commit()
    conn.close()

    # ════════════════════════════════════════════════════════════════════
    # WORKSPACE FILES
    # ════════════════════════════════════════════════════════════════════

    # ── Fixed config files (not counted in SCALE) ──────────────────────

    # 1. cold_chain_thresholds.yaml
    with open(os.path.join(workspace, "cold_chain_thresholds.yaml"), "w") as f:
        yaml.dump(
            {"crop_thresholds": CROP_THRESHOLDS}, f, default_flow_style=False
        )

    # 2. spoilage_classification.json
    spoilage_classes = [
        {"min_spoilage_pct": 0, "max_spoilage_pct": 5, "severity": "none"},
        {"min_spoilage_pct": 5, "max_spoilage_pct": 15, "severity": "minor"},
        {"min_spoilage_pct": 15, "max_spoilage_pct": 30, "severity": "moderate"},
        {"min_spoilage_pct": 30, "max_spoilage_pct": 50, "severity": "major"},
        {"min_spoilage_pct": 50, "max_spoilage_pct": 100, "severity": "critical"},
    ]
    with open(os.path.join(workspace, "spoilage_classification.json"), "w") as f:
        json.dump(
            {
                "classifications": spoilage_classes,
                "flagged_threshold_pct": 5.0,
            },
            f,
            indent=2,
        )

    # 3. corrective_action_guidelines.md
    guidelines = (
        "# Corrective Action Guidelines\n\n"
        "## Transport Temperature Excursion\n"
        "When transport temperature exceeds the crop-specific maximum threshold:\n"
        "- Immediately inspect and recalibrate the vehicle refrigeration unit\n"
        "- Review and reduce maximum allowable transit duration for the affected route\n"
        "- Install redundant temperature monitoring sensors\n"
        "- Implement pre-departure cooling verification checklist\n"
        "Priority: HIGH\n\n"
        "## Warehouse Humidity Violation\n"
        "When warehouse humidity exceeds the crop-specific maximum threshold:\n"
        "- Inspect and service HVAC systems in the affected warehouse zone\n"
        "- Increase humidity monitoring frequency to every 30 minutes\n"
        "- Install additional dehumidification units in the affected zone\n"
        "- Review and update zone assignment criteria for moisture-sensitive crops\n"
        "Priority: HIGH\n\n"
        "## Delayed Precooling\n"
        "When the time between harvest and first cold storage check exceeds "
        "the crop-specific maximum delay:\n"
        "- Implement forced-air precooling at the farm gate\n"
        "- Reduce field-to-cooler target time by deploying mobile cooling units\n"
        "- Adjust harvest scheduling to cooler hours of the day\n"
        "- Establish maximum field hold times with automatic alerts\n"
        "Priority: MEDIUM\n\n"
        "## Adverse Field Conditions\n"
        "When field temperature at harvest exceeds the crop-specific maximum "
        "or rainfall exceeds threshold:\n"
        "- Adjust harvest windows based on weather forecasts to avoid peak temperatures\n"
        "- Implement field-level quality gates with immediate rejection criteria\n"
        "- Deploy shade structures for staging areas\n"
        "- Increase post-harvest inspection frequency for weather-affected batches\n"
        "Priority: MEDIUM\n"
    )
    with open(
        os.path.join(workspace, "corrective_action_guidelines.md"), "w"
    ) as f:
        f.write(guidelines)

    # 4. analysis_protocol.txt
    protocol = (
        "Post-Harvest Spoilage Analysis Protocol\n"
        "========================================\n\n"
        "A batch is considered flagged for spoilage investigation when its\n"
        "inspection spoilage percentage meets or exceeds the threshold defined\n"
        "in spoilage_classification.json (the flagged_threshold_pct value).\n\n"
        "Root Cause Classification Rules (apply in order, assign first match):\n\n"
        "1. TRANSPORT TEMPERATURE EXCURSION: The maximum temperature recorded\n"
        "   across all transport legs for the batch exceeds the crop-specific\n"
        "   max_transport_temp_c from cold_chain_thresholds.yaml.\n\n"
        "2. WAREHOUSE HUMIDITY VIOLATION: The maximum humidity recorded across\n"
        "   all warehouse checks for the batch exceeds the crop-specific\n"
        "   max_warehouse_humidity_pct from cold_chain_thresholds.yaml.\n\n"
        "3. DELAYED PRECOOLING: The time elapsed between the batch harvest\n"
        "   datetime and the earliest warehouse check datetime exceeds the\n"
        "   crop-specific max_precool_delay_hours from cold_chain_thresholds.yaml.\n\n"
        "4. ADVERSE FIELD CONDITIONS: The field temperature at harvest (from\n"
        "   field condition reports) exceeds the crop-specific max_field_temp_c,\n"
        "   OR the rainfall at harvest exceeds the crop-specific max_rainfall_mm,\n"
        "   as defined in cold_chain_thresholds.yaml.\n\n"
        "5. UNKNOWN: If none of the above conditions are met.\n\n"
        "Severity is determined by the spoilage percentage using the ranges\n"
        "defined in spoilage_classification.json.\n"
    )
    with open(os.path.join(workspace, "analysis_protocol.txt"), "w") as f:
        f.write(protocol)

    # ── Scalable data files ────────────────────────────────────────────
    n_field_files = num_files // 2
    n_vehicle_files = num_files - n_field_files

    # Field-condition CSVs
    batches_per_file = max(1, num_batches // n_field_files)
    for f_idx in range(n_field_files):
        start = f_idx * batches_per_file
        end = (
            start + batches_per_file if f_idx < n_field_files - 1 else num_batches
        )
        chunk = all_fc[start:end]
        fp = os.path.join(
            workspace, f"field_conditions_report_{f_idx + 1:03d}.csv"
        )
        with open(fp, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(chunk[0].keys()))
            writer.writeheader()
            writer.writerows(chunk)

    # Vehicle-status JSONs
    vehicles_used = sorted(set(tl["vehicle_id"] for tl in all_legs))
    veh_per_file = max(1, len(vehicles_used) // n_vehicle_files)
    for v_idx in range(n_vehicle_files):
        start = v_idx * veh_per_file
        end = (
            start + veh_per_file
            if v_idx < n_vehicle_files - 1
            else len(vehicles_used)
        )
        veh_chunk = vehicles_used[start:end]
        records = []
        for vid in veh_chunk:
            last_maint = (
                base_date - timedelta(days=int(np.random.randint(10, 90)))
            ).strftime("%Y-%m-%d")
            last_cal = (
                base_date - timedelta(days=int(np.random.randint(5, 60)))
            ).strftime("%Y-%m-%d")
            model = str(
                np.random.choice(
                    [
                        "ThermoKing T-800R",
                        "Carrier Transicold X4",
                        "Daikin ZR-500",
                        "Mitsubishi TFV",
                    ]
                )
            )
            age = int(np.random.randint(1, 8))
            issue = str(
                np.random.choice(
                    [
                        "none",
                        "intermittent sensor fault",
                        "door seal wear",
                        "compressor cycling delay",
                        "none",
                        "none",
                    ]
                )
            )
            records.append({
                "vehicle_id": vid,
                "refrigeration_model": model,
                "unit_age_years": age,
                "last_maintenance_date": last_maint,
                "last_calibration_date": last_cal,
                "known_issues": issue,
                "max_load_capacity_kg": int(np.random.choice([2000, 3000, 5000])),
            })
        fp = os.path.join(workspace, f"vehicle_status_{v_idx + 1:03d}.json")
        with open(fp, "w") as fh:
            json.dump(
                {
                    "vehicles": records,
                    "report_date": base_date.strftime("%Y-%m-%d"),
                },
                fh,
                indent=2,
            )

    print(f"Database written to {db_path}")
    print(
        f"Workspace populated in {workspace}/ "
        f"({4} config + {num_files} scalable files)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
