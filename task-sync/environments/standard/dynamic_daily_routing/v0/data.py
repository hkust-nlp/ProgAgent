"""
data.py - Generate database and workspace for technician schedule optimization task.
"""
import argparse
import sqlite3
import os
import json
import csv
import math
import random
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 15,
    "num_workspace_files": 8,
}

random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------- Constants ----------

ZONE_POOL = [
    "Downtown", "Northside", "Southside", "Eastville", "Westpark",
    "Industrial", "Lakefront", "Hillcrest", "Riverside", "Midtown",
    "Oakwood", "Pinegrove", "Marshfield", "Cedarville", "Fairview",
    "Grandview", "Maplewood", "Stonebridge", "Clearwater", "Brookside",
]

ZONE_COORDS = {
    "Downtown": (40.7128, -74.0060),
    "Northside": (40.7580, -73.9855),
    "Southside": (40.6782, -73.9442),
    "Eastville": (40.7282, -73.9562),
    "Westpark": (40.7489, -74.0445),
    "Industrial": (40.6892, -74.0445),
    "Lakefront": (40.7614, -73.9776),
    "Hillcrest": (40.7831, -73.9712),
    "Riverside": (40.8032, -73.9580),
    "Midtown": (40.7549, -73.9840),
    "Oakwood": (40.7023, -74.0142),
    "Pinegrove": (40.7394, -74.0279),
    "Marshfield": (40.7211, -73.9873),
    "Cedarville": (40.6945, -73.9708),
    "Fairview": (40.7712, -74.0100),
    "Grandview": (40.7900, -74.0200),
    "Maplewood": (40.7300, -74.0600),
    "Stonebridge": (40.6800, -74.0000),
    "Clearwater": (40.7600, -74.0700),
    "Brookside": (40.7100, -73.9300),
}

PART_NAMES = [
    "Air Filter", "Compressor", "Thermostat", "Capacitor", "Relay Switch",
    "Fan Motor", "Condensate Pump", "Evaporator Coil", "Expansion Valve",
    "Refrigerant Charge", "Blower Wheel", "Contactor", "Transformer",
    "Circuit Board", "Ignitor", "Flame Sensor", "Gas Valve", "Heat Exchanger",
    "Pilot Assembly", "Pressure Switch", "Drain Pan", "UV Lamp",
    "Humidifier Pad", "Belt Drive", "Duct Seal", "Copper Tubing",
    "Insulation Wrap", "Mounting Bracket", "Voltage Regulator", "Fuse Kit",
]

JOB_TYPES = [
    "HVAC Repair", "HVAC Maintenance", "Plumbing Repair", "Electrical Repair",
    "Appliance Service", "Furnace Inspection", "AC Installation",
    "Water Heater Service", "Duct Cleaning", "Thermostat Setup",
]

PART_CATEGORIES = ["HVAC", "Electrical", "Plumbing", "General"]

SHIFT_PATTERNS = [
    ("07:00", "17:00"),
    ("07:30", "17:30"),
    ("08:00", "18:00"),
    ("06:30", "16:30"),
]


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def time_to_min(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def min_to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)

    R = SCALE["rows_per_table"]
    NF = SCALE["num_workspace_files"]

    num_technicians = R
    num_jobs = R * 2
    num_zones = max(6, int(math.ceil(math.sqrt(R))) + 3)
    num_parts = max(R, 15)

    zones = ZONE_POOL[:num_zones]
    zone_coords = {z: ZONE_COORDS[z] for z in zones}

    # ==================== DATABASE ====================
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS technicians (
        tech_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        skill_level INTEGER NOT NULL,
        van_id TEXT NOT NULL,
        shift_start TEXT NOT NULL,
        shift_end TEXT NOT NULL,
        home_zone TEXT NOT NULL,
        phone TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'available'
    );
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        customer_name TEXT NOT NULL,
        address TEXT NOT NULL,
        zone TEXT NOT NULL,
        job_type TEXT NOT NULL,
        priority_tier TEXT NOT NULL,
        estimated_duration_min INTEGER NOT NULL,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        required_skill_level INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
    );
    CREATE TABLE IF NOT EXISTS parts_catalog (
        part_id TEXT PRIMARY KEY,
        part_name TEXT NOT NULL,
        category TEXT NOT NULL,
        weight_kg REAL NOT NULL,
        unit_cost REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS parts_inventory (
        inv_id INTEGER PRIMARY KEY AUTOINCREMENT,
        van_id TEXT NOT NULL,
        part_id TEXT NOT NULL,
        quantity INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS traffic_conditions (
        segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_zone TEXT NOT NULL,
        to_zone TEXT NOT NULL,
        base_travel_min REAL NOT NULL,
        congestion_factor REAL NOT NULL,
        road_condition TEXT NOT NULL,
        last_updated TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS job_parts (
        req_id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        part_id TEXT NOT NULL,
        quantity_needed INTEGER NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(job_id),
        FOREIGN KEY (part_id) REFERENCES parts_catalog(part_id)
    );
    """)

    # ---------- Technicians ----------
    tech_rows = []
    for i in range(num_technicians):
        tech_id = f"TECH_{i + 1:03d}"
        name = fake.name()
        # Ensure skill coverage: at least a few high-skill techs
        if i < 2:
            skill = 5
        elif i < 5:
            skill = 4
        else:
            skill = random.choices([1, 2, 3, 4, 5], weights=[5, 15, 40, 25, 15], k=1)[0]
        van_id = f"VAN_{i + 1:03d}"
        shift = SHIFT_PATTERNS[i % len(SHIFT_PATTERNS)]
        home_zone = zones[i % len(zones)]
        phone = fake.phone_number()
        tech_rows.append((tech_id, name, skill, van_id, shift[0], shift[1],
                          home_zone, phone, "available"))
    cur.executemany("INSERT INTO technicians VALUES (?,?,?,?,?,?,?,?,?)", tech_rows)

    # ---------- Parts Catalog ----------
    parts_rows = []
    for i in range(num_parts):
        pid = f"PART_{i + 1:03d}"
        pname = PART_NAMES[i] if i < len(PART_NAMES) else f"Component_{i + 1}"
        cat = PART_CATEGORIES[i % len(PART_CATEGORIES)]
        wt = round(random.uniform(0.1, 12.0), 2)
        cost = round(random.uniform(5.0, 450.0), 2)
        parts_rows.append((pid, pname, cat, wt, cost))
    cur.executemany("INSERT INTO parts_catalog VALUES (?,?,?,?,?)", parts_rows)

    # ---------- Parts Inventory ----------
    # Each van carries 6-10 part types with quantity 2-5
    inv_rows = []
    van_parts_map = {}  # van_id -> {part_id: qty}
    for i in range(num_technicians):
        van_id = f"VAN_{i + 1:03d}"
        n_carry = random.randint(6, min(10, num_parts))
        carried_indices = random.sample(range(num_parts), n_carry)
        van_parts_map[van_id] = {}
        for pi in carried_indices:
            pid = f"PART_{pi + 1:03d}"
            qty = random.randint(2, 5)
            inv_rows.append((van_id, pid, qty))
            van_parts_map[van_id][pid] = qty
    cur.executemany(
        "INSERT INTO parts_inventory (van_id, part_id, quantity) VALUES (?,?,?)",
        inv_rows,
    )

    # ---------- Part Substitutions (workspace config) ----------
    substitutions = {}
    for i in range(0, num_parts - 1, 3):
        a = f"PART_{i + 1:03d}"
        b = f"PART_{i + 2:03d}"
        substitutions.setdefault(a, []).append(b)
        substitutions.setdefault(b, []).append(a)

    # ---------- Jobs (with pre-assignment feasibility) ----------
    priority_tiers = ["P1", "P2", "P3", "P4"]
    p_weights = [0.10, 0.20, 0.40, 0.30]
    durations = [30, 45, 60, 75, 90]

    job_rows = []
    jp_rows = []

    for i in range(num_jobs):
        jid = f"JOB_{i + 1:03d}"
        cname = fake.name()
        addr = fake.street_address()
        zone = random.choice(zones)
        jtype = random.choice(JOB_TYPES)
        prio = random.choices(priority_tiers, weights=p_weights, k=1)[0]
        dur = random.choice(durations)

        # Pre-assign to a target technician for feasibility
        target_idx = i % num_technicians
        target_skill = tech_rows[target_idx][2]
        target_van_id = tech_rows[target_idx][3]
        target_shift_start = time_to_min(tech_rows[target_idx][4])
        target_shift_end = time_to_min(tech_rows[target_idx][5])

        # Required skill: 1 to target_skill
        req_skill = random.randint(1, max(1, target_skill))

        # Time window: 3-5 hour window within target tech's shift
        earliest = max(target_shift_start, 7 * 60)
        latest = min(target_shift_end, 18 * 60)
        window_width = random.randint(3, 5) * 60  # 3-5 hours in minutes
        ws_min = random.randint(earliest, max(earliest, latest - window_width - dur))
        we_min = min(ws_min + window_width, latest)
        # Ensure window can fit the job
        if we_min - ws_min < dur + 15:
            we_min = min(ws_min + dur + 120, latest)

        window_start = min_to_time(ws_min)
        window_end = min_to_time(we_min)

        job_rows.append((jid, cname, addr, zone, jtype, prio, dur,
                         window_start, window_end, req_skill, "pending"))

        # Required parts: 1-2 from target van's inventory
        target_parts = list(van_parts_map[target_van_id].keys())
        n_req = min(random.randint(1, 2), len(target_parts))
        req_parts = random.sample(target_parts, n_req)
        for pid in req_parts:
            jp_rows.append((jid, pid, 1))

    cur.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)", job_rows)
    cur.executemany(
        "INSERT INTO job_parts (job_id, part_id, quantity_needed) VALUES (?,?,?)",
        jp_rows,
    )

    # ---------- Traffic Conditions ----------
    traffic_rows = []
    for fz in zones:
        for tz in zones:
            if fz == tz:
                continue
            lat1, lon1 = zone_coords[fz]
            lat2, lon2 = zone_coords[tz]
            dist = haversine_miles(lat1, lon1, lat2, lon2)
            base_min = round(max(5.0, dist * 3.0 + random.uniform(-2, 4)), 1)
            cong = round(random.uniform(0.8, 2.0), 2)
            road = random.choices(["good", "fair", "poor"], weights=[50, 35, 15], k=1)[0]
            ts = f"2026-04-23 {random.randint(6, 9):02d}:{random.randint(0, 59):02d}:00"
            traffic_rows.append((fz, tz, base_min, cong, road, ts))
    cur.executemany(
        "INSERT INTO traffic_conditions "
        "(from_zone, to_zone, base_travel_min, congestion_factor, road_condition, last_updated) "
        "VALUES (?,?,?,?,?,?)",
        traffic_rows,
    )

    conn.commit()
    conn.close()

    # ==================== WORKSPACE FILES ====================

    # ----- Fixed configuration files -----

    # 1. priority_config.yaml
    priority_config = {
        "tiers": {
            "P1": {"label": "Emergency", "max_response_minutes": 60, "scheduling_weight": 4.0},
            "P2": {"label": "Urgent", "max_response_minutes": 120, "scheduling_weight": 3.0},
            "P3": {"label": "Standard", "max_response_minutes": 240, "scheduling_weight": 2.0},
            "P4": {"label": "Routine", "max_response_minutes": 480, "scheduling_weight": 1.0},
        },
        "ordering_rule": (
            "Assign jobs with lower tier numbers first. "
            "Within the same tier, assign jobs with the earliest window_end first."
        ),
    }
    with open(os.path.join(workspace, "priority_config.yaml"), "w") as f:
        yaml.dump(priority_config, f, default_flow_style=False, sort_keys=False)

    # 2. scheduling_rules.json
    sched_rules = {
        "max_jobs_per_technician": 6,
        "road_condition_multipliers": {
            "good": 1.0,
            "fair": 1.15,
            "poor": 1.35,
        },
        "same_zone_travel_minutes": 5,
        "travel_time_formula": (
            "base_travel_min * congestion_factor * "
            "road_condition_multiplier * zone_adjustment_factor"
        ),
    }
    with open(os.path.join(workspace, "scheduling_rules.json"), "w") as f:
        json.dump(sched_rules, f, indent=2)

    # 3. part_substitutions.json
    with open(os.path.join(workspace, "part_substitutions.json"), "w") as f:
        json.dump(substitutions, f, indent=2)

    # 4. travel_adjustments.csv
    adj_zones = random.sample(zones, min(len(zones), max(3, len(zones) // 2)))
    adj_types = ["construction", "school_zone", "event_detour", "road_closure_detour"]
    adj_rows = []
    for z in adj_zones:
        atype = random.choice(adj_types)
        mult = round(random.uniform(1.05, 1.40), 2)
        note = f"{atype.replace('_', ' ').title()} affecting {z} area"
        adj_rows.append({"zone": z, "adjustment_type": atype,
                         "multiplier": mult, "notes": note})
    with open(os.path.join(workspace, "travel_adjustments.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["zone", "adjustment_type", "multiplier", "notes"])
        w.writeheader()
        w.writerows(adj_rows)

    # 5. service_level_agreements.md
    sla_text = (
        "All technicians must comply with the maximum job limit per shift as stated "
        "in the scheduling rules.\n\n"
        "Emergency and urgent jobs receive priority as defined in the priority "
        "configuration. Standard and routine jobs should be scheduled to maximize "
        "daily throughput after all higher-priority work has been assigned.\n\n"
        "When multiple technicians are eligible for a job, the one with the shortest "
        "travel time from their current position should be preferred. Ties are broken "
        "by ascending technician identifier.\n"
    )
    with open(os.path.join(workspace, "service_level_agreements.md"), "w") as f:
        f.write(sla_text)

    # ----- Scalable data files -----

    num_gps_files = NF // 2
    num_site_files = NF - num_gps_files

    # GPS tracking CSVs
    techs_per_gps = max(1, math.ceil(num_technicians / num_gps_files))
    for batch_idx in range(num_gps_files):
        start = batch_idx * techs_per_gps
        end = min(start + techs_per_gps, num_technicians)
        if batch_idx == num_gps_files - 1:
            end = num_technicians
        records = []
        for ti in range(start, end):
            tech_id = f"TECH_{ti + 1:03d}"
            home_zone = tech_rows[ti][6]
            base_lat, base_lng = zone_coords[home_zone]
            lat = round(base_lat + random.uniform(-0.008, 0.008), 6)
            lng = round(base_lng + random.uniform(-0.008, 0.008), 6)
            speed = round(random.uniform(0, 35), 1)
            heading = random.randint(0, 359)
            ts = f"2026-04-23 {random.randint(6, 8):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
            records.append({
                "tech_id": tech_id,
                "latitude": lat,
                "longitude": lng,
                "current_zone": home_zone,
                "speed_mph": speed,
                "heading_degrees": heading,
                "timestamp": ts,
            })
        fname = f"gps_tracking_batch_{batch_idx + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "tech_id", "latitude", "longitude", "current_zone",
                "speed_mph", "heading_degrees", "timestamp",
            ])
            w.writeheader()
            w.writerows(records)

    # Site detail JSONs
    jobs_per_site = max(1, math.ceil(num_jobs / num_site_files))
    for batch_idx in range(num_site_files):
        start = batch_idx * jobs_per_site
        end = min(start + jobs_per_site, num_jobs)
        if batch_idx == num_site_files - 1:
            end = num_jobs
        records = []
        for ji in range(start, end):
            jid = f"JOB_{ji + 1:03d}"
            job_ws = job_rows[ji][7]
            job_we = job_rows[ji][8]
            ws_m = time_to_min(job_ws)
            we_m = time_to_min(job_we)
            job_dur = job_rows[ji][6]

            # 30% chance of narrower access window
            if random.random() < 0.3:
                acc_start = ws_m + 30
                acc_end = we_m - 30
                if acc_end - acc_start < job_dur + 15:
                    acc_start = ws_m
                    acc_end = we_m
            else:
                acc_start = ws_m
                acc_end = we_m

            records.append({
                "job_id": jid,
                "site_access_code": str(random.randint(1000, 9999)),
                "parking_instructions": random.choice([
                    "Use rear parking lot", "Street parking only",
                    "Visitor spot in garage level 2", "Park in driveway",
                    "Loading dock access via side road",
                ]),
                "contact_name": fake.name(),
                "contact_phone": fake.phone_number(),
                "access_start": min_to_time(acc_start),
                "access_end": min_to_time(acc_end),
                "floor_level": random.randint(1, 5),
                "special_instructions": random.choice([
                    "Ring doorbell twice", "Call on arrival",
                    "Use service entrance", "Check in at front desk",
                    "Gate code required - see access code", "",
                ]),
            })
        fname = f"site_details_batch_{batch_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(records, f, indent=2)

    print(f"Database created at {db_path}")
    print(f"Workspace populated at {workspace}/")
    print(f"  Technicians: {num_technicians}, Jobs: {num_jobs}, "
          f"Zones: {num_zones}, Parts: {num_parts}")
    print(f"  Scalable files: {NF} ({num_gps_files} GPS + {num_site_files} site)")
    print(f"  Fixed config files: 5")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
