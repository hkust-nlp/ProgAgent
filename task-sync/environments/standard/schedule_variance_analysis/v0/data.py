#!/usr/bin/env python3
"""Generate project schedule compliance monitoring data.

Creates a SQLite database with project task actuals, equipment telemetry,
labor timecards, material procurement, and weather delay logs.  Also generates
workspace files including the baseline Gantt chart, configuration/policy docs,
and daily inspection reports.
"""

import argparse
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 10,
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_START = datetime(2026, 1, 5)  # Monday
REPORTING_DATE = datetime(2026, 3, 13)  # Friday, week 10

PHASES = ["Foundation", "Structural", "MEP", "Finishing"]
PHASE_CODES = {
    "Foundation": "FND",
    "Structural": "STR",
    "MEP": "MEP",
    "Finishing": "FIN",
}

TASK_TEMPLATES = {
    "Foundation": [
        "Excavation", "Pile Driving", "Foundation Pour", "Waterproofing",
        "Backfill", "Grade Beam", "Footing Install", "Drainage System",
        "Shoring", "Compaction", "Survey Layout", "Dewatering",
        "Retaining Wall", "Slab on Grade", "Anchor Bolt Setting",
    ],
    "Structural": [
        "Steel Erection", "Column Install", "Beam Placement", "Floor Decking",
        "Roof Framing", "Welding Joints", "Concrete Pour", "Rebar Tying",
        "Shear Wall", "Bracing Install", "Stair Framing", "Elevator Shaft",
        "Canopy Structure", "Moment Frame", "Connection Plate",
    ],
    "MEP": [
        "Electrical Rough-in", "Plumbing Rough-in", "HVAC Ductwork",
        "Fire Suppression", "Low Voltage Wiring", "Pipe Fitting",
        "Panel Install", "Conduit Run", "Insulation Wrap", "Controls Setup",
        "BMS Wiring", "Sprinkler Head", "Chiller Pad", "Switchgear Mount",
        "Grounding System",
    ],
    "Finishing": [
        "Drywall Hang", "Painting", "Flooring Install", "Ceiling Tiles",
        "Trim Work", "Hardware Install", "Glazing", "Landscaping",
        "Final Grading", "Punch List", "Millwork", "Signage Install",
        "Carpet Lay", "Tile Setting", "Touch-up Coat",
    ],
}

EQUIPMENT_POOL = [
    ("EQ-001", "Excavator CAT 320", "Excavation"),
    ("EQ-002", "Tower Crane TC-50", "Lifting"),
    ("EQ-003", "Concrete Mixer CM-9", "Concrete"),
    ("EQ-004", "Bulldozer D6", "Earthwork"),
    ("EQ-005", "Forklift FL-3T", "Material Handling"),
    ("EQ-006", "Backhoe BH-430", "Excavation"),
    ("EQ-007", "Plate Compactor PC-20", "Compaction"),
    ("EQ-008", "Generator 100kVA", "Power"),
    ("EQ-009", "Welding Rig WR-400", "Welding"),
    ("EQ-010", "Boom Lift BL-60", "Access"),
    ("EQ-011", "Dump Truck DT-20", "Hauling"),
    ("EQ-012", "Scaffolding System SS-A", "Access"),
    ("EQ-013", "Concrete Pump CP-36", "Concrete"),
    ("EQ-014", "Roller Compactor RC-10", "Compaction"),
    ("EQ-015", "Telehandler TH-7", "Material Handling"),
]

WORKER_ROLES = [
    "Foreman", "Carpenter", "Electrician", "Plumber", "Ironworker",
    "Mason", "Laborer", "Heavy Operator", "Welder", "HVAC Tech",
    "Painter", "Roofer", "Pipefitter", "Inspector", "Rigger",
]

ROLE_HOURLY_RATES = {
    "Foreman": 65.0, "Carpenter": 48.0, "Electrician": 55.0,
    "Plumber": 52.0, "Ironworker": 58.0, "Mason": 50.0,
    "Laborer": 35.0, "Heavy Operator": 60.0, "Welder": 56.0,
    "HVAC Tech": 54.0, "Painter": 42.0, "Roofer": 46.0,
    "Pipefitter": 53.0, "Inspector": 62.0, "Rigger": 57.0,
}

MATERIAL_POOL = [
    "Ready-Mix Concrete", "Rebar #4", "Rebar #8", "Structural Steel W-Beam",
    "Lumber 2x6", "Plywood Sheathing", "Drywall 4x8", "Electrical Wire 12AWG",
    "PVC Pipe 4in", "Copper Pipe 1in", "Fiberglass Insulation", "Latex Paint",
    "Asphalt Shingle", "Glass Panel", "HVAC Ductwork 12in",
    "Fire Sprinkler Pipe", "Ceiling Grid", "Carpet Tile", "Ceramic Tile",
    "Anchor Bolt Set", "Welding Rod", "Gravel Fill", "Waterproof Membrane",
    "Conduit EMT 1in", "Switchgear Panel",
]

SUPPLIER_POOL = [
    "BuildCo Supply", "Metro Materials", "Apex Steel", "Premier Lumber",
    "National Electric", "Delta Plumbing", "Ace Concrete", "Summit HVAC",
]

WEATHER_TYPES = ["Rain", "High Wind", "Snow", "Extreme Heat", "Fog", "Thunderstorm"]

OUTDOOR_PHASES = {"Foundation", "Structural"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def working_days_between(start, end):
    """Return list of working days (Mon-Fri) in [start, end]."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def add_working_days(start, n):
    """Add *n* working days to *start* (n can be 0)."""
    if n <= 0:
        return start
    current = start
    added = 0
    while added < n:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def working_days_count(start, end):
    return len(working_days_between(start, end))


def ds(dt):
    """Datetime  → 'YYYY-MM-DD' string or None."""
    return dt.strftime("%Y-%m-%d") if dt else None


# ---------------------------------------------------------------------------
# Task generation
# ---------------------------------------------------------------------------
def generate_tasks(n_tasks, rng):
    tasks = []
    tasks_per_phase = n_tasks // len(PHASES)
    remainder = n_tasks % len(PHASES)
    task_id = 1

    phase_offsets = {
        "Foundation": 0,
        "Structural": max(10, tasks_per_phase * 3),
        "MEP": max(22, tasks_per_phase * 5),
        "Finishing": max(34, tasks_per_phase * 7),
    }

    for pi, phase in enumerate(PHASES):
        count = tasks_per_phase + (1 if pi < remainder else 0)
        templates = TASK_TEMPLATES[phase]
        phase_base = add_working_days(PROJECT_START, phase_offsets[phase])

        num_zones = max(2, math.ceil(count / len(templates)))
        zone_labels = [chr(65 + z) for z in range(num_zones)]

        cur_date = {z: phase_base for z in zone_labels}
        prev_code = {z: None for z in zone_labels}

        for j in range(count):
            zone_idx = j % num_zones
            zone = zone_labels[zone_idx]
            tmpl_idx = (j // num_zones) % len(templates)
            task_name = f"{templates[tmpl_idx]} - Zone {zone}"
            task_code = f"{PHASE_CODES[phase]}-{task_id:03d}"

            planned_dur = int(rng.integers(3, 11))
            planned_start = cur_date[zone]
            planned_end = add_working_days(planned_start, planned_dur - 1)

            preds = []
            if prev_code[zone]:
                preds.append(prev_code[zone])

            is_outdoor = phase in OUTDOOR_PHASES
            delay_prob = 0.40 if is_outdoor else 0.22

            if planned_end <= REPORTING_DATE - timedelta(days=10):
                status = "completed"
                start_jitter = int(rng.integers(-1, 3))
                actual_start = add_working_days(planned_start, max(0, start_jitter))
                if rng.random() < delay_prob:
                    delay_d = int(rng.integers(1, 9))
                elif rng.random() < 0.15:
                    delay_d = -int(rng.integers(1, 4))
                else:
                    delay_d = 0
                actual_end = add_working_days(planned_end, max(0, delay_d)) if delay_d >= 0 else planned_end - timedelta(days=-delay_d)
                # Ensure actual_end >= actual_start
                if actual_end < actual_start:
                    actual_end = actual_start
                pct = 100
            elif planned_start <= REPORTING_DATE:
                status = "in_progress"
                start_jitter = int(rng.integers(0, 3))
                actual_start = add_working_days(planned_start, start_jitter)
                actual_end = None
                elapsed = working_days_count(actual_start, REPORTING_DATE)
                pct = min(95, max(5, int(elapsed / max(1, planned_dur) * 100 + int(rng.integers(-15, 10)))))
            else:
                status = "not_started"
                actual_start = None
                actual_end = None
                pct = 0

            total_float = 0 if zone == "A" else int(rng.integers(1, 16))
            is_cp = total_float == 0

            tasks.append({
                "task_id": task_id,
                "task_code": task_code,
                "task_name": task_name,
                "phase": phase,
                "zone": zone,
                "planned_start": planned_start,
                "planned_end": planned_end,
                "planned_duration_days": planned_dur,
                "actual_start": actual_start,
                "actual_end": actual_end,
                "percent_complete": pct,
                "status": status,
                "predecessors": preds,
                "is_critical_path": is_cp,
                "total_float_days": total_float,
                "is_outdoor": is_outdoor,
            })

            cur_date[zone] = add_working_days(planned_end, 1)
            prev_code[zone] = task_code
            task_id += 1

    return tasks


# ---------------------------------------------------------------------------
# Equipment telemetry
# ---------------------------------------------------------------------------
def generate_equipment_telemetry(tasks, rng):
    records = []
    rec_id = 1
    for t in tasks:
        if t["status"] == "not_started":
            continue
        start = t["actual_start"] or t["planned_start"]
        end = t["actual_end"] or REPORTING_DATE
        days = working_days_between(start, end)
        if not days:
            continue
        n_eq = int(rng.integers(1, 3))
        eqs = [EQUIPMENT_POOL[i] for i in rng.choice(len(EQUIPMENT_POOL), size=n_eq, replace=False)]
        for eq_id, _, _ in eqs:
            for d in days:
                hrs = round(float(rng.uniform(4, 10)), 1)
                idle = round(float(rng.uniform(0, 2)), 1)
                dt_hrs, dt_reason = 0.0, "none"
                if rng.random() < 0.12:
                    dt_hrs = round(float(rng.uniform(1, 4)), 1)
                    dt_reason = str(rng.choice([
                        "mechanical_failure", "maintenance", "fuel_shortage",
                        "operator_unavailable", "part_replacement"]))
                fuel = round(float(hrs * rng.uniform(8, 25)), 1)
                records.append((rec_id, t["task_id"], eq_id, ds(d), hrs, idle,
                                dt_hrs, dt_reason, fuel))
                rec_id += 1
    return records


# ---------------------------------------------------------------------------
# Workers & labor timecards
# ---------------------------------------------------------------------------
def generate_workers(n, rng, fake):
    workers = []
    for i in range(n):
        role = WORKER_ROLES[i % len(WORKER_ROLES)]
        workers.append({
            "worker_id": f"W-{i+1:03d}",
            "name": fake.name(),
            "role": role,
            "hourly_rate": ROLE_HOURLY_RATES[role],
            "certification_level": str(rng.choice(["Level 1", "Level 2", "Level 3"])),
            "years_experience": int(rng.integers(1, 25)),
        })
    return workers


def generate_labor_timecards(tasks, workers, rng):
    records = []
    rec_id = 1
    for t in tasks:
        if t["status"] == "not_started":
            continue
        start = t["actual_start"] or t["planned_start"]
        end = t["actual_end"] or REPORTING_DATE
        days = working_days_between(start, end)
        if not days:
            continue
        n_w = min(len(workers), int(rng.integers(2, 6)))
        assigned = [workers[i] for i in rng.choice(len(workers), size=n_w, replace=False)]
        for w in assigned:
            for d in days:
                reg = round(float(rng.uniform(6, 8)), 1)
                ot = round(float(rng.uniform(1, 4)), 1) if rng.random() < 0.20 else 0.0
                shift = str(rng.choice(["day", "swing", "night"]))
                records.append((rec_id, w["worker_id"], t["task_id"], ds(d),
                                reg, ot, w["role"], shift))
                rec_id += 1
    return records


# ---------------------------------------------------------------------------
# Material procurement
# ---------------------------------------------------------------------------
def generate_procurement(tasks, rng):
    records = []
    rec_id = 1
    for t in tasks:
        n_mat = int(rng.integers(1, 4))
        indices = rng.choice(len(MATERIAL_POOL), size=n_mat, replace=False)
        for mi in indices:
            mat_name = MATERIAL_POOL[mi]
            mat_code = f"MAT-{mi+1:03d}"
            qty_ord = int(rng.integers(20, 500))
            unit_cost = round(float(rng.uniform(5, 300)), 2)
            order_dt = t["planned_start"] - timedelta(days=int(rng.integers(14, 45)))
            exp_del = t["planned_start"] - timedelta(days=int(rng.integers(1, 7)))

            if t["status"] == "not_started":
                if rng.random() < 0.6:
                    st, act_del, qty_rec = "ordered", None, 0
                else:
                    st = "delivered"
                    act_del = exp_del + timedelta(days=int(rng.integers(-3, 5)))
                    qty_rec = qty_ord
            elif t["status"] in ("in_progress", "completed"):
                roll = rng.random()
                if roll < 0.65:
                    st = "delivered"
                    act_del = exp_del + timedelta(days=int(rng.integers(-3, 8)))
                    qty_rec = qty_ord
                elif roll < 0.85:
                    st = "partial"
                    act_del = exp_del + timedelta(days=int(rng.integers(0, 10)))
                    qty_rec = int(qty_ord * float(rng.uniform(0.3, 0.8)))
                else:
                    st, act_del, qty_rec = "delayed", None, 0
            else:
                st, act_del, qty_rec = "ordered", None, 0

            supplier = str(rng.choice(SUPPLIER_POOL))
            records.append((rec_id, t["task_id"], mat_code, mat_name,
                            qty_ord, qty_rec, unit_cost,
                            ds(order_dt), ds(exp_del), ds(act_del),
                            st, supplier))
            rec_id += 1
    return records


# ---------------------------------------------------------------------------
# Weather delay logs
# ---------------------------------------------------------------------------
def generate_weather_delays(tasks, min_rows, rng):
    all_days = working_days_between(PROJECT_START, REPORTING_DATE)
    per_day = max(1, math.ceil(min_rows / len(all_days)))

    records = []
    rec_id = 1
    for d in all_days:
        for obs in range(per_day):
            if rng.random() < 0.32:
                wtype = str(rng.choice(WEATHER_TYPES))
                sev = str(rng.choice(["low", "moderate", "severe"]))
                if sev == "low":
                    hrs = round(float(rng.uniform(0.5, 2)), 1)
                elif sev == "moderate":
                    hrs = round(float(rng.uniform(2, 5)), 1)
                else:
                    hrs = round(float(rng.uniform(4, 8)), 1)
            else:
                wtype, sev, hrs = "Clear", "none", 0.0

            affected = []
            if hrs > 0:
                for t in tasks:
                    if not t["is_outdoor"]:
                        continue
                    ts = t["actual_start"] or t["planned_start"]
                    te = t["actual_end"] or REPORTING_DATE
                    if ts <= d <= te:
                        affected.append(t["task_id"])

            records.append((rec_id, ds(d), obs, wtype, sev, hrs,
                            json.dumps(affected), ""))
            rec_id += 1
    return records


# ---------------------------------------------------------------------------
# Database creation
# ---------------------------------------------------------------------------
def create_database(db_path, tasks, telemetry, timecards, procurement, weather):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE project_tasks (
        task_id INTEGER PRIMARY KEY, task_code TEXT, task_name TEXT,
        phase TEXT, status TEXT, actual_start_date TEXT,
        actual_end_date TEXT, percent_complete INTEGER)""")
    c.executemany("INSERT INTO project_tasks VALUES (?,?,?,?,?,?,?,?)",
                  [(t["task_id"], t["task_code"], t["task_name"], t["phase"],
                    t["status"], ds(t["actual_start"]), ds(t["actual_end"]),
                    t["percent_complete"]) for t in tasks])

    c.execute("""CREATE TABLE equipment_telemetry (
        id INTEGER PRIMARY KEY, task_id INTEGER, equipment_id TEXT,
        record_date TEXT, hours_operated REAL, idle_hours REAL,
        downtime_hours REAL, downtime_reason TEXT,
        fuel_consumption_liters REAL)""")
    c.executemany("INSERT INTO equipment_telemetry VALUES (?,?,?,?,?,?,?,?,?)",
                  telemetry)

    c.execute("""CREATE TABLE labor_timecards (
        id INTEGER PRIMARY KEY, worker_id TEXT, task_id INTEGER,
        record_date TEXT, regular_hours REAL, overtime_hours REAL,
        role TEXT, shift TEXT)""")
    c.executemany("INSERT INTO labor_timecards VALUES (?,?,?,?,?,?,?,?)",
                  timecards)

    c.execute("""CREATE TABLE material_procurement (
        id INTEGER PRIMARY KEY, task_id INTEGER, material_code TEXT,
        material_name TEXT, quantity_ordered INTEGER,
        quantity_received INTEGER, unit_cost REAL, order_date TEXT,
        expected_delivery TEXT, actual_delivery TEXT,
        status TEXT, supplier TEXT)""")
    c.executemany("INSERT INTO material_procurement VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  procurement)

    c.execute("""CREATE TABLE weather_delay_logs (
        id INTEGER PRIMARY KEY, record_date TEXT,
        observation_index INTEGER, weather_type TEXT,
        severity TEXT, delay_hours REAL,
        affected_task_ids TEXT, notes TEXT)""")
    c.executemany("INSERT INTO weather_delay_logs VALUES (?,?,?,?,?,?,?,?)",
                  weather)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Workspace files — fixed (config/policy)
# ---------------------------------------------------------------------------
def create_fixed_files(ws, tasks, workers, rng):
    # 1. gantt_baseline.csv — planned schedule (NOT in DB)
    rows = []
    for t in tasks:
        rows.append({
            "task_code": t["task_code"],
            "task_name": t["task_name"],
            "phase": t["phase"],
            "zone": t["zone"],
            "planned_start": ds(t["planned_start"]),
            "planned_end": ds(t["planned_end"]),
            "planned_duration_days": t["planned_duration_days"],
            "predecessors": ";".join(t["predecessors"]) if t["predecessors"] else "",
            "is_critical_path": "TRUE" if t["is_critical_path"] else "FALSE",
            "total_float_days": t["total_float_days"],
            "is_outdoor": "TRUE" if t["is_outdoor"] else "FALSE",
        })
    pd.DataFrame(rows).to_csv(os.path.join(ws, "gantt_baseline.csv"), index=False)

    # 2. equipment_registry.json
    reg = {}
    for eq_id, eq_name, eq_type in EQUIPMENT_POOL:
        reg[eq_id] = {
            "name": eq_name,
            "type": eq_type,
            "max_daily_hours": round(float(rng.uniform(8, 12)), 1),
            "fuel_capacity_liters": int(rng.integers(100, 600)),
            "daily_rental_cost": round(float(rng.uniform(200, 1500)), 2),
        }
    with open(os.path.join(ws, "equipment_registry.json"), "w") as f:
        json.dump(reg, f, indent=2)

    # 3. worker_roster.yaml
    roster = {}
    for w in workers:
        roster[w["worker_id"]] = {
            "name": w["name"],
            "role": w["role"],
            "hourly_rate": w["hourly_rate"],
            "overtime_multiplier": 1.5,
            "certification_level": w["certification_level"],
            "years_experience": w["years_experience"],
        }
    with open(os.path.join(ws, "worker_roster.yaml"), "w") as f:
        yaml.dump(roster, f, default_flow_style=False, sort_keys=True)

    # 4. budget_allocation.csv — planned cost per task (NOT in DB)
    brows = []
    for t in tasks:
        pl = round(float(t["planned_duration_days"] * rng.uniform(3, 6) * 8 * rng.uniform(40, 60)), 2)
        pm = round(float(rng.uniform(5000, 80000)), 2)
        pe = round(float(t["planned_duration_days"] * rng.uniform(300, 1200)), 2)
        brows.append({
            "task_code": t["task_code"],
            "planned_labor_cost": pl,
            "planned_material_cost": pm,
            "planned_equipment_cost": pe,
            "planned_total_cost": round(pl + pm + pe, 2),
        })
    pd.DataFrame(brows).to_csv(os.path.join(ws, "budget_allocation.csv"), index=False)

    # 5. variance_thresholds.json
    thresholds = {
        "reporting_date": ds(REPORTING_DATE),
        "schedule_variance": {
            "critical_threshold_days": 5,
            "significant_threshold_days": 3,
            "moderate_threshold_days": 1,
        },
        "cost_variance": {
            "critical_threshold_pct": 20.0,
            "significant_threshold_pct": 10.0,
            "moderate_threshold_pct": 5.0,
        },
        "impact_assessment_rules": {
            "CRITICAL": "critical_path task with schedule_variance_days >= critical_threshold_days OR any task with cost_variance_pct >= critical_threshold_pct",
            "SIGNIFICANT": "schedule_variance_days >= significant_threshold_days OR cost_variance_pct >= significant_threshold_pct",
            "MODERATE": "schedule_variance_days >= moderate_threshold_days OR cost_variance_pct >= moderate_threshold_pct",
            "MINOR": "any positive schedule_variance_days or positive cost_variance_pct that does not meet higher thresholds",
            "NONE": "on or ahead of schedule and on or under budget",
        },
        "overtime_multiplier": 1.5,
    }
    with open(os.path.join(ws, "variance_thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=2)

    # 6. weather_impact_policy.json
    wpolicy = {
        "severity_delay_weight": {
            "low": 0.5,
            "moderate": 1.0,
            "severe": 1.5,
        },
        "affected_scope": "outdoor tasks only",
        "conversion_note": "Sum weighted delay_hours for each task, then divide by 8 to get weather_delay_days (round to 2 decimals)",
        "weather_contingency_buffer_days": 2,
    }
    with open(os.path.join(ws, "weather_impact_policy.json"), "w") as f:
        json.dump(wpolicy, f, indent=2)


# ---------------------------------------------------------------------------
# Workspace files — scalable (daily inspection reports)
# ---------------------------------------------------------------------------
def create_scalable_files(ws, tasks, n_files, rng, fake):
    all_days = working_days_between(PROJECT_START, REPORTING_DATE)
    step = max(1, len(all_days) // n_files)
    selected = [all_days[i * step] for i in range(n_files) if i * step < len(all_days)]
    while len(selected) < n_files and len(selected) < len(all_days):
        selected.append(all_days[len(selected)])

    FORMATS = [".md", ".json", ".csv", ".txt", ".yaml"]
    RISK_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]
    RISK_WEIGHTS = [0.05, 0.15, 0.30, 0.35, 0.15]

    for idx, day in enumerate(selected):
        fmt = FORMATS[idx % len(FORMATS)]
        dstr = day.strftime("%Y-%m-%d")

        active = [t for t in tasks
                  if (t["actual_start"] or t["planned_start"]) <= day <=
                     (t["actual_end"] or REPORTING_DATE)
                  and t["status"] != "not_started"]

        assessments = []
        for t in active:
            risk = str(rng.choice(RISK_LEVELS, p=RISK_WEIGHTS))
            qs = int(rng.integers(1, 6))
            note = fake.sentence(nb_words=8)
            assessments.append({
                "task_code": t["task_code"],
                "task_name": t["task_name"],
                "risk_level": risk,
                "quality_score": qs,
                "inspector_note": note,
            })

        fname = f"inspection_report_{dstr}{fmt}"
        fpath = os.path.join(ws, fname)

        inspector = fake.name()
        wx = str(rng.choice(["Clear", "Overcast", "Light Rain", "Windy"]))
        temp = int(rng.integers(25, 95))

        if fmt == ".md":
            lines = [
                f"# Daily Inspection Report - {dstr}", "",
                f"Inspector: {inspector}",
                f"Weather Conditions: {wx}",
                f"Temperature: {temp}F", "",
                "## Task Assessments", "",
            ]
            for a in assessments:
                lines += [
                    f"### {a['task_code']} - {a['task_name']}",
                    f"- Risk Level: {a['risk_level']}",
                    f"- Quality Score: {a['quality_score']}/5",
                    f"- Notes: {a['inspector_note']}", "",
                ]
            with open(fpath, "w") as f:
                f.write("\n".join(lines))

        elif fmt == ".json":
            with open(fpath, "w") as f:
                json.dump({"date": dstr, "inspector": inspector,
                           "weather": wx, "temperature_f": temp,
                           "assessments": assessments}, f, indent=2)

        elif fmt == ".csv":
            if assessments:
                df = pd.DataFrame(assessments)
                df.insert(0, "date", dstr)
                df.insert(1, "inspector", inspector)
                df.to_csv(fpath, index=False)
            else:
                with open(fpath, "w") as f:
                    f.write("date,inspector,task_code,task_name,risk_level,quality_score,inspector_note\n")

        elif fmt == ".txt":
            lines = ["DAILY INSPECTION REPORT", f"Date: {dstr}",
                     f"Inspector: {inspector}", ""]
            for a in assessments:
                lines.append(
                    f"Task {a['task_code']} ({a['task_name']}): "
                    f"Risk={a['risk_level']}, Quality={a['quality_score']}/5, "
                    f"Note: {a['inspector_note']}")
            with open(fpath, "w") as f:
                f.write("\n".join(lines))

        elif fmt == ".yaml":
            with open(fpath, "w") as f:
                yaml.dump({
                    "date": dstr, "inspector": inspector,
                    "weather": wx, "temperature_f": temp,
                    "assessments": [
                        {"task_code": a["task_code"], "task_name": a["task_name"],
                         "risk_level": a["risk_level"],
                         "quality_score": int(a["quality_score"]),
                         "inspector_note": a["inspector_note"]}
                        for a in assessments],
                }, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    rng = np.random.default_rng(42)
    fake = Faker()

    os.makedirs(args.workspace, exist_ok=True)

    n_tasks = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    tasks = generate_tasks(n_tasks, rng)
    n_workers = max(15, n_tasks // 3)
    workers = generate_workers(n_workers, rng, fake)

    telemetry = generate_equipment_telemetry(tasks, rng)
    timecards = generate_labor_timecards(tasks, workers, rng)
    procurement = generate_procurement(tasks, rng)
    weather = generate_weather_delays(tasks, SCALE["rows_per_table"], rng)

    create_database(args.db_path, tasks, telemetry, timecards, procurement, weather)
    create_fixed_files(args.workspace, tasks, workers, rng)
    create_scalable_files(args.workspace, tasks, n_files, rng, fake)

    conn = sqlite3.connect(args.db_path)
    for tbl in ["project_tasks", "equipment_telemetry", "labor_timecards",
                "material_procurement", "weather_delay_logs"]:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {cnt} rows")
    conn.close()
    ws_files = [f for f in os.listdir(args.workspace)
                if os.path.isfile(os.path.join(args.workspace, f))]
    print(f"  Workspace files: {len(ws_files)}")


if __name__ == "__main__":
    main()
