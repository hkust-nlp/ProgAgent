"""
Data generation for weekly referee assignment roster task.
Generates database tables and workspace files for referee scheduling.
"""

import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker
import yaml

# ──────────────────────────────────────────────────────────────
# SCALE — only this block differs across v0 / v1 / v2 / v3
# ──────────────────────────────────────────────────────────────
SCALE = {
    "rows_per_table": 100,      # v2 = 4x base
    "num_workspace_files": 30,  # v2 = base + 2N (N=10)
}

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
MATCH_TYPES = ["league", "cup", "friendly", "playoff", "international"]
CERT_LEVELS = {"basic": 1, "advanced": 2, "elite": 3}
TIME_SLOTS = ["morning", "afternoon", "evening"]
WEEK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DIVISIONS = ["Division A", "Division B", "Division C", "Division D"]

MATCH_CERT_REQUIREMENTS = {
    "friendly": "basic",
    "league": "advanced",
    "cup": "advanced",
    "playoff": "elite",
    "international": "elite",
}

CONFLICT_TYPES = ["bias_complaint", "prior_incident", "financial_interest", "family_tie", "regional_rivalry"]


def set_seeds(seed=42):
    random.seed(seed)
    np.random.seed(seed)


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS referees (
            referee_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            home_city TEXT NOT NULL,
            experience_years INTEGER NOT NULL,
            max_weekly_assignments INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            division TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            venue_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            has_var INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS fixtures (
            fixture_id INTEGER PRIMARY KEY,
            match_date TEXT NOT NULL,
            day_of_week TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL,
            venue_id INTEGER NOT NULL,
            match_type TEXT NOT NULL,
            priority_level INTEGER NOT NULL,
            FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
            FOREIGN KEY (away_team_id) REFERENCES teams(team_id),
            FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS certifications (
            cert_id INTEGER PRIMARY KEY,
            referee_id INTEGER NOT NULL,
            match_type TEXT NOT NULL,
            cert_level TEXT NOT NULL,
            FOREIGN KEY (referee_id) REFERENCES referees(referee_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS conflicts (
            conflict_id INTEGER PRIMARY KEY,
            referee_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            conflict_type TEXT NOT NULL,
            severity INTEGER NOT NULL,
            active INTEGER NOT NULL,
            FOREIGN KEY (referee_id) REFERENCES referees(referee_id),
            FOREIGN KEY (team_id) REFERENCES teams(team_id)
        )
    """)
    conn.commit()


def generate_cities(fake, n):
    """Generate a pool of unique city names."""
    cities = set()
    while len(cities) < n:
        cities.add(fake.city())
    return sorted(cities)


def generate_referees(conn, fake, cities, n_referees):
    rows = []
    for i in range(1, n_referees + 1):
        name = fake.name()
        home_city = cities[i % len(cities)]
        exp = random.randint(1, 25)
        max_weekly = random.choice([3, 4, 5, 6])
        rows.append((i, name, home_city, exp, max_weekly))
    conn.executemany(
        "INSERT INTO referees VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_teams(conn, fake, cities, n_teams):
    used_names = set()
    rows = []
    suffixes = ['United', 'FC', 'City', 'Rovers', 'Athletic',
                'Wanderers', 'Rangers', 'Dynamo', 'Sporting', 'Olympique']
    for i in range(1, n_teams + 1):
        while True:
            team_name = f"{fake.city()} {random.choice(suffixes)}"
            if team_name not in used_names:
                used_names.add(team_name)
                break
        city = cities[i % len(cities)]
        division = DIVISIONS[i % len(DIVISIONS)]
        rows.append((i, team_name, city, division))
    conn.executemany(
        "INSERT INTO teams VALUES (?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_venues(conn, fake, cities, n_venues):
    rows = []
    for i in range(1, n_venues + 1):
        vname = f"{fake.last_name()} {random.choice(['Stadium', 'Arena', 'Park', 'Ground', 'Field'])}"
        city = cities[i % len(cities)]
        capacity = random.choice([5000, 10000, 15000, 20000, 30000, 50000])
        has_var = random.choice([0, 1])
        rows.append((i, vname, city, capacity, has_var))
    conn.executemany(
        "INSERT INTO venues VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_fixtures(conn, team_rows, venue_rows, n_fixtures):
    rows = []
    team_ids = [t[0] for t in team_rows]
    venue_ids = [v[0] for v in venue_rows]

    base_dates = [f"2026-04-{20 + d}" for d in range(7)]

    for i in range(1, n_fixtures + 1):
        day_idx = (i - 1) % 7
        match_date = base_dates[day_idx]
        day_of_week = WEEK_DAYS[day_idx]
        time_slot = TIME_SLOTS[(i - 1) % len(TIME_SLOTS)]

        ht = team_ids[(i * 2) % len(team_ids)]
        at = team_ids[(i * 2 + 1) % len(team_ids)]
        if ht == at:
            at = team_ids[(i * 2 + 3) % len(team_ids)]

        venue_id = venue_ids[(i - 1) % len(venue_ids)]

        if i % 7 == 0:
            mt = "international"
        elif i % 5 == 0:
            mt = "playoff"
        elif i % 3 == 0:
            mt = "cup"
        elif i % 4 == 0:
            mt = "friendly"
        else:
            mt = "league"

        priority = {"friendly": 1, "league": 2, "cup": 3, "playoff": 4, "international": 5}[mt]
        rows.append((i, match_date, day_of_week, time_slot, ht, at, venue_id, mt, priority))

    conn.executemany(
        "INSERT INTO fixtures VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_certifications(conn, referee_rows, n_certs):
    """Each referee gets certifications for 2-4 match types at varying levels."""
    rows = []
    cert_id = 1
    referee_ids = [r[0] for r in referee_rows]

    for rid in referee_ids:
        n_types = random.randint(2, min(4, len(MATCH_TYPES)))
        chosen_types = random.sample(MATCH_TYPES, n_types)
        for mt in chosen_types:
            ref_row = next(r for r in referee_rows if r[0] == rid)
            exp = ref_row[3]
            if exp >= 15:
                lvl = random.choice(["advanced", "elite", "elite"])
            elif exp >= 7:
                lvl = random.choice(["basic", "advanced", "advanced", "elite"])
            else:
                lvl = random.choice(["basic", "basic", "advanced"])
            rows.append((cert_id, rid, mt, lvl))
            cert_id += 1

    while len(rows) < n_certs:
        rid = random.choice(referee_ids)
        mt = random.choice(MATCH_TYPES)
        existing = [(r[1], r[2]) for r in rows]
        if (rid, mt) not in existing:
            lvl = random.choice(list(CERT_LEVELS.keys()))
            rows.append((cert_id, rid, mt, lvl))
            cert_id += 1

    conn.executemany(
        "INSERT INTO certifications VALUES (?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_conflicts(conn, referee_rows, team_rows, n_conflicts):
    rows = []
    referee_ids = [r[0] for r in referee_rows]
    team_ids = [t[0] for t in team_rows]

    used_pairs = set()
    conflict_id = 1
    while len(rows) < n_conflicts:
        rid = random.choice(referee_ids)
        tid = random.choice(team_ids)
        if (rid, tid) in used_pairs:
            continue
        used_pairs.add((rid, tid))
        ct = random.choice(CONFLICT_TYPES)
        severity = random.randint(1, 5)
        active = random.choices([1, 0], weights=[0.7, 0.3])[0]
        rows.append((conflict_id, rid, tid, ct, severity, active))
        conflict_id += 1

    conn.executemany(
        "INSERT INTO conflicts VALUES (?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_distance_matrix(cities):
    """Generate a symmetric distance matrix between cities."""
    n = len(cities)
    distances = {}
    for i in range(n):
        for j in range(n):
            if i == j:
                distances[(cities[i], cities[j])] = 0
            elif (cities[j], cities[i]) in distances:
                distances[(cities[i], cities[j])] = distances[(cities[j], cities[i])]
            else:
                distances[(cities[i], cities[j])] = random.randint(10, 500)
    return distances


def write_workspace_files(workspace, referee_rows, venue_rows, team_rows,
                          fixture_rows, cities, distances, n_avail_files):
    os.makedirs(workspace, exist_ok=True)
    avail_dir = os.path.join(workspace, "availability")
    os.makedirs(avail_dir, exist_ok=True)

    # ── Fixed policy files ──────────────────────────────────────

    # 1. policy.yaml
    policy = {
        "max_travel_distance_km": 300,
        "assignment_priority_order": "priority_level descending, then match_date ascending, then time_slot order morning<afternoon<evening, then fixture_id ascending",
        "tiebreak_rules": [
            "Highest certification level for the fixture match type (elite=3 > advanced=2 > basic=1)",
            "Most experience years",
            "Lowest referee_id as final tiebreaker"
        ],
        "conflict_policy": "A referee must NOT be assigned to any fixture involving a team with which they have an ACTIVE conflict (active=1). Inactive conflicts are ignored.",
        "time_slot_constraint": "A referee cannot officiate more than one match in the same day and time_slot combination.",
    }
    with open(os.path.join(workspace, "policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. match_requirements.json
    with open(os.path.join(workspace, "match_requirements.json"), "w") as f:
        json.dump(MATCH_CERT_REQUIREMENTS, f, indent=2)

    # 3. travel_matrix.csv
    city_list = sorted(set(cities))
    rows_csv = []
    for c1 in city_list:
        row = {"city": c1}
        for c2 in city_list:
            row[c2] = distances.get((c1, c2), distances.get((c2, c1), 0))
        rows_csv.append(row)
    df_dist = pd.DataFrame(rows_csv)
    df_dist.to_csv(os.path.join(workspace, "travel_matrix.csv"), index=False)

    # 4. scheduling_notes.txt
    with open(os.path.join(workspace, "scheduling_notes.txt"), "w") as f:
        f.write("Weekly Referee Scheduling Notes\n")
        f.write("=" * 40 + "\n\n")
        f.write("All assignments for the week of 2026-04-20 through 2026-04-26.\n\n")
        f.write("Referees who do not have an availability file on record are considered\n")
        f.write("UNAVAILABLE for the entire week and must not be assigned.\n\n")
        f.write("The final roster must be saved as 'roster.csv' with the following columns:\n")
        f.write("fixture_id, match_date, day_of_week, time_slot, home_team, away_team, ")
        f.write("venue_name, referee_id, referee_name\n\n")
        f.write("Rows in roster.csv must be sorted by fixture_id ascending.\n\n")
        f.write("If no eligible referee can be found for a fixture after applying all\n")
        f.write("constraints, that fixture must still appear in roster.csv with\n")
        f.write("referee_id set to -1 and referee_name set to 'UNASSIGNED'.\n")

    # 5. output_format.md
    with open(os.path.join(workspace, "output_format.md"), "w") as f:
        f.write("# Output Specification\n\n")
        f.write("The deliverable is a single file named `roster.csv` placed in the working directory.\n\n")
        f.write("Columns (exact names, exact order):\n\n")
        f.write("| Column | Type | Description |\n")
        f.write("|--------|------|-------------|\n")
        f.write("| fixture_id | int | Fixture identifier |\n")
        f.write("| match_date | str | YYYY-MM-DD format |\n")
        f.write("| day_of_week | str | Full day name (Monday, Tuesday, etc.) |\n")
        f.write("| time_slot | str | morning, afternoon, or evening |\n")
        f.write("| home_team | str | Full team name |\n")
        f.write("| away_team | str | Full team name |\n")
        f.write("| venue_name | str | Full venue name |\n")
        f.write("| referee_id | int | Referee ID or -1 if unassigned |\n")
        f.write("| referee_name | str | Referee full name or UNASSIGNED |\n\n")
        f.write("No additional columns. No index column. UTF-8 encoding.\n")

    # 6. assignment_methodology.md
    with open(os.path.join(workspace, "assignment_methodology.md"), "w") as f:
        f.write("# Assignment Methodology\n\n")
        f.write("This document is the binding procedure for constructing the weekly roster.\n")
        f.write("It complements the policy file (travel limit, processing order, tie-breaks,\n")
        f.write("conflict policy, time-slot rule), the match requirements mapping, the travel\n")
        f.write("matrix, the scheduling notes, and the output specification.\n\n")
        f.write("## Active pool\n\n")
        f.write("Only referees with an availability file on record in the availability\n")
        f.write("subdirectory form the active pool for the week. Referees without such a file\n")
        f.write("are entirely unavailable regardless of any other data.\n\n")
        f.write("## Procedure\n\n")
        f.write("The assignment algorithm is strictly greedy. Process fixtures one at a time\n")
        f.write("in the exact order given by the policy file's assignment_priority_order.\n")
        f.write("For each fixture, evaluate every referee in the active pool against ALL of\n")
        f.write("the following eligibility conditions:\n\n")
        f.write("1. Weekly cap: the referee's number of assignments already confirmed this\n")
        f.write("   week must be strictly below their max_weekly_assignments value.\n")
        f.write("2. Slot exclusivity: the referee must not already be assigned to another\n")
        f.write("   fixture in the same day-of-week and time-slot combination.\n")
        f.write("3. Availability: the referee's availability file must list the fixture's\n")
        f.write("   day of week, and that day's entry must include the fixture's time slot.\n")
        f.write("4. Certification: the referee must hold a certification for the fixture's\n")
        f.write("   match type at or above the minimum level given in the match requirements\n")
        f.write("   mapping. Levels compare numerically: basic=1, advanced=2, elite=3. A\n")
        f.write("   referee with no certification for that match type is ineligible.\n")
        f.write("5. Conflicts: the referee must have no ACTIVE conflict (active=1) with\n")
        f.write("   either the home team or the away team. Inactive conflicts are ignored.\n")
        f.write("6. Travel: the distance between the referee's home city and the fixture\n")
        f.write("   venue's city, per the travel matrix, must not exceed the policy's\n")
        f.write("   max_travel_distance_km. The matrix is symmetric; either lookup\n")
        f.write("   direction may be used.\n\n")
        f.write("From the eligible referees, select the single best candidate using the\n")
        f.write("tiebreak_rules in the policy file, applied in order. If no referee is\n")
        f.write("eligible, leave the fixture unassigned using the sentinel values described\n")
        f.write("in the scheduling notes.\n\n")
        f.write("## Recording\n\n")
        f.write("Every confirmed fixture-referee pairing must be recorded in the league's\n")
        f.write("central assignment registry. Fixtures left unassigned are not registered.\n")

    # ── Scaling availability files ──────────────────────────────

    all_ref_ids = [r[0] for r in referee_rows]
    available_ref_ids = sorted(all_ref_ids[:n_avail_files])

    for rid in available_ref_ids:
        ref_row = next(r for r in referee_rows if r[0] == rid)
        n_days_avail = random.randint(4, 7)
        avail_days = sorted(random.sample(WEEK_DAYS, n_days_avail),
                            key=lambda d: WEEK_DAYS.index(d))
        schedule = {}
        for day in avail_days:
            n_slots = random.randint(1, 3)
            slots = sorted(random.sample(TIME_SLOTS, n_slots),
                           key=lambda s: TIME_SLOTS.index(s))
            schedule[day] = slots

        avail_data = {
            "referee_id": rid,
            "referee_name": ref_row[1],
            "week_start": "2026-04-20",
            "availability": schedule
        }

        fname = f"referee_{rid:04d}.json"
        with open(os.path.join(avail_dir, fname), "w") as f:
            json.dump(avail_data, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    set_seeds(42)
    fake = Faker()
    Faker.seed(42)

    rpt = SCALE["rows_per_table"]
    nwf = SCALE["num_workspace_files"]

    n_referees = max(rpt, nwf + 5)
    n_teams = rpt
    n_venues = max(rpt, 10)
    n_fixtures = rpt
    n_certs = rpt * 2
    n_conflicts = rpt

    n_cities = max(15, n_venues)
    cities = generate_cities(fake, n_cities)

    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    referee_rows = generate_referees(conn, fake, cities, n_referees)
    team_rows = generate_teams(conn, fake, cities, n_teams)
    venue_rows = generate_venues(conn, fake, cities, n_venues)
    fixture_rows = generate_fixtures(conn, team_rows, venue_rows, n_fixtures)
    cert_rows = generate_certifications(conn, referee_rows, n_certs)
    conflict_rows = generate_conflicts(conn, referee_rows, team_rows, n_conflicts)

    conn.close()

    all_cities = sorted(set(cities))
    distances = generate_distance_matrix(all_cities)

    write_workspace_files(
        args.workspace, referee_rows, venue_rows, team_rows,
        fixture_rows, cities, distances, nwf
    )

    print(f"Database created at {args.db_path}")
    print(f"  referees:       {n_referees}")
    print(f"  teams:          {n_teams}")
    print(f"  venues:         {n_venues}")
    print(f"  fixtures:       {n_fixtures}")
    print(f"  certifications: {len(cert_rows)}")
    print(f"  conflicts:      {n_conflicts}")
    print(f"Workspace created at {args.workspace}")
    print(f"  availability files: {nwf}")


if __name__ == "__main__":
    main()
