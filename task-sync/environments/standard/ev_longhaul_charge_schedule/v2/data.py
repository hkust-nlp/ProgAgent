import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 30,
}

BASE_TIME = datetime(2026, 4, 25, 6, 0, 0)

TERRAIN_CONFIGS = {
    "flat":        {"energy_factor": 1.00, "avg_speed_mph": 60},
    "rolling":     {"energy_factor": 1.15, "avg_speed_mph": 55},
    "hilly":       {"energy_factor": 1.30, "avg_speed_mph": 50},
    "mountainous": {"energy_factor": 1.50, "avg_speed_mph": 45},
}

WEIGHT_BRACKETS = [
    (20000, 0.85),
    (35000, 1.00),
    (50000, 1.15),
    (65000, 1.30),
    (80000, 1.50),
]


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    R = SCALE["rows_per_table"]
    NW = SCALE["num_workspace_files"]
    num_active = NW // 2

    # ===================== LOCATIONS =====================
    num_locs = max(R, num_active * 12 + 20)
    locs = []
    used_names = set()
    for i in range(num_locs):
        name = fake.city()
        attempt = 0
        while name in used_names and attempt < 200:
            name = fake.city()
            attempt += 1
        if name in used_names:
            name = f"{fake.city()} Jct {i}"
        used_names.add(name)
        lat = round(30 + 15 * (i / max(1, num_locs - 1)) + random.uniform(-0.5, 0.5), 4)
        lon = round(-95 + 25 * (i / max(1, num_locs - 1)) + random.uniform(-0.5, 0.5), 4)
        locs.append({"location_id": f"L{i+1:04d}", "name": name, "lat": lat, "lon": lon})

    c.execute("""CREATE TABLE locations (
        location_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL
    )""")
    for loc in locs:
        c.execute("INSERT INTO locations VALUES (?,?,?,?)",
                  (loc["location_id"], loc["name"], loc["lat"], loc["lon"]))

    # ===================== TRUCKS =====================
    models = ["Freightliner eCascadia", "Tesla Semi", "Volvo VNR Electric",
              "Kenworth T680E", "Peterbilt 579EV"]
    trucks = []
    for i in range(R):
        trucks.append({
            "truck_id": f"TRK_{i+1:04d}",
            "model": models[i % len(models)],
            "capacity": float(random.choice([400, 450, 500, 550, 600])),
            "efficiency": round(random.uniform(1.3, 1.8), 2),
            "status": "active" if i < num_active else random.choice(["active", "maintenance", "idle"]),
        })

    c.execute("""CREATE TABLE trucks (
        truck_id TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        battery_capacity_kwh REAL NOT NULL,
        base_efficiency_kwh_per_mile REAL NOT NULL,
        status TEXT NOT NULL
    )""")
    for t in trucks:
        c.execute("INSERT INTO trucks VALUES (?,?,?,?,?)",
                  (t["truck_id"], t["model"], t["capacity"], t["efficiency"], t["status"]))

    # ===================== DRIVERS =====================
    drivers = []
    for i in range(R):
        drivers.append({
            "driver_id": f"DRV_{i+1:04d}",
            "name": fake.name(),
            "license": "CDL-A" if i % 3 != 2 else "CDL-B",
            "hire_date": fake.date_between(start_date="-5y", end_date="-6m").isoformat(),
            "status": "available" if i < num_active else random.choice(["available", "off_duty", "on_leave"]),
        })

    c.execute("""CREATE TABLE drivers (
        driver_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        license_class TEXT NOT NULL,
        hire_date TEXT NOT NULL,
        status TEXT NOT NULL
    )""")
    for d in drivers:
        c.execute("INSERT INTO drivers VALUES (?,?,?,?,?)",
                  (d["driver_id"], d["name"], d["license"], d["hire_date"], d["status"]))

    # ===================== BUILD ROUTES FOR ACTIVE DELIVERIES =====================
    terrains = ["flat", "rolling", "hilly", "mountainous"]
    terrain_w = [0.4, 0.3, 0.2, 0.1]

    active_route_info = []
    station_locs_needed = set()

    for d in range(num_active):
        n_seg = random.randint(5, 7)
        third = max(1, num_locs // 3)
        origin_idx = random.randint(0, third - 1)
        dest_idx = random.randint(2 * third, num_locs - 1)
        mid_pool = list(range(third, 2 * third))
        n_mid = min(n_seg - 1, len(mid_pool))
        mids = sorted(random.sample(mid_pool, n_mid))
        route = [origin_idx] + mids + [dest_idx]

        segs = []
        for si in range(len(route) - 1):
            segs.append({
                "from_idx": route[si],
                "to_idx": route[si + 1],
                "distance": round(random.uniform(50, 90), 1),
                "terrain": random.choices(terrains, weights=terrain_w, k=1)[0],
            })
        active_route_info.append((route, segs))
        for idx in route[1:-1]:
            station_locs_needed.add(idx)

    # ===================== CHARGING STATIONS =====================
    station_loc_list = sorted(station_locs_needed)
    extra_pool = [i for i in range(num_locs) if i not in station_locs_needed]
    random.shuffle(extra_pool)
    while len(station_loc_list) < R:
        if extra_pool:
            station_loc_list.append(extra_pool.pop())
        else:
            station_loc_list.append(random.randint(0, num_locs - 1))
    station_loc_list = sorted(set(station_loc_list))
    extra2 = [i for i in range(num_locs) if i not in set(station_loc_list)]
    random.shuffle(extra2)
    while len(station_loc_list) < R:
        if extra2:
            station_loc_list.append(extra2.pop())
        else:
            break
    station_loc_list = sorted(station_loc_list)

    ctypes = ["CCS", "CHAdeMO", "MCS"]
    stations = []
    for i, loc_idx in enumerate(station_loc_list):
        ports = random.randint(2, 8)
        occ = random.randint(0, ports)
        wait = 0 if occ < ports else random.randint(5, 40)
        stations.append({
            "station_id": f"STN_{i+1:04d}",
            "location_id": locs[loc_idx]["location_id"],
            "name": f"ChargeHub {locs[loc_idx]['name']}",
            "charger_type": ctypes[i % len(ctypes)],
            "rate": float(random.choice([150, 200, 250, 300, 350])),
            "ports": ports,
            "occupied": occ,
            "wait": wait,
        })

    c.execute("""CREATE TABLE charging_stations (
        station_id TEXT PRIMARY KEY,
        location_id TEXT NOT NULL,
        name TEXT NOT NULL,
        charger_type TEXT NOT NULL,
        charge_rate_kw REAL NOT NULL,
        num_ports INTEGER NOT NULL,
        occupied_ports INTEGER NOT NULL,
        estimated_wait_min INTEGER NOT NULL,
        FOREIGN KEY (location_id) REFERENCES locations(location_id)
    )""")
    for s in stations:
        c.execute("INSERT INTO charging_stations VALUES (?,?,?,?,?,?,?,?)",
                  (s["station_id"], s["location_id"], s["name"], s["charger_type"],
                   s["rate"], s["ports"], s["occupied"], s["wait"]))

    # ===================== DELIVERIES =====================
    cargo_descs = ["Electronics", "Auto Parts", "Consumer Goods", "Medical Supplies",
                   "Food Products", "Building Materials", "Textiles", "Machinery",
                   "Chemicals", "Furniture"]
    prios = ["standard", "express", "critical"]
    deliveries = []
    active_socs = []
    active_cargo_weights = []

    for i in range(R):
        del_id = f"DEL_{i+1:04d}"
        truck_id = trucks[i % len(trucks)]["truck_id"]
        driver_id = drivers[i % len(drivers)]["driver_id"]

        if i < num_active:
            route, segs = active_route_info[i]
            origin_id = locs[route[0]]["location_id"]
            dest_id = locs[route[-1]]["location_id"]
            status = "pending"
            prio = prios[i % len(prios)]
            total_dist = sum(s["distance"] for s in segs)
            min_hours = total_dist / 55.0
            deadline = BASE_TIME + timedelta(hours=min_hours * 2.0 + 6)
            cargo_w = random.randint(25000, 60000)
            soc = round(random.uniform(65, 85), 1)
            active_socs.append(soc)
            active_cargo_weights.append(cargo_w)
        else:
            origin_id = locs[random.randint(0, num_locs - 1)]["location_id"]
            dest_id = locs[random.randint(0, num_locs - 1)]["location_id"]
            while dest_id == origin_id and num_locs > 1:
                dest_id = locs[random.randint(0, num_locs - 1)]["location_id"]
            status = random.choice(["completed", "cancelled"])
            prio = random.choice(prios)
            deadline = BASE_TIME + timedelta(hours=random.randint(12, 72))
            cargo_w = random.randint(15000, 70000)

        deliveries.append({
            "delivery_id": del_id,
            "truck_id": truck_id,
            "driver_id": driver_id,
            "origin_id": origin_id,
            "dest_id": dest_id,
            "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%S"),
            "priority": prio,
            "status": status,
            "cargo_desc": cargo_descs[i % len(cargo_descs)],
        })

    c.execute("""CREATE TABLE deliveries (
        delivery_id TEXT PRIMARY KEY,
        truck_id TEXT NOT NULL,
        driver_id TEXT NOT NULL,
        origin_location_id TEXT NOT NULL,
        destination_location_id TEXT NOT NULL,
        deadline TEXT NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        cargo_description TEXT NOT NULL,
        FOREIGN KEY (truck_id) REFERENCES trucks(truck_id),
        FOREIGN KEY (driver_id) REFERENCES drivers(driver_id),
        FOREIGN KEY (origin_location_id) REFERENCES locations(location_id),
        FOREIGN KEY (destination_location_id) REFERENCES locations(location_id)
    )""")
    for d in deliveries:
        c.execute("INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?)",
                  (d["delivery_id"], d["truck_id"], d["driver_id"],
                   d["origin_id"], d["dest_id"], d["deadline"],
                   d["priority"], d["status"], d["cargo_desc"]))

    # ===================== ROUTE SEGMENTS =====================
    all_segs = []
    seg_ctr = 0

    for i in range(num_active):
        del_id = deliveries[i]["delivery_id"]
        _, segs = active_route_info[i]
        for si, s in enumerate(segs):
            seg_ctr += 1
            all_segs.append({
                "segment_id": f"SEG_{seg_ctr:05d}",
                "delivery_id": del_id,
                "order": si + 1,
                "from_id": locs[s["from_idx"]]["location_id"],
                "to_id": locs[s["to_idx"]]["location_id"],
                "distance": s["distance"],
                "terrain": s["terrain"],
            })

    for i in range(num_active, R):
        del_id = deliveries[i]["delivery_id"]
        n_s = random.randint(3, 5)
        for si in range(n_s):
            seg_ctr += 1
            fi = random.randint(0, num_locs - 1)
            ti = random.randint(0, num_locs - 1)
            while ti == fi and num_locs > 1:
                ti = random.randint(0, num_locs - 1)
            all_segs.append({
                "segment_id": f"SEG_{seg_ctr:05d}",
                "delivery_id": del_id,
                "order": si + 1,
                "from_id": locs[fi]["location_id"],
                "to_id": locs[ti]["location_id"],
                "distance": round(random.uniform(30, 100), 1),
                "terrain": random.choice(terrains),
            })

    c.execute("""CREATE TABLE route_segments (
        segment_id TEXT PRIMARY KEY,
        delivery_id TEXT NOT NULL,
        segment_order INTEGER NOT NULL,
        from_location_id TEXT NOT NULL,
        to_location_id TEXT NOT NULL,
        distance_miles REAL NOT NULL,
        terrain_type TEXT NOT NULL,
        FOREIGN KEY (delivery_id) REFERENCES deliveries(delivery_id),
        FOREIGN KEY (from_location_id) REFERENCES locations(location_id),
        FOREIGN KEY (to_location_id) REFERENCES locations(location_id)
    )""")
    for s in all_segs:
        c.execute("INSERT INTO route_segments VALUES (?,?,?,?,?,?,?)",
                  (s["segment_id"], s["delivery_id"], s["order"],
                   s["from_id"], s["to_id"], s["distance"], s["terrain"]))

    # ===================== WORKSPACE — FIXED CONFIG FILES =====================

    # 1. efficiency_factors.csv
    with open(os.path.join(workspace, "efficiency_factors.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["terrain_type", "energy_factor", "avg_speed_mph"])
        for t_name, cfg in TERRAIN_CONFIGS.items():
            w.writerow([t_name, f"{cfg['energy_factor']:.2f}", str(cfg["avg_speed_mph"])])

    # 2. charging_policy.json
    with open(os.path.join(workspace, "charging_policy.json"), "w") as f:
        json.dump({
            "min_soc_pct": 15,
            "target_charge_soc_pct": 85,
            "charge_time_formula": "charge_time_min = (target_kwh - current_kwh) / charge_rate_kw * 60",
            "station_selection_rule": "Choose the station with the shortest estimated_wait_min. Break ties by station_id in ascending lexicographic order."
        }, f, indent=2)

    # 3. hos_regulations.yaml
    with open(os.path.join(workspace, "hos_regulations.yaml"), "w") as f:
        f.write("max_continuous_driving_hours: 8.0\n")
        f.write("mandatory_rest_minutes: 30\n")
        f.write("rest_during_charging: true\n")
        f.write("notes: >\n")
        f.write("  When both rest and charging occur at the same stop,\n")
        f.write("  the stop duration equals the maximum of the total\n")
        f.write("  charging duration (including wait) and the mandatory\n")
        f.write("  rest duration. A rest resets continuous driving hours\n")
        f.write("  to zero.\n")

    # 4. weight_factors.md
    with open(os.path.join(workspace, "weight_factors.md"), "w") as f:
        f.write("# Cargo Weight Efficiency Factors\n\n")
        f.write("Adjust the truck base energy consumption rate (kWh per mile) by the\n")
        f.write("factor from the first bracket where cargo weight is less than or equal\n")
        f.write("to the max weight.\n\n")
        f.write("| Max Weight (lbs) | Factor |\n")
        f.write("|------------------|--------|\n")
        for mw, fac in WEIGHT_BRACKETS:
            f.write(f"| {mw:<16} | {fac:.2f}   |\n")
        f.write("\nIf cargo weight exceeds 80000 lbs, use factor 1.50.\n")

    # ===================== WORKSPACE — SCALABLE DATA FILES =====================

    # Truck telemetry CSVs  (num_active files)
    for i in range(num_active):
        truck = trucks[i]
        soc = active_socs[i]
        cw = active_cargo_weights[i]
        route_idxs = active_route_info[i][0]
        origin_loc = locs[route_idxs[0]]

        records = []
        t = BASE_TIME - timedelta(hours=3)
        cur_soc = min(soc + random.uniform(10, 20), 100.0)
        for j in range(13):
            spd = round(random.uniform(0, 60), 1) if j > 0 else 0.0
            bt = round(random.uniform(22, 35), 1)
            records.append([
                t.strftime("%Y-%m-%dT%H:%M:%S"),
                round(cur_soc, 1),
                round(origin_loc["lat"] + random.uniform(-0.005, 0.005), 4),
                round(origin_loc["lon"] + random.uniform(-0.005, 0.005), 4),
                spd, bt, cw,
            ])
            cur_soc -= random.uniform(0.5, 2.0)
            cur_soc = max(cur_soc, soc)
            t += timedelta(minutes=15)

        records[-1][0] = BASE_TIME.strftime("%Y-%m-%dT%H:%M:%S")
        records[-1][1] = soc
        records[-1][4] = 0.0

        fp = os.path.join(workspace, f"telemetry_{truck['truck_id']}.csv")
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "soc_pct", "latitude", "longitude",
                         "speed_mph", "battery_temp_c", "cargo_weight_lbs"])
            w.writerows(records)

    # Driver HOS log TXTs  (num_active files)
    for i in range(num_active):
        drv = drivers[i]
        daily_h = round(random.uniform(1.0, 5.0), 2)
        cont_h = round(random.uniform(0.5, min(daily_h, 4.0)), 2)
        weekly_h = round(random.uniform(10.0, 40.0), 2)

        fp = os.path.join(workspace, f"hos_log_{drv['driver_id']}.txt")
        with open(fp, "w") as f:
            f.write("=" * 44 + "\n")
            f.write("  DRIVER HOURS-OF-SERVICE LOG\n")
            f.write("=" * 44 + "\n")
            f.write(f"Driver ID       : {drv['driver_id']}\n")
            f.write(f"Driver Name     : {drv['name']}\n")
            f.write(f"Date            : {BASE_TIME.strftime('%Y-%m-%d')}\n")
            f.write(f"Report Time     : {BASE_TIME.strftime('%Y-%m-%dT%H:%M:%S')}\n\n")

            duty_start = BASE_TIME - timedelta(hours=daily_h + 0.25)
            f.write("DUTY ENTRIES:\n")
            f.write(f"  {duty_start.strftime('%H:%M')}  ON_DUTY\n")
            drive_start = duty_start + timedelta(minutes=15)
            f.write(f"  {drive_start.strftime('%H:%M')}  DRIVING\n")
            if daily_h > cont_h + 0.5:
                gap = daily_h - cont_h
                rest_at = drive_start + timedelta(hours=gap)
                f.write(f"  {rest_at.strftime('%H:%M')}  OFF_DUTY_REST\n")
                resume = rest_at + timedelta(minutes=30)
                f.write(f"  {resume.strftime('%H:%M')}  DRIVING\n")
            f.write(f"  {BASE_TIME.strftime('%H:%M')}  ON_DUTY (current)\n\n")

            f.write("CURRENT STATUS:\n")
            f.write(f"  driving_hours_today: {daily_h}\n")
            f.write(f"  continuous_driving_hours: {cont_h}\n")
            f.write(f"  on_duty_hours_today: {round(daily_h + 0.25, 2)}\n")
            f.write(f"  driving_hours_this_week: {weekly_h}\n")

    conn.commit()
    conn.close()
    print(f"Database written to {db_path}")
    print(f"Workspace populated at {workspace} with {NW} scalable + 4 config files")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db_path", required=True)
    p.add_argument("--workspace", required=True)
    args = p.parse_args()
    main(args.db_path, args.workspace)
