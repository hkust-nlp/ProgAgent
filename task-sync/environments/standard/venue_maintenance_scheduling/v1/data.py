import argparse
import sqlite3
import os
import json
import random
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 16,
}

REFERENCE_DATE = datetime(2026, 5, 1)
PLANNING_DAYS = 30

DISTRICTS = [
    "North", "South", "East", "West", "Central", "Riverside",
    "Hillside", "Lakefront", "Downtown", "Suburban", "Industrial", "Parkland",
]

SURFACE_TYPES = ["natural_grass", "hybrid_grass", "artificial_turf"]
CATEGORIES = ["A", "B", "C"]
MATCH_TYPES = ["league", "cup", "friendly", "training"]
EVENT_TYPES = ["concert", "corporate", "festival", "community"]
STAFF_ROLES = ["head_groundskeeper", "senior_technician", "technician", "assistant"]
ALL_CERTIFICATIONS = [
    "advanced_turf_management",
    "turf_maintenance",
    "irrigation_systems",
    "pest_control",
    "equipment_operation",
    "safety_compliance",
]

VENUE_SUFFIXES = ["Stadium", "Arena", "Ground", "Park", "Pitch", "Field", "Centre"]
TEAM_POOL = [
    "United", "City", "Rovers", "Athletic", "Wanderers", "Rangers",
    "Albion", "Town", "Hotspur", "Villa", "Palace", "Forest",
    "Dynamo", "Olympique", "Sporting", "Real", "Inter", "Corinthians",
]


def create_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS venues (
            venue_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            district TEXT NOT NULL,
            surface_type TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            category TEXT NOT NULL,
            year_built INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fixtures (
            fixture_id INTEGER PRIMARY KEY,
            venue_id INTEGER NOT NULL,
            fixture_date TEXT NOT NULL,
            match_type TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            kick_off_time TEXT NOT NULL,
            FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
        );
        CREATE TABLE IF NOT EXISTS pitch_wear_records (
            record_id INTEGER PRIMARY KEY,
            venue_id INTEGER NOT NULL,
            inspection_date TEXT NOT NULL,
            wear_index REAL NOT NULL,
            moisture_level REAL NOT NULL,
            compaction_score REAL NOT NULL,
            grass_height_mm REAL NOT NULL,
            notes TEXT,
            FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
        );
        CREATE TABLE IF NOT EXISTS third_party_events (
            event_id INTEGER PRIMARY KEY,
            venue_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            event_type TEXT NOT NULL,
            organizer TEXT NOT NULL,
            expected_attendance INTEGER NOT NULL,
            setup_days INTEGER NOT NULL,
            teardown_days INTEGER NOT NULL,
            contract_status TEXT NOT NULL,
            FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
        );
        CREATE TABLE IF NOT EXISTS ground_staff (
            staff_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            skill_level INTEGER NOT NULL,
            hourly_rate REAL NOT NULL,
            max_weekly_hours INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staff_shifts (
            shift_id INTEGER PRIMARY KEY,
            staff_id INTEGER NOT NULL,
            shift_date TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (staff_id) REFERENCES ground_staff(staff_id)
        );
    """)


def generate_venues(cursor, fake, n_rows, districts_used):
    venues = []
    used_names = set()
    for i in range(1, n_rows + 1):
        while True:
            city = fake.city()
            suffix = random.choice(VENUE_SUFFIXES)
            name = f"{city} {suffix}"
            if name not in used_names:
                used_names.add(name)
                break
        district = districts_used[i % len(districts_used)]
        # ~25% artificial_turf, 45% natural_grass, 30% hybrid_grass
        r = random.random()
        if r < 0.25:
            surface = "artificial_turf"
        elif r < 0.70:
            surface = "natural_grass"
        else:
            surface = "hybrid_grass"
        capacity = random.randint(2000, 60000)
        # 25% A, 45% B, 30% C
        cr = random.random()
        if cr < 0.25:
            cat = "A"
        elif cr < 0.70:
            cat = "B"
        else:
            cat = "C"
        year_built = random.randint(1960, 2024)
        venues.append((i, name, district, surface, capacity, cat, year_built))
    cursor.executemany(
        "INSERT INTO venues VALUES (?,?,?,?,?,?,?)", venues
    )
    return venues


def generate_fixtures(cursor, fake, n_rows, venues):
    fixtures = []
    fid = 1
    venue_ids = [v[0] for v in venues]
    # Distribute fixtures: each venue gets 0-3 fixtures, ensure total >= n_rows
    assignments = []
    for vid in venue_ids:
        count = random.choices([0, 1, 2, 3], weights=[15, 40, 30, 15])[0]
        assignments.append((vid, count))
    total = sum(c for _, c in assignments)
    while total < n_rows:
        idx = random.randint(0, len(assignments) - 1)
        vid, c = assignments[idx]
        if c < 4:
            assignments[idx] = (vid, c + 1)
            total += 1

    teams = []
    for prefix in TEAM_POOL:
        teams.append(f"{fake.city()} {prefix}")
    if len(teams) < 30:
        for _ in range(30 - len(teams)):
            teams.append(f"{fake.city()} {random.choice(TEAM_POOL)}")

    for vid, count in assignments:
        used_dates = set()
        for _ in range(count):
            for _attempt in range(50):
                day_offset = random.randint(0, PLANNING_DAYS - 1)
                fdate = (REFERENCE_DATE + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                if fdate not in used_dates:
                    used_dates.add(fdate)
                    break
            mtype = random.choice(MATCH_TYPES)
            home = random.choice(teams)
            away = random.choice([t for t in teams if t != home])
            hour = random.choice(["10:00", "14:00", "15:00", "17:30", "19:45", "20:00"])
            fixtures.append((fid, vid, fdate, mtype, home, away, hour))
            fid += 1
    cursor.executemany(
        "INSERT INTO fixtures VALUES (?,?,?,?,?,?,?)", fixtures
    )
    return fixtures


def generate_wear_records(cursor, fake, n_rows, venues):
    records = []
    rid = 1
    venue_ids = [v[0] for v in venues]
    surface_map = {v[0]: v[3] for v in venues}
    # Each venue gets 1-3 inspection records in the past 60 days
    assignments = []
    for vid in venue_ids:
        count = random.choices([1, 2, 3], weights=[30, 50, 20])[0]
        assignments.append((vid, count))
    total = sum(c for _, c in assignments)
    while total < n_rows:
        idx = random.randint(0, len(assignments) - 1)
        vid, c = assignments[idx]
        assignments[idx] = (vid, c + 1)
        total += 1

    for vid, count in assignments:
        dates_used = set()
        for j in range(count):
            for _attempt in range(50):
                day_offset = random.randint(1, 60)
                idate = (REFERENCE_DATE - timedelta(days=day_offset)).strftime("%Y-%m-%d")
                if idate not in dates_used:
                    dates_used.add(idate)
                    break
            surf = surface_map[vid]
            if surf == "artificial_turf":
                wear = round(random.uniform(5, 35), 1)
            else:
                # Distribution: ~20% low (10-29), ~25% light (30-49),
                # ~25% medium (50-74), ~30% high (75-95)
                wr = random.random()
                if wr < 0.20:
                    wear = round(random.uniform(10, 29), 1)
                elif wr < 0.45:
                    wear = round(random.uniform(30, 49), 1)
                elif wr < 0.70:
                    wear = round(random.uniform(50, 74), 1)
                else:
                    wear = round(random.uniform(75, 95), 1)
            moisture = round(random.uniform(20, 90), 1)
            compaction = round(random.uniform(15, 85), 1)
            grass_h = round(random.uniform(15, 45), 1) if surf != "artificial_turf" else 0.0
            notes_pool = [
                "Routine inspection completed.",
                "Some wear observed near goal areas.",
                "Center circle shows heavy use.",
                "Overall condition satisfactory.",
                "Drainage issues noted after recent rain.",
                "Recovery progressing well after last event.",
                "Touch-line areas need attention.",
                "Pitch in excellent condition.",
                "Minor divots observed in penalty area.",
                "Surface compaction higher than expected.",
            ]
            note = random.choice(notes_pool)
            records.append((rid, vid, idate, wear, moisture, compaction, grass_h, note))
            rid += 1
    cursor.executemany(
        "INSERT INTO pitch_wear_records VALUES (?,?,?,?,?,?,?,?)", records
    )
    return records


def generate_events(cursor, fake, n_rows, venues):
    events = []
    eid = 1
    venue_ids = [v[0] for v in venues]
    assignments = []
    for vid in venue_ids:
        count = random.choices([0, 1, 2], weights=[30, 50, 20])[0]
        assignments.append((vid, count))
    total = sum(c for _, c in assignments)
    while total < n_rows:
        idx = random.randint(0, len(assignments) - 1)
        vid, c = assignments[idx]
        assignments[idx] = (vid, c + 1)
        total += 1

    organizers = [fake.company() for _ in range(20)]
    for vid, count in assignments:
        used_dates = set()
        for _ in range(count):
            for _attempt in range(50):
                day_offset = random.randint(0, PLANNING_DAYS - 1)
                edate = (REFERENCE_DATE + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                if edate not in used_dates:
                    used_dates.add(edate)
                    break
            etype = random.choice(EVENT_TYPES)
            org = random.choice(organizers)
            attendance = random.randint(500, 40000)
            setup = random.randint(1, 3)
            teardown = random.randint(1, 2)
            status = random.choices(["confirmed", "tentative"], weights=[70, 30])[0]
            events.append((eid, vid, edate, etype, org, attendance, setup, teardown, status))
            eid += 1
    cursor.executemany(
        "INSERT INTO third_party_events VALUES (?,?,?,?,?,?,?,?,?)", events
    )
    return events


def generate_staff(cursor, fake, n_rows):
    staff = []
    for i in range(1, n_rows + 1):
        name = fake.name()
        # Role distribution: 10% head, 25% senior, 40% tech, 25% assistant
        rr = random.random()
        if rr < 0.10:
            role = "head_groundskeeper"
            skill = random.randint(4, 5)
        elif rr < 0.35:
            role = "senior_technician"
            skill = random.randint(3, 5)
        elif rr < 0.75:
            role = "technician"
            skill = random.randint(2, 4)
        else:
            role = "assistant"
            skill = random.randint(1, 3)
        hourly = round(15.0 + skill * 5.0 + random.uniform(-2, 2), 2)
        max_hrs = random.choice([30, 35, 40, 40, 45])
        staff.append((i, name, role, skill, hourly, max_hrs))
    cursor.executemany(
        "INSERT INTO ground_staff VALUES (?,?,?,?,?,?)", staff
    )
    return staff


def generate_shifts(cursor, n_rows, staff):
    shifts = []
    sid = 1
    staff_ids = [s[0] for s in staff]
    for staff_id in staff_ids:
        for day_offset in range(PLANNING_DAYS):
            # ~65% chance of having a shift on any day
            if random.random() < 0.65:
                shift_type = random.choice(["morning", "afternoon"])
                # 70% available, 15% scheduled (busy), 15% off
                sr = random.random()
                if sr < 0.70:
                    status = "available"
                elif sr < 0.85:
                    status = "scheduled"
                else:
                    status = "off"
                sdate = (REFERENCE_DATE + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                shifts.append((sid, staff_id, sdate, shift_type, status))
                sid += 1
    cursor.executemany(
        "INSERT INTO staff_shifts VALUES (?,?,?,?,?)", shifts
    )
    return shifts


def generate_policy_files(workspace):
    import yaml

    # maintenance_policy.yaml
    policy = {
        "maintenance_types": {
            "deep_restoration": {
                "min_wear_index": 75,
                "hours_required": 8,
                "min_skill_level": 4,
                "required_certification": "advanced_turf_management",
            },
            "surface_treatment": {
                "min_wear_index": 50,
                "hours_required": 4,
                "min_skill_level": 3,
                "required_certification": "turf_maintenance",
            },
            "light_maintenance": {
                "min_wear_index": 30,
                "hours_required": 2,
                "min_skill_level": 2,
                "required_certification": None,
            },
        },
        "excluded_surface_types": ["artificial_turf"],
        "category_multipliers": {"A": 1.5, "B": 1.0, "C": 0.8},
        "weather_constraints": {"max_precipitation_mm": 5.0},
        "urgency_factors": {
            "days_0_to_3": 2.0,
            "days_4_to_7": 1.5,
            "days_8_to_14": 1.2,
            "days_15_plus": 1.0,
        },
        "recent_maintenance_adjustment": {
            "lookback_days": 14,
            "wear_reduction": 15,
        },
        "scheduling_rules": {
            "planning_start": "2026-05-01",
            "planning_end": "2026-05-30",
            "max_maintenance_per_venue_per_day": 1,
        },
    }
    with open(os.path.join(workspace, "maintenance_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # priority_rules.json
    rules = {
        "priority_formula": "adjusted_wear_index * category_multiplier * urgency_factor",
        "rounding": 2,
        "scheduling_order": "priority_score descending",
        "tie_breaker": "venue_id ascending",
    }
    with open(os.path.join(workspace, "priority_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)

    # staff_assignment_guidelines.md
    guidelines = """Staff Assignment Guidelines

When assigning ground staff to maintenance tasks, the following rules apply in order.

Each maintenance type specifies a minimum skill level and, for some types, a required
certification. A staff member is eligible for a task only if their skill level meets or
exceeds the minimum and, when a certification is required, they hold that certification
as recorded in the staff certification files.

Among all eligible and available staff for a given task date, assign the staff member
with the numerically lowest staff_id. A staff member may be assigned to at most one
maintenance task on any single calendar day. If a staff member has already been assigned
to a task on a given date, they are unavailable for further assignments that day.

Shift availability is determined by whether the staff member has a shift record with
status "available" on the task date. Staff with status "scheduled" or "off", or with
no shift record for that date, are not available.

Only confirmed third-party events block venue dates. Tentative events should be ignored
when determining scheduling conflicts. For each confirmed event, the blocked window runs
from (event_date minus setup_days) through (event_date plus teardown_days), inclusive.
"""
    with open(os.path.join(workspace, "staff_assignment_guidelines.md"), "w") as f:
        f.write(guidelines)


def generate_weather_files(workspace, n_files, districts_used):
    n_weather = max(3, n_files * 3 // 8)
    # Distribute PLANNING_DAYS across n_weather files, capping at PLANNING_DAYS
    n_weather = min(n_weather, PLANNING_DAYS)
    days_per_file = math.ceil(PLANNING_DAYS / n_weather)
    for fi in range(n_weather):
        start_day = fi * days_per_file
        end_day = min(start_day + days_per_file, PLANNING_DAYS)
        if start_day >= PLANNING_DAYS:
            break
        rows = []
        for d in range(start_day, end_day):
            date_str = (REFERENCE_DATE + timedelta(days=d)).strftime("%Y-%m-%d")
            for district in districts_used:
                temp_high = round(random.uniform(12, 30), 1)
                temp_low = round(temp_high - random.uniform(5, 12), 1)
                # ~25% chance of significant precipitation
                if random.random() < 0.25:
                    precip = round(random.uniform(5.1, 25.0), 1)
                else:
                    precip = round(random.uniform(0, 4.9), 1)
                wind = round(random.uniform(3, 35), 1)
                if precip > 10:
                    cond = "heavy_rain"
                elif precip > 5:
                    cond = "rain"
                elif precip > 2:
                    cond = "light_rain"
                elif random.random() < 0.5:
                    cond = "sunny"
                else:
                    cond = "partly_cloudy"
                rows.append({
                    "date": date_str,
                    "district": district,
                    "temp_high": temp_high,
                    "temp_low": temp_low,
                    "precipitation_mm": precip,
                    "wind_speed_kmh": wind,
                    "condition": cond,
                })
        df = pd.DataFrame(rows)
        df.to_csv(
            os.path.join(workspace, f"weather_forecast_{fi + 1}.csv"),
            index=False,
        )


def generate_cert_files(workspace, n_files, staff):
    n_cert = max(3, n_files * 3 // 8)
    staff_ids = [s[0] for s in staff]
    skill_map = {s[0]: s[3] for s in staff}
    batch_size = math.ceil(len(staff_ids) / n_cert)
    for fi in range(n_cert):
        batch_start = fi * batch_size
        batch_end = min(batch_start + batch_size, len(staff_ids))
        batch = staff_ids[batch_start:batch_end]
        entries = []
        for sid in batch:
            skill = skill_map[sid]
            certs = []
            if skill >= 4:
                certs.append("advanced_turf_management")
            if skill >= 3:
                certs.append("turf_maintenance")
            extras = [c for c in ALL_CERTIFICATIONS if c not in certs]
            n_extra = min(random.randint(0, 2), len(extras))
            certs.extend(random.sample(extras, n_extra))
            entries.append({"staff_id": sid, "certifications": sorted(certs)})
        with open(os.path.join(workspace, f"staff_certifications_{fi + 1}.json"), "w") as f:
            json.dump(entries, f, indent=2)


def generate_maintenance_logs(workspace, n_files, venues):
    n_weather = max(3, n_files * 3 // 8)
    n_cert = max(3, n_files * 3 // 8)
    n_logs = max(2, n_files - n_weather - n_cert)
    venue_ids = [v[0] for v in venues]
    # ~25% of venues have a recent maintenance record (within 14 days before reference)
    maintained_venues = random.sample(
        venue_ids, max(1, len(venue_ids) // 4)
    )
    entries = []
    for vid in maintained_venues:
        days_ago = random.randint(1, 14)
        mdate = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        mtype = random.choice(["surface_treatment", "light_maintenance", "deep_restoration"])
        hours = {"deep_restoration": 8.0, "surface_treatment": 4.0, "light_maintenance": 2.0}[mtype]
        staff_id = random.randint(1, len(venues))
        entries.append({
            "venue_id": vid,
            "maintenance_date": mdate,
            "type": mtype,
            "duration_hours": hours,
            "staff_id": staff_id,
        })
    # Also add some older entries (>14 days ago) as noise
    for _ in range(len(entries)):
        vid = random.choice(venue_ids)
        days_ago = random.randint(15, 45)
        mdate = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        mtype = random.choice(["surface_treatment", "light_maintenance", "deep_restoration"])
        hours = {"deep_restoration": 8.0, "surface_treatment": 4.0, "light_maintenance": 2.0}[mtype]
        staff_id = random.randint(1, len(venues))
        entries.append({
            "venue_id": vid,
            "maintenance_date": mdate,
            "type": mtype,
            "duration_hours": hours,
            "staff_id": staff_id,
        })

    random.shuffle(entries)
    batch_size = math.ceil(len(entries) / n_logs)
    for fi in range(n_logs):
        batch_start = fi * batch_size
        batch_end = min(batch_start + batch_size, len(entries))
        batch = entries[batch_start:batch_end]
        lines = []
        for e in batch:
            lines.append("=== Maintenance Record ===")
            lines.append(f"Venue ID: {e['venue_id']}")
            lines.append(f"Date: {e['maintenance_date']}")
            lines.append(f"Type: {e['type']}")
            lines.append(f"Duration: {e['duration_hours']} hours")
            lines.append(f"Staff ID: {e['staff_id']}")
            lines.append("==========================")
            lines.append("")
        with open(os.path.join(workspace, f"maintenance_log_{fi + 1}.txt"), "w") as f:
            f.write("\n".join(lines))


def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    num_districts = min(len(DISTRICTS), max(6, n_rows // 7))
    districts_used = DISTRICTS[:num_districts]

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    create_tables(cursor)

    venues = generate_venues(cursor, fake, n_rows, districts_used)
    fixtures = generate_fixtures(cursor, fake, n_rows, venues)
    wear_records = generate_wear_records(cursor, fake, n_rows, venues)
    events = generate_events(cursor, fake, n_rows, venues)
    staff = generate_staff(cursor, fake, n_rows)
    shifts = generate_shifts(cursor, n_rows, staff)

    conn.commit()

    generate_policy_files(workspace)
    generate_weather_files(workspace, n_files, districts_used)
    generate_cert_files(workspace, n_files, staff)
    generate_maintenance_logs(workspace, n_files, venues)

    conn.close()
    print(f"Database created at {db_path}")
    print(f"Workspace populated at {workspace}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
