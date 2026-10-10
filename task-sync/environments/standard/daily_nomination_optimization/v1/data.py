import argparse
import sqlite3
import os
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker

try:
    import yaml
except ImportError:
    yaml = None

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 20,
}

random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)


def _normalize(vals):
    """Normalize a list so it sums to 1.0."""
    s = sum(vals)
    return [v / s for v in vals]


def generate_hourly_profile(profile_type):
    """Generate a 24-element list of floats summing to 1.0."""
    base = [1.0] * 24
    if profile_type == "flat":
        noise = np.random.uniform(0.9, 1.1, 24)
        base = list(noise)
    elif profile_type == "morning_peak":
        for h in range(24):
            if 6 <= h <= 10:
                base[h] = 3.0 + random.uniform(-0.3, 0.3)
            elif 5 <= h <= 11:
                base[h] = 1.8 + random.uniform(-0.2, 0.2)
            else:
                base[h] = 0.6 + random.uniform(-0.1, 0.1)
    elif profile_type == "evening_peak":
        for h in range(24):
            if 17 <= h <= 21:
                base[h] = 3.0 + random.uniform(-0.3, 0.3)
            elif 16 <= h <= 22:
                base[h] = 1.8 + random.uniform(-0.2, 0.2)
            else:
                base[h] = 0.6 + random.uniform(-0.1, 0.1)
    elif profile_type == "business_hours":
        for h in range(24):
            if 8 <= h <= 17:
                base[h] = 2.5 + random.uniform(-0.3, 0.3)
            elif 7 <= h <= 18:
                base[h] = 1.5 + random.uniform(-0.2, 0.2)
            else:
                base[h] = 0.5 + random.uniform(-0.1, 0.1)
    return _normalize(base)


PROFILE_TYPES = ["flat", "morning_peak", "evening_peak", "business_hours"]


def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    n_seg = SCALE["rows_per_table"]
    n_ship = SCALE["rows_per_table"]
    n_cust = SCALE["rows_per_table"]
    n_comp = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # ── Derived counts ──
    n_shipper_files = max(1, round(n_files * 0.3))   # 3
    n_customer_files = max(1, round(n_files * 0.3))   # 3
    n_segment_files = n_files - n_shipper_files - n_customer_files  # 4

    # ========================================================================
    # 1. Pipeline Segments
    # ========================================================================
    n_nodes = int(n_seg * 1.2)
    node_ids = [f"NODE-{i+1:03d}" for i in range(n_nodes)]

    segments = []
    prefixes = ["Mainline-Alpha", "Mainline-Beta", "Lateral-Gamma",
                 "Trunk-Delta", "Spur-Epsilon", "Header-Zeta"]
    used_pairs = set()
    for i in range(n_seg):
        seg_id = f"SEG-{i+1:04d}"
        seg_name = f"{prefixes[i % len(prefixes)]}-{i+1:03d}"
        while True:
            fn = random.choice(node_ids)
            tn = random.choice(node_ids)
            if fn != tn and (fn, tn) not in used_pairs:
                used_pairs.add((fn, tn))
                break
        segments.append((seg_id, seg_name, fn, tn))

    cursor.execute("""
        CREATE TABLE pipeline_segments (
            segment_id TEXT PRIMARY KEY,
            segment_name TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL
        )
    """)
    cursor.executemany(
        "INSERT INTO pipeline_segments VALUES (?,?,?,?)", segments
    )

    seg_ids = [s[0] for s in segments]

    # ========================================================================
    # 2. Shippers
    # ========================================================================
    shippers = []
    for i in range(n_ship):
        sid = f"SHIP-{i+1:04d}"
        sname = fake.company()
        shippers.append((sid, sname))

    cursor.execute("""
        CREATE TABLE shippers (
            shipper_id TEXT PRIMARY KEY,
            shipper_name TEXT NOT NULL
        )
    """)
    cursor.executemany("INSERT INTO shippers VALUES (?,?)", shippers)

    ship_ids = [s[0] for s in shippers]

    # ========================================================================
    # 3. Customers
    # ========================================================================
    customers = []
    for i in range(n_cust):
        cid = f"CUST-{i+1:04d}"
        cname = fake.name()
        connected_seg = seg_ids[i % n_seg]
        customers.append((cid, cname, connected_seg))

    cursor.execute("""
        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            connected_segment_id TEXT NOT NULL,
            FOREIGN KEY (connected_segment_id) REFERENCES pipeline_segments(segment_id)
        )
    """)
    cursor.executemany("INSERT INTO customers VALUES (?,?,?)", customers)

    cust_ids = [c[0] for c in customers]

    # ========================================================================
    # 4. Compressor Stations
    # ========================================================================
    stations = []
    for i in range(n_comp):
        station_id = f"COMP-{i+1:04d}"
        station_name = f"Station-{fake.city()}-{i+1:02d}"
        seg = seg_ids[i % n_seg]
        stations.append((station_id, station_name, seg))

    cursor.execute("""
        CREATE TABLE compressor_stations (
            station_id TEXT PRIMARY KEY,
            station_name TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            FOREIGN KEY (segment_id) REFERENCES pipeline_segments(segment_id)
        )
    """)
    cursor.executemany(
        "INSERT INTO compressor_stations VALUES (?,?,?)", stations
    )

    station_ids = [s[0] for s in stations]

    # ========================================================================
    # Generate segment specs (needed before nominations for calibration)
    # ========================================================================
    seg_specs = {}
    for seg_id in seg_ids:
        seg_specs[seg_id] = {
            "segment_id": seg_id,
            "max_capacity_mmbtu_hr": round(random.uniform(100, 600), 1),
            "min_pressure_psi": round(random.uniform(400, 600), 1),
            "max_pressure_psi": round(random.uniform(900, 1200), 1),
            "diameter_inches": round(random.uniform(12, 48), 1),
            "length_miles": round(random.uniform(5, 50), 1),
        }

    # ========================================================================
    # Assign shipper profiles
    # ========================================================================
    shipper_profiles = {}
    for sid in ship_ids:
        ptype = random.choice(PROFILE_TYPES)
        profile = generate_hourly_profile(ptype)
        shipper_profiles[sid] = {
            "profile_type": ptype,
            "hourly_profile": profile,
            "priority_tier": random.randint(1, 5),
            "penalty_rate_usd_per_mmbtu": round(random.uniform(0.5, 5.0), 2),
        }

    # ========================================================================
    # 5. Nominations (calibrated)
    # ========================================================================
    # Assign each shipper to 2-4 segments
    shipper_seg_map = {}
    for sid in ship_ids:
        k = random.randint(2, 4)
        assigned = random.sample(seg_ids, min(k, n_seg))
        shipper_seg_map[sid] = assigned

    # Figure out which segments will be constrained (~30%)
    n_constrained = max(1, round(n_seg * 0.33))
    constrained_segs = set(random.sample(seg_ids, n_constrained))

    # For each segment, gather which shippers nominate on it
    seg_shipper_map = {sid: [] for sid in seg_ids}
    for sid, segs in shipper_seg_map.items():
        for seg in segs:
            seg_shipper_map[seg].append(sid)

    # Generate nomination volumes with calibration
    nominations = []
    nom_id = 1
    shipper_seg_daily = {}  # (shipper_id, seg_id) -> daily_volume

    for seg_id in seg_ids:
        cap = seg_specs[seg_id]["max_capacity_mmbtu_hr"]
        shippers_on_seg = seg_shipper_map[seg_id]
        if not shippers_on_seg:
            continue

        is_constrained = seg_id in constrained_segs

        # Determine target utilization at peak hour
        if is_constrained:
            target_peak_util = random.uniform(1.30, 1.60)
        else:
            target_peak_util = random.uniform(0.55, 0.80)

        target_peak_flow = cap * target_peak_util

        # For each shipper on this segment, find their peak profile fraction
        peak_fracs = []
        for sid in shippers_on_seg:
            pf = max(shipper_profiles[sid]["hourly_profile"])
            peak_fracs.append(pf)
        avg_peak_frac = sum(peak_fracs) / len(peak_fracs)

        # daily_vol * avg_peak_frac * n_shippers ~ target_peak_flow
        n_shippers_here = len(shippers_on_seg)
        base_daily = target_peak_flow / (avg_peak_frac * n_shippers_here)

        for idx, sid in enumerate(shippers_on_seg):
            daily_vol = base_daily * random.uniform(0.7, 1.3)
            daily_vol = round(max(50, daily_vol), 1)
            shipper_seg_daily[(sid, seg_id)] = daily_vol
            nominations.append((nom_id, sid, seg_id, daily_vol))
            nom_id += 1

    # Ensure at least SCALE rows
    while len(nominations) < SCALE["rows_per_table"]:
        sid = random.choice(ship_ids)
        seg = random.choice(seg_ids)
        if (sid, seg) not in shipper_seg_daily:
            vol = round(random.uniform(100, 2000), 1)
            shipper_seg_daily[(sid, seg)] = vol
            nominations.append((nom_id, sid, seg, vol))
            nom_id += 1

    cursor.execute("""
        CREATE TABLE nominations (
            nomination_id INTEGER PRIMARY KEY,
            shipper_id TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            daily_volume_mmbtu REAL NOT NULL,
            FOREIGN KEY (shipper_id) REFERENCES shippers(shipper_id),
            FOREIGN KEY (segment_id) REFERENCES pipeline_segments(segment_id)
        )
    """)
    cursor.executemany(
        "INSERT INTO nominations VALUES (?,?,?,?)", nominations
    )

    # ========================================================================
    # Identify segments with pressure anomalies (~15%)
    # ========================================================================
    n_anomaly_segs = max(1, round(n_seg * 0.15))
    anomaly_segs = set(random.sample(seg_ids, n_anomaly_segs))
    seg_anomaly_hours = {}
    for seg_id in anomaly_segs:
        n_hours = random.randint(2, 4)
        hours = random.sample(range(24), n_hours)
        seg_anomaly_hours[seg_id] = set(hours)

    # ========================================================================
    # 6. Sensor Readings (n_seg x 24)
    # ========================================================================
    sensor_rows = []
    reading_id = 1

    for seg_id in seg_ids:
        spec = seg_specs[seg_id]
        min_p = spec["min_pressure_psi"]
        max_p = spec["max_pressure_psi"]

        # Compute hourly flow from nominations
        hourly_flow = [0.0] * 24
        for sid in seg_shipper_map.get(seg_id, []):
            key = (sid, seg_id)
            if key in shipper_seg_daily:
                dv = shipper_seg_daily[key]
                prof = shipper_profiles[sid]["hourly_profile"]
                for h in range(24):
                    hourly_flow[h] += dv * prof[h]

        base_temp = random.uniform(55, 80)

        for h in range(24):
            # Pressure
            if seg_id in anomaly_segs and h in seg_anomaly_hours.get(seg_id, set()):
                if random.random() < 0.5:
                    pressure = max_p * random.uniform(1.05, 1.15)
                else:
                    pressure = min_p * random.uniform(0.85, 0.95)
            else:
                pressure = random.uniform(min_p + 20, max_p - 20)

            flow_rate = hourly_flow[h] + random.uniform(-5, 5)
            flow_rate = max(0, flow_rate)
            temp = base_temp + random.uniform(-3, 3) + 5 * math.sin(math.pi * h / 12)
            temp = min(90, max(50, temp))

            sensor_rows.append((
                reading_id, seg_id, h,
                round(pressure, 2),
                round(flow_rate, 2),
                round(temp, 2),
            ))
            reading_id += 1

    cursor.execute("""
        CREATE TABLE sensor_readings (
            reading_id INTEGER PRIMARY KEY,
            segment_id TEXT NOT NULL,
            hour INTEGER NOT NULL,
            pressure_psi REAL NOT NULL,
            flow_rate_mmbtu_hr REAL NOT NULL,
            temperature_f REAL NOT NULL,
            FOREIGN KEY (segment_id) REFERENCES pipeline_segments(segment_id)
        )
    """)
    cursor.executemany(
        "INSERT INTO sensor_readings VALUES (?,?,?,?,?,?)", sensor_rows
    )

    # ========================================================================
    # 7. Compressor Logs (n_comp x 24)
    # ========================================================================
    comp_rows = []
    log_id = 1
    for station_id, _, seg_id in stations:
        cap = seg_specs[seg_id]["max_capacity_mmbtu_hr"]
        base_throughput = cap * random.uniform(0.3, 0.7)
        for h in range(24):
            hourly_factor = 0.7 + 0.3 * math.sin(math.pi * (h - 4) / 12)
            throughput = base_throughput * hourly_factor * random.uniform(0.9, 1.1)
            throughput = max(10, throughput)
            fuel = throughput * random.uniform(0.02, 0.05)
            comp_rows.append((
                log_id, station_id, h,
                round(fuel, 2),
                round(throughput, 2),
            ))
            log_id += 1

    cursor.execute("""
        CREATE TABLE compressor_logs (
            log_id INTEGER PRIMARY KEY,
            station_id TEXT NOT NULL,
            hour INTEGER NOT NULL,
            fuel_consumed_mmbtu REAL NOT NULL,
            throughput_mmbtu_hr REAL NOT NULL,
            FOREIGN KEY (station_id) REFERENCES compressor_stations(station_id)
        )
    """)
    cursor.executemany(
        "INSERT INTO compressor_logs VALUES (?,?,?,?,?)", comp_rows
    )

    # ========================================================================
    # 8. Demand Forecasts (n_cust x 24)
    # ========================================================================
    demand_rows = []
    forecast_id = 1
    for cid, _, connected_seg in customers:
        total_noms_on_seg = sum(
            shipper_seg_daily.get((sid, connected_seg), 0)
            for sid in seg_shipper_map.get(connected_seg, [])
        )
        n_custs_on_seg = sum(1 for c in customers if c[2] == connected_seg)
        daily_demand = (total_noms_on_seg / max(1, n_custs_on_seg)) * random.uniform(0.8, 1.2)
        daily_demand = max(50, daily_demand)

        for h in range(24):
            if 7 <= h <= 20:
                frac = random.uniform(0.05, 0.07)
            else:
                frac = random.uniform(0.015, 0.03)
            hourly_demand = daily_demand * frac
            demand_rows.append((
                forecast_id, cid, h,
                round(hourly_demand, 2),
            ))
            forecast_id += 1

    cursor.execute("""
        CREATE TABLE demand_forecasts (
            forecast_id INTEGER PRIMARY KEY,
            customer_id TEXT NOT NULL,
            hour INTEGER NOT NULL,
            forecasted_demand_mmbtu REAL NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)
    cursor.executemany(
        "INSERT INTO demand_forecasts VALUES (?,?,?,?)", demand_rows
    )

    conn.commit()
    conn.close()

    # ====================================================================
    # WORKSPACE FILES
    # ====================================================================

    # -- Shipper contract files (JSON) --
    shippers_per_file = math.ceil(n_ship / n_shipper_files)
    for fidx in range(n_shipper_files):
        start = fidx * shippers_per_file
        end = min(start + shippers_per_file, n_ship)
        contracts = []
        for i in range(start, end):
            sid = ship_ids[i]
            prof = shipper_profiles[sid]
            max_daily = sum(
                shipper_seg_daily.get((sid, seg), 0) for seg in shipper_seg_map[sid]
            ) * random.uniform(1.1, 1.5)
            contracts.append({
                "shipper_id": sid,
                "max_daily_volume_mmbtu": round(max_daily, 1),
                "priority_tier": prof["priority_tier"],
                "penalty_rate_usd_per_mmbtu": prof["penalty_rate_usd_per_mmbtu"],
                "hourly_profile": [round(v, 6) for v in prof["hourly_profile"]],
                "profile_type": prof["profile_type"],
            })
        fname = os.path.join(workspace, f"shipper_contracts_{fidx+1:02d}.json")
        with open(fname, "w") as f:
            json.dump(contracts, f, indent=2)

    # -- Customer profile files (CSV) --
    cust_types = ["residential", "commercial", "industrial"]
    criticalities = ["high", "medium", "low"]
    custs_per_file = math.ceil(n_cust / n_customer_files)
    for fidx in range(n_customer_files):
        start = fidx * custs_per_file
        end = min(start + custs_per_file, n_cust)
        fname = os.path.join(workspace, f"customer_profiles_{fidx+1:02d}.csv")
        with open(fname, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "customer_id", "customer_type",
                "min_delivery_obligation_mmbtu_hr", "criticality",
            ])
            for i in range(start, end):
                cid = cust_ids[i]
                ctype = random.choice(cust_types)
                if ctype == "industrial":
                    min_del = round(random.uniform(10, 50), 2)
                elif ctype == "commercial":
                    min_del = round(random.uniform(5, 25), 2)
                else:
                    min_del = round(random.uniform(1, 10), 2)
                crit = random.choice(criticalities)
                writer.writerow([cid, ctype, min_del, crit])

    # -- Segment specification files (YAML) --
    segs_per_file = math.ceil(n_seg / n_segment_files)
    for fidx in range(n_segment_files):
        start = fidx * segs_per_file
        end = min(start + segs_per_file, n_seg)
        specs_list = []
        for i in range(start, end):
            sid = seg_ids[i]
            specs_list.append(seg_specs[sid])
        fname = os.path.join(workspace, f"segment_specs_{fidx+1:02d}.yaml")
        if yaml is not None:
            with open(fname, "w") as f:
                yaml.dump({"segments": specs_list}, f, default_flow_style=False)
        else:
            with open(fname, "w") as f:
                f.write("segments:\n")
                for sp in specs_list:
                    f.write(f"- segment_id: {sp['segment_id']}\n")
                    f.write(f"  max_capacity_mmbtu_hr: {sp['max_capacity_mmbtu_hr']}\n")
                    f.write(f"  min_pressure_psi: {sp['min_pressure_psi']}\n")
                    f.write(f"  max_pressure_psi: {sp['max_pressure_psi']}\n")
                    f.write(f"  diameter_inches: {sp['diameter_inches']}\n")
                    f.write(f"  length_miles: {sp['length_miles']}\n")

    # -- Fixed policy files --

    # operational_rules.txt
    rules_text = """\
=== Gas Pipeline Nomination Optimization - Operational Rules ===

1. OVERPRESSURE FACTOR
   When a segment's pressure reading exceeds max_pressure_psi at a given hour,
   the effective capacity for that hour is reduced:
       effective_capacity = max_capacity_mmbtu_hr * 0.85
   (OVERPRESSURE_FACTOR = 0.85)

2. UNDERPRESSURE FACTOR
   When a segment's pressure reading falls below min_pressure_psi at a given hour,
   the effective capacity for that hour is reduced:
       effective_capacity = max_capacity_mmbtu_hr * 0.90
   (UNDERPRESSURE_FACTOR = 0.90)

3. NORMAL OPERATION
   When pressure is within [min_pressure_psi, max_pressure_psi], effective capacity
   equals max_capacity_mmbtu_hr (factor = 1.0).

4. CURTAILMENT ORDER
   When total nominated flow on a segment exceeds effective capacity at any hour,
   curtailment is applied in the following order:
     a. Sort shippers by priority_tier DESCENDING (tier 5 curtailed first, tier 1 last).
     b. Ties are broken by shipper_id ASCENDING (alphabetical order).
     c. Curtail each shipper's hourly volume in order until total flow <= effective capacity.

5. CUSTOMER PROTECTION RULE
   The total adjusted flow on a segment must never fall below the sum of
   min_delivery_obligation_mmbtu_hr for all customers connected to that segment.
   If curtailment would violate this constraint:
       max_curtailable = total_nominated - sum(min_delivery_obligations)
   Curtailment is capped at max_curtailable.

6. HOURLY VOLUME CALCULATION
   For each shipper-segment nomination:
       hourly_volume(h) = daily_volume_mmbtu * hourly_profile[h]
   where hourly_profile is the shipper's 24-element profile (sums to 1.0).
"""
    with open(os.path.join(workspace, "operational_rules.txt"), "w") as f:
        f.write(rules_text)

    # compressor_config.csv
    with open(os.path.join(workspace, "compressor_config.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "station_id", "max_throughput_mmbtu_hr",
            "base_fuel_rate", "efficiency_pct",
        ])
        for station_id, _, seg_id in stations:
            cap = seg_specs[seg_id]["max_capacity_mmbtu_hr"]
            max_thr = round(cap * random.uniform(0.6, 1.0), 1)
            base_fuel = round(random.uniform(0.02, 0.05), 4)
            eff = round(random.uniform(80, 98), 1)
            writer.writerow([station_id, max_thr, base_fuel, eff])

    # fuel_prices.json
    fuel_prices = {}
    for h in range(24):
        if (7 <= h <= 9) or (17 <= h <= 20):
            price = round(random.uniform(4.0, 6.0), 2)
        else:
            price = round(random.uniform(2.0, 3.0), 2)
        fuel_prices[str(h)] = price
    with open(os.path.join(workspace, "fuel_prices.json"), "w") as f:
        json.dump(fuel_prices, f, indent=2)

    # network_map.yaml
    all_nodes = sorted(set(
        [s[2] for s in segments] + [s[3] for s in segments]
    ))
    connections = [
        {"segment_id": s[0], "from_node": s[2], "to_node": s[3]}
        for s in segments
    ]
    network = {"nodes": all_nodes, "connections": connections}
    fname = os.path.join(workspace, "network_map.yaml")
    if yaml is not None:
        with open(fname, "w") as f:
            yaml.dump(network, f, default_flow_style=False)
    else:
        with open(fname, "w") as f:
            f.write("nodes:\n")
            for n in all_nodes:
                f.write(f"- {n}\n")
            f.write("connections:\n")
            for c in connections:
                f.write(f"- segment_id: {c['segment_id']}\n")
                f.write(f"  from_node: {c['from_node']}\n")
                f.write(f"  to_node: {c['to_node']}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate gas pipeline nomination optimization data"
    )
    parser.add_argument("--db_path", required=True, help="Path to SQLite database")
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    args = parser.parse_args()
    main(args.db_path, args.workspace)
