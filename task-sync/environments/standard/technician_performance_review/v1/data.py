"""
Data generation script for Technician Performance & Retraining Priority task.
Generates database tables and workspace files for cross-referencing GPS logs,
appointment windows, satisfaction surveys, and service complexity ratings.
"""

import argparse
import os
import sys
import sqlite3
import json
import csv
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 80,       # v1 = 2× base
    "num_workspace_files": 20,  # v1 = base + N (10 + 10)
}


def main(db_path: str, workspace: str):
    # ── Seeds ──
    np.random.seed(42)
    random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    rows = SCALE["rows_per_table"]
    num_gps_weeks = SCALE["num_workspace_files"]

    # ── Derived counts ──
    num_technicians = rows
    num_service_categories = rows
    num_customers = max(rows, 40)
    num_appointments = rows * 6  # ~6 appointments per technician on average
    num_surveys = rows * 4       # ~4 surveys per technician on average

    # ── Designate problem technicians ──
    all_tech_ids = list(range(1, num_technicians + 1))
    problem_late_count = max(5, num_technicians // 5)
    problem_sat_count = max(4, num_technicians // 6)
    penalty_count = max(3, num_technicians // 12)

    shuffled_for_late = all_tech_ids.copy()
    random.shuffle(shuffled_for_late)
    problem_late = set(shuffled_for_late[:problem_late_count])

    shuffled_for_sat = all_tech_ids.copy()
    random.shuffle(shuffled_for_sat)
    problem_sat = set(shuffled_for_sat[:problem_sat_count])

    shuffled_for_penalty = all_tech_ids.copy()
    random.shuffle(shuffled_for_penalty)
    penalty_techs = shuffled_for_penalty[:penalty_count]

    # ── Service Categories ──
    base_services = [
        "HVAC", "Plumbing", "Electrical", "Appliance Repair", "Roofing",
        "Painting", "Carpentry", "Landscaping", "Pest Control", "Flooring",
        "Window Installation", "Insulation", "Solar Panel", "Security System",
        "Fire Protection", "Garage Door", "Water Heater", "Chimney",
        "Drywall", "Fencing"
    ]
    sub_types = [
        "Installation", "Repair", "Maintenance", "Inspection",
        "Emergency", "Upgrade", "Replacement", "Diagnostic"
    ]

    categories = []
    cat_id = 0
    for base in base_services:
        for sub in sub_types:
            cat_id += 1
            if cat_id > num_service_categories:
                break
            complexity = int(np.random.randint(1, 6))
            avg_dur = int(np.random.randint(30, 241))
            categories.append({
                "id": cat_id,
                "name": f"{base} - {sub}",
                "complexity_rating": complexity,
                "avg_duration_minutes": avg_dur,
                "description": fake.sentence(nb_words=10),
            })
        if cat_id >= num_service_categories:
            break
    while len(categories) < num_service_categories:
        cat_id += 1
        categories.append({
            "id": cat_id,
            "name": f"Specialty Service {cat_id}",
            "complexity_rating": int(np.random.randint(1, 6)),
            "avg_duration_minutes": int(np.random.randint(30, 241)),
            "description": fake.sentence(nb_words=10),
        })

    # ── Technicians ──
    regions = ["North", "South", "East", "West", "Central"]
    cert_levels = ["Junior", "Standard", "Senior", "Master"]

    technicians = []
    for i in range(1, num_technicians + 1):
        technicians.append({
            "id": f"TECH_{i:04d}",
            "name": fake.name(),
            "certification_level": random.choice(cert_levels),
            "hire_date": fake.date_between(start_date="-10y", end_date="-6m").isoformat(),
            "region": random.choice(regions),
            "phone": fake.phone_number(),
            "email": fake.email(),
        })

    # ── Customers ──
    customer_tiers = ["Bronze", "Silver", "Gold", "Platinum"]
    customers = []
    for i in range(1, num_customers + 1):
        customers.append({
            "id": f"CUST_{i:04d}",
            "name": fake.name(),
            "address": fake.address().replace("\n", ", "),
            "phone": fake.phone_number(),
            "email": fake.email(),
            "tier": random.choice(customer_tiers),
        })

    # ── Appointments ──
    base_date = datetime(2025, 1, 6)  # Monday of week 1
    appointments = []
    for i in range(1, num_appointments + 1):
        tech_idx = ((i - 1) % num_technicians) + 1
        tech_id = f"TECH_{tech_idx:04d}"
        cust_idx = random.randint(1, num_customers)
        cust_id = f"CUST_{cust_idx:04d}"
        cat = random.choice(categories)
        cat_id_val = cat["id"]

        week = (i - 1) % num_gps_weeks
        day_in_week = random.randint(0, 4)
        appt_date = base_date + timedelta(days=week * 7 + day_in_week)

        hour = random.randint(8, 16)
        minute = random.choice([0, 15, 30, 45])
        scheduled_start = f"{hour:02d}:{minute:02d}"
        dur = cat["avg_duration_minutes"]
        end_total = hour * 60 + minute + dur
        end_h = min(end_total // 60, 20)
        end_m = end_total % 60
        scheduled_end = f"{end_h:02d}:{end_m:02d}"

        if random.random() < 0.90:
            status = "completed"
        elif random.random() < 0.5:
            status = "cancelled"
        else:
            status = "no-show"

        appointments.append({
            "id": f"APPT_{i:05d}",
            "technician_id": tech_id,
            "customer_id": cust_id,
            "service_category_id": cat_id_val,
            "scheduled_date": appt_date.strftime("%Y-%m-%d"),
            "scheduled_start_time": scheduled_start,
            "scheduled_end_time": scheduled_end,
            "status": status,
            "address": fake.street_address(),
            "region": technicians[tech_idx - 1]["region"],
        })

    # ── GPS arrival records (only for completed appointments) ──
    completed_appts = [a for a in appointments if a["status"] == "completed"]
    gps_records = []
    for appt in completed_appts:
        tech_num = int(appt["technician_id"].split("_")[1])
        is_late_prone = tech_num in problem_late

        sched_h, sched_m = map(int, appt["scheduled_start_time"].split(":"))
        sched_minutes = sched_h * 60 + sched_m

        if is_late_prone:
            offset = float(np.random.normal(12, 14))
        else:
            offset = float(np.random.normal(-3, 7))

        arrival_total = sched_minutes + offset
        arrival_h = int(max(6, min(20, arrival_total // 60)))
        arrival_m = int(max(0, min(59, arrival_total % 60)))
        arrival_s = random.randint(0, 59)
        arrival_time_str = f"{arrival_h:02d}:{arrival_m:02d}:{arrival_s:02d}"

        lat = round(float(np.random.uniform(25.0, 48.0)), 6)
        lon = round(float(np.random.uniform(-122.0, -73.0)), 6)

        gps_records.append({
            "technician_id": appt["technician_id"],
            "appointment_id": appt["id"],
            "date": appt["scheduled_date"],
            "arrival_timestamp": f"{appt['scheduled_date']} {arrival_time_str}",
            "latitude": lat,
            "longitude": lon,
            "event_type": "arrived",
        })

    # ── Satisfaction Surveys ──
    survey_appt_indices = random.sample(
        range(len(completed_appts)),
        k=min(num_surveys, len(completed_appts)),
    )
    surveys = []
    for idx, appt_idx in enumerate(sorted(survey_appt_indices)):
        appt = completed_appts[appt_idx]
        tech_num = int(appt["technician_id"].split("_")[1])
        is_poor_sat = tech_num in problem_sat

        if is_poor_sat:
            overall = round(float(np.clip(np.random.normal(2.3, 0.8), 1.0, 5.0)), 1)
            punctuality = round(float(np.clip(np.random.normal(2.0, 0.9), 1.0, 5.0)), 1)
            professionalism = round(float(np.clip(np.random.normal(2.5, 0.8), 1.0, 5.0)), 1)
            resolution = round(float(np.clip(np.random.normal(2.4, 0.9), 1.0, 5.0)), 1)
        else:
            overall = round(float(np.clip(np.random.normal(4.0, 0.6), 1.0, 5.0)), 1)
            punctuality = round(float(np.clip(np.random.normal(4.2, 0.5), 1.0, 5.0)), 1)
            professionalism = round(float(np.clip(np.random.normal(4.1, 0.5), 1.0, 5.0)), 1)
            resolution = round(float(np.clip(np.random.normal(4.0, 0.6), 1.0, 5.0)), 1)

        surveys.append({
            "id": f"SURV_{idx + 1:05d}",
            "appointment_id": appt["id"],
            "technician_id": appt["technician_id"],
            "customer_id": appt["customer_id"],
            "overall_score": overall,
            "punctuality_score": punctuality,
            "professionalism_score": professionalism,
            "resolution_score": resolution,
            "comments": fake.sentence(nb_words=12),
            "survey_date": appt["scheduled_date"],
        })

    # ═══════════════════════════════════════════════════════
    # ── DATABASE ──
    # ═══════════════════════════════════════════════════════
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS technicians (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            certification_level TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            region TEXT NOT NULL,
            phone TEXT,
            email TEXT
        )
    """)
    for t in technicians:
        cur.execute(
            "INSERT INTO technicians VALUES (?,?,?,?,?,?,?)",
            (t["id"], t["name"], t["certification_level"],
             t["hire_date"], t["region"], t["phone"], t["email"]),
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS service_categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            complexity_rating INTEGER NOT NULL,
            avg_duration_minutes INTEGER NOT NULL,
            description TEXT
        )
    """)
    for c in categories:
        cur.execute(
            "INSERT INTO service_categories VALUES (?,?,?,?,?)",
            (c["id"], c["name"], c["complexity_rating"],
             c["avg_duration_minutes"], c["description"]),
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            email TEXT,
            tier TEXT NOT NULL
        )
    """)
    for c in customers:
        cur.execute(
            "INSERT INTO customers VALUES (?,?,?,?,?,?)",
            (c["id"], c["name"], c["address"], c["phone"], c["email"], c["tier"]),
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            technician_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            service_category_id INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL,
            scheduled_start_time TEXT NOT NULL,
            scheduled_end_time TEXT NOT NULL,
            status TEXT NOT NULL,
            address TEXT,
            region TEXT,
            FOREIGN KEY (technician_id) REFERENCES technicians(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (service_category_id) REFERENCES service_categories(id)
        )
    """)
    for a in appointments:
        cur.execute(
            "INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)",
            (a["id"], a["technician_id"], a["customer_id"],
             a["service_category_id"], a["scheduled_date"],
             a["scheduled_start_time"], a["scheduled_end_time"],
             a["status"], a["address"], a["region"]),
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS satisfaction_surveys (
            id TEXT PRIMARY KEY,
            appointment_id TEXT NOT NULL,
            technician_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            overall_score REAL NOT NULL,
            punctuality_score REAL NOT NULL,
            professionalism_score REAL NOT NULL,
            resolution_score REAL NOT NULL,
            comments TEXT,
            survey_date TEXT NOT NULL,
            FOREIGN KEY (appointment_id) REFERENCES appointments(id),
            FOREIGN KEY (technician_id) REFERENCES technicians(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    for s in surveys:
        cur.execute(
            "INSERT INTO satisfaction_surveys VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["appointment_id"], s["technician_id"],
             s["customer_id"], s["overall_score"], s["punctuality_score"],
             s["professionalism_score"], s["resolution_score"],
             s["comments"], s["survey_date"]),
        )

    conn.commit()
    conn.close()

    # ═══════════════════════════════════════════════════════
    # ── WORKSPACE FILES ──
    # ═══════════════════════════════════════════════════════

    # ── 1. GPS log CSV files (scalable: num_workspace_files) ──
    # Group GPS records by week
    week_buckets = {}
    for rec in gps_records:
        d = datetime.strptime(rec["date"], "%Y-%m-%d")
        week_num = ((d - base_date).days // 7) % num_gps_weeks
        week_buckets.setdefault(week_num, []).append(rec)

    # Ensure we create exactly num_gps_weeks files even if some weeks are empty
    for w in range(num_gps_weeks):
        fname = f"gps_log_week_{w + 1:03d}.csv"
        fpath = os.path.join(workspace, fname)
        records = week_buckets.get(w, [])
        with open(fpath, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "technician_id", "appointment_id", "date",
                    "arrival_timestamp", "latitude", "longitude", "event_type",
                ],
            )
            writer.writeheader()
            for rec in records:
                writer.writerow(rec)

    # ── 2. scoring_config.yaml (fixed) ──
    scoring_config = {
        "late_threshold_minutes": 15,
        "satisfaction_threshold": 3.0,
        "late_rate_flag_threshold": 0.30,
        "priority_weights": {
            "late_rate": 0.40,
            "satisfaction": 0.35,
            "complexity": 0.25,
        },
        "retraining_threshold": 0.45,
    }
    import yaml
    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(scoring_config, f, default_flow_style=False, sort_keys=False)

    # ── 3. complexity_matrix.json (fixed) ──
    complexity_matrix = {
        "1": 0.20,
        "2": 0.40,
        "3": 0.60,
        "4": 0.80,
        "5": 1.00,
    }
    with open(os.path.join(workspace, "complexity_matrix.json"), "w") as f:
        json.dump(complexity_matrix, f, indent=2)

    # ── 4. penalty_adjustments.txt (fixed) ──
    penalty_multipliers = [1.5, 1.3, 1.2, 1.4, 1.25, 1.35, 1.15, 1.45]
    penalty_reasons = [
        "Probationary period",
        "Previous customer complaint escalation",
        "Repeated safety protocol violation",
        "Pending certification renewal",
        "Disciplinary review outcome",
        "Missed mandatory training session",
        "Equipment misuse report",
        "Late documentation submissions",
    ]
    with open(os.path.join(workspace, "penalty_adjustments.txt"), "w") as f:
        f.write("# Penalty adjustments for technicians with prior incidents or special conditions\n")
        f.write("# Format: technician_id | multiplier | reason\n")
        f.write("# The multiplier is applied to the weighted priority score\n")
        f.write("#\n")
        for i, tech_num in enumerate(penalty_techs):
            tid = f"TECH_{tech_num:04d}"
            mult = penalty_multipliers[i % len(penalty_multipliers)]
            reason = penalty_reasons[i % len(penalty_reasons)]
            f.write(f"{tid} | {mult} | {reason}\n")

    # ── 5. service_zone_mapping.md (fixed) ──
    with open(os.path.join(workspace, "service_zone_mapping.md"), "w") as f:
        f.write("# Service Zone Mapping\n\n")
        f.write("This document maps operational regions to service zones.\n\n")
        f.write("| Region | Zone Code | Zone Description |\n")
        f.write("|--------|-----------|------------------|\n")
        f.write("| North | ZN-01 | Northern metropolitan and suburban coverage |\n")
        f.write("| South | ZS-02 | Southern residential and commercial districts |\n")
        f.write("| East | ZE-03 | Eastern industrial and residential corridors |\n")
        f.write("| West | ZW-04 | Western coastal and inland communities |\n")
        f.write("| Central | ZC-05 | Central downtown and business district |\n")
        f.write("\n")
        f.write("Zone codes are used in dispatch logs and performance reports.\n")
        f.write("All technician evaluations should reference the zone of their primary region.\n")

    print(f"Database created at {db_path}")
    print(f"Workspace created at {workspace}")
    print(f"  - {num_gps_weeks} GPS weekly log files")
    print(f"  - scoring_config.yaml")
    print(f"  - complexity_matrix.json")
    print(f"  - penalty_adjustments.txt")
    print(f"  - service_zone_mapping.md")
    print(f"Tables: {num_technicians} technicians, {len(categories)} categories, "
          f"{num_customers} customers, {len(appointments)} appointments, {len(surveys)} surveys")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
