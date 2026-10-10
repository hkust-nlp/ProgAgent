"""
Data generation script for industrial facility compliance risk assessment task.
Generates a SQLite database and workspace files for the task environment.
"""

import argparse
import os
import json
import csv
import sqlite3
import random
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
import yaml

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 60,       # v1 = 2 × 30
    "num_workspace_files": 20,  # v1 = 10 + 10
}

# ── Deterministic seeds ─────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ── Domain constants ────────────────────────────────────────────────────────
POLLUTANTS = [
    ("BOD", "mg/L"),
    ("COD", "mg/L"),
    ("TSS", "mg/L"),
    ("NH3", "mg/L"),
    ("PH", "pH"),
    ("TEMP", "°C"),
    ("OG", "mg/L"),
    ("TN", "mg/L"),
    ("TP", "mg/L"),
    ("HM_PB", "µg/L"),
    ("HM_CD", "µg/L"),
    ("HM_CR", "µg/L"),
]

SECTORS = [
    "Chemical Manufacturing", "Food Processing", "Metal Fabrication",
    "Petroleum Refining", "Pharmaceutical", "Pulp and Paper",
    "Textile Manufacturing", "Electronics Manufacturing",
]

REGIONS = ["North", "South", "East", "West", "Central"]

SENSITIVITY_ZONES = ["Critical", "High", "Medium", "Low"]
ZONE_MULTIPLIERS = {"Critical": 2.0, "High": 1.5, "Medium": 1.0, "Low": 0.75}

VIOLATION_TYPES = [
    "Exceedance", "Reporting Failure", "Equipment Malfunction",
    "Unauthorized Discharge", "Monitoring Gap", "Record Keeping",
]

EQUIPMENT_TYPES = [
    "Primary Clarifier", "Aeration Basin", "Secondary Clarifier",
    "Chemical Feed System", "UV Disinfection", "pH Neutralization",
    "Oil-Water Separator", "Filtration System", "Sludge Dewatering",
    "Flow Meter", "Effluent Sampler", "Cooling Tower",
]

REFERENCE_DATE = datetime(2026, 4, 25)

# Realistic value ranges per pollutant (for sensor readings)
SENSOR_RANGES = {
    "BOD": (15, 90), "COD": (40, 250), "TSS": (10, 120),
    "NH3": (0.5, 35), "PH": (5.0, 10.0), "TEMP": (12, 42),
    "OG": (1, 30), "TN": (3, 55), "TP": (0.5, 18),
    "HM_PB": (3, 120), "HM_CD": (0.5, 35), "HM_CR": (5, 180),
}

# Permit limit ranges (daily max)
PERMIT_RANGES = {
    "BOD": (30, 65), "COD": (100, 200), "TSS": (30, 85),
    "NH3": (5, 22), "PH": (6.0, 9.0), "TEMP": (25, 38),
    "OG": (5, 18), "TN": (10, 40), "TP": (2, 12),
    "HM_PB": (15, 70), "HM_CD": (3, 18), "HM_CR": (25, 110),
}


# ── Database helpers ────────────────────────────────────────────────────────

def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS facilities (
            facility_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT NOT NULL,
            region TEXT NOT NULL,
            operating_status TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            employee_count INTEGER,
            established_year INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id TEXT NOT NULL,
            pollutant_code TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            sensor_status TEXT NOT NULL,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS discharge_permits (
            permit_id TEXT PRIMARY KEY,
            facility_id TEXT NOT NULL,
            pollutant_code TEXT NOT NULL,
            daily_max REAL NOT NULL,
            monthly_avg_max REAL NOT NULL,
            unit TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            violation_id TEXT PRIMARY KEY,
            facility_id TEXT NOT NULL,
            inspection_date TEXT NOT NULL,
            violation_type TEXT NOT NULL,
            severity INTEGER NOT NULL,
            description TEXT,
            resolved INTEGER NOT NULL DEFAULT 0,
            resolution_date TEXT,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id TEXT NOT NULL,
            equipment_name TEXT NOT NULL,
            maintenance_type TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            completed_date TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (facility_id) REFERENCES facilities(facility_id)
        )
    """)
    conn.commit()


def generate_facilities(conn, n):
    """Generate n facilities and return (facility_ids, facility_rows)."""
    rows = []
    used_names = set()
    for i in range(n):
        fid = f"FAC-{i+1:04d}"
        while True:
            base = fake.company()
            suffix = random.choice(["Industries", "Manufacturing", "Works",
                                    "Plant", "Corp", "Facilities", "Operations"])
            name = f"{base} {suffix}"
            if name not in used_names:
                used_names.add(name)
                break
        sector = random.choice(SECTORS)
        region = random.choice(REGIONS)
        status = random.choices(
            ["Active", "Suspended", "Under Review"],
            weights=[80, 10, 10],
        )[0]
        lat = round(random.uniform(30.0, 45.0), 6)
        lon = round(random.uniform(-120.0, -75.0), 6)
        emp = random.randint(50, 2000)
        year = random.randint(1960, 2020)
        rows.append((fid, name, sector, region, status, lat, lon, emp, year))
    conn.executemany("INSERT INTO facilities VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return [r[0] for r in rows], rows


def _random_ts(days_back_max=30):
    """Return an ISO timestamp within the last days_back_max days from REFERENCE_DATE."""
    delta = timedelta(
        days=random.randint(0, days_back_max),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    dt = REFERENCE_DATE - delta
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def generate_sensor_readings(conn, facility_ids, n):
    """
    Generate sensor readings. Each facility gets readings for 3-6 pollutants.
    Returns {facility_id: [(pollutant_code, unit), ...]} mapping.
    """
    fac_pollutants = {}
    rows = []
    for fid in facility_ids:
        num_poll = random.randint(3, 6)
        chosen = random.sample(POLLUTANTS, num_poll)
        fac_pollutants[fid] = chosen
        for code, unit in chosen:
            num_readings = random.randint(1, 3)
            lo, hi = SENSOR_RANGES[code]
            for _ in range(num_readings):
                val = round(random.uniform(lo, hi), 2)
                ts = _random_ts(30)
                ss = random.choices(
                    ["Normal", "Calibration Due", "Fault"],
                    weights=[80, 15, 5],
                )[0]
                rows.append((fid, code, val, unit, ts, ss))

    # Ensure at least n rows
    while len(rows) < n:
        fid = random.choice(facility_ids)
        code, unit = random.choice(fac_pollutants[fid])
        lo, hi = SENSOR_RANGES[code]
        val = round(random.uniform(lo, hi), 2)
        rows.append((fid, code, val, unit, _random_ts(30),
                      random.choice(["Normal", "Calibration Due", "Fault"])))

    conn.executemany(
        "INSERT INTO sensor_readings "
        "(facility_id, pollutant_code, value, unit, timestamp, sensor_status) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return fac_pollutants


def generate_permits(conn, facility_ids, fac_pollutants, n):
    """Generate discharge permits aligned with each facility's pollutant set."""
    rows = []
    pid_counter = 0
    for fid in facility_ids:
        for code, unit in fac_pollutants[fid]:
            pid_counter += 1
            pid = f"PRM-{pid_counter:05d}"
            lo, hi = PERMIT_RANGES[code]
            daily_max = round(random.uniform(lo, hi), 2)
            monthly_avg = round(daily_max * random.uniform(0.60, 0.85), 2)
            eff = f"2025-{random.randint(1,12):02d}-01"
            exp = f"2027-{random.randint(1,12):02d}-01"
            rows.append((pid, fid, code, daily_max, monthly_avg, unit, eff, exp))

    # Ensure at least n rows
    while len(rows) < n:
        fid = random.choice(facility_ids)
        code, unit = random.choice(fac_pollutants[fid])
        pid_counter += 1
        pid = f"PRM-{pid_counter:05d}"
        lo, hi = PERMIT_RANGES[code]
        daily_max = round(random.uniform(lo, hi), 2)
        monthly_avg = round(daily_max * random.uniform(0.60, 0.85), 2)
        rows.append((pid, fid, code, daily_max, monthly_avg, unit,
                      "2025-06-01", "2027-06-01"))

    conn.executemany("INSERT INTO discharge_permits VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_violations(conn, facility_ids, n):
    """Generate violation records; at least n rows."""
    rows = []
    vid = 0
    for fid in facility_ids:
        num_v = random.randint(1, max(2, n // len(facility_ids) + 1))
        for _ in range(num_v):
            vid += 1
            vid_str = f"VIO-{vid:05d}"
            days_ago = random.randint(30, 400)
            insp_dt = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            vtype = random.choice(VIOLATION_TYPES)
            sev = random.randint(1, 5)
            desc = f"{vtype} detected at facility {fid} during scheduled inspection"
            resolved = random.choices([0, 1], weights=[35, 65])[0]
            res_date = None
            if resolved:
                res_days = random.randint(5, min(days_ago, 120))
                res_date = (REFERENCE_DATE - timedelta(days=days_ago - res_days)).strftime("%Y-%m-%d")
            rows.append((vid_str, fid, insp_dt, vtype, sev, desc, resolved, res_date))

    while len(rows) < n:
        fid = random.choice(facility_ids)
        vid += 1
        vid_str = f"VIO-{vid:05d}"
        days_ago = random.randint(30, 400)
        insp_dt = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        vtype = random.choice(VIOLATION_TYPES)
        sev = random.randint(1, 5)
        resolved = random.choices([0, 1], weights=[35, 65])[0]
        res_date = None
        if resolved:
            res_days = random.randint(5, min(days_ago, 120))
            res_date = (REFERENCE_DATE - timedelta(days=days_ago - res_days)).strftime("%Y-%m-%d")
        rows.append((vid_str, fid, insp_dt, vtype, sev,
                      f"{vtype} at {fid}", resolved, res_date))

    conn.executemany("INSERT INTO violations VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def generate_maintenance(conn, facility_ids, n):
    """Generate maintenance log entries; at least n rows."""
    rows = []
    for fid in facility_ids:
        num_m = random.randint(1, max(2, n // len(facility_ids) + 1))
        for _ in range(num_m):
            equip = random.choice(EQUIPMENT_TYPES)
            mtype = random.choice(["Preventive", "Corrective", "Emergency", "Calibration"])
            days_offset = random.randint(-60, 60)
            sched = (REFERENCE_DATE + timedelta(days=days_offset)).strftime("%Y-%m-%d")
            if days_offset < -7:
                status = random.choices(["Completed", "Overdue"], weights=[60, 40])[0]
            elif days_offset < 0:
                status = random.choices(["Completed", "Overdue", "Scheduled"],
                                        weights=[40, 40, 20])[0]
            else:
                status = "Scheduled"
            comp_date = sched if status == "Completed" else None
            rows.append((fid, equip, mtype, sched, comp_date, status))

    while len(rows) < n:
        fid = random.choice(facility_ids)
        equip = random.choice(EQUIPMENT_TYPES)
        mtype = random.choice(["Preventive", "Corrective", "Emergency", "Calibration"])
        days_offset = random.randint(-60, 60)
        sched = (REFERENCE_DATE + timedelta(days=days_offset)).strftime("%Y-%m-%d")
        status = random.choices(["Completed", "Overdue", "Scheduled"],
                                weights=[40, 30, 30])[0]
        comp_date = sched if status == "Completed" else None
        rows.append((fid, equip, mtype, sched, comp_date, status))

    conn.executemany(
        "INSERT INTO maintenance_logs "
        "(facility_id, equipment_name, maintenance_type, scheduled_date, "
        "completed_date, status) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


# ── Workspace generation ────────────────────────────────────────────────────

def generate_workspace(workspace, facility_ids, conn, n_files):
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed configuration files (not counted in n_files) ──────────────

    # 1. Risk scoring configuration
    risk_config = {
        "reference_date": "2026-04-25",
        "scoring_weights": {
            "exceedance": 0.35,
            "violation_history": 0.25,
            "maintenance_risk": 0.15,
            "lab_discrepancy": 0.15,
            "corrective_action": 0.10,
        },
        "recency_weights": {
            "last_90_days": 2.0,
            "last_180_days": 1.5,
            "last_365_days": 1.0,
            "older": 0.5,
        },
        "unresolved_multiplier": 1.5,
        "dispatch_thresholds": {
            "IMMEDIATE": 8.0,
            "PRIORITY": 5.0,
            "ROUTINE": 2.0,
        },
        "risk_categories": {
            "CRITICAL": 8.0,
            "HIGH": 5.0,
            "MODERATE": 2.0,
        },
    }
    with open(os.path.join(workspace, "risk_scoring_config.yaml"), "w") as f:
        yaml.dump(risk_config, f, default_flow_style=False, sort_keys=False)

    # 2. Pollutant hazard tiers
    tier_map = {
        "BOD": 2, "COD": 2, "TSS": 1, "NH3": 3, "PH": 2, "TEMP": 1,
        "OG": 3, "TN": 2, "TP": 2, "HM_PB": 4, "HM_CD": 4, "HM_CR": 4,
    }
    tier_multipliers = {1: 1.0, 2: 1.5, 3: 2.0, 4: 3.0}
    hazard_rows = []
    for code, _ in POLLUTANTS:
        tier = tier_map[code]
        hazard_rows.append({
            "pollutant_code": code,
            "hazard_tier": tier,
            "tier_multiplier": tier_multipliers[tier],
            "category": (
                "Heavy Metal" if code.startswith("HM_")
                else "Conventional" if code in ("BOD", "COD", "TSS", "PH", "TEMP")
                else "Nutrient/Other"
            ),
        })
    with open(os.path.join(workspace, "pollutant_hazard_tiers.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pollutant_code", "hazard_tier",
                                           "tier_multiplier", "category"])
        w.writeheader()
        w.writerows(hazard_rows)

    # 3. Dispatch rules
    dispatch_rules = {
        "max_dispatches_per_day": 12,
        "inspector_capacity_by_region": {r: random.randint(2, 5) for r in REGIONS},
        "urgency_order": ["IMMEDIATE", "PRIORITY", "ROUTINE", "MONITOR"],
        "tie_breaking": "risk_score descending then facility_id ascending",
        "output_format": {
            "filename": "dispatch_list.csv",
            "columns": [
                "rank", "facility_id", "facility_name", "region",
                "risk_score", "risk_category", "primary_concern",
                "dispatch_urgency",
            ],
            "risk_score_precision": 2,
            "sort": "risk_score descending, facility_id ascending for ties",
        },
    }
    with open(os.path.join(workspace, "dispatch_rules.json"), "w") as f:
        json.dump(dispatch_rules, f, indent=2)

    # 4. Assessment methodology — authoritative definition of every risk
    #    component, mapping, and label used in the quarterly assessment.
    methodology_md = """# Quarterly Compliance Risk Assessment Methodology

## Scope

The assessment covers every registered facility whose operating status is
currently Active. Each in-scope facility receives a composite risk score
built from the five components below, weighted by the scoring weights in the
risk scoring configuration.

## Component 1 — Effluent exceedance

For every pollutant monitored at a facility, identify the most recent sensor
reading and the corresponding permitted daily maximum. Independent laboratory
analyses of discharge samples are recorded in the lab analysis files; when
the lab-verified value for a given facility and pollutant exceeds the
sensor-reported value, the lab-verified value is used in place of the sensor
value for exceedance purposes. If a facility holds multiple permit records
for the same pollutant, use the most restrictive (lowest) daily maximum.
Pollutants without a permit record are skipped. For each pollutant where the
effective concentration exceeds the daily maximum, compute the fractional
excess as the difference between the effective value and the limit divided
by the limit, then multiply by that pollutant's hazard-tier multiplier from
the pollutant hazard tier reference table. Sum these across all pollutants
to obtain the exceedance component.

## Component 2 — Violation history

Each inspection violation carries a severity rating on a one-to-five scale.
Weight each violation's severity by a recency factor determined by the
number of days elapsed between the inspection date and the reference date in
the scoring configuration: violations within the most recent ninety days use
the 90-day weight, those within one hundred eighty days the 180-day weight,
those within three hundred sixty-five days the 365-day weight, and anything
older the "older" weight. Violations that remain unresolved are further
scaled by the unresolved multiplier from the configuration. Sum the weighted
severity values to produce the violation-history component.

## Component 3 — Maintenance risk

Count the facility's maintenance log entries whose status is Overdue; this
count is the maintenance risk component.

## Component 4 — Lab discrepancy

For each pollutant at the facility, compare the most recent sensor reading
with the corresponding lab-verified value. Count the pollutants for which
the lab-verified value exceeds the sensor-reported value by more than ten
percent of the sensor value. This count is the lab-discrepancy component.

## Component 5 — Corrective actions

The corrective action files record the current status of corrective action
plans filed in response to past violations, across multiple files in varying
formats. Count the corrective actions marked as Overdue for each facility;
this count is the corrective-action component.

## Composite score

Multiply each of the five component scores by its respective weight from the
scoring configuration and sum them to obtain a raw risk score. Multiply the
raw score by the environmental sensitivity zone multiplier assigned to the
facility in the site assessment records. Round the final risk score to two
decimal places.

## Category, urgency, and primary concern

Map the final risk score to a risk category using the thresholds in the
scoring configuration: scores at or above the CRITICAL threshold are
CRITICAL, those at or above the HIGH threshold are HIGH, those at or above
the MODERATE threshold are MODERATE, and all others are LOW. Map the score
to a dispatch urgency using the dispatch thresholds: IMMEDIATE for the
highest tier, PRIORITY for the next, ROUTINE for the next, and MONITOR for
everything below. The facility's primary concern is the component whose
weighted contribution to the raw score (before the zone multiplier) is the
greatest, labeled exactly as one of: Exceedance, Violations, Maintenance,
Lab Discrepancy, Corrective Actions.
"""
    with open(os.path.join(workspace, "assessment_methodology.md"), "w") as f:
        f.write(methodology_md)

    # ── Scalable data files (n_files total) ─────────────────────────────

    n_site = max(1, n_files * 4 // 10)       # ~40 % site assessments (.json)
    n_lab = max(1, n_files * 3 // 10)         # ~30 % lab results (.csv)
    n_ca = max(1, n_files - n_site - n_lab)   # ~30 % corrective actions (mixed)

    # --- Site assessment files (JSON) ---
    fac_zones = {}
    for fid in facility_ids:
        fac_zones[fid] = random.choice(SENSITIVITY_ZONES)

    facs_per_file = max(1, math.ceil(len(facility_ids) / n_site))
    for i in range(n_site):
        start = i * facs_per_file
        end = min(start + facs_per_file, len(facility_ids))
        if start >= len(facility_ids):
            start = start % len(facility_ids)
            end = min(start + facs_per_file, len(facility_ids))
        batch_fids = facility_ids[start:end]
        assessments = []
        for fid in batch_fids:
            assessments.append({
                "facility_id": fid,
                "environmental_sensitivity_zone": fac_zones[fid],
                "zone_multiplier": ZONE_MULTIPLIERS[fac_zones[fid]],
                "proximity_to_waterway_km": round(random.uniform(0.1, 15.0), 2),
                "nearby_population_density": random.choice(
                    ["Dense", "Moderate", "Sparse"]),
                "last_comprehensive_audit_date": (
                    REFERENCE_DATE - timedelta(days=random.randint(60, 365))
                ).strftime("%Y-%m-%d"),
                "audit_score": random.randint(40, 100),
            })
        fname = f"site_assessment_batch_{i+1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(assessments, f, indent=2)

    # --- Lab analysis files (CSV) ---
    c = conn.cursor()
    c.execute("""
        SELECT facility_id, pollutant_code, value, unit
        FROM sensor_readings
        ORDER BY facility_id, pollutant_code, timestamp DESC
    """)
    all_sensor = c.fetchall()

    # Deduplicate to one row per (facility, pollutant) – use first (latest) reading
    seen = set()
    unique_sensor = []
    for fid, pcode, val, unit in all_sensor:
        key = (fid, pcode)
        if key not in seen:
            seen.add(key)
            unique_sensor.append((fid, pcode, val, unit))

    rows_per_lab = max(1, math.ceil(len(unique_sensor) / n_lab))
    for i in range(n_lab):
        start = i * rows_per_lab
        end = min(start + rows_per_lab, len(unique_sensor))
        if start >= len(unique_sensor):
            break
        batch = unique_sensor[start:end]
        lab_rows = []
        for fid, pcode, sensor_val, unit in batch:
            deviation = random.uniform(-0.20, 0.40)
            lab_val = round(sensor_val * (1 + deviation), 2)
            lab_rows.append({
                "facility_id": fid,
                "pollutant_code": pcode,
                "sensor_reported_value": sensor_val,
                "lab_verified_value": lab_val,
                "discrepancy_pct": round(deviation * 100, 1),
                "sample_date": (
                    REFERENCE_DATE - timedelta(days=random.randint(1, 25))
                ).strftime("%Y-%m-%d"),
                "lab_name": random.choice([
                    "EnviroTest Labs", "AquaCheck Inc",
                    "PureAnalysis Corp", "GreenMetrics Lab",
                ]),
            })
        fname = f"lab_analysis_batch_{i+1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "facility_id", "pollutant_code", "sensor_reported_value",
                "lab_verified_value", "discrepancy_pct", "sample_date",
                "lab_name",
            ])
            w.writeheader()
            w.writerows(lab_rows)

    # --- Corrective action files (mixed YAML / MD / TXT) ---
    c.execute("""
        SELECT violation_id, facility_id, violation_type, severity, resolved
        FROM violations
    """)
    all_viols = c.fetchall()
    ca_records = []
    for vid_str, fid, vtype, sev, resolved in all_viols:
        if resolved:
            ca_status = "Closed"
        else:
            ca_status = random.choices(
                ["Open", "Overdue", "In Progress"],
                weights=[30, 40, 30],
            )[0]
        due_days = random.randint(-30, 90)
        due_date = (REFERENCE_DATE + timedelta(days=due_days)).strftime("%Y-%m-%d")
        ca_records.append({
            "violation_id": vid_str,
            "facility_id": fid,
            "violation_type": vtype,
            "corrective_action_status": ca_status,
            "assigned_to": fake.name(),
            "due_date": due_date,
            "action_description": f"Corrective action for {vtype} at facility {fid}",
        })

    ca_per_file = max(1, math.ceil(len(ca_records) / n_ca))
    for i in range(n_ca):
        start = i * ca_per_file
        end = min(start + ca_per_file, len(ca_records))
        if start >= len(ca_records):
            break
        batch = ca_records[start:end]
        fmt = i % 3

        if fmt == 0:
            fname = f"corrective_actions_{i+1:03d}.yaml"
            with open(os.path.join(workspace, fname), "w") as f:
                yaml.dump(batch, f, default_flow_style=False, sort_keys=False)

        elif fmt == 1:
            fname = f"corrective_actions_{i+1:03d}.md"
            lines = [f"# Corrective Action Report - Batch {i+1}\n\n"]
            for rec in batch:
                lines.append(f"## {rec['violation_id']}\n\n")
                lines.append(f"- Facility: {rec['facility_id']}\n")
                lines.append(f"- Violation Type: {rec['violation_type']}\n")
                lines.append(
                    f"- Corrective Action Status: "
                    f"{rec['corrective_action_status']}\n")
                lines.append(f"- Assigned To: {rec['assigned_to']}\n")
                lines.append(f"- Due Date: {rec['due_date']}\n\n")
            with open(os.path.join(workspace, fname), "w") as f:
                f.writelines(lines)

        else:
            fname = f"corrective_actions_{i+1:03d}.txt"
            lines = []
            for rec in batch:
                lines.append(f"Violation ID: {rec['violation_id']}\n")
                lines.append(f"Facility: {rec['facility_id']}\n")
                lines.append(f"Type: {rec['violation_type']}\n")
                lines.append(
                    f"Corrective Action Status: "
                    f"{rec['corrective_action_status']}\n")
                lines.append(f"Assigned To: {rec['assigned_to']}\n")
                lines.append(f"Due Date: {rec['due_date']}\n")
                lines.append("---\n")
            with open(os.path.join(workspace, fname), "w") as f:
                f.writelines(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    facility_ids, _ = generate_facilities(conn, n)
    fac_pollutants = generate_sensor_readings(conn, facility_ids, n)
    generate_permits(conn, facility_ids, fac_pollutants, n)
    generate_violations(conn, facility_ids, n)
    generate_maintenance(conn, facility_ids, n)
    generate_workspace(args.workspace, facility_ids, conn,
                       SCALE["num_workspace_files"])

    conn.close()
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")


if __name__ == "__main__":
    main()
