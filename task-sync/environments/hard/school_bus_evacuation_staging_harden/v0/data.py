"""
School Bus Evacuation Staging - Data Generation Script

Generates database and workspace files for the evacuation planning task.
Cross-references student addresses, bus capacity/GPS logs, shelter locations
with capacity limits, and road network bridge weight restrictions.
"""
import argparse
import os
import json
import csv
import sqlite3
import random
import math
import yaml
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 30,
    "num_workspace_files": 10,
}

# ---- deterministic seeding ----
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
Faker.seed(SEED)
fake = Faker()


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    R = SCALE["rows_per_table"]
    W = SCALE["num_workspace_files"]
    num_zones = max(4, R // 5)

    # ==================================================================
    # TABLE 1 : schools  (>= R rows)
    # ==================================================================
    c.execute("""CREATE TABLE IF NOT EXISTS schools (
        school_id   INTEGER PRIMARY KEY,
        name        TEXT NOT NULL,
        lat         REAL NOT NULL,
        lon         REAL NOT NULL,
        zone_id     INTEGER NOT NULL,
        address     TEXT NOT NULL
    )""")

    school_types = ["Elementary", "Middle School", "High School",
                    "Academy", "Preparatory", "Magnet School"]
    schools = []
    used_names = set()
    grid_side = int(math.sqrt(num_zones)) + 1
    for i in range(R):
        while True:
            name = f"{fake.last_name()} {random.choice(school_types)}"
            if name not in used_names:
                used_names.add(name)
                break
        zone_id = (i % num_zones) + 1
        base_lat = 33.5 + (zone_id % grid_side) * 0.15
        base_lon = -117.5 - (zone_id // grid_side) * 0.15
        lat = round(base_lat + random.uniform(-0.05, 0.05), 6)
        lon = round(base_lon + random.uniform(-0.05, 0.05), 6)
        school = dict(school_id=i + 1, name=name, lat=lat, lon=lon,
                      zone_id=zone_id, address=fake.street_address())
        schools.append(school)
        c.execute("INSERT INTO schools VALUES (?,?,?,?,?,?)",
                  (school["school_id"], school["name"], school["lat"],
                   school["lon"], school["zone_id"], school["address"]))

    # ==================================================================
    # TABLE 2 : students  (>= R rows, FK -> schools)
    # ==================================================================
    c.execute("""CREATE TABLE IF NOT EXISTS students (
        student_id    INTEGER PRIMARY KEY,
        name          TEXT NOT NULL,
        school_id     INTEGER NOT NULL,
        grade         INTEGER NOT NULL,
        home_lat      REAL NOT NULL,
        home_lon      REAL NOT NULL,
        special_needs INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (school_id) REFERENCES schools(school_id)
    )""")

    students = []
    sid = 1
    enrollments = {}
    for s in schools:
        enroll = random.randint(max(3, R // 10), max(8, R // 4))
        enrollments[s["school_id"]] = enroll
        for _ in range(enroll):
            st = dict(
                student_id=sid, name=fake.name(), school_id=s["school_id"],
                grade=random.randint(1, 12),
                home_lat=round(s["lat"] + random.uniform(-0.03, 0.03), 6),
                home_lon=round(s["lon"] + random.uniform(-0.03, 0.03), 6),
                special_needs=1 if random.random() < 0.15 else 0,
            )
            students.append(st)
            sid += 1
    for st in students:
        c.execute("INSERT INTO students VALUES (?,?,?,?,?,?,?)",
                  (st["student_id"], st["name"], st["school_id"], st["grade"],
                   st["home_lat"], st["home_lon"], st["special_needs"]))

    # ==================================================================
    # TABLE 3 : buses  (>= R rows)
    # ==================================================================
    c.execute("""CREATE TABLE IF NOT EXISTS buses (
        bus_id                INTEGER PRIMARY KEY,
        plate_number          TEXT NOT NULL,
        capacity              INTEGER NOT NULL,
        empty_weight_tons     REAL NOT NULL,
        depot_zone_id         INTEGER NOT NULL,
        wheelchair_accessible INTEGER NOT NULL DEFAULT 0
    )""")

    buses = []
    num_buses = max(R, int(R * 2.5))
    for i in range(num_buses):
        bus = dict(
            bus_id=i + 1,
            plate_number=f"BUS-{fake.bothify('??###').upper()}",
            capacity=random.choice([20, 25, 30, 35, 40, 45]),
            empty_weight_tons=round(random.uniform(8.0, 14.0), 2),
            depot_zone_id=random.randint(1, num_zones),
            wheelchair_accessible=1 if random.random() < 0.3 else 0,
        )
        buses.append(bus)
        c.execute("INSERT INTO buses VALUES (?,?,?,?,?,?)",
                  (bus["bus_id"], bus["plate_number"], bus["capacity"],
                   bus["empty_weight_tons"], bus["depot_zone_id"],
                   bus["wheelchair_accessible"]))

    # ==================================================================
    # TABLE 4 : shelters  (>= R rows)
    # ==================================================================
    c.execute("""CREATE TABLE IF NOT EXISTS shelters (
        shelter_id            INTEGER PRIMARY KEY,
        name                  TEXT NOT NULL,
        lat                   REAL NOT NULL,
        lon                   REAL NOT NULL,
        base_capacity         INTEGER NOT NULL,
        medical_facility      INTEGER NOT NULL DEFAULT 0,
        wheelchair_accessible INTEGER NOT NULL DEFAULT 0,
        address               TEXT NOT NULL
    )""")

    shelter_types = ["Community Center", "Recreation Center", "Church Hall",
                     "School Gym", "Convention Center", "Armory", "Civic Center"]
    shelters = []
    used_shelter = set()
    for i in range(R):
        while True:
            name = f"{fake.last_name()} {random.choice(shelter_types)}"
            if name not in used_shelter:
                used_shelter.add(name)
                break
        zone_id = (i % num_zones) + 1
        base_lat = 33.5 + (zone_id % grid_side) * 0.15
        base_lon = -117.5 - (zone_id // grid_side) * 0.15
        shelter = dict(
            shelter_id=i + 1, name=name,
            lat=round(base_lat + random.uniform(-0.07, 0.07), 6),
            lon=round(base_lon + random.uniform(-0.07, 0.07), 6),
            base_capacity=random.randint(30, 150),
            medical_facility=1 if random.random() < 0.3 else 0,
            wheelchair_accessible=1 if random.random() < 0.4 else 0,
            address=fake.street_address(),
        )
        shelters.append(shelter)
        c.execute("INSERT INTO shelters VALUES (?,?,?,?,?,?,?,?)",
                  (shelter["shelter_id"], shelter["name"], shelter["lat"],
                   shelter["lon"], shelter["base_capacity"],
                   shelter["medical_facility"], shelter["wheelchair_accessible"],
                   shelter["address"]))

    # ==================================================================
    # TABLE 5 : road_segments  (>= R rows)
    # ==================================================================
    c.execute("""CREATE TABLE IF NOT EXISTS road_segments (
        segment_id               INTEGER PRIMARY KEY,
        road_name                TEXT NOT NULL,
        distance_km              REAL NOT NULL,
        has_bridge               INTEGER NOT NULL DEFAULT 0,
        bridge_weight_limit_tons REAL
    )""")

    road_prefixes = [
        "Oak", "Maple", "Pine", "Cedar", "Elm", "Walnut", "Birch", "Willow",
        "Main", "First", "Second", "Third", "Park", "Lake", "River", "Hill",
        "Washington", "Lincoln", "Jefferson", "Adams", "Madison", "Spruce",
        "Ash", "Cherry", "Poplar", "Sycamore", "Magnolia", "Cypress",
    ]
    road_suffixes = ["St", "Ave", "Blvd", "Dr", "Rd", "Ln", "Way", "Ct"]
    num_segments = max(R, R * 2)
    segments = []
    for i in range(num_segments):
        has_bridge = 1 if random.random() < 0.18 else 0
        bridge_limit = round(random.uniform(16.0, 32.0), 1) if has_bridge else None
        seg = dict(
            segment_id=i + 1,
            road_name=f"{random.choice(road_prefixes)} {random.choice(road_suffixes)}",
            distance_km=round(random.uniform(0.5, 8.0), 2),
            has_bridge=has_bridge,
            bridge_weight_limit_tons=bridge_limit,
        )
        segments.append(seg)
        c.execute("INSERT INTO road_segments VALUES (?,?,?,?,?)",
                  (seg["segment_id"], seg["road_name"], seg["distance_km"],
                   seg["has_bridge"], seg["bridge_weight_limit_tons"]))

    # ==================================================================
    # TABLE 6 : routes  (>= R rows, FK -> schools, shelters)
    # ==================================================================
    c.execute("""CREATE TABLE IF NOT EXISTS routes (
        route_id             INTEGER PRIMARY KEY,
        school_id            INTEGER NOT NULL,
        shelter_id           INTEGER NOT NULL,
        segment_ids          TEXT NOT NULL,
        total_distance_km    REAL NOT NULL,
        estimated_travel_min REAL NOT NULL,
        FOREIGN KEY (school_id)  REFERENCES schools(school_id),
        FOREIGN KEY (shelter_id) REFERENCES shelters(shelter_id)
    )""")

    routes = []
    route_id = 1
    routes_per_school = max(3, min(6, len(shelters) // 3))
    for school in schools:
        dists = sorted(
            [(haversine_km(school["lat"], school["lon"], sh["lat"], sh["lon"]), sh)
             for sh in shelters],
            key=lambda x: x[0],
        )
        for _, shelter in dists[:routes_per_school]:
            n_segs = random.randint(2, 5)
            chosen = random.sample(range(num_segments), n_segs)
            seg_ids = sorted([segments[s]["segment_id"] for s in chosen])
            total_dist = round(sum(segments[s]["distance_km"] for s in chosen), 2)
            travel_min = round(total_dist / 0.6, 1)  # ~36 km/h avg
            route = dict(
                route_id=route_id, school_id=school["school_id"],
                shelter_id=shelter["shelter_id"],
                segment_ids=json.dumps(seg_ids),
                total_distance_km=total_dist,
                estimated_travel_min=travel_min,
            )
            routes.append(route)
            c.execute("INSERT INTO routes VALUES (?,?,?,?,?,?)",
                      (route["route_id"], route["school_id"],
                       route["shelter_id"], route["segment_ids"],
                       route["total_distance_km"], route["estimated_travel_min"]))
            route_id += 1

    conn.commit()

    # ==================================================================
    # WORKSPACE — fixed policy / config files  (not counted in SCALE)
    # ==================================================================

    # 1. evacuation_policy.yaml
    policy = {
        "min_fuel_threshold_pct": 30,
        "passenger_weight_tons": 0.07,
        "max_travel_time_min": 60,
        "special_needs_require_accessible_bus": True,
        "shelter_assignment_strategy": "nearest_feasible",
        "loading_order": "special_needs_first_then_grade_ascending",
        "max_load_factor": 1.0,
    }
    with open(os.path.join(workspace, "evacuation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. shelter_status.json  — some shelters closed or reduced
    shelter_adj = {}
    for shelter in shelters:
        r = random.random()
        if r < 0.08:
            shelter_adj[str(shelter["shelter_id"])] = dict(
                status="closed", effective_capacity=0,
                reason="Structural damage from recent storm")
        elif r < 0.22:
            cap = int(shelter["base_capacity"] * random.uniform(0.3, 0.7))
            shelter_adj[str(shelter["shelter_id"])] = dict(
                status="reduced", effective_capacity=cap,
                reason=random.choice([
                    "Partial roof damage", "HVAC system failure",
                    "Water main break", "Ongoing renovation"]))
    with open(os.path.join(workspace, "shelter_status.json"), "w") as f:
        json.dump(shelter_adj, f, indent=2)

    # 3. bridge_weight_updates.json — some bridges have lower limits
    bridge_segs = [s for s in segments if s["has_bridge"]]
    bridge_updates = {}
    for seg in bridge_segs:
        if random.random() < 0.30:
            new_lim = round(seg["bridge_weight_limit_tons"] * random.uniform(0.75, 0.95), 1)
            bridge_updates[str(seg["segment_id"])] = dict(
                original_limit_tons=seg["bridge_weight_limit_tons"],
                updated_limit_tons=new_lim,
                reason=random.choice([
                    "Recent inspection found corrosion",
                    "Temporary restriction due to construction",
                    "Structural assessment pending",
                    "Load-bearing capacity reassessed"]),
                effective_date="2026-04-01")
    with open(os.path.join(workspace, "bridge_weight_updates.json"), "w") as f:
        json.dump(bridge_updates, f, indent=2)

    # 4. evacuation_procedures.md — operational methodology (fixed document)
    procedures = """# District Evacuation Operations Manual

This manual, together with `evacuation_policy.yaml`, governs every dispatch
decision. Where a figure here conflicts with a baseline value in the district
records system, the operational updates described below take precedence.

## Bus deployability

A bus may be dispatched only if its `current_status` is `ready` AND its
`fuel_level_pct` is greater than or equal to `min_fuel_threshold_pct` from
`evacuation_policy.yaml`. Current readiness and fuel levels for the entire
fleet are recorded in the `bus_status_*.csv` files; buses listed as
`maintenance` must not be used under any circumstances.

## Loaded weight

The loaded weight of a bus in tonnes is computed as:

    loaded_weight_tons = empty_weight_tons + (number_of_riders * passenger_weight_tons)

where `passenger_weight_tons` comes from `evacuation_policy.yaml`.

## Bridge weight limits

A bus may travel a route only if its loaded weight does not exceed the
effective bridge weight limit on EVERY road segment along that route.
Segments without a bridge impose no weight restriction. For segments listed
in `bridge_weight_updates.json`, the `updated_limit_tons` value supersedes
the posted `bridge_weight_limit_tons`; for all other bridge segments the
posted limit applies.

## Shelter capacity and status

The effective capacity of a shelter is its `base_capacity` unless the
shelter appears in `shelter_status.json`, in which case the
`effective_capacity` recorded there overrides the base figure. Shelters with
status `closed` (effective capacity zero) must receive no students. The
total number of students sent to a shelter, across all schools and buses,
must not exceed its effective capacity.

## Shelter selection

A shelter is feasible for a school only if it is not closed, its remaining
effective capacity can absorb the students being sent there, and the route's
estimated travel time does not exceed `max_travel_time_min` from
`evacuation_policy.yaml`. Assign students to the nearest feasible shelter
first (`shelter_assignment_strategy: nearest_feasible`). If one shelter
cannot take all of a school's students, split them across multiple shelters
along different routes.

## Bus selection and loading

The maximum number of riders on a bus is its rated seating `capacity`
multiplied by `max_load_factor` from `evacuation_policy.yaml`. When bridge
constraints are tight, prefer the lightest available buses first. Students
who require a wheelchair-accessible vehicle — identified by cross-referencing
the `student_medical_*.csv` files with the special-needs flag on the student
roster — must ride wheelchair-accessible buses; per
`special_needs_require_accessible_bus` in the policy, any load that includes
such students must use an accessible bus. Riders are loaded in the order
given by `loading_order` in the policy: special-needs students first, then
remaining students by grade ascending.

## Road conditions

The `road_conditions_*.json` files record current surface condition and
speed multipliers for road segments, for situational awareness during
dispatch.
"""
    with open(os.path.join(workspace, "evacuation_procedures.md"), "w") as f:
        f.write(procedures)

    # ==================================================================
    # WORKSPACE — scalable data files  (counted in SCALE)
    # ==================================================================
    num_bus_files = max(1, round(W * 0.5))
    num_student_files = max(1, round(W * 0.3))
    num_road_files = max(1, W - num_bus_files - num_student_files)

    # --- bus_status_*.csv ---
    buses_per_file = max(1, math.ceil(len(buses) / num_bus_files))
    for fi in range(num_bus_files):
        batch = buses[fi * buses_per_file: (fi + 1) * buses_per_file]
        if not batch:
            batch = [buses[fi % len(buses)]]
        rows = []
        for bus in batch:
            cert = "CDL_special_needs" if bus["wheelchair_accessible"] else \
                   ("CDL_special_needs" if random.random() < 0.10 else "CDL_standard")
            rows.append(dict(
                bus_id=bus["bus_id"],
                fuel_level_pct=random.randint(25, 100),
                last_service_date=fake.date_between("-1y", "today").isoformat(),
                driver_name=fake.name(),
                driver_certification=cert,
                current_status="maintenance" if random.random() < 0.07 else "ready",
            ))
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"bus_status_{fi + 1}.csv"), index=False)

    # --- student_medical_*.csv ---
    special = [st for st in students if st["special_needs"]]
    normal_pool = [st for st in students if not st["special_needs"]]
    normal_sample = random.sample(normal_pool, min(len(special), len(normal_pool)))
    medical_pool = special + normal_sample
    random.shuffle(medical_pool)
    per_file = max(1, math.ceil(len(medical_pool) / num_student_files))
    for fi in range(num_student_files):
        batch = medical_pool[fi * per_file: (fi + 1) * per_file]
        if not batch:
            batch = [medical_pool[fi % len(medical_pool)]]
        rows = []
        for st in batch:
            wc = st["special_needs"] and random.random() < 0.4
            md = st["special_needs"] and random.random() < 0.3
            ai = st["special_needs"] and random.random() < 0.25
            rows.append(dict(
                student_id=st["student_id"],
                wheelchair_required=1 if wc else 0,
                medical_device=1 if md else 0,
                aide_required=1 if ai else 0,
                notes="Requires wheelchair-accessible vehicle" if wc else "",
            ))
        pd.DataFrame(rows).to_csv(
            os.path.join(workspace, f"student_medical_{fi + 1}.csv"), index=False)

    # --- road_conditions_*.json ---
    per_file = max(1, math.ceil(len(segments) / num_road_files))
    for fi in range(num_road_files):
        batch = segments[fi * per_file: (fi + 1) * per_file]
        if not batch:
            batch = [segments[fi % len(segments)]]
        data = []
        for seg in batch:
            cond = random.choices(["good", "fair", "poor"], weights=[0.6, 0.3, 0.1])[0]
            mult = {"good": 1.0, "fair": 0.75, "poor": 0.5}[cond]
            data.append(dict(
                segment_id=seg["segment_id"],
                condition=cond,
                speed_multiplier=mult,
                last_inspected=fake.date_between("-6m", "today").isoformat(),
            ))
        with open(os.path.join(workspace, f"road_conditions_{fi + 1}.json"), "w") as f:
            json.dump(data, f, indent=2)

    conn.close()
    total_ws = num_bus_files + num_student_files + num_road_files + 3
    print(f"Database : {db_path}")
    print(f"Workspace: {workspace}/ ({total_ws} files)")
    print(f"  Schools={len(schools)}  Students={len(students)}  "
          f"Buses={len(buses)}  Shelters={len(shelters)}  "
          f"Segments={len(segments)}  Routes={len(routes)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    args = p.parse_args()
    main(args.db_path, args.workspace)
