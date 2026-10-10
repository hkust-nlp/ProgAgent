"""
Data generation for cloud storage volume reclamation task.
Generates a SQLite database and workspace files representing a cloud
infrastructure environment with volumes, attachment events, snapshots,
projects, and budget alerts.
"""

import argparse
import csv
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ──────────────────────────────────────────────────────────────
# SCALE – only this block differs across v0 → v3
# ──────────────────────────────────────────────────────────────
SCALE = {
    "rows_per_table": 640,      # v3 = 8× base
    "num_workspace_files": 40,  # v3 = base + 3N
}

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
REFERENCE_DATE = datetime(2026, 4, 25)
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
VOLUME_TYPES = ["ssd", "hdd", "nvme", "cold-storage"]
DEPARTMENTS = ["engineering", "data-science", "marketing", "finance", "operations"]
VOLUME_STATUSES = ["attached", "available"]
EVENT_TYPES = ["attach", "detach"]
ALERT_SEVERITIES = ["low", "medium", "high", "critical"]
SNAPSHOT_STATUSES = ["completed", "pending", "failed"]

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)


def create_tables(conn):
    """Create all database tables."""
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            department TEXT NOT NULL,
            budget_limit REAL NOT NULL,
            current_spend REAL NOT NULL,
            created_at TEXT NOT NULL,
            owner_email TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS volumes (
            volume_id TEXT PRIMARY KEY,
            volume_name TEXT NOT NULL,
            project_id TEXT NOT NULL,
            size_gb INTEGER NOT NULL,
            volume_type TEXT NOT NULL,
            region TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS attachment_events (
            event_id TEXT PRIMARY KEY,
            volume_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_timestamp TEXT NOT NULL,
            FOREIGN KEY (volume_id) REFERENCES volumes(volume_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT PRIMARY KEY,
            volume_id TEXT NOT NULL,
            snapshot_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            size_gb INTEGER NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (volume_id) REFERENCES volumes(volume_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS budget_alerts (
            alert_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            threshold_pct REAL NOT NULL,
            triggered_at TEXT NOT NULL,
            severity TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
    """)

    conn.commit()


def generate_projects(conn, n_projects):
    """Generate project records."""
    projects = []
    for i in range(n_projects):
        pid = f"proj-{i+1:04d}"
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        budget = round(random.uniform(5000, 50000), 2)
        spend = round(random.uniform(budget * 0.3, budget * 1.1), 2)
        created = REFERENCE_DATE - timedelta(days=random.randint(180, 730))
        projects.append({
            "project_id": pid,
            "project_name": fake.catch_phrase().replace("'", ""),
            "department": dept,
            "budget_limit": budget,
            "current_spend": spend,
            "created_at": created.strftime("%Y-%m-%d"),
            "owner_email": fake.email(),
        })
    df = pd.DataFrame(projects)
    df.to_sql("projects", conn, if_exists="replace", index=False)
    return projects


def generate_volumes(conn, n_volumes, projects):
    """Generate volume records with controlled attachment status."""
    volumes = []
    project_ids = [p["project_id"] for p in projects]

    for i in range(n_volumes):
        vid = f"vol-{i+1:06d}"
        proj = random.choice(project_ids)
        size = random.choice([10, 20, 50, 100, 200, 500, 1000])
        vtype = random.choice(VOLUME_TYPES)
        region = random.choice(REGIONS)
        created = REFERENCE_DATE - timedelta(days=random.randint(30, 500))

        # ~40% of volumes are currently "available" (unattached)
        if random.random() < 0.4:
            status = "available"
        else:
            status = "attached"

        volumes.append({
            "volume_id": vid,
            "volume_name": f"{fake.word()}-{fake.word()}-vol",
            "project_id": proj,
            "size_gb": size,
            "volume_type": vtype,
            "region": region,
            "status": status,
            "created_at": created.strftime("%Y-%m-%d"),
            "description": fake.sentence(nb_words=8),
        })

    df = pd.DataFrame(volumes)
    df.to_sql("volumes", conn, if_exists="replace", index=False)
    return volumes


def generate_attachment_events(conn, volumes, n_events_per_vol_range=(1, 6)):
    """Generate attachment/detach event history for volumes."""
    events = []
    eid = 0
    for vol in volumes:
        vol_created = datetime.strptime(vol["created_at"], "%Y-%m-%d")
        n_events = random.randint(*n_events_per_vol_range)

        # Generate event timestamps after volume creation
        max_days = max(1, (REFERENCE_DATE - vol_created).days - 1)
        event_times = sorted([
            vol_created + timedelta(days=random.randint(1, max_days))
            for _ in range(n_events)
        ])

        # Alternate attach/detach, always starting with attach
        for j, ts in enumerate(event_times):
            eid += 1
            etype = "attach" if j % 2 == 0 else "detach"
            inst_id = f"inst-{random.randint(1000, 9999)}"
            events.append({
                "event_id": f"evt-{eid:06d}",
                "volume_id": vol["volume_id"],
                "instance_id": inst_id,
                "event_type": etype,
                "event_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            })

        # For "available" volumes, ensure last event is a detach
        if vol["status"] == "available":
            vol_events = [e for e in events if e["volume_id"] == vol["volume_id"]]
            if vol_events and vol_events[-1]["event_type"] == "attach":
                eid += 1
                last_ts = datetime.strptime(vol_events[-1]["event_timestamp"], "%Y-%m-%d %H:%M:%S")
                detach_ts = last_ts + timedelta(days=random.randint(1, 30))
                if detach_ts >= REFERENCE_DATE:
                    detach_ts = REFERENCE_DATE - timedelta(days=random.randint(1, 30))
                events.append({
                    "event_id": f"evt-{eid:06d}",
                    "volume_id": vol["volume_id"],
                    "instance_id": vol_events[-1]["instance_id"],
                    "event_type": "detach",
                    "event_timestamp": detach_ts.strftime("%Y-%m-%d %H:%M:%S"),
                })

    df = pd.DataFrame(events)
    df.to_sql("attachment_events", conn, if_exists="replace", index=False)
    return events


def generate_snapshots(conn, volumes, n_snapshots_base):
    """Generate snapshot records for volumes."""
    snapshots = []
    sid = 0
    for vol in volumes:
        n_snaps = random.randint(0, 5)
        vol_created = datetime.strptime(vol["created_at"], "%Y-%m-%d")
        days_range = max(1, (REFERENCE_DATE - vol_created).days)
        for _ in range(n_snaps):
            sid += 1
            snap_date = vol_created + timedelta(days=random.randint(1, days_range))
            snapshots.append({
                "snapshot_id": f"snap-{sid:06d}",
                "volume_id": vol["volume_id"],
                "snapshot_name": f"snap-{vol['volume_name']}-{sid}",
                "created_at": snap_date.strftime("%Y-%m-%d"),
                "size_gb": max(1, vol["size_gb"] // random.randint(1, 4)),
                "status": random.choices(SNAPSHOT_STATUSES, weights=[0.8, 0.1, 0.1])[0],
            })

    # Pad if needed to meet row count
    while len(snapshots) < n_snapshots_base:
        sid += 1
        vol = random.choice(volumes)
        vol_created = datetime.strptime(vol["created_at"], "%Y-%m-%d")
        days_range = max(1, (REFERENCE_DATE - vol_created).days)
        snap_date = vol_created + timedelta(days=random.randint(1, days_range))
        snapshots.append({
            "snapshot_id": f"snap-{sid:06d}",
            "volume_id": vol["volume_id"],
            "snapshot_name": f"snap-{vol['volume_name']}-{sid}",
            "created_at": snap_date.strftime("%Y-%m-%d"),
            "size_gb": max(1, vol["size_gb"] // random.randint(1, 4)),
            "status": random.choices(SNAPSHOT_STATUSES, weights=[0.8, 0.1, 0.1])[0],
        })

    df = pd.DataFrame(snapshots)
    df.to_sql("snapshots", conn, if_exists="replace", index=False)
    return snapshots


def generate_budget_alerts(conn, projects, n_alerts_base):
    """Generate budget alert records."""
    alerts = []
    aid = 0
    alert_types = ["spending_spike", "near_limit", "over_limit", "forecast_overrun"]

    for proj in projects:
        n_alerts = random.randint(0, 4)
        for _ in range(n_alerts):
            aid += 1
            triggered = REFERENCE_DATE - timedelta(days=random.randint(1, 180))
            alerts.append({
                "alert_id": f"alert-{aid:04d}",
                "project_id": proj["project_id"],
                "alert_type": random.choice(alert_types),
                "threshold_pct": random.choice([50, 75, 80, 90, 95, 100]),
                "triggered_at": triggered.strftime("%Y-%m-%d"),
                "severity": random.choice(ALERT_SEVERITIES),
                "resolved": random.choice([0, 1]),
            })

    while len(alerts) < n_alerts_base:
        aid += 1
        proj = random.choice(projects)
        triggered = REFERENCE_DATE - timedelta(days=random.randint(1, 180))
        alerts.append({
            "alert_id": f"alert-{aid:04d}",
            "project_id": proj["project_id"],
            "alert_type": random.choice(alert_types),
            "threshold_pct": random.choice([50, 75, 80, 90, 95, 100]),
            "triggered_at": triggered.strftime("%Y-%m-%d"),
            "severity": random.choice(ALERT_SEVERITIES),
            "resolved": random.choice([0, 1]),
        })

    df = pd.DataFrame(alerts)
    df.to_sql("budget_alerts", conn, if_exists="replace", index=False)
    return alerts


# ──────────────────────────────────────────────────────────────
# Workspace generation
# ──────────────────────────────────────────────────────────────

def generate_workspace(workspace, volumes, projects, snapshots, events, alerts):
    """Generate all workspace files: fixed config + scalable data files."""
    os.makedirs(workspace, exist_ok=True)

    # ── Fixed config files (not counted in SCALE["num_workspace_files"]) ──

    # 1. Reclamation policy
    policy = {
        "reclamation_policy": {
            "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
            "unattached_threshold_days": 90,
            "exclude_volume_labels": ["retain", "do-not-delete", "compliance-hold"],
            "exclude_volumes_in_maintenance": True,
            "report_sort_primary": "estimated_monthly_savings",
            "report_sort_order": "descending",
            "report_sort_tiebreaker": "days_unattached",
            "report_tiebreaker_order": "descending",
            "savings_formula": "size_gb * base_price_per_gb * region_multiplier",
        }
    }
    with open(os.path.join(workspace, "reclamation_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. Pricing tiers (base price per GB per month by volume type)
    pricing = {
        "pricing_tiers": {
            "ssd": 0.10,
            "hdd": 0.04,
            "nvme": 0.18,
            "cold-storage": 0.02,
        },
        "currency": "USD",
        "billing_cycle": "monthly",
    }
    with open(os.path.join(workspace, "pricing_tiers.json"), "w") as f:
        json.dump(pricing, f, indent=2)

    # 3. Region multipliers
    region_mult = [
        {"region": "us-east-1", "multiplier": 1.0},
        {"region": "us-west-2", "multiplier": 1.05},
        {"region": "eu-west-1", "multiplier": 1.15},
        {"region": "ap-southeast-1", "multiplier": 1.25},
    ]
    with open(os.path.join(workspace, "region_multipliers.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["region", "multiplier"])
        w.writeheader()
        w.writerows(region_mult)

    # ── Scalable data files ──
    n_files = SCALE["num_workspace_files"]

    # Determine label assignments: ~15% of available volumes get "exempt" labels
    exempt_labels = ["retain", "do-not-delete", "compliance-hold"]
    vol_labels = {}
    for v in volumes:
        labels = []
        labels.append(random.choice(["production", "staging", "development", "test"]))
        if random.random() < 0.3:
            labels.append(random.choice(["backup", "archive", "migration", "temporary"]))
        if v["status"] == "available" and random.random() < 0.15:
            labels.append(random.choice(exempt_labels))
        vol_labels[v["volume_id"]] = labels

    # Distribute files across formats
    n_csv = max(1, round(n_files * 0.3))
    n_json = max(1, round(n_files * 0.3))
    n_txt = max(1, round(n_files * 0.2))
    n_yaml = n_files - n_csv - n_json - n_txt
    if n_yaml < 1:
        n_yaml = 1
        n_csv = n_files - n_json - n_txt - n_yaml

    # CSV: volume label files
    vol_list = list(vol_labels.items())
    batch_size_csv = max(1, len(vol_list) // n_csv)

    for i in range(n_csv):
        start = i * batch_size_csv
        end = len(vol_list) if i == n_csv - 1 else (i + 1) * batch_size_csv
        batch = vol_list[start:end]
        filepath = os.path.join(workspace, f"volume_labels_batch_{i+1}.csv")
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["volume_id", "labels"])
            for vid, lbls in batch:
                w.writerow([vid, "; ".join(lbls)])

    # JSON: cost history files
    vol_batch_json = max(1, len(volumes) // n_json)
    for i in range(n_json):
        start = i * vol_batch_json
        end = len(volumes) if i == n_json - 1 else (i + 1) * vol_batch_json
        batch_vols = volumes[start:end]
        records = []
        for v in batch_vols:
            for m in range(random.randint(1, 3)):
                month_offset = random.randint(1, 6)
                period = (REFERENCE_DATE - timedelta(days=30 * month_offset)).strftime("%Y-%m")
                records.append({
                    "volume_id": v["volume_id"],
                    "period": period,
                    "billed_amount": round(
                        v["size_gb"] * random.uniform(0.02, 0.20) * random.uniform(0.9, 1.3), 2
                    ),
                    "currency": "USD",
                })
        filepath = os.path.join(workspace, f"cost_history_{i+1}.json")
        with open(filepath, "w") as f:
            json.dump(records, f, indent=2)

    # TXT: snapshot audit logs
    snap_batch = max(1, len(snapshots) // n_txt)
    for i in range(n_txt):
        start = i * snap_batch
        end = len(snapshots) if i == n_txt - 1 else (i + 1) * snap_batch
        batch_snaps = snapshots[start:end]
        filepath = os.path.join(workspace, f"snapshot_audit_{i+1}.txt")
        with open(filepath, "w") as f:
            f.write(f"Snapshot Audit Log - Batch {i+1}\n")
            f.write(f"Generated: {REFERENCE_DATE.strftime('%Y-%m-%d')}\n")
            f.write("=" * 60 + "\n\n")
            for s in batch_snaps:
                f.write(f"Snapshot: {s['snapshot_id']}\n")
                f.write(f"  Volume: {s['volume_id']}\n")
                f.write(f"  Name: {s['snapshot_name']}\n")
                f.write(f"  Created: {s['created_at']}\n")
                f.write(f"  Size: {s['size_gb']} GB\n")
                f.write(f"  Status: {s['status']}\n")
                retention = random.choice(["30-day", "60-day", "90-day", "365-day", "indefinite"])
                f.write(f"  Retention: {retention}\n")
                f.write("\n")

    # YAML: maintenance schedule files
    maintenance_vols = random.sample(
        [v["volume_id"] for v in volumes],
        min(max(2, len(volumes) // 15), len(volumes))
    )
    maint_batch = max(1, len(maintenance_vols) // n_yaml)
    for i in range(n_yaml):
        start = i * maint_batch
        end = len(maintenance_vols) if i == n_yaml - 1 else (i + 1) * maint_batch
        batch_maint = maintenance_vols[start:end]
        schedules = []
        for vid in batch_maint:
            maint_start = REFERENCE_DATE - timedelta(days=random.randint(0, 5))
            maint_end = maint_start + timedelta(days=random.randint(3, 14))
            schedules.append({
                "volume_id": vid,
                "maintenance_type": random.choice([
                    "firmware_update", "migration", "health_check", "encryption_rotation"
                ]),
                "window_start": maint_start.strftime("%Y-%m-%d"),
                "window_end": maint_end.strftime("%Y-%m-%d"),
                "status": "active",
            })
        filepath = os.path.join(workspace, f"maintenance_schedule_{i+1}.yaml")
        with open(filepath, "w") as f:
            yaml.dump({"maintenance_windows": schedules}, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    # Reset seeds for reproducibility
    Faker.seed(42)
    random.seed(42)
    np.random.seed(42)

    n_rows = SCALE["rows_per_table"]

    # Number of projects: ~20% of row count, at least 5
    n_projects = max(5, n_rows // 5)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    projects = generate_projects(conn, n_projects)
    volumes = generate_volumes(conn, n_rows, projects)
    events = generate_attachment_events(conn, volumes)
    snapshots = generate_snapshots(conn, volumes, n_rows)
    alerts = generate_budget_alerts(conn, projects, n_rows)

    conn.commit()
    conn.close()

    generate_workspace(args.workspace, volumes, projects, snapshots, events, alerts)
    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"  Volumes: {len(volumes)}")
    print(f"  Projects: {len(projects)}")
    print(f"  Events: {len(events)}")
    print(f"  Snapshots: {len(snapshots)}")
    print(f"  Alerts: {len(alerts)}")


if __name__ == "__main__":
    main()
