"""
Data generation for EV Charging Station Relocation Analysis task.
Generates database tables and workspace files at the configured SCALE.
"""

import argparse
import os
import sqlite3
import json
import csv
import math
import random
import numpy as np
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 30,
    "num_workspace_files": 10,
}


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    R = SCALE["rows_per_table"]
    F = SCALE["num_workspace_files"]

    # ================================================================
    # CREATE TABLES
    # ================================================================
    cur.executescript("""
        CREATE TABLE regions (
            region_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            state TEXT NOT NULL,
            population INTEGER NOT NULL,
            area_sq_km REAL NOT NULL,
            urban_pct REAL NOT NULL
        );
        CREATE TABLE charging_stations (
            station_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region_id INTEGER NOT NULL REFERENCES regions(region_id),
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            num_chargers INTEGER NOT NULL,
            charger_type TEXT NOT NULL,
            install_date TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE monthly_station_stats (
            stat_id INTEGER PRIMARY KEY,
            station_id INTEGER NOT NULL REFERENCES charging_stations(station_id),
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            total_sessions INTEGER NOT NULL,
            completed_sessions INTEGER NOT NULL,
            failed_sessions INTEGER NOT NULL,
            total_charge_hours REAL NOT NULL,
            energy_kwh REAL NOT NULL,
            revenue REAL NOT NULL
        );
        CREATE TABLE session_failures (
            failure_id INTEGER PRIMARY KEY,
            station_id INTEGER NOT NULL REFERENCES charging_stations(station_id),
            failure_date TEXT NOT NULL,
            failure_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            resolution_hours REAL NOT NULL,
            description TEXT
        );
        CREATE TABLE competitors (
            competitor_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            num_chargers INTEGER NOT NULL,
            network TEXT NOT NULL,
            region_id INTEGER NOT NULL REFERENCES regions(region_id)
        );
        CREATE TABLE ev_registrations (
            reg_id INTEGER PRIMARY KEY,
            region_id INTEGER NOT NULL REFERENCES regions(region_id),
            year INTEGER NOT NULL,
            quarter INTEGER NOT NULL,
            vehicle_count INTEGER NOT NULL,
            vehicle_type TEXT NOT NULL
        );
    """)

    # ================================================================
    # GENERATE DATA
    # ================================================================

    STATES = [
        "CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI",
        "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
        "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT",
        "IA", "NV", "AR", "MS", "KS", "NM", "NE", "ID", "WV", "HI",
        "NH", "ME", "MT", "RI", "DE", "SD", "ND", "AK", "VT", "WY",
    ]

    # --- Regions ---
    regions = []
    for i in range(R):
        r = (i + 1, fake.city(), STATES[i % len(STATES)],
             random.randint(50000, 2000000),
             round(random.uniform(100, 5000), 1),
             round(random.uniform(0.30, 0.95), 2))
        regions.append(r)
        cur.execute("INSERT INTO regions VALUES (?,?,?,?,?,?)", r)

    # --- Charging Stations (~33 % deliberately underperforming) ---
    CHARGER_TYPES = ["Level 2", "DC Fast", "Level 2/DC Fast"]
    n_under = max(3, R // 3)
    under_set = set(random.sample(range(R), n_under))

    stations = []
    for i in range(R):
        rid = regions[i % len(regions)][0]
        s = (i + 1,
             f"{fake.company()} Charging Hub",
             rid,
             round(random.uniform(25.0, 48.0), 6),
             round(random.uniform(-124.0, -71.0), 6),
             random.randint(3, 10),
             random.choice(CHARGER_TYPES),
             fake.date_between(start_date="-5y", end_date="-1y").isoformat(),
             "active")
        stations.append(s)
        cur.execute("INSERT INTO charging_stations VALUES (?,?,?,?,?,?,?,?,?)", s)

    under_region_ids = {stations[i][2] for i in under_set}

    # --- Monthly Station Stats (year 2024, 12 months per station) ---
    ANNUAL_HOURS = 6570  # 18 h/day * 365
    MONTHLY_HOURS = ANNUAL_HOURS / 12.0

    stat_id = 0
    station_annual = {}
    for idx, s in enumerate(stations):
        sid, nc = s[0], s[5]
        is_under = idx in under_set
        annual = dict(charge_hours=0.0, total_sess=0, completed=0, failed=0,
                      energy=0.0, revenue=0.0)
        for m in range(1, 13):
            if is_under:
                u = float(np.clip(np.random.normal(0.22, 0.06), 0.08, 0.37))
                fr = float(np.clip(np.random.normal(0.20, 0.05), 0.12, 0.35))
            else:
                u = float(np.clip(np.random.normal(0.58, 0.08), 0.42, 0.80))
                fr = float(np.clip(np.random.normal(0.05, 0.02), 0.01, 0.10))
            ch = round(u * nc * MONTHLY_HOURS, 2)
            ts = max(1, int(ch / 2.5 + np.random.normal(0, 3)))
            fs = max(0, min(ts - 1, int(ts * fr)))
            cs = ts - fs
            en = round(ch * random.uniform(5.0, 8.0), 2)
            rv = round(en * random.uniform(0.28, 0.42), 2)
            stat_id += 1
            cur.execute("INSERT INTO monthly_station_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (stat_id, sid, 2024, m, ts, cs, fs, ch, en, rv))
            annual["charge_hours"] += ch
            annual["total_sess"] += ts
            annual["completed"] += cs
            annual["failed"] += fs
            annual["energy"] += en
            annual["revenue"] += rv
        station_annual[sid] = annual

    # --- Session Failures ---
    FAIL_TYPES = [
        "connector_error", "payment_failure", "power_surge",
        "communication_timeout", "overcurrent_protection",
        "ground_fault", "thermal_shutdown",
    ]
    SEVERITIES = ["low", "medium", "high", "critical"]
    SEV_W = [0.30, 0.35, 0.25, 0.10]
    FAIL_DESC = {
        "connector_error": ["Connector failed to lock",
                            "Connector communication lost",
                            "Pin misalignment detected"],
        "payment_failure": ["Card reader malfunction",
                            "Network timeout during payment",
                            "Authentication failed"],
        "power_surge": ["Grid voltage spike detected",
                        "Internal power regulation failure",
                        "Surge protector triggered"],
        "communication_timeout": ["Backend server unreachable",
                                  "OCPP heartbeat lost",
                                  "Cellular module reset"],
        "overcurrent_protection": ["Charger overcurrent on phase A",
                                   "Current limiter engaged",
                                   "Breaker tripped"],
        "ground_fault": ["Ground fault detected on connector",
                         "Isolation monitoring alert",
                         "PE continuity lost"],
        "thermal_shutdown": ["Cabinet temperature exceeded limit",
                             "Thermal runaway prevention",
                             "Cooling system failure"],
    }

    fid = 0
    for s in stations:
        sid = s[0]
        n_fail = station_annual[sid]["failed"]
        for _ in range(n_fail):
            fid += 1
            ft = random.choice(FAIL_TYPES)
            sv = random.choices(SEVERITIES, weights=SEV_W)[0]
            cur.execute(
                "INSERT INTO session_failures VALUES (?,?,?,?,?,?,?)",
                (fid, sid,
                 fake.date_between(start_date="-1y", end_date="now").isoformat(),
                 ft, sv,
                 round(random.uniform(0.5, 48 if sv in ("high", "critical") else 12), 1),
                 random.choice(FAIL_DESC[ft])))
    while fid < R:
        fid += 1
        sid = random.choice(stations)[0]
        ft = random.choice(FAIL_TYPES)
        sv = random.choices(SEVERITIES, weights=SEV_W)[0]
        cur.execute(
            "INSERT INTO session_failures VALUES (?,?,?,?,?,?,?)",
            (fid, sid,
             fake.date_between(start_date="-1y", end_date="now").isoformat(),
             ft, sv,
             round(random.uniform(0.5, 12), 1),
             random.choice(FAIL_DESC[ft])))

    # --- Competitors (more near underperforming stations) ---
    NETWORKS = ["ChargePoint", "EVgo", "Electrify America",
                "Tesla Supercharger", "Blink", "SemaConnect"]
    cid = 0
    for idx, s in enumerate(stations):
        n_comp = random.randint(3, 7) if idx in under_set else random.randint(0, 3)
        for _ in range(n_comp):
            cid += 1
            cur.execute(
                "INSERT INTO competitors VALUES (?,?,?,?,?,?,?)",
                (cid,
                 f"{fake.company()} Charging",
                 round(s[3] + random.uniform(-0.08, 0.08), 6),
                 round(s[4] + random.uniform(-0.08, 0.08), 6),
                 random.randint(2, 16),
                 random.choice(NETWORKS),
                 s[2]))
    while cid < R:
        cid += 1
        s = random.choice(stations)
        cur.execute(
            "INSERT INTO competitors VALUES (?,?,?,?,?,?,?)",
            (cid,
             f"{fake.company()} Charging",
             round(s[3] + random.uniform(-0.08, 0.08), 6),
             round(s[4] + random.uniform(-0.08, 0.08), 6),
             random.randint(2, 16),
             random.choice(NETWORKS),
             s[2]))

    # --- EV Registrations (lower growth for underperforming regions) ---
    VEH_TYPES = ["BEV", "PHEV"]
    reg_auto = 0
    for reg in regions:
        rid = reg[0]
        is_low = rid in under_region_ids
        base = random.randint(800, 8000)
        for yr in [2023, 2024]:
            for q in [1, 2, 3, 4]:
                for vt in VEH_TYPES:
                    reg_auto += 1
                    g = random.uniform(0.005, 0.03) if is_low else random.uniform(0.04, 0.12)
                    period = (yr - 2023) * 4 + (q - 1)
                    cnt = int(base * (1 + g) ** period * (0.7 if vt == "PHEV" else 1.0))
                    cur.execute(
                        "INSERT INTO ev_registrations VALUES (?,?,?,?,?,?)",
                        (reg_auto, rid, yr, q, cnt, vt))

    conn.commit()

    # ================================================================
    # WORKSPACE FILES
    # ================================================================

    # ---- Fixed configuration files (not counted in num_workspace_files) ----
    scoring_config = {
        "underperformance_thresholds": {
            "adjusted_utilization_below": 0.40,
            "failure_rate_above": 0.12,
        },
        "scoring_weights": {
            "utilization_deficit": 0.30,
            "failure_severity": 0.25,
            "competitor_pressure": 0.25,
            "ev_growth_deficit": 0.20,
        },
        "competitor_radius_km": 15.0,
        "competitor_cap": 5,
        "min_composite_score": 0.25,
    }
    with open(os.path.join(workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(scoring_config, f, default_flow_style=False, sort_keys=False)

    revenue_params = {
        "benchmark_utilization": 0.65,
        "revenue_per_charger_hour": 8.50,
        "annual_operating_hours": ANNUAL_HOURS,
        "relocation_cost_per_charger": 15000,
    }
    with open(os.path.join(workspace, "revenue_model_params.json"), "w") as f:
        json.dump(revenue_params, f, indent=2)

    # ---- Scaling workspace files ----
    n_cost = max(1, round(F * 0.4))
    n_fore = max(1, round(F * 0.3))
    n_maint = max(1, F - n_cost - n_fore)

    # Station-cost CSV files
    per_cost = math.ceil(len(stations) / n_cost)
    for fi in range(n_cost):
        batch = stations[fi * per_cost:(fi + 1) * per_cost]
        with open(os.path.join(workspace, f"station_costs_batch_{fi + 1}.csv"),
                  "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["station_id", "monthly_lease", "electricity_cost",
                         "maintenance_cost", "staff_cost"])
            for s in batch:
                nc = s[5]
                w.writerow([
                    s[0],
                    round(800 + nc * random.uniform(200, 450), 2),
                    round(500 + nc * random.uniform(150, 350), 2),
                    round(300 + nc * random.uniform(80, 200), 2),
                    round(400 + nc * random.uniform(100, 250), 2),
                ])

    # EV-market forecast JSON files — cover first ~75 % of regions
    n_forecast_regions = max(1, int(len(regions) * 0.75))
    forecast_regions = regions[:n_forecast_regions]
    per_fore = max(1, math.ceil(len(forecast_regions) / n_fore))
    for fi in range(n_fore):
        batch = forecast_regions[fi * per_fore:(fi + 1) * per_fore]
        data = []
        for r in batch:
            rid = r[0]
            is_low = rid in under_region_ids
            data.append({
                "region_id": rid,
                "region_name": r[1],
                "projected_ev_growth_rate": round(
                    random.uniform(0.02, 0.06) if is_low
                    else random.uniform(0.10, 0.28), 4),
                "market_saturation_index": round(
                    random.uniform(0.55, 0.85) if is_low
                    else random.uniform(0.15, 0.50), 4),
            })
        with open(os.path.join(workspace, f"ev_market_forecast_{fi + 1}.json"),
                  "w") as f:
            json.dump(data, f, indent=2)

    # Maintenance / downtime log TXT files
    records = []
    for idx, s in enumerate(stations):
        sid, nc = s[0], s[5]
        is_under = idx in under_set
        n_inc = random.randint(3, 8) if is_under else random.randint(0, 3)
        for _ in range(n_inc):
            records.append({
                "station_id": sid,
                "date": fake.date_between(
                    start_date="-1y", end_date="now").isoformat(),
                "downtime_hours": round(
                    random.uniform(8, 72) if is_under
                    else random.uniform(2, 24), 1),
                "chargers_affected": random.randint(1, nc),
                "reason": random.choice([
                    "Scheduled maintenance", "Charger unit malfunction",
                    "Power grid outage", "Software update required",
                    "Vandalism repair", "Connector replacement",
                    "Electrical inspection", "Weather damage repair",
                ]),
            })
    random.shuffle(records)
    per_maint = max(1, math.ceil(len(records) / n_maint))
    for fi in range(n_maint):
        batch = records[fi * per_maint:(fi + 1) * per_maint]
        with open(os.path.join(workspace, f"maintenance_log_{fi + 1}.txt"),
                  "w") as f:
            for rec in batch:
                f.write(f"Station ID: {rec['station_id']}\n")
                f.write(f"Date: {rec['date']}\n")
                f.write(f"Downtime Hours: {rec['downtime_hours']}\n")
                f.write(f"Chargers Affected: {rec['chargers_affected']}\n")
                f.write(f"Reason: {rec['reason']}\n")
                f.write("---\n")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
