"""
Data generation script for labor law compliance task.
Generates employee time-clock punches, union contract break rules,
machine energy usage logs, and training schedule data.
"""

import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 50,       # v0 base; v1=2x, v2=4x, v3=8x
    "num_workspace_files": 8,   # v0 base; v1=+N, v2=+2N, v3=+3N
}

# ── Constants ────────────────────────────────────────────────────────────────
SEED = 42
DEPARTMENTS = ["Assembly", "Welding", "Packaging", "QualityControl", "Maintenance"]
UNION_CODES = ["UAW-Local-101", "IBEW-Local-202", "USW-Local-303"]
SHIFT_TYPES = ["morning", "afternoon", "night"]
SKILLS = [
    "forklift_operation", "crane_operation", "hazmat_handling",
    "electrical_safety", "fire_safety", "first_aid",
    "lockout_tagout", "confined_space",
]
MACHINES = [
    "CNC-01", "CNC-02", "CNC-03",
    "WELD-01", "WELD-02",
    "PRESS-01", "PRESS-02",
    "PACK-01", "PACK-02",
    "CONV-01", "CONV-02",
    "LATHE-01",
]
WEEK_START = datetime(2025, 3, 10)  # Monday
WEEK_END = datetime(2025, 3, 16)    # Sunday inclusive

MACHINE_DEPT = {
    "CNC-01": "Assembly", "CNC-02": "Assembly", "CNC-03": "Assembly",
    "WELD-01": "Welding", "WELD-02": "Welding",
    "PRESS-01": "Assembly", "PRESS-02": "Assembly",
    "PACK-01": "Packaging", "PACK-02": "Packaging",
    "CONV-01": "Packaging", "CONV-02": "Packaging",
    "LATHE-01": "Maintenance",
}

UNION_BREAK_RULES = {
    "UAW-Local-101": {
        "meal_break_minutes": 30,
        "meal_break_after_hours": 5.0,
        "rest_break_minutes": 15,
        "rest_break_interval_hours": 3.0,
        "max_shift_hours": 10.0,
    },
    "IBEW-Local-202": {
        "meal_break_minutes": 45,
        "meal_break_after_hours": 4.0,
        "rest_break_minutes": 10,
        "rest_break_interval_hours": 2.5,
        "max_shift_hours": 9.0,
    },
    "USW-Local-303": {
        "meal_break_minutes": 30,
        "meal_break_after_hours": 4.5,
        "rest_break_minutes": 15,
        "rest_break_interval_hours": 3.5,
        "max_shift_hours": 10.0,
    },
}

OVERTIME_RULES = {
    "daily_max_hours": 10,
    "weekly_max_hours": 45,
    "weekend_flag_threshold_hours": 6,
}

ENERGY_THRESHOLDS = {
    "CNC": {"max_kwh_per_hour": 18.0, "idle_kwh_per_hour": 2.0},
    "WELD": {"max_kwh_per_hour": 25.0, "idle_kwh_per_hour": 3.0},
    "PRESS": {"max_kwh_per_hour": 30.0, "idle_kwh_per_hour": 4.0},
    "PACK": {"max_kwh_per_hour": 12.0, "idle_kwh_per_hour": 1.5},
    "CONV": {"max_kwh_per_hour": 8.0, "idle_kwh_per_hour": 1.0},
    "LATHE": {"max_kwh_per_hour": 15.0, "idle_kwh_per_hour": 2.5},
}

TRAINING_REQUIREMENTS = {
    "Assembly": ["forklift_operation", "lockout_tagout", "fire_safety"],
    "Welding": ["fire_safety", "first_aid", "hazmat_handling"],
    "Packaging": ["forklift_operation", "fire_safety", "confined_space"],
    "QualityControl": ["electrical_safety", "first_aid"],
    "Maintenance": ["lockout_tagout", "electrical_safety", "confined_space", "hazmat_handling"],
}

SEVERITY_CONFIG = {
    "violation_severity": {
        "break_meal_missing": {"level": "critical", "points": 10},
        "break_meal_short": {"level": "major", "points": 7},
        "break_rest_missing": {"level": "minor", "points": 3},
        "overtime_daily": {"level": "major", "points": 8},
        "overtime_weekly": {"level": "critical", "points": 10},
        "training_expired": {"level": "critical", "points": 10},
        "energy_exceeded": {"level": "major", "points": 6},
        "weekend_long_shift": {"level": "minor", "points": 4},
    }
}


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS employees (
            employee_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            union_code TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS time_punches (
            punch_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            punch_date TEXT NOT NULL,
            clock_in TEXT NOT NULL,
            clock_out TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        );
        CREATE TABLE IF NOT EXISTS break_records (
            break_id TEXT PRIMARY KEY,
            punch_id TEXT NOT NULL,
            employee_id TEXT NOT NULL,
            break_type TEXT NOT NULL,
            break_start TEXT NOT NULL,
            break_end TEXT NOT NULL,
            FOREIGN KEY (punch_id) REFERENCES time_punches(punch_id),
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        );
        CREATE TABLE IF NOT EXISTS training_records (
            record_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            completed_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        );
    """)


def generate_employees(rng, fake, n):
    employees = []
    for i in range(n):
        emp_id = f"EMP-{i+1:04d}"
        name = fake.name()
        dept = rng.choice(DEPARTMENTS)
        union = rng.choice(UNION_CODES)
        hire_date = fake.date_between(
            start_date=datetime(2015, 1, 1),
            end_date=datetime(2024, 6, 1),
        ).isoformat()
        employees.append((emp_id, name, dept, union, hire_date, 1))
    return employees


def generate_time_punches(rng, employees):
    punches = []
    punch_counter = 0
    days_in_week = [(WEEK_START + timedelta(days=d)).date() for d in range(7)]

    for emp_id, _, dept, union_code, _, _ in employees:
        n_days = rng.randint(4, 6)
        work_days = sorted(rng.sample(range(7), n_days))

        for day_idx in work_days:
            punch_counter += 1
            p_id = f"PUNCH-{punch_counter:06d}"
            p_date = days_in_week[day_idx].isoformat()
            shift = rng.choice(SHIFT_TYPES)

            if shift == "morning":
                start_hour = rng.choice([5, 6, 7])
                duration = rng.uniform(7.0, 11.0)
            elif shift == "afternoon":
                start_hour = rng.choice([13, 14, 15])
                duration = rng.uniform(6.5, 10.5)
            else:
                start_hour = rng.choice([21, 22, 23])
                duration = rng.uniform(7.0, 10.0)

            start_min = rng.randint(0, 59)
            clock_in = f"{start_hour:02d}:{start_min:02d}"
            end_total_min = start_hour * 60 + start_min + int(duration * 60)
            end_hour = (end_total_min // 60) % 24
            end_min = end_total_min % 60
            clock_out = f"{end_hour:02d}:{end_min:02d}"

            punches.append((p_id, emp_id, p_date, clock_in, clock_out, shift))

    return punches


def generate_break_records(rng, punches, employees_dict):
    breaks = []
    break_counter = 0

    for p_id, emp_id, p_date, clock_in, clock_out, shift_type in punches:
        union_code = employees_dict[emp_id]["union_code"]
        rules = UNION_BREAK_RULES[union_code]

        in_h, in_m = map(int, clock_in.split(":"))
        out_h, out_m = map(int, clock_out.split(":"))
        start_min = in_h * 60 + in_m
        end_min = out_h * 60 + out_m
        if end_min <= start_min:
            end_min += 24 * 60
        shift_hours = (end_min - start_min) / 60.0

        create_violation = rng.random() < 0.15

        # Meal break
        if shift_hours >= rules["meal_break_after_hours"]:
            if create_violation:
                if rng.random() < 0.5:
                    # Short meal break
                    break_counter += 1
                    b_id = f"BRK-{break_counter:06d}"
                    meal_start = start_min + int(rules["meal_break_after_hours"] * 60)
                    actual_dur = rng.randint(10, max(11, rules["meal_break_minutes"] - 5))
                    meal_end = meal_start + actual_dur
                    bs = f"{(meal_start // 60) % 24:02d}:{meal_start % 60:02d}"
                    be = f"{(meal_end // 60) % 24:02d}:{meal_end % 60:02d}"
                    breaks.append((b_id, p_id, emp_id, "meal", bs, be))
                # else: no meal break record at all => missing meal
            else:
                break_counter += 1
                b_id = f"BRK-{break_counter:06d}"
                meal_start = start_min + int(rules["meal_break_after_hours"] * 60) + rng.randint(0, 30)
                meal_end = meal_start + rules["meal_break_minutes"] + rng.randint(0, 10)
                bs = f"{(meal_start // 60) % 24:02d}:{meal_start % 60:02d}"
                be = f"{(meal_end // 60) % 24:02d}:{meal_end % 60:02d}"
                breaks.append((b_id, p_id, emp_id, "meal", bs, be))

        # Rest breaks
        n_rest_expected = max(0, int(shift_hours / rules["rest_break_interval_hours"]) - 1)
        if create_violation and n_rest_expected > 0:
            n_rest_actual = max(0, n_rest_expected - rng.randint(1, n_rest_expected))
        else:
            n_rest_actual = n_rest_expected

        for r in range(n_rest_actual):
            break_counter += 1
            b_id = f"BRK-{break_counter:06d}"
            rest_start = start_min + int((r + 1) * rules["rest_break_interval_hours"] * 60) + rng.randint(-10, 10)
            rest_end = rest_start + rules["rest_break_minutes"] + rng.randint(-2, 5)
            if rest_end > end_min or rest_start < start_min:
                break_counter -= 1
                continue
            bs = f"{(rest_start // 60) % 24:02d}:{rest_start % 60:02d}"
            be = f"{(rest_end // 60) % 24:02d}:{rest_end % 60:02d}"
            breaks.append((b_id, p_id, emp_id, "rest", bs, be))

    return breaks


def generate_training_records(rng, fake, employees):
    records = []
    rec_counter = 0

    for emp_id, _, dept, _, _, _ in employees:
        required = TRAINING_REQUIREMENTS.get(dept, [])
        extras = rng.sample(
            [s for s in SKILLS if s not in required],
            k=min(2, len([s for s in SKILLS if s not in required]))
        )
        all_skills = list(required) + extras

        for skill in all_skills:
            rec_counter += 1
            r_id = f"TRAIN-{rec_counter:06d}"

            if rng.random() < 0.12:
                completed = fake.date_between(
                    start_date=datetime(2023, 1, 1),
                    end_date=datetime(2024, 3, 1),
                )
                expiry = completed + timedelta(days=rng.randint(180, 365))
                if expiry >= WEEK_START.date():
                    expiry = WEEK_START.date() - timedelta(days=rng.randint(1, 60))
            else:
                completed = fake.date_between(
                    start_date=datetime(2024, 6, 1),
                    end_date=datetime(2025, 2, 28),
                )
                expiry = completed + timedelta(days=rng.randint(365, 730))

            records.append((r_id, emp_id, skill, completed.isoformat(), expiry.isoformat()))

    return records


def generate_machine_energy_data(rng, punches, employees_dict):
    entries = []
    entry_id = 0

    for p_id, emp_id, p_date, clock_in, clock_out, shift_type in punches:
        dept = employees_dict[emp_id]["department"]
        dept_machines = [m for m, d in MACHINE_DEPT.items() if d == dept]
        if not dept_machines:
            continue

        n_machines = min(len(dept_machines), rng.randint(1, 2))
        operated = rng.sample(dept_machines, n_machines)

        in_h, in_m = map(int, clock_in.split(":"))
        out_h, out_m = map(int, clock_out.split(":"))
        start_min = in_h * 60 + in_m
        end_min = out_h * 60 + out_m
        if end_min <= start_min:
            end_min += 24 * 60

        for machine_id in operated:
            entry_id += 1
            prefix = machine_id.split("-")[0]
            threshold = ENERGY_THRESHOLDS[prefix]

            op_duration_min = rng.randint(60, min(240, end_min - start_min))
            op_start = start_min + rng.randint(0, max(0, end_min - start_min - op_duration_min))
            op_end = op_start + op_duration_min
            op_hours = op_duration_min / 60.0

            if rng.random() < 0.10:
                kwh = threshold["max_kwh_per_hour"] * op_hours * rng.uniform(1.05, 1.4)
            else:
                kwh = threshold["max_kwh_per_hour"] * op_hours * rng.uniform(0.4, 0.95)

            op_start_str = f"{(op_start // 60) % 24:02d}:{op_start % 60:02d}"
            op_end_str = f"{(op_end // 60) % 24:02d}:{op_end % 60:02d}"

            entries.append({
                "entry_id": f"ELOG-{entry_id:06d}",
                "machine_id": machine_id,
                "employee_id": emp_id,
                "date": p_date,
                "operation_start": op_start_str,
                "operation_end": op_end_str,
                "duration_hours": round(op_hours, 2),
                "energy_kwh": round(kwh, 2),
            })

    return entries


def write_workspace_files(workspace, rng, fake, employees, punches,
                          employees_dict, energy_entries, training_records):
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]

    # ─── Fixed policy files ──────────────────────────────────────────────

    with open(os.path.join(workspace, "union_contract_rules.json"), "w") as f:
        json.dump(UNION_BREAK_RULES, f, indent=2)

    with open(os.path.join(workspace, "overtime_policy.json"), "w") as f:
        json.dump(OVERTIME_RULES, f, indent=2)

    with open(os.path.join(workspace, "energy_thresholds.yaml"), "w") as f:
        yaml.dump(ENERGY_THRESHOLDS, f, default_flow_style=False)

    rows_tr = []
    for dept, skills in TRAINING_REQUIREMENTS.items():
        for skill in skills:
            rows_tr.append({"department": dept, "required_skill": skill,
                            "certification_mandatory": "yes"})
    pd.DataFrame(rows_tr).to_csv(
        os.path.join(workspace, "training_requirements.csv"), index=False
    )

    with open(os.path.join(workspace, "severity_config.yaml"), "w") as f:
        yaml.dump(SEVERITY_CONFIG, f, default_flow_style=False)

    # ─── Scalable data files ─────────────────────────────────────────────

    n_energy_files = max(1, int(n_files * 0.6))
    n_shift_notes = n_files - n_energy_files

    # Energy log CSVs
    if energy_entries:
        sorted_entries = sorted(energy_entries, key=lambda x: (x["date"], x["machine_id"]))
        chunk_size = max(1, len(sorted_entries) // n_energy_files)
        for i in range(n_energy_files):
            start_idx = i * chunk_size
            if i == n_energy_files - 1:
                chunk = sorted_entries[start_idx:]
            else:
                chunk = sorted_entries[start_idx:start_idx + chunk_size]
            if not chunk:
                chunk = [sorted_entries[-1]]
            df = pd.DataFrame(chunk)
            df.to_csv(os.path.join(workspace, f"machine_energy_log_{i+1:03d}.csv"), index=False)

    # Shift supervisor notes (Markdown)
    days_of_week = [(WEEK_START + timedelta(days=d)) for d in range(7)]

    for i in range(n_shift_notes):
        day = days_of_week[i % 7]
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        day_str = day.strftime("%Y-%m-%d")
        day_name = day.strftime("%A")

        dept_emps = [(eid, e) for eid, e in employees_dict.items()
                     if e["department"] == dept]
        dept_machines = [m for m, d in MACHINE_DEPT.items() if d == dept]

        lines = [
            f"# Shift Supervisor Notes - {dept} - {day_name} {day_str}",
            "",
            f"Supervisor on duty: {fake.name()}",
            f"Report filed: {day_str} end of day",
            "",
        ]

        if dept_machines:
            lines += ["## Machine Status", "",
                       "| Machine ID | Status | Notes |",
                       "|-----------|--------|-------|"]
            for m in dept_machines:
                status = rng.choice(["operational"] * 3 + ["maintenance_required"])
                note = rng.choice([
                    "Running within normal parameters",
                    "Minor vibration detected",
                    "Scheduled maintenance upcoming",
                    "Calibration due next week",
                    "Operating normally",
                ])
                lines.append(f"| {m} | {status} | {note} |")
            lines.append("")

        lines += ["## Employee Observations", ""]
        if dept_emps:
            n_obs = min(len(dept_emps), rng.randint(2, 5))
            observed = rng.sample(dept_emps, n_obs)
            for emp_id, emp_info in observed:
                obs = rng.choice([
                    "arrived on time for shift",
                    "completed safety check before machine operation",
                    "reported minor equipment issue",
                    "requested schedule adjustment",
                    "participated in safety drill",
                    "noted working through part of break period",
                    "machine area left clean at end of shift",
                ])
                lines.append(f"- **{emp_info['name']}** ({emp_id}): {obs}")
            lines.append("")

        if rng.random() < 0.4:
            lines += [
                "## Safety Incidents", "",
                f"- Near-miss reported at {rng.randint(8,17)}:{rng.randint(0,59):02d}: "
                f"{rng.choice(['Forklift clearance issue', 'Wet floor near station', 'PPE compliance check', 'Tool left in walkway'])}",
                "",
            ]

        lines += [
            "## General Notes", "",
            rng.choice([
                "Overall smooth operations today. All safety protocols followed.",
                "Production targets met. Minor scheduling adjustments made.",
                "Equipment running within specifications. Break schedule adhered to by most staff.",
                "Busy shift with high output. Some employees extended shifts for urgent orders.",
                "Standard operations. Maintenance team completed scheduled checks.",
            ]),
            "",
        ]

        with open(os.path.join(workspace, f"shift_notes_{dept.lower()}_{day_str}.md"), "w") as f:
            f.write("\n".join(lines))


def main(db_path, workspace):
    random.seed(SEED)
    np.random.seed(SEED)
    rng = random.Random(SEED)
    fake = Faker()
    Faker.seed(SEED)

    n = SCALE["rows_per_table"]

    employees = generate_employees(rng, fake, n)
    employees_dict = {
        e[0]: {"name": e[1], "department": e[2], "union_code": e[3],
               "hire_date": e[4], "is_active": e[5]}
        for e in employees
    }

    punches = generate_time_punches(rng, employees)
    break_records = generate_break_records(rng, punches, employees_dict)
    training_records = generate_training_records(rng, fake, employees)
    energy_entries = generate_machine_energy_data(rng, punches, employees_dict)

    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    create_tables(conn)

    conn.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?)", employees)
    conn.executemany("INSERT INTO time_punches VALUES (?,?,?,?,?,?)", punches)
    conn.executemany("INSERT INTO break_records VALUES (?,?,?,?,?,?)", break_records)
    conn.executemany("INSERT INTO training_records VALUES (?,?,?,?,?)", training_records)

    conn.commit()
    conn.close()

    write_workspace_files(workspace, rng, fake, employees, punches,
                          employees_dict, energy_entries, training_records)

    print(f"Database: {db_path}")
    print(f"  employees: {len(employees)}")
    print(f"  time_punches: {len(punches)}")
    print(f"  break_records: {len(break_records)}")
    print(f"  training_records: {len(training_records)}")
    wfiles = sorted(os.listdir(workspace))
    print(f"Workspace: {len(wfiles)} files in {workspace}/")
    for wf in wfiles:
        print(f"  {wf}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
