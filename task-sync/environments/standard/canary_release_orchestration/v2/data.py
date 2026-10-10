"""
data.py - Canary Release Decision Task Data Generator

Generates database and workspace files for evaluating canary deployments.
"""

import argparse
import os
import sqlite3
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 24,
}

fake = Faker()
Faker.seed(42)
np.random.seed(42)

# --- Constants for deterministic name generation ---
SERVICE_DOMAINS = [
    "auth", "payment", "inventory", "notification", "analytics",
    "search", "recommendation", "shipping", "billing", "user",
    "order", "catalog", "review", "messaging", "monitoring",
    "gateway", "cache", "config", "logging", "scheduler",
]
SERVICE_FUNCTIONS = [
    "api", "worker", "processor", "handler", "manager",
    "service", "engine", "proxy", "aggregator", "validator",
]
TIERS = ["critical", "standard", "experimental"]
METRIC_TYPES = ["latency_p50", "latency_p95", "error_rate", "cpu_usage", "memory_usage"]
ERROR_TYPES = [
    "NullPointerException", "TimeoutError", "ConnectionRefused",
    "AuthenticationFailure", "RateLimitExceeded", "DatabaseError",
    "SerializationError", "OutOfMemoryError", "ConfigurationError",
    "ValidationError",
]
TEAMS = ["platform", "payments", "growth", "infrastructure",
         "data-eng", "security", "mobile", "web-frontend"]
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
SCENARIOS = [
    "login_flow", "checkout_flow", "search_query", "data_fetch",
    "api_health_check", "payment_process", "user_registration",
    "inventory_check", "session_refresh", "report_generation",
]
FLAG_NAMES_POOL = [
    "new_ui_v2", "enhanced_logging", "rate_limit_v3", "cache_optimization",
    "async_processing", "ml_recommendations", "dark_mode", "beta_dashboard",
    "new_checkout", "advanced_search", "real_time_sync", "auto_scaling",
    "smart_routing", "ab_test_pricing", "lazy_loading",
]


def generate_service_name(idx):
    d = idx % len(SERVICE_DOMAINS)
    f = (idx // len(SERVICE_DOMAINS)) % len(SERVICE_FUNCTIONS)
    suffix = idx // (len(SERVICE_DOMAINS) * len(SERVICE_FUNCTIONS))
    name = f"{SERVICE_DOMAINS[d]}-{SERVICE_FUNCTIONS[f]}"
    if suffix > 0:
        name += f"-{suffix}"
    return name


def create_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS services (
            service_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            team TEXT NOT NULL,
            tier TEXT NOT NULL,
            deployment_status TEXT NOT NULL,
            canary_version TEXT,
            stable_version TEXT NOT NULL,
            region TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance_metrics (
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metric_type TEXT NOT NULL,
            value REAL NOT NULL,
            environment TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(service_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS synthetic_transactions (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            test_scenario TEXT NOT NULL,
            status TEXT NOT NULL,
            response_time_ms REAL NOT NULL,
            environment TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(service_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            severity TEXT NOT NULL,
            environment TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(service_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feature_flags (
            flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            flag_name TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            rollout_percentage REAL NOT NULL,
            variant TEXT NOT NULL,
            targeting_rules TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(service_id)
        )
    """)
    conn.commit()


def generate_services(n_services):
    services = []
    n_canary = max(4, n_services // 4)

    # Determine which indices are canary
    indices = list(range(n_services))
    perm = np.random.permutation(indices).tolist()
    canary_set = set(perm[:n_canary])

    base_date = datetime(2026, 4, 1)
    tier_choices = np.random.choice(TIERS, size=n_services, p=[0.2, 0.5, 0.3]).tolist()

    for i in range(n_services):
        svc_id = f"svc_{i:04d}"
        svc_name = generate_service_name(i)
        team = TEAMS[i % len(TEAMS)]
        tier = tier_choices[i]
        status = "canary" if i in canary_set else "stable"
        major = int(np.random.randint(1, 5))
        minor = int(np.random.randint(0, 20))
        patch = int(np.random.randint(0, 100))
        stable_ver = f"{major}.{minor}.{patch}"
        canary_ver = f"{major}.{minor + 1}.0" if status == "canary" else None
        region = REGIONS[i % len(REGIONS)]
        created = (base_date - timedelta(days=int(np.random.randint(30, 365)))).isoformat()
        services.append({
            "service_id": svc_id,
            "service_name": svc_name,
            "team": team,
            "tier": tier,
            "deployment_status": status,
            "canary_version": canary_ver,
            "stable_version": stable_ver,
            "region": region,
            "created_at": created,
        })
    return services


def generate_performance_metrics(services):
    """Returns (rows, baselines_dict)."""
    rows = []
    baselines = {}
    base_time = datetime(2026, 4, 25, 8, 0, 0)
    timestamps = [(base_time + timedelta(minutes=10 * t)).isoformat() for t in range(5)]

    canary_svcs = [s for s in services if s["deployment_status"] == "canary"]
    stable_svcs = [s for s in services if s["deployment_status"] == "stable"]

    # Assign performance profiles: good / mid / bad
    n_c = len(canary_svcs)
    n_good = max(1, n_c // 3)
    n_bad = max(1, n_c // 4)
    profiles = (["good"] * n_good +
                ["mid"] * (n_c - n_good - n_bad) +
                ["bad"] * n_bad)
    np.random.shuffle(profiles)

    for idx, svc in enumerate(canary_svcs):
        profile = profiles[idx]
        bl_lat = float(np.random.uniform(20, 100))
        bl_err = float(np.random.uniform(0.005, 0.025))
        baselines[svc["service_id"]] = {
            "latency_p50": bl_lat,
            "error_rate": bl_err,
        }

        if profile == "good":
            deg = float(np.random.uniform(1.00, 1.08))
            err_f = float(np.random.uniform(0.6, 1.0))
        elif profile == "mid":
            deg = float(np.random.uniform(1.12, 1.22))
            err_f = float(np.random.uniform(1.0, 1.8))
        else:
            deg = float(np.random.uniform(1.30, 1.65))
            err_f = float(np.random.uniform(2.0, 4.0))

        for ts in timestamps:
            noise = float(np.random.uniform(0.95, 1.05))
            rows.append((svc["service_id"], ts, "latency_p50",
                         bl_lat * deg * noise, "canary"))
            rows.append((svc["service_id"], ts, "latency_p95",
                         bl_lat * deg * noise * float(np.random.uniform(2.0, 3.5)),
                         "canary"))
            err_noise = float(np.random.uniform(0.85, 1.15))
            rows.append((svc["service_id"], ts, "error_rate",
                         max(0.0, bl_err * err_f * err_noise), "canary"))
            rows.append((svc["service_id"], ts, "cpu_usage",
                         float(np.random.uniform(10, 80)), "canary"))
            rows.append((svc["service_id"], ts, "memory_usage",
                         float(np.random.uniform(20, 85)), "canary"))

            # Stable-env metrics for the same service (baseline-level)
            rows.append((svc["service_id"], ts, "latency_p50",
                         bl_lat * float(np.random.uniform(0.95, 1.05)), "stable"))
            rows.append((svc["service_id"], ts, "error_rate",
                         max(0.0, bl_err * float(np.random.uniform(0.85, 1.15))),
                         "stable"))

    # Stable-only services: fewer readings to pad table
    for svc in stable_svcs:
        for ts in timestamps[:2]:
            rows.append((svc["service_id"], ts, "latency_p50",
                         float(np.random.uniform(20, 100)), "stable"))
            rows.append((svc["service_id"], ts, "error_rate",
                         float(np.random.uniform(0.001, 0.04)), "stable"))

    return rows, baselines


def generate_synthetic_transactions(services):
    """Returns (rows, success_rate_dict)."""
    rows = []
    success_rates = {}
    base_time = datetime(2026, 4, 25, 7, 0, 0)

    canary_svcs = [s for s in services if s["deployment_status"] == "canary"]
    n_c = len(canary_svcs)
    n_good = max(1, n_c // 3)
    n_bad = max(1, n_c // 4)
    profiles = (["good"] * n_good +
                ["mid"] * (n_c - n_good - n_bad) +
                ["bad"] * n_bad)
    np.random.shuffle(profiles)

    for idx, svc in enumerate(canary_svcs):
        profile = profiles[idx]
        if profile == "good":
            sr = float(np.random.uniform(0.96, 0.995))
        elif profile == "mid":
            sr = float(np.random.uniform(0.90, 0.96))
        else:
            sr = float(np.random.uniform(0.72, 0.88))
        success_rates[svc["service_id"]] = sr

        n_txns = int(np.random.randint(15, 26))
        for j in range(n_txns):
            ts = (base_time + timedelta(minutes=int(np.random.randint(0, 600)))).isoformat()
            scenario = SCENARIOS[j % len(SCENARIOS)]
            if np.random.random() < sr:
                status = "success"
                resp = float(np.random.uniform(30, 400))
            else:
                status = np.random.choice(["failure", "timeout"])
                resp = float(np.random.uniform(500, 5000))
            rows.append((svc["service_id"], ts, scenario, status, resp, "canary"))

    # Stable-env baseline txns
    for svc in services:
        for j in range(3):
            ts = (base_time + timedelta(minutes=int(np.random.randint(0, 600)))).isoformat()
            rows.append((svc["service_id"], ts, SCENARIOS[j % len(SCENARIOS)],
                         "success", float(np.random.uniform(30, 250)), "stable"))

    return rows, success_rates


def generate_error_logs(services):
    """Returns (rows, critical_error_service_ids_set)."""
    rows = []
    critical_set = set()
    base_time = datetime(2026, 4, 25, 6, 0, 0)

    canary_svcs = [s for s in services if s["deployment_status"] == "canary"]

    for svc in canary_svcs:
        has_critical = bool(np.random.random() < 0.18)
        if has_critical:
            critical_set.add(svc["service_id"])

        n_errors = int(np.random.randint(5, 16))
        for j in range(n_errors):
            ts = (base_time + timedelta(minutes=int(np.random.randint(0, 720)))).isoformat()
            session = fake.uuid4()
            etype = str(np.random.choice(ERROR_TYPES))
            emsg = f"{etype}: {fake.sentence()}"
            if has_critical and j == 0:
                severity = "critical"
            else:
                severity = str(np.random.choice(["critical", "warning", "info"],
                                                p=[0.03, 0.37, 0.60]))
            rows.append((svc["service_id"], session, ts, etype, emsg, severity, "canary"))

    # Stable-env errors for all services
    for svc in services:
        n_errs = int(np.random.randint(1, 4))
        for j in range(n_errs):
            ts = (base_time + timedelta(minutes=int(np.random.randint(0, 720)))).isoformat()
            session = fake.uuid4()
            etype = str(np.random.choice(ERROR_TYPES))
            emsg = f"{etype}: {fake.sentence()}"
            severity = str(np.random.choice(["warning", "info"]))
            rows.append((svc["service_id"], session, ts, etype, emsg, severity, "stable"))

    return rows, critical_set


def generate_feature_flags(services):
    """Returns (rows, target_rollouts_dict)."""
    rows = []
    target_rollouts = {}

    for svc in services:
        n_flags = int(np.random.randint(2, 5))
        chosen = list(np.random.choice(FLAG_NAMES_POOL,
                                       size=min(n_flags, len(FLAG_NAMES_POOL)),
                                       replace=False))
        for flag_name in chosen:
            enabled = 1 if np.random.random() < 0.8 else 0
            if svc["deployment_status"] == "canary":
                target_pct = float(np.random.choice([25.0, 50.0, 75.0, 100.0]))
                actual_pct = min(100.0, target_pct * float(np.random.uniform(0.55, 1.15)))
                target_rollouts.setdefault(svc["service_id"], {})[str(flag_name)] = float(target_pct)
            else:
                actual_pct = float(np.random.choice([0.0, 100.0]))

            variant = str(np.random.choice(["control", "treatment_a", "treatment_b"]))
            rules = json.dumps({
                "user_segment": str(np.random.choice(["all", "beta", "internal", "percentage"]))
            })
            updated = (datetime(2026, 4, 24) +
                       timedelta(hours=int(np.random.randint(0, 24)))).isoformat()
            rows.append((svc["service_id"], str(flag_name), int(enabled),
                         float(actual_pct), variant, rules, updated))

    return rows, target_rollouts


# ─────────────────────── workspace files ───────────────────────


def _split_list(lst, n_parts):
    """Split list into n_parts roughly equal parts."""
    k, m = divmod(len(lst), n_parts)
    parts = []
    idx = 0
    for i in range(n_parts):
        size = k + (1 if i < m else 0)
        parts.append(lst[idx:idx + size])
        idx += size
    return parts


def write_workspace_files(workspace, services, baselines,
                          target_rollouts, critical_set):
    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]
    canary_svcs = [s for s in services if s["deployment_status"] == "canary"]

    # --- Distribute file counts across 4 types (csv, json, yaml, txt) ---
    n_csv = max(1, round(n_files * 3 / 8))
    n_json = max(1, round(n_files * 2 / 8))
    n_yaml = max(1, round(n_files * 2 / 8))
    n_txt = max(1, n_files - n_csv - n_json - n_yaml)
    # adjust to hit exact total
    total = n_csv + n_json + n_yaml + n_txt
    while total < n_files:
        n_csv += 1
        total += 1
    while total > n_files:
        if n_txt > 1:
            n_txt -= 1
        elif n_yaml > 1:
            n_yaml -= 1
        else:
            n_json = max(1, n_json - 1)
        total -= 1

    # ── CSV: service baselines ──
    batches_csv = _split_list(canary_svcs, n_csv)
    for i, batch in enumerate(batches_csv):
        path = os.path.join(workspace, f"service_baseline_{i + 1}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["service_id", "service_name",
                        "baseline_latency_p50_ms", "baseline_error_rate"])
            for svc in batch:
                bl = baselines.get(svc["service_id"], {})
                w.writerow([
                    svc["service_id"], svc["service_name"],
                    f"{bl.get('latency_p50', 0):.4f}",
                    f"{bl.get('error_rate', 0):.6f}",
                ])

    # ── JSON: synthetic test target info ──
    batches_json = _split_list(canary_svcs, n_json)
    for i, batch in enumerate(batches_json):
        data = {}
        for svc in batch:
            sid = svc["service_id"]
            data[sid] = {
                "service_name": svc["service_name"],
                "baseline_synthetic_success_rate": round(
                    float(np.random.uniform(0.95, 0.995)), 4),
                "baseline_test_count": int(np.random.randint(50, 200)),
            }
        path = os.path.join(workspace, f"synthetic_target_{i + 1}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    # ── YAML: rollout targets ──
    import yaml
    batches_yaml = _split_list(canary_svcs, n_yaml)
    for i, batch in enumerate(batches_yaml):
        data = {}
        for svc in batch:
            sid = svc["service_id"]
            if sid in target_rollouts:
                data[str(sid)] = {
                    "service_name": str(svc["service_name"]),
                    "flags": {str(k): {"target_rollout_pct": float(v)}
                              for k, v in target_rollouts[sid].items()},
                }
        path = os.path.join(workspace, f"rollout_target_{i + 1}.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=True)

    # ── TXT: deployment notes (includes manual_rollback_override) ──
    # Pick a subset for manual override (avoid overlap w/ critical-error svcs)
    override_candidates = [s for s in canary_svcs
                           if s["service_id"] not in critical_set]
    n_overrides = max(1, len(override_candidates) // 6)
    if override_candidates:
        ov_idx = list(np.random.choice(len(override_candidates),
                                       size=min(n_overrides, len(override_candidates)),
                                       replace=False))
        override_set = {override_candidates[int(j)]["service_id"] for j in ov_idx}
    else:
        override_set = set()

    batches_txt = _split_list(canary_svcs, n_txt)
    for i, batch in enumerate(batches_txt):
        path = os.path.join(workspace, f"deployment_notes_{i + 1}.txt")
        with open(path, "w") as f:
            for svc in batch:
                sid = svc["service_id"]
                f.write(f"=== {sid} ({svc['service_name']}) ===\n")
                f.write(f"Team: {svc['team']}\n")
                f.write(f"Canary Version: {svc['canary_version']}\n")
                f.write(f"Stable Version: {svc['stable_version']}\n")
                if sid in override_set:
                    f.write("manual_rollback_override: true\n")
                    f.write(f"Override Reason: {fake.sentence()}\n")
                else:
                    f.write("manual_rollback_override: false\n")
                f.write(f"Notes: {fake.paragraph()}\n\n")

    # ═══════════════ Fixed config files (not counted in SCALE) ═══════════════

    # canary_policy.yaml
    policy = {
        "scoring": {
            "weights": {
                "latency": 0.30,
                "error_rate": 0.25,
                "synthetic_success": 0.25,
                "flag_coverage": 0.20,
            },
            "decision_thresholds": {
                "promote": 0.75,
                "rollback": 0.40,
            },
        }
    }
    with open(os.path.join(workspace, "canary_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=True)

    # tier_config.json
    tier_config = {
        "critical": {
            "max_latency_degradation_pct": 10,
            "max_error_rate": 0.03,
            "min_synthetic_success_rate": 0.97,
            "min_flag_coverage": 0.90,
        },
        "standard": {
            "max_latency_degradation_pct": 15,
            "max_error_rate": 0.05,
            "min_synthetic_success_rate": 0.95,
            "min_flag_coverage": 0.80,
        },
        "experimental": {
            "max_latency_degradation_pct": 25,
            "max_error_rate": 0.08,
            "min_synthetic_success_rate": 0.90,
            "min_flag_coverage": 0.70,
        },
    }
    with open(os.path.join(workspace, "tier_config.json"), "w") as f:
        json.dump(tier_config, f, indent=2)

    # evaluation_rules.md
    rules_text = """# Canary Release Evaluation Rules

## Scoring Components

Each canary service is evaluated on four metrics. Each component score is in [0.0, 1.0].

### 1. Latency Degradation Score

Compare the average canary-environment latency_p50 against the baseline latency
from the service baseline CSV files.

    degradation_pct = (avg_canary_latency - baseline_latency) / baseline_latency * 100

- If degradation_pct <= tier.max_latency_degradation_pct  =>  score = 1.0
- If degradation_pct >= 2 * tier.max_latency_degradation_pct  =>  score = 0.0
- Otherwise  =>  score = 1.0 - (degradation_pct - max) / max

Clamp to [0.0, 1.0].

### 2. Error Rate Score

Use the average of the error_rate metric readings from the canary environment.

- If error_rate <= tier.max_error_rate  =>  score = 1.0
- If error_rate >= 2 * tier.max_error_rate  =>  score = 0.0
- Otherwise  =>  score = 1.0 - (error_rate - max) / max

Clamp to [0.0, 1.0].

### 3. Synthetic Success Rate Score

Compute success_rate = count(status == "success") / count(all) from
canary-environment synthetic transactions for that service.

- If success_rate >= tier.min_synthetic_success_rate  =>  score = 1.0
- If success_rate <= tier.min_synthetic_success_rate - 0.10  =>  score = 0.0
- Otherwise  =>  score = (success_rate - (min - 0.10)) / 0.10

Clamp to [0.0, 1.0].

### 4. Flag Coverage Score

For each feature flag of the service, compute:

    coverage_ratio = actual_rollout_percentage / target_rollout_percentage

where actual_rollout_percentage comes from the deployment system and
target_rollout_percentage comes from the rollout target YAML files.

Take the arithmetic mean of coverage_ratio across all flags that have a target.

- If avg_coverage >= tier.min_flag_coverage  =>  score = 1.0
- Otherwise  =>  score = avg_coverage / tier.min_flag_coverage

Clamp to [0.0, 1.0].

## Weighted Score

    weighted_score = latency_score * w_latency
                   + error_score * w_error_rate
                   + synthetic_score * w_synthetic_success
                   + flag_score * w_flag_coverage

Weights are defined in canary_policy.yaml under scoring.weights.

## Override Rules

1. If a canary service has ANY error log entry with severity "critical"
   in the **canary** environment, its decision is forced to ROLLBACK
   regardless of its weighted score.

2. If a service's deployment notes contain "manual_rollback_override: true",
   its decision is forced to ROLLBACK regardless of its weighted score.

## Per-Service Decision (after overrides)

- weighted_score >= promote_threshold  =>  PROMOTE
- weighted_score < rollback_threshold  =>  ROLLBACK
- otherwise  =>  HOLD

Thresholds are in canary_policy.yaml under scoring.decision_thresholds.

## Overall Release Decision

- If ANY service with tier == "critical" has decision == ROLLBACK  =>  overall ROLLBACK
- Else if ALL canary services have decision == PROMOTE  =>  overall PROMOTE
- Otherwise  =>  overall HOLD
"""
    with open(os.path.join(workspace, "evaluation_rules.md"), "w") as f:
        f.write(rules_text)

    return override_set


# ─────────────────────── main ───────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_services = SCALE["rows_per_table"]

    services = generate_services(n_services)
    metric_rows, baselines = generate_performance_metrics(services)
    tx_rows, success_rates = generate_synthetic_transactions(services)
    err_rows, critical_set = generate_error_logs(services)
    flag_rows, target_rollouts = generate_feature_flags(services)

    # Create DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)
    create_tables(conn)
    cur = conn.cursor()

    for s in services:
        cur.execute("""INSERT INTO services
            (service_id, service_name, team, tier, deployment_status,
             canary_version, stable_version, region, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (s["service_id"], s["service_name"], s["team"], s["tier"],
             s["deployment_status"], s["canary_version"], s["stable_version"],
             s["region"], s["created_at"]))

    cur.executemany("""INSERT INTO performance_metrics
        (service_id, timestamp, metric_type, value, environment)
        VALUES (?,?,?,?,?)""", metric_rows)

    cur.executemany("""INSERT INTO synthetic_transactions
        (service_id, timestamp, test_scenario, status, response_time_ms, environment)
        VALUES (?,?,?,?,?,?)""", tx_rows)

    cur.executemany("""INSERT INTO error_logs
        (service_id, session_id, timestamp, error_type, error_message,
         severity, environment)
        VALUES (?,?,?,?,?,?,?)""", err_rows)

    cur.executemany("""INSERT INTO feature_flags
        (service_id, flag_name, enabled, rollout_percentage, variant,
         targeting_rules, updated_at)
        VALUES (?,?,?,?,?,?,?)""", flag_rows)

    conn.commit()

    # Verify minimum rows
    for tbl in ["services", "performance_metrics", "synthetic_transactions",
                "error_logs", "feature_flags"]:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        assert cnt >= SCALE["rows_per_table"], \
            f"Table {tbl} has {cnt} rows, need >= {SCALE['rows_per_table']}"

    conn.close()

    # Write workspace
    override_set = write_workspace_files(
        args.workspace, services, baselines, target_rollouts, critical_set)

    # Summary
    n_canary = sum(1 for s in services if s["deployment_status"] == "canary")
    print(f"Database: {args.db_path}")
    print(f"  services:               {len(services)}")
    print(f"  performance_metrics:    {len(metric_rows)}")
    print(f"  synthetic_transactions: {len(tx_rows)}")
    print(f"  error_logs:             {len(err_rows)}")
    print(f"  feature_flags:          {len(flag_rows)}")
    print(f"Canary services: {n_canary}")
    print(f"Critical-error overrides: {len(critical_set)}")
    print(f"Manual-rollback overrides: {len(override_set)}")
    print(f"Workspace files: {len(os.listdir(args.workspace))}")


if __name__ == "__main__":
    main()
