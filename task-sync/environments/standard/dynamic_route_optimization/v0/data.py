import argparse
import os
import sqlite3
import json
import csv
import math
import random
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 25,
    "num_workspace_files": 10,
}

DISTRICTS = ["North", "South", "East", "West", "Central"]
DISTRICT_COORDS = {
    "North":   {"lat": (5, 15),   "lon": (-5, 5)},
    "South":   {"lat": (-15, -5), "lon": (-5, 5)},
    "East":    {"lat": (-5, 5),   "lon": (5, 15)},
    "West":    {"lat": (-5, 5),   "lon": (-15, -5)},
    "Central": {"lat": (-3, 3),   "lon": (-3, 3)},
}
DISTRICT_SCHEDULE = {
    "North":   {"primary_day": 1, "secondary_day": 4},
    "South":   {"primary_day": 2, "secondary_day": 5},
    "East":    {"primary_day": 3, "secondary_day": 1},
    "West":    {"primary_day": 4, "secondary_day": 2},
    "Central": {"primary_day": 5, "secondary_day": 3},
}
BIN_TYPES = ["general", "recycling", "organic"]
BIN_CAPACITIES = [120, 240, 360]
TIER_LIST = ["basic", "standard", "premium"]
TIER_WEIGHTS = [0.55, 0.30, 0.15]
FUEL_TYPES = ["diesel", "gasoline"]
TRUCK_MODELS = ["CompactCollector", "MidRangeHauler", "HeavyDutyLifter",
                "EcoCompactor", "UrbanSwift"]
HIGH_DEMAND_THRESHOLD = 120.0
FUEL_PRICES = {"diesel": 1.45, "gasoline": 1.32}
DENSITY_FACTOR = 0.25  # kg per litre of bin capacity


def euclidean(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    Faker.seed(42)

    n = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    # ------------------------------------------------------------------ #
    # CREATE TABLES                                                       #
    # ------------------------------------------------------------------ #
    cur.executescript("""
        DROP TABLE IF EXISTS fuel_logs;
        DROP TABLE IF EXISTS weight_readings;
        DROP TABLE IF EXISTS residents;
        DROP TABLE IF EXISTS bins;
        DROP TABLE IF EXISTS trucks;
        DROP TABLE IF EXISTS service_areas;

        CREATE TABLE service_areas (
            area_id      TEXT PRIMARY KEY,
            area_name    TEXT NOT NULL,
            district     TEXT NOT NULL,
            latitude     REAL NOT NULL,
            longitude    REAL NOT NULL
        );
        CREATE TABLE bins (
            bin_id          TEXT PRIMARY KEY,
            area_id         TEXT NOT NULL,
            bin_type        TEXT NOT NULL,
            capacity_liters INTEGER NOT NULL,
            FOREIGN KEY (area_id) REFERENCES service_areas(area_id)
        );
        CREATE TABLE residents (
            resident_id       TEXT PRIMARY KEY,
            area_id           TEXT NOT NULL,
            name              TEXT NOT NULL,
            subscription_tier TEXT NOT NULL,
            FOREIGN KEY (area_id) REFERENCES service_areas(area_id)
        );
        CREATE TABLE trucks (
            truck_id             TEXT PRIMARY KEY,
            plate_number         TEXT NOT NULL,
            model                TEXT NOT NULL,
            capacity_kg          REAL NOT NULL,
            fuel_type            TEXT NOT NULL,
            fuel_efficiency_spec REAL NOT NULL
        );
        CREATE TABLE weight_readings (
            reading_id  TEXT PRIMARY KEY,
            bin_id      TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            weight_kg   REAL NOT NULL,
            FOREIGN KEY (bin_id) REFERENCES bins(bin_id)
        );
        CREATE TABLE fuel_logs (
            log_id               TEXT PRIMARY KEY,
            truck_id             TEXT NOT NULL,
            date                 TEXT NOT NULL,
            distance_km          REAL NOT NULL,
            fuel_consumed_liters REAL NOT NULL,
            FOREIGN KEY (truck_id) REFERENCES trucks(truck_id)
        );
    """)

    # ------------------------------------------------------------------ #
    # SERVICE AREAS                                                       #
    # ------------------------------------------------------------------ #
    areas = []
    for i in range(n):
        d = DISTRICTS[i % len(DISTRICTS)]
        lat_range = DISTRICT_COORDS[d]["lat"]
        lon_range = DISTRICT_COORDS[d]["lon"]
        lat = round(float(np.random.uniform(*lat_range)), 4)
        lon = round(float(np.random.uniform(*lon_range)), 4)
        area_id = f"SA{i+1:03d}"
        area_name = fake.street_name()
        areas.append((area_id, area_name, d, lat, lon))
    cur.executemany("INSERT INTO service_areas VALUES (?,?,?,?,?)", areas)

    # ------------------------------------------------------------------ #
    # BINS  (2-4 per area, total >= n)                                    #
    # ------------------------------------------------------------------ #
    bins_data = []
    bin_idx = 0
    for area_id, *_ in areas:
        num_bins = int(np.random.randint(2, 5))
        for _ in range(num_bins):
            bin_idx += 1
            bid = f"B{bin_idx:04d}"
            btype = str(np.random.choice(BIN_TYPES))
            cap = int(np.random.choice(BIN_CAPACITIES))
            bins_data.append((bid, area_id, btype, cap))
    cur.executemany("INSERT INTO bins VALUES (?,?,?,?)", bins_data)
    assert len(bins_data) >= n, f"bins {len(bins_data)} < {n}"

    # ------------------------------------------------------------------ #
    # RESIDENTS  (1-3 per area, total >= n)                               #
    # ------------------------------------------------------------------ #
    residents_data = []
    res_idx = 0
    for area_id, *_ in areas:
        num_res = int(np.random.randint(1, 4))
        for _ in range(num_res):
            res_idx += 1
            rid = f"R{res_idx:04d}"
            rname = fake.name()
            tier = str(np.random.choice(TIER_LIST, p=TIER_WEIGHTS))
            residents_data.append((rid, area_id, rname, tier))
    while len(residents_data) < n:
        res_idx += 1
        rid = f"R{res_idx:04d}"
        aid = areas[int(np.random.randint(len(areas)))][0]
        residents_data.append((rid, aid, fake.name(),
                               str(np.random.choice(TIER_LIST, p=TIER_WEIGHTS))))
    cur.executemany("INSERT INTO residents VALUES (?,?,?,?)", residents_data)

    # ------------------------------------------------------------------ #
    # TRUCKS  (exactly n)                                                 #
    # ------------------------------------------------------------------ #
    trucks_data = []
    for i in range(n):
        tid = f"T{i+1:03d}"
        plate = fake.license_plate()
        model = str(np.random.choice(TRUCK_MODELS))
        capacity_kg = int(np.random.uniform(400, 1200))
        ft = str(np.random.choice(FUEL_TYPES))
        eff_spec = round(float(np.random.uniform(3.0, 7.0)), 2)
        trucks_data.append((tid, plate, model, capacity_kg, ft, eff_spec))
    cur.executemany("INSERT INTO trucks VALUES (?,?,?,?,?,?)", trucks_data)

    # ------------------------------------------------------------------ #
    # WEIGHT READINGS  (one per bin per weekday)                          #
    # ------------------------------------------------------------------ #
    wr_data = []
    wr_idx = 0
    for bid, _area, _bt, cap in bins_data:
        for dow in range(1, 6):
            wr_idx += 1
            fill = float(np.random.uniform(0.20, 0.85))
            weight = round(fill * cap * DENSITY_FACTOR, 1)
            wr_data.append((f"WR{wr_idx:06d}", bid, dow, weight))
    cur.executemany("INSERT INTO weight_readings VALUES (?,?,?,?)", wr_data)
    assert len(wr_data) >= n, f"weight_readings {len(wr_data)} < {n}"

    # ------------------------------------------------------------------ #
    # FUEL LOGS  (3-5 per truck, total >= n)                              #
    # ------------------------------------------------------------------ #
    fl_data = []
    fl_idx = 0
    for tid, _, _, _, ft, eff_spec in trucks_data:
        num_logs = int(np.random.randint(3, 6))
        for _ in range(num_logs):
            fl_idx += 1
            date_val = fake.date_between(start_date="-30d", end_date="today")
            dist = round(float(np.random.uniform(30, 120)), 1)
            actual_eff = eff_spec * float(np.random.uniform(0.8, 1.2))
            fuel = round(dist / actual_eff, 2)
            fl_data.append((f"FL{fl_idx:05d}", tid, date_val.isoformat(),
                            dist, fuel))
    cur.executemany("INSERT INTO fuel_logs VALUES (?,?,?,?,?)", fl_data)
    assert len(fl_data) >= n, f"fuel_logs {len(fl_data)} < {n}"

    conn.commit()

    # ================================================================== #
    # WORKSPACE FILES                                                     #
    # ================================================================== #
    ws = args.workspace

    # ---------- Fixed config files ------------------------------------ #

    # 1. collection_policy.md
    policy_text = f"""# Collection Policy Configuration

## Demand Classification

An area is classified as high-demand when its average daily total expected bin
weight (averaged across all five weekdays) equals or exceeds {HIGH_DEMAND_THRESHOLD}
kilograms.  Additionally, any area containing at least one resident with a
premium subscription tier is automatically classified as high-demand, regardless
of weight.

## Collection Frequency

High-demand areas receive collections twice per week: once on their district's
designated primary day and once on the designated secondary day.  Standard-demand
areas receive a single collection on their district's primary day only.

The district-to-day mapping is specified in the district schedule configuration
file (district_schedule.json).

## Truck Assignment

For each collection day the following procedure is applied:

1. Compute each scheduled area's expected weight as the sum of all bin weight
   readings for that specific day of the week.
2. Identify available trucks by excluding any truck listed for maintenance on
   that day of the week AND excluding any truck that has no fuel-log history.
3. Rank the available trucks by their actual fuel efficiency in descending
   order.  Actual fuel efficiency for a truck equals the sum of all distance_km
   values divided by the sum of all fuel_consumed_liters values from the
   truck's fuel logs.  Ties in efficiency are broken by truck identifier in
   ascending lexicographic order.
4. Rank the day's areas by expected collection weight in descending order.
   Ties in weight are broken by area identifier in ascending lexicographic
   order.
5. Assign areas to trucks using a greedy approach: iterate through the sorted
   area list and assign each area to the highest-ranked available truck (by
   efficiency rank) whose remaining capacity can still accommodate the area's
   weight.  If no truck has sufficient remaining capacity, assign the area to
   the truck with the greatest remaining capacity; ties in remaining capacity
   are broken by efficiency rank (higher-ranked truck wins).

## Route Ordering

Within each truck's daily assignment, order the stops using the
nearest-neighbour heuristic starting from the depot located at coordinates
latitude 0.0, longitude 0.0.  At each step, select the unvisited area closest
to the current position by Euclidean distance (sqrt of the sum of squared
coordinate differences).  Ties are broken by area identifier in ascending
lexicographic order.  The route concludes with a return segment to the depot.

## Cost Calculations

Fuel cost for each route segment is computed as:

    segment_distance_km / truck_actual_fuel_efficiency * fuel_price_per_litre

where the fuel price corresponds to the truck's fuel type as listed in
fuel_prices.json.

Drive time for each segment is obtained from the traffic data files for the
corresponding day of the week.  Look up the ordered pair (from_id, to_id)
where identifiers are the area IDs of the two endpoints; use "DEPOT" as the
identifier for the depot.  Both directions are listed in the traffic files.
If a specific pair is not found in any traffic file for that day, estimate
drive time as (Euclidean distance in km) / 30.0 * 60.0 minutes.

Total daily drive time and fuel cost sum all segments in all routes for that
day, including the final return-to-depot segment for each truck.
"""
    with open(os.path.join(ws, "collection_policy.md"), "w") as f:
        f.write(policy_text)

    # 2. subscription_tiers.yaml
    yaml_text = """premium:
  priority: 1
  force_high_demand: true
  description: "Premium service - guarantees high-demand classification"
standard:
  priority: 2
  force_high_demand: false
  description: "Standard service tier"
basic:
  priority: 3
  force_high_demand: false
  description: "Basic service tier"
"""
    with open(os.path.join(ws, "subscription_tiers.yaml"), "w") as f:
        f.write(yaml_text)

    # 3. fuel_prices.json
    with open(os.path.join(ws, "fuel_prices.json"), "w") as f:
        json.dump(FUEL_PRICES, f, indent=2)

    # 4. district_schedule.json
    with open(os.path.join(ws, "district_schedule.json"), "w") as f:
        json.dump(DISTRICT_SCHEDULE, f, indent=2)

    # 5. truck_maintenance.txt
    maintenance_entries = []
    for tid, *_ in trucks_data:
        if float(np.random.random()) < 0.30:
            dow = int(np.random.randint(1, 6))
            maintenance_entries.append((tid, dow))
    with open(os.path.join(ws, "truck_maintenance.txt"), "w") as f:
        f.write("# Truck Maintenance Schedule\n")
        f.write("# Format: truck_id | day_of_week  (1=Monday ... 5=Friday)\n")
        for tid, dow in maintenance_entries:
            f.write(f"{tid} | {dow}\n")

    # ---------- Scalable traffic files -------------------------------- #
    parts_per_day = n_files // 5
    assert parts_per_day >= 1, "Need at least 1 traffic part per day"

    area_coords = {a[0]: (a[3], a[4]) for a in areas}
    area_coords["DEPOT"] = (0.0, 0.0)

    all_ids = ["DEPOT"] + [a[0] for a in areas]

    # Build all directed pairs
    directed_pairs = []
    for fid in all_ids:
        for tid_to in all_ids:
            if fid != tid_to:
                directed_pairs.append((fid, tid_to))

    traffic_dir = os.path.join(ws, "traffic")
    os.makedirs(traffic_dir, exist_ok=True)

    for day in range(1, 6):
        day_rng = np.random.RandomState(42 + day * 1000)
        pair_data = []
        for fid, tid_to in directed_pairs:
            fc = area_coords[fid]
            tc = area_coords[tid_to]
            eucl = euclidean(fc[0], fc[1], tc[0], tc[1])
            road_factor = 1.2 + float(day_rng.random()) * 0.3
            dist = round(eucl * road_factor, 2)
            speed = 25.0 + float(day_rng.random()) * 15.0
            travel_time = round(dist / speed * 60.0, 2)
            pair_data.append((fid, tid_to, dist, travel_time))

        chunk_size = len(pair_data) // parts_per_day
        for p in range(parts_per_day):
            start = p * chunk_size
            end = (start + chunk_size) if p < parts_per_day - 1 else len(pair_data)
            chunk = pair_data[start:end]
            fname = f"day_{day}_part_{p+1}.csv"
            with open(os.path.join(traffic_dir, fname), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["from_id", "to_id", "distance_km",
                            "travel_time_minutes"])
                w.writerows(chunk)

    conn.close()
    print(f"Database written to {args.db_path}")
    print(f"Workspace created at {ws}")
    print(f"  Areas: {len(areas)}, Bins: {len(bins_data)}, "
          f"Residents: {len(residents_data)}, Trucks: {len(trucks_data)}")
    print(f"  Weight readings: {len(wr_data)}, Fuel logs: {len(fl_data)}")
    print(f"  Traffic files: {5 * parts_per_day}")


if __name__ == "__main__":
    main()
