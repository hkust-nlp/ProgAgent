"""
Data generator for cell tower capacity upgrade prioritization task.
Creates database tables and workspace files for analysis.
"""

import argparse
import os
import sqlite3
import json
import csv
import math
import random

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 25,
    "num_workspace_files": 8,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_database(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    N = SCALE["rows_per_table"]

    # Drop existing tables for idempotency
    for tbl in ["traffic_daily", "handoff_events", "construction_permits",
                 "sectors", "towers"]:
        c.execute(f"DROP TABLE IF EXISTS {tbl}")

    # ---- Table 1: towers ----
    c.execute("""
        CREATE TABLE towers (
            tower_id    INTEGER PRIMARY KEY,
            tower_name  TEXT    NOT NULL,
            region      TEXT    NOT NULL,
            latitude    REAL    NOT NULL,
            longitude   REAL    NOT NULL,
            install_year INTEGER NOT NULL,
            tower_class TEXT    NOT NULL
        )
    """)

    regions = ["North", "South", "East", "West", "Central"]
    tower_classes = ["macro", "micro", "small_cell"]
    class_weights = [0.5, 0.3, 0.2]

    towers = []
    for i in range(1, N + 1):
        towers.append((
            i,
            f"TWR-{i:04d}",
            regions[i % len(regions)],
            round(40.0 + random.uniform(-0.5, 0.5), 6),
            round(-74.0 + random.uniform(-0.5, 0.5), 6),
            random.randint(2010, 2023),
            random.choices(tower_classes, weights=class_weights, k=1)[0],
        ))
    c.executemany("INSERT INTO towers VALUES (?,?,?,?,?,?,?)", towers)

    # ---- Table 2: sectors ----
    c.execute("""
        CREATE TABLE sectors (
            sector_id          INTEGER PRIMARY KEY,
            tower_id           INTEGER NOT NULL,
            sector_label       TEXT    NOT NULL,
            azimuth_deg        INTEGER NOT NULL,
            frequency_band     TEXT    NOT NULL,
            current_ru_model   TEXT    NOT NULL,
            current_capacity_mbps REAL NOT NULL,
            FOREIGN KEY (tower_id) REFERENCES towers(tower_id)
        )
    """)

    bands = ["700MHz", "1800MHz", "2600MHz", "3500MHz"]
    ru_models = ["RU-100A", "RU-200B", "RU-150C", "RU-300D"]
    ru_capacity = {"RU-100A": 150.0, "RU-200B": 300.0, "RU-150C": 200.0, "RU-300D": 450.0}
    labels = ["Alpha", "Beta", "Gamma"]
    azimuths = [0, 120, 240]

    sectors = []
    sid = 1
    for t in towers:
        tid = t[0]
        n_sec = random.choice([2, 3, 3, 3])
        used_bands = random.sample(bands, n_sec)
        for s in range(n_sec):
            ru = random.choice(ru_models)
            sectors.append((
                sid, tid, labels[s], azimuths[s],
                used_bands[s], ru, ru_capacity[ru],
            ))
            sid += 1
    c.executemany("INSERT INTO sectors VALUES (?,?,?,?,?,?,?)", sectors)

    # ---- Table 3: traffic_daily ----
    c.execute("""
        CREATE TABLE traffic_daily (
            record_id            INTEGER PRIMARY KEY,
            sector_id            INTEGER NOT NULL,
            date                 TEXT    NOT NULL,
            avg_volume_mbps      REAL    NOT NULL,
            peak_volume_mbps     REAL    NOT NULL,
            avg_connected_users  INTEGER NOT NULL,
            peak_connected_users INTEGER NOT NULL,
            FOREIGN KEY (sector_id) REFERENCES sectors(sector_id)
        )
    """)

    from datetime import datetime, timedelta
    base_date = datetime(2025, 12, 1)
    rid = 1
    traffic_rows = []
    for sec in sectors:
        s_id = sec[0]
        cap = sec[6]
        base_util = random.uniform(0.30, 0.95)
        for day in range(30):
            dt = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
            u = max(0.10, min(1.0, base_util + random.uniform(-0.10, 0.10)))
            avg_v = round(cap * u * random.uniform(0.55, 0.75), 2)
            peak_v = round(cap * u * random.uniform(0.90, 1.15), 2)
            avg_u = max(1, int(50 * u + random.randint(-5, 5)))
            peak_u = max(1, int(80 * u + random.randint(-3, 10)))
            traffic_rows.append((rid, s_id, dt, avg_v, peak_v, avg_u, peak_u))
            rid += 1
    c.executemany("INSERT INTO traffic_daily VALUES (?,?,?,?,?,?,?)", traffic_rows)

    # ---- Table 4: handoff_events ----
    c.execute("""
        CREATE TABLE handoff_events (
            event_id         INTEGER PRIMARY KEY,
            source_tower_id  INTEGER NOT NULL,
            target_tower_id  INTEGER NOT NULL,
            month            TEXT    NOT NULL,
            total_attempts   INTEGER NOT NULL,
            successful       INTEGER NOT NULL,
            failed           INTEGER NOT NULL,
            FOREIGN KEY (source_tower_id) REFERENCES towers(tower_id),
            FOREIGN KEY (target_tower_id) REFERENCES towers(tower_id)
        )
    """)

    months = ["2025-10", "2025-11", "2025-12"]
    eid = 1
    handoff_rows = []
    all_tids = [t[0] for t in towers]
    for t in towers:
        tid = t[0]
        others = [x for x in all_tids if x != tid]
        n_adj = random.randint(2, min(4, len(others)))
        adj = random.sample(others, n_adj)
        for a in adj:
            for m in months:
                att = random.randint(500, 5000)
                fr = random.uniform(0.01, 0.15)
                failed = int(att * fr)
                handoff_rows.append((eid, tid, a, m, att, att - failed, failed))
                eid += 1
    c.executemany("INSERT INTO handoff_events VALUES (?,?,?,?,?,?,?)", handoff_rows)

    # ---- Table 5: construction_permits ----
    c.execute("""
        CREATE TABLE construction_permits (
            permit_id                    INTEGER PRIMARY KEY,
            project_name                 TEXT    NOT NULL,
            project_type                 TEXT    NOT NULL,
            latitude                     REAL    NOT NULL,
            longitude                    REAL    NOT NULL,
            estimated_new_residents      INTEGER NOT NULL,
            estimated_new_commercial_sqft INTEGER NOT NULL,
            issue_date                   TEXT    NOT NULL,
            expected_completion          TEXT    NOT NULL,
            status                       TEXT    NOT NULL
        )
    """)

    project_types = ["residential", "commercial", "mixed_use", "industrial"]
    statuses = ["approved", "under_construction", "planned"]
    permits = []
    for i in range(1, N + 1):
        ref = random.choice(towers)
        permits.append((
            i,
            fake.company() + " " + random.choice(["Plaza", "Tower", "Complex", "Park", "Center"]),
            random.choice(project_types),
            round(ref[3] + random.uniform(-0.025, 0.025), 6),
            round(ref[4] + random.uniform(-0.025, 0.025), 6),
            random.randint(100, 5000),
            random.randint(10000, 200000),
            f"2025-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
            f"2026-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
            random.choice(statuses),
        ))
    c.executemany("INSERT INTO construction_permits VALUES (?,?,?,?,?,?,?,?,?,?)", permits)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

def create_workspace(workspace, db_path):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)

    num_files = SCALE["num_workspace_files"]

    # ===== Fixed policy / config files (not part of SCALE) =====

    # 1. upgrade_policy.yaml
    policy = {
        "utilization_thresholds": {
            "avg_utilization_pct": 65,
            "peak_utilization_pct": 85,
        },
        "handoff_failure_threshold_pct": 8.0,
        "permit_impact": {
            "radius_km": 3.0,
            "min_new_residents": 500,
        },
        "upgrade_eligibility": {
            "min_factors_triggered": 2,
            "structural_grade_required": ["A", "B"],
        },
        "tower_class_multiplier": {
            "macro": 1.0,
            "micro": 0.8,
            "small_cell": 0.6,
        },
    }
    with open(os.path.join(workspace, "upgrade_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False)

    # 2. radio_unit_catalog.csv
    catalog = [
        {"model": "RU-400X", "frequency_bands": "700MHz;1800MHz",
         "capacity_mbps": 500, "power_watts": 80, "cost_usd": 12000,
         "form_factor": "standard"},
        {"model": "RU-500X", "frequency_bands": "1800MHz;2600MHz",
         "capacity_mbps": 750, "power_watts": 120, "cost_usd": 18000,
         "form_factor": "standard"},
        {"model": "RU-600M", "frequency_bands": "2600MHz;3500MHz",
         "capacity_mbps": 1000, "power_watts": 150, "cost_usd": 25000,
         "form_factor": "standard"},
        {"model": "RU-350S", "frequency_bands": "700MHz;1800MHz;2600MHz",
         "capacity_mbps": 400, "power_watts": 60, "cost_usd": 15000,
         "form_factor": "compact"},
        {"model": "RU-800X",
         "frequency_bands": "700MHz;1800MHz;2600MHz;3500MHz",
         "capacity_mbps": 1200, "power_watts": 200, "cost_usd": 35000,
         "form_factor": "large"},
        {"model": "RU-450C", "frequency_bands": "3500MHz",
         "capacity_mbps": 600, "power_watts": 90, "cost_usd": 16000,
         "form_factor": "compact"},
    ]
    with open(os.path.join(workspace, "radio_unit_catalog.csv"), "w",
              newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(catalog[0].keys()))
        writer.writeheader()
        writer.writerows(catalog)

    # 3. priority_weights.json
    weights = {
        "avg_utilization_score_weight": 0.30,
        "peak_utilization_score_weight": 0.25,
        "handoff_failure_score_weight": 0.25,
        "permit_impact_score_weight": 0.20,
        "scoring_instructions": (
            "Each factor is scored 0-100. avg_utilization_score equals the "
            "tower-wide average utilization percentage (capped at 100). "
            "peak_utilization_score equals the tower-wide maximum peak "
            "utilization percentage (capped at 100). handoff_failure_score "
            "equals min(100, failure_rate_pct / 15 * 100) rounded to two "
            "decimals. permit_impact_score equals "
            "min(100, total_nearby_new_residents / 5000 * 100) rounded to "
            "two decimals. Final priority_score = (sum of each score * its "
            "weight) * tower_class_multiplier, rounded to two decimals."
        ),
    }
    with open(os.path.join(workspace, "priority_weights.json"), "w") as f:
        json.dump(weights, f, indent=2)

    # 4. band_compatibility.yaml
    compat = {
        "notes": (
            "The recommended RU must support ALL distinct frequency bands "
            "present across the tower's sectors. For example, if a tower has "
            "sectors on 700MHz and 2600MHz the RU must list both bands."
        ),
        "form_factor_constraints": {
            "macro": ["standard", "large"],
            "micro": ["standard", "compact"],
            "small_cell": ["compact"],
        },
    }
    with open(os.path.join(workspace, "band_compatibility.yaml"), "w") as f:
        yaml.dump(compat, f, default_flow_style=False)

    # ===== Scalable data files (SCALE["num_workspace_files"]) =====
    # Site-assessment batch reports, each covering a subset of towers.
    # These contain structural_grade and power/slot info NOT in the database.

    towers_df = pd.read_sql("SELECT tower_id FROM towers ORDER BY tower_id",
                            conn)
    tower_ids = towers_df["tower_id"].tolist()

    # Distribute towers evenly
    per_file = max(1, len(tower_ids) // num_files)

    grades = ["A", "B", "C", "D"]
    grade_w = [0.30, 0.35, 0.20, 0.15]
    access_opts = ["easy", "moderate", "difficult"]

    for idx in range(num_files):
        start = idx * per_file
        if idx == num_files - 1:
            batch = tower_ids[start:]
        else:
            batch = tower_ids[start : start + per_file]
        if not batch:
            batch = random.sample(tower_ids, min(3, len(tower_ids)))

        records = []
        for tid in batch:
            records.append({
                "tower_id": int(tid),
                "structural_grade": random.choices(grades, weights=grade_w, k=1)[0],
                "power_headroom_kw": round(random.uniform(1.0, 10.0), 1),
                "max_additional_ru_slots": random.randint(1, 4),
                "site_access": random.choice(access_opts),
                "notes": fake.sentence(),
            })

        fmt = idx % 4
        if fmt == 0:
            fp = os.path.join(workspace,
                              f"site_assessment_batch_{idx + 1}.json")
            with open(fp, "w") as f:
                json.dump(records, f, indent=2)
        elif fmt == 1:
            fp = os.path.join(workspace,
                              f"site_assessment_batch_{idx + 1}.csv")
            with open(fp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
                w.writeheader()
                w.writerows(records)
        elif fmt == 2:
            fp = os.path.join(workspace,
                              f"site_assessment_batch_{idx + 1}.txt")
            with open(fp, "w") as f:
                for r in records:
                    f.write(f"Tower ID: {r['tower_id']}\n")
                    f.write(f"Structural Grade: {r['structural_grade']}\n")
                    f.write(f"Power Headroom (kW): {r['power_headroom_kw']}\n")
                    f.write(
                        f"Max Additional RU Slots: "
                        f"{r['max_additional_ru_slots']}\n"
                    )
                    f.write(f"Site Access: {r['site_access']}\n")
                    f.write(f"Notes: {r['notes']}\n")
                    f.write("---\n")
        else:
            fp = os.path.join(workspace,
                              f"site_assessment_batch_{idx + 1}.yaml")
            with open(fp, "w") as f:
                yaml.dump(records, f, default_flow_style=False)

    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    create_database(args.db_path)
    create_workspace(args.workspace, args.db_path)
    print("Data generation complete.")


if __name__ == "__main__":
    main()
