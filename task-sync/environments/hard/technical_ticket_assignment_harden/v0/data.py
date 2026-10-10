"""
Technical Support Ticket Routing - Data Generation
Generates database and workspace files for the ticket routing task.
"""

import argparse
import json
import os
import random
import sqlite3
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 50,
    "num_workspace_files": 12,
}

# Seed everything
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# Domain constants
PRODUCT_CATEGORIES = ["Networking", "Storage", "Compute", "Security", "Database", "Analytics"]
SEVERITY_LEVELS = ["low", "medium", "high", "critical"]
TEAMS = ["Alpha", "Beta", "Gamma", "Delta"]
SHIFTS = ["morning", "afternoon", "night"]
CERT_LEVELS = {"junior": 1, "senior": 2, "expert": 3}
SUPPORT_TIERS = ["basic", "standard", "premium"]
REFERENCE_DATE = datetime(2025, 6, 1)


def create_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY,
        sku TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        support_tier TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS error_codes (
        error_id TEXT PRIMARY KEY,
        code TEXT UNIQUE NOT NULL,
        product_sku TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT,
        FOREIGN KEY (product_sku) REFERENCES products(sku)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS engineers (
        engineer_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        team TEXT NOT NULL,
        shift TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        max_queue_size INTEGER NOT NULL DEFAULT 5
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS certifications (
        cert_id TEXT PRIMARY KEY,
        engineer_id TEXT NOT NULL,
        product_category TEXT NOT NULL,
        cert_level TEXT NOT NULL,
        cert_level_num INTEGER NOT NULL,
        certified_date TEXT NOT NULL,
        expiry_date TEXT NOT NULL,
        FOREIGN KEY (engineer_id) REFERENCES engineers(engineer_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        priority INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        error_code TEXT,
        customer_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        assigned_to TEXT,
        FOREIGN KEY (error_code) REFERENCES error_codes(code),
        FOREIGN KEY (assigned_to) REFERENCES engineers(engineer_id)
    )""")
    conn.commit()


def generate_products(n):
    products = []
    for i in range(n):
        cat = PRODUCT_CATEGORIES[i % len(PRODUCT_CATEGORIES)]
        tier = SUPPORT_TIERS[i % len(SUPPORT_TIERS)]
        prefix = cat[:3].upper()
        products.append({
            "product_id": f"PROD-{i+1:04d}",
            "sku": f"SKU-{prefix}-{i+1:04d}",
            "name": fake.catch_phrase() + f" {cat} Suite",
            "category": cat,
            "support_tier": tier,
        })
    return products


def generate_error_codes(products, n):
    codes = []
    code_idx = 0
    while len(codes) < n:
        prod = products[len(codes) % len(products)]
        code_idx += 1
        cat_prefix = prod["category"][:3].upper()
        severity = SEVERITY_LEVELS[(code_idx - 1) % len(SEVERITY_LEVELS)]
        codes.append({
            "error_id": f"ERRID-{code_idx:05d}",
            "code": f"ERR-{cat_prefix}-{code_idx:04d}",
            "product_sku": prod["sku"],
            "severity": severity,
            "description": fake.sentence(nb_words=8),
        })
    return codes


def generate_engineers(n):
    engineers = []
    for i in range(n):
        team = TEAMS[i % len(TEAMS)]
        shift = SHIFTS[i % len(SHIFTS)]
        is_active = 1 if (i % 4 != 3) else 0  # 75% active
        max_q = 4 + (i % 5)  # 4..8
        engineers.append({
            "engineer_id": f"ENG-{i+1:04d}",
            "name": fake.name(),
            "email": fake.email(),
            "team": team,
            "shift": shift,
            "is_active": is_active,
            "max_queue_size": max_q,
        })
    return engineers


def generate_certifications(engineers, n):
    certs = []
    cert_idx = 0

    active_morning = [e for e in engineers if e["is_active"] == 1 and e["shift"] == "morning"]
    active_other = [e for e in engineers if e["is_active"] == 1 and e["shift"] != "morning"]
    inactive = [e for e in engineers if e["is_active"] == 0]

    # Guarantee: each category gets >=2 active-morning engineers with expert cert
    for i, eng in enumerate(active_morning):
        primary_cat = PRODUCT_CATEGORIES[i % len(PRODUCT_CATEGORIES)]
        cert_idx += 1
        certs.append({
            "cert_id": f"CERT-{cert_idx:05d}",
            "engineer_id": eng["engineer_id"],
            "product_category": primary_cat,
            "cert_level": "expert",
            "cert_level_num": 3,
            "certified_date": (REFERENCE_DATE - timedelta(days=365)).strftime("%Y-%m-%d"),
            "expiry_date": (REFERENCE_DATE + timedelta(days=180)).strftime("%Y-%m-%d"),
        })
        # secondary cert
        secondary_cat = PRODUCT_CATEGORIES[(i + 1) % len(PRODUCT_CATEGORIES)]
        cert_idx += 1
        lvl = random.choice(["junior", "senior"])
        certs.append({
            "cert_id": f"CERT-{cert_idx:05d}",
            "engineer_id": eng["engineer_id"],
            "product_category": secondary_cat,
            "cert_level": lvl,
            "cert_level_num": CERT_LEVELS[lvl],
            "certified_date": (REFERENCE_DATE - timedelta(days=random.randint(180, 500))).strftime("%Y-%m-%d"),
            "expiry_date": (REFERENCE_DATE + timedelta(days=random.randint(60, 300))).strftime("%Y-%m-%d"),
        })

    # Certs for other active engineers (non-morning)
    for eng in active_other:
        num_certs = random.randint(1, 3)
        cats = random.sample(PRODUCT_CATEGORIES, num_certs)
        for cat in cats:
            cert_idx += 1
            lvl = random.choice(list(CERT_LEVELS.keys()))
            is_valid = random.random() < 0.80
            expiry = (
                (REFERENCE_DATE + timedelta(days=random.randint(30, 365)))
                if is_valid
                else (REFERENCE_DATE - timedelta(days=random.randint(1, 180)))
            )
            certs.append({
                "cert_id": f"CERT-{cert_idx:05d}",
                "engineer_id": eng["engineer_id"],
                "product_category": cat,
                "cert_level": lvl,
                "cert_level_num": CERT_LEVELS[lvl],
                "certified_date": (REFERENCE_DATE - timedelta(days=random.randint(180, 730))).strftime("%Y-%m-%d"),
                "expiry_date": expiry.strftime("%Y-%m-%d"),
            })

    # Expired certs for inactive engineers (noise)
    for eng in inactive:
        cert_idx += 1
        cat = random.choice(PRODUCT_CATEGORIES)
        lvl = random.choice(list(CERT_LEVELS.keys()))
        certs.append({
            "cert_id": f"CERT-{cert_idx:05d}",
            "engineer_id": eng["engineer_id"],
            "product_category": cat,
            "cert_level": lvl,
            "cert_level_num": CERT_LEVELS[lvl],
            "certified_date": (REFERENCE_DATE - timedelta(days=random.randint(365, 730))).strftime("%Y-%m-%d"),
            "expiry_date": (REFERENCE_DATE - timedelta(days=random.randint(1, 365))).strftime("%Y-%m-%d"),
        })

    # Pad to at least n
    all_active = active_morning + active_other
    while len(certs) < n:
        cert_idx += 1
        eng = random.choice(all_active)
        cat = random.choice(PRODUCT_CATEGORIES)
        lvl = random.choice(list(CERT_LEVELS.keys()))
        is_valid = random.random() < 0.75
        expiry = (
            (REFERENCE_DATE + timedelta(days=random.randint(30, 365)))
            if is_valid
            else (REFERENCE_DATE - timedelta(days=random.randint(1, 180)))
        )
        certs.append({
            "cert_id": f"CERT-{cert_idx:05d}",
            "engineer_id": eng["engineer_id"],
            "product_category": cat,
            "cert_level": lvl,
            "cert_level_num": CERT_LEVELS[lvl],
            "certified_date": (REFERENCE_DATE - timedelta(days=random.randint(180, 730))).strftime("%Y-%m-%d"),
            "expiry_date": expiry.strftime("%Y-%m-%d"),
        })

    return certs


def generate_tickets(n, num_pending, error_codes, engineers):
    tickets = []

    # Select distinct error codes for pending tickets
    pending_indices = random.sample(range(len(error_codes)), min(num_pending, len(error_codes)))
    pending_errors = [error_codes[i] for i in pending_indices]

    # Pending tickets
    for i in range(num_pending):
        ec = pending_errors[i]
        priority = random.randint(1, 5)
        created = REFERENCE_DATE - timedelta(hours=random.randint(1, 48))
        tickets.append({
            "ticket_id": f"TKT-{i+1:05d}",
            "title": fake.sentence(nb_words=6).rstrip("."),
            "priority": priority,
            "status": "pending",
            "error_code": ec["code"],
            "customer_id": f"CUST-{random.randint(1, 500):04d}",
            "created_at": created.strftime("%Y-%m-%d %H:%M:%S"),
            "assigned_to": None,
        })

    # Non-pending tickets
    active_engineers = [e for e in engineers if e["is_active"] == 1]
    queue_counts = {e["engineer_id"]: 0 for e in active_engineers}

    for i in range(num_pending, n):
        ec = error_codes[i % len(error_codes)]
        status = random.choice(["in_progress", "in_progress", "resolved", "closed"])
        assigned_to = None

        if status == "in_progress":
            candidates = [
                e for e in active_engineers
                if queue_counts[e["engineer_id"]] < e["max_queue_size"] - 2
            ]
            if candidates:
                eng = random.choice(candidates)
                assigned_to = eng["engineer_id"]
                queue_counts[eng["engineer_id"]] += 1
            else:
                status = "resolved"
                assigned_to = random.choice(active_engineers)["engineer_id"]
        elif status == "resolved":
            assigned_to = random.choice(active_engineers)["engineer_id"]

        created = REFERENCE_DATE - timedelta(hours=random.randint(24, 720))
        tickets.append({
            "ticket_id": f"TKT-{i+1:05d}",
            "title": fake.sentence(nb_words=6).rstrip("."),
            "priority": random.randint(1, 5),
            "status": status,
            "error_code": ec["code"],
            "customer_id": f"CUST-{random.randint(1, 500):04d}",
            "created_at": created.strftime("%Y-%m-%d %H:%M:%S"),
            "assigned_to": assigned_to,
        })

    return tickets, tickets[:num_pending]


def insert_rows(conn, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace generation
# ---------------------------------------------------------------------------

def generate_ticket_files(workspace, pending_tickets):
    """Generate a .txt file per pending ticket with the error code embedded in prose."""
    templates = [
        (
            "Our team has been experiencing persistent issues since {date}. The application "
            "logs consistently show {error_code} appearing at regular intervals, roughly every "
            "{freq} minutes. Users are reporting {symptom}. This is affecting approximately "
            "{num_users} users across our organization and we need urgent resolution.\n\n"
            "Environment: Production\nFirst occurrence: {date}\n"
            "Frequency: Every {freq} minutes\nImpact: {num_users} users affected"
        ),
        (
            "We encountered {error_code} while performing routine operations on {date}. The "
            "error manifests as {symptom}. Our internal monitoring system flagged this as a "
            "recurring issue that has not responded to standard troubleshooting procedures "
            "including service restarts and configuration reviews. Approximately {num_users} "
            "users are affected.\n\nTimeline:\n- {date}: First occurrence detected\n"
            "- Subsequent occurrences: {freq} times per hour\n- Users impacted: {num_users}"
        ),
        (
            "Since {date}, our infrastructure has been logging {error_code} at an alarming "
            "rate. The technical team has attempted basic troubleshooting including service "
            "restarts and configuration reviews but the error persists. The issue correlates "
            "with {symptom}. We require expert assistance to diagnose and resolve this "
            "promptly.\n\nDetails:\n- Error frequency: {freq} per hour\n"
            "- Affected user base: approximately {num_users}\n- Business impact: {impact}"
        ),
        (
            "Reporting an urgent issue: {error_code} has been surfacing in our production "
            "environment since {date}. The problem appears to be causing {symptom}. Our SLA "
            "requires resolution within {sla} hours. Current workarounds including service "
            "restart, configuration rollback, and cache clearing have been ineffective.\n\n"
            "Technical context:\n- Error rate: {freq} occurrences per hour\n"
            "- Affected users: {num_users}\n- Previous similar incident: none on record"
        ),
        (
            "This ticket documents the ongoing occurrence of {error_code} first detected on "
            "{date}. The error is causing {symptom} across our deployment. Diagnostic data "
            "suggests the root cause may be related to a recent infrastructure change. "
            "Immediate investigation is needed as {num_users} end users are experiencing "
            "degraded service.\n\nScope:\n- Error frequency: every {freq} minutes\n"
            "- Business criticality: {impact}"
        ),
    ]
    symptoms = [
        "intermittent connectivity failures",
        "data synchronization delays",
        "authentication timeouts",
        "unexpected service restarts",
        "memory allocation errors",
        "disk I/O bottlenecks",
        "API response degradation",
        "certificate validation failures",
        "query execution timeouts",
        "load balancer health check failures",
        "connection pool exhaustion",
        "DNS resolution failures",
    ]
    impacts = [
        "High - revenue-generating services affected",
        "Critical - customer-facing portal degraded",
        "Moderate - internal tools experiencing slowdowns",
        "Severe - data pipeline processing halted",
    ]

    for idx, ticket in enumerate(pending_tickets):
        template = templates[idx % len(templates)]
        date_str = ticket["created_at"].split(" ")[0]
        content = template.format(
            error_code=ticket["error_code"],
            date=date_str,
            freq=random.randint(5, 60),
            symptom=symptoms[idx % len(symptoms)],
            num_users=random.randint(10, 500),
            impact=impacts[idx % len(impacts)],
            sla=random.choice([4, 8, 12, 24]),
        )
        header = (
            f"Ticket ID: {ticket['ticket_id']}\n"
            f"Submitted: {ticket['created_at']}\n"
            f"Customer: {ticket['customer_id']}\n"
            f"Priority: P{ticket['priority']}\n"
            f"{'=' * 50}\n\n"
        )
        filepath = os.path.join(workspace, f"ticket_{ticket['ticket_id']}.txt")
        with open(filepath, "w") as f:
            f.write(header + content)


def generate_portal_logs(workspace, error_codes, num_logs):
    """Generate portal-log CSV files.  Every error code appears in at least one file."""
    # Assign each error code to exactly one primary log file (round-robin)
    buckets = {i: [] for i in range(num_logs)}
    for idx, ec in enumerate(error_codes):
        buckets[idx % num_logs].append(ec)

    # Sprinkle a few extra duplicates for realism
    for log_idx in range(num_logs):
        extras = random.sample(error_codes, min(3, len(error_codes)))
        buckets[log_idx].extend(extras)

    for log_idx in range(num_logs):
        log_date = REFERENCE_DATE - timedelta(days=log_idx)
        date_str = log_date.strftime("%Y%m%d")
        rows = []
        for ec in buckets[log_idx]:
            for _ in range(random.randint(1, 3)):
                ts = log_date - timedelta(
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59),
                )
                rows.append({
                    "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "error_code": ec["code"],
                    "product_sku": ec["product_sku"],
                    "severity": ec["severity"],
                    "occurrence_count": random.randint(1, 100),
                    "source_ip": fake.ipv4_private(),
                })
        rows.sort(key=lambda r: r["timestamp"])
        filepath = os.path.join(workspace, f"portal_log_{date_str}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp", "error_code", "product_sku",
                    "severity", "occurrence_count", "source_ip",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)


def generate_config_files(workspace):
    """Generate fixed (non-scaling) configuration/policy files."""

    # routing_rules.json
    rules = {
        "severity_to_cert_level": {
            "critical": 3,
            "high": 2,
            "medium": 1,
            "low": 1,
        },
        "processing_order": {
            "primary_sort": "priority",
            "primary_direction": "descending",
            "secondary_sort": "ticket_id",
            "secondary_direction": "ascending",
        },
        "assignment_preference": {
            "metric": "lowest_current_queue_depth",
            "tiebreaker": "lowest_engineer_id",
        },
        "constraints": {
            "engineer_must_be_active": True,
            "engineer_must_match_current_shift": True,
            "certification_must_not_be_expired": True,
            "queue_must_not_exceed_max": True,
        },
        "output_format": {
            "filename": "assignments.csv",
            "columns": [
                "ticket_id",
                "error_code",
                "product_sku",
                "product_category",
                "severity",
                "required_cert_level",
                "assigned_engineer_id",
                "assigned_engineer_name",
            ],
        },
    }
    with open(os.path.join(workspace, "routing_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)

    # shift_schedule.json
    schedule = {
        "current_shift": "morning",
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "shift_definitions": {
            "morning": {"start": "06:00", "end": "14:00"},
            "afternoon": {"start": "14:00", "end": "22:00"},
            "night": {"start": "22:00", "end": "06:00"},
        },
    }
    with open(os.path.join(workspace, "shift_schedule.json"), "w") as f:
        json.dump(schedule, f, indent=2)

    # escalation_policy.md
    policy = (
        "All pending tickets must be assigned to a qualified support engineer. "
        "An engineer is qualified if they hold a valid (non-expired) certification "
        "in the product category associated with the ticket's error code, and their "
        "certification level meets or exceeds the minimum required for the error's "
        "severity as defined in the routing rules configuration.\n\n"
        "Only engineers who are currently active and on the current shift (as specified "
        "in the shift schedule) are eligible for assignment. Certification validity is "
        "evaluated against the reference date in the shift schedule: a certification is "
        "valid only if its expiry date is strictly after that reference date. An "
        "engineer's queue must not be at maximum capacity after the new ticket is "
        "assigned.\n\n"
        "Tickets are processed in descending order of priority, where P5 is the highest "
        "priority and P1 is the lowest. Tickets with the same priority are processed in "
        "ascending order of ticket ID. This ordering matters because each assignment "
        "changes the queue depth for subsequent routing decisions.\n\n"
        "Among all qualified and available engineers for a given ticket, the one with "
        "the lowest current queue depth is selected. If two or more engineers have the "
        "same queue depth, the one with the numerically smallest engineer ID is chosen.\n\n"
        "The final assignments must be saved as a CSV report following the output "
        "format in the routing rules configuration, and each assignment must be "
        "recorded in the ticket system so that the database reflects the new "
        "routing.\n"
    )
    with open(os.path.join(workspace, "escalation_policy.md"), "w") as f:
        f.write(policy)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    create_tables(conn)

    n = SCALE["rows_per_table"]
    num_ws = SCALE["num_workspace_files"]

    # Derived file counts
    num_ticket_files = max(int(num_ws * 2 / 3), 6)
    num_portal_logs = max(num_ws - num_ticket_files, 2)

    # Core data
    products = generate_products(n)
    insert_rows(conn, "products", products)

    error_codes = generate_error_codes(products, n)
    insert_rows(conn, "error_codes", error_codes)

    engineers = generate_engineers(n)
    insert_rows(conn, "engineers", engineers)

    certifications = generate_certifications(engineers, n)
    insert_rows(conn, "certifications", certifications)

    tickets, pending = generate_tickets(n, num_ticket_files, error_codes, engineers)
    insert_rows(conn, "tickets", tickets)

    conn.close()

    # Workspace
    generate_ticket_files(workspace, pending)
    generate_portal_logs(workspace, error_codes, num_portal_logs)
    generate_config_files(workspace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
