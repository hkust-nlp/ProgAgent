"""
Emergency Resource Utilization Audit - Data Generation Script
Generates SQLite database and workspace files for the audit task.
"""

import numpy as np
import pandas as pd
from faker import Faker
import sqlite3
import os
import json
import csv
import random
import argparse
from datetime import datetime, timedelta
import yaml

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 20,
}

SEED = 42

# ── Constants ──────────────────────────────────────────────────────────────────

AUDIT_DATE = datetime(2025, 1, 15)

UNIT_TYPES = ["engine", "ladder", "rescue", "ems", "hazmat"]
TYPE_PREFIXES = {"engine": "E", "ladder": "L", "rescue": "R", "ems": "M", "hazmat": "H"}

ROLES_BY_TYPE = {
    "engine": ["captain", "lieutenant", "firefighter"],
    "ladder": ["captain", "lieutenant", "firefighter"],
    "rescue": ["captain", "lieutenant", "firefighter"],
    "ems": ["captain", "paramedic", "emt"],
    "hazmat": ["captain", "lieutenant", "hazmat_tech"],
}

CERT_LEVELS = ["basic", "intermediate", "advanced", "specialist"]
CERT_LEVEL_ORDER = {c: i for i, c in enumerate(CERT_LEVELS)}

CERT_REQUIREMENTS = {
    "engine": {"captain": "advanced", "lieutenant": "intermediate", "firefighter": "basic"},
    "ladder": {"captain": "advanced", "lieutenant": "advanced", "firefighter": "intermediate"},
    "rescue": {"captain": "specialist", "lieutenant": "advanced", "firefighter": "intermediate"},
    "ems": {"captain": "specialist", "paramedic": "advanced", "emt": "intermediate"},
    "hazmat": {"captain": "specialist", "lieutenant": "advanced", "hazmat_tech": "specialist"},
}

EQUIPMENT_TYPES = [
    "scba", "thermal_camera", "hydraulic_tool", "defibrillator",
    "pump_unit", "hose_set", "gas_detector", "ventilation_fan",
]

INCIDENT_TYPES = [
    "structure_fire", "vehicle_accident", "hazmat_spill",
    "medical_emergency", "rescue_operation", "wildfire", "gas_leak",
]

MAINTENANCE_TYPES = ["routine_inspection", "repair", "calibration", "replacement"]
MAINTENANCE_RESULTS = ["pass", "fail", "conditional_pass", "deferred"]

VIOLATION_KEYWORDS = [
    "delayed response",
    "unauthorized deviation",
    "communication failure",
    "missed check-in",
    "incomplete handoff",
]

SCORING_MATRIX = {
    "slow_response": {"penalty": 15, "category": "retraining"},
    "certification_deficiency": {"penalty": 5, "category": "retraining"},
    "poor_outcome": {"penalty": 4, "category": "retraining"},
    "protocol_violation": {"penalty": 7, "category": "retraining"},
    "overdue_maintenance": {"penalty": 8, "category": "reequipping"},
    "poor_equipment_condition": {"penalty": 6, "category": "reequipping"},
}


# ── Data Generation ───────────────────────────────────────────────────────────

def generate_units(n, fake):
    units = []
    for i in range(n):
        ut = UNIT_TYPES[i % len(UNIT_TYPES)]
        uid = f"UNIT-{i+1:04d}"
        name = f"{TYPE_PREFIXES[ut]}-{i+1}"
        station = f"Station {(i % max(1, n // 3)) + 1}"
        active = fake.date_between(start_date="-15y", end_date="-1y").isoformat()
        units.append({
            "unit_id": uid,
            "unit_name": name,
            "station": station,
            "unit_type": ut,
            "active_since": active,
        })
    return units


def generate_personnel(units, n_total, fake):
    personnel = []
    person_id = 1

    # Assign at least 2 personnel per unit
    for unit in units:
        ut = unit["unit_type"]
        roles = ROLES_BY_TYPE[ut]
        for role in roles[:2]:
            p = _make_person(person_id, unit, role, fake)
            personnel.append(p)
            person_id += 1

    # Fill remaining
    while len(personnel) < n_total:
        unit = units[len(personnel) % len(units)]
        ut = unit["unit_type"]
        role = random.choice(ROLES_BY_TYPE[ut])
        p = _make_person(person_id, unit, role, fake)
        personnel.append(p)
        person_id += 1

    return personnel


def _make_person(pid, unit, role, fake):
    ut = unit["unit_type"]
    required = CERT_REQUIREMENTS[ut].get(role, "basic")
    req_idx = CERT_LEVEL_ORDER[required]

    # 18% chance under-qualified
    if np.random.random() < 0.18:
        cl_idx = max(0, req_idx - int(np.random.randint(1, 3)))
    else:
        cl_idx = min(len(CERT_LEVELS) - 1, req_idx + int(np.random.randint(0, 2)))
    cl = CERT_LEVELS[cl_idx]

    # 22% chance expired or expiring soon
    if np.random.random() < 0.22:
        days_offset = int(np.random.randint(-90, 90))
        expiry = AUDIT_DATE + timedelta(days=days_offset)
    else:
        expiry = AUDIT_DATE + timedelta(days=int(np.random.randint(91, 730)))

    return {
        "person_id": f"PER-{pid:04d}",
        "name": fake.name(),
        "unit_id": unit["unit_id"],
        "role": role,
        "certification_level": cl,
        "cert_expiry_date": expiry.strftime("%Y-%m-%d"),
        "years_experience": int(np.random.randint(1, 25)),
    }


def generate_equipment(units, n_total, fake):
    equipment = []
    eq_id = 1

    # At least 1 per unit
    for unit in units:
        eq = _make_equipment(eq_id, unit, fake)
        equipment.append(eq)
        eq_id += 1

    # Fill remaining
    while len(equipment) < n_total:
        unit = units[len(equipment) % len(units)]
        eq = _make_equipment(eq_id, unit, fake)
        equipment.append(eq)
        eq_id += 1

    return equipment


def _make_equipment(eid, unit, fake):
    etype = random.choice(EQUIPMENT_TYPES)
    # 20% chance poor condition
    if np.random.random() < 0.20:
        condition = int(np.random.randint(1, 4))  # 1-3
    else:
        condition = int(np.random.randint(4, 10))  # 4-9

    return {
        "equipment_id": f"EQ-{eid:04d}",
        "unit_id": unit["unit_id"],
        "equipment_type": etype,
        "serial_number": fake.bothify("??-####-???").upper(),
        "acquisition_date": fake.date_between(start_date="-10y", end_date="-6m").isoformat(),
        "condition_rating": condition,
    }


def generate_incidents(n_total, fake):
    incidents = []
    for i in range(n_total):
        inc_date = fake.date_time_between(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2025, 1, 14),
        )
        severity = int(np.random.choice([1, 2, 3, 4, 5], p=[0.15, 0.25, 0.30, 0.20, 0.10]))
        itype = random.choice(INCIDENT_TYPES)
        duration = int(np.random.randint(15, 240))
        incidents.append({
            "incident_id": f"INC-{i+1:04d}",
            "incident_date": inc_date.strftime("%Y-%m-%d"),
            "incident_time": inc_date.strftime("%H:%M:%S"),
            "incident_type": itype,
            "severity": severity,
            "location": fake.address().replace("\n", ", "),
            "duration_minutes": duration,
        })
    return incidents


def generate_dispatches(incidents, units):
    dispatches = []
    d_id = 1
    unit_ids = [u["unit_id"] for u in units]
    n_units = len(unit_ids)

    for inc in incidents:
        # 1-3 units per incident
        n_dispatched = int(np.random.choice([1, 2, 3], p=[0.30, 0.45, 0.25]))
        dispatched_units = list(np.random.choice(unit_ids, size=min(n_dispatched, n_units), replace=False))

        inc_dt = datetime.strptime(f"{inc['incident_date']} {inc['incident_time']}", "%Y-%m-%d %H:%M:%S")

        for uid in dispatched_units:
            dispatch_time = inc_dt + timedelta(seconds=int(np.random.randint(0, 120)))
            # Response time: mean ~6 min, but some units are consistently slow
            unit_idx = int(uid.split("-")[1]) - 1
            # Units with index % 5 == 0 or % 7 == 0 are "slow" (~35% of units)
            if unit_idx % 5 == 0 or unit_idx % 7 == 0:
                response_min = max(1, np.random.normal(11, 3))
            else:
                response_min = max(1, np.random.normal(5.5, 2.5))

            arrival_time = dispatch_time + timedelta(minutes=float(response_min))

            dispatches.append({
                "dispatch_id": f"DSP-{d_id:04d}",
                "incident_id": inc["incident_id"],
                "unit_id": uid,
                "dispatch_time": dispatch_time.strftime("%Y-%m-%d %H:%M:%S"),
                "arrival_time": arrival_time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            d_id += 1

    return dispatches


def generate_maintenance_logs(equipment, n_total, fake):
    logs = []
    log_id = 1

    # At least one log per equipment
    for eq in equipment:
        log = _make_maintenance_log(log_id, eq, fake)
        logs.append(log)
        log_id += 1

    # Fill to n_total
    while len(logs) < n_total:
        eq = equipment[len(logs) % len(equipment)]
        log = _make_maintenance_log(log_id, eq, fake)
        logs.append(log)
        log_id += 1

    return logs


def _make_maintenance_log(lid, eq, fake):
    mtype = random.choice(MAINTENANCE_TYPES)

    # 25% chance of overdue (next_due before audit date)
    if np.random.random() < 0.25:
        maint_date = fake.date_between(start_date="-12m", end_date="-3m")
        next_due = maint_date + timedelta(days=int(np.random.randint(30, 90)))
        # Ensure next_due < AUDIT_DATE
        if next_due >= AUDIT_DATE.date():
            next_due = AUDIT_DATE.date() - timedelta(days=int(np.random.randint(1, 60)))
        result = random.choice(["fail", "conditional_pass", "deferred"])
    else:
        maint_date = fake.date_between(start_date="-6m", end_date="-1m")
        next_due = AUDIT_DATE.date() + timedelta(days=int(np.random.randint(30, 365)))
        result = random.choice(["pass", "pass", "pass", "conditional_pass"])

    return {
        "log_id": f"MNT-{lid:04d}",
        "equipment_id": eq["equipment_id"],
        "maintenance_date": maint_date.isoformat(),
        "maintenance_type": mtype,
        "result": result,
        "technician": fake.name(),
        "next_due_date": next_due.isoformat() if isinstance(next_due, datetime) else next_due.isoformat(),
    }


def generate_incident_outcomes(incidents, fake):
    outcomes = []
    for i, inc in enumerate(incidents):
        severity = inc["severity"]
        # Higher severity → more likely poor outcome
        if severity >= 4:
            rating = int(np.random.choice([1, 2, 3, 4, 5], p=[0.15, 0.25, 0.30, 0.20, 0.10]))
        elif severity >= 3:
            rating = int(np.random.choice([1, 2, 3, 4, 5], p=[0.05, 0.15, 0.30, 0.30, 0.20]))
        else:
            rating = int(np.random.choice([1, 2, 3, 4, 5], p=[0.02, 0.08, 0.20, 0.35, 0.35]))

        civilian_injuries = int(np.random.poisson(max(0, severity - 2)))
        prop_damage = round(float(np.random.exponential(severity * 15)), 1)

        outcomes.append({
            "outcome_id": f"OUT-{i+1:04d}",
            "incident_id": inc["incident_id"],
            "outcome_rating": rating,
            "civilian_injuries": civilian_injuries,
            "property_damage_k": prop_damage,
            "after_action_notes": fake.sentence(nb_words=12),
        })
    return outcomes


# ── Transcript Generation ─────────────────────────────────────────────────────

def _generate_radio_messages(inc, dispatched_unit_names, fake):
    """Generate a list of (timestamp, speaker, message) tuples for an incident."""
    inc_dt = datetime.strptime(f"{inc['incident_date']} {inc['incident_time']}", "%Y-%m-%d %H:%M:%S")
    messages = []
    t = inc_dt

    # Initial dispatch
    unit_list = ", ".join(dispatched_unit_names)
    messages.append((t, "DISPATCH", f"{unit_list}, respond to {inc['incident_type'].replace('_', ' ')} at {inc['location']}. Incident #{inc['incident_id']}."))
    t += timedelta(seconds=int(np.random.randint(10, 30)))

    # Acknowledgments
    for uname in dispatched_unit_names:
        messages.append((t, uname, "Copy, en route."))
        t += timedelta(seconds=int(np.random.randint(5, 20)))

    # On-scene messages
    for uname in dispatched_unit_names:
        t += timedelta(minutes=float(np.random.uniform(3, 12)))
        messages.append((t, uname, f"On scene. {fake.sentence(nb_words=6)}"))

    # Operations
    n_ops = int(np.random.randint(2, 6))
    for _ in range(n_ops):
        t += timedelta(minutes=float(np.random.uniform(1, 8)))
        speaker = random.choice(dispatched_unit_names + ["DISPATCH"])
        messages.append((t, speaker, fake.sentence(nb_words=8)))

    # Clearance
    t += timedelta(minutes=float(np.random.uniform(5, 30)))
    messages.append((t, "DISPATCH", "All units clear. Incident closed."))

    return messages


def generate_transcripts(incidents, dispatches, units, n_files):
    """Generate transcript .txt files. Returns list of (filename, content, violation_map)."""
    # Build unit_id -> unit_name mapping
    uid_to_name = {u["unit_id"]: u["unit_name"] for u in units}

    # Build incident -> dispatched unit names
    inc_to_units = {}
    for d in dispatches:
        iid = d["incident_id"]
        uname = uid_to_name.get(d["unit_id"], d["unit_id"])
        inc_to_units.setdefault(iid, set()).add(uname)

    # Select incidents for transcripts
    # Spread evenly across all incidents
    incident_ids = [inc["incident_id"] for inc in incidents]
    step = max(1, len(incident_ids) // n_files)
    selected_indices = list(range(0, len(incident_ids), step))[:n_files]
    # If not enough, take from the end
    while len(selected_indices) < n_files and len(selected_indices) < len(incident_ids):
        candidate = selected_indices[-1] + 1
        if candidate < len(incident_ids):
            selected_indices.append(candidate)
        else:
            break

    fake_t = Faker()
    Faker.seed(SEED + 1000)  # Separate seed for transcript generation
    np.random.seed(SEED + 1000)

    transcripts = []
    for idx in selected_indices:
        inc = incidents[idx]
        iid = inc["incident_id"]
        dispatched_names = sorted(inc_to_units.get(iid, set()))
        if not dispatched_names:
            continue

        messages = _generate_radio_messages(inc, dispatched_names, fake_t)

        # Inject violations: each dispatched unit has 0-2 violations
        violation_map = {}  # unit_name -> count
        violation_lines = []
        for uname in dispatched_names:
            n_violations = int(np.random.choice([0, 0, 1, 1, 2], p=[0.30, 0.15, 0.25, 0.15, 0.15]))
            if n_violations > 0:
                violation_map[uname] = n_violations
                for _ in range(n_violations):
                    keyword = random.choice(VIOLATION_KEYWORDS)
                    # Create a violation message at a random time during incident
                    inc_dt = datetime.strptime(
                        f"{inc['incident_date']} {inc['incident_time']}",
                        "%Y-%m-%d %H:%M:%S",
                    )
                    vtime = inc_dt + timedelta(minutes=float(np.random.uniform(5, 45)))
                    # Randomly choose format
                    if np.random.random() < 0.5:
                        vmsg = (vtime, "DISPATCH", f"{keyword} noted for {uname}")
                    else:
                        vmsg = (vtime, uname, f"Reporting {keyword} during operations")
                    violation_lines.append(vmsg)

        # Merge and sort all messages
        all_messages = messages + violation_lines
        all_messages.sort(key=lambda x: x[0])

        # Format transcript
        lines = []
        lines.append(f"DISPATCH LOG - Incident #{iid}")
        lines.append(f"Date: {inc['incident_date']}")
        lines.append(f"Time: {inc['incident_time']}")
        lines.append(f"Type: {inc['incident_type']}")
        lines.append(f"Severity: {inc['severity']}")
        lines.append(f"Location: {inc['location']}")
        lines.append(f"Dispatched Units: {', '.join(dispatched_names)}")
        lines.append("---")
        for ts, speaker, msg in all_messages:
            lines.append(f"[{ts.strftime('%H:%M:%S')}] {speaker}: {msg}")
        lines.append("--- END OF LOG ---")

        filename = f"dispatch_transcript_{iid}.txt"
        transcripts.append((filename, "\n".join(lines), violation_map))

    # Reset seeds back
    np.random.seed(SEED + 2000)

    return transcripts


# ── Workspace File Writers ────────────────────────────────────────────────────

def write_audit_policy(workspace):
    policy = {
        "audit_date": AUDIT_DATE.strftime("%Y-%m-%d"),
        "thresholds": {
            "response_time_minutes": 8,
            "cert_expiry_warning_days": 90,
            "min_outcome_rating": 3,
            "min_equipment_condition": 4,
        },
        "scoring": {
            "retraining_factors": [
                "slow_response",
                "certification_deficiency",
                "poor_outcome",
                "protocol_violation",
            ],
            "reequip_factors": [
                "overdue_maintenance",
                "poor_equipment_condition",
            ],
        },
        "protocol_violation_keywords": VIOLATION_KEYWORDS,
        "violation_attribution_rule": (
            "A protocol violation is attributed to a unit when the unit's identifier "
            "(its short name, e.g. E-5, L-12) appears on the same line as a violation keyword. "
            "Each such co-occurrence counts as one violation for that unit."
        ),
    }
    path = os.path.join(workspace, "audit_policy.yaml")
    with open(path, "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def write_certification_requirements(workspace):
    path = os.path.join(workspace, "certification_requirements.json")
    with open(path, "w") as f:
        json.dump(CERT_REQUIREMENTS, f, indent=2)


def write_scoring_matrix(workspace):
    path = os.path.join(workspace, "scoring_matrix.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["deficiency_type", "penalty_points", "category"])
        for dtype, info in SCORING_MATRIX.items():
            writer.writerow([dtype, info["penalty"], info["category"]])


# ── Database Writer ───────────────────────────────────────────────────────────

def write_database(db_path, units, personnel, equipment, incidents, dispatches, maintenance, outcomes):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS units (
        unit_id TEXT PRIMARY KEY,
        unit_name TEXT NOT NULL,
        station TEXT NOT NULL,
        unit_type TEXT NOT NULL,
        active_since TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS personnel (
        person_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        unit_id TEXT NOT NULL,
        role TEXT NOT NULL,
        certification_level TEXT NOT NULL,
        cert_expiry_date TEXT NOT NULL,
        years_experience INTEGER NOT NULL,
        FOREIGN KEY (unit_id) REFERENCES units(unit_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS equipment (
        equipment_id TEXT PRIMARY KEY,
        unit_id TEXT NOT NULL,
        equipment_type TEXT NOT NULL,
        serial_number TEXT NOT NULL,
        acquisition_date TEXT NOT NULL,
        condition_rating INTEGER NOT NULL,
        FOREIGN KEY (unit_id) REFERENCES units(unit_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS incidents (
        incident_id TEXT PRIMARY KEY,
        incident_date TEXT NOT NULL,
        incident_time TEXT NOT NULL,
        incident_type TEXT NOT NULL,
        severity INTEGER NOT NULL,
        location TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS dispatches (
        dispatch_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        unit_id TEXT NOT NULL,
        dispatch_time TEXT NOT NULL,
        arrival_time TEXT NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (unit_id) REFERENCES units(unit_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS maintenance_logs (
        log_id TEXT PRIMARY KEY,
        equipment_id TEXT NOT NULL,
        maintenance_date TEXT NOT NULL,
        maintenance_type TEXT NOT NULL,
        result TEXT NOT NULL,
        technician TEXT NOT NULL,
        next_due_date TEXT NOT NULL,
        FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS incident_outcomes (
        outcome_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        outcome_rating INTEGER NOT NULL,
        civilian_injuries INTEGER NOT NULL,
        property_damage_k REAL NOT NULL,
        after_action_notes TEXT,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
    )""")

    # Insert data
    for u in units:
        c.execute("INSERT INTO units VALUES (?,?,?,?,?)",
                  (u["unit_id"], u["unit_name"], u["station"], u["unit_type"], u["active_since"]))

    for p in personnel:
        c.execute("INSERT INTO personnel VALUES (?,?,?,?,?,?,?)",
                  (p["person_id"], p["name"], p["unit_id"], p["role"],
                   p["certification_level"], p["cert_expiry_date"], p["years_experience"]))

    for e in equipment:
        c.execute("INSERT INTO equipment VALUES (?,?,?,?,?,?)",
                  (e["equipment_id"], e["unit_id"], e["equipment_type"],
                   e["serial_number"], e["acquisition_date"], e["condition_rating"]))

    for inc in incidents:
        c.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?)",
                  (inc["incident_id"], inc["incident_date"], inc["incident_time"],
                   inc["incident_type"], inc["severity"], inc["location"], inc["duration_minutes"]))

    for d in dispatches:
        c.execute("INSERT INTO dispatches VALUES (?,?,?,?,?)",
                  (d["dispatch_id"], d["incident_id"], d["unit_id"],
                   d["dispatch_time"], d["arrival_time"]))

    for m in maintenance:
        c.execute("INSERT INTO maintenance_logs VALUES (?,?,?,?,?,?,?)",
                  (m["log_id"], m["equipment_id"], m["maintenance_date"],
                   m["maintenance_type"], m["result"], m["technician"], m["next_due_date"]))

    for o in outcomes:
        c.execute("INSERT INTO incident_outcomes VALUES (?,?,?,?,?,?)",
                  (o["outcome_id"], o["incident_id"], o["outcome_rating"],
                   o["civilian_injuries"], o["property_damage_k"], o["after_action_notes"]))

    conn.commit()
    conn.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main(db_path, workspace):
    np.random.seed(SEED)
    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    os.makedirs(workspace, exist_ok=True)

    n_units = SCALE["rows_per_table"]
    n_personnel = max(SCALE["rows_per_table"], n_units * 3)
    n_equipment = max(SCALE["rows_per_table"], n_units * 2)
    n_incidents = max(SCALE["rows_per_table"], n_units * 2)
    n_maintenance = max(SCALE["rows_per_table"], n_equipment)
    n_transcript_files = SCALE["num_workspace_files"]

    # Generate data
    units = generate_units(n_units, fake)
    personnel = generate_personnel(units, n_personnel, fake)
    equipment = generate_equipment(units, n_equipment, fake)
    incidents = generate_incidents(n_incidents, fake)
    dispatches = generate_dispatches(incidents, units)
    maintenance = generate_maintenance_logs(equipment, n_maintenance, fake)
    outcomes = generate_incident_outcomes(incidents, fake)

    # Write database
    if os.path.exists(db_path):
        os.remove(db_path)
    write_database(db_path, units, personnel, equipment, incidents, dispatches, maintenance, outcomes)

    # Write fixed workspace files
    write_audit_policy(workspace)
    write_certification_requirements(workspace)
    write_scoring_matrix(workspace)

    # Generate and write transcript files
    transcripts = generate_transcripts(incidents, dispatches, units, n_transcript_files)
    for filename, content, _ in transcripts:
        path = os.path.join(workspace, filename)
        with open(path, "w") as f:
            f.write(content)

    print(f"Database written to {db_path}")
    print(f"Workspace files written to {workspace}/")
    print(f"  - Units: {len(units)}")
    print(f"  - Personnel: {len(personnel)}")
    print(f"  - Equipment: {len(equipment)}")
    print(f"  - Incidents: {len(incidents)}")
    print(f"  - Dispatches: {len(dispatches)}")
    print(f"  - Maintenance logs: {len(maintenance)}")
    print(f"  - Incident outcomes: {len(outcomes)}")
    print(f"  - Transcript files: {len(transcripts)}")
    print(f"  - Fixed config files: 3")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
