"""
data.py - Shift Assignment Optimization Task Data Generator

Generates database tables and workspace files for a manufacturing
shift assignment optimization task.
"""

import argparse
import os
import json
import csv
import sqlite3
import random
import math
import datetime
import numpy as np
from faker import Faker

SCALE = {
    "rows_per_table": 30,
    "num_workspace_files": 8,
}

# ── Constants ──────────────────────────────────────────────────────────────────
PLANNING_DATE = "2025-10-15"
PLANNING_DATE_OBJ = datetime.date(2025, 10, 15)
MACHINE_TYPES = ["CNC", "Assembly", "Welding", "Packaging", "Inspection", "Painting"]
SHIFTS = ["Morning", "Afternoon", "Night"]
SKILL_TIERS = ["junior", "mid", "senior"]
PRIORITY_LEVELS = ["critical", "high", "medium", "low"]


def init_seeds():
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)


def get_num_lines(rows):
    return max(6, rows // 5)


# ── Table generators ──────────────────────────────────────────────────────────

def generate_operators(n):
    fake = Faker()
    Faker.seed(42)
    operators = []
    used_names = set()
    for i in range(n):
        op_id = f"O{i+1:03d}"
        while True:
            name = fake.name()
            if name not in used_names:
                used_names.add(name)
                break
        skill_tier = random.choices(SKILL_TIERS, weights=[0.4, 0.35, 0.25])[0]
        dept = f"Dept-{(i % 4) + 1}"
        hire_date = fake.date_between(
            start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=3650),
            end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=180))
        phone = fake.phone_number()
        operators.append((op_id, name, skill_tier, dept, str(hire_date), phone))
    return operators


def generate_machines(n):
    num_lines = get_num_lines(n)
    fake = Faker()
    Faker.seed(42)
    machines = []
    for i in range(n):
        m_id = f"M{i+1:03d}"
        m_type = MACHINE_TYPES[i % len(MACHINE_TYPES)]
        m_name = f"{m_type}-Unit-{i+1}"
        line_idx = i % num_lines
        line = f"L{line_idx + 1:02d}"
        throughput = round(50 + (i * 7 + 13) % 151, 1)
        install_date = fake.date_between(
            start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=1825),
            end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=30))
        machines.append((m_id, m_name, line, m_type, throughput, str(install_date)))
    return machines


def generate_certifications(operators, machines, scale_rows):
    """Each operator certified on 2-5 machines, total >= scale_rows."""
    certs = []
    cert_id = 1
    fake = Faker()
    Faker.seed(42)
    machine_ids = [m[0] for m in machines]

    for op_id, _, skill_tier, _, _, _ in operators:
        # senior → more certs
        if skill_tier == "senior":
            num_certs = random.randint(3, min(6, len(machine_ids)))
        elif skill_tier == "mid":
            num_certs = random.randint(2, min(4, len(machine_ids)))
        else:
            num_certs = random.randint(1, min(3, len(machine_ids)))

        chosen_machines = random.sample(machine_ids, num_certs)
        for mid in chosen_machines:
            if skill_tier == "senior":
                cert_level = random.choice([2, 3, 3])
            elif skill_tier == "mid":
                cert_level = random.choice([1, 2, 2])
            else:
                cert_level = random.choice([1, 1, 2])
            cert_date = fake.date_between(
                start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=1095),
                end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=60))
            # ~10% expired
            if random.random() < 0.1:
                expiry_date = fake.date_between(
                    start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=180),
                    end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=1))
            else:
                expiry_date = fake.date_between(
                    start_date=PLANNING_DATE_OBJ + datetime.timedelta(days=30),
                    end_date=PLANNING_DATE_OBJ + datetime.timedelta(days=730))
            certs.append((cert_id, op_id, mid, cert_level,
                          str(cert_date), str(expiry_date)))
            cert_id += 1

    # Pad if below scale_rows
    while len(certs) < scale_rows:
        op_id = random.choice(operators)[0]
        mid = random.choice(machine_ids)
        # avoid duplicates
        existing = {(c[1], c[2]) for c in certs}
        if (op_id, mid) in existing:
            continue
        cert_level = random.choice([1, 2])
        cert_date = fake.date_between(
            start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=1095),
            end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=60))
        expiry_date = fake.date_between(
            start_date=PLANNING_DATE_OBJ + datetime.timedelta(days=30),
            end_date=PLANNING_DATE_OBJ + datetime.timedelta(days=730))
        certs.append((cert_id, op_id, mid, cert_level,
                      str(cert_date), str(expiry_date)))
        cert_id += 1

    return certs


def generate_maintenance_logs(machines, scale_rows):
    """Generate maintenance events. ~20% of machines have unresolved issues."""
    fake = Faker()
    Faker.seed(42)
    logs = []
    log_id = 1
    machine_ids = [m[0] for m in machines]
    n_machines = len(machine_ids)

    # Decide which machines are currently down (unresolved, severity >= 3)
    n_down = max(2, n_machines // 5)
    down_machines = set(random.sample(machine_ids, n_down))

    event_types = ["routine_check", "breakdown", "scheduled_maintenance",
                   "repair_completed", "part_replacement"]

    for mid in machine_ids:
        # 1-3 historical resolved events per machine
        n_events = random.randint(1, 3)
        for _ in range(n_events):
            log_date = fake.date_between(
                start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=60),
                end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=2))
            etype = random.choice(event_types)
            severity = random.randint(1, 5)
            downtime = round(random.uniform(0.5, 24.0), 1)
            logs.append((log_id, mid, str(log_date), etype, severity,
                          downtime, 1))  # resolved=1
            log_id += 1

        # If machine is down, add an unresolved event near planning date
        if mid in down_machines:
            log_date = fake.date_between(
                start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=3),
                end_date=PLANNING_DATE_OBJ)
            etype = random.choice(["breakdown", "scheduled_maintenance"])
            severity = random.randint(3, 5)
            downtime = round(random.uniform(4.0, 48.0), 1)
            logs.append((log_id, mid, str(log_date), etype, severity,
                          downtime, 0))  # resolved=0
            log_id += 1

    # Pad if below scale_rows
    while len(logs) < scale_rows:
        mid = random.choice(machine_ids)
        log_date = fake.date_between(
            start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=90),
            end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=5))
        etype = random.choice(event_types)
        severity = random.randint(1, 3)
        downtime = round(random.uniform(0.5, 8.0), 1)
        logs.append((log_id, mid, str(log_date), etype, severity,
                      downtime, 1))
        log_id += 1

    return logs, down_machines


def generate_absenteeism(operators, scale_rows):
    """Generate absence records over past 90 days."""
    fake = Faker()
    Faker.seed(42)
    records = []
    rec_id = 1
    reasons = ["sick_leave", "personal", "no_show", "family_emergency", "vacation"]

    # ~20% of operators have high absence rate (6-12 absences in 90 days)
    n_ops = len(operators)
    n_high = max(2, n_ops // 5)
    high_absence_ops = set(op[0] for op in random.sample(operators, n_high))

    for op_id, _, _, _, _, _ in operators:
        if op_id in high_absence_ops:
            n_absences = random.randint(6, 12)
        else:
            n_absences = random.randint(0, 3)

        absence_dates = set()
        for _ in range(n_absences):
            d = fake.date_between(
                start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=90),
                end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=1))
            absence_dates.add(str(d))

        for d in sorted(absence_dates):
            reason = random.choice(reasons)
            hours = random.choice([4, 8])
            records.append((rec_id, op_id, d, 1, reason, hours))
            rec_id += 1

    # Pad if below scale_rows
    while len(records) < scale_rows:
        op_id = random.choice(operators)[0]
        d = str(fake.date_between(
            start_date=PLANNING_DATE_OBJ - datetime.timedelta(days=90),
            end_date=PLANNING_DATE_OBJ - datetime.timedelta(days=1)))
        reason = random.choice(reasons)
        records.append((rec_id, op_id, d, 1, reason, 8))
        rec_id += 1

    return records


# ── Database ──────────────────────────────────────────────────────────────────

def create_database(db_path, operators, machines, certifications,
                    maintenance_logs, absenteeism_records):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS operators (
        operator_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        skill_tier TEXT NOT NULL,
        department TEXT NOT NULL,
        hire_date TEXT NOT NULL,
        phone TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS machines (
        machine_id TEXT PRIMARY KEY,
        machine_name TEXT NOT NULL,
        production_line TEXT NOT NULL,
        machine_type TEXT NOT NULL,
        nominal_throughput REAL NOT NULL,
        install_date TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS certifications (
        cert_id INTEGER PRIMARY KEY,
        operator_id TEXT NOT NULL,
        machine_id TEXT NOT NULL,
        cert_level INTEGER NOT NULL,
        cert_date TEXT NOT NULL,
        expiry_date TEXT NOT NULL,
        FOREIGN KEY (operator_id) REFERENCES operators(operator_id),
        FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS maintenance_logs (
        log_id INTEGER PRIMARY KEY,
        machine_id TEXT NOT NULL,
        log_date TEXT NOT NULL,
        event_type TEXT NOT NULL,
        severity INTEGER NOT NULL,
        estimated_downtime_hours REAL NOT NULL,
        resolved INTEGER NOT NULL,
        FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS absenteeism_records (
        record_id INTEGER PRIMARY KEY,
        operator_id TEXT NOT NULL,
        absence_date TEXT NOT NULL,
        was_absent INTEGER NOT NULL,
        reason TEXT NOT NULL,
        hours_missed INTEGER NOT NULL,
        FOREIGN KEY (operator_id) REFERENCES operators(operator_id)
    )""")

    c.executemany("INSERT INTO operators VALUES (?,?,?,?,?,?)", operators)
    c.executemany("INSERT INTO machines VALUES (?,?,?,?,?,?)", machines)
    c.executemany("INSERT INTO certifications VALUES (?,?,?,?,?,?)",
                  certifications)
    c.executemany("INSERT INTO maintenance_logs VALUES (?,?,?,?,?,?,?)",
                  maintenance_logs)
    c.executemany("INSERT INTO absenteeism_records VALUES (?,?,?,?,?,?)",
                  absenteeism_records)

    conn.commit()
    conn.close()


# ── Workspace ─────────────────────────────────────────────────────────────────

def create_workspace(workspace, machines, operators, down_machines):
    os.makedirs(workspace, exist_ok=True)

    num_lines = get_num_lines(SCALE["rows_per_table"])
    line_ids = [f"L{i+1:02d}" for i in range(num_lines)]

    # ── Fixed files ───────────────────────────────────────────────────────
    _write_staffing_rules(workspace)
    _write_shift_config(workspace)
    _write_staffing_methodology(workspace)

    # ── Scalable files ────────────────────────────────────────────────────
    num_target_files = SCALE["num_workspace_files"] // 2
    num_avail_files = SCALE["num_workspace_files"] - num_target_files

    _write_production_targets(workspace, line_ids, num_target_files)
    _write_operator_availability(workspace, operators, num_avail_files)


def _write_staffing_rules(workspace):
    rules = {
        "min_cert_level": 1,
        "high_priority_min_cert": 2,
        "max_absence_rate": 0.25,
        "maintenance_severity_threshold": 3,
        "max_machines_per_operator_per_shift": 1,
        "operator_ranking": {
            "primary": "cert_level_desc",
            "secondary": "absence_rate_asc",
            "tiebreaker": "operator_id_asc",
        },
        "priority_order": ["critical", "high", "medium", "low"],
    }
    path = os.path.join(workspace, "staffing_rules.yaml")
    with open(path, "w") as f:
        # Write YAML manually for determinism
        f.write("# Staffing Assignment Rules\n\n")
        f.write(f"min_cert_level: {rules['min_cert_level']}\n")
        f.write(f"high_priority_min_cert: {rules['high_priority_min_cert']}\n")
        f.write(f"max_absence_rate: {rules['max_absence_rate']}\n")
        f.write(f"maintenance_severity_threshold: {rules['maintenance_severity_threshold']}\n")
        f.write(f"max_machines_per_operator_per_shift: {rules['max_machines_per_operator_per_shift']}\n")
        f.write("\noperator_ranking:\n")
        f.write(f"  primary: {rules['operator_ranking']['primary']}\n")
        f.write(f"  secondary: {rules['operator_ranking']['secondary']}\n")
        f.write(f"  tiebreaker: {rules['operator_ranking']['tiebreaker']}\n")
        f.write("\npriority_order:\n")
        for p in rules["priority_order"]:
            f.write(f"  - {p}\n")


def _write_staffing_methodology(workspace):
    text = """# Daily Staffing Assignment Methodology

This document is the authoritative specification of how the daily staffing
plan must be constructed. It is read together with `staffing_rules.yaml`
(numeric thresholds and orderings) and `shift_config.json` (planning date
and shift order). Production target records supply each production line's
priority classification and per-shift throughput targets; operator
availability records state which operators are available for which shifts
on the planning date.

## Scope of the plan

A machine-shift slot must be staffed when, and only when, the machine's
production line has a production target entry for that shift. Lines without
a target entry for a particular shift are skipped for that shift.

## Machine availability

A machine is unavailable (down) on the planning date if it has at least one
unresolved maintenance event whose severity is greater than or equal to
`maintenance_severity_threshold`. Down machines must not be staffed and are
excluded from coverage totals.

## Operator eligibility for a machine-shift slot

An operator is an eligible candidate for a machine during a shift when all
of the following hold:

1. The operator holds a certification for that machine that has not
   expired: the certification's expiry date is on or after the planning
   date.
2. The certification level is at least `min_cert_level`; for machines on
   production lines whose priority is `critical` or `high`, the level must
   instead be at least `high_priority_min_cert`.
3. The operator is listed as available for that shift in the operator
   availability records for the planning date.
4. The operator's historical absence rate does not exceed
   `max_absence_rate`. The absence rate is the total number of recorded
   absences divided by 90, rounded to 4 decimal places.
5. The operator has not already been assigned to another machine during
   the same shift (`max_machines_per_operator_per_shift` is 1).

## Candidate ranking

Competing eligible candidates for the same machine are ranked by
certification level descending, then absence rate ascending, then operator
identifier ascending. The top-ranked candidate is assigned.

## Processing order

The assignment procedure is greedy and order-dependent — each assignment
removes the operator from the candidate pool for the remainder of that
shift — so the following order is mandatory:

1. Shifts are processed in the order given by `shift_order`.
2. Within a shift, production lines are processed sorted by priority
   according to `priority_order` (critical before high before medium
   before low); lines sharing the same priority are ordered by line
   identifier in ascending alphabetical order.
3. Within a line, operational machines are processed by machine identifier
   in ascending order.

If a slot has no eligible candidate, it is recorded as uncovered together
with the reason.

## Recording

Every assignment made must also be registered in the plant's central shift
roster system, one record per shift/machine/operator assignment, so that
the system of record reflects the final plan.
"""
    path = os.path.join(workspace, "staffing_methodology.md")
    with open(path, "w") as f:
        f.write(text)


def _write_shift_config(workspace):
    config = {
        "planning_date": PLANNING_DATE,
        "shifts": {
            "Morning": {"start": "06:00", "end": "14:00"},
            "Afternoon": {"start": "14:00", "end": "22:00"},
            "Night": {"start": "22:00", "end": "06:00"},
        },
        "shift_order": ["Morning", "Afternoon", "Night"],
    }
    path = os.path.join(workspace, "shift_config.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def _write_production_targets(workspace, line_ids, num_files):
    """Write production target CSV files.

    Each file covers a subset of lines.  Every line has one row per shift.
    """
    os.makedirs(os.path.join(workspace, "production_targets"), exist_ok=True)

    # Assign priorities deterministically
    priority_cycle = PRIORITY_LEVELS  # critical, high, medium, low
    line_priorities = {}
    for i, lid in enumerate(line_ids):
        line_priorities[lid] = priority_cycle[i % len(priority_cycle)]

    # Build all rows: (line_id, shift, target_units, priority)
    all_rows = []
    for lid in line_ids:
        base_target = 300 + (int(lid[1:]) * 47) % 400
        for si, shift in enumerate(SHIFTS):
            # morning highest, night lowest
            factor = [1.0, 0.85, 0.65][si]
            target = int(base_target * factor)
            all_rows.append((lid, shift, target, line_priorities[lid]))

    # Distribute across files
    rows_per_file = math.ceil(len(all_rows) / num_files)
    for fi in range(num_files):
        chunk = all_rows[fi * rows_per_file:(fi + 1) * rows_per_file]
        if not chunk:
            continue
        path = os.path.join(workspace, "production_targets",
                            f"targets_batch_{fi+1:03d}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["production_line", "shift", "target_units",
                             "priority"])
            writer.writerows(chunk)


def _write_operator_availability(workspace, operators, num_files):
    """Write operator availability JSON files.

    Each file covers a subset of operators.  Every operator is available
    for 1-2 shifts on the planning date.
    """
    os.makedirs(os.path.join(workspace, "operator_availability"), exist_ok=True)

    avail_list = []
    for i, (op_id, name, *_) in enumerate(operators):
        # Deterministic shift assignment
        primary_shift = SHIFTS[i % 3]
        if random.random() < 0.35:
            # Also available for an adjacent shift
            adj = SHIFTS[(i % 3 + 1) % 3]
            shifts = sorted(set([primary_shift, adj]),
                            key=lambda s: SHIFTS.index(s))
        else:
            shifts = [primary_shift]
        avail_list.append({
            "operator_id": op_id,
            "operator_name": name,
            "available_shifts": shifts,
        })

    # Distribute across files
    per_file = math.ceil(len(avail_list) / num_files)
    for fi in range(num_files):
        chunk = avail_list[fi * per_file:(fi + 1) * per_file]
        if not chunk:
            continue
        payload = {
            "planning_date": PLANNING_DATE,
            "operators": chunk,
        }
        path = os.path.join(workspace, "operator_availability",
                            f"availability_batch_{fi+1:03d}.json")
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    init_seeds()

    rows = SCALE["rows_per_table"]

    # Generate data
    operators = generate_operators(rows)
    machines = generate_machines(rows)
    certifications = generate_certifications(operators, machines, rows)
    maintenance_logs, down_machines = generate_maintenance_logs(machines, rows)
    absenteeism_records = generate_absenteeism(operators, rows)

    # Create database
    create_database(args.db_path, operators, machines, certifications,
                    maintenance_logs, absenteeism_records)

    # Create workspace
    create_workspace(args.workspace, machines, operators, down_machines)

    print(f"Database created at {args.db_path}")
    print(f"  operators:            {len(operators)}")
    print(f"  machines:             {len(machines)}")
    print(f"  certifications:       {len(certifications)}")
    print(f"  maintenance_logs:     {len(maintenance_logs)}")
    print(f"  absenteeism_records:  {len(absenteeism_records)}")
    print(f"Workspace created at {args.workspace}")
    n_target = SCALE['num_workspace_files'] // 2
    n_avail = SCALE['num_workspace_files'] - n_target
    print(f"  production target files:     {n_target}")
    print(f"  operator availability files: {n_avail}")
    print(f"  fixed config files:          3")


if __name__ == "__main__":
    import json  # ensure available at top-level scope
    main()
