"""
Deployment Readiness Gate - Data Generation Script
Generates database and workspace files for the deployment readiness validation task.
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

SCALE = {
    "rows_per_table": 200,
    "num_workspace_files": 30,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEAMS = [
    "Platform", "Payments", "Auth", "Search", "Analytics",
    "Notifications", "Billing", "Inventory", "Shipping", "UserProfile",
    "Gateway", "Messaging", "Reporting", "Compliance", "DataPipeline",
]

STAGES = ["dev", "staging", "prod"]
REGIONS = [
    "us-east-1", "us-west-2", "eu-west-1", "eu-central-1",
    "ap-southeast-1", "ap-northeast-1",
]

SCAN_TYPES = ["SAST", "DAST", "SCA", "container"]
PRIORITIES = ["P0", "P1", "P2", "P3", "P4"]
TICKET_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
DRIFT_SEVERITIES = ["critical", "high", "medium", "low", "none"]
CONFIG_PARAMS = [
    "max_connections", "timeout_ms", "retry_count", "log_level",
    "cache_ttl", "rate_limit", "thread_pool_size", "heap_size_mb",
    "gc_interval", "replication_factor", "batch_size", "flush_interval_s",
    "max_payload_kb", "idle_timeout_s", "health_check_interval_s",
]


def create_tables(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            criticality TEXT NOT NULL,
            repo_url TEXT NOT NULL,
            created_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commits (
            id INTEGER PRIMARY KEY,
            service_id INTEGER NOT NULL,
            commit_hash TEXT NOT NULL,
            author TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            test_coverage_pct REAL NOT NULL,
            branch TEXT NOT NULL,
            message TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
        CREATE TABLE IF NOT EXISTS jira_tickets (
            id INTEGER PRIMARY KEY,
            service_id INTEGER NOT NULL,
            ticket_key TEXT NOT NULL,
            summary TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            environment TEXT,
            created_date TEXT NOT NULL,
            updated_date TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
        CREATE TABLE IF NOT EXISTS environments (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            last_deploy_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS config_drift_entries (
            id INTEGER PRIMARY KEY,
            environment_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            parameter_name TEXT NOT NULL,
            expected_value TEXT NOT NULL,
            actual_value TEXT NOT NULL,
            drift_severity TEXT NOT NULL,
            detected_date TEXT NOT NULL,
            FOREIGN KEY (environment_id) REFERENCES environments(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
        CREATE TABLE IF NOT EXISTS security_scans (
            id INTEGER PRIMARY KEY,
            service_id INTEGER NOT NULL,
            scan_type TEXT NOT NULL,
            status TEXT NOT NULL,
            scan_timestamp TEXT NOT NULL,
            vulnerabilities_critical INTEGER NOT NULL,
            vulnerabilities_high INTEGER NOT NULL,
            vulnerabilities_medium INTEGER NOT NULL,
            vulnerabilities_low INTEGER NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
    """)
    conn.commit()


def generate_services(conn: sqlite3.Connection, n: int):
    rows = []
    used_names = set()
    prefixes = [
        "user", "order", "payment", "auth", "catalog", "cart", "search",
        "notify", "report", "audit", "config", "gateway", "cache", "queue",
        "stream", "metric", "log", "trace", "billing", "invoice",
        "shipment", "return", "review", "recommend", "feed", "session",
        "token", "policy", "rule", "scheduler", "worker", "proxy",
        "router", "balancer", "registry", "discovery", "vault", "secret",
        "monitor", "alert", "dashboard", "export", "import", "sync",
        "transform", "validate", "enrich", "aggregate", "index", "backup",
        "restore", "migrate", "deploy", "provision", "scale", "health",
        "status", "profile", "preference", "consent", "email", "sms",
        "webhook", "callback", "adapter", "connector", "bridge",
    ]
    suffixes = ["svc", "api", "service", "engine", "hub", "core", "agent", "daemon"]
    for i in range(n):
        while True:
            name = f"{random.choice(prefixes)}-{random.choice(suffixes)}"
            if name not in used_names:
                used_names.add(name)
                break
        team = random.choice(TEAMS)
        criticality = random.choices(["critical", "standard"], weights=[0.3, 0.7])[0]
        repo_url = f"https://github.com/acme-corp/{name}"
        created = fake.date_between(start_date="-3y", end_date="-6M")
        rows.append((i + 1, name, team, criticality, repo_url, str(created)))
    conn.executemany(
        "INSERT INTO services VALUES (?,?,?,?,?,?)", rows
    )
    conn.commit()
    return rows


def generate_commits(conn: sqlite3.Connection, services, n: int):
    rows = []
    commit_id = 1
    now = datetime.now()
    # Distribute commits across services, ensure at least 1 per service
    per_service_base = max(1, n // len(services))
    remaining = n - per_service_base * len(services)
    for svc in services:
        svc_id = svc[0]
        count = per_service_base + (1 if remaining > 0 else 0)
        if remaining > 0:
            remaining -= 1
        for _ in range(count):
            ts = now - timedelta(days=random.randint(0, 30),
                                 hours=random.randint(0, 23),
                                 minutes=random.randint(0, 59))
            coverage = round(random.uniform(40.0, 99.0), 2)
            branch = random.choices(["main", "develop", "release/v2.1", "feature/xyz"],
                                    weights=[0.5, 0.2, 0.2, 0.1])[0]
            msg = fake.sentence(nb_words=6)
            rows.append((
                commit_id, svc_id, fake.sha1()[:12], fake.user_name(),
                ts.strftime("%Y-%m-%dT%H:%M:%S"), coverage, branch, msg
            ))
            commit_id += 1
    # Pad if needed
    while len(rows) < n:
        svc_id = random.choice(services)[0]
        ts = now - timedelta(days=random.randint(0, 30),
                             hours=random.randint(0, 23))
        coverage = round(random.uniform(40.0, 99.0), 2)
        rows.append((
            commit_id, svc_id, fake.sha1()[:12], fake.user_name(),
            ts.strftime("%Y-%m-%dT%H:%M:%S"),
            coverage, "main", fake.sentence(nb_words=6)
        ))
        commit_id += 1
    conn.executemany("INSERT INTO commits VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_environments(conn: sqlite3.Connection, n: int):
    rows = []
    env_id = 1
    combos = []
    for stage in STAGES:
        for region in REGIONS:
            combos.append((stage, region))
    random.shuffle(combos)
    # Ensure we have at least n environments
    while len(combos) < n:
        combos.append((random.choice(STAGES), random.choice(REGIONS)))
    for i in range(n):
        stage, region = combos[i]
        name = f"{stage}-{region}-{i:03d}"
        status = random.choices(["active", "inactive"], weights=[0.85, 0.15])[0]
        last_deploy = fake.date_time_between(start_date="-30d", end_date="now")
        rows.append((
            env_id, name, region, stage, status,
            last_deploy.strftime("%Y-%m-%dT%H:%M:%S")
        ))
        env_id += 1
    conn.executemany("INSERT INTO environments VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_jira_tickets(conn: sqlite3.Connection, services, environments, n: int):
    rows = []
    env_names = [e[1] for e in environments]
    for i in range(n):
        svc = random.choice(services)
        svc_id = svc[0]
        priority = random.choices(PRIORITIES, weights=[0.05, 0.10, 0.25, 0.35, 0.25])[0]
        status = random.choices(TICKET_STATUSES, weights=[0.3, 0.25, 0.25, 0.2])[0]
        env = random.choice(env_names) if random.random() < 0.7 else None
        created = fake.date_time_between(start_date="-60d", end_date="now")
        updated = created + timedelta(days=random.randint(0, 14))
        key = f"ACME-{1000 + i}"
        summary = fake.sentence(nb_words=8)
        rows.append((
            i + 1, svc_id, key, summary, priority, status,
            env, created.strftime("%Y-%m-%d"), updated.strftime("%Y-%m-%d")
        ))
    conn.executemany("INSERT INTO jira_tickets VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_config_drift(conn: sqlite3.Connection, services, environments, n: int):
    rows = []
    drift_id = 1
    while len(rows) < n:
        env = random.choice(environments)
        svc = random.choice(services)
        param = random.choice(CONFIG_PARAMS)
        expected = str(random.randint(10, 10000))
        # Some drift, some not
        if random.random() < 0.35:
            actual = str(int(expected) + random.choice([-5, -2, 2, 5, 10, 50]))
            severity = random.choices(
                ["critical", "high", "medium", "low"],
                weights=[0.1, 0.2, 0.3, 0.4]
            )[0]
        else:
            actual = expected
            severity = "none"
        detected = fake.date_time_between(start_date="-14d", end_date="now")
        rows.append((
            drift_id, env[0], svc[0], param, expected, actual,
            severity, detected.strftime("%Y-%m-%dT%H:%M:%S")
        ))
        drift_id += 1
    conn.executemany("INSERT INTO config_drift_entries VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


def generate_security_scans(conn: sqlite3.Connection, services, n: int):
    rows = []
    scan_id = 1
    now = datetime.now()
    per_service = max(1, n // len(services))
    remaining = n - per_service * len(services)
    for svc in services:
        svc_id = svc[0]
        count = per_service + (1 if remaining > 0 else 0)
        if remaining > 0:
            remaining -= 1
        for _ in range(count):
            scan_type = random.choice(SCAN_TYPES)
            # Most scans pass
            status = random.choices(["passed", "failed"], weights=[0.75, 0.25])[0]
            ts = now - timedelta(days=random.randint(0, 20),
                                 hours=random.randint(0, 23))
            vuln_c = random.choices([0, 0, 0, 1, 2], weights=[0.6, 0.15, 0.1, 0.1, 0.05])[0]
            vuln_h = random.choices([0, 0, 1, 2, 3], weights=[0.4, 0.2, 0.2, 0.1, 0.1])[0]
            vuln_m = random.randint(0, 8)
            vuln_l = random.randint(0, 15)
            if status == "passed":
                vuln_c = 0
                vuln_h = min(vuln_h, 1)
            rows.append((
                scan_id, svc_id, scan_type, status,
                ts.strftime("%Y-%m-%dT%H:%M:%S"),
                vuln_c, vuln_h, vuln_m, vuln_l
            ))
            scan_id += 1
    while len(rows) < n:
        svc_id = random.choice(services)[0]
        ts = now - timedelta(days=random.randint(0, 20))
        rows.append((
            scan_id, svc_id, random.choice(SCAN_TYPES), "passed",
            ts.strftime("%Y-%m-%dT%H:%M:%S"), 0, 0,
            random.randint(0, 5), random.randint(0, 10)
        ))
        scan_id += 1
    conn.executemany("INSERT INTO security_scans VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rows


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def select_release_scope(services, environments):
    """Select services and environments for the current release."""
    # Pick ~30% of services for the release, minimum 8
    n_release_svcs = max(8, len(services) * 3 // 10)
    release_services = random.sample(services, min(n_release_svcs, len(services)))

    # Pick active prod/staging environments as targets
    target_envs = [e for e in environments if e[3] in ("prod", "staging") and e[4] == "active"]
    # Take a reasonable subset
    n_target = max(3, len(target_envs) * 4 // 10)
    target_envs = random.sample(target_envs, min(n_target, len(target_envs)))

    return release_services, target_envs


def generate_workspace(workspace: str, services, commits, environments,
                       jira_tickets, config_drift, security_scans):
    os.makedirs(workspace, exist_ok=True)

    release_services, target_envs = select_release_scope(services, environments)

    # --- Fixed files ---

    # 1. release_manifest.json
    manifest = {
        "release_id": "REL-2026-04-21-001",
        "release_date": "2026-04-21",
        "services": [
            {"service_id": s[0], "service_name": s[1], "target_branch": "main"}
            for s in release_services
        ],
        "target_environments": [
            {"environment_id": e[0], "environment_name": e[1]}
            for e in target_envs
        ],
    }
    with open(os.path.join(workspace, "release_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # 2. go_nogo_policy.yaml
    policy = {
        "deployment_policy": {
            "test_coverage": {
                "critical_services_min_pct": 80.0,
                "standard_services_min_pct": 65.0,
                "branch": "main",
                "lookback_commits": 5,
                "aggregation": "average",
            },
            "jira_blocking": {
                "blocking_priorities": ["P0", "P1"],
                "blocking_statuses": ["Open", "In Progress"],
                "description": "Any open or in-progress P0/P1 ticket for a release service blocks deployment.",
            },
            "config_drift": {
                "max_allowed_severity": "low",
                "description": "Any drift entry with severity above 'low' (i.e., medium, high, or critical) for a release service in a target environment is a blocker.",
            },
            "security_scan": {
                "max_scan_age_days": 7,
                "required_scan_types": {
                    "critical": ["SAST", "DAST", "SCA", "container"],
                    "standard": ["SAST", "SCA"],
                },
                "max_critical_vulnerabilities": 0,
                "max_high_vulnerabilities": 2,
                "description": "All required scans must have passed within the last N days with vulnerabilities within limits.",
            },
            "overall_decision": "If ANY service-environment pair has a blocking issue, the overall release decision is NO-GO.",
        }
    }
    with open(os.path.join(workspace, "go_nogo_policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 3. scan_requirements.json
    scan_req = {
        "scan_freshness_note": "Scan age is computed from scan_timestamp to the release_date in the manifest.",
        "vulnerability_thresholds": {
            "critical": 0,
            "high": 2,
        },
        "pass_status_required": True,
        "description": "Only scans with status 'passed' count toward freshness. Failed or in-progress scans are ignored.",
    }
    with open(os.path.join(workspace, "scan_requirements.json"), "w") as f:
        json.dump(scan_req, f, indent=2)

    # 4. team_escalation.md
    lines = ["# Escalation Contacts\n\n"]
    for team in TEAMS:
        lines.append(f"- **{team}**: {fake.name()} ({fake.email()})\n")
    with open(os.path.join(workspace, "team_escalation.md"), "w") as f:
        f.writelines(lines)

    # --- Scalable files ---
    num_files = SCALE["num_workspace_files"]
    n_coverage_files = num_files // 2
    n_baseline_files = num_files - n_coverage_files

    # Coverage trend CSVs: each file covers a batch of services
    os.makedirs(os.path.join(workspace, "coverage_trends"), exist_ok=True)
    svc_ids_all = [s[0] for s in services]
    batch_size_cov = max(1, len(svc_ids_all) // n_coverage_files)
    for fi in range(n_coverage_files):
        start = fi * batch_size_cov
        end = start + batch_size_cov if fi < n_coverage_files - 1 else len(svc_ids_all)
        batch_svc_ids = svc_ids_all[start:end]
        rows_csv = []
        for sid in batch_svc_ids:
            svc_commits = [c for c in commits if c[1] == sid and c[6] == "main"]
            svc_name = next(s[1] for s in services if s[0] == sid)
            svc_crit = next(s[3] for s in services if s[0] == sid)
            target_cov = 85.0 if svc_crit == "critical" else 70.0
            for c in svc_commits[-10:]:
                rows_csv.append({
                    "service_id": sid,
                    "service_name": svc_name,
                    "commit_hash": c[2],
                    "timestamp": c[4],
                    "coverage_pct": c[5],
                    "target_coverage_pct": target_cov,
                    "criticality": svc_crit,
                })
        if rows_csv:
            df = pd.DataFrame(rows_csv)
            df.to_csv(
                os.path.join(workspace, "coverage_trends", f"coverage_batch_{fi:03d}.csv"),
                index=False,
            )
        else:
            # Write empty with headers
            pd.DataFrame(columns=[
                "service_id", "service_name", "commit_hash", "timestamp",
                "coverage_pct", "target_coverage_pct", "criticality"
            ]).to_csv(
                os.path.join(workspace, "coverage_trends", f"coverage_batch_{fi:03d}.csv"),
                index=False,
            )

    # Environment baseline YAML files
    os.makedirs(os.path.join(workspace, "env_baselines"), exist_ok=True)
    batch_size_env = max(1, len(environments) // n_baseline_files)
    for fi in range(n_baseline_files):
        start = fi * batch_size_env
        end = start + batch_size_env if fi < n_baseline_files - 1 else len(environments)
        batch_envs = environments[start:end]
        baseline_data = {}
        for env in batch_envs:
            env_id, env_name = env[0], env[1]
            # Get expected values from drift entries for this env
            env_drift = [d for d in config_drift if d[1] == env_id]
            params = {}
            for d in env_drift:
                params[d[3]] = {
                    "expected": d[4],
                    "service_id": d[2],
                }
            baseline_data[env_name] = {
                "environment_id": env_id,
                "region": env[2],
                "stage": env[3],
                "parameters": params,
            }
        with open(os.path.join(workspace, "env_baselines", f"baseline_{fi:03d}.yaml"), "w") as f:
            yaml.dump(baseline_data, f, default_flow_style=False, sort_keys=False)

    return release_services, target_envs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    if os.path.exists(args.db_path):
        os.remove(args.db_path)

    conn = sqlite3.connect(args.db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]

    services = generate_services(conn, n)
    commits = generate_commits(conn, services, n)
    environments = generate_environments(conn, n)
    jira_tickets = generate_jira_tickets(conn, services, environments, n)
    config_drift = generate_config_drift(conn, services, environments, n)
    security_scans = generate_security_scans(conn, services, n)

    conn.close()

    generate_workspace(
        args.workspace, services, commits, environments,
        jira_tickets, config_drift, security_scans
    )

    print(f"Database created at {args.db_path}")
    print(f"Workspace created at {args.workspace}")
    print(f"Services: {len(services)}, Commits: {len(commits)}, "
          f"Environments: {len(environments)}, Tickets: {len(jira_tickets)}, "
          f"Drift entries: {len(config_drift)}, Scans: {len(security_scans)}")


if __name__ == "__main__":
    main()
