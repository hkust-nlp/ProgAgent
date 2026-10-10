#!/usr/bin/env python3
"""Generate pilot duty-time compliance database and workspace files."""

import argparse
import os
import sqlite3
import json
import csv
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 16,
}

# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AIRPORTS = [
    "ATL", "ORD", "DFW", "DEN", "LAX", "JFK", "SFO", "SEA",
    "MIA", "BOS", "PHX", "IAH", "MSP", "DTW", "EWR",
]
BASES = ["ATL", "ORD", "DFW", "LAX", "JFK"]
RANKS = ["Captain", "First Officer"]
LICENSE_TYPES = ["ATPL", "CPL"]
DUTY_TYPES = ["regular", "reserve", "deadhead", "training"]
FACILITY_TYPES = ["hotel", "crew_room", "home", "airport_lounge"]

ANALYSIS_START = datetime(2025, 1, 1)
ANALYSIS_END = datetime(2025, 1, 31, 23, 59, 59)
PRIOR_START = datetime(2024, 12, 1)
PRIOR_END = datetime(2024, 12, 31, 23, 59, 59)

# Timezone offsets (UTC hours) for airports
TIMEZONE_MAP = {
    "ATL": -5, "ORD": -6, "DFW": -6, "DEN": -7, "LAX": -8,
    "JFK": -5, "SFO": -8, "SEA": -8, "MIA": -5, "BOS": -5,
    "PHX": -7, "IAH": -6, "MSP": -6, "DTW": -5, "EWR": -5,
}

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS pilots (
        pilot_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        employee_number TEXT UNIQUE NOT NULL,
        rank TEXT NOT NULL,
        base_airport TEXT NOT NULL,
        license_type TEXT NOT NULL,
        hire_date TEXT NOT NULL,
        medical_expiry TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS crew_pairings (
        pairing_id INTEGER PRIMARY KEY,
        pilot_id INTEGER NOT NULL,
        pairing_code TEXT UNIQUE NOT NULL,
        report_time TEXT NOT NULL,
        release_time TEXT NOT NULL,
        duty_type TEXT NOT NULL,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        FOREIGN KEY (pilot_id) REFERENCES pilots(pilot_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS flight_logs (
        log_id INTEGER PRIMARY KEY,
        pairing_id INTEGER,
        pilot_id INTEGER NOT NULL,
        flight_number TEXT NOT NULL,
        scheduled_departure TEXT NOT NULL,
        actual_departure TEXT NOT NULL,
        scheduled_arrival TEXT NOT NULL,
        actual_arrival TEXT NOT NULL,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        FOREIGN KEY (pairing_id) REFERENCES crew_pairings(pairing_id),
        FOREIGN KEY (pilot_id) REFERENCES pilots(pilot_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS rest_declarations (
        declaration_id INTEGER PRIMARY KEY,
        pilot_id INTEGER NOT NULL,
        rest_start TEXT NOT NULL,
        rest_end TEXT NOT NULL,
        location TEXT NOT NULL,
        facility_type TEXT NOT NULL,
        self_reported_quality INTEGER NOT NULL,
        FOREIGN KEY (pilot_id) REFERENCES pilots(pilot_id)
    )""")
    conn.commit()


def generate_pilots(conn, n_pilots):
    pilots = []
    used_names = set()
    for i in range(1, n_pilots + 1):
        while True:
            name = fake.name()
            if name not in used_names:
                used_names.add(name)
                break
        emp_num = f"EMP{10000 + i}"
        rank = RANKS[i % 2]
        base = BASES[i % len(BASES)]
        lt = "ATPL" if rank == "Captain" else random.choice(LICENSE_TYPES)
        hire = fake.date_between(start_date="-20y", end_date="-1y").isoformat()
        med = fake.date_between(start_date="+1m", end_date="+24m").isoformat()
        pilots.append((i, name, emp_num, rank, base, lt, hire, med))
    conn.executemany("INSERT INTO pilots VALUES (?,?,?,?,?,?,?,?)", pilots)
    conn.commit()
    return pilots


def generate_crew_pairings(conn, pilots, n_pairings):
    """Generate pairings per pilot.

    Schedule types:
      - Type A (60 %): spread-out, normal hours
      - Type B (25 %): some back-to-back days (rest-violation prone)
      - Type C (15 %): heavy + early/late starts (FDP-violation prone)
    """
    pairings = []
    used_codes = set()
    n_pilots_count = len(pilots)
    per_pilot = n_pairings // n_pilots_count
    remainder = n_pairings % n_pilots_count

    pairing_id = 1
    for pi, pilot in enumerate(pilots):
        pilot_id = pilot[0]
        n_p = per_pilot + (1 if pi < remainder else 0)

        # Decide schedule type
        if pi % 20 < 12:
            stype = "A"
        elif pi % 20 < 17:
            stype = "B"
        else:
            stype = "C"

        # Generate days for this pilot's pairings
        days_and_hours = []
        for j in range(n_p):
            if stype == "B" and j > 0 and j % 2 == 1:
                # Next day after previous, late release + early report → short rest
                prev_day = days_and_hours[-1][0]
                day = min(prev_day + 1, 28)
                report_hour = random.choice([5, 6, 7])  # early start
                duty_h = random.uniform(7, 10)
            elif stype == "C":
                day = random.randint(1, 28)
                report_hour = random.choice([5, 5, 6, 14, 15, 22, 23])
                duty_h = random.uniform(11.5, 15.5)  # long duty → FDP violation
            else:
                # Type A: well-spaced
                base = int((j + 1) * 28 / (n_p + 1))
                day = max(1, min(base + random.randint(-1, 1), 28))
                report_hour = random.choice([7, 8, 9, 10, 11, 12, 13])
                duty_h = random.uniform(6, 10)

            # For Type B first in a pair, use a late departure
            if stype == "B" and j % 2 == 0:
                report_hour = random.choice([14, 15, 16, 17])
                duty_h = random.uniform(8, 12)

            days_and_hours.append((day, report_hour, duty_h))

        # Sort by (day, hour) to keep chronological order
        days_and_hours.sort(key=lambda x: (x[0], x[1]))

        for day, rh, duty_h in days_and_hours:
            while True:
                code = f"P{random.randint(1000, 9999)}"
                if code not in used_codes:
                    used_codes.add(code)
                    break

            report_time = datetime(2025, 1, day, rh, random.randint(0, 59))
            release_time = report_time + timedelta(hours=duty_h)
            duty_type = random.choices(DUTY_TYPES, weights=[0.7, 0.15, 0.1, 0.05])[0]
            origin = AIRPORTS[pairing_id % len(AIRPORTS)]
            dest = AIRPORTS[(pairing_id + 3) % len(AIRPORTS)]
            if dest == origin:
                dest = AIRPORTS[(pairing_id + 5) % len(AIRPORTS)]

            pairings.append((
                pairing_id, pilot_id, code,
                report_time.strftime("%Y-%m-%dT%H:%M:%S"),
                release_time.strftime("%Y-%m-%dT%H:%M:%S"),
                duty_type, origin, dest,
            ))
            pairing_id += 1

    conn.executemany("INSERT INTO crew_pairings VALUES (?,?,?,?,?,?,?,?)", pairings)
    conn.commit()
    return pairings


def generate_flight_logs(conn, pairings, pilots, n_flights):
    logs = []
    log_id = 1

    # One flight per pairing
    for p in pairings:
        pairing_id, pilot_id = p[0], p[1]
        report_time = datetime.fromisoformat(p[3])
        origin, dest = p[6], p[7]

        sched_dep = report_time + timedelta(minutes=random.randint(30, 60))
        delay_min = random.choices([0, 0, 0, 15, 30, 60, 90], weights=[4, 2, 1, 1, 1, 1, 1])[0]
        actual_dep = sched_dep + timedelta(minutes=delay_min)
        flight_h = random.uniform(1.5, 4.5)
        sched_arr = sched_dep + timedelta(hours=flight_h)
        actual_arr = actual_dep + timedelta(hours=flight_h + random.uniform(-0.1, 0.2))
        fnum = f"FL{100 + log_id}"

        logs.append((
            log_id, pairing_id, pilot_id, fnum,
            sched_dep.strftime("%Y-%m-%dT%H:%M:%S"),
            actual_dep.strftime("%Y-%m-%dT%H:%M:%S"),
            sched_arr.strftime("%Y-%m-%dT%H:%M:%S"),
            actual_arr.strftime("%Y-%m-%dT%H:%M:%S"),
            origin, dest,
        ))
        log_id += 1

    # Pad to reach minimum row count
    while len(logs) < n_flights:
        pilot = pilots[log_id % len(pilots)]
        pilot_id = pilot[0]
        day = (log_id % 28) + 1
        dep_h = random.randint(6, 20)
        sched_dep = datetime(2025, 1, day, dep_h, random.randint(0, 59))
        actual_dep = sched_dep + timedelta(minutes=random.choice([0, 10, 25]))
        fh = random.uniform(1.5, 4.0)
        sched_arr = sched_dep + timedelta(hours=fh)
        actual_arr = actual_dep + timedelta(hours=fh)
        fnum = f"FL{100 + log_id}"
        origin = AIRPORTS[log_id % len(AIRPORTS)]
        dest = AIRPORTS[(log_id + 4) % len(AIRPORTS)]
        if dest == origin:
            dest = AIRPORTS[(log_id + 6) % len(AIRPORTS)]
        logs.append((
            log_id, None, pilot_id, fnum,
            sched_dep.strftime("%Y-%m-%dT%H:%M:%S"),
            actual_dep.strftime("%Y-%m-%dT%H:%M:%S"),
            sched_arr.strftime("%Y-%m-%dT%H:%M:%S"),
            actual_arr.strftime("%Y-%m-%dT%H:%M:%S"),
            origin, dest,
        ))
        log_id += 1

    conn.executemany("INSERT INTO flight_logs VALUES (?,?,?,?,?,?,?,?,?,?)", logs)
    conn.commit()
    return logs


def generate_rest_declarations(conn, pilots, pairings, n_rest):
    rests = []
    decl_id = 1

    # Sort pairings by pilot then time to create realistic rest periods
    sorted_pairs = sorted(pairings, key=lambda p: (p[1], p[3]))

    for i, p in enumerate(sorted_pairs):
        pilot_id = p[1]
        release_time = datetime.fromisoformat(p[4])
        rest_start = release_time + timedelta(minutes=random.randint(15, 45))

        # ~15 % short rest (violation)
        if decl_id % 7 == 0:
            rest_hours = random.uniform(6.0, 9.5)
        else:
            rest_hours = random.uniform(10.5, 16.0)

        rest_end = rest_start + timedelta(hours=rest_hours)
        location = random.choice(AIRPORTS)
        facility = random.choice(FACILITY_TYPES)
        quality = random.randint(1, 5)

        rests.append((
            decl_id, pilot_id,
            rest_start.strftime("%Y-%m-%dT%H:%M:%S"),
            rest_end.strftime("%Y-%m-%dT%H:%M:%S"),
            location, facility, quality,
        ))
        decl_id += 1

    while len(rests) < n_rest:
        pilot = pilots[decl_id % len(pilots)]
        pilot_id = pilot[0]
        day = (decl_id % 28) + 1
        sh = random.randint(18, 23)
        rest_start = datetime(2025, 1, day, sh, random.randint(0, 59))
        rh = random.uniform(8, 14)
        rest_end = rest_start + timedelta(hours=rh)
        location = random.choice(AIRPORTS)
        facility = random.choice(FACILITY_TYPES)
        quality = random.randint(1, 5)
        rests.append((
            decl_id, pilot_id,
            rest_start.strftime("%Y-%m-%dT%H:%M:%S"),
            rest_end.strftime("%Y-%m-%dT%H:%M:%S"),
            location, facility, quality,
        ))
        decl_id += 1

    conn.executemany(
        "INSERT INTO rest_declarations VALUES (?,?,?,?,?,?,?)", rests
    )
    conn.commit()
    return rests


# ---------------------------------------------------------------------------
# Workspace – fixed config files
# ---------------------------------------------------------------------------

def create_config_files(workspace):
    cfg_dir = os.path.join(workspace, "config")
    os.makedirs(cfg_dir, exist_ok=True)

    # 1. regulatory_limits.yaml
    reg_limits = {
        "max_fdp": {
            "early_start_0500_0659": 11.0,
            "normal_0700_1359": 13.0,
            "late_start_1400_0459": 10.0,
        },
        "min_rest_period_hours": 10.0,
        "max_7day_duty_hours": 60.0,
        "max_28day_duty_hours": 190.0,
        "fatigue_risk_threshold": 75.0,
    }
    with open(os.path.join(cfg_dir, "regulatory_limits.yaml"), "w") as f:
        # Write YAML manually for readability
        f.write("# Regulatory duty-time limits\n")
        f.write("max_fdp:\n")
        f.write("  early_start_0500_0659: 11.0   # report 05:00-06:59\n")
        f.write("  normal_0700_1359: 13.0         # report 07:00-13:59\n")
        f.write("  late_start_1400_0459: 10.0     # report 14:00-04:59\n")
        f.write("\n")
        f.write("min_rest_period_hours: 10.0\n")
        f.write("max_7day_duty_hours: 60.0\n")
        f.write("max_28day_duty_hours: 190.0\n")
        f.write("fatigue_risk_threshold: 55.0\n")

    # 2. fatigue_risk_weights.json
    frw = {
        "weights": {
            "time_of_day": 0.25,
            "cumulative_hours_ratio": 0.30,
            "rest_quality": 0.20,
            "consecutive_early_starts": 0.15,
            "sectors_flown_ratio": 0.10,
        },
        "time_of_day_penalty": {
            "00-05": 1.0,
            "05-07": 0.7,
            "07-10": 0.2,
            "10-14": 0.1,
            "14-18": 0.2,
            "18-22": 0.5,
            "22-24": 0.9,
        },
        "rest_quality_baseline": 4,
        "max_consecutive_early_for_full_penalty": 3,
        "reference_sectors_per_week": 6,
    }
    with open(os.path.join(cfg_dir, "fatigue_risk_weights.json"), "w") as f:
        json.dump(frw, f, indent=2)

    # 3. severity_thresholds.yaml
    with open(os.path.join(cfg_dir, "severity_thresholds.yaml"), "w") as f:
        f.write("# Violation severity classification\n")
        f.write("fdp_exceeded:\n")
        f.write("  HIGH: 2.0    # exceeded by >= 2 hours\n")
        f.write("  MEDIUM: 1.0  # exceeded by >= 1 hour\n")
        f.write("  LOW: 0.0     # exceeded by < 1 hour\n")
        f.write("\n")
        f.write("insufficient_rest:\n")
        f.write("  HIGH: 8.0    # rest below 8 hours\n")
        f.write("  MEDIUM: 9.0  # rest below 9 hours\n")
        f.write("  LOW: 10.0    # rest below 10 hours (the regulatory min)\n")
        f.write("\n")
        f.write("cumulative_7day:\n")
        f.write("  HIGH: 5.0    # exceeded by >= 5 hours\n")
        f.write("  MEDIUM: 2.0  # exceeded by >= 2 hours\n")
        f.write("  LOW: 0.0     # exceeded by < 2 hours\n")
        f.write("\n")
        f.write("cumulative_28day:\n")
        f.write("  HIGH: 15.0   # exceeded by >= 15 hours\n")
        f.write("  MEDIUM: 5.0  # exceeded by >= 5 hours\n")
        f.write("  LOW: 0.0     # exceeded by < 5 hours\n")

    # 4. duty_type_rules.json
    dtr = {
        "regular":  {"counts_toward_fdp": True,  "cumulative_multiplier": 1.0},
        "reserve":  {"counts_toward_fdp": True,  "cumulative_multiplier": 0.75},
        "deadhead": {"counts_toward_fdp": False, "cumulative_multiplier": 0.5},
        "training": {"counts_toward_fdp": True,  "cumulative_multiplier": 1.0},
    }
    with open(os.path.join(cfg_dir, "duty_type_rules.json"), "w") as f:
        json.dump(dtr, f, indent=2)

    # 5. airport_timezones.csv
    with open(os.path.join(cfg_dir, "airport_timezones.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["airport_code", "utc_offset_hours", "timezone_name"])
        tz_names = {
            -5: "US/Eastern", -6: "US/Central", -7: "US/Mountain", -8: "US/Pacific",
        }
        for code, offset in sorted(TIMEZONE_MAP.items()):
            w.writerow([code, offset, tz_names.get(offset, "Unknown")])


# ---------------------------------------------------------------------------
# Workspace – scalable prior-hours files
# ---------------------------------------------------------------------------

def create_prior_hours_files(workspace, pilots, n_files):
    """Create CSV files with December 2024 duty hours per pilot."""
    ph_dir = os.path.join(workspace, "prior_hours")
    os.makedirs(ph_dir, exist_ok=True)

    n_pilots_count = len(pilots)
    dec_days = 31  # December has 31 days

    # Generate full prior-hours data first, then split into files
    all_records = []
    for pilot in pilots:
        pid = pilot[0]
        emp = pilot[2]
        for d in range(1, dec_days + 1):
            # Most days have some duty hours, with variation
            if random.random() < 0.35:
                duty_h = 0.0  # day off
            else:
                duty_h = round(random.uniform(4.0, 12.0), 2)
            all_records.append({
                "pilot_id": pid,
                "employee_number": emp,
                "date": f"2024-12-{d:02d}",
                "duty_hours": duty_h,
            })

    # Split records across n_files (by date ranges)
    days_per_file = max(1, math.ceil(dec_days / n_files))
    for fi in range(n_files):
        start_day = fi * days_per_file + 1
        end_day = min((fi + 1) * days_per_file, dec_days)
        if start_day > dec_days:
            break
        date_range_start = f"2024-12-{start_day:02d}"
        date_range_end = f"2024-12-{end_day:02d}"

        file_records = [
            r for r in all_records
            if date_range_start <= r["date"] <= date_range_end
        ]

        fname = os.path.join(ph_dir, f"segment_{fi + 1}.csv")
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["pilot_id", "employee_number", "date", "duty_hours"])
            w.writeheader()
            w.writerows(file_records)


# ---------------------------------------------------------------------------
# Workspace – scalable amendment files
# ---------------------------------------------------------------------------

def create_amendment_files(workspace, pairings, n_files):
    """Create JSON amendment files that modify some pairing release times."""
    amd_dir = os.path.join(workspace, "amendments")
    os.makedirs(amd_dir, exist_ok=True)

    # ~20 % of pairings receive an amendment
    amended_indices = [i for i in range(len(pairings)) if (i * 13 + 7) % 5 == 0]
    amendments = []
    for idx in amended_indices:
        p = pairings[idx]
        pairing_code = p[2]
        original_release = p[4]
        orig_dt = datetime.fromisoformat(original_release)

        # Extension by 1-3 hours
        ext_hours = round(random.uniform(1.0, 3.0), 2)
        new_release = (orig_dt + timedelta(hours=ext_hours)).strftime("%Y-%m-%dT%H:%M:%S")

        reasons = ["ATC delay", "weather hold", "maintenance extension",
                    "crew swap delay", "gate conflict", "passenger medical"]
        amendments.append({
            "pairing_code": pairing_code,
            "amendment_type": "time_extension",
            "original_release_time": original_release,
            "new_release_time": new_release,
            "extension_hours": ext_hours,
            "reason": random.choice(reasons),
        })

    # Split across files
    per_file = max(1, math.ceil(len(amendments) / n_files))
    for fi in range(n_files):
        chunk = amendments[fi * per_file: (fi + 1) * per_file]
        fname = os.path.join(amd_dir, f"batch_{fi + 1}.json")
        with open(fname, "w") as f:
            json.dump(chunk, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    # Database
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n_pilots = SCALE["rows_per_table"]
    n_pairings = SCALE["rows_per_table"] * 3
    n_flights = SCALE["rows_per_table"] * 3
    n_rest = SCALE["rows_per_table"] * 2

    pilots = generate_pilots(conn, n_pilots)
    pairings = generate_crew_pairings(conn, pilots, n_pairings)
    flight_logs = generate_flight_logs(conn, pairings, pilots, n_flights)
    rest_decls = generate_rest_declarations(conn, pilots, pairings, n_rest)
    conn.close()

    # Workspace – fixed config
    create_config_files(args.workspace)

    # Workspace – scalable files (split evenly between prior_hours and amendments)
    n_scalable = SCALE["num_workspace_files"]
    n_prior = max(1, n_scalable // 2)
    n_amend = max(1, n_scalable - n_prior)

    create_prior_hours_files(args.workspace, pilots, n_prior)
    create_amendment_files(args.workspace, pairings, n_amend)

    # Summary
    print(f"Created DB at {args.db_path}")
    print(f"  pilots:            {n_pilots}")
    print(f"  crew_pairings:     {n_pairings}")
    print(f"  flight_logs:       {len(flight_logs)}")
    print(f"  rest_declarations: {len(rest_decls)}")
    print(f"Created workspace at {args.workspace}")
    print(f"  config files:      5 (fixed)")
    print(f"  prior_hours files: {n_prior}")
    print(f"  amendment files:   {n_amend}")


if __name__ == "__main__":
    main()
