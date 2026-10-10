"""
Data generation for Cattle Respiratory Outbreak Risk Watchlist task.
Generates a SQLite database and workspace files for the agent.
"""
import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Scale parameters (v0 base) ──────────────────────────────────────────
SCALE = {
    "rows_per_table": 640,      # v3 = 8× base
    "num_workspace_files": 40,  # v3 = base + 3N (10 + 30)
}

# ── Deterministic seeds ─────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Domain constants ────────────────────────────────────────────────────
TODAY = datetime(2026, 4, 22)
BREEDS = ["Angus", "Hereford", "Charolais", "Simmental", "Brahman",
          "Limousin", "Shorthorn", "Red Angus", "Gelbvieh", "Beefmaster"]
VACCINES = ["Mannheimia haemolytica", "Pasteurella multocida",
            "IBR", "BVD", "BRSV", "PI3"]
DIAGNOSES_RESPIRATORY = [
    "bovine respiratory disease", "pneumonia", "shipping fever",
    "upper respiratory infection", "pleuritis"
]
DIAGNOSES_OTHER = [
    "foot rot", "bloat", "pinkeye", "coccidiosis",
    "anaplasmosis", "hardware disease", "acidosis"
]
MEDICATIONS_RESP = ["Draxxin", "Excede", "Nuflor", "Baytril", "Zuprevo"]
MEDICATIONS_OTHER = ["Penicillin", "Tetracycline", "Dexamethasone",
                     "Thiamine", "Ivermectin"]
MOVE_REASONS = ["arrival", "pen rotation", "weight sorting",
                "treatment isolation", "regroup"]
VET_IDS = [f"VET-{i:03d}" for i in range(1, 11)]


def create_tables(conn: sqlite3.Connection):
    """Create all database tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cattle (
            cattle_id INTEGER PRIMARY KEY,
            tag_number TEXT UNIQUE NOT NULL,
            breed TEXT NOT NULL,
            age_months INTEGER NOT NULL,
            weight_kg REAL NOT NULL,
            current_pen_id TEXT NOT NULL,
            arrival_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS vaccinations (
            vax_id INTEGER PRIMARY KEY,
            cattle_id INTEGER NOT NULL,
            vaccine_name TEXT NOT NULL,
            administered_date TEXT NOT NULL,
            batch_number TEXT NOT NULL,
            FOREIGN KEY (cattle_id) REFERENCES cattle(cattle_id)
        );

        CREATE TABLE IF NOT EXISTS sensor_readings (
            reading_id INTEGER PRIMARY KEY,
            barn_id TEXT NOT NULL,
            reading_date TEXT NOT NULL,
            reading_hour INTEGER NOT NULL,
            temperature_f REAL NOT NULL,
            humidity_pct REAL NOT NULL,
            ammonia_ppm REAL NOT NULL,
            airflow_cfm REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS movement_logs (
            move_id INTEGER PRIMARY KEY,
            cattle_id INTEGER NOT NULL,
            from_pen_id TEXT NOT NULL,
            to_pen_id TEXT NOT NULL,
            move_date TEXT NOT NULL,
            move_reason TEXT NOT NULL,
            FOREIGN KEY (cattle_id) REFERENCES cattle(cattle_id)
        );

        CREATE TABLE IF NOT EXISTS treatments (
            treatment_id INTEGER PRIMARY KEY,
            cattle_id INTEGER NOT NULL,
            diagnosis TEXT NOT NULL,
            medication TEXT NOT NULL,
            treatment_date TEXT NOT NULL,
            vet_id TEXT NOT NULL,
            follow_up_needed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (cattle_id) REFERENCES cattle(cattle_id)
        );
    """)
    conn.commit()


def _gen_barns_and_pens(n_cattle: int):
    """Determine barn/pen layout based on cattle count."""
    n_pens = max(6, n_cattle // 10)
    n_barns = max(3, n_pens // 3)
    barns = [f"BARN-{chr(65 + i)}" for i in range(n_barns)]
    pens = []
    for i in range(n_pens):
        barn = barns[i % n_barns]
        pens.append((f"PEN-{i+1:03d}", barn))
    return barns, pens


def generate_cattle(conn: sqlite3.Connection, n: int, pens):
    """Generate cattle records."""
    rows = []
    for i in range(1, n + 1):
        tag = f"TAG-{i:05d}"
        breed = random.choice(BREEDS)
        age = random.randint(6, 60)
        weight = round(random.uniform(200, 700), 1)
        pen_id = random.choice(pens)[0]
        days_back = random.randint(1, 180)
        arrival = (TODAY - timedelta(days=days_back)).strftime("%Y-%m-%d")
        status = "active"
        rows.append((i, tag, breed, age, weight, pen_id, arrival, status))
    conn.executemany(
        "INSERT INTO cattle VALUES (?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_vaccinations(conn: sqlite3.Connection, n_cattle: int, n_rows: int):
    """Generate vaccination records.  Each animal gets 0-4 vaccines."""
    rows = []
    vax_id = 1
    cattle_ids = list(range(1, n_cattle + 1))
    random.shuffle(cattle_ids)
    # ensure we produce at least n_rows records
    while len(rows) < n_rows:
        for cid in cattle_ids:
            n_vax = random.randint(0, 4)
            for _ in range(n_vax):
                vaccine = random.choice(VACCINES)
                days_ago = random.randint(7, 365)
                date_str = (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                batch = f"BATCH-{random.randint(1000, 9999)}"
                rows.append((vax_id, cid, vaccine, date_str, batch))
                vax_id += 1
            if len(rows) >= n_rows:
                break
    rows = rows[:n_rows]
    conn.executemany("INSERT INTO vaccinations VALUES (?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_sensor_readings(conn: sqlite3.Connection, barns, n_rows: int):
    """Generate hourly sensor readings for last 7 days across all barns."""
    rows = []
    reading_id = 1
    # distribute readings across barns and dates
    dates = [(TODAY - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(7)]
    hours = list(range(0, 24))
    while len(rows) < n_rows:
        for barn_id in barns:
            for date_str in dates:
                for hour in hours:
                    # base environmental values
                    temp = round(random.gauss(68, 12), 1)
                    humidity = round(random.gauss(55, 18), 1)
                    humidity = max(10, min(99, humidity))
                    ammonia = round(random.gauss(12, 8), 1)
                    ammonia = max(0, ammonia)
                    airflow = round(random.gauss(800, 250), 0)
                    airflow = max(100, airflow)
                    rows.append((reading_id, barn_id, date_str, hour,
                                 temp, humidity, ammonia, airflow))
                    reading_id += 1
                    if len(rows) >= n_rows:
                        break
                if len(rows) >= n_rows:
                    break
            if len(rows) >= n_rows:
                break
        if len(rows) < n_rows:
            break  # all combos exhausted
    rows = rows[:n_rows]
    conn.executemany("INSERT INTO sensor_readings VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_movements(conn: sqlite3.Connection, n_cattle: int, pens, n_rows: int):
    """Generate movement logs."""
    rows = []
    move_id = 1
    pen_ids = [p[0] for p in pens]
    while len(rows) < n_rows:
        for cid in range(1, n_cattle + 1):
            n_moves = random.randint(0, 3)
            for _ in range(n_moves):
                from_pen = random.choice(pen_ids)
                to_pen = random.choice([p for p in pen_ids if p != from_pen])
                days_ago = random.randint(1, 90)
                date_str = (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                reason = random.choice(MOVE_REASONS)
                rows.append((move_id, cid, from_pen, to_pen, date_str, reason))
                move_id += 1
            if len(rows) >= n_rows:
                break
    rows = rows[:n_rows]
    conn.executemany("INSERT INTO movement_logs VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_treatments(conn: sqlite3.Connection, n_cattle: int, n_rows: int):
    """Generate treatment records.  ~40% respiratory, rest other."""
    rows = []
    treat_id = 1
    while len(rows) < n_rows:
        for cid in range(1, n_cattle + 1):
            n_treat = random.randint(0, 3)
            for _ in range(n_treat):
                if random.random() < 0.4:
                    diag = random.choice(DIAGNOSES_RESPIRATORY)
                    med = random.choice(MEDICATIONS_RESP)
                else:
                    diag = random.choice(DIAGNOSES_OTHER)
                    med = random.choice(MEDICATIONS_OTHER)
                days_ago = random.randint(1, 120)
                date_str = (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                vet = random.choice(VET_IDS)
                follow_up = 1 if random.random() < 0.3 else 0
                rows.append((treat_id, cid, diag, med, date_str, vet,
                             follow_up))
                treat_id += 1
            if len(rows) >= n_rows:
                break
    rows = rows[:n_rows]
    conn.executemany("INSERT INTO treatments VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


# ── Workspace file generators ───────────────────────────────────────────

def write_risk_thresholds(workspace: str):
    """Write risk scoring configuration (fixed config file)."""
    config = {
        "environmental_thresholds": {
            "temperature_high_f": 80.0,
            "temperature_low_f": 40.0,
            "humidity_high_pct": 75.0,
            "ammonia_high_ppm": 20.0,
            "airflow_low_cfm": 400.0,
        },
        "risk_score_weights": {
            "environmental": 25,
            "vaccination_gap": 30,
            "recent_movement": 15,
            "treatment_history": 20,
            "observation_symptoms": 10,
        },
        "quarantine_threshold": 55,
        "recent_move_window_days": 14,
        "recent_treatment_window_days": 30,
        "vaccine_overdue_days": 180,
    }
    path = os.path.join(workspace, "risk_thresholds.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def write_vaccine_protocols(workspace: str):
    """Write required vaccine protocol (fixed config file)."""
    protocols = {
        "required_vaccines": [
            {
                "vaccine_name": "Mannheimia haemolytica",
                "required_within_days_of_arrival": 14,
                "booster_interval_days": 180,
                "priority": "critical"
            },
            {
                "vaccine_name": "IBR",
                "required_within_days_of_arrival": 14,
                "booster_interval_days": 365,
                "priority": "high"
            },
            {
                "vaccine_name": "BVD",
                "required_within_days_of_arrival": 14,
                "booster_interval_days": 365,
                "priority": "high"
            },
            {
                "vaccine_name": "BRSV",
                "required_within_days_of_arrival": 21,
                "booster_interval_days": 180,
                "priority": "critical"
            },
        ],
        "missing_critical_vaccine_risk_points": 30,
        "missing_high_vaccine_risk_points": 15,
        "overdue_booster_risk_points": 10,
    }
    path = os.path.join(workspace, "vaccine_protocols.json")
    with open(path, "w") as f:
        json.dump(protocols, f, indent=2)


def write_pen_barn_mapping(workspace: str, pens):
    """Write pen-to-barn mapping (fixed config file)."""
    df = pd.DataFrame(pens, columns=["pen_id", "barn_id"])
    df["capacity"] = [random.randint(10, 25) for _ in range(len(pens))]
    path = os.path.join(workspace, "pen_barn_mapping.csv")
    df.to_csv(path, index=False)


def write_quarantine_policy(workspace: str):
    """Write quarantine policy document (fixed config file)."""
    content = """Quarantine Watchlist Generation Policy

When an animal's composite risk score meets or exceeds the quarantine threshold
defined in the risk thresholds configuration, it must be placed on the daily
quarantine watchlist.

For animals on the watchlist, the herd manager requires the following information:
tag number, current pen, barn assignment, composite risk score, and a semicolon-
delimited list of contributing risk factors sorted alphabetically.

Risk factor labels must use exactly these identifiers: ENV_TEMP_HIGH, ENV_TEMP_LOW,
ENV_HUMIDITY_HIGH, ENV_AMMONIA_HIGH, ENV_AIRFLOW_LOW, VAX_MISSING_CRITICAL,
VAX_MISSING_HIGH, VAX_OVERDUE_BOOSTER, RECENT_MOVE, RESP_TREATMENT_HISTORY,
OBSERVATION_SYMPTOMS.

The watchlist must be sorted by composite risk score in descending order. Where
two animals share the same score, sort by tag number in ascending lexicographic
order.

Composite risk score computation:
- Start at 0 for each animal.
- Environmental score: For each environmental threshold breach in the animal's
  barn (using the most recent 24 hours of sensor data), add (environmental weight
  / number of environmental threshold types) points per breach. The five threshold
  types are: temperature high, temperature low, humidity high, ammonia high,
  airflow low.
- Vaccination gap score: Check each required vaccine from the protocol. If a
  critical vaccine was never administered or its last dose is overdue, add the
  missing-critical-vaccine risk points. If a high-priority vaccine is missing or
  overdue, add the missing-high-vaccine risk points. If the vaccine was
  administered but the booster interval has elapsed since the last dose, add the
  overdue-booster risk points. Only count the highest applicable penalty per
  vaccine (missing > overdue).
- Recent movement score: If the animal was moved within the recent-move window,
  add the full recent-movement weight.
- Treatment history score: If the animal has any respiratory diagnosis within the
  recent treatment window, add the full treatment-history weight.
- Observation symptoms score: If the animal has any symptom flags recorded in
  the daily health observation files, add the full observation-symptoms weight.

The maximum possible risk score per animal is the sum of all weights (100).
Report scores as integers (round down via floor).
"""
    path = os.path.join(workspace, "quarantine_policy.md")
    with open(path, "w") as f:
        f.write(content)


def write_health_observations(workspace: str, db_path: str, n_files: int):
    """Write daily health observation batch files (scalable data files).

    Each file covers a subset of cattle with observation notes including
    optional symptom flags. These symptom flags are NOT in the database and
    are only available through these files.
    """
    conn = sqlite3.connect(db_path)
    cattle_df = pd.read_sql_query("SELECT cattle_id, tag_number, current_pen_id FROM cattle", conn)
    conn.close()

    n_cattle = len(cattle_df)
    # assign cattle to batches
    cattle_ids = cattle_df["cattle_id"].tolist()
    random.shuffle(cattle_ids)
    batch_size = max(1, n_cattle // n_files)

    symptom_options = [
        "nasal discharge", "coughing", "labored breathing",
        "reduced feed intake", "lethargy", "fever signs",
        "eye discharge", "drooping ears"
    ]

    for file_idx in range(n_files):
        start = file_idx * batch_size
        if file_idx == n_files - 1:
            batch_ids = cattle_ids[start:]
        else:
            batch_ids = cattle_ids[start:start + batch_size]

        if not batch_ids:
            batch_ids = [random.choice(cattle_ids)]

        records = []
        for cid in batch_ids:
            row = cattle_df[cattle_df["cattle_id"] == cid].iloc[0]
            # ~25% of animals show some respiratory symptoms
            if random.random() < 0.25:
                n_symptoms = random.randint(1, 3)
                symptoms = random.sample(symptom_options, n_symptoms)
                symptom_str = "; ".join(sorted(symptoms))
            else:
                symptom_str = "none"
            body_temp = round(random.gauss(101.5, 1.5), 1)
            records.append({
                "tag_number": row["tag_number"],
                "pen_id": row["current_pen_id"],
                "observation_date": TODAY.strftime("%Y-%m-%d"),
                "body_temp_f": body_temp,
                "symptoms": symptom_str,
                "observer_notes": fake.sentence(nb_words=8)
            })

        # Alternate file formats for variety
        fmt_cycle = file_idx % 4
        if fmt_cycle == 0:
            # CSV
            fname = f"health_obs_batch_{file_idx+1:03d}.csv"
            df = pd.DataFrame(records)
            df.to_csv(os.path.join(workspace, fname), index=False)
        elif fmt_cycle == 1:
            # JSON
            fname = f"health_obs_batch_{file_idx+1:03d}.json"
            with open(os.path.join(workspace, fname), "w") as f:
                json.dump(records, f, indent=2)
        elif fmt_cycle == 2:
            # TXT (pipe-delimited)
            fname = f"health_obs_batch_{file_idx+1:03d}.txt"
            lines = ["tag_number|pen_id|observation_date|body_temp_f|symptoms|observer_notes"]
            for r in records:
                lines.append("|".join(str(r[k]) for k in
                    ["tag_number", "pen_id", "observation_date",
                     "body_temp_f", "symptoms", "observer_notes"]))
            with open(os.path.join(workspace, fname), "w") as f:
                f.write("\n".join(lines) + "\n")
        else:
            # YAML
            fname = f"health_obs_batch_{file_idx+1:03d}.yaml"
            with open(os.path.join(workspace, fname), "w") as f:
                yaml.dump(records, f, default_flow_style=False)


def write_weather_advisory(workspace: str):
    """Write today's weather advisory (fixed file)."""
    content = f"""Weather Advisory - {TODAY.strftime('%Y-%m-%d')}

Issued by: County Agricultural Extension Office

Current Conditions:
- Temperature: 45°F (expected high 78°F)
- Relative Humidity: 82%
- Wind: NW 12 mph gusting to 25 mph
- Precipitation: 40% chance afternoon thunderstorms

Livestock Advisory:
Large temperature swings expected today. Ensure adequate ventilation
in enclosed barns to prevent heat and humidity buildup during afternoon
hours. Monitor ammonia levels closely in barns with poor airflow.
Animals recently transported or moved between pens are at elevated
risk for respiratory stress under these conditions.
"""
    path = os.path.join(workspace, "weather_advisory.txt")
    with open(path, "w") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Re-seed for reproducibility
    random.seed(SEED)
    np.random.seed(SEED)
    Faker.seed(SEED)

    os.makedirs(args.workspace, exist_ok=True)

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Create database
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    barns, pens = _gen_barns_and_pens(n_rows)

    cattle_rows = generate_cattle(conn, n_rows, pens)
    generate_vaccinations(conn, n_rows, n_rows)
    generate_sensor_readings(conn, barns, n_rows)
    generate_movements(conn, n_rows, pens, n_rows)
    generate_treatments(conn, n_rows, n_rows)

    conn.close()

    # Write fixed config files (not counted toward scalable num_workspace_files)
    write_risk_thresholds(args.workspace)
    write_vaccine_protocols(args.workspace)
    write_pen_barn_mapping(args.workspace, pens)
    write_quarantine_policy(args.workspace)
    write_weather_advisory(args.workspace)

    # Write scalable data files
    write_health_observations(args.workspace, args.db_path, n_files)

    print(f"Generated DB at {args.db_path} with {n_rows} rows/table")
    print(f"Generated {n_files} health observation files + 5 config files "
          f"in {args.workspace}/")


if __name__ == "__main__":
    main()
