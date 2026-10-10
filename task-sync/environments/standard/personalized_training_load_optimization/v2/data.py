import os
import argparse
import sqlite3
import json
import random
import math
import yaml
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 80,
    "num_workspace_files": 30,
}

# ---------------------------------------------------------------------------
# Seed everything
# ---------------------------------------------------------------------------
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
TARGET_WEEK_START = "2025-03-10"  # Monday of the scheduling week
GPS_PERIOD_DAYS = 28  # 4 weeks of historical GPS data

SPORTS = ["soccer", "basketball", "track_and_field", "rugby", "swimming"]
POSITIONS = {
    "soccer": ["goalkeeper", "defender", "midfielder", "forward"],
    "basketball": ["point_guard", "shooting_guard", "small_forward", "power_forward", "center"],
    "track_and_field": ["sprinter", "distance_runner", "jumper", "thrower"],
    "rugby": ["prop", "hooker", "lock", "flanker", "scrum_half", "fly_half", "wing", "fullback"],
    "swimming": ["freestyle", "backstroke", "breaststroke", "butterfly"],
}
BODY_REGIONS = [
    "knee", "ankle", "hamstring", "lower_back", "shoulder",
    "hip", "groin", "calf", "quadriceps", "wrist",
]
SESSION_TYPES = [
    "field_session", "gym_session", "match", "recovery_run",
    "skills_session", "conditioning",
]
CLASS_SLOTS = [
    ("08:00", "09:30"), ("09:30", "11:00"), ("10:00", "11:30"),
    ("11:00", "12:30"), ("13:00", "14:30"), ("14:00", "15:30"),
    ("15:00", "16:30"), ("16:00", "17:30"),
]
TRAINING_WINDOWS = [
    ("06:00", "08:00"), ("10:00", "12:00"),
    ("14:00", "16:00"), ("18:00", "20:00"),
]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
COURSE_NAMES = [
    "Biomechanics", "Sports Psychology", "Anatomy & Physiology",
    "Nutrition Science", "Exercise Physiology", "Statistics",
    "Research Methods", "Motor Learning", "Sports Management",
    "Kinesiology", "Rehabilitation Science", "Health Promotion",
    "Strength & Conditioning Theory", "Performance Analysis",
    "Sports Sociology", "Athletic Training", "Public Health",
    "Organic Chemistry", "Cell Biology", "Physics",
]

# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS athletes (
    athlete_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    age INTEGER NOT NULL,
    sport TEXT NOT NULL,
    position TEXT NOT NULL,
    team TEXT NOT NULL,
    academic_year TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gps_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id INTEGER NOT NULL,
    session_date TEXT NOT NULL,
    session_type TEXT NOT NULL,
    total_distance_m REAL NOT NULL,
    high_speed_running_m REAL NOT NULL,
    sprint_count INTEGER NOT NULL,
    accelerations INTEGER NOT NULL,
    decelerations INTEGER NOT NULL,
    max_speed_kmh REAL NOT NULL,
    duration_min INTEGER NOT NULL,
    player_load REAL NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE TABLE IF NOT EXISTS wellness_surveys (
    survey_id INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id INTEGER NOT NULL,
    survey_date TEXT NOT NULL,
    sleep_hours REAL NOT NULL,
    sleep_quality INTEGER NOT NULL,
    fatigue INTEGER NOT NULL,
    soreness INTEGER NOT NULL,
    stress INTEGER NOT NULL,
    mood INTEGER NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE TABLE IF NOT EXISTS msk_screenings (
    screening_id INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id INTEGER NOT NULL,
    screening_date TEXT NOT NULL,
    body_region TEXT NOT NULL,
    rom_score REAL NOT NULL,
    strength_score REAL NOT NULL,
    asymmetry_pct REAL NOT NULL,
    pain_level INTEGER NOT NULL,
    risk_category TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE TABLE IF NOT EXISTS academic_timetable (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id INTEGER NOT NULL,
    day_of_week TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    course_name TEXT NOT NULL,
    is_mandatory INTEGER NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);
"""


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------

def generate_athletes(n):
    rows = []
    teams = [f"Team {chr(65 + i)}" for i in range(5)]
    years = ["Freshman", "Sophomore", "Junior", "Senior"]
    for i in range(1, n + 1):
        sport = random.choice(SPORTS)
        rows.append({
            "athlete_id": i,
            "name": fake.name(),
            "age": random.randint(18, 24),
            "sport": sport,
            "position": random.choice(POSITIONS[sport]),
            "team": random.choice(teams),
            "academic_year": random.choice(years),
        })
    return rows


def generate_gps_sessions(athletes, min_rows):
    """Generate GPS sessions for 28 days before target week."""
    start = datetime.strptime(TARGET_WEEK_START, "%Y-%m-%d") - timedelta(days=GPS_PERIOD_DAYS)
    rows = []
    for ath in athletes:
        aid = ath["athlete_id"]
        sport = ath["sport"]
        for week_offset in range(4):
            week_start = start + timedelta(days=week_offset * 7)
            n_sessions = random.randint(4, 6)
            session_days = sorted(random.sample(range(7), n_sessions))
            for d in session_days:
                sess_date = (week_start + timedelta(days=d)).strftime("%Y-%m-%d")
                st = random.choice(SESSION_TYPES)
                base_dist = {"soccer": 7000, "basketball": 5000, "track_and_field": 6000,
                             "rugby": 7500, "swimming": 3000}[sport]
                total_dist = round(np.random.normal(base_dist, base_dist * 0.2), 1)
                total_dist = max(1000, total_dist)
                hsr = round(total_dist * np.random.uniform(0.1, 0.3), 1)
                sprints = max(0, int(np.random.normal(8, 4)))
                accels = max(0, int(np.random.normal(15, 6)))
                decels = max(0, int(np.random.normal(12, 5)))
                max_spd = round(np.random.uniform(22, 34), 1)
                dur = random.randint(40, 100)
                pl = round(total_dist / 1000 * 0.5 + hsr / 1000 * 1.5 + sprints * 0.8
                           + accels * 0.3 + decels * 0.2 + dur * 0.05, 2)
                rows.append({
                    "athlete_id": aid,
                    "session_date": sess_date,
                    "session_type": st,
                    "total_distance_m": total_dist,
                    "high_speed_running_m": hsr,
                    "sprint_count": sprints,
                    "accelerations": accels,
                    "decelerations": decels,
                    "max_speed_kmh": max_spd,
                    "duration_min": dur,
                    "player_load": pl,
                })
    while len(rows) < min_rows:
        ath = random.choice(athletes)
        rows.append({
            "athlete_id": ath["athlete_id"],
            "session_date": (start + timedelta(days=random.randint(0, 27))).strftime("%Y-%m-%d"),
            "session_type": random.choice(SESSION_TYPES),
            "total_distance_m": round(np.random.normal(5000, 1000), 1),
            "high_speed_running_m": round(np.random.normal(1000, 300), 1),
            "sprint_count": max(0, int(np.random.normal(6, 3))),
            "accelerations": max(0, int(np.random.normal(12, 4))),
            "decelerations": max(0, int(np.random.normal(10, 4))),
            "max_speed_kmh": round(np.random.uniform(22, 32), 1),
            "duration_min": random.randint(40, 90),
            "player_load": round(np.random.uniform(8, 25), 2),
        })
    return rows


def generate_wellness_surveys(athletes, min_rows):
    """Generate weekly wellness surveys for the past 4 weeks."""
    target = datetime.strptime(TARGET_WEEK_START, "%Y-%m-%d")
    rows = []
    for ath in athletes:
        aid = ath["athlete_id"]
        for w in range(4):
            survey_date = (target - timedelta(days=7 * (w + 1))).strftime("%Y-%m-%d")
            fatigue_base = random.choice([3, 4, 5, 6, 7, 8])
            rows.append({
                "athlete_id": aid,
                "survey_date": survey_date,
                "sleep_hours": round(np.random.uniform(5, 9), 1),
                "sleep_quality": random.randint(2, 9),
                "fatigue": min(10, max(1, int(np.random.normal(fatigue_base, 1.5)))),
                "soreness": min(10, max(1, int(np.random.normal(fatigue_base - 0.5, 1.8)))),
                "stress": min(10, max(1, int(np.random.normal(5, 2)))),
                "mood": min(10, max(1, int(np.random.normal(6, 1.5)))),
            })
    while len(rows) < min_rows:
        ath = random.choice(athletes)
        rows.append({
            "athlete_id": ath["athlete_id"],
            "survey_date": (target - timedelta(days=random.randint(7, 28))).strftime("%Y-%m-%d"),
            "sleep_hours": round(np.random.uniform(5, 9), 1),
            "sleep_quality": random.randint(2, 9),
            "fatigue": random.randint(1, 10),
            "soreness": random.randint(1, 10),
            "stress": random.randint(1, 10),
            "mood": random.randint(1, 10),
        })
    return rows


def generate_msk_screenings(athletes, min_rows):
    """Generate musculoskeletal screening results."""
    target = datetime.strptime(TARGET_WEEK_START, "%Y-%m-%d")
    rows = []
    for ath in athletes:
        aid = ath["athlete_id"]
        n_screenings = random.randint(2, 4)
        regions = random.sample(BODY_REGIONS, min(n_screenings, len(BODY_REGIONS)))
        for region in regions:
            scr_date = (target - timedelta(days=random.randint(3, 30))).strftime("%Y-%m-%d")
            pain = max(0, min(10, int(np.random.exponential(2.5))))
            asym = round(max(0, np.random.exponential(6)), 1)
            if pain >= 6 or (asym >= 15 and region in ["knee", "ankle", "hamstring", "lower_back"]):
                risk_cat = "high"
            elif pain >= 4 or asym >= 10:
                risk_cat = "moderate"
            else:
                risk_cat = "low"
            rows.append({
                "athlete_id": aid,
                "screening_date": scr_date,
                "body_region": region,
                "rom_score": round(np.random.uniform(60, 100), 1),
                "strength_score": round(np.random.uniform(50, 100), 1),
                "asymmetry_pct": asym,
                "pain_level": pain,
                "risk_category": risk_cat,
            })
    while len(rows) < min_rows:
        ath = random.choice(athletes)
        region = random.choice(BODY_REGIONS)
        pain = max(0, min(10, int(np.random.exponential(2))))
        asym = round(max(0, np.random.exponential(5)), 1)
        risk_cat = "high" if pain >= 6 else ("moderate" if pain >= 4 or asym >= 10 else "low")
        rows.append({
            "athlete_id": ath["athlete_id"],
            "screening_date": (target - timedelta(days=random.randint(3, 30))).strftime("%Y-%m-%d"),
            "body_region": region,
            "rom_score": round(np.random.uniform(60, 100), 1),
            "strength_score": round(np.random.uniform(50, 100), 1),
            "asymmetry_pct": asym,
            "pain_level": pain,
            "risk_category": risk_cat,
        })
    return rows


def generate_academic_timetable(athletes, min_rows):
    """Generate academic class schedules for each athlete."""
    rows = []
    for ath in athletes:
        aid = ath["athlete_id"]
        n_classes = random.randint(3, 6)
        used = set()
        for _ in range(n_classes):
            day = random.choice(WEEKDAYS)
            slot = random.choice(CLASS_SLOTS)
            key = (day, slot[0])
            if key in used:
                continue
            used.add(key)
            rows.append({
                "athlete_id": aid,
                "day_of_week": day,
                "start_time": slot[0],
                "end_time": slot[1],
                "course_name": random.choice(COURSE_NAMES),
                "is_mandatory": 1 if random.random() < 0.7 else 0,
            })
    while len(rows) < min_rows:
        ath = random.choice(athletes)
        day = random.choice(WEEKDAYS)
        slot = random.choice(CLASS_SLOTS)
        rows.append({
            "athlete_id": ath["athlete_id"],
            "day_of_week": day,
            "start_time": slot[0],
            "end_time": slot[1],
            "course_name": random.choice(COURSE_NAMES),
            "is_mandatory": 1 if random.random() < 0.7 else 0,
        })
    return rows


# ---------------------------------------------------------------------------
# Workspace file generators
# ---------------------------------------------------------------------------

def write_training_zones(workspace):
    data = {
        "zones": {
            "recovery": {"intensity_range": [0.0, 0.5], "description": "Active recovery and regeneration"},
            "low": {"intensity_range": [0.5, 0.65], "description": "Aerobic base building"},
            "moderate": {"intensity_range": [0.65, 0.8], "description": "Tempo and threshold work"},
            "high": {"intensity_range": [0.8, 0.9], "description": "High-intensity intervals"},
            "maximal": {"intensity_range": [0.9, 1.0], "description": "Sprint and power work"},
        },
        "load_multipliers": {
            "recovery": 0.3,
            "low": 0.5,
            "moderate": 0.75,
            "high": 1.0,
            "maximal": 1.2,
        },
    }
    with open(os.path.join(workspace, "training_zones.yaml"), "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def write_risk_thresholds(workspace):
    data = {
        "acwr": {
            "low_risk": [0.8, 1.3],
            "moderate_risk_low": [0.6, 0.8],
            "moderate_risk_high": [1.3, 1.5],
            "high_risk_low": [0.0, 0.6],
            "high_risk_high": [1.5, 100.0],
        },
        "wellness": {
            "fatigue_threshold": 7,
            "soreness_threshold": 7,
            "sleep_quality_threshold": 3,
            "composite_risk_threshold": 18,
        },
        "msk": {
            "high_risk_pain_level": 6,
            "asymmetry_threshold": 15,
            "critical_regions": ["knee", "ankle", "hamstring", "lower_back"],
        },
        "rpe": {
            "moderate_threshold": 7.5,
            "high_threshold": 8.5,
        },
    }
    with open(os.path.join(workspace, "risk_thresholds.json"), "w") as f:
        json.dump(data, f, indent=2)


def write_load_management_policy(workspace):
    data = {
        "weekly_constraints": {
            "max_sessions_per_week": 6,
            "min_rest_days": 1,
            "max_high_intensity_sessions": 2,
            "max_consecutive_training_days": 3,
        },
        "risk_adjustments": {
            "high": {
                "max_intensity": "moderate",
                "max_sessions": 4,
                "mandatory_rest_days": 2,
                "exclude_session_types": ["maximal_sprint", "plyometric"],
            },
            "moderate": {
                "max_intensity": "high",
                "max_sessions": 5,
                "mandatory_rest_days": 1,
                "exclude_session_types": ["maximal_sprint"],
            },
            "low": {
                "max_intensity": "maximal",
                "max_sessions": 6,
                "mandatory_rest_days": 1,
                "exclude_session_types": [],
            },
        },
    }
    with open(os.path.join(workspace, "load_management_policy.yaml"), "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def write_session_templates(workspace):
    data = [
        {"session_type": "endurance_run", "default_duration": 60, "intensity": "moderate", "focus": "cardiovascular"},
        {"session_type": "interval_training", "default_duration": 45, "intensity": "high", "focus": "speed_endurance"},
        {"session_type": "strength_training", "default_duration": 50, "intensity": "moderate", "focus": "strength"},
        {"session_type": "recovery_session", "default_duration": 30, "intensity": "recovery", "focus": "regeneration"},
        {"session_type": "skill_practice", "default_duration": 60, "intensity": "low", "focus": "technique"},
        {"session_type": "plyometric", "default_duration": 40, "intensity": "high", "focus": "power"},
        {"session_type": "maximal_sprint", "default_duration": 35, "intensity": "maximal", "focus": "speed"},
        {"session_type": "flexibility_mobility", "default_duration": 30, "intensity": "recovery", "focus": "mobility"},
    ]
    with open(os.path.join(workspace, "session_templates.json"), "w") as f:
        json.dump(data, f, indent=2)


def write_scheduling_rules(workspace):
    content = """TRAINING SCHEDULING RULES
=========================

Available training windows (each session occupies exactly one window):
  Window 1: 06:00 - 08:00
  Window 2: 10:00 - 12:00
  Window 3: 14:00 - 16:00
  Window 4: 18:00 - 20:00

Conflict policy:
  Sessions must not overlap with mandatory academic commitments.
  A training window is blocked if any mandatory class overlaps with it
  (class_start < window_end AND class_end > window_start).

Session placement rules:
  At most one session per training window per athlete.
  At most two sessions per day per athlete.
  No more than max_consecutive_training_days consecutive training days
  (as defined in load_management_policy.yaml).

Rest day rules:
  Every athlete must have at least the number of rest days specified by
  their risk level in load_management_policy.yaml.
  A rest day is a day with zero scheduled sessions.

Intensity sequencing:
  A high-intensity session must not be immediately followed by another
  high-intensity session on the next calendar day. Insert at least one
  low, recovery, or rest day between high-intensity days.

Priority for assigning session types (descending):
  1. recovery_session / flexibility_mobility (if athlete is high-risk)
  2. skill_practice
  3. strength_training / endurance_run
  4. interval_training / plyometric
  5. maximal_sprint

Default preferences (when no athlete report file exists):
  Use any available window; no time-of-day preference.
  Session type selection follows the priority list above filtered by
  risk-level constraints.
"""
    with open(os.path.join(workspace, "scheduling_rules.txt"), "w") as f:
        f.write(content)


def write_historical_baselines(workspace, athletes):
    """CSV with sport/position baseline loads - fixed reference file."""
    rows = []
    for sport in SPORTS:
        for pos in POSITIONS[sport]:
            rows.append({
                "sport": sport,
                "position": pos,
                "baseline_weekly_player_load": round(np.random.uniform(50, 120), 1),
                "baseline_weekly_distance_m": round(np.random.uniform(20000, 50000), 0),
                "typical_sessions_per_week": random.randint(4, 6),
            })
    pd.DataFrame(rows).to_csv(
        os.path.join(workspace, "historical_baselines.csv"), index=False
    )


def write_athlete_reports(workspace, athletes, gps_rows):
    """Scalable workspace files: one JSON report per athlete (first N athletes)."""
    n_files = SCALE["num_workspace_files"]
    target = datetime.strptime(TARGET_WEEK_START, "%Y-%m-%d")
    gps_by_athlete = {}
    for g in gps_rows:
        gps_by_athlete.setdefault(g["athlete_id"], []).append(g)

    selected = athletes[:n_files]
    for ath in selected:
        aid = ath["athlete_id"]
        sessions = gps_by_athlete.get(aid, [])
        recent = [s for s in sessions
                  if (target - datetime.strptime(s["session_date"], "%Y-%m-%d")).days <= 7]
        rpe_history = []
        for s in sorted(recent, key=lambda x: x["session_date"]):
            rpe = min(10.0, max(1.0, round(s["player_load"] / 3 + np.random.normal(0, 0.8), 1)))
            rpe_history.append({"date": s["session_date"], "rpe": float(rpe)})

        n_pref = random.randint(1, 2)
        prefs = random.sample(TRAINING_WINDOWS, n_pref)
        pref_strs = [f"{p[0]}-{p[1]}" for p in prefs]

        injury_notes_options = [
            "", "", "",
            "mild tightness in left hamstring",
            "recovering from ankle sprain, cleared for modified activity",
            "intermittent knee discomfort during cutting movements",
            "lower back stiffness after prolonged sitting",
            "slight groin strain, monitor closely",
        ]

        phases = ["pre-season", "in-season", "competition", "transition"]

        report = {
            "athlete_id": aid,
            "athlete_name": ath["name"],
            "report_date": (target - timedelta(days=1)).strftime("%Y-%m-%d"),
            "rpe_7day_avg": round(float(np.mean([r["rpe"] for r in rpe_history])), 2) if rpe_history else None,
            "rpe_history": rpe_history,
            "preferred_training_windows": pref_strs,
            "injury_notes": random.choice(injury_notes_options),
            "training_phase": random.choice(phases),
        }
        fname = f"athlete_report_{aid}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(report, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()
    cur.executescript(CREATE_TABLES_SQL)

    n_athletes = SCALE["rows_per_table"]
    athletes = generate_athletes(n_athletes)
    for a in athletes:
        cur.execute(
            "INSERT INTO athletes VALUES (?,?,?,?,?,?,?)",
            (a["athlete_id"], a["name"], a["age"], a["sport"],
             a["position"], a["team"], a["academic_year"]),
        )

    gps_rows = generate_gps_sessions(athletes, SCALE["rows_per_table"])
    for g in gps_rows:
        cur.execute(
            "INSERT INTO gps_sessions (athlete_id, session_date, session_type, "
            "total_distance_m, high_speed_running_m, sprint_count, accelerations, "
            "decelerations, max_speed_kmh, duration_min, player_load) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (g["athlete_id"], g["session_date"], g["session_type"],
             g["total_distance_m"], g["high_speed_running_m"], g["sprint_count"],
             g["accelerations"], g["decelerations"], g["max_speed_kmh"],
             g["duration_min"], g["player_load"]),
        )

    wellness_rows = generate_wellness_surveys(athletes, SCALE["rows_per_table"])
    for w in wellness_rows:
        cur.execute(
            "INSERT INTO wellness_surveys (athlete_id, survey_date, sleep_hours, "
            "sleep_quality, fatigue, soreness, stress, mood) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (w["athlete_id"], w["survey_date"], w["sleep_hours"],
             w["sleep_quality"], w["fatigue"], w["soreness"],
             w["stress"], w["mood"]),
        )

    msk_rows = generate_msk_screenings(athletes, SCALE["rows_per_table"])
    for m in msk_rows:
        cur.execute(
            "INSERT INTO msk_screenings (athlete_id, screening_date, body_region, "
            "rom_score, strength_score, asymmetry_pct, pain_level, risk_category) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (m["athlete_id"], m["screening_date"], m["body_region"],
             m["rom_score"], m["strength_score"], m["asymmetry_pct"],
             m["pain_level"], m["risk_category"]),
        )

    acad_rows = generate_academic_timetable(athletes, SCALE["rows_per_table"])
    for t in acad_rows:
        cur.execute(
            "INSERT INTO academic_timetable (athlete_id, day_of_week, start_time, "
            "end_time, course_name, is_mandatory) "
            "VALUES (?,?,?,?,?,?)",
            (t["athlete_id"], t["day_of_week"], t["start_time"],
             t["end_time"], t["course_name"], t["is_mandatory"]),
        )

    conn.commit()
    conn.close()

    # ---- Workspace: fixed config files ----
    write_training_zones(args.workspace)
    write_risk_thresholds(args.workspace)
    write_load_management_policy(args.workspace)
    write_session_templates(args.workspace)
    write_scheduling_rules(args.workspace)
    write_historical_baselines(args.workspace, athletes)

    # ---- Workspace: scalable athlete report files ----
    write_athlete_reports(args.workspace, athletes, gps_rows)

    print(f"Database created at {args.db_path}")
    print(f"Workspace populated at {args.workspace} "
          f"({SCALE['num_workspace_files']} athlete reports + 6 config files)")


if __name__ == "__main__":
    main()
