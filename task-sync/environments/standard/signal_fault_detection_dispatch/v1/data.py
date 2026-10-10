"""
Traffic Signal Maintenance Task - Data Generator
Generates database and workspace files for identifying malfunctioning traffic signals.
"""

import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 20,
}

DISTRICTS = ["Central", "North", "South", "East", "West"]
SIGNAL_TYPES = ["fixed_time", "actuated", "adaptive", "pedestrian_only"]
BUTTON_POSITIONS = ["north", "south", "east", "west"]
PHASE_NAMES = ["green", "yellow", "red", "left_turn", "pedestrian_walk"]
SEVERITY_LEVELS = ["low", "medium", "high", "critical"]
NAV_APPS = ["GoogleMaps", "Waze", "AppleMaps", "CityNav"]
COMPLAINT_CATEGORIES = [
    "signal_not_responding", "long_wait_time", "button_not_working",
    "dangerous_intersection", "timing_issue",
]
FAULT_CODES = [
    "F001_STUCK_RELAY", "F002_TIMING_DRIFT", "F003_SENSOR_FAIL",
    "F004_LAMP_OUT", "F005_CONTROLLER_ERR",
]


def generate_signals(n_signals, fake):
    signals = []
    for i in range(n_signals):
        sig_id = f"SIG-{i+1:04d}"
        intersection = f"{fake.street_name()} & {fake.street_name()}"
        district = DISTRICTS[i % len(DISTRICTS)]
        sig_type = str(np.random.choice(SIGNAL_TYPES, p=[0.3, 0.35, 0.25, 0.1]))
        install_date = fake.date_between(start_date="-15y", end_date="-1y").isoformat()
        lat = round(40.0 + float(np.random.uniform(-0.1, 0.1)), 6)
        lon = round(-74.0 + float(np.random.uniform(-0.1, 0.1)), 6)
        status = str(np.random.choice(["active", "inactive"], p=[0.92, 0.08]))
        signals.append({
            "signal_id": sig_id,
            "intersection_name": intersection,
            "district": district,
            "signal_type": sig_type,
            "install_date": install_date,
            "latitude": lat,
            "longitude": lon,
            "status": status,
        })
    return signals


def generate_button_logs(signals, n_logs, fake):
    n_signals = len(signals)
    problem_indices = set(
        np.random.choice(n_signals, size=max(3, n_signals // 5), replace=False).tolist()
    )
    logs = []
    for i in range(n_logs):
        sig_idx = int(np.random.randint(0, n_signals))
        sig_id = signals[sig_idx]["signal_id"]
        timestamp = fake.date_time_between(start_date="-30d", end_date="now").isoformat()
        if sig_idx in problem_indices:
            rt = int(np.random.normal(7000, 2000))
            rt = max(1000, rt)
        else:
            rt = int(np.random.normal(2000, 500))
            rt = max(200, rt)
        pos = str(np.random.choice(BUTTON_POSITIONS))
        logs.append({
            "signal_id": sig_id,
            "timestamp": timestamp,
            "response_time_ms": rt,
            "button_position": pos,
        })
    return logs


def generate_phase_telemetry(signals, n_records, fake):
    n_signals = len(signals)
    problem_indices = set(
        np.random.choice(n_signals, size=max(3, n_signals // 5), replace=False).tolist()
    )
    records = []
    for i in range(n_records):
        sig_idx = int(np.random.randint(0, n_signals))
        sig_id = signals[sig_idx]["signal_id"]
        timestamp = fake.date_time_between(start_date="-30d", end_date="now").isoformat()
        phase = str(np.random.choice(PHASE_NAMES))
        planned = round(float(np.random.uniform(15, 90)), 1)
        if sig_idx in problem_indices:
            actual = round(planned + float(np.random.normal(10, 5)), 1)
        else:
            actual = round(planned + float(np.random.normal(0, 1.5)), 1)
        actual = max(1.0, actual)
        anomaly = 1 if abs(actual - planned) > 5 else 0
        records.append({
            "signal_id": sig_id,
            "timestamp": timestamp,
            "phase_name": phase,
            "planned_duration_s": planned,
            "actual_duration_s": actual,
            "anomaly_flag": anomaly,
        })
    return records


def generate_congestion_alerts(signals, n_alerts, fake):
    n_signals = len(signals)
    problem_indices = set(
        np.random.choice(n_signals, size=max(3, n_signals // 4), replace=False).tolist()
    )
    weights = np.ones(n_signals)
    for idx in problem_indices:
        weights[idx] = 5.0
    weights /= weights.sum()
    alerts = []
    for i in range(n_alerts):
        sig_idx = int(np.random.choice(n_signals, p=weights))
        sig_id = signals[sig_idx]["signal_id"]
        timestamp = fake.date_time_between(start_date="-30d", end_date="now").isoformat()
        if sig_idx in problem_indices:
            severity = str(np.random.choice(SEVERITY_LEVELS, p=[0.1, 0.2, 0.4, 0.3]))
        else:
            severity = str(np.random.choice(SEVERITY_LEVELS, p=[0.5, 0.3, 0.15, 0.05]))
        delay = round(float(np.random.uniform(10, 300)), 1)
        source = str(np.random.choice(NAV_APPS))
        alerts.append({
            "signal_id": sig_id,
            "timestamp": timestamp,
            "severity": severity,
            "avg_delay_s": delay,
            "source_app": source,
        })
    return alerts


def generate_maintenance_history(signals, n_records, fake):
    n_signals = len(signals)
    actions = [
        "bulb_replacement", "controller_reset", "timing_adjustment",
        "sensor_calibration", "full_inspection", "cable_repair",
    ]
    records = []
    for i in range(n_records):
        sig_idx = int(np.random.randint(0, n_signals))
        sig_id = signals[sig_idx]["signal_id"]
        date = fake.date_between(start_date="-2y", end_date="-1d").isoformat()
        action = str(np.random.choice(actions))
        tech = fake.name()
        records.append({
            "signal_id": sig_id,
            "date": date,
            "action_taken": action,
            "technician": tech,
        })
    return records


def create_database(db_path, signals, button_logs, phase_telemetry,
                    congestion_alerts, maintenance_history):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS signals (
        signal_id TEXT PRIMARY KEY,
        intersection_name TEXT NOT NULL,
        district TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        install_date TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        status TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS button_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        response_time_ms INTEGER NOT NULL,
        button_position TEXT NOT NULL,
        FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS phase_telemetry (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        phase_name TEXT NOT NULL,
        planned_duration_s REAL NOT NULL,
        actual_duration_s REAL NOT NULL,
        anomaly_flag INTEGER NOT NULL,
        FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS congestion_alerts (
        alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        severity TEXT NOT NULL,
        avg_delay_s REAL NOT NULL,
        source_app TEXT NOT NULL,
        FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS maintenance_history (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT NOT NULL,
        date TEXT NOT NULL,
        action_taken TEXT NOT NULL,
        technician TEXT NOT NULL,
        FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
    )""")

    for s in signals:
        c.execute(
            "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?)",
            (s["signal_id"], s["intersection_name"], s["district"],
             s["signal_type"], s["install_date"], s["latitude"],
             s["longitude"], s["status"]),
        )

    for l in button_logs:
        c.execute(
            "INSERT INTO button_logs (signal_id,timestamp,response_time_ms,button_position) VALUES (?,?,?,?)",
            (l["signal_id"], l["timestamp"], l["response_time_ms"], l["button_position"]),
        )

    for r in phase_telemetry:
        c.execute(
            "INSERT INTO phase_telemetry (signal_id,timestamp,phase_name,"
            "planned_duration_s,actual_duration_s,anomaly_flag) VALUES (?,?,?,?,?,?)",
            (r["signal_id"], r["timestamp"], r["phase_name"],
             r["planned_duration_s"], r["actual_duration_s"], r["anomaly_flag"]),
        )

    for a in congestion_alerts:
        c.execute(
            "INSERT INTO congestion_alerts (signal_id,timestamp,severity,"
            "avg_delay_s,source_app) VALUES (?,?,?,?,?)",
            (a["signal_id"], a["timestamp"], a["severity"],
             a["avg_delay_s"], a["source_app"]),
        )

    for m in maintenance_history:
        c.execute(
            "INSERT INTO maintenance_history (signal_id,date,action_taken,technician) VALUES (?,?,?,?)",
            (m["signal_id"], m["date"], m["action_taken"], m["technician"]),
        )

    conn.commit()
    conn.close()


def generate_workspace(workspace, signals, fake):
    n_signals = len(signals)
    n_files = SCALE["num_workspace_files"]

    # ── Fixed config files (not counted toward scalable quota) ──────────
    scoring_config = {
        "scoring_weights": {
            "button_malfunction": 25,
            "phase_anomaly": 25,
            "congestion_impact": 20,
            "complaint_severity": 20,
            "inspection_findings": 10,
        },
        "thresholds": {
            "button_avg_response_ms": 5000,
            "phase_anomaly_rate": 0.15,
            "congestion_alert_count": 3,
            "unresolved_complaint_count": 2,
        },
        "urgency_tiers": {
            "critical": {"min_score": 80, "action": "Immediate on-site repair"},
            "high": {"min_score": 60, "action": "Schedule repair within 48 hours"},
            "medium": {"min_score": 40, "action": "Schedule inspection within 1 week"},
        },
        "dispatch_threshold": 40,
    }
    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(scoring_config, f, default_flow_style=False, sort_keys=False)

    district_priorities = {
        "Central": 1.3,
        "North": 1.1,
        "South": 1.0,
        "East": 0.9,
        "West": 1.0,
    }
    with open(os.path.join(workspace, "district_priorities.json"), "w") as f:
        json.dump(district_priorities, f, indent=2)

    # ── Scalable data files ─────────────────────────────────────────────
    n_complaint_files = max(2, n_files // 2)
    n_inspection_files = max(1, (n_files - n_complaint_files + 1) // 2)
    n_outage_files = max(1, n_files - n_complaint_files - n_inspection_files)
    # Ensure total matches
    while n_complaint_files + n_inspection_files + n_outage_files < n_files:
        n_complaint_files += 1
    while n_complaint_files + n_inspection_files + n_outage_files > n_files:
        if n_complaint_files > 2:
            n_complaint_files -= 1
        else:
            n_inspection_files -= 1

    # --- Citizen complaint CSVs ---
    n_total_complaints = SCALE["rows_per_table"] * 2
    complaint_records = []
    for i in range(n_total_complaints):
        sig_idx = int(np.random.randint(0, n_signals))
        sig_id = signals[sig_idx]["signal_id"]
        date = fake.date_between(start_date="-30d", end_date="today").isoformat()
        cat = str(np.random.choice(COMPLAINT_CATEGORIES))
        desc = fake.sentence(nb_words=10)
        resolved = str(np.random.choice(["yes", "no"], p=[0.4, 0.6]))
        complaint_records.append({
            "complaint_id": f"CMP-{i+1:05d}",
            "signal_id": sig_id,
            "date": date,
            "category": cat,
            "description": desc,
            "resolved": resolved,
        })

    per = max(1, len(complaint_records) // n_complaint_files)
    for fi in range(n_complaint_files):
        start = fi * per
        end = start + per if fi < n_complaint_files - 1 else len(complaint_records)
        batch = complaint_records[start:end]
        fpath = os.path.join(workspace, f"complaint_report_week_{fi+1}.csv")
        with open(fpath, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["complaint_id", "signal_id", "date",
                            "category", "description", "resolved"],
            )
            w.writeheader()
            w.writerows(batch)

    # --- Field inspection TXTs ---
    n_inspected = max(5, n_signals * 2 // 5)
    inspected_indices = np.random.choice(
        n_signals, size=min(n_inspected, n_signals), replace=False
    ).tolist()
    inspection_entries = []
    for idx in inspected_indices:
        sig = signals[idx]
        has_fault = bool(np.random.random() < 0.5)
        if has_fault:
            fc = str(np.random.choice(FAULT_CODES))
            sev = str(np.random.choice(["high", "medium", "low"]))
            finding = f"Fault detected: {fc}. {fake.sentence(nb_words=8)}"
        else:
            fc = None
            sev = None
            finding = "No issues found during inspection. Signal operating normally."
        inspection_entries.append({
            "signal_id": sig["signal_id"],
            "intersection": sig["intersection_name"],
            "has_fault": has_fault,
            "fault_code": fc,
            "severity": sev,
            "finding": finding,
        })

    per = max(1, len(inspection_entries) // n_inspection_files)
    for fi in range(n_inspection_files):
        start = fi * per
        end = start + per if fi < n_inspection_files - 1 else len(inspection_entries)
        batch = inspection_entries[start:end]
        fpath = os.path.join(workspace, f"inspection_notes_batch_{fi+1}.txt")
        inspector_name = fake.name()
        report_date = fake.date_between(start_date="-14d", end_date="today").isoformat()
        with open(fpath, "w") as f:
            f.write(f"FIELD INSPECTION REPORT - Batch {fi+1}\n")
            f.write(f"Date: {report_date}\n")
            f.write(f"Inspector: {inspector_name}\n")
            f.write("=" * 60 + "\n\n")
            for entry in batch:
                f.write(f"Signal {entry['signal_id']} at {entry['intersection']}:\n")
                f.write(f"  Finding: {entry['finding']}\n")
                if entry["has_fault"]:
                    f.write(f"  Fault Code: {entry['fault_code']}\n")
                    f.write(f"  Severity: {entry['severity']}\n")
                else:
                    f.write(f"  Status: PASS\n")
                f.write("\n")

    # --- Planned outage YAMLs ---
    n_outages = max(2, SCALE["rows_per_table"] // 10)
    outage_indices = np.random.choice(
        n_signals, size=min(n_outages, n_signals), replace=False
    ).tolist()
    outage_entries = []
    for idx in outage_indices:
        sig_id = signals[idx]["signal_id"]
        sd = fake.date_between(start_date="-7d", end_date="+7d").isoformat()
        ed = fake.date_between(start_date="+8d", end_date="+30d").isoformat()
        reason = str(np.random.choice([
            "Scheduled upgrade", "Controller replacement",
            "Cable re-routing", "Intersection redesign",
        ]))
        outage_entries.append({
            "signal_id": sig_id,
            "start_date": sd,
            "end_date": ed,
            "reason": reason,
        })

    per = max(1, len(outage_entries) // n_outage_files)
    for fi in range(n_outage_files):
        start = fi * per
        end = start + per if fi < n_outage_files - 1 else len(outage_entries)
        batch = outage_entries[start:end]
        fpath = os.path.join(workspace, f"planned_outage_schedule_{fi+1}.yaml")
        with open(fpath, "w") as f:
            yaml.dump({"planned_outages": batch}, f,
                      default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(args.workspace, exist_ok=True)

    n_signals = SCALE["rows_per_table"]
    signals = generate_signals(n_signals, fake)
    button_logs = generate_button_logs(signals, SCALE["rows_per_table"] * 6, fake)
    phase_telemetry = generate_phase_telemetry(
        signals, SCALE["rows_per_table"] * 8, fake
    )
    congestion_alerts = generate_congestion_alerts(
        signals, SCALE["rows_per_table"] * 3, fake
    )
    maintenance_history = generate_maintenance_history(
        signals, SCALE["rows_per_table"] * 2, fake
    )

    create_database(
        args.db_path, signals, button_logs, phase_telemetry,
        congestion_alerts, maintenance_history,
    )
    generate_workspace(args.workspace, signals, fake)


if __name__ == "__main__":
    main()
