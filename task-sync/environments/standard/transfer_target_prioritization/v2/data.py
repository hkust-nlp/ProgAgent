import argparse
import os
import sqlite3
import json
import yaml
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 30,
}

fake = Faker()
Faker.seed(42)
np.random.seed(42)

POSITIONS = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST"]
LEAGUES = [
    "Premier League", "La Liga", "Serie A", "Bundesliga",
    "Ligue 1", "Eredivisie", "Primeira Liga", "Super Lig",
    "Scottish Premiership", "MLS",
]
NATIONALITIES = [
    "Brazil", "Argentina", "France", "Spain", "Germany", "England",
    "Portugal", "Netherlands", "Italy", "Colombia", "Belgium",
    "Uruguay", "Croatia", "Nigeria", "Senegal", "Japan",
    "South Korea", "Mexico", "USA", "Denmark",
]
ATTITUDE_GRADES = ["A", "B", "C", "D"]
COMPETITIONS = ["League", "Domestic Cup", "Champions League", "Europa League", "League Cup"]
FINANCIAL_CATEGORIES = [
    "total_revenue", "broadcast_income", "matchday_income", "commercial_income",
    "prize_money", "loan_income", "merchandise_revenue", "sponsorship_bonus",
    "youth_sales", "other_income",
    "committed_wages", "transfer_amortization", "youth_development",
    "stadium_operations", "medical_staff", "coaching_staff",
    "scouting_operations", "agent_fees", "bonus_obligations", "other_expenses",
]


def create_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            position TEXT NOT NULL,
            nationality TEXT NOT NULL,
            current_club TEXT NOT NULL,
            league TEXT NOT NULL,
            market_value_m REAL NOT NULL,
            contract_expiry_year INTEGER NOT NULL,
            wage_demand_weekly_k REAL NOT NULL,
            preferred_foot TEXT NOT NULL,
            caps_international INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scouting_reports (
            report_id INTEGER PRIMARY KEY,
            player_id INTEGER NOT NULL,
            scout_id TEXT NOT NULL,
            technical_score REAL NOT NULL,
            tactical_score REAL NOT NULL,
            physical_score REAL NOT NULL,
            mental_score REAL NOT NULL,
            potential_score REAL NOT NULL,
            overall_score REAL NOT NULL,
            report_date TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS squad_roster (
            member_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            position TEXT NOT NULL,
            age INTEGER NOT NULL,
            salary_weekly_k REAL NOT NULL,
            contract_end_year INTEGER NOT NULL,
            status TEXT NOT NULL,
            fitness_score INTEGER NOT NULL,
            appearances_season INTEGER NOT NULL,
            goals_season INTEGER NOT NULL,
            assists_season INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS financial_projections (
            entry_id INTEGER PRIMARY KEY,
            fiscal_year INTEGER NOT NULL,
            category TEXT NOT NULL,
            amount_m REAL NOT NULL,
            notes TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS match_schedule (
            fixture_id INTEGER PRIMARY KEY,
            match_date TEXT NOT NULL,
            opponent TEXT NOT NULL,
            competition TEXT NOT NULL,
            home_away TEXT NOT NULL,
            importance_rating INTEGER NOT NULL
        )
    """)
    conn.commit()


def generate_clubs(n_clubs=30):
    prefixes = [
        "FC", "AC", "Real", "Atletico", "Sporting", "Racing", "Dynamo",
        "Olympic", "Inter", "United", "City", "Rovers",
    ]
    suffixes = [
        "Lions", "Eagles", "Wolves", "Phoenix", "Titans", "Falcons",
        "Stallions", "Panthers", "Bears", "Hawks", "Sharks", "Dragons",
        "Vipers", "Cobras", "Stags", "Foxes", "Wasps", "Hornets",
        "Jaguars", "Leopards", "Rhinos", "Bison", "Cougars", "Marlins",
        "Condors", "Ospreys", "Otters", "Badgers", "Ravens", "Sparrows",
    ]
    cities = [fake.city() for _ in range(n_clubs)]
    clubs = []
    for i in range(n_clubs):
        prefix = prefixes[i % len(prefixes)]
        suffix = suffixes[i % len(suffixes)]
        clubs.append(f"{prefix} {cities[i]} {suffix}")
    return clubs


def generate_players(conn, n):
    clubs = generate_clubs(max(10, n // 4))
    rows = []
    for i in range(1, n + 1):
        pos = POSITIONS[i % len(POSITIONS)]
        age = int(np.random.randint(18, 35))
        mv = round(float(np.random.uniform(2.0, 120.0)), 1)
        if age <= 23:
            mv = round(mv * 1.3, 1)
        elif age >= 30:
            mv = round(mv * 0.7, 1)
        contract_years_left = int(np.random.randint(1, 5))
        contract_expiry = 2026 + contract_years_left
        wage = round(float(np.random.uniform(20.0, 350.0)), 1)
        foot = np.random.choice(["Right", "Left", "Both"], p=[0.55, 0.35, 0.10])
        caps = int(np.random.randint(0, 80))
        rows.append((
            i,
            fake.name_male(),
            age,
            pos,
            np.random.choice(NATIONALITIES),
            np.random.choice(clubs),
            np.random.choice(LEAGUES),
            mv,
            int(contract_expiry),
            wage,
            str(foot),
            caps,
        ))
    conn.executemany(
        "INSERT INTO players VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_scouting_reports(conn, n):
    c = conn.cursor()
    player_ids = [r[0] for r in c.execute("SELECT player_id FROM players").fetchall()]
    scout_names = [f"Scout_{fake.last_name()}" for _ in range(max(5, n // 20))]
    rows = []
    rid = 1
    assignments = []
    for pid in player_ids:
        num_reports = int(np.random.randint(1, 4))
        for _ in range(num_reports):
            assignments.append(pid)
    while len(assignments) < n:
        assignments.append(int(np.random.choice(player_ids)))
    np.random.shuffle(assignments)
    assignments = assignments[:max(n, len(assignments))]

    recommendations = ["Strong Buy", "Buy", "Monitor", "Pass"]
    rec_weights = [0.15, 0.30, 0.35, 0.20]

    for pid in assignments:
        tech = round(float(np.random.uniform(40, 95)), 1)
        tact = round(float(np.random.uniform(40, 95)), 1)
        phys = round(float(np.random.uniform(40, 95)), 1)
        ment = round(float(np.random.uniform(40, 95)), 1)
        pot = round(float(np.random.uniform(40, 95)), 1)
        overall = round((tech + tact + phys + ment + pot) / 5.0, 1)
        date = fake.date_between(start_date="-1y", end_date="today").isoformat()
        rec = np.random.choice(recommendations, p=rec_weights)
        rows.append((
            rid, pid,
            np.random.choice(scout_names),
            tech, tact, phys, ment, pot, overall,
            date, str(rec),
        ))
        rid += 1
    conn.executemany(
        "INSERT INTO scouting_reports VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_squad_roster(conn, n):
    statuses = ["first_team", "reserve", "youth", "loan_out"]
    status_weights = [0.35, 0.25, 0.25, 0.15]
    rows = []
    for i in range(1, n + 1):
        pos = POSITIONS[i % len(POSITIONS)]
        age = int(np.random.randint(17, 36))
        status = np.random.choice(statuses, p=status_weights)
        if status == "youth":
            age = int(np.random.randint(17, 21))
        salary = round(float(np.random.uniform(5.0, 280.0)), 1)
        contract_end = int(np.random.randint(2026, 2031))
        fitness = int(np.random.randint(40, 100))
        apps = int(np.random.randint(0, 40))
        goals = int(np.random.randint(0, max(1, apps // 3)))
        assists = int(np.random.randint(0, max(1, apps // 4)))
        rows.append((
            i,
            fake.name_male(),
            pos,
            age,
            salary,
            contract_end,
            str(status),
            fitness,
            apps,
            goals,
            assists,
        ))
    conn.executemany(
        "INSERT INTO squad_roster VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_financial_projections(conn, n):
    years = list(range(2026, 2031))
    cats_per_year = max(len(FINANCIAL_CATEGORIES), n // len(years))
    categories = FINANCIAL_CATEGORIES[:]
    while len(categories) < cats_per_year:
        categories.append(f"misc_item_{len(categories)}")
    categories = categories[:cats_per_year]

    rows = []
    eid = 1
    base_revenue = float(np.random.uniform(350, 500))
    for yr in years:
        growth = 1.0 + (yr - 2026) * 0.03
        for cat in categories:
            if cat in [
                "total_revenue", "broadcast_income", "matchday_income",
                "commercial_income", "prize_money", "loan_income",
                "merchandise_revenue", "sponsorship_bonus", "youth_sales",
                "other_income",
            ]:
                if cat == "total_revenue":
                    amt = round(base_revenue * growth, 2)
                elif cat == "broadcast_income":
                    amt = round(base_revenue * 0.35 * growth * float(np.random.uniform(0.9, 1.1)), 2)
                elif cat == "matchday_income":
                    amt = round(base_revenue * 0.15 * growth * float(np.random.uniform(0.9, 1.1)), 2)
                elif cat == "commercial_income":
                    amt = round(base_revenue * 0.30 * growth * float(np.random.uniform(0.9, 1.1)), 2)
                else:
                    amt = round(float(np.random.uniform(2.0, 30.0)) * growth, 2)
            else:
                if cat == "committed_wages":
                    amt = round(base_revenue * 0.45 * growth * float(np.random.uniform(0.95, 1.05)), 2)
                elif cat == "transfer_amortization":
                    amt = round(float(np.random.uniform(20.0, 60.0)) * growth, 2)
                else:
                    amt = round(float(np.random.uniform(3.0, 25.0)) * growth, 2)
            note = f"Projected {cat} for FY{yr}"
            rows.append((eid, yr, cat, amt, note))
            eid += 1
    while len(rows) < n:
        yr = int(np.random.choice(years))
        cat = f"supplementary_item_{len(rows)}"
        amt = round(float(np.random.uniform(1.0, 15.0)), 2)
        rows.append((eid, yr, cat, amt, f"Supplementary {cat}"))
        eid += 1
    conn.executemany(
        "INSERT INTO financial_projections VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_match_schedule(conn, n):
    rows = []
    opponents = generate_clubs(20)
    fid = 1
    start_date = pd.Timestamp("2026-08-01")
    total_days = 300
    for i in range(n):
        day_offset = int((total_days / n) * i + np.random.randint(0, max(1, total_days // n)))
        match_date = (start_date + pd.Timedelta(days=day_offset)).strftime("%Y-%m-%d")
        comp = np.random.choice(COMPETITIONS, p=[0.40, 0.15, 0.20, 0.15, 0.10])
        ha = np.random.choice(["Home", "Away"], p=[0.5, 0.5])
        importance = int(np.random.randint(1, 11))
        rows.append((
            fid,
            match_date,
            str(np.random.choice(opponents)),
            str(comp),
            str(ha),
            importance,
        ))
        fid += 1
    conn.executemany(
        "INSERT INTO match_schedule VALUES (?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


# ── Workspace generation ──────────────────────────────────────────────

def _generate_scouting_dossiers(conn, workspace, n_files):
    c = conn.cursor()
    players = c.execute(
        "SELECT player_id, name, position, league FROM players"
    ).fetchall()

    leagues_unique = sorted(set(p[3] for p in players))
    league_to_file = {}
    for idx, lg in enumerate(leagues_unique):
        league_to_file[lg] = idx % n_files

    file_buckets = {i: [] for i in range(n_files)}
    for pid, name, pos, lg in players:
        fid = league_to_file[lg]
        injury_risk = int(np.random.randint(1, 11))
        attitude = str(np.random.choice(ATTITUDE_GRADES, p=[0.20, 0.40, 0.30, 0.10]))
        adaptability = int(np.random.randint(1, 11))
        consistency = int(np.random.randint(1, 11))
        leadership = int(np.random.randint(1, 11))
        file_buckets[fid].append({
            "player_id": pid,
            "player_name": name,
            "position": pos,
            "injury_risk": injury_risk,
            "attitude_grade": attitude,
            "adaptability": adaptability,
            "consistency": consistency,
            "leadership": leadership,
        })

    region_labels = [
        "iberia", "central_europe", "western_europe", "northern_europe",
        "southern_europe", "south_america", "north_america", "eastern_europe",
        "asia_pacific", "africa", "middle_east", "scandinavia",
        "balkans", "caribbean", "oceania",
    ]
    for i in range(n_files):
        label = region_labels[i % len(region_labels)]
        if i >= len(region_labels):
            label = f"{label}_{i // len(region_labels)}"
        fname = os.path.join(workspace, f"scouting_dossier_{label}.csv")
        df = pd.DataFrame(file_buckets[i])
        if len(df) == 0:
            p = players[i % len(players)]
            df = pd.DataFrame([{
                "player_id": p[0], "player_name": p[1], "position": p[2],
                "injury_risk": 5, "attitude_grade": "B",
                "adaptability": 5, "consistency": 5, "leadership": 5,
            }])
        df.to_csv(fname, index=False)


def _generate_squad_depth_charts(conn, workspace, n_files):
    c = conn.cursor()
    squad = c.execute(
        "SELECT member_id, name, position, age, status, fitness_score FROM squad_roster"
    ).fetchall()

    # Fixed urgency map per position — scale-invariant so the same positions
    # are always priority regardless of how many squad rows exist.
    # Use a dedicated RNG seeded identically every run so the map never changes.
    _urg_rng = np.random.RandomState(7777)
    POSITION_URGENCY_MAP = {}
    urgency_pool = ["critical", "high", "high", "medium", "medium", "low", "low", "low", "low", "low"]
    _urg_rng.shuffle(urgency_pool)
    for idx, pos in enumerate(POSITIONS):
        POSITION_URGENCY_MAP[pos] = urgency_pool[idx]

    pos_groups = []
    for i in range(n_files):
        pos_groups.append([])
    for idx, pos in enumerate(POSITIONS):
        pos_groups[idx % n_files].append(pos)

    group_labels = [
        "goalkeepers", "central_defense", "fullbacks", "defensive_midfield",
        "central_midfield", "attacking_midfield", "wide_attackers", "strikers",
        "reserves_overview", "versatile_players", "set_piece_specialists",
        "aerial_threats", "pace_merchants", "playmakers", "utility_players",
    ]

    for i in range(n_files):
        positions_in_group = pos_groups[i]
        members_in_group = [s for s in squad if s[2] in positions_in_group]

        rows_out = []
        for pos in positions_in_group:
            pos_members = [m for m in members_in_group if m[2] == pos]
            first_team = [m for m in pos_members if m[4] == "first_team"]
            backup_count = len([m for m in pos_members if m[4] in ["first_team", "reserve"]])

            avg_fitness = np.mean([m[5] for m in pos_members]) if pos_members else 50
            quality = int(np.clip(avg_fitness / 10 - int(np.random.randint(0, 3)), 1, 10))
            tactical_fit = int(np.random.randint(3, 10))

            urgency = POSITION_URGENCY_MAP[pos]

            rows_out.append({
                "position": pos,
                "first_team_count": len(first_team),
                "total_available": backup_count,
                "quality_rating": quality,
                "tactical_fit": tactical_fit,
                "avg_fitness": round(float(avg_fitness), 1),
                "urgency": urgency,
            })

        label = group_labels[i % len(group_labels)]
        if i >= len(group_labels):
            label = f"{label}_{i // len(group_labels)}"
        fname = os.path.join(workspace, f"squad_depth_{label}.csv")
        pd.DataFrame(rows_out).to_csv(fname, index=False)


def _generate_fixture_files(conn, workspace, n_files):
    c = conn.cursor()
    fixtures = c.execute(
        "SELECT fixture_id, match_date, opponent, competition, home_away, importance_rating "
        "FROM match_schedule ORDER BY match_date"
    ).fetchall()

    chunk_size = max(1, len(fixtures) // n_files)
    chunks = []
    for i in range(n_files):
        start = i * chunk_size
        end = start + chunk_size if i < n_files - 1 else len(fixtures)
        chunks.append(fixtures[start:end])

    for i, chunk in enumerate(chunks):
        records = []
        for fid, mdate, opp, comp, ha, imp in chunk:
            travel_km = int(np.random.randint(0, 3000)) if ha == "Away" else 0
            recovery_days = int(np.random.randint(2, 5))
            if comp == "Champions League":
                recovery_days = max(2, recovery_days - 1)
            records.append({
                "fixture_id": fid,
                "match_date": mdate,
                "opponent": opp,
                "competition": comp,
                "home_away": ha,
                "importance_rating": imp,
                "travel_km": travel_km,
                "recovery_days_available": recovery_days,
            })
        if records:
            first_month = records[0]["match_date"][:7]
            last_month = records[-1]["match_date"][:7]
            label = f"{first_month}_to_{last_month}".replace("-", "")
        else:
            label = f"period_{i}"
        fname = os.path.join(workspace, f"fixture_block_{label}.json")
        with open(fname, "w") as f:
            json.dump(records, f, indent=2)


def _generate_transfer_policy(workspace):
    policy = {
        "eligibility": {
            "max_age_by_position": {
                "GK": 34, "CB": 32, "LB": 31, "RB": 31,
                "CDM": 31, "CM": 31, "CAM": 30,
                "LW": 30, "RW": 30, "ST": 32,
            },
            "wage_ceiling_weekly_k": 250.0,
            "min_overall_scouting_score": 60.0,
            "min_weighted_composite_score": 55.0,
        },
        "bid_calculation": {
            "base_multiplier": 0.85,
            "contract_premium_per_year": 0.05,
            "age_threshold": 28,
            "age_discount_per_year": 0.04,
            "urgency_premium": {
                "critical": 0.15,
                "high": 0.10,
                "medium": 0.05,
                "low": 0.00,
            },
            "high_range_factor": 1.20,
        },
        "budget": {
            "description": "Available transfer budget for the budget_year is computed as total_revenue minus the sum of all expense categories for that year from the financial projections.",
            "revenue_categories": [
                "total_revenue",
            ],
            "expense_categories": [
                "committed_wages", "transfer_amortization", "youth_development",
                "stadium_operations", "medical_staff", "coaching_staff",
                "scouting_operations", "agent_fees", "bonus_obligations",
                "other_expenses",
            ],
            "budget_year": 2026,
        },
        "shortlist": {
            "max_targets_per_position": 3,
            "only_priority_positions": True,
            "priority_urgency_levels": ["critical", "high"],
        },
        "congestion_rules": {
            "congested_month_threshold": 6,
            "congestion_boost_trigger_months": 2,
            "boost_effect": "positions at medium urgency are promoted to high when the number of congested months meets or exceeds the trigger value",
        },
    }
    with open(os.path.join(workspace, "transfer_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)


def _generate_scoring_weights(workspace):
    weights = {
        "technical": 0.20,
        "tactical": 0.18,
        "physical": 0.14,
        "mental": 0.13,
        "potential": 0.10,
        "injury_risk_inverted": 0.08,
        "attitude": 0.07,
        "adaptability": 0.05,
        "consistency": 0.03,
        "leadership": 0.02,
    }
    attitude_mapping = {
        "A": 10,
        "B": 7,
        "C": 4,
        "D": 1,
    }
    config = {
        "weights": weights,
        "attitude_to_numeric": attitude_mapping,
        "injury_risk_inversion": "score = 11 - injury_risk (so lower risk yields higher score)",
        "score_range": "All component scores are on a 1-10 scale before weighting. Scouting scores from tool results are on a 0-100 scale and must be divided by 10 before applying weights.",
    }
    with open(os.path.join(workspace, "scoring_weights.json"), "w") as f:
        json.dump(config, f, indent=2)


def generate_workspace(conn, workspace, n_files):
    os.makedirs(workspace, exist_ok=True)

    n_scout = n_files // 3 + (1 if n_files % 3 >= 1 else 0)
    n_depth = n_files // 3 + (1 if n_files % 3 >= 2 else 0)
    n_fixture = n_files // 3

    _generate_scouting_dossiers(conn, workspace, n_scout)
    _generate_squad_depth_charts(conn, workspace, n_depth)
    _generate_fixture_files(conn, workspace, n_fixture)

    # Fixed config files (not part of SCALE count)
    _generate_transfer_policy(workspace)
    _generate_scoring_weights(workspace)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    generate_players(conn, n)
    generate_scouting_reports(conn, n)
    generate_squad_roster(conn, n)
    generate_financial_projections(conn, n)
    generate_match_schedule(conn, n)
    generate_workspace(conn, args.workspace, SCALE["num_workspace_files"])

    conn.close()
    print(f"Data generated: db={args.db_path}, workspace={args.workspace}")


if __name__ == "__main__":
    main()
