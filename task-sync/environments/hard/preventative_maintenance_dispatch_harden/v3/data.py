"""
Fleet Preventative Maintenance Task - Data Generator
Generates database and workspace files for maintenance scheduling optimization.
"""
import argparse
import os
import sqlite3
import json
import csv
import math
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain Constants ────────────────────────────────────────────────────────
CATEGORIES = ["sedan", "suv", "truck", "van", "bus"]
DEPOTS = ["North", "Central", "South"]

BASE_MAINTENANCE_TYPES = [
    "oil_change", "tire_rotation", "brake_inspection", "transmission_service",
    "coolant_flush", "air_filter_replacement", "battery_service", "belt_inspection",
    "wheel_alignment", "fuel_system_service", "spark_plug_replacement",
    "cabin_filter_replacement", "differential_service", "power_steering_service",
    "exhaust_inspection", "suspension_check", "wiper_blade_replacement",
    "ac_service", "headlight_service", "emissions_check",
]

# (part_name, compatible_base_type)
BASE_PARTS = [
    ("engine_oil_5w30", "oil_change"),
    ("oil_filter_standard", "oil_change"),
    ("tire_valve_kit", "tire_rotation"),
    ("wheel_weight_set", "tire_rotation"),
    ("brake_pad_set", "brake_inspection"),
    ("brake_rotor_disc", "brake_inspection"),
    ("brake_fluid_dot4", "brake_inspection"),
    ("atf_fluid", "transmission_service"),
    ("transmission_filter", "transmission_service"),
    ("coolant_premix", "coolant_flush"),
    ("coolant_hose_kit", "coolant_flush"),
    ("air_filter_panel", "air_filter_replacement"),
    ("battery_agm_12v", "battery_service"),
    ("battery_terminal_kit", "battery_service"),
    ("serpentine_belt", "belt_inspection"),
    ("belt_tensioner", "belt_inspection"),
    ("alignment_shim_set", "wheel_alignment"),
    ("fuel_filter_inline", "fuel_system_service"),
    ("fuel_injector_cleaner", "fuel_system_service"),
    ("spark_plug_iridium_set", "spark_plug_replacement"),
    ("cabin_air_filter", "cabin_filter_replacement"),
    ("diff_fluid_75w90", "differential_service"),
    ("power_steering_fluid", "power_steering_service"),
    ("exhaust_gasket_set", "exhaust_inspection"),
    ("suspension_bushing_kit", "suspension_check"),
    ("shock_absorber_pair", "suspension_check"),
    ("wiper_blade_pair", "wiper_blade_replacement"),
    ("ac_refrigerant_r134a", "ac_service"),
    ("headlight_bulb_led", "headlight_service"),
    ("o2_sensor_upstream", "emissions_check"),
]

MAKES_MODELS = {
    "sedan": [("Toyota", "Camry"), ("Honda", "Accord"), ("Ford", "Fusion"),
              ("Chevrolet", "Malibu"), ("Nissan", "Altima")],
    "suv":   [("Toyota", "RAV4"), ("Ford", "Explorer"), ("Chevrolet", "Tahoe"),
              ("Jeep", "Cherokee"), ("Honda", "CR-V")],
    "truck": [("Ford", "F-150"), ("Ram", "1500"), ("Chevrolet", "Silverado"),
              ("Toyota", "Tacoma"), ("GMC", "Sierra")],
    "van":   [("Ford", "Transit"), ("Mercedes", "Sprinter"), ("Ram", "ProMaster"),
              ("Chevrolet", "Express"), ("Nissan", "NV200")],
    "bus":   [("Blue Bird", "Vision"), ("Thomas", "Saf-T-Liner"), ("IC Bus", "CE"),
              ("Freightliner", "FS-65"), ("Collins", "DH-IV")],
}

RESERVATION_PURPOSES = [
    "Client delivery run", "Long-haul route", "Special event transport",
    "Executive travel", "VIP shuttle service", "Airport transfer duty",
    "Trade show support", "Branch vehicle transfer", "Emergency standby",
    "Weekend rental commitment", "Driver training vehicle", "Regulatory inspection",
]

REFERENCE_DATE = datetime(2026, 4, 22)
SCHEDULING_WEEK_START = datetime(2026, 4, 27)  # Monday

# Parameters per base maintenance type
TYPE_PARAMS = {
    "oil_change":              {"mi": 5000,  "eh": 200,  "pb": 10.0, "cl": 1, "dur": 0.75},
    "tire_rotation":           {"mi": 7000,  "eh": 280,  "pb": 6.0,  "cl": 1, "dur": 0.75},
    "brake_inspection":        {"mi": 15000, "eh": 550,  "pb": 15.0, "cl": 2, "dur": 2.0},
    "transmission_service":    {"mi": 30000, "eh": 1000, "pb": 12.0, "cl": 3, "dur": 3.0},
    "coolant_flush":           {"mi": 25000, "eh": 800,  "pb": 10.0, "cl": 2, "dur": 1.5},
    "air_filter_replacement":  {"mi": 12000, "eh": 450,  "pb": 5.0,  "cl": 1, "dur": 0.5},
    "battery_service":         {"mi": 25000, "eh": 850,  "pb": 9.0,  "cl": 2, "dur": 1.0},
    "belt_inspection":         {"mi": 40000, "eh": 1300, "pb": 11.0, "cl": 2, "dur": 1.5},
    "wheel_alignment":         {"mi": 12000, "eh": 500,  "pb": 7.0,  "cl": 3, "dur": 1.25},
    "fuel_system_service":     {"mi": 25000, "eh": 850,  "pb": 10.0, "cl": 3, "dur": 2.0},
    "spark_plug_replacement":  {"mi": 30000, "eh": 1100, "pb": 8.0,  "cl": 2, "dur": 1.5},
    "cabin_filter_replacement":{"mi": 12000, "eh": 450,  "pb": 4.0,  "cl": 1, "dur": 0.5},
    "differential_service":    {"mi": 30000, "eh": 1050, "pb": 10.0, "cl": 3, "dur": 2.0},
    "power_steering_service":  {"mi": 40000, "eh": 1300, "pb": 9.0,  "cl": 3, "dur": 1.5},
    "exhaust_inspection":      {"mi": 25000, "eh": 850,  "pb": 11.0, "cl": 2, "dur": 1.5},
    "suspension_check":        {"mi": 20000, "eh": 700,  "pb": 12.0, "cl": 2, "dur": 2.5},
    "wiper_blade_replacement": {"mi": 10000, "eh": 380,  "pb": 3.0,  "cl": 1, "dur": 0.5},
    "ac_service":              {"mi": 25000, "eh": 850,  "pb": 6.0,  "cl": 2, "dur": 1.5},
    "headlight_service":       {"mi": 40000, "eh": 1300, "pb": 7.0,  "cl": 1, "dur": 0.75},
    "emissions_check":         {"mi": 20000, "eh": 700,  "pb": 10.0, "cl": 3, "dur": 1.5},
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _mtype_name(base_idx, tier):
    base = BASE_MAINTENANCE_TYPES[base_idx % len(BASE_MAINTENANCE_TYPES)]
    return base if tier == 1 else f"{base}_tier{tier}"


# ── Generators ──────────────────────────────────────────────────────────────

def generate_vehicles(n):
    vehicles = []
    for i in range(n):
        cat = CATEGORIES[i % len(CATEGORIES)]
        make, model = random.choice(MAKES_MODELS[cat])
        year = random.randint(2018, 2024)
        depot = DEPOTS[i % len(DEPOTS)]
        vin = "1" + "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ0123456789", k=16))
        vehicles.append({
            "vehicle_id": f"V{i + 1:04d}",
            "make": make,
            "model": model,
            "year": year,
            "category": cat,
            "vin": vin,
            "depot_id": depot,
        })
    return vehicles


def generate_telemetry(vehicles):
    """Current telemetry readings per vehicle (workspace-only, NOT in DB)."""
    telemetry = {}
    for v in vehicles:
        base_mileage = random.randint(18000, 110000)
        hours_per_mile = random.uniform(0.032, 0.048)
        telemetry[v["vehicle_id"]] = {
            "odometer_miles": base_mileage,
            "engine_hours": int(base_mileage * hours_per_mile),
            "oil_life_pct": random.randint(5, 95),
            "brake_wear_pct": random.randint(20, 90),
            "coolant_temp_f": random.randint(185, 220),
            "fault_codes": random.choice(["", "", "", "", "P0301", "P0420", "P0171", ""]),
        }
    return telemetry


def generate_rules(n):
    rules = []
    for i in range(n):
        cat = CATEGORIES[i % len(CATEGORIES)]
        base_idx = (i // len(CATEGORIES)) % len(BASE_MAINTENANCE_TYPES)
        tier = (i // len(CATEGORIES)) // len(BASE_MAINTENANCE_TYPES) + 1
        mtype = _mtype_name(base_idx, tier)
        base = BASE_MAINTENANCE_TYPES[base_idx]
        p = TYPE_PARAMS[base]

        tier_factor = 1.0 / (0.5 + 0.5 * tier)
        noise = random.uniform(0.88, 1.12)

        rules.append({
            "rule_id": f"R{i + 1:04d}",
            "vehicle_category": cat,
            "maintenance_type": mtype,
            "mileage_interval": max(1000, int(p["mi"] * noise * tier_factor)),
            "engine_hours_interval": max(50, int(p["eh"] * noise * tier_factor)),
            "priority_base": round(p["pb"] * random.uniform(0.9, 1.1), 1),
            "required_cert_level": min(5, p["cl"] + max(0, tier - 2)),
            "estimated_duration_hours": round(
                p["dur"] * random.uniform(0.9, 1.1) * (1 + 0.15 * (tier - 1)), 1
            ),
        })
    return rules


def generate_technicians(n):
    techs = []
    for i in range(n):
        cert = random.choices([1, 2, 3, 4, 5], weights=[15, 25, 30, 20, 10])[0]
        depot = DEPOTS[i % len(DEPOTS)]
        techs.append({
            "tech_id": f"T{i + 1:04d}",
            "name": fake.name(),
            "cert_level": cert,
            "max_weekly_hours": round(random.uniform(30, 45), 0),
            "depot_id": depot,
            "hourly_rate": round(random.uniform(25, 75), 2),
        })
    return techs


def generate_parts(n):
    parts = []
    for i in range(n):
        base_idx = i % len(BASE_PARTS)
        variant = i // len(BASE_PARTS) + 1
        base_name, compat_type = BASE_PARTS[base_idx]
        name = base_name if variant == 1 else f"{base_name}_v{variant}"
        qty = random.choices(
            [0, random.randint(1, 5), random.randint(6, 50)],
            weights=[10, 20, 70],
        )[0]
        reorder = random.randint(3, 10)
        parts.append({
            "part_id": f"P{i + 1:04d}",
            "part_name": name,
            "compatible_types": compat_type,
            "quantity_on_hand": qty,
            "reorder_point": reorder,
            "unit_cost": round(random.uniform(5, 450), 2),
        })
    return parts


def generate_service_history(vehicles, rules, technicians, telemetry):
    """Past service records.  ~60 % of vehicle-rule pairs get a record."""
    rules_by_cat = {}
    for r in rules:
        rules_by_cat.setdefault(r["vehicle_category"], []).append(r)

    tech_ids = [t["tech_id"] for t in technicians]
    records = []
    rec_idx = 0

    for v in vehicles:
        cat = v["category"]
        vid = v["vehicle_id"]
        cur = telemetry[vid]
        applicable = rules_by_cat.get(cat, [])

        for rule in applicable:
            if random.random() > 0.60:
                continue

            overdue_ratio = random.uniform(0.3, 1.4)
            mi_at = cur["odometer_miles"] - int(overdue_ratio * rule["mileage_interval"])
            eh_at = cur["engine_hours"] - int(overdue_ratio * rule["engine_hours_interval"])
            mi_at = max(0, mi_at)
            eh_at = max(0, eh_at)

            miles_driven = cur["odometer_miles"] - mi_at
            daily_mi = random.uniform(30, 120)
            days_ago = max(1, int(miles_driven / daily_mi))
            svc_date = REFERENCE_DATE - timedelta(days=days_ago)

            rec_idx += 1
            records.append({
                "record_id": f"SH{rec_idx:05d}",
                "vehicle_id": vid,
                "maintenance_type": rule["maintenance_type"],
                "service_date": svc_date.strftime("%Y-%m-%d"),
                "mileage_at_service": mi_at,
                "engine_hours_at_service": eh_at,
                "technician_id": random.choice(tech_ids),
            })

    return records


# ── Database ────────────────────────────────────────────────────────────────

def create_database(db_path, vehicles, rules, technicians, parts, history):
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE vehicles (
        vehicle_id TEXT PRIMARY KEY, make TEXT, model TEXT, year INTEGER,
        category TEXT, vin TEXT, depot_id TEXT)""")

    c.execute("""CREATE TABLE maintenance_rules (
        rule_id TEXT PRIMARY KEY, vehicle_category TEXT, maintenance_type TEXT,
        mileage_interval INTEGER, engine_hours_interval INTEGER,
        priority_base REAL, required_cert_level INTEGER,
        estimated_duration_hours REAL)""")

    c.execute("""CREATE TABLE technicians (
        tech_id TEXT PRIMARY KEY, name TEXT, cert_level INTEGER,
        max_weekly_hours REAL, depot_id TEXT, hourly_rate REAL)""")

    c.execute("""CREATE TABLE parts_inventory (
        part_id TEXT PRIMARY KEY, part_name TEXT, compatible_types TEXT,
        quantity_on_hand INTEGER, reorder_point INTEGER, unit_cost REAL)""")

    c.execute("""CREATE TABLE service_history (
        record_id TEXT PRIMARY KEY, vehicle_id TEXT, maintenance_type TEXT,
        service_date TEXT, mileage_at_service INTEGER,
        engine_hours_at_service INTEGER, technician_id TEXT,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id),
        FOREIGN KEY (technician_id) REFERENCES technicians(tech_id))""")

    for v in vehicles:
        c.execute("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?)",
                  (v["vehicle_id"], v["make"], v["model"], v["year"],
                   v["category"], v["vin"], v["depot_id"]))

    for r in rules:
        c.execute("INSERT INTO maintenance_rules VALUES (?,?,?,?,?,?,?,?)",
                  (r["rule_id"], r["vehicle_category"], r["maintenance_type"],
                   r["mileage_interval"], r["engine_hours_interval"],
                   r["priority_base"], r["required_cert_level"],
                   r["estimated_duration_hours"]))

    for t in technicians:
        c.execute("INSERT INTO technicians VALUES (?,?,?,?,?,?)",
                  (t["tech_id"], t["name"], t["cert_level"],
                   t["max_weekly_hours"], t["depot_id"], t["hourly_rate"]))

    for p in parts:
        c.execute("INSERT INTO parts_inventory VALUES (?,?,?,?,?,?)",
                  (p["part_id"], p["part_name"], p["compatible_types"],
                   p["quantity_on_hand"], p["reorder_point"], p["unit_cost"]))

    for h in history:
        c.execute("INSERT INTO service_history VALUES (?,?,?,?,?,?,?)",
                  (h["record_id"], h["vehicle_id"], h["maintenance_type"],
                   h["service_date"], h["mileage_at_service"],
                   h["engine_hours_at_service"], h["technician_id"]))

    conn.commit()
    conn.close()


# ── Workspace Files ─────────────────────────────────────────────────────────

def generate_telemetry_files(vehicles, telemetry, n_files, workspace):
    n_telem = max(1, math.ceil(n_files * 0.6))
    vids = [v["vehicle_id"] for v in vehicles]
    chunk_size = max(1, math.ceil(len(vids) / n_telem))

    for fi in range(n_telem):
        chunk = vids[fi * chunk_size: (fi + 1) * chunk_size]
        if not chunk:
            continue
        path = os.path.join(workspace, f"telemetry_batch_{fi + 1:02d}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "vehicle_id", "reading_date", "odometer_miles", "engine_hours",
                "oil_life_pct", "brake_wear_pct", "coolant_temp_f", "fault_codes",
            ])
            for vid in chunk:
                t = telemetry[vid]
                writer.writerow([
                    vid, "2026-04-21", t["odometer_miles"], t["engine_hours"],
                    t["oil_life_pct"], t["brake_wear_pct"], t["coolant_temp_f"],
                    t["fault_codes"],
                ])


def generate_reservation_files(vehicles, n_files, workspace):
    n_telem = max(1, math.ceil(n_files * 0.6))
    n_res = n_files - n_telem

    week_dates = [(SCHEDULING_WEEK_START + timedelta(days=d)) for d in range(5)]
    vids = [v["vehicle_id"] for v in vehicles]
    n_reserved = max(1, int(len(vids) * 0.3))
    reserved = random.sample(vids, n_reserved)

    all_reservations = []
    for vid in reserved:
        start_idx = random.randint(0, 4)
        span = random.randint(1, min(2, 5 - start_idx))
        start_d = week_dates[start_idx]
        end_d = week_dates[start_idx + span - 1]
        all_reservations.append({
            "vehicle_id": vid,
            "start_date": start_d.strftime("%Y-%m-%d"),
            "end_date": end_d.strftime("%Y-%m-%d"),
            "purpose": random.choice(RESERVATION_PURPOSES),
        })

    # Sprinkle noise reservations outside the scheduling week
    n_noise = max(2, len(reserved) // 3)
    for _ in range(n_noise):
        vid = random.choice(vids)
        offset = random.choice([-7, -5, 7, 10, 14])
        d = SCHEDULING_WEEK_START + timedelta(days=offset)
        all_reservations.append({
            "vehicle_id": vid,
            "start_date": d.strftime("%Y-%m-%d"),
            "end_date": d.strftime("%Y-%m-%d"),
            "purpose": random.choice(RESERVATION_PURPOSES),
        })

    random.shuffle(all_reservations)
    chunk_size = max(1, math.ceil(len(all_reservations) / max(1, n_res)))

    for fi in range(max(1, n_res)):
        chunk = all_reservations[fi * chunk_size: (fi + 1) * chunk_size]
        path = os.path.join(workspace, f"reservations_{fi + 1:02d}.json")
        with open(path, "w") as f:
            json.dump(chunk, f, indent=2)


def generate_policy_files(workspace):
    # ── maintenance_policy.yaml ──
    policy = {
        "due_threshold": 0.85,
        "critical_threshold": 1.15,
        "standard_multiplier": 1.0,
        "critical_multiplier": 1.5,
        "no_history_overdue_ratio": 1.3,
        "scoring_formula": "urgency_score = round(overdue_ratio * priority_base * multiplier, 2)",
        "overdue_ratio_formula": (
            "max(mileage_ratio, hours_ratio) where "
            "mileage_ratio = (current_odometer - last_service_mileage) / mileage_interval, "
            "hours_ratio = (current_engine_hours - last_service_engine_hours) / engine_hours_interval"
        ),
        "multiplier_rule": (
            "Use critical_multiplier when overdue_ratio >= critical_threshold, "
            "otherwise use standard_multiplier"
        ),
        "urgency_tiers": {
            "critical": {"min_score": 15.0},
            "high": {"min_score": 8.0},
            "routine": {"min_score": 0.0},
        },
    }
    with open(os.path.join(workspace, "maintenance_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # ── scheduling_constraints.json ──
    week_dates = [
        (SCHEDULING_WEEK_START + timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(5)
    ]
    day_labels = {
        week_dates[0]: "Monday", week_dates[1]: "Tuesday",
        week_dates[2]: "Wednesday", week_dates[3]: "Thursday",
        week_dates[4]: "Friday",
    }
    constraints = {
        "scheduling_week_start": SCHEDULING_WEEK_START.strftime("%Y-%m-%d"),
        "scheduling_week_end": (SCHEDULING_WEEK_START + timedelta(days=4)).strftime("%Y-%m-%d"),
        "available_days": week_dates,
        "day_labels": day_labels,
        "max_dispatches_per_day": 15,
        "max_hours_per_technician_per_day": 8.0,
        "technician_assignment_rule": (
            "Among qualified technicians at the same depot with sufficient "
            "remaining hours, select the one with the lowest hourly_rate. "
            "Break ties by ascending tech_id."
        ),
        "scheduling_order": (
            "Process maintenance items in descending urgency_score order. "
            "Break ties by ascending vehicle_id, then ascending maintenance_type."
        ),
        "day_selection": (
            "For each item, try days in chronological order (Monday first). "
            "Assign to the first day where the vehicle has no reservation conflict, "
            "the daily dispatch limit is not reached, and a qualified technician "
            "is available."
        ),
    }
    with open(os.path.join(workspace, "scheduling_constraints.json"), "w") as f:
        json.dump(constraints, f, indent=2)

    # ── certification_guide.md ──
    guide = """# Technician Certification Levels

| Level | Title        | Description                                                       |
|-------|--------------|-------------------------------------------------------------------|
| 1     | Junior       | Basic tasks: oil changes, filter replacements, tire rotations, wipers, headlights |
| 2     | Standard     | Intermediate: brake systems, cooling, battery, belts, exhaust, suspension, A/C, spark plugs |
| 3     | Advanced     | Complex systems: transmission, fuel system, alignment, differential, power steering, emissions |
| 4     | Senior       | All systems plus advanced diagnostics and specialty vehicle work   |
| 5     | Master       | Full authority across all maintenance types and fleet oversight    |

A technician may perform any maintenance task whose required certification level
is at or below their own certified level.
"""
    with open(os.path.join(workspace, "certification_guide.md"), "w") as f:
        f.write(guide.strip() + "\n")

    # ── dispatch_methodology.md ──
    methodology = """# Dispatch Planning Methodology

This document, together with the maintenance policy file and the scheduling
constraints file, is the authoritative specification for building the weekly
preventative maintenance dispatch schedule.

## Telemetry baseline

The telemetry batch files contain the current odometer mileage and engine
hours for every vehicle in the fleet. Use each vehicle's reported reading as
its current state.

## Service baseline

For every vehicle and maintenance type, the baseline for interval
calculations is the most recent service record of that maintenance type
(latest service_date). If a vehicle has no service history at all for a
maintenance type that applies to its category, use the policy file's
no_history_overdue_ratio as that pair's overdue ratio directly.

## Due candidacy

A vehicle / maintenance-type pair is due — and becomes a dispatch candidate —
when its overdue ratio, computed per the policy file's overdue_ratio_formula,
is greater than or equal to the policy file's due_threshold. Pairs below the
due threshold are excluded from consideration. Each candidate's urgency score
is computed per the policy file's scoring_formula and multiplier_rule.

## Scheduling

Process candidates in the order given by the scheduling constraints
(scheduling_order), trying days as described there (day_selection). A
technician is qualified for a candidate item only if all of the following
hold simultaneously:

- the technician is stationed at the same depot as the vehicle;
- the technician's certification level is at or above the maintenance rule's
  required certification level;
- adding the item's estimated duration keeps the technician's assigned hours
  for that day at or below the configured maximum daily hours per technician;
- adding the item's estimated duration keeps the technician's total assigned
  hours for the scheduling week at or below that technician's own maximum
  weekly hours.

A vehicle may not be scheduled on any day it is reserved: a reservation
blocks every calendar day from its start date through its end date,
inclusive. Reservations outside the scheduling week are irrelevant. If no
valid day-and-technician combination exists for a candidate, omit it from
the dispatch schedule entirely.

## Parts status

Each dispatched item carries the parts status of its maintenance type:
"ready" when every required part has a positive quantity on hand strictly
above its reorder point, "backordered" when any required part has zero
quantity on hand, and otherwise "low_stock" when some required part's
on-hand quantity is positive but at or below its reorder point. A
maintenance type with no required parts on file is "ready".

## Urgency tiers

A dispatched item belongs to the highest urgency tier whose min_score its
urgency score meets or exceeds, per the urgency_tiers thresholds in the
policy file.

## Work order recording

Every item on the final dispatch schedule must also be recorded as a work
order in the fleet dispatch system, naming the assigned technician's queue,
the vehicle, the maintenance type, and the scheduled day.
"""
    with open(os.path.join(workspace, "dispatch_methodology.md"), "w") as f:
        f.write(methodology.strip() + "\n")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    vehicles = generate_vehicles(n)
    telemetry = generate_telemetry(vehicles)
    rules = generate_rules(n)
    technicians = generate_technicians(n)
    parts = generate_parts(n)
    history = generate_service_history(vehicles, rules, technicians, telemetry)

    create_database(args.db_path, vehicles, rules, technicians, parts, history)
    generate_telemetry_files(vehicles, telemetry, n_files, args.workspace)
    generate_reservation_files(vehicles, n_files, args.workspace)
    generate_policy_files(args.workspace)

    print(f"Database: {args.db_path}")
    print(f"  vehicles:          {len(vehicles)}")
    print(f"  maintenance_rules: {len(rules)}")
    print(f"  technicians:       {len(technicians)}")
    print(f"  parts_inventory:   {len(parts)}")
    print(f"  service_history:   {len(history)}")
    print(f"Workspace: {args.workspace}/")
    for wf in sorted(os.listdir(args.workspace)):
        print(f"  {wf}")


if __name__ == "__main__":
    main()
