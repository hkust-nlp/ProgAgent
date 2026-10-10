import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 24,
}

# Deterministic seeds
random.seed(42)
np.random.seed(42)

STATIONS = [
    "London Paddington", "London Euston", "London Kings Cross", "London Victoria",
    "London Waterloo", "Birmingham New Street", "Manchester Piccadilly", "Leeds",
    "Bristol Temple Meads", "Edinburgh Waverley", "Glasgow Central", "Cardiff Central",
    "Sheffield", "Liverpool Lime Street", "Newcastle", "Nottingham",
    "Reading", "Oxford", "Cambridge", "York", "Crewe", "Derby",
    "Southampton Central", "Brighton", "Exeter St Davids", "Plymouth",
    "Swindon", "Milton Keynes Central", "Coventry", "Wolverhampton",
    "Preston", "Lancaster", "Carlisle", "Peterborough", "Doncaster",
    "Darlington", "Durham", "Wakefield Westgate", "Huddersfield",
    "Stockport", "Warrington Bank Quay", "Wigan North Western",
    "Stafford", "Tamworth", "Nuneaton", "Rugby", "Banbury",
    "Didcot Parkway", "Cheltenham Spa", "Gloucester", "Worcester Shrub Hill",
    "Hereford", "Newport", "Swansea", "Bath Spa", "Taunton",
    "Salisbury", "Winchester", "Basingstoke", "Guildford",
]

OPERATORS = [
    "CrossCountry", "Avanti West Coast", "GWR", "LNER", "TransPennine",
    "Northern", "ScotRail", "SWR", "Chiltern", "East Midlands",
]

TRAIN_TYPES = ["intercity", "express", "regional", "commuter", "freight"]
PRIORITY_MAP = {"intercity": 1, "express": 2, "regional": 3, "commuter": 4, "freight": 5}

POSSESSION_TYPES = [
    "full_closure", "single_line", "speed_restriction",
    "signaling", "platform_work", "overhead_line",
]

SIGNAL_TYPES = ["ETCS_L2", "TPWS", "AWS", "RETB", "TVM430"]

REFERENCE_DATE = datetime(2026, 3, 16)  # Monday of reference week


def create_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS junctions (
        junction_id INTEGER PRIMARY KEY,
        junction_name TEXT NOT NULL,
        capacity_per_hour INTEGER NOT NULL,
        signal_type TEXT NOT NULL,
        location TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS route_sections (
        section_id INTEGER PRIMARY KEY,
        section_name TEXT NOT NULL,
        from_station TEXT NOT NULL,
        to_station TEXT NOT NULL,
        length_km REAL NOT NULL,
        speed_limit_kmh INTEGER NOT NULL,
        junction_id INTEGER,
        FOREIGN KEY (junction_id) REFERENCES junctions(junction_id)
    );
    CREATE TABLE IF NOT EXISTS trains (
        train_id INTEGER PRIMARY KEY,
        service_code TEXT NOT NULL UNIQUE,
        operator TEXT NOT NULL,
        train_type TEXT NOT NULL,
        priority_class INTEGER NOT NULL,
        max_speed_kmh INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS maintenance_possessions (
        possession_id INTEGER PRIMARY KEY,
        section_id INTEGER NOT NULL,
        start_datetime TEXT NOT NULL,
        end_datetime TEXT NOT NULL,
        possession_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT,
        FOREIGN KEY (section_id) REFERENCES route_sections(section_id)
    );
    CREATE TABLE IF NOT EXISTS punctuality_history (
        record_id INTEGER PRIMARY KEY,
        section_id INTEGER NOT NULL,
        period TEXT NOT NULL,
        avg_delay_minutes REAL NOT NULL,
        on_time_percentage REAL NOT NULL,
        incident_count INTEGER NOT NULL,
        cancellation_rate REAL NOT NULL,
        FOREIGN KEY (section_id) REFERENCES route_sections(section_id)
    );
    """)
    conn.commit()


def populate_junctions(conn):
    n = max(SCALE["rows_per_table"] // 3, 10)
    rows = []
    for i in range(n):
        letter1 = chr(65 + (i // 26) % 26)
        letter2 = chr(65 + i % 26)
        name = f"JCT-{letter1}{letter2}{10 + i}"
        cap = random.choice([2, 3, 3, 4, 5, 6, 8, 10])
        sig = random.choice(SIGNAL_TYPES)
        loc = STATIONS[i % len(STATIONS)]
        rows.append((i + 1, name, cap, sig, loc))
    conn.executemany("INSERT INTO junctions VALUES (?,?,?,?,?)", rows)
    conn.commit()
    return rows


def populate_sections(conn, junctions):
    n = SCALE["rows_per_table"]
    num_st = len(STATIONS)
    jct_ids = [j[0] for j in junctions]
    rows = []
    for i in range(n):
        s1 = random.randint(0, num_st - 1)
        s2 = random.randint(0, num_st - 2)
        if s2 >= s1:
            s2 += 1
        has_jct = random.random() < 0.5
        jid = random.choice(jct_ids) if has_jct else None
        length = round(random.uniform(8, 250), 1)
        speed = random.choice([60, 80, 100, 120, 140, 160, 200])
        rows.append((
            i + 1,
            f"SEC-{i + 1:03d}",
            STATIONS[s1],
            STATIONS[s2],
            length,
            speed,
            jid,
        ))
    conn.executemany("INSERT INTO route_sections VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def populate_trains(conn):
    n = SCALE["rows_per_table"]
    rows = []
    used = set()
    for i in range(n):
        while True:
            code = f"{random.randint(1, 9)}{chr(random.randint(65, 90))}{random.randint(10, 99):02d}"
            if code not in used:
                used.add(code)
                break
        ttype = random.choice(TRAIN_TYPES)
        pclass = PRIORITY_MAP[ttype]
        op = random.choice(OPERATORS)
        mspeed = random.choice([100, 120, 140, 160, 200, 225])
        rows.append((i + 1, code, op, ttype, pclass, mspeed))
    conn.executemany("INSERT INTO trains VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def populate_maintenance(conn, sections):
    n = SCALE["rows_per_table"]
    sec_ids = [s[0] for s in sections]
    rows = []
    for i in range(n):
        sid = random.choice(sec_ids)
        day_off = random.randint(0, 6)
        start_h = random.randint(0, 18)
        dur_h = random.randint(2, 6)
        start_dt = REFERENCE_DATE + timedelta(days=day_off, hours=start_h)
        end_dt = start_dt + timedelta(hours=dur_h)
        ptype = random.choice(POSSESSION_TYPES)
        sev = random.choice(["critical", "major", "moderate", "minor"])
        desc = f"{ptype.replace('_', ' ').title()} on SEC-{sid:03d}"
        rows.append((
            i + 1, sid,
            start_dt.strftime("%Y-%m-%d %H:%M"),
            end_dt.strftime("%Y-%m-%d %H:%M"),
            ptype, sev, desc,
        ))
    conn.executemany(
        "INSERT INTO maintenance_possessions VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def populate_punctuality(conn, sections):
    n = SCALE["rows_per_table"]
    sec_ids = [s[0] for s in sections]
    periods = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1"]
    rows = []
    for i in range(n):
        sid = sec_ids[i % len(sec_ids)]
        period = periods[i % len(periods)]
        if random.random() < 0.20:
            avg_del = round(random.uniform(8, 25), 1)
            otp = round(random.uniform(45, 74), 1)
            inc = random.randint(5, 20)
            cr = round(random.uniform(0.05, 0.15), 3)
        else:
            avg_del = round(random.uniform(1, 7), 1)
            otp = round(random.uniform(76, 98), 1)
            inc = random.randint(0, 4)
            cr = round(random.uniform(0.0, 0.04), 3)
        rows.append((i + 1, sid, period, avg_del, otp, inc, cr))
    conn.executemany(
        "INSERT INTO punctuality_history VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def _make_dep_arr(day_offset):
    """Generate a random departure/arrival within one day."""
    dep_h = random.randint(5, 21)
    dep_m = random.randint(0, 59)
    remaining = (23 * 60 + 59) - (dep_h * 60 + dep_m)
    dur = random.randint(20, min(120, max(20, remaining)))
    dep_dt = REFERENCE_DATE + timedelta(days=day_offset, hours=dep_h, minutes=dep_m)
    arr_dt = dep_dt + timedelta(minutes=dur)
    return dep_dt, arr_dt


def generate_proposals(workspace, sections, trains, maintenance, junctions):
    """Generate schedule proposal CSV files."""
    n_files = SCALE["num_workspace_files"]
    ppf = max(10, SCALE["rows_per_table"] // SCALE["num_workspace_files"])

    sec_ids = [s[0] for s in sections]
    train_codes = [t[1] for t in trains]

    # Index maintenance by section
    maint_by_sec = {}
    for m in maintenance:
        maint_by_sec.setdefault(m[1], []).append(m)
    maint_sections = list(maint_by_sec.keys())

    # Index sections by junction
    secs_by_jct = {}
    for s in sections:
        if s[6] is not None:
            secs_by_jct.setdefault(s[6], []).append(s[0])

    # Low-capacity junctions (cap <= 3)
    low_cap_jcts = [j for j in junctions if j[2] <= 3 and j[0] in secs_by_jct]

    # Identify sections with potential poor punctuality
    # (we generated ~20% poor records; collect those section ids)
    # Not needed here — random placement will naturally hit some.

    total = n_files * ppf
    proposals = []

    # --- Batch 1: maintenance conflicts (~18%) ---
    n_maint = max(8, total // 5)
    for _ in range(n_maint):
        sid = random.choice(maint_sections)
        mb = random.choice(maint_by_sec[sid])
        m_start = datetime.strptime(mb[2], "%Y-%m-%d %H:%M")
        m_end = datetime.strptime(mb[3], "%Y-%m-%d %H:%M")
        span_sec = max(1, int((m_end - m_start).total_seconds()))
        off_sec = random.randint(0, span_sec - 1)
        dep_dt = m_start + timedelta(seconds=off_sec)
        dur = random.randint(20, 90)
        arr_dt = dep_dt + timedelta(minutes=dur)
        tc = random.choice(train_codes)
        proposals.append([None, tc, sid,
                          dep_dt.strftime("%Y-%m-%d"),
                          dep_dt.strftime("%H:%M"),
                          arr_dt.strftime("%H:%M")])

    # --- Batch 2: junction overload clusters ---
    for jct in low_cap_jcts[:3]:
        jid, _, cap = jct[0], jct[1], jct[2]
        day_off = random.randint(0, 6)
        hour = random.randint(7, 18)
        need = cap + 2  # exceed capacity
        for _ in range(need):
            sid = random.choice(secs_by_jct[jid])
            dep_m = random.randint(0, 40)
            dep_dt = REFERENCE_DATE + timedelta(days=day_off, hours=hour, minutes=dep_m)
            arr_dt = dep_dt + timedelta(minutes=random.randint(15, 45))
            tc = random.choice(train_codes)
            proposals.append([None, tc, sid,
                              dep_dt.strftime("%Y-%m-%d"),
                              dep_dt.strftime("%H:%M"),
                              arr_dt.strftime("%H:%M")])

    # --- Batch 3: fill remaining with random ---
    remaining = total - len(proposals)
    for _ in range(max(0, remaining)):
        sid = random.choice(sec_ids)
        dep_dt, arr_dt = _make_dep_arr(random.randint(0, 6))
        tc = random.choice(train_codes)
        proposals.append([None, tc, sid,
                          dep_dt.strftime("%Y-%m-%d"),
                          dep_dt.strftime("%H:%M"),
                          arr_dt.strftime("%H:%M")])

    # Shuffle and assign IDs
    random.shuffle(proposals)
    for idx, p in enumerate(proposals):
        p[0] = f"P{idx + 1:04d}"

    # Split into files
    for fi in range(n_files):
        start = fi * ppf
        end = min(start + ppf, len(proposals))
        chunk = proposals[start:end]
        fname = f"schedule_batch_{fi + 1:02d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "proposal_id", "train_service_code", "section_id",
                "date", "departure_time", "arrival_time",
            ])
            w.writerows(chunk)

    # Write any leftover proposals into the last file (when total > n_files*ppf)
    if len(proposals) > n_files * ppf:
        leftover = proposals[n_files * ppf:]
        fname = f"schedule_batch_{n_files:02d}.csv"
        with open(os.path.join(workspace, fname), "a", newline="") as f:
            w = csv.writer(f)
            w.writerows(leftover)

    return proposals


def generate_config_files(workspace):
    """Generate fixed configuration/policy files."""

    # --- conflict_rules.yaml ---
    yaml_content = (
        "maintenance_buffer_minutes: 30\n"
        "junction_capacity_threshold_ratio: 1.0\n"
        "\n"
        "conflict_severity:\n"
        '  maintenance_overlap: "critical"\n'
        '  maintenance_buffer: "major"\n'
        '  junction_overload: "major"\n'
        '  punctuality_risk: "moderate"\n'
        "\n"
        "priority_score_tie_breaker: \"proposal_id\"\n"
    )
    with open(os.path.join(workspace, "conflict_rules.yaml"), "w") as f:
        f.write(yaml_content)

    # --- priority_matrix.json ---
    matrix = {
        "severity_weights": {
            "critical": 4,
            "major": 3,
            "moderate": 2,
            "minor": 1,
        },
        "base_multiplier": 10,
        "train_priority_weight": 2.0,
        "punctuality_risk_weight": 1.5,
        "formula": (
            "severity_weight * base_multiplier + "
            "train_priority_class * train_priority_weight + "
            "section_avg_delay * punctuality_risk_weight"
        ),
    }
    with open(os.path.join(workspace, "priority_matrix.json"), "w") as f:
        json.dump(matrix, f, indent=2)

    # --- risk_thresholds.txt ---
    txt = (
        "# Punctuality Risk Level Thresholds\n"
        "# Each section's average on-time percentage across all periods\n"
        "# determines its risk level. Only high-risk sections are flagged.\n"
        "#\n"
        "# LEVEL | MAX_ON_TIME_PCT | FLAG_AS_CONFLICT\n"
        "high | 75.0 | yes\n"
        "medium | 85.0 | no\n"
        "low | 100.0 | no\n"
    )
    with open(os.path.join(workspace, "risk_thresholds.txt"), "w") as f:
        f.write(txt)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    junctions = populate_junctions(conn)
    sections = populate_sections(conn, junctions)
    trains = populate_trains(conn)
    maintenance = populate_maintenance(conn, sections)
    punctuality = populate_punctuality(conn, sections)

    generate_proposals(args.workspace, sections, trains, maintenance, junctions)
    generate_config_files(args.workspace)

    conn.close()
    print(f"Database written to {args.db_path}")
    print(f"Workspace populated at {args.workspace}")


if __name__ == "__main__":
    main()
