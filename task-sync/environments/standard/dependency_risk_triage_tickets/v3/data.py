"""
Data generation for dependency-risk triage task.
Generates a SQLite database and workspace files for the agent environment.
"""

import argparse
import sqlite3
import os
import json
import csv
import random
import numpy as np
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 240,
    "num_workspace_files": 32,
}

# ---------------------------------------------------------------------------
# Deterministic seeds
# ---------------------------------------------------------------------------
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ---------------------------------------------------------------------------
# Reference pools
# ---------------------------------------------------------------------------
PACKAGE_POOL = [
    ("lodash", "npm", "4.17.21"), ("express", "npm", "4.18.2"),
    ("axios", "npm", "1.6.0"), ("jsonwebtoken", "npm", "9.0.2"),
    ("ws", "npm", "8.16.0"), ("minimist", "npm", "1.2.8"),
    ("qs", "npm", "6.11.2"), ("semver", "npm", "7.5.4"),
    ("tar", "npm", "6.2.0"), ("node-fetch", "npm", "3.3.2"),
    ("requests", "pypi", "2.31.0"), ("flask", "pypi", "3.0.0"),
    ("django", "pypi", "5.0.1"), ("cryptography", "pypi", "41.0.7"),
    ("pillow", "pypi", "10.2.0"), ("pyyaml", "pypi", "6.0.1"),
    ("jinja2", "pypi", "3.1.3"), ("sqlalchemy", "pypi", "2.0.25"),
    ("urllib3", "pypi", "2.1.0"), ("paramiko", "pypi", "3.4.0"),
    ("log4j-core", "maven", "2.22.1"), ("spring-core", "maven", "6.1.3"),
    ("jackson-databind", "maven", "2.16.1"), ("commons-text", "maven", "1.11.0"),
    ("guava", "maven", "33.0.0"), ("netty-handler", "maven", "4.1.104"),
    ("snakeyaml", "maven", "2.2.0"), ("httpclient", "maven", "5.3.0"),
    ("golang.org/x/crypto", "go", "0.18.0"), ("golang.org/x/net", "go", "0.20.0"),
    ("github.com/gin-gonic/gin", "go", "1.9.1"),
    ("github.com/gorilla/mux", "go", "1.8.1"),
    ("github.com/dgrijalva/jwt-go", "go", "3.2.2"),
    ("google.golang.org/protobuf", "go", "1.32.0"),
    ("certifi", "pypi", "2024.2.2"), ("aiohttp", "pypi", "3.9.1"),
    ("tornado", "pypi", "6.4.0"), ("setuptools", "pypi", "69.0.3"),
    ("chalk", "npm", "5.3.0"), ("glob-parent", "npm", "6.0.2"),
    ("debug", "npm", "4.3.4"), ("cookie", "npm", "0.6.0"),
    ("path-to-regexp", "npm", "6.2.1"), ("moment", "npm", "2.30.1"),
    ("underscore", "npm", "1.13.6"), ("async", "npm", "3.2.5"),
    ("body-parser", "npm", "1.20.2"), ("cors", "npm", "2.8.5"),
    ("dotenv", "npm", "16.3.1"), ("helmet", "npm", "7.1.0"),
    ("morgan", "npm", "1.10.0"), ("multer", "npm", "1.4.5"),
]

SVC_PARTS = [
    "auth", "payment", "user", "order", "inventory", "notification",
    "search", "analytics", "billing", "gateway", "catalog", "shipping",
    "messaging", "logging", "config", "media", "report", "audit",
    "scheduler", "workflow", "email", "cache", "proxy", "monitor",
    "identity", "session", "token", "limiter", "health", "dashboard",
    "ingest", "etl", "ml-serve", "feature", "abtest", "consent",
    "storage", "cdn", "dns", "backup", "queue", "stream",
    "webhook", "oauth", "sso", "mfa", "vault", "crypto",
    "telemetry", "trace", "metric", "alerting", "deploy", "release",
]

SVC_SUFFIXES = ["svc", "api", "worker", "engine", "hub"]

SEVERITIES = ["critical", "high", "medium", "low"]
EXPLOIT_MATURITIES = ["active", "poc", "theoretical", "none"]


def _make_older_version(ver_str):
    """Return a version string strictly less than *ver_str*."""
    parts = ver_str.split(".")
    if len(parts) < 3:
        parts = (parts + ["0", "0", "0"])[:3]
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    r = random.random()
    if r < 0.35 and minor > 0:
        minor -= random.randint(1, min(3, minor))
        patch = random.randint(0, max(patch, 5))
    elif patch > 0:
        patch -= random.randint(1, min(5, patch))
    else:
        if minor > 0:
            minor -= 1
            patch = random.randint(0, 9)
        else:
            patch = 0  # can't go lower — same version (edge case)
    return f"{major}.{minor}.{patch}"


def _generate_cve(existing: set) -> str:
    while True:
        year = random.choice([2024, 2025, 2026])
        num = random.randint(1000, 59999)
        cve = f"CVE-{year}-{num}"
        if cve not in existing:
            existing.add(cve)
            return cve


def _unique_service_names(n: int) -> list:
    names, used = [], set()
    for _ in range(n):
        found = False
        for _ in range(500):
            name = f"{random.choice(SVC_PARTS)}-{random.choice(SVC_SUFFIXES)}"
            if name not in used:
                used.add(name)
                names.append(name)
                found = True
                break
        if not found:
            idx = len(names)
            name = f"svc-extra-{idx}"
            used.add(name)
            names.append(name)
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    rows = SCALE["rows_per_table"]
    num_ws = SCALE["num_workspace_files"]
    os.makedirs(args.workspace, exist_ok=True)

    # ── Packages ──────────────────────────────────────────────────────────
    pool = list(PACKAGE_POOL)
    idx = len(pool)
    while len(pool) < rows:
        eco = random.choice(["npm", "pypi", "maven", "go"])
        pool.append((f"lib-{fake.word()}-{idx}", eco,
                      f"{random.randint(1,9)}.{random.randint(0,30)}.{random.randint(0,20)}"))
        idx += 1

    seen_pkg: set = set()
    unique_pkgs: list = []
    for p in pool:
        if p[0] not in seen_pkg:
            seen_pkg.add(p[0])
            unique_pkgs.append(p)
    while len(unique_pkgs) < rows:
        eco = random.choice(["npm", "pypi", "maven", "go"])
        name = f"lib-extra-{len(unique_pkgs)}"
        unique_pkgs.append((name, eco,
                            f"{random.randint(1,9)}.{random.randint(0,30)}.{random.randint(0,20)}"))
    unique_pkgs = unique_pkgs[:rows]

    packages_data = []
    for i, (pname, eco, ver) in enumerate(unique_pkgs):
        packages_data.append({
            "package_id": i + 1,
            "package_name": pname,
            "ecosystem": eco,
            "latest_version": ver,
            "license": random.choice(["MIT", "Apache-2.0", "BSD-3-Clause",
                                       "GPL-3.0", "ISC"]),
        })
    pkg_names = [p["package_name"] for p in packages_data]

    # ── Services ──────────────────────────────────────────────────────────
    svc_names = _unique_service_names(max(rows, num_ws + 15))
    team_count = max(6, rows // 5)
    teams = [f"team-{fake.unique.first_name().lower()}" for _ in range(team_count)]

    services_data = []
    for i in range(rows):
        services_data.append({
            "service_id": i + 1,
            "service_name": svc_names[i],
            "team_name": random.choice(teams),
            "tier": random.choices([1, 2, 3, 4], weights=[15, 30, 35, 20])[0],
            "oncall_email": fake.email(),
            "description": fake.sentence(nb_words=8),
        })

    # ── Dependabot Alerts ─────────────────────────────────────────────────
    cve_set: set = set()
    alerts_data = []
    for i in range(rows):
        pkg_name = random.choice(pkg_names)
        pkg_info = next(p for p in packages_data if p["package_name"] == pkg_name)
        cve = _generate_cve(cve_set)
        sev = random.choices(SEVERITIES, weights=[15, 30, 35, 20])[0]
        status = random.choices(["open", "dismissed", "fixed"],
                                weights=[50, 25, 25])[0]
        patched = pkg_info["latest_version"]
        alerts_data.append({
            "alert_id": i + 1,
            "repo_name": f"org/{random.choice(svc_names[:num_ws + 5])}-repo",
            "package_name": pkg_name,
            "cve_id": cve,
            "severity": sev,
            "status": status,
            "vulnerable_version_range": f"<{patched}",
            "patched_version": patched,
            "created_at": fake.date_time_between(
                start_date="-90d", end_date="now").isoformat(),
        })

    # ── Threat Intelligence ───────────────────────────────────────────────
    all_cves = list(cve_set)
    while len(all_cves) < rows:
        all_cves.append(_generate_cve(cve_set))

    threat_data = []
    for i, cve in enumerate(all_cves[:rows]):
        threat_data.append({
            "intel_id": i + 1,
            "cve_id": cve,
            "epss_score": round(random.uniform(0.001, 0.95), 4),
            "exploit_maturity": random.choices(
                EXPLOIT_MATURITIES, weights=[10, 25, 40, 25])[0],
            "known_exploited": random.choice([0, 1]),
            "last_updated": fake.date_time_between(
                start_date="-30d", end_date="now").isoformat(),
        })

    # ── Workspace: deployment manifests (scalable files) ──────────────────
    prod_services = services_data[:num_ws]
    service_deployments: dict = {}

    for svc in prod_services:
        n_deps = random.randint(4, min(7, len(pkg_names)))
        chosen = random.sample(pkg_names, n_deps)
        deps = []
        for pn in chosen:
            pi = next(p for p in packages_data if p["package_name"] == pn)
            if random.random() < 0.55:
                ver = _make_older_version(pi["latest_version"])
            else:
                ver = pi["latest_version"]
            deps.append({"package": pn, "version": ver,
                          "pinned": random.choice([True, False])})
        service_deployments[svc["service_name"]] = deps

        manifest = {
            "service_name": svc["service_name"],
            "environment": "production",
            "region": random.choice(
                ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]),
            "last_deploy": fake.date_time_between(
                start_date="-14d", end_date="now").isoformat(),
            "dependencies": deps,
        }
        with open(os.path.join(args.workspace,
                               f"deploy_{svc['service_name']}.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)

    # ── Known exceptions ──────────────────────────────────────────────────
    open_pkgs = {a["package_name"] for a in alerts_data if a["status"] == "open"}
    prod_pkgs = set()
    for deps in service_deployments.values():
        for d in deps:
            prod_pkgs.add(d["package"])
    overlap = sorted(open_pkgs & prod_pkgs)
    n_exc = min(2, max(1, len(overlap) // 4))
    if overlap:
        exception_pkgs = random.sample(overlap, min(n_exc, len(overlap)))
    else:
        exception_pkgs = random.sample(pkg_names, 1)
    noise = [p for p in pkg_names
             if p not in set(overlap) | set(exception_pkgs)]
    if noise:
        exception_pkgs += random.sample(noise, min(2, len(noise)))

    with open(os.path.join(args.workspace, "known_exceptions.txt"), "w") as fh:
        fh.write("# Packages approved for security exception - "
                 "exclude from remediation tickets\n")
        fh.write("# One package name per line\n")
        for ep in sorted(exception_pkgs):
            fh.write(f"{ep}\n")

    # ── Remediation history ───────────────────────────────────────────────
    remediation_data = []
    for i in range(rows):
        alert = random.choice(alerts_data)
        svc = random.choice(prod_services)
        r_status = random.choices(
            ["completed", "in_progress", "pending", "cancelled"],
            weights=[30, 20, 30, 20])[0]
        created = fake.date_time_between(start_date="-180d", end_date="-30d")
        resolved = (fake.date_time_between(start_date=created, end_date="now")
                     if r_status == "completed" else None)
        remediation_data.append({
            "ticket_id": f"HIST-{i+1:04d}",
            "alert_id": alert["alert_id"],
            "service_name": svc["service_name"],
            "status": r_status,
            "assigned_team": svc["team_name"],
            "created_at": created.isoformat(),
            "resolved_at": resolved.isoformat() if resolved else None,
        })

    # ── Write database ────────────────────────────────────────────────────
    conn = sqlite3.connect(args.db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS dependabot_alerts (
        alert_id INTEGER PRIMARY KEY,
        repo_name TEXT,
        package_name TEXT,
        cve_id TEXT UNIQUE,
        severity TEXT,
        status TEXT,
        vulnerable_version_range TEXT,
        patched_version TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS threat_intelligence (
        intel_id INTEGER PRIMARY KEY,
        cve_id TEXT UNIQUE,
        epss_score REAL,
        exploit_maturity TEXT,
        known_exploited INTEGER,
        last_updated TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS services (
        service_id INTEGER PRIMARY KEY,
        service_name TEXT UNIQUE,
        team_name TEXT,
        tier INTEGER,
        oncall_email TEXT,
        description TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS packages (
        package_id INTEGER PRIMARY KEY,
        package_name TEXT UNIQUE,
        ecosystem TEXT,
        latest_version TEXT,
        license TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS remediation_history (
        ticket_id TEXT PRIMARY KEY,
        alert_id INTEGER,
        service_name TEXT,
        status TEXT,
        assigned_team TEXT,
        created_at TEXT,
        resolved_at TEXT,
        FOREIGN KEY (alert_id) REFERENCES dependabot_alerts(alert_id),
        FOREIGN KEY (service_name) REFERENCES services(service_name)
    )""")

    for a in alerts_data:
        c.execute("INSERT INTO dependabot_alerts VALUES (?,?,?,?,?,?,?,?,?)",
                  tuple(a.values()))
    for t in threat_data:
        c.execute("INSERT INTO threat_intelligence VALUES (?,?,?,?,?,?)",
                  tuple(t.values()))
    for s in services_data:
        c.execute("INSERT INTO services VALUES (?,?,?,?,?,?)",
                  tuple(s.values()))
    for p in packages_data:
        c.execute("INSERT INTO packages VALUES (?,?,?,?,?)",
                  tuple(p.values()))
    for r in remediation_data:
        c.execute("INSERT INTO remediation_history VALUES (?,?,?,?,?,?,?)",
                  tuple(r.values()))
    conn.commit()

    # ── Fixed workspace config files ──────────────────────────────────────
    priority_config = {
        "severity_weights": {"critical": 4, "high": 3, "medium": 2, "low": 1},
        "exploit_maturity_weights": {"active": 4, "poc": 3,
                                      "theoretical": 2, "none": 1},
        "service_tier_weights": {"1": 4, "2": 3, "3": 2, "4": 1},
        "formula": "severity_weight * exploit_maturity_weight * service_tier_weight",
    }
    with open(os.path.join(args.workspace, "priority_config.yaml"), "w") as fh:
        yaml.dump(priority_config, fh, default_flow_style=False, sort_keys=False)

    sla_policy = {
        "sla_tiers": [
            {"min_priority_score": 48, "sla_hours": 24, "label": "P0-Critical"},
            {"min_priority_score": 24, "sla_hours": 72, "label": "P1-High"},
            {"min_priority_score": 12, "sla_hours": 168, "label": "P2-Medium"},
            {"min_priority_score": 0, "sla_hours": 336, "label": "P3-Low"},
        ],
        "business_hours_only": False,
        "escalation_after_breach": True,
    }
    with open(os.path.join(args.workspace, "sla_policy.yaml"), "w") as fh:
        yaml.dump(sla_policy, fh, default_flow_style=False, sort_keys=False)

    seen_teams: set = set()
    team_rows = []
    for svc in services_data:
        tn = svc["team_name"]
        if tn not in seen_teams:
            seen_teams.add(tn)
            team_rows.append({
                "team_name": tn,
                "manager": fake.name(),
                "escalation_email": fake.company_email(),
                "slack_channel": f"#sec-{tn}",
            })
    with open(os.path.join(args.workspace, "team_directory.csv"),
              "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "team_name", "manager", "escalation_email", "slack_channel"])
        w.writeheader()
        w.writerows(team_rows)

    with open(os.path.join(args.workspace, "remediation_playbook.md"), "w") as fh:
        fh.write("# Remediation Playbook\n\n")
        fh.write("## Version Comparison\n\n")
        fh.write(
            "A deployment is considered vulnerable when its installed version "
            "is strictly less than the patched version listed in the alert. "
            "Compare versions using semantic versioning: compare the major "
            "component first, then minor, then patch, all numerically.\n\n")
        fh.write("## Duplicate Prevention\n\n")
        fh.write(
            "Before creating a new remediation ticket, check the existing "
            "remediation history for the same alert. If any historical ticket "
            "for the same alert ID **and** the same service has a status of "
            "'in_progress' or 'completed', do NOT create a new ticket for "
            "that combination.\n\n")
        fh.write("## Exception Handling\n\n")
        fh.write(
            "Packages listed in the known-exceptions file have been reviewed "
            "and approved by security leadership. Do not create remediation "
            "tickets for alerts that target an excepted package.\n")

    conn.close()
    print(f"Database created at {args.db_path} ({rows} rows/table)")
    print(f"Workspace: {num_ws} deploy manifests + 5 config files "
          f"in {args.workspace}")


if __name__ == "__main__":
    main()
