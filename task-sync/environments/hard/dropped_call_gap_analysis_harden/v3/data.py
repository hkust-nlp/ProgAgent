#!/usr/bin/env python3
"""Data generation script for tower upgrade prioritization task."""

import argparse
import csv
import json
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 800,
    "num_workspace_files": 40,
}

REGIONS = ["Central", "East", "North", "South", "West"]
REGION_COORDS = {
    "North": {"lat": (48.0, 52.0), "lon": (10.0, 14.0)},
    "South": {"lat": (30.0, 34.0), "lon": (10.0, 14.0)},
    "East": {"lat": (40.0, 44.0), "lon": (20.0, 24.0)},
    "West": {"lat": (40.0, 44.0), "lon": (0.0, 4.0)},
    "Central": {"lat": (44.0, 48.0), "lon": (12.0, 16.0)},
}
TECHNOLOGIES = ["2G", "3G", "4G", "5G"]
PLAN_TIERS = ["basic", "standard", "premium", "enterprise"]
CALL_TYPES = ["voice", "data", "video"]
MAINT_TYPES = ["preventive", "corrective", "upgrade"]
MAINT_STATUSES = ["completed", "scheduled", "in_progress"]
IMPACT_LEVELS = ["none", "partial", "full"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(args.workspace, exist_ok=True)

    n_towers = SCALE["rows_per_table"]
    n_complaints = SCALE["rows_per_table"] * 4
    n_network_logs = SCALE["rows_per_table"] * 3
    n_maintenance = SCALE["rows_per_table"]
    n_subscribers = SCALE["rows_per_table"] * 2
    n_signal_files = SCALE["num_workspace_files"] // 2
    n_drop_files = SCALE["num_workspace_files"] - n_signal_files

    # ================================================================
    # Generate towers
    # ================================================================
    towers = []
    for i in range(n_towers):
        region = REGIONS[i % len(REGIONS)]
        coords = REGION_COORDS[region]
        lat = round(np.random.uniform(*coords["lat"]), 6)
        lon = round(np.random.uniform(*coords["lon"]), 6)
        tech = np.random.choice(TECHNOLOGIES, p=[0.05, 0.15, 0.55, 0.25])
        bw_choices = {
            "2G": [5, 10],
            "3G": [10, 15, 20],
            "4G": [15, 20, 40],
            "5G": [40, 60, 100],
        }
        towers.append(
            {
                "tower_id": f"TWR-{i + 1:04d}",
                "tower_name": f"{fake.city()}-{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(1, 99):02d}",
                "latitude": lat,
                "longitude": lon,
                "technology": tech,
                "bandwidth_mhz": random.choice(bw_choices[tech]),
                "region": region,
                "install_year": random.randint(2005, 2023),
                "status": np.random.choice(["active", "degraded"], p=[0.8, 0.2]),
            }
        )

    # Mark ~30% of towers as problematic (high complaints, bad metrics)
    n_problematic = max(1, int(n_towers * 0.30))
    problematic_indices = set(
        np.random.choice(n_towers, n_problematic, replace=False).tolist()
    )

    # ================================================================
    # Generate subscribers
    # ================================================================
    subscribers = []
    for i in range(n_subscribers):
        assigned_tower = towers[i % n_towers]
        home_lat = round(
            assigned_tower["latitude"] + np.random.uniform(-0.2, 0.2), 6
        )
        home_lon = round(
            assigned_tower["longitude"] + np.random.uniform(-0.2, 0.2), 6
        )
        subscribers.append(
            {
                "subscriber_id": f"SUB-{i + 1:05d}",
                "name": fake.name(),
                "plan_tier": random.choice(PLAN_TIERS),
                "home_latitude": home_lat,
                "home_longitude": home_lon,
                "primary_tower_id": assigned_tower["tower_id"],
                "registration_date": fake.date_between(
                    start_date="-5y", end_date="-30d"
                ).isoformat(),
            }
        )

    # ================================================================
    # Generate complaints (weighted toward problematic towers)
    # ================================================================
    tower_weights = np.array(
        [5.0 if i in problematic_indices else 0.5 for i in range(n_towers)]
    )
    tower_weights /= tower_weights.sum()

    complaints = []
    base_date = date(2024, 6, 1)
    date_range_days = (date(2025, 3, 31) - base_date).days
    for i in range(n_complaints):
        tower_idx = int(np.random.choice(n_towers, p=tower_weights))
        tower = towers[tower_idx]
        sub = subscribers[random.randint(0, n_subscribers - 1)]
        if tower_idx in problematic_indices:
            severity = random.randint(3, 5)
        else:
            severity = random.randint(1, 3)
        comp_date = base_date + timedelta(days=random.randint(0, date_range_days))
        complaints.append(
            {
                "complaint_id": f"CMP-{i + 1:05d}",
                "subscriber_id": sub["subscriber_id"],
                "tower_id": tower["tower_id"],
                "complaint_date": comp_date.isoformat(),
                "severity": severity,
                "call_type": random.choice(CALL_TYPES),
                "description": fake.sentence(nb_words=10),
            }
        )

    # ================================================================
    # Generate network logs
    # ================================================================
    network_logs = []
    for i in range(n_network_logs):
        tower_idx = i % n_towers
        tower = towers[tower_idx]
        is_prob = tower_idx in problematic_indices
        if is_prob:
            avg_signal = round(np.random.uniform(-105, -80), 1)
            packet_loss = round(np.random.uniform(3.0, 15.0), 2)
            latency = round(np.random.uniform(50.0, 200.0), 1)
            downtime = round(np.random.uniform(5.0, 60.0), 1)
        else:
            avg_signal = round(np.random.uniform(-75, -55), 1)
            packet_loss = round(np.random.uniform(0.1, 3.0), 2)
            latency = round(np.random.uniform(10.0, 50.0), 1)
            downtime = round(np.random.uniform(0.0, 5.0), 1)
        log_date = base_date + timedelta(days=random.randint(0, date_range_days))
        network_logs.append(
            {
                "log_id": f"LOG-{i + 1:05d}",
                "tower_id": tower["tower_id"],
                "log_date": log_date.isoformat(),
                "avg_signal_dbm": avg_signal,
                "packet_loss_pct": packet_loss,
                "avg_latency_ms": latency,
                "downtime_minutes": downtime,
            }
        )

    # ================================================================
    # Generate maintenance schedules
    # ================================================================
    maintenance = []
    for i in range(n_maintenance):
        tower = towers[i % n_towers]
        start = fake.date_between(start_date="-6m", end_date="+3m")
        end = start + timedelta(days=random.randint(1, 14))
        status = random.choice(MAINT_STATUSES)
        maintenance.append(
            {
                "maintenance_id": f"MNT-{i + 1:04d}",
                "tower_id": tower["tower_id"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "maintenance_type": random.choice(MAINT_TYPES),
                "impact_level": random.choice(IMPACT_LEVELS),
                "status": status,
            }
        )

    # ================================================================
    # Create database
    # ================================================================
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    c = conn.cursor()

    c.execute(
        """CREATE TABLE towers (
        tower_id TEXT PRIMARY KEY,
        tower_name TEXT,
        latitude REAL,
        longitude REAL,
        technology TEXT,
        bandwidth_mhz INTEGER,
        region TEXT,
        install_year INTEGER,
        status TEXT
    )"""
    )

    c.execute(
        """CREATE TABLE subscribers (
        subscriber_id TEXT PRIMARY KEY,
        name TEXT,
        plan_tier TEXT,
        home_latitude REAL,
        home_longitude REAL,
        primary_tower_id TEXT,
        registration_date TEXT,
        FOREIGN KEY (primary_tower_id) REFERENCES towers(tower_id)
    )"""
    )

    c.execute(
        """CREATE TABLE complaints (
        complaint_id TEXT PRIMARY KEY,
        subscriber_id TEXT,
        tower_id TEXT,
        complaint_date TEXT,
        severity INTEGER,
        call_type TEXT,
        description TEXT,
        FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id),
        FOREIGN KEY (tower_id) REFERENCES towers(tower_id)
    )"""
    )

    c.execute(
        """CREATE TABLE network_logs (
        log_id TEXT PRIMARY KEY,
        tower_id TEXT,
        log_date TEXT,
        avg_signal_dbm REAL,
        packet_loss_pct REAL,
        avg_latency_ms REAL,
        downtime_minutes REAL,
        FOREIGN KEY (tower_id) REFERENCES towers(tower_id)
    )"""
    )

    c.execute(
        """CREATE TABLE maintenance_schedules (
        maintenance_id TEXT PRIMARY KEY,
        tower_id TEXT,
        start_date TEXT,
        end_date TEXT,
        maintenance_type TEXT,
        impact_level TEXT,
        status TEXT,
        FOREIGN KEY (tower_id) REFERENCES towers(tower_id)
    )"""
    )

    for t in towers:
        c.execute(
            "INSERT INTO towers VALUES (?,?,?,?,?,?,?,?,?)",
            (
                t["tower_id"],
                t["tower_name"],
                t["latitude"],
                t["longitude"],
                t["technology"],
                t["bandwidth_mhz"],
                t["region"],
                t["install_year"],
                t["status"],
            ),
        )

    for s in subscribers:
        c.execute(
            "INSERT INTO subscribers VALUES (?,?,?,?,?,?,?)",
            (
                s["subscriber_id"],
                s["name"],
                s["plan_tier"],
                s["home_latitude"],
                s["home_longitude"],
                s["primary_tower_id"],
                s["registration_date"],
            ),
        )

    for comp in complaints:
        c.execute(
            "INSERT INTO complaints VALUES (?,?,?,?,?,?,?)",
            (
                comp["complaint_id"],
                comp["subscriber_id"],
                comp["tower_id"],
                comp["complaint_date"],
                comp["severity"],
                comp["call_type"],
                comp["description"],
            ),
        )

    for nl in network_logs:
        c.execute(
            "INSERT INTO network_logs VALUES (?,?,?,?,?,?,?)",
            (
                nl["log_id"],
                nl["tower_id"],
                nl["log_date"],
                nl["avg_signal_dbm"],
                nl["packet_loss_pct"],
                nl["avg_latency_ms"],
                nl["downtime_minutes"],
            ),
        )

    for m in maintenance:
        c.execute(
            "INSERT INTO maintenance_schedules VALUES (?,?,?,?,?,?,?)",
            (
                m["maintenance_id"],
                m["tower_id"],
                m["start_date"],
                m["end_date"],
                m["maintenance_type"],
                m["impact_level"],
                m["status"],
            ),
        )

    conn.commit()
    conn.close()

    # ================================================================
    # Generate workspace files - FIXED (non-scaling) config files
    # ================================================================

    # 1. upgrade_scoring_criteria.yaml
    criteria = {
        "scoring": {
            "complaint_score": {
                "formula": "min(100, complaint_count * average_severity * 4)",
                "notes": "complaint_count is the total number of complaints for the tower. average_severity is the arithmetic mean of severity values across all complaints for that tower.",
            },
            "network_score": {
                "formula": "min(100, (max(0, (-1 * average_signal_dbm) - 70) * 2 + average_packet_loss_pct * 8) / 2)",
                "notes": "average_signal_dbm and average_packet_loss_pct are arithmetic means across all network log entries for the tower. If a tower has no network log entries, this score is 0.",
            },
            "coverage_gap_score": {
                "formula": "(count_below_threshold / total_count) * 100",
                "notes": "From signal survey CSV files, find all measurements where the absolute difference in latitude from the tower is at most 0.5 AND the absolute difference in longitude from the tower is at most 0.5. count_below_threshold is the number of those measurements with signal_dbm strictly less than -90. total_count is the total measurements in that area. If total_count is 0, score is 0.",
            },
            "device_signal_score": {
                "formula": "min(100, max(0, (-1 * average_device_signal_dbm) - 80) * 3)",
                "notes": "From call drop report JSON files, collect all device_signal_dbm values matching the tower_id. average_device_signal_dbm is their arithmetic mean. If no records exist for the tower, score is 0.",
            },
        },
        "weights": {
            "complaint": 0.30,
            "network": 0.25,
            "coverage_gap": 0.25,
            "device_signal": 0.20,
        },
        "qualification_thresholds": {
            "min_complaint_count": 3,
            "min_avg_severity": 2.0,
        },
        "maintenance_discount": {
            "description": "If a tower has any maintenance record with status 'scheduled' or 'in_progress', multiply the final priority_score by the discount factor.",
            "factor": 0.5,
        },
        "primary_issue_mapping": {
            "complaint": "high_complaint_rate",
            "network": "poor_network_performance",
            "coverage_gap": "coverage_gap",
            "device_signal": "weak_device_signal",
        },
        "primary_issue_rule": "The component whose raw_score multiplied by its weight is the highest determines the primary_issue. Ties are broken alphabetically by component name (complaint < coverage_gap < device_signal < network).",
        "priority_tiers": {
            "critical": {"min_score": 75},
            "high": {"min_score": 50},
            "medium": {"min_score": 25},
            "low": {"min_score": 0},
        },
        "output": {
            "filename": "tower_upgrade_priority.csv",
            "columns": [
                "rank",
                "tower_id",
                "tower_name",
                "region",
                "priority_score",
                "priority_tier",
                "primary_issue",
                "recommended_upgrade",
            ],
            "sort": "priority_score descending, tower_id ascending for ties",
            "score_precision": 2,
        },
    }
    with open(
        os.path.join(args.workspace, "upgrade_scoring_criteria.yaml"), "w"
    ) as f:
        yaml.dump(criteria, f, default_flow_style=False, sort_keys=False)

    # 2. technology_upgrade_paths.json
    upgrade_paths = {
        "2G": {"recommended_upgrade": "4G", "estimated_cost_usd": 250000},
        "3G": {"recommended_upgrade": "4G", "estimated_cost_usd": 180000},
        "4G": {"recommended_upgrade": "5G", "estimated_cost_usd": 350000},
        "5G": {"recommended_upgrade": "5G-Advanced", "estimated_cost_usd": 420000},
    }
    with open(
        os.path.join(args.workspace, "technology_upgrade_paths.json"), "w"
    ) as f:
        json.dump(upgrade_paths, f, indent=2)

    # 3. regional_budget_priorities.csv
    regional_priorities = [
        {"region": "North", "priority_multiplier": "1.2"},
        {"region": "South", "priority_multiplier": "1.0"},
        {"region": "East", "priority_multiplier": "1.1"},
        {"region": "West", "priority_multiplier": "0.9"},
        {"region": "Central", "priority_multiplier": "1.3"},
    ]
    with open(
        os.path.join(args.workspace, "regional_budget_priorities.csv"),
        "w",
        newline="",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=["region", "priority_multiplier"])
        writer.writeheader()
        writer.writerows(regional_priorities)

    # 4. tower_classification_rules.txt
    rules_text = (
        "Tower Classification Rules\n"
        "==========================\n\n"
        "Towers are classified based on their current operational metrics and complaint history.\n\n"
        "A tower qualifies for upgrade assessment when it meets BOTH of these conditions:\n"
        "- Total complaint count is at least the minimum specified in the scoring criteria configuration.\n"
        "- Average complaint severity meets or exceeds the severity threshold in the scoring criteria.\n\n"
        "Once qualified, each tower receives scores across four dimensions as defined in\n"
        "the scoring criteria configuration. The final priority score determines the\n"
        "upgrade urgency and is used to rank all qualifying towers.\n\n"
        "Towers with ongoing or scheduled maintenance receive a reduced priority score\n"
        "as specified by the maintenance discount factor, since resources are already\n"
        "being allocated to address their issues.\n\n"
        "The recommended upgrade path for each tower is determined by its current\n"
        "technology generation, as specified in the technology upgrade paths configuration.\n"
    )
    with open(
        os.path.join(args.workspace, "tower_classification_rules.txt"), "w"
    ) as f:
        f.write(rules_text)

    # 5. upgrade_scoring_methodology.md
    methodology_text = (
        "# Tower Upgrade Priority Scoring Methodology\n"
        "\n"
        "This document defines how the final upgrade priority score is assembled for\n"
        "every tower that qualifies for assessment. It complements the scoring criteria\n"
        "configuration (`upgrade_scoring_criteria.yaml`), which defines the four\n"
        "dimension formulas, the dimension weights, the qualification thresholds, the\n"
        "maintenance discount factor, the primary issue mapping, the priority tier\n"
        "boundaries, and the output specification.\n"
        "\n"
        "## Qualification\n"
        "\n"
        "A tower is assessed only if it meets BOTH qualification thresholds in the\n"
        "scoring criteria configuration: its total complaint count must be at least\n"
        "`min_complaint_count` AND its average complaint severity (arithmetic mean of\n"
        "severity across all of its complaints, unrounded) must be at least\n"
        "`min_avg_severity`.\n"
        "\n"
        "## Priority score assembly\n"
        "\n"
        "1. Compute the four dimension scores (complaint_score, network_score,\n"
        "   coverage_gap_score, device_signal_score) using the formulas and data\n"
        "   sources given in the scoring criteria configuration.\n"
        "2. Multiply each dimension score by its configured weight and sum the four\n"
        "   weighted values:\n"
        "   `raw_score = complaint_score * weight_complaint + network_score *\n"
        "   weight_network + coverage_gap_score * weight_coverage_gap +\n"
        "   device_signal_score * weight_device_signal`.\n"
        "3. Multiply `raw_score` by the tower's regional priority multiplier, looked up\n"
        "   by the tower's region in the regional budget priorities table\n"
        "   (`regional_budget_priorities.csv`). A region not listed in that table uses\n"
        "   a multiplier of 1.0.\n"
        "4. If the tower has any maintenance record with status 'scheduled' or\n"
        "   'in_progress', multiply the result by the maintenance discount factor from\n"
        "   the scoring criteria configuration.\n"
        "5. Round the resulting priority_score to exactly two decimal places (see\n"
        "   `score_precision` in the output specification).\n"
        "\n"
        "## Priority tier\n"
        "\n"
        "Tier assignment uses the final rounded priority_score. A tower is assigned\n"
        "the highest tier whose `min_score` its priority_score meets or exceeds, per\n"
        "the `priority_tiers` boundaries in the scoring criteria configuration (for\n"
        "example, a score of 80 falls in the tier whose `min_score` is 75).\n"
        "\n"
        "## Primary issue\n"
        "\n"
        "The primary issue is the dimension whose weighted contribution (dimension\n"
        "score multiplied by its weight, evaluated BEFORE the regional multiplier and\n"
        "the maintenance discount are applied) is the largest, translated to its label\n"
        "via the primary issue mapping. Ties are broken alphabetically by component\n"
        "name (complaint < coverage_gap < device_signal < network).\n"
        "\n"
        "## Recommended upgrade\n"
        "\n"
        "The recommended upgrade for each tower is determined by its current\n"
        "technology generation, as specified in the technology upgrade paths\n"
        "configuration (`technology_upgrade_paths.json`).\n"
    )
    with open(
        os.path.join(args.workspace, "upgrade_scoring_methodology.md"), "w"
    ) as f:
        f.write(methodology_text)

    # ================================================================
    # Generate workspace files - SCALABLE data files
    # ================================================================

    # Signal survey CSV files
    for file_idx in range(n_signal_files):
        region_idx = file_idx % len(REGIONS)
        region = REGIONS[region_idx]
        coords = REGION_COORDS[region]

        # Get towers in this region
        region_towers = [t for t in towers if t["region"] == region]
        region_tower_indices = [
            j for j, t in enumerate(towers) if t["region"] == region
        ]

        measurements = []
        n_measurements = random.randint(40, 80)

        for _ in range(n_measurements):
            if random.random() < 0.6 and region_towers:
                # Near a specific tower
                idx_in_region = random.randint(0, len(region_towers) - 1)
                tower = region_towers[idx_in_region]
                global_idx = region_tower_indices[idx_in_region]
                lat = round(tower["latitude"] + np.random.uniform(-0.3, 0.3), 6)
                lon = round(tower["longitude"] + np.random.uniform(-0.3, 0.3), 6)

                if global_idx in problematic_indices:
                    signal = round(np.random.uniform(-108, -85), 1)
                else:
                    signal = round(np.random.uniform(-82, -60), 1)
            else:
                lat = round(np.random.uniform(*coords["lat"]), 6)
                lon = round(np.random.uniform(*coords["lon"]), 6)
                signal = round(np.random.uniform(-95, -65), 1)

            meas_date = base_date + timedelta(days=random.randint(0, date_range_days))
            measurements.append(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "signal_dbm": signal,
                    "measurement_date": meas_date.isoformat(),
                }
            )

        sub_idx = file_idx // len(REGIONS) + 1
        filename = f"signal_survey_{region.lower()}_{sub_idx:02d}.csv"
        with open(os.path.join(args.workspace, filename), "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["latitude", "longitude", "signal_dbm", "measurement_date"]
            )
            writer.writeheader()
            writer.writerows(measurements)

    # Call drop report JSON files
    for file_idx in range(n_drop_files):
        records = []
        n_records = random.randint(30, 60)

        for _ in range(n_records):
            tower_idx = int(np.random.choice(n_towers, p=tower_weights))
            tower = towers[tower_idx]
            sub = subscribers[random.randint(0, n_subscribers - 1)]

            if tower_idx in problematic_indices:
                device_signal = round(np.random.uniform(-115, -85), 1)
            else:
                device_signal = round(np.random.uniform(-85, -70), 1)

            drop_dt = datetime.combine(
                base_date + timedelta(days=random.randint(0, date_range_days)),
                datetime.min.time(),
            ) + timedelta(
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59),
            )
            records.append(
                {
                    "tower_id": tower["tower_id"],
                    "subscriber_id": sub["subscriber_id"],
                    "device_signal_dbm": device_signal,
                    "gps_latitude": round(
                        tower["latitude"] + np.random.uniform(-0.3, 0.3), 6
                    ),
                    "gps_longitude": round(
                        tower["longitude"] + np.random.uniform(-0.3, 0.3), 6
                    ),
                    "drop_timestamp": drop_dt.isoformat(),
                }
            )

        filename = f"call_drop_report_{file_idx + 1:03d}.json"
        with open(os.path.join(args.workspace, filename), "w") as f:
            json.dump(records, f, indent=2)

    print(
        f"Data generated: {n_towers} towers, {n_complaints} complaints, "
        f"{n_network_logs} network logs, {n_maintenance} maintenance records, "
        f"{n_subscribers} subscribers, {n_signal_files + n_drop_files} workspace data files"
    )


if __name__ == "__main__":
    main()
