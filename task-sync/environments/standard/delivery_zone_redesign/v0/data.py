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
import yaml

SCALE = {
    "rows_per_table": 100,
    "num_workspace_files": 10,
}

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ---------- City & Zone layout ----------
NUM_ZONES = 10
CITY_CENTER_LAT = 40.7128
CITY_CENTER_LNG = -74.0060

# Each zone has characteristics that determine generated data distributions.
# Some zones are intentionally configured to be inefficient.
ZONE_DEFS = [
    # (name, lat_offset, lng_offset, radius_km, current_quota,
    #  transit_mean, transit_std, prep_mean, prep_std, order_weight)
    ("Downtown Core",    0.000,  0.000, 2.0, 15, 12, 3, 10, 2, 1.5),
    ("Midtown East",     0.015,  0.020, 2.5, 12, 14, 4, 11, 3, 1.2),
    ("Midtown West",    -0.015,  0.020, 2.3, 10, 25, 5, 18, 4, 0.7),   # high transit+prep
    ("Upper East",       0.025,  0.040, 2.8,  8, 13, 3, 11, 2, 1.0),
    ("Upper West",      -0.025,  0.040, 2.7, 14, 11, 2,  9, 2, 0.6),   # too many riders
    ("Riverside",        0.035,  0.000, 3.0,  6, 28, 6, 16, 5, 1.4),   # very high transit
    ("Harbor District", -0.035,  0.000, 2.2, 11, 13, 3, 12, 3, 1.1),
    ("Tech Quarter",     0.010, -0.025, 1.8, 13, 10, 2,  8, 2, 1.3),
    ("University Area", -0.010, -0.025, 2.0,  9, 14, 3, 11, 3, 1.0),
    ("Suburban Ring",    0.000,  0.055, 3.5,  7, 30, 7, 20, 5, 0.5),   # high transit+prep, low orders
]


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def jitter(center, spread):
    return center + np.random.uniform(-spread, spread)


def build_zones():
    zones = []
    for i, (name, lat_off, lng_off, radius, quota, *_rest) in enumerate(ZONE_DEFS, 1):
        zones.append({
            "zone_id": i,
            "zone_name": name,
            "center_lat": round(CITY_CENTER_LAT + lat_off, 6),
            "center_lng": round(CITY_CENTER_LNG + lng_off, 6),
            "radius_km": radius,
            "current_rider_quota": quota,
        })
    return zones


def main(db_path: str, workspace: str):
    os.makedirs(workspace, exist_ok=True)
    rows = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    zones = build_zones()

    # ------ Database ------
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Table 1: zones
    cur.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            zone_id INTEGER PRIMARY KEY,
            zone_name TEXT,
            center_lat REAL,
            center_lng REAL,
            radius_km REAL,
            current_rider_quota INTEGER
        )
    """)
    for z in zones:
        cur.execute("INSERT INTO zones VALUES (?,?,?,?,?,?)",
                     (z["zone_id"], z["zone_name"], z["center_lat"],
                      z["center_lng"], z["radius_km"], z["current_rider_quota"]))

    # Table 2: riders  (>= rows)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS riders (
            rider_id INTEGER PRIMARY KEY,
            zone_id INTEGER,
            rider_name TEXT,
            avg_speed_kmh REAL,
            total_deliveries INTEGER,
            is_active INTEGER,
            rider_tier TEXT,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    rider_tiers = ["standard", "express", "part_time"]
    tier_weights = [0.5, 0.3, 0.2]
    riders = []
    for rid in range(1, rows + 1):
        zid = ((rid - 1) % NUM_ZONES) + 1
        tier = np.random.choice(rider_tiers, p=tier_weights)
        riders.append((
            rid, zid, fake.name(),
            round(np.random.uniform(15, 35), 1),
            int(np.random.randint(20, 500)),
            1 if np.random.random() < 0.85 else 0,
            tier,
        ))
    cur.executemany("INSERT INTO riders VALUES (?,?,?,?,?,?,?)", riders)

    # Table 3: restaurants  (>= rows)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS restaurants (
            restaurant_id INTEGER PRIMARY KEY,
            zone_id INTEGER,
            restaurant_name TEXT,
            lat REAL,
            lng REAL,
            cuisine_type TEXT,
            avg_rating REAL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    cuisines = ["Italian", "Chinese", "Mexican", "Indian", "Japanese",
                "Thai", "American", "Mediterranean", "Korean", "Vietnamese"]
    restaurants = []
    for rid in range(1, rows + 1):
        zid = ((rid - 1) % NUM_ZONES) + 1
        z = zones[zid - 1]
        restaurants.append((
            rid, zid, fake.company() + " Kitchen",
            round(jitter(z["center_lat"], 0.01), 6),
            round(jitter(z["center_lng"], 0.01), 6),
            random.choice(cuisines),
            round(np.random.uniform(3.0, 5.0), 1),
        ))
    cur.executemany("INSERT INTO restaurants VALUES (?,?,?,?,?,?,?)", restaurants)

    # Table 4: orders  (>= rows)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY,
            zone_id INTEGER,
            restaurant_id INTEGER,
            rider_id INTEGER,
            customer_lat REAL,
            customer_lng REAL,
            order_timestamp TEXT,
            delivery_time_min REAL,
            order_value REAL,
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id),
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(restaurant_id),
            FOREIGN KEY (rider_id) REFERENCES riders(rider_id)
        )
    """)
    # Distribute orders across zones with weights
    total_weight = sum(d[9] for d in ZONE_DEFS)
    zone_order_counts = []
    remaining = rows
    for i, d in enumerate(ZONE_DEFS):
        if i == NUM_ZONES - 1:
            cnt = remaining
        else:
            cnt = max(1, int(rows * d[9] / total_weight))
            remaining -= cnt
        zone_order_counts.append(cnt)

    orders = []
    oid = 1
    for zid_idx, cnt in enumerate(zone_order_counts):
        zid = zid_idx + 1
        z = zones[zid_idx]
        zone_rids = [r[0] for r in riders if r[1] == zid]
        zone_rest_ids = [r[0] for r in restaurants if r[1] == zid]
        for _ in range(cnt):
            orders.append((
                oid, zid,
                random.choice(zone_rest_ids) if zone_rest_ids else 1,
                random.choice(zone_rids) if zone_rids else 1,
                round(jitter(z["center_lat"], 0.015), 6),
                round(jitter(z["center_lng"], 0.015), 6),
                fake.date_time_between(start_date="-30d", end_date="now").isoformat(),
                round(np.random.uniform(15, 60), 1),
                round(np.random.uniform(8, 45), 2),
            ))
            oid += 1
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", orders)

    # Table 5: transit_logs  (>= rows)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transit_logs (
            log_id INTEGER PRIMARY KEY,
            rider_id INTEGER,
            zone_id INTEGER,
            from_restaurant_id INTEGER,
            to_restaurant_id INTEGER,
            transit_time_min REAL,
            distance_km REAL,
            log_date TEXT,
            FOREIGN KEY (rider_id) REFERENCES riders(rider_id),
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    transit_rows = []
    for lid in range(1, rows + 1):
        zid = ((lid - 1) % NUM_ZONES) + 1
        zone_def = ZONE_DEFS[zid - 1]
        t_mean, t_std = zone_def[5], zone_def[6]
        zone_rids = [r[0] for r in riders if r[1] == zid]
        zone_rest_ids = [r[0] for r in restaurants if r[1] == zid]
        transit_rows.append((
            lid,
            random.choice(zone_rids) if zone_rids else 1,
            zid,
            random.choice(zone_rest_ids) if zone_rest_ids else 1,
            random.choice(zone_rest_ids) if zone_rest_ids else 1,
            round(max(2, np.random.normal(t_mean, t_std)), 1),
            round(max(0.2, np.random.normal(t_mean / 5, t_std / 5)), 2),
            fake.date_between(start_date="-30d", end_date="today").isoformat(),
        ))
    cur.executemany("INSERT INTO transit_logs VALUES (?,?,?,?,?,?,?,?)", transit_rows)

    # Table 6: prep_logs  (>= rows)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prep_logs (
            log_id INTEGER PRIMARY KEY,
            restaurant_id INTEGER,
            zone_id INTEGER,
            order_id INTEGER,
            prep_duration_min REAL,
            log_timestamp TEXT,
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(restaurant_id),
            FOREIGN KEY (zone_id) REFERENCES zones(zone_id)
        )
    """)
    prep_rows = []
    for lid in range(1, rows + 1):
        zid = ((lid - 1) % NUM_ZONES) + 1
        zone_def = ZONE_DEFS[zid - 1]
        p_mean, p_std = zone_def[7], zone_def[8]
        zone_rest_ids = [r[0] for r in restaurants if r[1] == zid]
        prep_rows.append((
            lid,
            random.choice(zone_rest_ids) if zone_rest_ids else 1,
            zid,
            random.choice([o[0] for o in orders if o[1] == zid]) if any(o[1] == zid for o in orders) else 1,
            round(max(3, np.random.normal(p_mean, p_std)), 1),
            fake.date_time_between(start_date="-30d", end_date="now").isoformat(),
        ))
    cur.executemany("INSERT INTO prep_logs VALUES (?,?,?,?,?,?)", prep_rows)

    conn.commit()

    # ------ Fixed Workspace Files ------

    # 1. Zone boundaries (fixed)
    zone_boundaries = {}
    for z in zones:
        zone_boundaries[str(z["zone_id"])] = {
            "zone_name": z["zone_name"],
            "center_lat": z["center_lat"],
            "center_lng": z["center_lng"],
            "radius_km": z["radius_km"],
            "current_rider_quota": z["current_rider_quota"],
        }
    with open(os.path.join(workspace, "zone_boundaries.json"), "w") as f:
        json.dump(zone_boundaries, f, indent=2)

    # 2. Rezoning policy (fixed)
    policy = {
        "efficiency_weights": {
            "transit_time": 0.35,
            "prep_time": 0.25,
            "order_rider_ratio": 0.25,
            "density_utilization": 0.15,
        },
        "scoring_rules": {
            "transit_baseline_min": 15,
            "prep_baseline_min": 12,
            "target_orders_per_rider": 10,
            "transit_penalty_per_min": 5,
            "prep_penalty_per_min": 5,
            "ratio_penalty_per_unit": 8,
        },
        "efficiency_cutoff": 60.0,
        "adjustment_rules": {
            "radius_shrink_factor": 0.85,
            "min_radius_km": 1.0,
            "max_radius_km": 5.0,
        },
        "quota_formula_note": "new_quota = ceil(zone_order_count * density_factor / target_orders_per_rider)",
    }
    with open(os.path.join(workspace, "rezoning_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 3. Rider tier standards (fixed)
    tier_standards = {
        "standard": {"max_concurrent_orders": 3, "shift_hours": 8, "capacity_weight": 1.0},
        "express": {"max_concurrent_orders": 5, "shift_hours": 6, "capacity_weight": 1.5},
        "part_time": {"max_concurrent_orders": 2, "shift_hours": 4, "capacity_weight": 0.6},
    }
    with open(os.path.join(workspace, "rider_tier_standards.json"), "w") as f:
        json.dump(tier_standards, f, indent=2)

    # 4. Operational notes (fixed, .txt for format diversity)
    notes_lines = [
        "DELIVERY OPERATIONS - ZONE ANALYSIS NOTES",
        "==========================================",
        "",
        "Haversine Formula Reference",
        "--------------------------",
        "All geographic distance calculations use the haversine formula with",
        "Earth radius R = 6371.0 km. A sub-sector overlaps a zone when the",
        "distance from the sub-sector's geographic center (midpoint of its",
        "lat/lng bounds) to the zone center is less than or equal to the",
        "zone's radius.",
        "",
        "Density Factor Computation",
        "--------------------------",
        "Zone density: weighted average of density_per_sq_km for overlapping",
        "sub-sectors, weighted by total addresses (residential + commercial).",
        "City average density: arithmetic mean of all zone densities.",
        "Density factor for a zone = zone_density / city_average_density.",
        "",
        "Active Riders",
        "--------------",
        "Only riders with is_active = 1 are counted when computing the",
        "orders-per-rider ratio for efficiency scoring.",
        "",
    ]
    with open(os.path.join(workspace, "operations_notes.txt"), "w") as f:
        f.write("\n".join(notes_lines))

    # ------ Scalable Workspace Files: Sector Density CSVs ------
    # Generate a grid of sectors covering the city, split into `num_files` files.
    # Each file covers a geographic strip (longitude band).

    all_zone_lats = [z["center_lat"] for z in zones]
    all_zone_lngs = [z["center_lng"] for z in zones]
    lat_min_city = min(all_zone_lats) - 0.05
    lat_max_city = max(all_zone_lats) + 0.05
    lng_min_city = min(all_zone_lngs) - 0.05
    lng_max_city = max(all_zone_lngs) + 0.05

    # Create grid: num_files columns (lng strips) x rows_grid rows (lat strips)
    rows_grid = max(5, num_files // 2)
    lat_step = (lat_max_city - lat_min_city) / rows_grid
    lng_step = (lng_max_city - lng_min_city) / num_files

    sector_id_counter = 1
    for file_idx in range(num_files):
        lng_lo = lng_min_city + file_idx * lng_step
        lng_hi = lng_lo + lng_step
        file_rows = []
        for row_idx in range(rows_grid):
            lat_lo = lat_min_city + row_idx * lat_step
            lat_hi = lat_lo + lat_step
            # Density varies: higher near city center
            center_lat_s = (lat_lo + lat_hi) / 2
            center_lng_s = (lng_lo + lng_hi) / 2
            dist_from_center = haversine_km(center_lat_s, center_lng_s,
                                            CITY_CENTER_LAT, CITY_CENTER_LNG)
            base_density = max(50, int(800 * math.exp(-dist_from_center / 4)))
            residential = int(base_density * np.random.uniform(0.7, 1.3))
            commercial = int(base_density * np.random.uniform(0.1, 0.5))
            area = round(haversine_km(lat_lo, lng_lo, lat_hi, lng_lo) *
                         haversine_km(lat_lo, lng_lo, lat_lo, lng_hi), 3)
            if area < 0.001:
                area = 0.01
            file_rows.append({
                "sub_sector_id": f"SEC-{sector_id_counter:04d}",
                "lat_min": round(lat_lo, 6),
                "lat_max": round(lat_hi, 6),
                "lng_min": round(lng_lo, 6),
                "lng_max": round(lng_hi, 6),
                "residential_addresses": residential,
                "commercial_addresses": commercial,
                "area_sq_km": area,
                "density_per_sq_km": round((residential + commercial) / area, 1),
            })
            sector_id_counter += 1

        fname = f"sector_density_{file_idx + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(file_rows[0].keys()))
            writer.writeheader()
            writer.writerows(file_rows)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
