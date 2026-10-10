import os
import argparse
import sqlite3
import json
import yaml
import csv
import numpy as np
from datetime import datetime, timedelta
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 40,
}

END_DATE = datetime(2025, 1, 15)
TEAMS = ["Alpha FC", "Beta United", "Gamma Athletic", "Delta Sports", "Epsilon Rangers"]
POSITIONS = ["Forward", "Midfielder", "Defender", "Goalkeeper", "Winger"]
BODY_REGIONS = [
    "knee", "ankle", "hamstring", "shoulder", "back",
    "hip", "groin", "calf", "quadriceps", "foot",
]
INJURY_TYPES = ["strain", "sprain", "contusion", "fracture", "tendinitis", "tear", "dislocation"]
SESSION_TYPES = ["strength", "conditioning", "tactical", "match", "recovery"]

BODY_REGION_MULTIPLIERS = {
    "knee": 1.5, "ankle": 1.3, "hamstring": 1.4, "shoulder": 1.1,
    "back": 1.3, "hip": 1.2, "groin": 1.3, "calf": 1.2,
    "quadriceps": 1.2, "foot": 1.1,
}

FATIGUE_WEIGHTS = {
    "wellness_weight": 0.30,
    "training_weight": 0.25,
    "sleep_weight": 0.25,
    "injury_weight": 0.20,
}

RISK_THRESHOLDS_CONFIG = {
    "analysis_window_days": 7,
    "injury_lookback_days": 90,
    "reference_date": END_DATE.strftime("%Y-%m-%d"),
    "risk_levels": {
        "critical": {"min_score": 7.0, "protocol": "Protocol_A"},
        "high": {"min_score": 5.0, "protocol": "Protocol_B"},
        "moderate": {"min_score": 3.5, "protocol": "Protocol_C"},
        "low": {"min_score": 0.0, "protocol": "None"},
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    num_athletes = SCALE["rows_per_table"]
    num_days = SCALE["num_workspace_files"]

    os.makedirs(args.workspace, exist_ok=True)

    # Date range: num_days ending on END_DATE
    dates = [END_DATE - timedelta(days=num_days - 1 - i) for i in range(num_days)]
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]

    # ---- Athlete profiles ----
    athletes = []
    for i in range(num_athletes):
        athletes.append({
            "athlete_id": i + 1,
            "name": fake.unique.name(),
            "age": int(np.random.randint(18, 38)),
            "position": POSITIONS[int(np.random.randint(0, len(POSITIONS)))],
        })

    # Team assignments (workspace-only, NOT stored in DB)
    team_data = []
    for i, ath in enumerate(athletes):
        team_data.append({
            "athlete_id": ath["athlete_id"],
            "team": TEAMS[i % len(TEAMS)],
            "jersey_number": int(np.random.randint(1, 100)),
            "contract_status": str(np.random.choice(["active", "reserve", "loan"])),
        })

    # Risk profiles drive data characteristics (not stored anywhere)
    risk_profiles = []
    for i in range(num_athletes):
        r = np.random.random()
        if r < 0.15:
            risk_profiles.append("critical")
        elif r < 0.35:
            risk_profiles.append("high")
        elif r < 0.60:
            risk_profiles.append("moderate")
        else:
            risk_profiles.append("low")

    # ---- Wellness surveys ----
    wellness_data = []
    for ath_idx, athlete in enumerate(athletes):
        profile = risk_profiles[ath_idx]
        for date_str in date_strs:
            if profile == "critical":
                base = np.random.uniform(2.0, 4.0)
            elif profile == "high":
                base = np.random.uniform(3.5, 5.5)
            elif profile == "moderate":
                base = np.random.uniform(5.5, 7.0)
            else:
                base = np.random.uniform(7.5, 9.5)

            wellness_data.append({
                "athlete_id": athlete["athlete_id"],
                "date": date_str,
                "fatigue_rating": round(float(np.clip(base + np.random.normal(0, 0.5), 1, 10)), 1),
                "mood_rating": round(float(np.clip(base + np.random.normal(0, 0.7), 1, 10)), 1),
                "soreness_rating": round(float(np.clip(base + np.random.normal(0, 0.6), 1, 10)), 1),
                "stress_rating": round(float(np.clip(base + np.random.normal(0, 0.5), 1, 10)), 1),
                "sleep_quality_rating": round(float(np.clip(base + np.random.normal(0, 0.4), 1, 10)), 1),
            })

    # ---- GPS training load ----
    gps_data = []
    for ath_idx, athlete in enumerate(athletes):
        profile = risk_profiles[ath_idx]
        for day_idx, date_str in enumerate(date_strs):
            recency = day_idx / max(num_days - 1, 1)
            if profile in ["critical", "high"]:
                load_boost = 1.0 + recency * 0.5
                player_load = round(float(np.random.uniform(550, 800) * load_boost), 1)
            elif profile == "moderate":
                player_load = round(float(np.random.uniform(400, 600)), 1)
            else:
                player_load = round(float(np.random.uniform(250, 450)), 1)

            gps_data.append({
                "athlete_id": athlete["athlete_id"],
                "date": date_str,
                "total_distance_m": round(float(np.random.uniform(5000, 12000)), 0),
                "high_speed_distance_m": round(float(np.random.uniform(500, 2500)), 0),
                "sprint_count": int(np.random.randint(5, 30)),
                "duration_min": round(float(np.random.uniform(60, 120)), 0),
                "player_load": player_load,
            })

    # ---- Sleep tracker ----
    sleep_data = []
    for ath_idx, athlete in enumerate(athletes):
        profile = risk_profiles[ath_idx]
        for date_str in date_strs:
            if profile == "critical":
                sleep_hours = round(float(np.random.uniform(4.0, 6.0)), 1)
                efficiency = round(float(np.random.uniform(60, 75)), 1)
                awakenings = int(np.random.randint(3, 7))
            elif profile == "high":
                sleep_hours = round(float(np.random.uniform(5.0, 6.8)), 1)
                efficiency = round(float(np.random.uniform(68, 80)), 1)
                awakenings = int(np.random.randint(2, 5))
            elif profile == "moderate":
                sleep_hours = round(float(np.random.uniform(6.0, 7.5)), 1)
                efficiency = round(float(np.random.uniform(75, 88)), 1)
                awakenings = int(np.random.randint(1, 3))
            else:
                sleep_hours = round(float(np.random.uniform(7.0, 9.0)), 1)
                efficiency = round(float(np.random.uniform(85, 97)), 1)
                awakenings = int(np.random.randint(0, 2))

            sleep_data.append({
                "athlete_id": athlete["athlete_id"],
                "date": date_str,
                "total_sleep_hours": sleep_hours,
                "deep_sleep_pct": round(float(np.random.uniform(15, 30)), 1),
                "rem_sleep_pct": round(float(np.random.uniform(15, 25)), 1),
                "awakenings": awakenings,
                "sleep_efficiency": efficiency,
            })

    # ---- Injury logs ----
    injury_data = []
    injury_id = 1
    for ath_idx, athlete in enumerate(athletes):
        profile = risk_profiles[ath_idx]
        if profile == "critical":
            num_injuries = int(np.random.randint(2, 5))
        elif profile == "high":
            num_injuries = int(np.random.randint(1, 3))
        elif profile == "moderate":
            num_injuries = int(np.random.randint(0, 2))
        else:
            num_injuries = int(np.random.choice([0, 0, 0, 1]))

        for _ in range(num_injuries):
            days_ago = int(np.random.randint(1, 91))
            injury_date = END_DATE - timedelta(days=days_ago)
            severity = int(np.random.randint(1, 6))
            if profile in ["critical", "high"]:
                severity = max(severity, int(np.random.randint(3, 6)))

            injury_data.append({
                "injury_id": injury_id,
                "athlete_id": athlete["athlete_id"],
                "injury_date": injury_date.strftime("%Y-%m-%d"),
                "injury_type": str(np.random.choice(INJURY_TYPES)),
                "severity": severity,
                "days_missed": int(severity * int(np.random.randint(2, 8))),
                "body_region": str(np.random.choice(BODY_REGIONS)),
                "is_recurring": int(np.random.random() < 0.3),
            })
            injury_id += 1

    # Pad injury_logs to meet minimum row count
    while len(injury_data) < SCALE["rows_per_table"]:
        ath_id = int(np.random.randint(1, num_athletes + 1))
        days_ago = int(np.random.randint(1, 91))
        injury_date = END_DATE - timedelta(days=days_ago)
        severity = int(np.random.randint(1, 4))
        injury_data.append({
            "injury_id": injury_id,
            "athlete_id": ath_id,
            "injury_date": injury_date.strftime("%Y-%m-%d"),
            "injury_type": str(np.random.choice(INJURY_TYPES)),
            "severity": severity,
            "days_missed": int(severity * int(np.random.randint(2, 8))),
            "body_region": str(np.random.choice(BODY_REGIONS)),
            "is_recurring": int(np.random.random() < 0.3),
        })
        injury_id += 1

    # ===================== DATABASE =====================
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE athletes (
            athlete_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER,
            position TEXT
        )
    """)
    for a in athletes:
        c.execute("INSERT INTO athletes VALUES (?, ?, ?, ?)",
                  (a["athlete_id"], a["name"], a["age"], a["position"]))

    c.execute("""
        CREATE TABLE wellness_surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER,
            date TEXT,
            fatigue_rating REAL,
            mood_rating REAL,
            soreness_rating REAL,
            stress_rating REAL,
            sleep_quality_rating REAL,
            FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
        )
    """)
    for w in wellness_data:
        c.execute(
            "INSERT INTO wellness_surveys (athlete_id, date, fatigue_rating, mood_rating, "
            "soreness_rating, stress_rating, sleep_quality_rating) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (w["athlete_id"], w["date"], w["fatigue_rating"], w["mood_rating"],
             w["soreness_rating"], w["stress_rating"], w["sleep_quality_rating"]))

    c.execute("""
        CREATE TABLE gps_training_load (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER,
            date TEXT,
            total_distance_m REAL,
            high_speed_distance_m REAL,
            sprint_count INTEGER,
            duration_min REAL,
            player_load REAL,
            FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
        )
    """)
    for g in gps_data:
        c.execute(
            "INSERT INTO gps_training_load (athlete_id, date, total_distance_m, "
            "high_speed_distance_m, sprint_count, duration_min, player_load) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g["athlete_id"], g["date"], g["total_distance_m"], g["high_speed_distance_m"],
             g["sprint_count"], g["duration_min"], g["player_load"]))

    c.execute("""
        CREATE TABLE sleep_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER,
            date TEXT,
            total_sleep_hours REAL,
            deep_sleep_pct REAL,
            rem_sleep_pct REAL,
            awakenings INTEGER,
            sleep_efficiency REAL,
            FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
        )
    """)
    for s in sleep_data:
        c.execute(
            "INSERT INTO sleep_tracker (athlete_id, date, total_sleep_hours, deep_sleep_pct, "
            "rem_sleep_pct, awakenings, sleep_efficiency) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (s["athlete_id"], s["date"], s["total_sleep_hours"], s["deep_sleep_pct"],
             s["rem_sleep_pct"], s["awakenings"], s["sleep_efficiency"]))

    c.execute("""
        CREATE TABLE injury_logs (
            injury_id INTEGER PRIMARY KEY,
            athlete_id INTEGER,
            injury_date TEXT,
            injury_type TEXT,
            severity INTEGER,
            days_missed INTEGER,
            body_region TEXT,
            is_recurring INTEGER,
            FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
        )
    """)
    for inj in injury_data:
        c.execute("INSERT INTO injury_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (inj["injury_id"], inj["athlete_id"], inj["injury_date"],
                   inj["injury_type"], inj["severity"], inj["days_missed"],
                   inj["body_region"], inj["is_recurring"]))

    conn.commit()
    conn.close()

    # ===================== WORKSPACE FILES =====================

    # ---- Fixed config files (not counted in SCALE) ----

    # Team roster CSV
    with open(os.path.join(args.workspace, "team_roster.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["athlete_id", "team", "jersey_number", "contract_status"])
        for td in team_data:
            writer.writerow([td["athlete_id"], td["team"],
                             td["jersey_number"], td["contract_status"]])

    # Risk thresholds YAML
    with open(os.path.join(args.workspace, "risk_thresholds.yaml"), "w") as f:
        yaml.dump(RISK_THRESHOLDS_CONFIG, f, default_flow_style=False, sort_keys=False)

    # Fatigue weights JSON
    with open(os.path.join(args.workspace, "fatigue_weights.json"), "w") as f:
        json.dump(FATIGUE_WEIGHTS, f, indent=2)

    # Body region multipliers CSV
    with open(os.path.join(args.workspace, "body_region_multipliers.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["body_region", "multiplier"])
        for region, mult in BODY_REGION_MULTIPLIERS.items():
            writer.writerow([region, mult])

    # Rest protocols MD
    protocols_content = """# Rest Protocol Definitions

## Protocol_A - Complete Rest
Assigned to athletes classified as critical risk. The athlete must cease all training activities for a minimum of 5 consecutive days. Only light walking and stretching are permitted. A follow-up wellness assessment is required before any return to training.

## Protocol_B - Active Recovery Only
Assigned to athletes classified as high risk. Training intensity must be reduced to no more than 40% of normal load. Sessions are limited to low-impact recovery exercises, swimming, or yoga. Duration must not exceed 30 minutes per session. Reassessment after 3 days.

## Protocol_C - Reduced Load
Assigned to athletes classified as moderate risk. Training volume should be reduced by 25% from the current weekly plan. High-intensity sessions are replaced with moderate-intensity alternatives. No match participation for 2 days. Monitor wellness scores daily.
"""
    with open(os.path.join(args.workspace, "rest_protocols.md"), "w") as f:
        f.write(protocols_content)

    # ---- Scalable data files: one training-session CSV per day ----
    for day_idx, date in enumerate(dates):
        date_str = date.strftime("%Y-%m-%d")
        filename = f"training_session_{date_str}.csv"
        recency = day_idx / max(num_days - 1, 1)

        with open(os.path.join(args.workspace, filename), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["athlete_id", "session_type", "rpe_score",
                             "session_duration_min", "recovery_hours"])
            for ath_idx, athlete in enumerate(athletes):
                profile = risk_profiles[ath_idx]

                num_sessions = 1
                if profile in ["critical", "high"] and np.random.random() < 0.3:
                    num_sessions = 2

                for _ in range(num_sessions):
                    if profile == "critical":
                        base_rpe = 7.0 + recency * 2.0
                        rpe = round(float(np.clip(
                            base_rpe + np.random.normal(0, 0.5), 1, 10)), 1)
                        duration = int(np.random.randint(80, 121))
                        recovery = round(float(np.random.uniform(12, 24)), 1)
                    elif profile == "high":
                        base_rpe = 6.0 + recency * 1.5
                        rpe = round(float(np.clip(
                            base_rpe + np.random.normal(0, 0.5), 1, 10)), 1)
                        duration = int(np.random.randint(70, 111))
                        recovery = round(float(np.random.uniform(16, 36)), 1)
                    elif profile == "moderate":
                        rpe = round(float(np.clip(
                            np.random.uniform(4, 7) + np.random.normal(0, 0.3),
                            1, 10)), 1)
                        duration = int(np.random.randint(60, 91))
                        recovery = round(float(np.random.uniform(24, 48)), 1)
                    else:
                        rpe = round(float(np.clip(
                            np.random.uniform(3, 5.5) + np.random.normal(0, 0.3),
                            1, 10)), 1)
                        duration = int(np.random.randint(50, 81))
                        recovery = round(float(np.random.uniform(36, 60)), 1)

                    session_type = str(np.random.choice(SESSION_TYPES))
                    writer.writerow([athlete["athlete_id"], session_type,
                                     rpe, duration, recovery])


if __name__ == "__main__":
    main()
