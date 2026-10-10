"""
Data generation for Microservice Deployment Readiness Validation task.
Generates database tables and workspace files for evaluating deployment go/no-go decisions.
"""

import os
import json
import csv
import random
import sqlite3
import argparse
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 400,
    "num_workspace_files": 40,
}

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# --- Constants ---
NAMESPACES = [
    "prod-core", "prod-data", "prod-api", "prod-web", "prod-ml",
    "prod-payments", "prod-auth", "prod-messaging",
]
TEAMS = [
    "platform-infra", "data-engineering", "api-gateway", "frontend",
    "ml-ops", "security", "payments", "notifications", "analytics", "identity",
]
SEVERITIES = ["critical", "high", "medium", "low"]
CVE_STATUSES = ["open", "mitigated", "accepted_risk", "false_positive"]
CR_STATUSES = ["approved", "pending_review", "rejected", "conditionally_approved"]
DEPENDENCY_CRITICALITIES = ["critical", "standard"]
PROTOCOLS = ["gRPC", "HTTP/2", "AMQP", "TCP", "HTTP/1.1"]
HEALTH_STATUSES = ["healthy", "degraded", "unhealthy", "unknown"]
RESOURCE_TYPES = ["cpu_cores", "memory_gb", "storage_gb", "pod_count"]

SERVICE_PREFIXES = [
    "auth", "user", "order", "payment", "notif", "search", "catalog",
    "inventory", "shipping", "analytics", "logging", "metrics", "config",
    "gateway", "cache", "queue", "scheduler", "worker", "proxy", "monitor",
    "billing", "audit", "session", "report", "feed", "media", "crypto",
    "rate-limit", "discovery", "healthcheck", "transformer", "aggregator",
    "router", "balancer", "validator",
]
SERVICE_SUFFIXES = [
    "svc", "api", "handler", "processor", "mgr", "engine", "daemon",
    "agent", "ctrl", "bridge", "relay", "hub", "node", "core",
]

FILE_FORMATS = [".yaml", ".json", ".csv", ".txt", ".md"]


def generate_service_name(used_names):
    """Generate a unique service name."""
    while True:
        name = f"{random.choice(SERVICE_PREFIXES)}-{random.choice(SERVICE_SUFFIXES)}-{random.randint(1, 99):02d}"
        if name not in used_names:
            used_names.add(name)
            return name


def generate_microservices(n):
    """Generate microservice records."""
    used_names = set()
    services = []
    for i in range(n):
        name = generate_service_name(used_names)
        services.append({
            "id": i + 1,
            "name": name,
            "team": random.choice(TEAMS),
            "image_registry": f"registry.internal/{name}",
            "image_tag": fake.bothify("v#.#.#-?????").lower(),
            "namespace": random.choice(NAMESPACES),
            "priority": random.choice(["critical", "high", "medium", "low"]),
            "last_deployed": fake.date_between(start_date="-180d", end_date="-10d").isoformat(),
        })
    return services


def generate_vulnerability_scans(services, n):
    """Generate vulnerability scan records. Multiple vulns per service possible."""
    scans = []
    scan_id = 1
    service_ids = [s["id"] for s in services]
    while len(scans) < n:
        sid = random.choice(service_ids)
        svc = next(s for s in services if s["id"] == sid)
        severity = random.choices(SEVERITIES, weights=[5, 15, 40, 40])[0]
        cvss = {
            "critical": round(random.uniform(9.0, 10.0), 1),
            "high": round(random.uniform(7.0, 8.9), 1),
            "medium": round(random.uniform(4.0, 6.9), 1),
            "low": round(random.uniform(0.1, 3.9), 1),
        }[severity]
        status = random.choices(
            CVE_STATUSES,
            weights=[40, 25, 20, 15],
        )[0]
        scans.append({
            "id": scan_id,
            "service_id": sid,
            "cve_id": f"CVE-{random.randint(2022, 2026)}-{random.randint(10000, 99999)}",
            "severity": severity,
            "cvss_score": cvss,
            "status": status,
            "package_name": fake.bothify("lib???-###"),
            "scan_date": fake.date_between(start_date="-30d", end_date="today").isoformat(),
            "image_tag": svc["image_tag"],
        })
        scan_id += 1
    return scans


def generate_resource_quotas(namespaces_used, n):
    """Generate resource quota records for each namespace and resource type."""
    quotas = []
    quota_id = 1
    # Ensure every namespace-resource combo exists
    for ns in namespaces_used:
        for rt in RESOURCE_TYPES:
            limits = {
                "cpu_cores": round(random.uniform(20, 80), 1),
                "memory_gb": round(random.uniform(64, 256), 1),
                "storage_gb": round(random.uniform(200, 1000), 0),
                "pod_count": random.randint(50, 200),
            }
            limit = limits[rt]
            usage_pct = random.uniform(0.40, 0.90)
            current = round(limit * usage_pct, 1) if rt != "pod_count" else int(limit * usage_pct)
            quotas.append({
                "id": quota_id,
                "namespace": ns,
                "resource_type": rt,
                "quota_limit": limit,
                "current_usage": current,
                "unit": {"cpu_cores": "cores", "memory_gb": "GB", "storage_gb": "GB", "pod_count": "pods"}[rt],
                "last_updated": fake.date_between(start_date="-7d", end_date="today").isoformat(),
            })
            quota_id += 1
    # Pad with extra historical snapshot rows if needed
    while len(quotas) < n:
        ns = random.choice(namespaces_used)
        rt = random.choice(RESOURCE_TYPES)
        existing = [q for q in quotas if q["namespace"] == ns and q["resource_type"] == rt]
        if existing:
            base = existing[0]
            quotas.append({
                "id": quota_id,
                "namespace": ns,
                "resource_type": rt,
                "quota_limit": base["quota_limit"],
                "current_usage": round(base["current_usage"] * random.uniform(0.95, 1.05), 1)
                    if rt != "pod_count" else max(1, int(base["current_usage"] * random.uniform(0.95, 1.05))),
                "unit": base["unit"],
                "last_updated": fake.date_between(start_date="-30d", end_date="-8d").isoformat(),
            })
            quota_id += 1
    return quotas


def generate_dependency_map(services, n):
    """Generate dependency relationships between services."""
    deps = []
    dep_id = 1
    service_ids = [s["id"] for s in services]
    used_pairs = set()

    while len(deps) < n:
        sid = random.choice(service_ids)
        dep_sid = random.choice(service_ids)
        if sid == dep_sid or (sid, dep_sid) in used_pairs:
            continue
        used_pairs.add((sid, dep_sid))
        dep_svc = next(s for s in services if s["id"] == dep_sid)
        health = random.choices(
            HEALTH_STATUSES,
            weights=[65, 20, 10, 5],
        )[0]
        latency = {
            "healthy": round(random.uniform(1, 50), 1),
            "degraded": round(random.uniform(50, 200), 1),
            "unhealthy": round(random.uniform(200, 5000), 1),
            "unknown": -1.0,
        }[health]
        deps.append({
            "id": dep_id,
            "service_id": sid,
            "depends_on_service_id": dep_sid,
            "depends_on_service_name": dep_svc["name"],
            "criticality": random.choices(DEPENDENCY_CRITICALITIES, weights=[30, 70])[0],
            "protocol": random.choice(PROTOCOLS),
            "health_status": health,
            "latency_ms": latency,
            "last_checked": fake.date_time_between(start_date="-1d", end_date="now").isoformat(),
        })
        dep_id += 1
    return deps


def generate_change_requests(services, n, pending_service_ids):
    """Generate change request records."""
    crs = []
    cr_id = 1
    approver_pool = [fake.name() for _ in range(20)]

    # Ensure every pending service has at least one CR
    for sid in pending_service_ids:
        svc = next(s for s in services if s["id"] == sid)
        status = random.choices(CR_STATUSES, weights=[55, 20, 10, 15])[0]
        num_approvals = random.randint(0, 4)
        approvers = random.sample(approver_pool, min(num_approvals, len(approver_pool)))
        submitted_date = fake.date_between(start_date="-30d", end_date="-3d")
        resolved_date = fake.date_between(start_date=submitted_date, end_date="today") if status != "pending_review" else None
        crs.append({
            "id": cr_id,
            "service_id": sid,
            "cr_number": f"CR-{random.randint(10000, 99999)}",
            "title": f"Deploy {svc['name']} {svc['image_tag']} to {svc['namespace']}",
            "status": status,
            "submitted_by": random.choice(approver_pool),
            "approvers": ";".join(approvers) if approvers else "",
            "num_approvals": len(approvers),
            "submitted_date": submitted_date.isoformat(),
            "resolved_date": resolved_date.isoformat() if resolved_date else "",
            "risk_level": random.choice(["low", "medium", "high"]),
        })
        cr_id += 1

    # Fill remaining CRs for other services
    other_ids = [s["id"] for s in services if s["id"] not in pending_service_ids]
    while len(crs) < n:
        sid = random.choice(other_ids) if other_ids else random.choice(pending_service_ids)
        svc = next(s for s in services if s["id"] == sid)
        status = random.choices(CR_STATUSES, weights=[50, 25, 15, 10])[0]
        num_approvals = random.randint(0, 4)
        approvers = random.sample(approver_pool, min(num_approvals, len(approver_pool)))
        submitted_date = fake.date_between(start_date="-60d", end_date="-3d")
        resolved_date = fake.date_between(start_date=submitted_date, end_date="today") if status != "pending_review" else None
        crs.append({
            "id": cr_id,
            "service_id": sid,
            "cr_number": f"CR-{random.randint(10000, 99999)}",
            "title": f"Deploy {svc['name']} {svc['image_tag']}",
            "status": status,
            "submitted_by": random.choice(approver_pool),
            "approvers": ";".join(approvers) if approvers else "",
            "num_approvals": len(approvers),
            "submitted_date": submitted_date.isoformat(),
            "resolved_date": resolved_date.isoformat() if resolved_date else "",
            "risk_level": random.choice(["low", "medium", "high"]),
        })
        cr_id += 1

    return crs


def create_database(db_path, services, vulns, quotas, deps, crs):
    """Create SQLite database with all tables."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS microservices (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        team TEXT NOT NULL,
        image_registry TEXT NOT NULL,
        image_tag TEXT NOT NULL,
        namespace TEXT NOT NULL,
        priority TEXT NOT NULL,
        last_deployed TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS vulnerability_scans (
        id INTEGER PRIMARY KEY,
        service_id INTEGER NOT NULL,
        cve_id TEXT NOT NULL,
        severity TEXT NOT NULL,
        cvss_score REAL NOT NULL,
        status TEXT NOT NULL,
        package_name TEXT NOT NULL,
        scan_date TEXT NOT NULL,
        image_tag TEXT NOT NULL,
        FOREIGN KEY (service_id) REFERENCES microservices(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS resource_quotas (
        id INTEGER PRIMARY KEY,
        namespace TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        quota_limit REAL NOT NULL,
        current_usage REAL NOT NULL,
        unit TEXT NOT NULL,
        last_updated TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS dependency_map (
        id INTEGER PRIMARY KEY,
        service_id INTEGER NOT NULL,
        depends_on_service_id INTEGER NOT NULL,
        depends_on_service_name TEXT NOT NULL,
        criticality TEXT NOT NULL,
        protocol TEXT NOT NULL,
        health_status TEXT NOT NULL,
        latency_ms REAL NOT NULL,
        last_checked TEXT NOT NULL,
        FOREIGN KEY (service_id) REFERENCES microservices(id),
        FOREIGN KEY (depends_on_service_id) REFERENCES microservices(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS change_requests (
        id INTEGER PRIMARY KEY,
        service_id INTEGER NOT NULL,
        cr_number TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        submitted_by TEXT NOT NULL,
        approvers TEXT NOT NULL,
        num_approvals INTEGER NOT NULL,
        submitted_date TEXT NOT NULL,
        resolved_date TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        FOREIGN KEY (service_id) REFERENCES microservices(id)
    )""")

    for s in services:
        c.execute("INSERT INTO microservices VALUES (?,?,?,?,?,?,?,?)",
                  (s["id"], s["name"], s["team"], s["image_registry"],
                   s["image_tag"], s["namespace"], s["priority"], s["last_deployed"]))

    for v in vulns:
        c.execute("INSERT INTO vulnerability_scans VALUES (?,?,?,?,?,?,?,?,?)",
                  (v["id"], v["service_id"], v["cve_id"], v["severity"],
                   v["cvss_score"], v["status"], v["package_name"],
                   v["scan_date"], v["image_tag"]))

    for q in quotas:
        c.execute("INSERT INTO resource_quotas VALUES (?,?,?,?,?,?,?)",
                  (q["id"], q["namespace"], q["resource_type"],
                   q["quota_limit"], q["current_usage"], q["unit"], q["last_updated"]))

    for d in deps:
        c.execute("INSERT INTO dependency_map VALUES (?,?,?,?,?,?,?,?,?)",
                  (d["id"], d["service_id"], d["depends_on_service_id"],
                   d["depends_on_service_name"], d["criticality"], d["protocol"],
                   d["health_status"], d["latency_ms"], d["last_checked"]))

    for cr in crs:
        c.execute("INSERT INTO change_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (cr["id"], cr["service_id"], cr["cr_number"], cr["title"],
                   cr["status"], cr["submitted_by"], cr["approvers"],
                   cr["num_approvals"], cr["submitted_date"], cr["resolved_date"],
                   cr["risk_level"]))

    conn.commit()
    conn.close()


def create_workspace(workspace, services, pending_services, vulns):
    """Create workspace files: deployment request files + policy/config files."""
    os.makedirs(workspace, exist_ok=True)

    # --- Fixed policy/config files (do not scale) ---

    # 1. deployment_policy.yaml - thresholds for go/no-go
    policy = {
        "vulnerability_policy": {
            "max_critical_open": 0,
            "max_high_open": 2,
            "max_risk_score": 30.0,
            "excluded_statuses": ["mitigated", "false_positive"],
        },
        "resource_policy": {
            "max_utilization_after_deploy": 0.85,
            "required_resource_checks": ["cpu_cores", "memory_gb"],
        },
        "dependency_policy": {
            "critical_must_be_healthy": True,
            "max_degraded_standard_ratio": 0.25,
            "unhealthy_blocks_deploy": True,
        },
        "change_request_policy": {
            "required_status": ["approved"],
            "min_approvals": 2,
        },
        "priority_override": {
            "critical_services_require_zero_high_vulns": True,
        },
    }
    with open(os.path.join(workspace, "deployment_policy.yaml"), "w") as f:
        # Use yaml-like manual writing for determinism
        import yaml
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    # 2. risk_scoring.csv - severity to risk score
    risk_rows = [
        {"severity": "critical", "risk_score": "10.0", "weight": "4.0"},
        {"severity": "high", "risk_score": "5.0", "weight": "2.0"},
        {"severity": "medium", "risk_score": "2.0", "weight": "1.0"},
        {"severity": "low", "risk_score": "0.5", "weight": "0.5"},
    ]
    with open(os.path.join(workspace, "risk_scoring.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["severity", "risk_score", "weight"])
        writer.writeheader()
        writer.writerows(risk_rows)

    # 3. namespace_resource_buffer.json - per-namespace reserved buffer that must
    #    also be subtracted from available capacity before computing utilization
    ns_set = list(sorted(set(s["namespace"] for s in pending_services)))
    ns_buffers = {}
    for ns in ns_set:
        ns_buffers[ns] = {
            "cpu_cores_reserved": round(random.uniform(1.0, 3.0), 1),
            "memory_gb_reserved": round(random.uniform(2.0, 8.0), 1),
        }
    with open(os.path.join(workspace, "namespace_resource_buffer.json"), "w") as f:
        json.dump(ns_buffers, f, indent=2)

    # --- Scaling deployment request files ---
    formats_cycle = [".yaml", ".json", ".csv", ".txt", ".md"]
    for idx, svc in enumerate(pending_services):
        fmt = formats_cycle[idx % len(formats_cycle)]
        filename = f"deploy_request_{svc['name']}{fmt}"

        req_cpu = round(random.uniform(0.5, 6.0), 2)
        req_mem = round(random.uniform(1.0, 16.0), 2)
        req_pods = random.randint(1, 8)
        rollback_plan = random.choice(["blue-green", "canary", "rolling", "immediate"])
        deploy_window = random.choice(["weekday-business", "weekday-offhours", "weekend", "anytime"])
        requester = fake.name()

        content = {
            "service_name": svc["name"],
            "service_id": svc["id"],
            "target_namespace": svc["namespace"],
            "requested_cpu_cores": req_cpu,
            "requested_memory_gb": req_mem,
            "requested_pods": req_pods,
            "image_tag": svc["image_tag"],
            "rollback_strategy": rollback_plan,
            "deployment_window": deploy_window,
            "requested_by": requester,
            "notes": fake.sentence(nb_words=10),
        }

        filepath = os.path.join(workspace, filename)
        if fmt == ".yaml":
            import yaml
            with open(filepath, "w") as f:
                yaml.dump(content, f, default_flow_style=False, sort_keys=False)
        elif fmt == ".json":
            with open(filepath, "w") as f:
                json.dump(content, f, indent=2)
        elif fmt == ".csv":
            with open(filepath, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(content.keys()))
                writer.writeheader()
                writer.writerow(content)
        elif fmt == ".txt":
            with open(filepath, "w") as f:
                f.write("DEPLOYMENT REQUEST FORM\n")
                f.write("=" * 40 + "\n")
                for k, v in content.items():
                    f.write(f"{k}: {v}\n")
        elif fmt == ".md":
            with open(filepath, "w") as f:
                f.write(f"# Deployment Request: {svc['name']}\n\n")
                f.write("| Field | Value |\n|---|---|\n")
                for k, v in content.items():
                    f.write(f"| {k} | {v} |\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n_rows = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]

    # Generate microservices
    services = generate_microservices(n_rows)

    # Select pending deployment services (= num_workspace_files)
    pending_ids = sorted(random.sample([s["id"] for s in services], min(n_files, len(services))))
    pending_services = [s for s in services if s["id"] in pending_ids]

    # Generate vulnerability scans (3x service count for density)
    n_vulns = max(n_rows, len(services) * 3)
    vulns = generate_vulnerability_scans(services, n_vulns)

    # Generate resource quotas
    namespaces_used = list(set(s["namespace"] for s in services))
    quotas = generate_resource_quotas(namespaces_used, n_rows)

    # Generate dependency map
    deps = generate_dependency_map(services, n_rows)

    # Generate change requests
    crs = generate_change_requests(services, n_rows, pending_ids)

    # Create database
    create_database(args.db_path, services, vulns, quotas, deps, crs)

    # Create workspace
    create_workspace(args.workspace, services, pending_services, vulns)

    print(f"Database created at {args.db_path}")
    print(f"  - microservices: {len(services)} rows")
    print(f"  - vulnerability_scans: {len(vulns)} rows")
    print(f"  - resource_quotas: {len(quotas)} rows")
    print(f"  - dependency_map: {len(deps)} rows")
    print(f"  - change_requests: {len(crs)} rows")
    print(f"Workspace created at {args.workspace}")
    print(f"  - {n_files} deployment request files + 3 policy/config files")
    print(f"  - Pending services: {[s['name'] for s in pending_services]}")


if __name__ == "__main__":
    main()
