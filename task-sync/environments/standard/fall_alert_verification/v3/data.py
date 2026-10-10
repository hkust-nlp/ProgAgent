import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
from datetime import datetime, timedelta
from faker import Faker

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 32,
}


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = SCALE["rows_per_table"]
    num_zones = SCALE["num_workspace_files"]
    rooms_per_zone = 4
    total_rooms = num_zones * rooms_per_zone

    # ------------------------------------------------------------------ #
    #  Zones, Rooms, Devices                                              #
    # ------------------------------------------------------------------ #
    zones = [f"Floor_{i + 1}" for i in range(num_zones)]
    rooms = []
    devices = []
    for z_idx, zone in enumerate(zones):
        for r in range(rooms_per_zone):
            room_num = f"{(z_idx + 1) * 100 + r + 1}"
            rooms.append({"room_number": room_num, "zone": zone})
            devices.append(
                {
                    "device_id": f"DEV_{room_num}_01",
                    "room_number": room_num,
                    "zone": zone,
                }
            )
            if np.random.random() < 0.3:
                devices.append(
                    {
                        "device_id": f"DEV_{room_num}_02",
                        "room_number": room_num,
                        "zone": zone,
                    }
                )

    # ------------------------------------------------------------------ #
    #  Room Baselines (kept in memory, written to workspace later)        #
    # ------------------------------------------------------------------ #
    room_baselines = {}
    for room_info in rooms:
        rn = room_info["room_number"]
        room_baselines[rn] = {
            "typical_accel_max": round(float(np.random.uniform(0.8, 1.8)), 2),
            "typical_accel_mean": round(float(np.random.uniform(0.2, 0.6)), 2),
            "typical_gyro_max": round(float(np.random.uniform(0.3, 1.0)), 2),
            "active_hours_start": int(np.random.choice([6, 7, 8])),
            "active_hours_end": int(np.random.choice([20, 21, 22])),
        }

    # ------------------------------------------------------------------ #
    #  Validation rule constants (used during generation)                 #
    # ------------------------------------------------------------------ #
    DEVIATION_FACTOR = 1.8
    MIN_MAGNITUDE = 2.0
    CAREGIVER_WINDOW = 300
    EXEMPT_TYPES = ["mobility_assist", "physical_therapy", "transfer"]
    AUDIO_WINDOW = 120
    AUDIO_MIN_CONF = 0.65
    AUDIO_CONFIRM_TYPES = ["impact", "crash", "thud", "cry_for_help"]

    # ------------------------------------------------------------------ #
    #  Residents table                                                    #
    # ------------------------------------------------------------------ #
    cursor.execute(
        """
        CREATE TABLE residents (
            resident_id   INTEGER PRIMARY KEY,
            name          TEXT    NOT NULL,
            age           INTEGER NOT NULL,
            room_number   TEXT    NOT NULL,
            mobility_level TEXT   NOT NULL,
            admission_date TEXT   NOT NULL
        )
    """
    )

    mobility_levels = ["independent", "assisted", "wheelchair", "bedridden"]
    residents = []
    for i in range(rows):
        room = rooms[i % len(rooms)]
        r = {
            "resident_id": i + 1,
            "name": fake.name(),
            "age": int(np.random.randint(65, 96)),
            "room_number": room["room_number"],
            "mobility_level": str(
                np.random.choice(mobility_levels, p=[0.30, 0.35, 0.25, 0.10])
            ),
            "admission_date": fake.date_between(
                start_date="-3y", end_date="-1m"
            ).isoformat(),
        }
        residents.append(r)
        cursor.execute(
            "INSERT INTO residents VALUES (?,?,?,?,?,?)",
            (
                r["resident_id"],
                r["name"],
                r["age"],
                r["room_number"],
                r["mobility_level"],
                r["admission_date"],
            ),
        )

    # ------------------------------------------------------------------ #
    #  Pre-classify alerts & assign statuses                              #
    # ------------------------------------------------------------------ #
    base_date = datetime(2025, 3, 15, 8, 0, 0)

    classifications = []
    for _ in range(rows):
        roll = float(np.random.random())
        if roll < 0.45:
            classifications.append("true_fall")
        elif roll < 0.70:
            classifications.append("false_caregiver")
        elif roll < 0.90:
            classifications.append("false_baseline")
        else:
            classifications.append("false_low_accel")

    statuses = []
    for _ in range(rows):
        roll = float(np.random.random())
        if roll < 0.60:
            statuses.append("pending")
        elif roll < 0.80:
            statuses.append("resolved")
        else:
            statuses.append("dismissed")

    # ------------------------------------------------------------------ #
    #  Fall alerts table                                                  #
    # ------------------------------------------------------------------ #
    cursor.execute(
        """
        CREATE TABLE fall_alerts (
            alert_id          INTEGER PRIMARY KEY,
            resident_id       INTEGER NOT NULL,
            device_id         TEXT    NOT NULL,
            timestamp         TEXT    NOT NULL,
            raw_severity_score REAL   NOT NULL,
            status            TEXT    NOT NULL,
            FOREIGN KEY (resident_id) REFERENCES residents(resident_id)
        )
    """
    )

    alerts = []
    for i in range(rows):
        resident = residents[int(np.random.randint(0, len(residents)))]
        room_devs = [d for d in devices if d["room_number"] == resident["room_number"]]
        device = room_devs[int(np.random.randint(0, len(room_devs)))]
        # timestamps between 7:00 and 22:00 across 7 days
        day_off = int(np.random.randint(0, 7))
        hour_off = float(np.random.uniform(7, 22))
        ts = base_date + timedelta(days=day_off, hours=hour_off - 8)

        cls = classifications[i]
        if cls == "true_fall":
            raw_sev = float(np.random.uniform(0.60, 0.95))
        elif cls == "false_caregiver":
            raw_sev = float(np.random.uniform(0.40, 0.80))
        elif cls == "false_baseline":
            raw_sev = float(np.random.uniform(0.30, 0.60))
        else:
            raw_sev = float(np.random.uniform(0.10, 0.40))

        alert = {
            "alert_id": i + 1,
            "resident_id": resident["resident_id"],
            "device_id": device["device_id"],
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "raw_severity_score": round(raw_sev, 3),
            "status": statuses[i],
            "classification": cls,
            "room_number": resident["room_number"],
        }
        alerts.append(alert)
        cursor.execute(
            "INSERT INTO fall_alerts VALUES (?,?,?,?,?,?)",
            (
                alert["alert_id"],
                alert["resident_id"],
                alert["device_id"],
                alert["timestamp"],
                alert["raw_severity_score"],
                alert["status"],
            ),
        )

    # ------------------------------------------------------------------ #
    #  Motion readings table                                              #
    # ------------------------------------------------------------------ #
    cursor.execute(
        """
        CREATE TABLE motion_readings (
            reading_id     INTEGER PRIMARY KEY,
            alert_id       INTEGER NOT NULL,
            timestamp      TEXT    NOT NULL,
            accel_x        REAL    NOT NULL,
            accel_y        REAL    NOT NULL,
            accel_z        REAL    NOT NULL,
            gyro_magnitude REAL    NOT NULL,
            FOREIGN KEY (alert_id) REFERENCES fall_alerts(alert_id)
        )
    """
    )

    reading_id = 1
    for alert in alerts:
        room_num = alert["room_number"]
        baseline_max = room_baselines[room_num]["typical_accel_max"]
        threshold = max(baseline_max * DEVIATION_FACTOR, MIN_MAGNITUDE)
        alert_time = datetime.strptime(alert["timestamp"], "%Y-%m-%d %H:%M:%S")
        cls = alert["classification"]
        num_readings = int(np.random.randint(5, 10))

        for j in range(num_readings):
            t_off = float(np.random.uniform(-30, 30))
            read_time = alert_time + timedelta(seconds=t_off)

            if cls in ("true_fall", "false_caregiver"):
                if j == 0:
                    peak = float(np.random.uniform(threshold + 0.5, threshold + 4.0))
                else:
                    peak = float(np.random.uniform(0.3, baseline_max * 1.1))
            elif cls == "false_baseline":
                peak = float(np.random.uniform(0.3, baseline_max * 0.85))
            else:
                peak = float(np.random.uniform(0.1, MIN_MAGNITUDE * 0.6))

            rx = float(np.random.uniform(0.2, 0.6))
            ry = float(np.random.uniform(0.15, 0.45))
            ax = peak * rx
            ay = peak * ry
            remaining = peak ** 2 - ax ** 2 - ay ** 2
            az = math.sqrt(max(0, remaining))
            gyro = float(np.random.uniform(0.1, 2.5))

            cursor.execute(
                "INSERT INTO motion_readings VALUES (?,?,?,?,?,?,?)",
                (
                    reading_id,
                    alert["alert_id"],
                    read_time.strftime("%Y-%m-%d %H:%M:%S"),
                    round(ax, 4),
                    round(ay, 4),
                    round(az, 4),
                    round(gyro, 4),
                ),
            )
            reading_id += 1

    # ------------------------------------------------------------------ #
    #  Caregiver visits table                                             #
    # ------------------------------------------------------------------ #
    cursor.execute(
        """
        CREATE TABLE caregiver_visits (
            visit_id         INTEGER PRIMARY KEY,
            resident_id      INTEGER NOT NULL,
            caregiver_name   TEXT    NOT NULL,
            visit_type       TEXT    NOT NULL,
            scheduled_start  TEXT    NOT NULL,
            scheduled_end    TEXT    NOT NULL,
            actual_arrival   TEXT    NOT NULL,
            actual_departure TEXT    NOT NULL,
            FOREIGN KEY (resident_id) REFERENCES residents(resident_id)
        )
    """
    )

    non_exempt_types = ["medication", "checkup", "meal_assist", "social", "hygiene"]
    visit_id = 1

    # Exempt caregiver visits for false_caregiver alerts
    for alert in alerts:
        if alert["classification"] == "false_caregiver":
            alert_time = datetime.strptime(alert["timestamp"], "%Y-%m-%d %H:%M:%S")
            vs = alert_time - timedelta(minutes=float(np.random.uniform(10, 30)))
            ve = alert_time + timedelta(minutes=float(np.random.uniform(10, 30)))
            vtype = str(np.random.choice(EXEMPT_TYPES))
            aa = vs + timedelta(minutes=float(np.random.uniform(-2, 3)))
            ad = ve + timedelta(minutes=float(np.random.uniform(-2, 3)))
            cursor.execute(
                "INSERT INTO caregiver_visits VALUES (?,?,?,?,?,?,?,?)",
                (
                    visit_id,
                    alert["resident_id"],
                    fake.name(),
                    vtype,
                    vs.strftime("%Y-%m-%d %H:%M:%S"),
                    ve.strftime("%Y-%m-%d %H:%M:%S"),
                    aa.strftime("%Y-%m-%d %H:%M:%S"),
                    ad.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            visit_id += 1

    # Pad with non-exempt visits to reach rows_per_table
    while visit_id <= rows:
        resident = residents[int(np.random.randint(0, len(residents)))]
        day_off = int(np.random.randint(0, 7))
        hour = int(np.random.randint(6, 22))
        vs = base_date + timedelta(days=day_off, hours=hour - 8)
        dur = timedelta(minutes=float(np.random.uniform(15, 60)))
        ve = vs + dur
        vtype = str(np.random.choice(non_exempt_types))
        aa = vs + timedelta(minutes=float(np.random.uniform(-3, 8)))
        ad = ve + timedelta(minutes=float(np.random.uniform(-3, 8)))
        cursor.execute(
            "INSERT INTO caregiver_visits VALUES (?,?,?,?,?,?,?,?)",
            (
                visit_id,
                resident["resident_id"],
                fake.name(),
                vtype,
                vs.strftime("%Y-%m-%d %H:%M:%S"),
                ve.strftime("%Y-%m-%d %H:%M:%S"),
                aa.strftime("%Y-%m-%d %H:%M:%S"),
                ad.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        visit_id += 1

    # ------------------------------------------------------------------ #
    #  Audio events table                                                 #
    # ------------------------------------------------------------------ #
    cursor.execute(
        """
        CREATE TABLE audio_events (
            event_id         INTEGER PRIMARY KEY,
            room_number      TEXT    NOT NULL,
            timestamp        TEXT    NOT NULL,
            event_type       TEXT    NOT NULL,
            confidence_score REAL    NOT NULL,
            duration_ms      INTEGER NOT NULL
        )
    """
    )

    non_confirm_audio = [
        "speech",
        "television",
        "music",
        "door_close",
        "footsteps",
        "cough",
        "snoring",
    ]
    event_id = 1

    # Confirming audio for true_fall alerts (~70 %)
    for alert in alerts:
        if alert["classification"] == "true_fall":
            if float(np.random.random()) < 0.70:
                alert_time = datetime.strptime(
                    alert["timestamp"], "%Y-%m-%d %H:%M:%S"
                )
                audio_t = alert_time + timedelta(
                    seconds=float(np.random.uniform(-AUDIO_WINDOW / 2, AUDIO_WINDOW / 2))
                )
                atype = str(np.random.choice(AUDIO_CONFIRM_TYPES))
                conf = float(np.random.uniform(AUDIO_MIN_CONF + 0.05, 0.98))
                cursor.execute(
                    "INSERT INTO audio_events VALUES (?,?,?,?,?,?)",
                    (
                        event_id,
                        alert["room_number"],
                        audio_t.strftime("%Y-%m-%d %H:%M:%S"),
                        atype,
                        round(conf, 3),
                        int(np.random.randint(100, 5000)),
                    ),
                )
                event_id += 1

    # Pad with non-confirming audio noise
    while event_id <= rows:
        room = rooms[int(np.random.randint(0, len(rooms)))]
        day_off = int(np.random.randint(0, 7))
        hour = int(np.random.randint(0, 24))
        minute = int(np.random.randint(0, 60))
        ts = base_date + timedelta(days=day_off, hours=hour, minutes=minute)
        atype = str(np.random.choice(non_confirm_audio))
        conf = float(np.random.uniform(0.30, 0.95))
        cursor.execute(
            "INSERT INTO audio_events VALUES (?,?,?,?,?,?)",
            (
                event_id,
                room["room_number"],
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                atype,
                round(conf, 3),
                int(np.random.randint(50, 10000)),
            ),
        )
        event_id += 1

    conn.commit()

    # ================================================================== #
    #  WORKSPACE FILES                                                    #
    # ================================================================== #

    # 1. Zone baseline files  (scalable — one per zone)
    for z_idx, zone in enumerate(zones):
        zone_rooms = [r for r in rooms if r["zone"] == zone]
        baseline_data = {
            "zone": zone,
            "measurement_period": "2025-02-01 to 2025-03-14",
            "rooms": {},
        }
        for ri in zone_rooms:
            rn = ri["room_number"]
            baseline_data["rooms"][rn] = room_baselines[rn]
        fname = f"baseline_{zone.lower().replace(' ', '_')}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(baseline_data, f, indent=2)

    # 2. validation_rules.json  (fixed)
    rules_payload = {
        "acceleration": {
            "deviation_factor": DEVIATION_FACTOR,
            "minimum_magnitude": MIN_MAGNITUDE,
        },
        "caregiver": {
            "presence_window_seconds": CAREGIVER_WINDOW,
        },
        "audio": {
            "confirmation_window_seconds": AUDIO_WINDOW,
            "minimum_confidence": AUDIO_MIN_CONF,
            "confirming_types": list(AUDIO_CONFIRM_TYPES),
        },
    }
    with open(os.path.join(workspace, "validation_rules.json"), "w") as f:
        json.dump(rules_payload, f, indent=2)

    # 3. caregiver_exemptions.txt  (fixed)
    with open(os.path.join(workspace, "caregiver_exemptions.txt"), "w") as f:
        f.write(
            "# Caregiver visit types whose physical assistance may trigger motion sensors.\n"
            "# If a caregiver with one of these visit types was actually present\n"
            "# (arrival <= alert_time + window, departure >= alert_time - window),\n"
            "# the alert may be a false positive unless audio evidence overrides.\n"
            "#\n"
        )
        for et in EXEMPT_TYPES:
            f.write(et + "\n")

    # 4. severity_thresholds.csv  (fixed)
    with open(
        os.path.join(workspace, "severity_thresholds.csv"), "w", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "severity_level",
                "min_acceleration",
                "requires_audio_confirmation",
                "severity_rank",
            ]
        )
        writer.writerow(["critical", "5.0", "yes", "1"])
        writer.writerow(["high", "3.5", "no", "2"])
        writer.writerow(["medium", "2.5", "no", "3"])
        writer.writerow(["low", "0.0", "no", "4"])

    # 5. device_registry.csv  (fixed — content scales with rooms)
    with open(
        os.path.join(workspace, "device_registry.csv"), "w", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            ["device_id", "room_number", "zone", "device_type", "install_date"]
        )
        for d in devices:
            writer.writerow(
                [d["device_id"], d["room_number"], d["zone"], "motion_sensor", "2024-01-15"]
            )

    # 6. emergency_contacts.json  (fixed — content scales with residents)
    contacts = {}
    for r in residents:
        contacts[str(r["resident_id"])] = {
            "resident_name": r["name"],
            "primary_contact_name": fake.name(),
            "primary_contact_phone": fake.phone_number(),
            "relationship": str(
                np.random.choice(["spouse", "child", "sibling", "friend", "guardian"])
            ),
            "secondary_contact_name": fake.name(),
            "secondary_contact_phone": fake.phone_number(),
        }
    with open(os.path.join(workspace, "emergency_contacts.json"), "w") as f:
        json.dump(contacts, f, indent=2)

    # 7. output_specification.md  (fixed)
    with open(os.path.join(workspace, "output_specification.md"), "w") as f:
        f.write(
            """\
## Incident Report Specification

The deliverable file must be named `incident_report.csv` and placed in the working directory.

### Columns (in this exact order)

alert_id, resident_name, room_number, alert_timestamp, peak_acceleration, baseline_max, severity_level, verification_status, contributing_factors, emergency_contact_name, emergency_contact_phone

### Column Formatting

- `alert_id`: integer
- `resident_name`: full name string
- `room_number`: string matching the device registry
- `alert_timestamp`: YYYY-MM-DD HH:MM:SS
- `peak_acceleration`: float rounded to exactly 4 decimal places
- `baseline_max`: float as recorded in the baseline profile
- `severity_level`: one of `critical`, `high`, `medium`, `low` for verified incidents; `n/a` for false positives
- `verification_status`: exactly `verified` or `false_positive`
- `contributing_factors`: three assessments joined by `; ` (semicolon-space), always in the order: motion assessment, caregiver assessment, audio assessment. Use these exact tokens:
    - Motion: `motion_exceeded` or `motion_within_baseline`
    - Caregiver: `caregiver_exempt_present` or `no_caregiver_overlap`
    - Audio: `audio_confirmed` or `no_audio_confirmation`
- `emergency_contact_name`: primary contact name from the contacts file
- `emergency_contact_phone`: primary contact phone from the contacts file

### Sort Order

Primary sort by `severity_rank` ascending (critical=1, high=2, medium=3, low=4, n/a=5).
Secondary sort by `alert_timestamp` ascending.

### Scope

Every alert with status `pending` must appear in the report.
"""
        )

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace populated at {workspace}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
