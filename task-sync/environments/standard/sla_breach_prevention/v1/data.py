"""Data generation for SLA breach detection task."""

import argparse
import csv
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
import yaml

SCALE = {
    "rows_per_table": 160,
    "num_workspace_files": 16,
}

REFERENCE_DATE = datetime(2026, 4, 20, 9, 0, 0)

PRIORITIES = ["P1", "P2", "P3", "P4"]
STATUSES = ["open", "in_progress", "pending", "resolved", "closed"]
CATEGORIES = ["network", "hardware", "software", "security",
              "database", "cloud", "email", "telephony"]
CUSTOMER_TIERS = ["platinum", "gold", "silver", "bronze"]
SKILL_LEVELS = ["junior", "mid", "senior", "lead"]

DEPARTMENTS = [
    {"dept_id": 1, "dept_name": "Network Operations", "manager_name": "Diana Mitchell"},
    {"dept_id": 2, "dept_name": "Hardware Support", "manager_name": "Robert Chang"},
    {"dept_id": 3, "dept_name": "Software Engineering", "manager_name": "Sarah O'Brien"},
    {"dept_id": 4, "dept_name": "Security Operations", "manager_name": "James Kowalski"},
    {"dept_id": 5, "dept_name": "Database Administration", "manager_name": "Maria Santos"},
    {"dept_id": 6, "dept_name": "Cloud Infrastructure", "manager_name": "Kevin Okafor"},
    {"dept_id": 7, "dept_name": "Email Systems", "manager_name": "Lisa Petrov"},
    {"dept_id": 8, "dept_name": "Telephony Services", "manager_name": "Andrew Nakamura"},
]

SLA_HOURS = {
    "P1": {"platinum": 4, "gold": 6, "silver": 8, "bronze": 12},
    "P2": {"platinum": 12, "gold": 18, "silver": 24, "bronze": 36},
    "P3": {"platinum": 36, "gold": 48, "silver": 72, "bronze": 96},
    "P4": {"platinum": 72, "gold": 96, "silver": 120, "bronze": 168},
}

WARNING_THRESHOLD_PCT = 25

CAT_TO_DEPT = {
    "network": 1, "hardware": 2, "software": 3, "security": 4,
    "database": 5, "cloud": 6, "email": 7, "telephony": 8,
}


def create_database(db_path):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    n_rows = SCALE["rows_per_table"]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ---- schema ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            tier TEXT NOT NULL,
            contract_value REAL NOT NULL,
            industry TEXT NOT NULL,
            contact_email TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS technicians (
            tech_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            skill_level TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            specialization TEXT NOT NULL,
            max_capacity INTEGER NOT NULL,
            hire_date TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sla_deadline TEXT NOT NULL,
            assigned_technician_id INTEGER,
            customer_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            FOREIGN KEY (assigned_technician_id) REFERENCES technicians(tech_id),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assignment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            from_tech_id INTEGER,
            to_tech_id INTEGER NOT NULL,
            assigned_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS escalation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            from_level INTEGER NOT NULL,
            to_level INTEGER NOT NULL,
            escalated_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
        )
    """)

    # ---- customers ----
    industries = ["Finance", "Healthcare", "Technology", "Manufacturing",
                  "Retail", "Education", "Government", "Energy"]
    contract_base = {"platinum": 500000, "gold": 200000,
                     "silver": 100000, "bronze": 50000}
    customers = []
    for i in range(1, n_rows + 1):
        tier = random.choices(CUSTOMER_TIERS, weights=[0.15, 0.25, 0.35, 0.25])[0]
        customers.append((
            i, fake.company(), tier,
            round(contract_base[tier] * (0.8 + random.random() * 0.4), 2),
            random.choice(industries), fake.company_email(),
        ))
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
    customer_tier_map = {c[0]: c[2] for c in customers}

    # ---- technicians ----
    capacity_map = {"junior": 3, "mid": 4, "senior": 5, "lead": 6}
    dept_spec = {1: "network", 2: "hardware", 3: "software", 4: "security",
                 5: "database", 6: "cloud", 7: "email", 8: "telephony"}
    techs = []
    for i in range(1, n_rows + 1):
        dept_id = (i - 1) % len(DEPARTMENTS) + 1
        skill = random.choices(SKILL_LEVELS, weights=[0.25, 0.35, 0.25, 0.15])[0]
        techs.append((
            i, fake.name(), skill, dept_id, dept_spec[dept_id],
            capacity_map[skill],
            fake.date_between(start_date="-10y", end_date="-1y").isoformat(),
        ))
    cur.executemany("INSERT INTO technicians VALUES (?,?,?,?,?,?,?)", techs)

    # ---- tickets + per-ticket assignment_history + escalation_logs ----
    title_templates = [
        "Server {} unreachable", "Application {} crash",
        "Database {} slow queries", "Network {} latency spike",
        "Security {} alert triggered", "Email {} delivery failure",
        "Cloud {} instance down", "VPN {} connection drops",
        "Firewall {} rule conflict", "Storage {} capacity warning",
        "Backup {} job failed", "SSL {} certificate expiry",
        "DNS {} resolution failure", "Load balancer {} misconfigured",
        "API {} timeout errors", "Print server {} offline",
        "Auth {} service down", "Monitoring {} alert storm",
    ]
    reassignment_reasons = [
        "Workload balancing", "Skill mismatch", "Shift change",
        "Escalation requirement", "Customer request",
        "Unavailability", "Priority reassignment",
    ]
    escalation_reasons = [
        "SLA approaching breach", "Customer complaint",
        "System-wide impact", "VIP customer affected",
        "Repeated failure", "Security concern",
        "Management request", "Severity increase",
    ]

    tickets = []
    assignment_records = []
    escalation_records = []

    for i in range(1, n_rows + 1):
        priority = random.choices(PRIORITIES, weights=[0.15, 0.25, 0.35, 0.25])[0]
        customer_id = random.randint(1, n_rows)

        r = random.random()
        if r < 0.25:
            status = "open"
        elif r < 0.45:
            status = "in_progress"
        elif r < 0.60:
            status = "pending"
        elif r < 0.80:
            status = "resolved"
        else:
            status = "closed"

        category = random.choice(CATEGORIES)
        title = random.choice(title_templates).format(fake.bothify("??-###"))

        # creation time — active tickets spread across time ranges
        if status in ("open", "in_progress"):
            bucket = random.choice(["recent", "moderate", "old"])
            if bucket == "recent":
                hours_ago = random.uniform(1, 12)
            elif bucket == "moderate":
                hours_ago = random.uniform(12, 72)
            else:
                hours_ago = random.uniform(72, 240)
        else:
            hours_ago = random.uniform(24, 336)

        created_at = REFERENCE_DATE - timedelta(hours=hours_ago)
        tier = customer_tier_map[customer_id]
        sla_hrs = SLA_HOURS[priority][tier]
        sla_deadline = created_at + timedelta(hours=sla_hrs)

        if status in ("resolved", "closed"):
            updated_at = created_at + timedelta(
                hours=random.uniform(1, sla_hrs * 0.8))
        else:
            updated_at = REFERENCE_DATE - timedelta(
                hours=random.uniform(0, min(hours_ago, 24)))

        target_dept = CAT_TO_DEPT.get(category, random.randint(1, 8))
        dept_techs = [t[0] for t in techs if t[3] == target_dept]
        assigned_tech = (random.choice(dept_techs)
                         if dept_techs else random.randint(1, n_rows))

        description = fake.paragraph(nb_sentences=3)

        tickets.append((
            i, title, priority, status, category,
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            sla_deadline.strftime("%Y-%m-%d %H:%M:%S"),
            assigned_tech, customer_id, description,
        ))

        # ---- assignment history for this ticket ----
        n_reassign = random.choices(
            [0, 1, 2, 3, 4], weights=[0.20, 0.30, 0.25, 0.15, 0.10])[0]
        prev_tech = None
        for j in range(n_reassign + 1):
            if j == 0:
                to_tech = random.randint(1, n_rows)
                reason = "Initial assignment"
            elif j == n_reassign:
                to_tech = assigned_tech
                reason = random.choice(reassignment_reasons)
            else:
                to_tech = random.randint(1, n_rows)
                reason = random.choice(reassignment_reasons)
            assign_time = created_at + timedelta(
                hours=j * random.uniform(0.5, 8))
            assignment_records.append((
                i, prev_tech, to_tech,
                assign_time.strftime("%Y-%m-%d %H:%M:%S"), reason,
            ))
            prev_tech = to_tech

        # ---- escalation logs for this ticket ----
        if status in ("open", "in_progress"):
            n_esc = random.choices(
                [0, 1, 2, 3], weights=[0.20, 0.30, 0.30, 0.20])[0]
        else:
            n_esc = random.choices(
                [0, 1, 2, 3], weights=[0.30, 0.35, 0.25, 0.10])[0]
        for j in range(n_esc):
            esc_time = created_at + timedelta(
                hours=(j + 1) * random.uniform(2, 18))
            resolved = (1 if status in ("resolved", "closed")
                        and j == n_esc - 1 else 0)
            escalation_records.append((
                i, j, j + 1,
                esc_time.strftime("%Y-%m-%d %H:%M:%S"),
                random.choice(escalation_reasons), resolved,
            ))

    # Pad escalation_logs if below n_rows
    tickets_without_esc = [
        t[0] for t in tickets
        if t[0] not in {e[0] for e in escalation_records}
    ]
    pad_idx = 0
    while len(escalation_records) < n_rows and pad_idx < len(tickets_without_esc):
        tid = tickets_without_esc[pad_idx]
        created = tickets[tid - 1][5]  # created_at string
        esc_time = (datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
                    + timedelta(hours=random.uniform(4, 24)))
        escalation_records.append((
            tid, 0, 1,
            esc_time.strftime("%Y-%m-%d %H:%M:%S"),
            random.choice(escalation_reasons), 0,
        ))
        pad_idx += 1

    cur.executemany(
        "INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)", tickets)
    cur.executemany(
        "INSERT INTO assignment_history "
        "(ticket_id, from_tech_id, to_tech_id, assigned_at, reason) "
        "VALUES (?,?,?,?,?)",
        assignment_records)
    cur.executemany(
        "INSERT INTO escalation_logs "
        "(ticket_id, from_level, to_level, escalated_at, reason, resolved) "
        "VALUES (?,?,?,?,?,?)",
        escalation_records)

    conn.commit()
    conn.close()


def create_workspace(workspace, db_path):
    random.seed(42)
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    n_files = SCALE["num_workspace_files"]
    n_impact = n_files // 2
    n_avail = n_files - n_impact

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ---- scalable: ticket impact batch files (JSON) ----
    all_tickets = conn.execute(
        "SELECT ticket_id, priority FROM tickets ORDER BY ticket_id"
    ).fetchall()
    ticket_ids = [t["ticket_id"] for t in all_tickets]
    priority_map = {t["ticket_id"]: t["priority"] for t in all_tickets}

    batch_size = max(1, len(ticket_ids) // n_impact)
    for idx in range(n_impact):
        start = idx * batch_size
        if idx == n_impact - 1:
            batch_ids = ticket_ids[start:]
        else:
            batch_ids = ticket_ids[start:start + batch_size]
        batch = []
        for tid in batch_ids:
            pri = priority_map[tid]
            base_impact = {"P1": 7.0, "P2": 5.5, "P3": 4.0, "P4": 2.5}[pri]
            score = round(
                min(10.0, max(1.0, base_impact + random.uniform(-2.0, 3.0))),
                1)
            affected = (random.randint(5, 500)
                        if pri in ("P1", "P2")
                        else random.randint(1, 100))
            batch.append({
                "ticket_id": tid,
                "business_impact_score": score,
                "affected_users": affected,
                "revenue_impact_per_hour": round(
                    affected * random.uniform(10, 100), 2),
                "customer_notes": fake.sentence(nb_words=12),
            })
        fpath = os.path.join(workspace,
                             f"ticket_impact_batch_{idx + 1}.json")
        with open(fpath, "w") as f:
            json.dump(batch, f, indent=2)

    # ---- scalable: availability report files (CSV) ----
    all_techs = conn.execute(
        "SELECT * FROM technicians ORDER BY tech_id").fetchall()
    tech_ids = [t["tech_id"] for t in all_techs]
    tech_batch = max(1, len(tech_ids) // n_avail)

    for idx in range(n_avail):
        start = idx * tech_batch
        if idx == n_avail - 1:
            batch_ids = tech_ids[start:]
        else:
            batch_ids = tech_ids[start:start + tech_batch]
        fpath = os.path.join(workspace,
                             f"availability_report_{idx + 1}.csv")
        with open(fpath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "tech_id", "name", "date", "available_hours",
                "current_ticket_count", "max_concurrent", "on_call",
                "skill_certifications",
            ])
            for tid in batch_ids:
                tech = conn.execute(
                    "SELECT * FROM technicians WHERE tech_id = ?",
                    (tid,)).fetchone()
                active_cnt = conn.execute(
                    "SELECT COUNT(*) c FROM tickets "
                    "WHERE assigned_technician_id = ? "
                    "AND status IN ('open','in_progress')",
                    (tid,)).fetchone()["c"]
                avail_hrs = round(
                    max(0.0, random.uniform(0, 8) - active_cnt * 0.5), 1)
                on_call = random.choice(["true", "false"])
                certs = tech["specialization"]
                if random.random() > 0.5:
                    extra = random.choice(
                        ["network", "security", "cloud", "database"])
                    if extra != certs:
                        certs += f",{extra}"
                w.writerow([
                    tid, tech["name"],
                    REFERENCE_DATE.strftime("%Y-%m-%d"),
                    avail_hrs, active_cnt, tech["max_capacity"],
                    on_call, certs,
                ])

    # ---- fixed: sla_policy.yaml ----
    sla_policy = {
        "sla_hours": SLA_HOURS,
        "warning_threshold_pct": WARNING_THRESHOLD_PCT,
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(workspace, "sla_policy.yaml"), "w") as f:
        yaml.dump(sla_policy, f, default_flow_style=False, sort_keys=False)

    # ---- fixed: escalation_rules.json ----
    esc_rules = {
        "intervention_threshold": 1.5,
        "escalation_threshold": 2.5,
        "min_available_hours": 4.0,
        "max_reassignment_count": 2,
        "max_escalation_level": 3,
        "reassignment_penalty_rate": 0.15,
        "skill_requirements": {
            "P1": "lead", "P2": "senior", "P3": "mid", "P4": "junior"},
        "skill_level_values": {
            "junior": 1, "mid": 2, "senior": 3, "lead": 4},
        "risk_score_formula": (
            "priority_weight * time_urgency * "
            "(1 + reassignment_penalty_rate * reassignment_count) * "
            "(business_impact_score / 10)"),
        "time_urgency_formula": (
            "max(0.1, min(2.0, 1.0 - hours_remaining / sla_total_hours))"),
    }
    with open(os.path.join(workspace, "escalation_rules.json"), "w") as f:
        json.dump(esc_rules, f, indent=2)

    # ---- fixed: priority_weights.csv ----
    with open(os.path.join(workspace, "priority_weights.csv"),
              "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["priority", "weight"])
        for p, wt in [("P1", "4.0"), ("P2", "3.0"),
                       ("P3", "2.0"), ("P4", "1.0")]:
            w.writerow([p, wt])

    # ---- fixed: department_contacts.md ----
    with open(os.path.join(workspace, "department_contacts.md"), "w") as f:
        f.write("# Department Contacts\n\n")
        f.write("| Dept ID | Department Name | Manager Name |\n")
        f.write("|---------|----------------|---------------|\n")
        for d in DEPARTMENTS:
            f.write(
                f"| {d['dept_id']} | {d['dept_name']} "
                f"| {d['manager_name']} |\n")

    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    create_database(args.db_path)
    create_workspace(args.workspace, args.db_path)


if __name__ == "__main__":
    main()
