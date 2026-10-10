#!/usr/bin/env python3
"""Data generation for disaster recovery compliance audit task."""
import argparse
import csv
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml
from faker import Faker

# ── Seeds ────────────────────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ── Scale parameters (v0 base) ──────────────────────────────────────────────
SCALE = {
    "rows_per_table": 800,       # v3 = 8x base
    "num_workspace_files": 40,   # v3 = base + 3N
}

# ── Domain constants ────────────────────────────────────────────────────────
PROVIDERS = ["CloudNova", "AzureWave", "NetVault", "SkyGrid", "DataPeak"]
REGIONS = {
    "CloudNova": ["us-east-1", "us-west-2", "eu-central-1"],
    "AzureWave": ["eastus", "southeastasia", "westeurope"],
    "NetVault": ["us-central", "eu-north", "ap-east"],
    "SkyGrid": ["us-west", "eu-south", "ap-north"],
    "DataPeak": ["us-east", "eu-central", "ap-west"],
}
ALL_PR = [(p, r) for p in PROVIDERS for r in REGIONS[p]]  # 15 combos

TIERS = ["platinum", "gold", "silver"]
SERVICE_TYPES = ["database", "storage", "application", "messaging", "cache", "analytics"]
SERVICE_WORDS = [
    "phoenix", "atlas", "nexus", "titan", "nova", "echo", "pulse", "apex",
    "core", "flux", "omega", "prime", "vega", "orion", "zenith", "delta",
    "sigma", "kappa", "gamma", "theta", "helix", "cipher", "prism", "quark",
]

TIER_THRESHOLDS = {
    "platinum": {
        "max_avg_replication_lag_ms": 50,
        "max_p95_replication_lag_ms": 100,
        "min_snapshot_success_rate_pct": 99.0,
        "min_dns_success_rate_pct": 99.5,
        "min_health_uptime_pct": 99.9,
        "max_dr_drill_age_days": 90,
    },
    "gold": {
        "max_avg_replication_lag_ms": 100,
        "max_p95_replication_lag_ms": 200,
        "min_snapshot_success_rate_pct": 95.0,
        "min_dns_success_rate_pct": 99.0,
        "min_health_uptime_pct": 99.5,
        "max_dr_drill_age_days": 180,
    },
    "silver": {
        "max_avg_replication_lag_ms": 200,
        "max_p95_replication_lag_ms": 400,
        "min_snapshot_success_rate_pct": 90.0,
        "min_dns_success_rate_pct": 98.0,
        "min_health_uptime_pct": 99.0,
        "max_dr_drill_age_days": 365,
    },
}

REFERENCE_DATE = datetime(2026, 4, 20)

GAP_PROBABILITIES = {
    "replication_lag": 0.15,
    "snapshot_compliance": 0.15,
    "retention_shortfall": 0.20,
    "dns_failover": 0.12,
    "failover_mismatch": 0.10,
    "health_uptime": 0.12,
    "dr_drill_overdue": 0.15,
}

RECORDS_PER_SERVICE = {
    "replication": 5,
    "snapshot": 4,
    "dns": 4,
    "health": 5,
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_gap_flags(num_services):
    """Deterministic per-service gap assignments (independent of scale)."""
    flags = {}
    for sid in range(1, num_services + 1):
        rng = random.Random(42 + sid)
        flags[sid] = {k: rng.random() < v for k, v in GAP_PROBABILITIES.items()}
    return flags


def generate_services(n):
    """Generate *n* DR-monitored service records."""
    services = []
    for i in range(n):
        sid = i + 1
        rng = random.Random(100 + sid)
        provider, region = ALL_PR[i % len(ALL_PR)]
        tier = rng.choice(TIERS)
        svc_type = rng.choice(SERVICE_TYPES)
        word = rng.choice(SERVICE_WORDS)
        name = f"{svc_type}-{word}-{sid:04d}"
        is_primary = 1 if rng.random() < 0.7 else 0
        failover_priority = rng.randint(1, 5)
        created = (REFERENCE_DATE - timedelta(days=rng.randint(30, 730))).strftime("%Y-%m-%d")
        services.append({
            "id": sid, "provider": provider, "region": region,
            "service_name": name, "service_type": svc_type, "tier": tier,
            "is_primary": is_primary, "failover_priority": failover_priority,
            "created_date": created,
        })
    return services


def generate_service_dr_configs(services, gap_flags):
    """Per-service DR configuration (written to workspace, NOT stored in DB)."""
    configs = []
    for svc in services:
        sid = svc["id"]
        rng = random.Random(5000 + sid)
        tier = svc["tier"]
        provider = svc["provider"]
        region = svc["region"]

        rto = rng.choice([15, 30, 60, 120, 240])
        rpo = rng.choice([5, 15, 30, 60, 120])

        if gap_flags[sid]["retention_shortfall"]:
            retention_req = rng.choice([60, 90, 120])
        else:
            retention_req = rng.choice([7, 14, 30])

        other_regions = [r for r in REGIONS[provider] if r != region]
        designated = rng.choice(other_regions) if other_regions else region

        max_age = TIER_THRESHOLDS[tier]["max_dr_drill_age_days"]
        if gap_flags[sid]["dr_drill_overdue"]:
            days_ago = rng.randint(max_age + 20, max_age + 400)
        else:
            days_ago = rng.randint(1, max(1, max_age - 5))
        last_drill = (REFERENCE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        drill_result = rng.choice(["pass", "pass", "pass", "fail"])

        email = f"dr-{sid:04d}@{provider.lower()}.example.com"

        configs.append({
            "service_id": sid,
            "rto_minutes": rto,
            "rpo_minutes": rpo,
            "backup_retention_required_days": retention_req,
            "designated_failover_region": designated,
            "dr_contact_email": email,
            "last_dr_drill_date": last_drill,
            "dr_drill_result": drill_result,
        })
    return configs


# ── Database creation ────────────────────────────────────────────────────────

def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dr_services (
            id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            region TEXT NOT NULL,
            service_name TEXT NOT NULL,
            service_type TEXT NOT NULL,
            tier TEXT NOT NULL,
            is_primary INTEGER NOT NULL,
            failover_priority INTEGER NOT NULL,
            created_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS replication_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            measured_at TEXT NOT NULL,
            lag_ms REAL NOT NULL,
            replication_status TEXT NOT NULL,
            db_instance TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES dr_services(id)
        );
        CREATE TABLE IF NOT EXISTS snapshot_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            snapshot_time TEXT NOT NULL,
            size_gb REAL NOT NULL,
            retention_days INTEGER NOT NULL,
            status TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES dr_services(id)
        );
        CREATE TABLE IF NOT EXISTS dns_failover_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            test_time TEXT NOT NULL,
            response_time_ms REAL NOT NULL,
            success INTEGER NOT NULL,
            failover_target_region TEXT NOT NULL,
            test_type TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES dr_services(id)
        );
        CREATE TABLE IF NOT EXISTS health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            check_time TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            latency_ms REAL NOT NULL,
            healthy INTEGER NOT NULL,
            FOREIGN KEY (service_id) REFERENCES dr_services(id)
        );
    """)


def insert_services(conn, services):
    conn.executemany(
        "INSERT INTO dr_services VALUES (?,?,?,?,?,?,?,?,?)",
        [(s["id"], s["provider"], s["region"], s["service_name"],
          s["service_type"], s["tier"], s["is_primary"],
          s["failover_priority"], s["created_date"]) for s in services],
    )
    conn.commit()


# ── Metric generation ────────────────────────────────────────────────────────

def generate_replication_metrics(conn, services, gap_flags):
    rps = RECORDS_PER_SERVICE["replication"]
    base_time = datetime(2026, 4, 1)
    rows = []
    for svc in services:
        sid = svc["id"]
        threshold = TIER_THRESHOLDS[svc["tier"]]["max_avg_replication_lag_ms"]
        has_gap = gap_flags[sid]["replication_lag"]
        nrng = np.random.RandomState(1000 + sid)
        rng = random.Random(1000 + sid)

        if has_gap:
            lags = nrng.uniform(threshold * 1.1, threshold * 2.5, size=rps)
        else:
            lags = nrng.uniform(threshold * 0.1, threshold * 0.75, size=rps)

        for j in range(rps):
            ts = base_time + timedelta(hours=j * 6 + rng.randint(0, 3))
            lag = round(float(lags[j]), 2)
            status = "healthy" if lag < threshold else ("degraded" if lag < threshold * 1.5 else "critical")
            inst = f"db-{sid:04d}-{['primary','replica-1','replica-2'][j % 3]}"
            rows.append((sid, ts.isoformat(), lag, status, inst))

    conn.executemany(
        "INSERT INTO replication_metrics (service_id, measured_at, lag_ms, replication_status, db_instance) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()


def generate_snapshot_records(conn, services, gap_flags, dr_configs):
    rps = RECORDS_PER_SERVICE["snapshot"]
    base_time = datetime(2026, 4, 1)
    cfg_map = {c["service_id"]: c for c in dr_configs}
    rows = []

    for svc in services:
        sid = svc["id"]
        nrng = np.random.RandomState(2000 + sid)
        rng = random.Random(2000 + sid)
        has_snap_gap = gap_flags[sid]["snapshot_compliance"]
        has_ret_gap = gap_flags[sid]["retention_shortfall"]
        required_ret = cfg_map[sid]["backup_retention_required_days"]

        fail_indices = set()
        if has_snap_gap:
            nf = rng.randint(1, 2)
            fail_indices = set(rng.sample(range(rps), nf))

        sizes = nrng.uniform(0.5, 50.0, size=rps)

        for j in range(rps):
            ts = base_time + timedelta(hours=j * 12 + rng.randint(0, 5))
            size = round(float(sizes[j]), 2)
            status = "failed" if j in fail_indices else "completed"
            if has_ret_gap:
                retention = rng.randint(1, max(1, required_ret - 5))
            else:
                retention = rng.randint(required_ret, required_ret + 60)
            schedule = rng.choice(["hourly", "daily", "weekly"])
            rows.append((sid, ts.isoformat(), size, retention, status, schedule))

    conn.executemany(
        "INSERT INTO snapshot_records (service_id, snapshot_time, size_gb, retention_days, status, schedule_type) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def generate_dns_failover_logs(conn, services, gap_flags, dr_configs):
    rps = RECORDS_PER_SERVICE["dns"]
    base_time = datetime(2026, 4, 1)
    cfg_map = {c["service_id"]: c for c in dr_configs}
    rows = []

    for svc in services:
        sid = svc["id"]
        nrng = np.random.RandomState(3000 + sid)
        rng = random.Random(3000 + sid)
        has_dns_gap = gap_flags[sid]["dns_failover"]
        has_fm_gap = gap_flags[sid]["failover_mismatch"]
        provider = svc["provider"]
        region = svc["region"]
        designated = cfg_map[sid]["designated_failover_region"]

        if has_fm_gap:
            others = [r for r in REGIONS[provider] if r != region and r != designated]
            target = rng.choice(others) if others else region
        else:
            target = designated

        fail_indices = set()
        if has_dns_gap:
            nf = rng.randint(1, 2)
            fail_indices = set(rng.sample(range(rps), nf))

        resp_times = nrng.uniform(10, 500, size=rps)

        for j in range(rps):
            ts = base_time + timedelta(hours=j * 24 + rng.randint(0, 12))
            rt = round(float(resp_times[j]), 2)
            success = 0 if j in fail_indices else 1
            ttype = rng.choice(["automatic", "manual"])
            rows.append((sid, ts.isoformat(), rt, success, target, ttype))

    conn.executemany(
        "INSERT INTO dns_failover_logs (service_id, test_time, response_time_ms, success, failover_target_region, test_type) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def generate_health_checks(conn, services, gap_flags):
    rps = RECORDS_PER_SERVICE["health"]
    base_time = datetime(2026, 4, 1)
    rows = []

    for svc in services:
        sid = svc["id"]
        nrng = np.random.RandomState(4000 + sid)
        rng = random.Random(4000 + sid)
        has_gap = gap_flags[sid]["health_uptime"]

        bad_indices = set()
        if has_gap:
            nb = rng.randint(1, 2)
            bad_indices = set(rng.sample(range(rps), nb))

        latencies = nrng.uniform(5, 200, size=rps)

        for j in range(rps):
            ts = base_time + timedelta(hours=j * 4 + rng.randint(0, 2))
            endpoint = f"https://{svc['service_name']}.{svc['provider'].lower()}.internal/health"
            lat = round(float(latencies[j]), 2)
            if j in bad_indices:
                healthy = 0
                code = rng.choice([500, 502, 503, 504, 408])
            else:
                healthy = 1
                code = 200
            rows.append((sid, ts.isoformat(), endpoint, code, lat, healthy))

    conn.executemany(
        "INSERT INTO health_checks (service_id, check_time, endpoint, status_code, latency_ms, healthy) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


# ── Workspace file generation ────────────────────────────────────────────────

SEVERITY_MATRIX_ROWS = [
    ["gap_category", "deviation_pct_min", "deviation_pct_max", "severity"],
    ["replication_lag", "0", "25", "low"],
    ["replication_lag", "25", "50", "medium"],
    ["replication_lag", "50", "100", "high"],
    ["replication_lag", "100", "", "critical"],
    ["snapshot_compliance", "0", "15", "low"],
    ["snapshot_compliance", "15", "35", "medium"],
    ["snapshot_compliance", "35", "60", "high"],
    ["snapshot_compliance", "60", "", "critical"],
    ["retention_shortfall", "0", "20", "low"],
    ["retention_shortfall", "20", "45", "medium"],
    ["retention_shortfall", "45", "70", "high"],
    ["retention_shortfall", "70", "", "critical"],
    ["dns_failover", "0", "5", "low"],
    ["dns_failover", "5", "15", "medium"],
    ["dns_failover", "15", "30", "high"],
    ["dns_failover", "30", "", "critical"],
    ["failover_mismatch", "0", "", "high"],
    ["health_uptime", "0", "2", "low"],
    ["health_uptime", "2", "5", "medium"],
    ["health_uptime", "5", "10", "high"],
    ["health_uptime", "10", "", "critical"],
    ["dr_drill_overdue", "0", "50", "low"],
    ["dr_drill_overdue", "50", "100", "medium"],
    ["dr_drill_overdue", "100", "200", "high"],
    ["dr_drill_overdue", "200", "", "critical"],
]


def write_fixed_workspace_files(workspace):
    """Write policy / threshold / guideline files (do not scale with SCALE)."""

    # 1. compliance_thresholds.yaml
    with open(os.path.join(workspace, "compliance_thresholds.yaml"), "w") as f:
        yaml.dump({"tiers": TIER_THRESHOLDS}, f, default_flow_style=False, sort_keys=False)

    # 2. dr_policy.json
    policy = {
        "audit_name": "Q2 2026 Disaster Recovery Compliance Audit",
        "reference_date": "2026-04-20",
        "audit_scope": "All monitored DR services across all providers and regions",
        "gap_categories": [
            "replication_lag", "snapshot_compliance", "retention_shortfall",
            "dns_failover", "failover_mismatch", "health_uptime", "dr_drill_overdue",
        ],
    }
    with open(os.path.join(workspace, "dr_policy.json"), "w") as f:
        json.dump(policy, f, indent=2)

    # 3. severity_matrix.csv
    with open(os.path.join(workspace, "severity_matrix.csv"), "w", newline="") as f:
        csv.writer(f).writerows(SEVERITY_MATRIX_ROWS)

    # 4. audit_guidelines.md
    guidelines = (
        "This document outlines the disaster recovery compliance audit procedures "
        "for Q2 2026.\n\n"
        "All services registered in the monitoring system must be evaluated against "
        "their assigned compliance tier. Each tier defines specific thresholds for "
        "replication performance, snapshot reliability, DNS failover readiness, health "
        "check consistency, and disaster recovery drill recency.\n\n"
        "The audit process involves collecting aggregated metrics from all monitoring "
        "endpoints, cross-referencing actual performance with per-service disaster "
        "recovery configurations, and identifying any deviations from established "
        "thresholds. Each deviation is classified according to the severity matrix, "
        "which maps the magnitude of non-compliance to a severity level.\n\n"
        "Services operating under higher tiers such as platinum are subject to stricter "
        "thresholds and shorter drill cycles. The reference date for all time-based "
        "calculations is specified in the audit policy document.\n\n"
        "For escalation purposes, the DR operations team can be reached at "
        "dr-ops@infrastructure.internal. Critical and high severity gaps must be "
        "escalated within 24 hours of identification. Medium severity gaps should be "
        "addressed within one business week. Low severity gaps are tracked for the "
        "next quarterly review.\n\n"
        "All calculations should use the data as recorded in the monitoring systems "
        "without rounding intermediate results. Only final output values should be "
        "rounded as specified in the reporting requirements.\n"
    )
    with open(os.path.join(workspace, "audit_guidelines.md"), "w") as f:
        f.write(guidelines)


BATCH_FORMATS = ["json", "csv", "yaml", "txt"]


def write_service_config_files(workspace, services, dr_configs, num_files):
    """Write scaling service DR-config batch files in rotating formats."""
    cfg_map = {c["service_id"]: c for c in dr_configs}
    batch_size = max(1, len(services) // num_files)
    batches = []
    for i in range(num_files):
        start = i * batch_size
        end = len(services) if i == num_files - 1 else start + batch_size
        batches.append([cfg_map[s["id"]] for s in services[start:end]])

    for i, batch in enumerate(batches):
        fmt = BATCH_FORMATS[i % len(BATCH_FORMATS)]
        fname = f"service_dr_config_batch_{i + 1:02d}.{fmt}"
        fpath = os.path.join(workspace, fname)

        if fmt == "json":
            with open(fpath, "w") as f:
                json.dump(batch, f, indent=2)

        elif fmt == "csv":
            if batch:
                df = pd.DataFrame(batch)
                df.to_csv(fpath, index=False)

        elif fmt == "yaml":
            with open(fpath, "w") as f:
                yaml.dump(batch, f, default_flow_style=False, sort_keys=False)

        elif fmt == "txt":
            with open(fpath, "w") as f:
                for j, cfg in enumerate(batch):
                    if j > 0:
                        f.write("\n")
                    for k, v in cfg.items():
                        f.write(f"{k}={v}\n")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate DR audit data")
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)

    num_services = SCALE["rows_per_table"]
    num_files = SCALE["num_workspace_files"]

    services = generate_services(num_services)
    gap_flags = compute_gap_flags(num_services)
    dr_configs = generate_service_dr_configs(services, gap_flags)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    insert_services(conn, services)
    generate_replication_metrics(conn, services, gap_flags)
    generate_snapshot_records(conn, services, gap_flags, dr_configs)
    generate_dns_failover_logs(conn, services, gap_flags, dr_configs)
    generate_health_checks(conn, services, gap_flags)
    conn.close()

    write_fixed_workspace_files(args.workspace)
    write_service_config_files(args.workspace, services, dr_configs, num_files)

    print(f"Generated {num_services} services, {num_files} config batch files")
    print(f"DB tables: dr_services, replication_metrics, snapshot_records, dns_failover_logs, health_checks")


if __name__ == "__main__":
    main()
