#!/usr/bin/env python3
"""Data generation for volunteer shift scheduling task."""

import os
import json
import csv
import sqlite3
import argparse
import random
import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 60,
    "num_workspace_files": 20,
}

# ── Constants ──────────────────────────────────────────────────────────────

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

CERTIFICATIONS = [
    "first_aid", "crowd_management", "food_safety",
    "child_care", "av_technology", "logistics", "registration_systems",
]

ROLES = [
    "coordinator", "setup_crew", "food_server", "registration",
    "childcare", "tech_support", "medical_support", "crowd_control",
]

# (required_certifications, min_experience_years)
ROLE_CERT_MAP = {
    "coordinator":      (["logistics"], 2),
    "setup_crew":       (["logistics"], 0),
    "food_server":      (["food_safety"], 0),
    "registration":     (["registration_systems"], 0),
    "childcare":        (["child_care"], 1),
    "tech_support":     (["av_technology"], 1),
    "medical_support":  (["first_aid"], 2),
    "crowd_control":    (["crowd_management"], 1),
}

EVENT_POOL = [
    ("Community Cleanup", True),
    ("Food Drive", False),
    ("Youth Summer Camp", True),
    ("Senior Social Gathering", False),
    ("Charity Fun Run", True),
    ("Blood Donation Drive", False),
    ("Neighborhood Watch Meetup", False),
    ("Park Restoration Day", True),
    ("Holiday Street Festival", True),
    ("Tech Skills Workshop", False),
    ("Art in the Park Fair", True),
    ("Book Collection Drive", False),
    ("Free Health Screening", False),
    ("Community Sports Day", True),
    ("Outdoor Music Concert", True),
    ("Coding Bootcamp", False),
    ("Community Garden Planting", True),
    ("Winter Clothing Drive", False),
    ("Pet Adoption Fair", True),
    ("Adult Literacy Program", False),
    ("River Cleanup Initiative", True),
    ("Farmers Market Setup", True),
    ("Cultural Heritage Festival", True),
    ("Youth Mentoring Session", False),
    ("Emergency Prep Drill", True),
    ("Recycling Awareness Day", True),
    ("Community Mural Painting", True),
    ("Senior Fitness Class", False),
    ("Back to School Drive", False),
    ("Thanksgiving Meal Prep", False),
    ("New Year Celebration", True),
    ("Spring Flower Festival", True),
    ("Beach Cleanup Day", True),
    ("Science Fair", False),
    ("Community Theater Show", False),
    ("Voter Registration Drive", False),
    ("Habitat Build Day", True),
    ("Winter Warmth Drive", False),
    ("Summer Reading Program", False),
    ("Dance Workshop", False),
]

LOCATIONS_OUTDOOR = [
    "Central Park Pavilion", "Riverside Park", "Downtown Plaza",
    "Lakeside Amphitheater", "Community Garden", "Sports Field",
    "Beach Front Area", "Town Square",
]

LOCATIONS_INDOOR = [
    "Community Center Hall A", "Community Center Hall B", "City Library",
    "Sports Complex Gym", "Church Basement", "School Gymnasium",
    "Town Hall Annex", "Fire Station Meeting Room",
]

TIME_WINDOWS = [
    ("08:00", "12:00"), ("09:00", "13:00"), ("10:00", "14:00"),
    ("12:00", "16:00"), ("13:00", "17:00"), ("14:00", "18:00"),
    ("15:00", "19:00"), ("16:00", "20:00"), ("17:00", "21:00"),
]

WEATHER_TEMPLATE = {
    "Monday":    {"condition": "Sunny",         "rain_probability": 0.10, "temperature_high_c": 28, "wind_speed_kmh": 12},
    "Tuesday":   {"condition": "Partly Cloudy", "rain_probability": 0.25, "temperature_high_c": 26, "wind_speed_kmh": 15},
    "Wednesday": {"condition": "Rainy",         "rain_probability": 0.75, "temperature_high_c": 20, "wind_speed_kmh": 25},
    "Thursday":  {"condition": "Thunderstorm",  "rain_probability": 0.85, "temperature_high_c": 18, "wind_speed_kmh": 35},
    "Friday":    {"condition": "Cloudy",        "rain_probability": 0.40, "temperature_high_c": 22, "wind_speed_kmh": 18},
    "Saturday":  {"condition": "Sunny",         "rain_probability": 0.05, "temperature_high_c": 30, "wind_speed_kmh":  8},
    "Sunday":    {"condition": "Partly Cloudy", "rain_probability": 0.55, "temperature_high_c": 24, "wind_speed_kmh": 20},
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _fake_event_description(name, location):
    templates = [
        f"Weekly {name.lower()} hosted at {location}. All participants welcome.",
        f"Join us for the {name} at {location}. Volunteers play a critical role.",
        f"The {name} will take place at {location} this week.",
        f"Volunteer-driven {name.lower()} event, coordinated at {location}.",
    ]
    return random.choice(templates)


# ── Generators ─────────────────────────────────────────────────────────────

def generate_volunteers(fake, num):
    """Generate volunteer records with guaranteed cert coverage."""
    volunteers = []
    min_per_cert = max(4, num // 5)
    vol_certs = {i: set() for i in range(1, num + 1)}

    ids = list(range(1, num + 1))
    for cert in CERTIFICATIONS:
        chosen = random.sample(ids, min(min_per_cert, num))
        for vid in chosen:
            vol_certs[vid].add(cert)

    for vid in range(1, num + 1):
        while len(vol_certs[vid]) < 2:
            vol_certs[vid].add(random.choice(CERTIFICATIONS))
        if random.random() < 0.5 and len(vol_certs[vid]) < 4:
            vol_certs[vid].add(random.choice(CERTIFICATIONS))

    for i in range(1, num + 1):
        volunteers.append({
            "id": i,
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "certifications": ",".join(sorted(vol_certs[i])),
            "max_shifts_per_week": random.choice([3, 3, 4, 4, 5, 5, 6]),
            "experience_years": random.choice([0, 1, 1, 2, 2, 3, 3, 4, 5, 6, 7, 8]),
        })
    return volunteers


def generate_events(num):
    """Generate events from pool with wrap-around for large num."""
    events = []
    for i in range(num):
        idx = i % len(EVENT_POOL)
        base_name, is_outdoor = EVENT_POOL[idx]
        name = base_name if i < len(EVENT_POOL) else f"{base_name} #{i // len(EVENT_POOL) + 1}"
        location = random.choice(LOCATIONS_OUTDOOR if is_outdoor else LOCATIONS_INDOOR)
        additional_cert = random.choice(["first_aid", "crowd_management", None, None, None, None, None])
        events.append({
            "id": i + 1,
            "name": name,
            "is_outdoor": is_outdoor,
            "location": location,
            "additional_certification": additional_cert,
            "description": _fake_event_description(name, location),
        })
    return events


def generate_shifts(events, min_shifts):
    """Generate shifts spread across days and roles, >= min_shifts total."""
    shifts = []
    shift_id = 1
    for event in events:
        num_s = random.choice([3, 3, 4, 4, 5])
        days_sample = random.sample(DAYS, min(num_s, 7))
        for day in days_sample[:num_s]:
            role = random.choice(ROLES)
            tw = random.choice(TIME_WINDOWS)
            shifts.append({
                "id": shift_id,
                "event_id": event["id"],
                "event_name": event["name"],
                "day_of_week": day,
                "start_time": tw[0],
                "end_time": tw[1],
                "role": role,
                "location": event["location"],
                "is_outdoor": event["is_outdoor"],
            })
            shift_id += 1

    while len(shifts) < min_shifts:
        event = random.choice(events)
        shifts.append({
            "id": shift_id,
            "event_id": event["id"],
            "event_name": event["name"],
            "day_of_week": random.choice(DAYS),
            "start_time": random.choice(TIME_WINDOWS)[0],
            "end_time": random.choice(TIME_WINDOWS)[1],
            "role": random.choice(ROLES),
            "location": event["location"],
            "is_outdoor": event["is_outdoor"],
        })
        shift_id += 1

    return shifts


def generate_availability(volunteers):
    """Each volunteer available 3-5 days with broad windows."""
    records = []
    rid = 1
    for vol in volunteers:
        num_days = random.choice([3, 4, 4, 5, 5])
        days_avail = random.sample(DAYS, num_days)
        for day in days_avail:
            patterns = [
                [("08:00", "21:00")],
                [("08:00", "17:00")],
                [("09:00", "18:00")],
                [("10:00", "20:00")],
                [("12:00", "21:00")],
                [("08:00", "14:00"), ("16:00", "21:00")],
            ]
            windows = random.choice(patterns)
            for fr, to in windows:
                records.append({
                    "id": rid,
                    "volunteer_id": vol["id"],
                    "day_of_week": day,
                    "available_from": fr,
                    "available_until": to,
                })
                rid += 1
    return records


def generate_attendance_history(volunteers, min_records):
    """Generate attendance records with intentionally varied no-show rates."""
    records = []
    rid = 1
    vol_tendency = {}
    for vol in volunteers:
        vol_tendency[vol["id"]] = random.choice(
            [0.0, 0.0, 0.0, 0.05, 0.05, 0.10, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
        )

    for vol in volunteers:
        n = random.randint(5, 15)
        p_no_show = vol_tendency[vol["id"]]
        for _ in range(n):
            status = "no_show" if random.random() < p_no_show else "attended"
            records.append({
                "id": rid,
                "volunteer_id": vol["id"],
                "shift_date": f"2026-{random.randint(1,3):02d}-{random.randint(1,28):02d}",
                "status": status,
            })
            rid += 1

    while len(records) < min_records:
        vol = random.choice(volunteers)
        status = "no_show" if random.random() < vol_tendency[vol["id"]] else "attended"
        records.append({
            "id": rid,
            "volunteer_id": vol["id"],
            "shift_date": f"2026-{random.randint(1,3):02d}-{random.randint(1,28):02d}",
            "status": status,
        })
        rid += 1

    return records


def ensure_solvability(volunteers, shifts, availability, events, attendance):
    """Patch certs/availability/attendance so every shift has >= 5 eligible volunteers
    with at least 3 having no_show_rate <= 0.30."""
    event_map = {e["id"]: e for e in events}
    avail_id = max(a["id"] for a in availability) + 1
    att_id = max(a["id"] for a in attendance) + 1

    avail_lookup = {}
    for a in availability:
        avail_lookup.setdefault(a["volunteer_id"], []).append(a)

    # Build no-show rate lookup
    def _compute_rates(att_list):
        counts = {}
        for r in att_list:
            vid = r["volunteer_id"]
            counts.setdefault(vid, {"total": 0, "no_show": 0})
            counts[vid]["total"] += 1
            if r["status"] == "no_show":
                counts[vid]["no_show"] += 1
        rates = {}
        for vid, c in counts.items():
            rates[vid] = c["no_show"] / c["total"] if c["total"] > 0 else 0.0
        return rates

    no_show_rates = _compute_rates(attendance)

    for shift in shifts:
        role = shift["role"]
        req_certs_list, min_exp = ROLE_CERT_MAP[role]
        event = event_map[shift["event_id"]]
        extra_cert = event.get("additional_certification")
        all_req = set(req_certs_list)
        if extra_cert:
            all_req.add(extra_cert)

        eligible_ids = set()
        eligible_low_noshow = set()
        for vol in volunteers:
            v_certs = set(vol["certifications"].split(","))
            if not all_req.issubset(v_certs):
                continue
            if vol["experience_years"] < min_exp:
                continue
            for a in avail_lookup.get(vol["id"], []):
                if a["day_of_week"] != shift["day_of_week"]:
                    continue
                if (_time_to_minutes(a["available_from"]) <= _time_to_minutes(shift["start_time"])
                        and _time_to_minutes(a["available_until"]) >= _time_to_minutes(shift["end_time"])):
                    eligible_ids.add(vol["id"])
                    if no_show_rates.get(vol["id"], 0.0) <= 0.30:
                        eligible_low_noshow.add(vol["id"])
                    break

        # Need at least 5 eligible, 3 with low no-show rate
        deficit = max(0, 5 - len(eligible_ids))
        if deficit > 0:
            candidates = [v for v in volunteers if v["id"] not in eligible_ids]
            random.shuffle(candidates)
            for vol in candidates[:deficit]:
                v_certs = set(vol["certifications"].split(","))
                v_certs.update(all_req)
                vol["certifications"] = ",".join(sorted(v_certs))
                if vol["experience_years"] < min_exp:
                    vol["experience_years"] = min_exp
                already_has_day = any(
                    a["day_of_week"] == shift["day_of_week"]
                    and _time_to_minutes(a["available_from"]) <= _time_to_minutes(shift["start_time"])
                    and _time_to_minutes(a["available_until"]) >= _time_to_minutes(shift["end_time"])
                    for a in avail_lookup.get(vol["id"], [])
                )
                if not already_has_day:
                    new_rec = {
                        "id": avail_id,
                        "volunteer_id": vol["id"],
                        "day_of_week": shift["day_of_week"],
                        "available_from": "08:00",
                        "available_until": "21:00",
                    }
                    availability.append(new_rec)
                    avail_lookup.setdefault(vol["id"], []).append(new_rec)
                    avail_id += 1
                eligible_ids.add(vol["id"])
                if no_show_rates.get(vol["id"], 0.0) <= 0.30:
                    eligible_low_noshow.add(vol["id"])

        # Ensure at least 3 eligible volunteers have low no-show rate
        low_deficit = max(0, 3 - len(eligible_low_noshow))
        if low_deficit > 0:
            high_noshow_eligible = [vid for vid in eligible_ids if vid not in eligible_low_noshow]
            for vid in high_noshow_eligible[:low_deficit]:
                # Add enough "attended" records to bring rate to <= 0.25
                cur = no_show_rates.get(vid, 0.0)
                existing_total = sum(1 for r in attendance if r["volunteer_id"] == vid)
                existing_noshows = sum(1 for r in attendance if r["volunteer_id"] == vid and r["status"] == "no_show")
                # We want: existing_noshows / (existing_total + extra) <= 0.25
                # extra >= existing_noshows / 0.25 - existing_total
                if existing_noshows > 0:
                    needed_total = int(existing_noshows / 0.20) + 1
                    extra = max(0, needed_total - existing_total)
                else:
                    extra = 0
                for _ in range(extra):
                    attendance.append({
                        "id": att_id,
                        "volunteer_id": vid,
                        "shift_date": f"2026-01-{random.randint(1,28):02d}",
                        "status": "attended",
                    })
                    att_id += 1
                # Update rate cache
                no_show_rates = _compute_rates(attendance)
                if no_show_rates.get(vid, 0.0) <= 0.30:
                    eligible_low_noshow.add(vid)


# ── Database ───────────────────────────────────────────────────────────────

def create_database(db_path, volunteers, events, shifts, availability, attendance):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE volunteers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        certifications TEXT NOT NULL,
        max_shifts_per_week INTEGER NOT NULL,
        experience_years INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        is_outdoor INTEGER NOT NULL,
        location TEXT
    )""")

    c.execute("""CREATE TABLE shifts (
        id INTEGER PRIMARY KEY,
        event_id INTEGER NOT NULL,
        event_name TEXT NOT NULL,
        day_of_week TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        role TEXT NOT NULL,
        location TEXT,
        is_outdoor INTEGER NOT NULL,
        FOREIGN KEY (event_id) REFERENCES events(id)
    )""")

    c.execute("""CREATE TABLE availability (
        id INTEGER PRIMARY KEY,
        volunteer_id INTEGER NOT NULL,
        day_of_week TEXT NOT NULL,
        available_from TEXT NOT NULL,
        available_until TEXT NOT NULL,
        FOREIGN KEY (volunteer_id) REFERENCES volunteers(id)
    )""")

    c.execute("""CREATE TABLE attendance_history (
        id INTEGER PRIMARY KEY,
        volunteer_id INTEGER NOT NULL,
        shift_date TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (volunteer_id) REFERENCES volunteers(id)
    )""")

    for v in volunteers:
        c.execute("INSERT INTO volunteers VALUES (?,?,?,?,?,?,?)",
                  (v["id"], v["name"], v["email"], v["phone"],
                   v["certifications"], v["max_shifts_per_week"], v["experience_years"]))

    for e in events:
        c.execute("INSERT INTO events VALUES (?,?,?,?)",
                  (e["id"], e["name"], 1 if e["is_outdoor"] else 0, e["location"]))

    for s in shifts:
        c.execute("INSERT INTO shifts VALUES (?,?,?,?,?,?,?,?,?)",
                  (s["id"], s["event_id"], s["event_name"], s["day_of_week"],
                   s["start_time"], s["end_time"], s["role"], s["location"],
                   1 if s["is_outdoor"] else 0))

    for a in availability:
        c.execute("INSERT INTO availability VALUES (?,?,?,?,?)",
                  (a["id"], a["volunteer_id"], a["day_of_week"],
                   a["available_from"], a["available_until"]))

    for h in attendance:
        c.execute("INSERT INTO attendance_history VALUES (?,?,?,?)",
                  (h["id"], h["volunteer_id"], h["shift_date"], h["status"]))

    conn.commit()
    conn.close()


# ── Workspace files ────────────────────────────────────────────────────────

def create_workspace(workspace, events, weather_data):
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed file 1: scheduling_policy.yaml ──
    policy = {
        "no_show_threshold": 0.30,
        "rain_threshold": 0.50,
        "normal_backup_count": 1,
        "outdoor_rain_backup_count": 2,
        "assignment_order": "shift_id_ascending",
        "primary_tiebreaker": "volunteer_id_ascending",
        "reliability_formula": "1.0 minus no_show_rate",
    }
    with open(os.path.join(workspace, "scheduling_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # ── Fixed file 2: weather_forecast.json ──
    with open(os.path.join(workspace, "weather_forecast.json"), "w") as f:
        json.dump(weather_data, f, indent=2)

    # ── Fixed file 3: role_certification_matrix.csv ──
    with open(os.path.join(workspace, "role_certification_matrix.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["role", "required_certifications", "min_experience_years"])
        for role in sorted(ROLE_CERT_MAP.keys()):
            certs, min_exp = ROLE_CERT_MAP[role]
            writer.writerow([role, ";".join(certs), min_exp])

    # ── Fixed file 4: backup_priority_rules.md ──
    rules_md = """# Backup Priority Rules

When selecting backup volunteers for a shift, follow these guidelines in order.

First, compile a list of all volunteers who are eligible for the shift. Eligibility
means the volunteer holds every certification the role requires (as listed in the
role certification matrix) plus any additional certification specified in the
event briefing document for that event. The volunteer must also meet the minimum
experience threshold for the role and must be available during the full shift
window on the relevant day. A volunteer who is already assigned as primary to
another shift that overlaps in time on the same day is not eligible as a backup
for this shift. However, unlike primary assignments, backup designations do not
count toward the volunteer's weekly shift cap and do not create scheduling
conflicts with other backup designations.

Second, rank the eligible volunteers by their reliability score in descending
order. The reliability score equals one minus the volunteer's historical
no-show rate. If two volunteers share the same reliability score, the one with
the lower volunteer ID takes precedence.

Third, exclude the volunteer who has already been selected as the primary for
this shift. The remaining top-ranked eligible volunteers fill the backup slots.
Under normal conditions each shift receives the number of backups specified by
the normal_backup_count in the scheduling policy. For outdoor shifts on days
when the forecasted rain probability exceeds the rain threshold defined in the
scheduling policy, the shift receives the outdoor_rain_backup_count instead.

Note: volunteers whose no-show rate exceeds the policy threshold may still
serve as backups; they are only barred from primary assignment.
"""
    with open(os.path.join(workspace, "backup_priority_rules.md"), "w") as f:
        f.write(rules_md.strip() + "\n")

    # ── Fixed file 5: primary_assignment_rules.md ──
    primary_md = """# Primary Assignment Rules

Process shifts in ascending order of their shift identifier, as stated by the
assignment_order key in the scheduling policy. Assignments are sequential:
each primary selection changes the picture for every later shift, so do not
reorder.

For each shift, first determine the pool of eligible volunteers. A volunteer
is eligible for a shift when all of the following hold: the volunteer holds
every certification the shift's role requires according to the role
certification matrix, plus any additional certification specified in the
event briefing document for the event the shift belongs to; the volunteer
meets the role's minimum experience threshold from the same matrix; and at
least one of the volunteer's availability windows on the shift's day of the
week covers the full shift duration, from its start time through its end
time.

Two further restrictions apply to primary selection only. A volunteer who is
already assigned as primary to another shift that overlaps in time on the
same day is ineligible for this shift. A volunteer whose primary assignments
for the week have already reached their personal max_shifts_per_week is
ineligible for further primary selection (backup designations never count
toward this cap).

Among the remaining candidates, only those whose historical no-show rate does
not exceed the no_show_threshold in the scheduling policy may serve as
primary. Rank these candidates by reliability score - defined in the
scheduling policy as 1.0 minus the no-show rate - in descending order, and
break ties by selecting the volunteer with the lower volunteer ID. Assign the
top-ranked candidate as the shift's primary and record the assignment in the
scheduling system. In the unlikely case that no candidate satisfies the
no-show threshold, assign the highest-ranked remaining candidate regardless
of threshold.
"""
    with open(os.path.join(workspace, "primary_assignment_rules.md"), "w") as f:
        f.write(primary_md.strip() + "\n")

    # ── Scalable files: event_brief_XXX.json ──
    for event in events:
        brief = {
            "event_id": event["id"],
            "event_name": event["name"],
            "is_outdoor": event["is_outdoor"],
            "location": event["location"],
            "additional_certification": event["additional_certification"],
            "description": event["description"],
        }
        fname = f"event_brief_{event['id']:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(brief, f, indent=2)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    num_volunteers = SCALE["rows_per_table"]
    num_events = SCALE["num_workspace_files"]

    volunteers = generate_volunteers(fake, num_volunteers)
    events = generate_events(num_events)
    shifts = generate_shifts(events, min_shifts=SCALE["rows_per_table"])
    availability_records = generate_availability(volunteers)
    attendance_records = generate_attendance_history(volunteers, min_records=SCALE["rows_per_table"])

    ensure_solvability(volunteers, shifts, availability_records, events, attendance_records)

    create_database(args.db_path, volunteers, events, shifts, availability_records, attendance_records)
    create_workspace(args.workspace, events, WEATHER_TEMPLATE)

    print(f"Created DB at {args.db_path}")
    print(f"  volunteers:         {len(volunteers)}")
    print(f"  events:             {len(events)}")
    print(f"  shifts:             {len(shifts)}")
    print(f"  availability:       {len(availability_records)}")
    print(f"  attendance_history: {len(attendance_records)}")
    ws_files = os.listdir(args.workspace)
    print(f"Workspace at {args.workspace} ({len(ws_files)} files)")


if __name__ == "__main__":
    main()
