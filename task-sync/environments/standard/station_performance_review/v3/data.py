import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import yaml
from datetime import date, timedelta
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 32,
}


def random_date(start, end):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()

    num_stations = SCALE["rows_per_table"]
    num_workspace_files = SCALE["num_workspace_files"]
    files_per_type = max(1, num_workspace_files // 4)

    os.makedirs(args.workspace, exist_ok=True)
    conn = sqlite3.connect(args.db_path)
    cursor = conn.cursor()

    # ── Create tables ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            station_id   INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            district     TEXT NOT NULL,
            latitude     REAL NOT NULL,
            longitude    REAL NOT NULL,
            capacity     INTEGER NOT NULL,
            station_type TEXT NOT NULL,
            install_date TEXT NOT NULL,
            status       TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_usage (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id      INTEGER NOT NULL,
            year_month      TEXT NOT NULL,
            total_rides     INTEGER NOT NULL,
            unique_users    INTEGER NOT NULL,
            avg_duration_min REAL NOT NULL,
            peak_hour_rides INTEGER NOT NULL,
            FOREIGN KEY (station_id) REFERENCES stations(station_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_logs (
            log_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id        INTEGER NOT NULL,
            log_date          TEXT NOT NULL,
            issue_type        TEXT NOT NULL,
            severity          INTEGER NOT NULL,
            cost              REAL NOT NULL,
            resolution_status TEXT NOT NULL,
            downtime_hours    REAL NOT NULL,
            FOREIGN KEY (station_id) REFERENCES stations(station_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            complaint_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id     INTEGER NOT NULL,
            complaint_date TEXT NOT NULL,
            category       TEXT NOT NULL,
            severity       INTEGER NOT NULL,
            description    TEXT NOT NULL,
            resolved       INTEGER NOT NULL,
            FOREIGN KEY (station_id) REFERENCES stations(station_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS points_of_interest (
            poi_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT NOT NULL,
            poi_type           TEXT NOT NULL,
            latitude           REAL NOT NULL,
            longitude          REAL NOT NULL,
            nearest_station_id INTEGER NOT NULL,
            distance_km        REAL NOT NULL,
            FOREIGN KEY (nearest_station_id) REFERENCES stations(station_id)
        )
    """)

    # ── Generate stations ──────────────────────────────────────────
    num_districts = max(3, num_stations // 12)
    districts = [f"District_{chr(65 + i)}" for i in range(num_districts)]
    station_types = ["bike_share", "scooter_dock", "e_bike_station"]

    stations = []
    for i in range(1, num_stations + 1):
        stations.append({
            "station_id": i,
            "name": f"Station {fake.street_name()} {i}",
            "district": districts[i % len(districts)],
            "latitude": round(40.0 + random.uniform(-0.5, 0.5), 6),
            "longitude": round(-74.0 + random.uniform(-0.5, 0.5), 6),
            "capacity": random.choice([10, 15, 20, 25, 30]),
            "station_type": random.choice(station_types),
            "install_date": random_date(date(2019, 1, 1), date(2025, 9, 1)).isoformat(),
            "status": random.choice(["active"] * 4 + ["under_review"]),
        })

    cursor.executemany(
        "INSERT INTO stations VALUES (?,?,?,?,?,?,?,?,?)",
        [(s["station_id"], s["name"], s["district"], s["latitude"],
          s["longitude"], s["capacity"], s["station_type"],
          s["install_date"], s["status"]) for s in stations],
    )

    # ── Generate monthly usage (12 months per station) ─────────────
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    usage_rows = []
    for s in stations:
        base_rides = random.randint(80, 600)
        trend = random.choice(["declining"] * 2 + ["stable"] + ["growing"] * 2)
        for j, month in enumerate(months):
            if trend == "declining":
                rides = max(5, int(base_rides * (1 - 0.06 * j) + random.gauss(0, 10)))
            elif trend == "growing":
                rides = int(base_rides * (1 + 0.03 * j) + random.gauss(0, 10))
            else:
                rides = int(base_rides + random.gauss(0, 15))
            unique_users = max(3, int(rides * random.uniform(0.4, 0.75)))
            avg_dur = round(random.uniform(5, 35), 1)
            peak = max(1, int(rides * random.uniform(0.15, 0.35)))
            usage_rows.append((s["station_id"], month, max(1, rides),
                               unique_users, avg_dur, peak))

    cursor.executemany(
        "INSERT INTO monthly_usage "
        "(station_id,year_month,total_rides,unique_users,avg_duration_min,peak_hour_rides) "
        "VALUES (?,?,?,?,?,?)",
        usage_rows,
    )

    # ── Generate maintenance logs ──────────────────────────────────
    issue_types = ["mechanical_failure", "vandalism", "electrical_fault",
                   "weather_damage", "software_glitch", "dock_malfunction"]
    res_statuses = ["resolved", "resolved", "resolved", "pending", "in_progress"]
    num_maint = max(SCALE["rows_per_table"], num_stations * 3)
    maint_rows = []
    for _ in range(num_maint):
        sid = random.choice([s["station_id"] for s in stations])
        maint_rows.append((
            sid,
            random_date(date(2024, 7, 1), date(2025, 12, 15)).isoformat(),
            random.choice(issue_types),
            random.randint(1, 5),
            round(random.uniform(50, 5000), 2),
            random.choice(res_statuses),
            round(random.uniform(0.5, 48), 1),
        ))

    cursor.executemany(
        "INSERT INTO maintenance_logs "
        "(station_id,log_date,issue_type,severity,cost,resolution_status,downtime_hours) "
        "VALUES (?,?,?,?,?,?,?)",
        maint_rows,
    )

    # ── Generate complaints ────────────────────────────────────────
    complaint_cats = ["broken_dock", "missing_vehicle", "billing_error",
                      "safety_concern", "dirty_station", "app_issue"]
    num_complaints = max(SCALE["rows_per_table"], num_stations * 2)
    comp_rows = []
    for _ in range(num_complaints):
        sid = random.choice([s["station_id"] for s in stations])
        comp_rows.append((
            sid,
            random_date(date(2024, 7, 1), date(2025, 12, 15)).isoformat(),
            random.choice(complaint_cats),
            random.randint(1, 5),
            fake.sentence(nb_words=10),
            random.choice([0, 0, 1, 1, 1]),
        ))

    cursor.executemany(
        "INSERT INTO complaints "
        "(station_id,complaint_date,category,severity,description,resolved) "
        "VALUES (?,?,?,?,?,?)",
        comp_rows,
    )

    # ── Generate points of interest ────────────────────────────────
    poi_types = ["restaurant", "school", "park", "office_building",
                 "shopping_mall", "hospital", "transit_hub", "residential_complex"]
    num_pois = max(SCALE["rows_per_table"], num_stations * 4)
    poi_rows = []
    for _ in range(num_pois):
        sid = random.choice([s["station_id"] for s in stations])
        s = next(st for st in stations if st["station_id"] == sid)
        dist_km = round(random.uniform(0.05, 1.5), 3)
        poi_rows.append((
            fake.company(),
            random.choice(poi_types),
            round(s["latitude"] + random.uniform(-0.015, 0.015), 6),
            round(s["longitude"] + random.uniform(-0.015, 0.015), 6),
            sid,
            dist_km,
        ))

    cursor.executemany(
        "INSERT INTO points_of_interest "
        "(name,poi_type,latitude,longitude,nearest_station_id,distance_km) "
        "VALUES (?,?,?,?,?,?)",
        poi_rows,
    )

    conn.commit()

    # ── Fixed workspace files ──────────────────────────────────────
    scoring_config = {
        "weights": {
            "usage_decline": 0.30,
            "maintenance_burden": 0.25,
            "complaint_index": 0.25,
            "poi_sparsity": 0.20,
        },
        "normalization": {
            "maintenance_cost_cap": 20000.0,
            "complaint_severity_cap": 50.0,
            "max_usage_decline_pct": 80.0,
            "max_poi_for_sparsity": 15,
            "downtime_cost_per_hour": 75.0,
        },
        "thresholds": {
            "candidate_score_min": 55.0,
            "critical_poi_count": 3,
            "severe_usage_decline_pct": 40.0,
        },
        "formulas": {
            "usage_decline": {
                "description": "Compare average total_rides in the first 3 months vs the last 3 months",
                "formula": "usage_decline_pct = max(0, (avg_first_3 - avg_last_3) / avg_first_3 * 100)",
                "score": "min(usage_decline_pct / max_usage_decline_pct, 1.0) * 100",
            },
            "maintenance_burden": {
                "description": "Total maintenance cost plus downtime valued at hourly rate",
                "formula": "burden = total_cost + total_downtime_hours * downtime_cost_per_hour",
                "score": "min(burden / maintenance_cost_cap, 1.0) * 100",
            },
            "complaint_index": {
                "description": "Severity-weighted complaints adjusted by unresolved ratio",
                "formula": "adjusted = weighted_severity_score * (1 + unresolved_count / max(total_complaints, 1))",
                "score": "min(adjusted / complaint_severity_cap, 1.0) * 100",
            },
            "poi_sparsity": {
                "description": "Inverse of nearby POI density within 500m radius",
                "formula": "sparsity_pct = max(0, max_poi_for_sparsity - poi_count_500m) / max_poi_for_sparsity * 100",
                "score": "sparsity_pct (already 0-100)",
            },
            "composite": {
                "formula": "sum(weight_i * score_i for each component)",
                "rounding": "round to 2 decimal places",
            },
        },
    }

    with open(os.path.join(args.workspace, "scoring_config.yaml"), "w") as f:
        yaml.dump(scoring_config, f, default_flow_style=False, sort_keys=False)

    relocation_criteria = {
        "eligibility": {
            "max_install_date": "2024-10-01",
            "description": "Stations installed after this date are too new for evaluation and must be excluded",
        },
        "decision_rules": {
            "decommission": {
                "condition": "poi_count_500m <= critical_poi_count AND usage_decline_pct > severe_usage_decline_pct",
                "description": "Station is in a low-activity area with severe usage decline",
            },
            "relocate": {
                "condition": "candidate but does not meet decommission criteria",
                "description": "Station may benefit from relocation to a better-served area",
            },
        },
        "output_format": {
            "file_name": "relocation_candidates.csv",
            "columns": ["rank", "station_id", "station_name", "district",
                         "composite_score", "recommendation"],
            "sort_by": "composite_score descending",
            "tie_breaking": "station_id ascending",
            "score_precision": 2,
        },
    }

    with open(os.path.join(args.workspace, "relocation_criteria.json"), "w") as f:
        json.dump(relocation_criteria, f, indent=2)

    # ── Scalable workspace files ───────────────────────────────────
    station_ids = [s["station_id"] for s in stations]

    def split_into_batches(items, n):
        k, m = divmod(len(items), n)
        return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

    batches = split_into_batches(station_ids, files_per_type)

    # Type 1: usage trend CSVs (total_rides, unique_users — no avg_duration / peak_hour)
    for idx, batch in enumerate(batches):
        rows = []
        for sid in batch:
            cursor.execute(
                "SELECT station_id, year_month, total_rides, unique_users "
                "FROM monthly_usage WHERE station_id = ? ORDER BY year_month",
                (sid,),
            )
            rows.extend(cursor.fetchall())
        path = os.path.join(args.workspace, f"usage_trends_{idx + 1}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["station_id", "year_month", "total_rides", "unique_users"])
            w.writerows(rows)

    # Type 2: POI survey JSONs (count within 500 m + type breakdown)
    for idx, batch in enumerate(batches):
        poi_density = {}
        for sid in batch:
            cursor.execute(
                "SELECT COUNT(*) FROM points_of_interest "
                "WHERE nearest_station_id = ? AND distance_km <= 0.5",
                (sid,),
            )
            cnt = cursor.fetchone()[0]
            cursor.execute(
                "SELECT poi_type, COUNT(*) FROM points_of_interest "
                "WHERE nearest_station_id = ? AND distance_km <= 0.5 GROUP BY poi_type",
                (sid,),
            )
            breakdown = {r[0]: r[1] for r in cursor.fetchall()}
            poi_density[str(sid)] = {
                "poi_count_500m": cnt,
                "type_breakdown": breakdown,
            }
        path = os.path.join(args.workspace, f"poi_survey_{idx + 1}.json")
        with open(path, "w") as f:
            json.dump(poi_density, f, indent=2)

    # Type 3: complaint summary TXTs (counts + unresolved — no severity)
    for idx, batch in enumerate(batches):
        path = os.path.join(args.workspace, f"complaint_summary_{idx + 1}.txt")
        with open(path, "w") as f:
            for sid in batch:
                cursor.execute(
                    "SELECT COUNT(*) FROM complaints WHERE station_id = ?", (sid,))
                total = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT COUNT(*) FROM complaints "
                    "WHERE station_id = ? AND resolved = 0", (sid,))
                unresolved = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT category, COUNT(*) FROM complaints "
                    "WHERE station_id = ? GROUP BY category", (sid,))
                cats = cursor.fetchall()
                f.write(f"Station {sid} | Total Complaints: {total} | Unresolved: {unresolved}\n")
                for cat, cnt in cats:
                    f.write(f"  - {cat}: {cnt}\n")
                f.write("\n")

    # Type 4: maintenance notes YAML (incident counts + downtime — no cost)
    for idx, batch in enumerate(batches):
        notes = {}
        for sid in batch:
            cursor.execute(
                "SELECT issue_type, COUNT(*), SUM(downtime_hours) "
                "FROM maintenance_logs WHERE station_id = ? GROUP BY issue_type",
                (sid,),
            )
            issues = cursor.fetchall()
            cursor.execute(
                "SELECT COUNT(*) FROM maintenance_logs WHERE station_id = ?", (sid,))
            total_inc = cursor.fetchone()[0]
            notes[f"station_{sid}"] = {
                "total_incidents": total_inc,
                "issues": {
                    row[0]: {"count": row[1],
                             "total_downtime_hours": round(row[2], 1)}
                    for row in issues
                },
            }
        path = os.path.join(args.workspace, f"maintenance_notes_{idx + 1}.yaml")
        with open(path, "w") as f:
            yaml.dump(notes, f, default_flow_style=False, sort_keys=False)

    conn.close()
    print(f"Database written to {args.db_path}")
    print(f"Workspace created at {args.workspace} "
          f"({2 + files_per_type * 4} files: 2 config + {files_per_type * 4} data)")


if __name__ == "__main__":
    main()
